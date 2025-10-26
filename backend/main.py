"""HTTP bridge between Agent S and the UI server."""

from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import requests
from flask import Flask, Response, jsonify, request
from dotenv import load_dotenv
import socketio

import audio


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

def _env_bool(name: str, default: bool = False) -> bool:
	raw = os.getenv(name)
	return default if raw is None else raw.lower() in {"1", "true", "yes", "on"}


LOG_LEVEL = os.getenv("BACKEND_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)

# Socket.IO client for connecting to call.py service
sio = socketio.Client(logger=True, engineio_logger=False)

# Call service configuration
CALL_SERVICE_HOST = os.getenv("CALL_SERVICE_HOST", "localhost")
CALL_SERVICE_PORT = os.getenv("CALL_SERVICE_PORT", "5002")
CALL_SERVICE_URL = f"http://{CALL_SERVICE_HOST}:{CALL_SERVICE_PORT}"


class CallManager:
	"""Manages WebSocket connection and audio streaming with call.py service."""
	
	def __init__(self):
		self.connected = False
		self.call_active = False
		
	def connect_to_call_service(self):
		"""Establish WebSocket connection to call.py service."""
		if not self.connected:
			try:
				logging.info(f"Connecting to call service at {CALL_SERVICE_URL}")
				sio.connect(CALL_SERVICE_URL, namespaces=['/'])
				self.connected = True
				logging.info("Connected to call service successfully")
			except Exception as e:
				logging.error(f"Failed to connect to call service: {e}")
				raise
	
	def disconnect_from_call_service(self):
		"""Disconnect from call.py service."""
		if self.connected:
			try:
				sio.disconnect()
				self.connected = False
				self.call_active = False
				logging.info("Disconnected from call service")
			except Exception as e:
				logging.error(f"Error disconnecting from call service: {e}")
	
	def start_call(self):
		"""Start a FaceTime call session."""
		if not self.connected:
			self.connect_to_call_service()
		
		if self.connected:
			# Start recording from the virtual audio device
			sio.emit('start_recording')
			self.call_active = True
			logging.info("Call started, recording initiated")
			return True
		return False
	
	def end_call(self):
		"""End the FaceTime call session."""
		if self.connected and self.call_active:
			# Stop recording
			sio.emit('stop_recording')
			self.call_active = False
			logging.info("Call ended, recording stopped")
			# Keep connection alive for potential future calls
			return True
		return False
	
	def send_audio_to_output(self, audio_bytes: bytes):
		"""Send audio to be played through the output device."""
		if self.connected:
			# Encode audio as base64 for transmission
			audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
			sio.emit('audio_input', {'audio': audio_b64})
			logging.debug(f"Sent {len(audio_bytes)} bytes of audio to output")
		else:
			logging.error("Not connected to call service, cannot send audio")


# Initialize call manager
call_manager = CallManager()


# Socket.IO event handlers
@sio.on('connect')
def on_connect():
	logging.info("Connected to call service via WebSocket")
	call_manager.connected = True


@sio.on('disconnect')
def on_disconnect():
	logging.info("Disconnected from call service")
	call_manager.connected = False
	call_manager.call_active = False


@sio.on('audio_stream')
def on_audio_stream(data):
	"""Handle incoming audio from the user through the call."""
	try:
		# Decode base64 audio
		audio_b64 = data.get('audio')
		if audio_b64:
			audio_bytes = base64.b64decode(audio_b64)
			logging.debug(f"Received {len(audio_bytes)} bytes of audio from user")
			
			# Transcribe the audio
			try:
				transcript = audio.transcribe_audio_bytes(audio_bytes)
				logging.info(f"User said: {transcript}")
				
				if transcript.strip():
					# Forward transcript to Agent-S for processing
					agent_payload = {
						"prompt": transcript,
						"metadata": {
							"source": "facetime_call",
							"call_active": call_manager.call_active,
							"audio_length_bytes": len(audio_bytes)
						}
					}
					
					# Send to Agent-S and get response
					try:
						response = _safe_post(agent_s_client, "/api/chat", agent_payload)
						
						if response and response.status_code == 200:
							result = response.json()
							response_text = result.get("response", "")
							
							if response_text:
								logging.info(f"Agent-S response: {response_text[:100]}...")
								
								# Convert response to speech and send back through call
								try:
									response_audio = audio.synthesize_speech_from_text(response_text)
									call_manager.send_audio_to_output(response_audio)
									logging.debug(f"Sent {len(response_audio)} bytes of synthesized audio to call")
								except Exception as e:
									logging.error(f"Failed to synthesize speech: {e}")
						else:
							# Fallback response if Agent-S is unavailable
							logging.warning("Agent-S unavailable, using fallback response")
							fallback_text = "I understand. Let me process that for you."
							
							try:
								fallback_audio = audio.synthesize_speech_from_text(fallback_text)
								call_manager.send_audio_to_output(fallback_audio)
							except Exception as e:
								logging.error(f"Failed to synthesize fallback speech: {e}")
								
					except Exception as e:
						logging.error(f"Error communicating with Agent-S: {e}")
						
			except audio.FishAudioError as e:
				logging.error(f"Failed to transcribe audio: {e}")
				# Audio might be too short or corrupted, skip processing
			except Exception as e:
				logging.error(f"Unexpected error during transcription: {e}")
				
	except Exception as e:
		logging.error(f"Error handling audio stream: {e}")


@sio.on('recording_started')
def on_recording_started(data):
	logging.info("Recording started confirmation received")


@sio.on('recording_stopped')
def on_recording_stopped(data):
	logging.info("Recording stopped confirmation received")


@sio.on('error')
def on_error(data):
	logging.error(f"Error from call service: {data}")


@dataclass
class RemoteClient:
	"""HTTP helper wrapping requests with shared configuration."""

	base_url: str
	timeout: float

	def _full_url(self, path: str) -> str:
		if not path.startswith("/"):
			raise ValueError("path must start with '/'")
		return f"{self.base_url.rstrip('/')}{path}"

	def post_json(self, path: str, payload: Dict[str, Any]) -> requests.Response:
		url = self._full_url(path)
		logging.debug("POST %s", url)
		return requests.post(url, timeout=self.timeout, json=payload)

	def get(self, path: str) -> requests.Response:
		url = self._full_url(path)
		logging.debug("GET %s", url)
		return requests.get(url, timeout=self.timeout)


HTTP_TIMEOUT = float(os.getenv("BACKEND_HTTP_TIMEOUT", "10"))
AGENT_HOST = os.environ["AGENT_HOST"]
AGENT_PORT = os.environ["AGENT_PORT"]
UI_HOST = os.environ["UI_HOST"]
UI_PORT = os.environ["UI_PORT"]
IMESSAGE_BRIDGE_HOST = os.environ["IMESSAGE_BRIDGE_HOST"]
IMESSAGE_BRIDGE_PORT = os.environ["IMESSAGE_BRIDGE_PORT"]
SERVER_HOST = os.environ["SERVER_HOST"]
SERVER_PORT = os.environ["SERVER_PORT"]
AGENT_S_BASE_URL = os.getenv(
    "AGENT_S_BASE_URL",
    f"http://{AGENT_HOST}:{AGENT_PORT}",
)
UI_SERVER_BASE_URL = os.getenv(
    "UI_SERVER_BASE_URL",
    f"http://{UI_HOST}:{UI_PORT}",
)
IMESSAGE_BRIDGE_BASE_URL = os.getenv(
    "IMESSAGE_BRIDGE_BASE_URL",
    f"http://{IMESSAGE_BRIDGE_HOST}:{IMESSAGE_BRIDGE_PORT}",
)

agent_s_client = RemoteClient(base_url=AGENT_S_BASE_URL, timeout=HTTP_TIMEOUT)
ui_client = RemoteClient(base_url=UI_SERVER_BASE_URL, timeout=HTTP_TIMEOUT)
imessage_bridge_client = RemoteClient(base_url=IMESSAGE_BRIDGE_BASE_URL, timeout=HTTP_TIMEOUT)


class ScreenshotError(RuntimeError):
	pass


_last_requester_phone: Optional[str] = None


def capture_screenshot() -> str:
	"""Capture the primary display and return it base64 encoded."""

	temp_dir = Path(tempfile.gettempdir())
	temp_path = temp_dir / f"agent_s_{uuid4().hex}.png"
	try:
		subprocess.run(["screencapture", "-x", str(temp_path)], check=True)
		encoded = base64.b64encode(temp_path.read_bytes()).decode("ascii")
		return encoded
	except (subprocess.CalledProcessError, FileNotFoundError) as exc:
		raise ScreenshotError("Failed to capture screenshot") from exc
	finally:
		try:
			temp_path.unlink(missing_ok=True)
		except OSError:
			logging.warning("Could not delete temporary screenshot %s", temp_path)


def _forward_response(remote_response: Optional[requests.Response]):
	if remote_response is None:
		return jsonify({"status": "forward_failed"}), 502

	content_type = (remote_response.headers.get("Content-Type") or "").lower()
	if "application/json" in content_type:
		try:
			body = remote_response.json()
		except ValueError:
			logging.warning("Expected JSON but got invalid payload from %s", remote_response.url)
			body = {"raw": remote_response.text}
		return jsonify(body), remote_response.status_code

	return remote_response.text, remote_response.status_code, {
		"Content-Type": content_type or "text/plain",
	}


def _safe_post(client: RemoteClient, path: str, payload: Dict[str, Any]) -> Optional[requests.Response]:
	try:
		return client.post_json(path, payload)
	except requests.RequestException as exc:
		logging.error("POST %s failed: %s", path, exc, exc_info=True)
		return None


def _safe_get(client: RemoteClient, path: str) -> Optional[requests.Response]:
	try:
		return client.get(path)
	except requests.RequestException as exc:
		logging.error("GET %s failed: %s", path, exc, exc_info=True)
		return None


@app.route("/api/completetask", methods=["POST"])
def complete_task():
	payload = request.get_json(silent=True) or {}
	logging.info("Received complete task payload: %s", payload)

	phone_number = _last_requester_phone
	if not phone_number:
		logging.warning("No phone number available for task completion notification")
		return jsonify({"error": "phone_number unavailable"}), 400
	phone_number = phone_number.strip()

	try:
		screenshot_b64 = capture_screenshot()
	except ScreenshotError as exc:
		logging.exception("Screenshot capture failed")
		return jsonify({"error": str(exc)}), 500

	action_text = payload.get("action")
	if action_text is not None and not isinstance(action_text, str):
		action_text = str(action_text)

	status = payload.get("status")
	message_parts = []
	if isinstance(status, str) and status.strip():
		message_parts.append(f"Task {status.strip()}")
	if action_text and action_text.strip():
		message_parts.append(action_text.strip())
	message_text = "\n".join(message_parts) if message_parts else "Task update"

	temp_dir = Path(tempfile.gettempdir())
	attachment_path = temp_dir / f"agent_s_task_{uuid4().hex}.png"
	try:
		attachment_path.write_bytes(base64.b64decode(screenshot_b64))
	except (ValueError, OSError) as exc: 
		return jsonify({"error": f"Unable to prepare screenshot: {exc}"}), 500

	try:
		forward_payload = {
			"target": phone_number,
			"text": message_text,
			"attachments": [str(attachment_path)],
		}
		response = _safe_post(imessage_bridge_client, "/api/send_imessage", forward_payload)
		if response is None:
			return jsonify({"status": "failed", "bridge_forwarded": False}), 502
		return _forward_response(response)
	finally:
		try:
			attachment_path.unlink(missing_ok=True)
		except OSError:
			logging.warning("Could not delete temporary attachment %s", attachment_path)


@app.route("/api/currentaction", methods=["POST"])
def current_action():
	payload = request.get_json(silent=True) or {}
	logging.info("Current action update: %s", payload)

	response = _safe_post(ui_client, "/api/currentaction", payload)
	if response is None:
		return jsonify({"status": "queued", "ui_forwarded": False}), 202

	return _forward_response(response)


@app.route("/api/chat", methods=["POST"])
def chat():
	payload = request.get_json(silent=True) or {}
	logging.info("UI chat payload: %s", payload)

	response = _safe_post(agent_s_client, "/api/chat", payload)
	if response is None:
		return jsonify({"status": "queued", "agent_forwarded": False}), 202

	return _forward_response(response)


@app.route("/api/send_imessage", methods=["POST"])
def send_imessage_endpoint() -> Any:
	payload = request.get_json(silent=True) or {}
	target = payload.get("target")
	text = payload.get("text")
	attachments = payload.get("attachments")
	logging.info("Send iMessage request for target=%s", target)

	if not isinstance(target, str) or not target.strip():
		return jsonify({"error": "target is required"}), 400
	if text is not None and not isinstance(text, str):
		return jsonify({"error": "text must be a string"}), 400
	if attachments is not None and not isinstance(attachments, list):
		return jsonify({"error": "attachments must be a list"}), 400

	file_list: Optional[list[str]] = None
	if attachments:
		file_list = []
		for item in attachments:
			if not isinstance(item, str) or not item.strip():
				return jsonify({"error": "attachments must contain non-empty paths"}), 400
			file_list.append(str(Path(item.strip().strip('"\'')).expanduser()))

	if text is not None and not text.strip():
		text = None
	if text is None and not file_list:
		return jsonify({"error": "text or attachments must be provided"}), 400

	forward_payload: Dict[str, Any] = {
		"target": target.strip(),
		"text": text,
		"attachments": file_list,
	}
	response = _safe_post(imessage_bridge_client, "/api/send_imessage", forward_payload)
	if response is None:
		return jsonify({"status": "failed", "bridge_forwarded": False}), 502

	return _forward_response(response)


@app.route("/api/new_imessage", methods=["POST"])
def new_imessage() -> Any:
	payload = request.get_json(silent=True) or {}
	logging.info("New iMessage payload: %s", payload)

	phone_number = payload.get("phone_number")
	if isinstance(phone_number, str) and phone_number.strip():
		global _last_requester_phone
		_last_requester_phone = phone_number.strip()

	message_text = payload.get("text")
	if message_text is None:
		message_text = ""
	elif not isinstance(message_text, str):
		message_text = str(message_text)

	if phone_number and isinstance(phone_number, str) and phone_number.strip():
		prompt_body = message_text.strip()
		if prompt_body:
			prompt = f"Message from {phone_number.strip()}:\n{prompt_body}"
		else:
			prompt = f"Message from {phone_number.strip()}."
	else:
		prompt = message_text

	# Forward to agent_s for LLM processing
	forward_payload: Dict[str, Any] = {
		"prompt": prompt,
		"metadata": {k: v for k, v in payload.items() if k != "text"},
	}
	response = _safe_post(agent_s_client, "/api/chat", forward_payload)
	if response is None:
		return jsonify({"status": "queued", "agent_forwarded": False}), 202
	return _forward_response(response)


def _proxy_command(path: str):
	response = _safe_get(agent_s_client, path)
	if response is None:
		return jsonify({"status": "failed", "agent_forwarded": False}), 502

	return _forward_response(response)


@app.route("/api/stop", methods=["GET"])
def stop():
	logging.info("Received stop command from UI")
	return _proxy_command("/api/stop")


@app.route("/api/pause", methods=["GET"])
def pause():
	logging.info("Received pause command from UI")
	return _proxy_command("/api/pause")


@app.route("/api/resume", methods=["GET"])
def resume():
	logging.info("Received resume command from UI")
	return _proxy_command("/api/resume")


@app.route("/api/audio/transcribe", methods=["POST"])
def transcribe() -> Response:
	"""Transcribe raw audio bytes sent in the request body via fish.audio ASR."""
	audio_bytes = request.get_data(cache=False)
	if not audio_bytes:
		return jsonify({"error": "Request body must contain audio bytes"}), HTTPStatus.BAD_REQUEST

	language = request.args.get("language")
	
	try:
		transcript = audio.transcribe_audio_bytes(audio_bytes, language=language)
		return jsonify({"text": transcript}), HTTPStatus.OK
	except audio.FishAudioError as exc:
		logging.error("fish.audio error: %s", exc)
		return jsonify({"error": str(exc)}), HTTPStatus.BAD_GATEWAY
	except ValueError as exc:
		return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST


@app.route("/api/audio/synthesize", methods=["POST"])
def synthesize() -> Response:
	"""Synthesize speech for the provided text via fish.audio TTS."""
	payload = request.get_json(silent=True) or {}
	text = payload.get("text")
	
	if not text:
		return jsonify({"error": "JSON body with 'text' field is required"}), HTTPStatus.BAD_REQUEST

	voice = payload.get("voice")
	audio_format = payload.get("audio_format")

	try:
		audio_bytes = audio.synthesize_speech_from_text(str(text), voice=voice, audio_format=audio_format)
		content_type = audio.AUDIO_FORMAT_CONTENT_TYPES.get(
			str(audio_format).lower() if audio_format else "",
			audio.DEFAULT_AUDIO_CONTENT_TYPE
		)
		return Response(io.BytesIO(audio_bytes).getvalue(), mimetype=content_type)
	except audio.FishAudioError as exc:
		logging.error("fish.audio error: %s", exc)
		return jsonify({"error": str(exc)}), HTTPStatus.BAD_GATEWAY
	except ValueError as exc:
		return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST


@app.route("/api/call_started", methods=["POST"])
def call_started() -> Response:
	"""Handle notification from Agent-S that a FaceTime call has been initiated."""
	payload = request.get_json(silent=True) or {}
	logging.info(f"Received call_started notification from Agent-S: {payload}")
	
	# Extract call metadata if provided
	number = payload.get("number")
	
	try:
		# Start the call session with the call.py service
		success = call_manager.start_call()
		
		if success:
			
			return jsonify({
				"status": "success",
				"message": "Call session started",
				"call_active": True,
				"connected_to_call_service": call_manager.connected
			}), HTTPStatus.OK
		else:
			return jsonify({
				"status": "error",
				"message": "Failed to start call session",
				"call_active": False
			}), HTTPStatus.INTERNAL_SERVER_ERROR
			
	except Exception as e:
		logging.error(f"Error starting call session: {e}")
		return jsonify({
			"status": "error",
			"message": str(e),
			"call_active": False
		}), HTTPStatus.INTERNAL_SERVER_ERROR


@app.route("/api/call_ended", methods=["POST"])
def call_ended() -> Response:
	"""Handle notification that the FaceTime call has ended."""
	payload = request.get_json(silent=True) or {}
	logging.info(f"Received call_ended notification: {payload}")
	
	try:
		# End the call session
		success = call_manager.end_call()
		
		if success:
			return jsonify({
				"status": "success",
				"message": "Call session ended",
				"call_active": False
			}), HTTPStatus.OK
		else:
			return jsonify({
				"status": "info",
				"message": "No active call to end",
				"call_active": False
			}), HTTPStatus.OK
			
	except Exception as e:
		logging.error(f"Error ending call session: {e}")
		return jsonify({
			"status": "error",
			"message": str(e)
		}), HTTPStatus.INTERNAL_SERVER_ERROR


@app.route("/api/call_status", methods=["GET"])
def call_status() -> Response:
	"""Get the current status of the call session."""
	return jsonify({
		"connected_to_service": call_manager.connected,
		"call_active": call_manager.call_active,
		"service_url": CALL_SERVICE_URL
	}), HTTPStatus.OK


@app.route("/api/send_audio_to_call", methods=["POST"])
def send_audio_to_call() -> Response:
	"""Send audio to be played through the call output."""
	# Get raw audio bytes from request body
	audio_bytes = request.get_data(cache=False)
	
	if not audio_bytes:
		# Try to get from JSON payload with base64 encoding
		payload = request.get_json(silent=True) or {}
		audio_b64 = payload.get("audio")
		if audio_b64:
			try:
				audio_bytes = base64.b64decode(audio_b64)
			except Exception as e:
				return jsonify({"error": f"Invalid base64 audio data: {e}"}), HTTPStatus.BAD_REQUEST
		else:
			return jsonify({"error": "No audio data provided"}), HTTPStatus.BAD_REQUEST
	
	if not call_manager.call_active:
		return jsonify({
			"status": "error",
			"message": "No active call session"
		}), HTTPStatus.BAD_REQUEST
	
	try:
		call_manager.send_audio_to_output(audio_bytes)
		return jsonify({
			"status": "success",
			"bytes_sent": len(audio_bytes)
		}), HTTPStatus.OK
	except Exception as e:
		logging.error(f"Error sending audio to call: {e}")
		return jsonify({
			"status": "error",
			"message": str(e)
		}), HTTPStatus.INTERNAL_SERVER_ERROR


if __name__ == "__main__":
	debug = _env_bool("BACKEND_DEBUG", default=False)
	app.run(host=SERVER_HOST, port=int(SERVER_PORT), debug=debug)
