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

import audio


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

def _env_bool(name: str, default: bool = False) -> bool:
	raw = os.getenv(name)
	return default if raw is None else raw.lower() in {"1", "true", "yes", "on"}


LOG_LEVEL = os.getenv("BACKEND_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)


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

	try:
		screenshot_b64 = capture_screenshot()
	except ScreenshotError as exc:
		logging.exception("Screenshot capture failed")
		return jsonify({"error": str(exc)}), 500

	forward_payload: Dict[str, Any] = {
		**payload,
		"screenshot": screenshot_b64,
	}
	response = _safe_post(ui_client, "/api/completetask", forward_payload)
	if response is None:
		return jsonify({"status": "queued", "ui_forwarded": False}), 202

	return _forward_response(response)


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
	
	# Forward to agent_s for LLM processing
	forward_payload: Dict[str, Any] = {
		"prompt": payload.get("text", ""),
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


if __name__ == "__main__":
	debug = _env_bool("BACKEND_DEBUG", default=False)
	app.run(host=SERVER_HOST, port=int(SERVER_PORT), debug=debug)