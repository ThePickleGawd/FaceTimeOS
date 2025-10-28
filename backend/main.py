"""HTTP bridge between Agent S and the UI server."""

from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import requests
from flask import Flask, Response, jsonify, request
from dotenv import load_dotenv
import socketio

import audio


# Global flag to track audio playback state
_audio_playing = False

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.lower() in {"1", "true", "yes", "on"}


LOG_LEVEL = os.getenv("BACKEND_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = Flask(__name__)

# Socket.IO client for connecting to call.py service
sio = socketio.Client(logger=True, engineio_logger=False)

# Call service configuration
CALL_SERVICE_HOST = os.getenv("CALL_SERVICE_HOST", "localhost")
CALL_SERVICE_PORT = os.getenv("CALL_SERVICE_PORT", "5002")
CALL_SERVICE_URL = f"http://{CALL_SERVICE_HOST}:{CALL_SERVICE_PORT}"

# Audio format configuration (must mirror backend/call.py defaults)
AUDIO_SAMPLE_RATE = int(os.getenv("CALL_AUDIO_SAMPLE_RATE", "48000"))
AUDIO_CHANNELS = int(os.getenv("CALL_AUDIO_CHANNELS", "2"))
AUDIO_SAMPLE_WIDTH = 2  # bytes (int16 PCM)


def _pcm_to_wav_bytes(pcm_data: bytes) -> bytes:
    """Wrap raw PCM int16 audio data into a WAV container."""
    if not pcm_data:
        raise ValueError("PCM data must not be empty when converting to WAV")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(AUDIO_CHANNELS)
        wav_file.setsampwidth(AUDIO_SAMPLE_WIDTH)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        wav_file.writeframes(pcm_data)

    return buffer.getvalue()


class CallManager:
    """Manages WebSocket connection and audio output to call.py service."""

    def __init__(self):
        self.connected = False
        self.call_active = False
        self.playback_in_progress = False

    def connect_to_call_service(self):
        """Establish WebSocket connection to call.py service."""
        if not self.connected:
            try:
                logging.info(f"Connecting to call service at {CALL_SERVICE_URL}")
                sio.connect(CALL_SERVICE_URL, namespaces=["/"])
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
            sio.emit("start_recording")
            self.call_active = True
            logging.info("Call started, recording initiated")
            return True
        return False

    def end_call(self):
        """End the FaceTime call session."""
        if self.connected and self.call_active:
            # Stop recording
            sio.emit("stop_recording")
            self.call_active = False
            logging.info("Call ended, recording stopped")
            # Keep connection alive for potential future calls
            return True
        return False

    def send_audio_to_output(self, audio_bytes: bytes):
        """Send audio to be played through the FaceTime output device."""
        if not self.connected:
            logging.error("Not connected to call service, cannot send audio")
            return False

        if not self.call_active:
            logging.warning("No active call, cannot send audio")
            return False

        try:
            # Encode audio as base64 for transmission
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            sio.emit("audio_input", {"audio": audio_b64})
            self.playback_in_progress = True
            logging.debug(f"Sent {len(audio_bytes)} bytes of audio to FaceTime output")
            return True
        except Exception as e:
            logging.error(f"Failed to send audio: {e}")
            return False


# Initialize call manager
call_manager = CallManager()


# Socket.IO event handlers
@sio.on("connect")
def on_connect():
    logging.info("Connected to call service via WebSocket")
    call_manager.connected = True


@sio.on("disconnect")
def on_disconnect():
    logging.info("Disconnected from call service")
    call_manager.connected = False
    call_manager.call_active = False


# Audio streaming buffer for accumulating chunks
current_utterance_chunks = []
utterance_start_time = None


@sio.on("utterance_start")
def on_utterance_start(data):
    """Handle start of user utterance."""
    global current_utterance_chunks, utterance_start_time
    current_utterance_chunks = []
    utterance_start_time = data.get("timestamp", time.time())
    logging.info("🎤 UTTERANCE START - Beginning audio stream from call.py")


@sio.on("audio_chunk")
def on_audio_chunk(data):
    """Handle incoming audio chunk during utterance."""
    global current_utterance_chunks
    try:
        audio_b64 = data.get("audio")
        if not audio_b64:
            return

        # Decode and store chunk
        audio_bytes = base64.b64decode(audio_b64)
        current_utterance_chunks.append(audio_bytes)
        # Log first few chunks, then every 10th chunk to avoid spam
        if (
            len(current_utterance_chunks) <= 5
            or len(current_utterance_chunks) % 10 == 0
        ):
            logging.info(
                f"📦 Audio chunk #{len(current_utterance_chunks)}: {len(audio_bytes)} bytes"
            )
    except Exception as e:
        logging.error(f"Error processing audio chunk: {e}")


@sio.on("utterance_end")
def on_utterance_end(data):
    """Handle end of user utterance - process complete audio."""
    global current_utterance_chunks, utterance_start_time
    try:
        duration = data.get("duration", 0)
        total_chunks = data.get("total_chunks", len(current_utterance_chunks))

        if not current_utterance_chunks:
            logging.warning("No audio chunks received for utterance")
            return

        # Combine all chunks into single audio buffer (raw PCM)
        pcm_bytes = b"".join(current_utterance_chunks)
        logging.info(
            f"🏁 UTTERANCE END - Received {len(pcm_bytes)} bytes of PCM from {len(current_utterance_chunks)} chunks, {duration:.2f}s duration"
        )

        # Convert to WAV container for downstream services
        wav_bytes = _pcm_to_wav_bytes(pcm_bytes)
        logging.info(f"🎧 Converted PCM to WAV ({len(wav_bytes)} bytes)")

        # Clear buffer
        current_utterance_chunks = []
        utterance_start_time = None

        # Transcribe the complete utterance
        try:
            transcript = audio.transcribe_audio_bytes(wav_bytes)
            logging.info(f"User said: {transcript}")

            if transcript.strip():
                # Forward transcript to Agent-S for processing
                agent_payload = {
                    "prompt": transcript,
                    "metadata": {
                        "source": "facetime_call",
                        "call_active": call_manager.call_active,
                        "audio_length_bytes": len(wav_bytes),
                        "duration_seconds": duration,
                        "audio_format": "wav",
                    },
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
                                response_audio = audio.synthesize_speech_from_text(
                                    response_text
                                )
                                call_manager.send_audio_to_output(response_audio)
                                logging.info(
                                    f"Sent {len(response_audio)} bytes of synthesized audio to FaceTime"
                                )
                            except Exception as e:
                                logging.error(f"Failed to synthesize speech: {e}")
                    else:
                        # Fallback response if Agent-S is unavailable
                        logging.warning("Agent-S unavailable, using fallback response")
                        fallback_text = "I understand. Let me process that for you."

                        try:
                            fallback_audio = audio.synthesize_speech_from_text(
                                fallback_text
                            )
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
        logging.error(f"Error handling utterance end: {e}", exc_info=True)


@sio.on("utterance_cancelled")
def on_utterance_cancelled(data):
    """Handle cancelled utterance (e.g., too short)."""
    global current_utterance_chunks, utterance_start_time
    reason = data.get("reason", "unknown")
    duration = data.get("duration", 0)
    logging.info(
        f"❌ UTTERANCE CANCELLED - Reason: {reason}, Duration: {duration:.2f}s"
    )
    current_utterance_chunks = []
    utterance_start_time = None


@sio.on("playback_interrupted")
def on_playback_interrupted(data):
    """Handle notification that playback was interrupted by user speech."""
    logging.info("Playback interrupted by user speech")


@sio.on("recording_started")
def on_recording_started(data):
    logging.info("Recording started confirmation received")


@sio.on("recording_stopped")
def on_recording_stopped(data):
    logging.info("Recording stopped confirmation received")


@sio.on("error")
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


HTTP_TIMEOUT = float(os.getenv("BACKEND_HTTP_TIMEOUT", "60"))
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
imessage_bridge_client = RemoteClient(
    base_url=IMESSAGE_BRIDGE_BASE_URL, timeout=HTTP_TIMEOUT
)


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
            logging.warning(
                "Expected JSON but got invalid payload from %s", remote_response.url
            )
            body = {"raw": remote_response.text}
        return jsonify(body), remote_response.status_code

    return (
        remote_response.text,
        remote_response.status_code,
        {
            "Content-Type": content_type or "text/plain",
        },
    )


def _safe_post(
    client: RemoteClient, path: str, payload: Dict[str, Any]
) -> Optional[requests.Response]:
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


def _synthesize_speech_payload(
    text: str,
    *,
    voice: Optional[str] = None,
    audio_format: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Synthesize speech and return audio bytes with best-effort content type."""
    normalized_voice = (
        voice.strip() if isinstance(voice, str) and voice.strip() else None
    )
    normalized_format = (
        audio_format.strip()
        if isinstance(audio_format, str) and audio_format.strip()
        else None
    )

    audio_bytes = audio.synthesize_speech_from_text(
        str(text),
        voice=normalized_voice,
        audio_format=normalized_format,
    )

    content_type_key = normalized_format.lower() if normalized_format else ""
    content_type = audio.AUDIO_FORMAT_CONTENT_TYPES.get(
        content_type_key, audio.DEFAULT_AUDIO_CONTENT_TYPE
    )
    return audio_bytes, content_type


def _play_audio_bytes(
    audio_bytes: bytes,
    *,
    audio_format: Optional[str] = None,
    output_device: Optional[str] = None,
) -> None:
    """Play synthesized audio through the requested output device if available."""
    global _audio_playing

    if not audio_bytes:
        logging.debug("No audio bytes provided for playback")
        return

    try:
        import sounddevice as sd  # type: ignore
        import soundfile as sf  # type: ignore
    except (
        Exception
    ) as exc:  # pragma: no cover - defensive: runtime environment specific
        logging.error("Audio playback libraries unavailable: %s", exc)
        return

    # Stop any currently playing audio to prevent queueing
    if _audio_playing:
        try:
            sd.stop()
            logging.info("Interrupted previous audio playback for new prompt")
        except Exception as exc:
            logging.debug("Failed to stop previous audio: %s", exc)

    device_name = (
        output_device
        or os.getenv("VOICE_SUMMARY_OUTPUT_DEVICE")
        or os.getenv("CURRENT_ACTION_AUDIO_DEVICE")
        or os.getenv("AUDIO_OUTPUT_DEVICE")
    )

    device_index: Optional[int] = None
    if device_name:
        try:
            devices = sd.query_devices()
        except Exception as exc:  # pragma: no cover - defensive
            logging.error("Unable to query audio devices: %s", exc)
        else:
            lowered = device_name.lower()
            for idx, device in enumerate(devices):
                if device.get("max_output_channels", 0) <= 0:
                    continue
                if lowered in device.get("name", "").lower():
                    device_index = idx
                    break
            if device_index is None:
                logging.warning(
                    "Requested audio output device '%s' not found, using system default",
                    device_name,
                )

    data: Optional[Any] = None
    sample_rate: Optional[int] = None

    try:
        with sf.SoundFile(io.BytesIO(audio_bytes)) as sound_file:
            sample_rate = int(sound_file.samplerate)
            data = sound_file.read(dtype="float32")
    except Exception as exc:
        logging.debug("Primary audio decode failed (%s); attempting fallback", exc)
        if not audio_format or audio_format.lower() != "mp3":
            logging.error("Unable to decode audio for playback: %s", exc)
            return

        try:
            from pydub import AudioSegment
            import numpy as np
        except Exception as inner_exc:  # pragma: no cover - defensive
            logging.error("MP3 playback fallback unavailable: %s", inner_exc)
            return

        segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        sample_rate = int(segment.frame_rate)
        samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
        max_val = float(1 << (segment.sample_width * 8 - 1))
        if max_val:
            samples /= max_val
        if segment.channels > 1:
            data = samples.reshape((-1, segment.channels))
        else:
            data = samples

    if data is None or sample_rate is None:
        logging.error("Decoded audio data unavailable for playback")
        return

    try:
        sd.play(data, sample_rate, device=device_index)
        sd.wait()
    except Exception as exc:  # pragma: no cover - runtime specific
        logging.error("Audio playback failed: %s", exc)


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
        response = _safe_post(
            imessage_bridge_client, "/api/send_imessage", forward_payload
        )
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
    for _, v in payload.items():
        if isinstance(v, str) and v.strip().lower() == "stopping":
            # Stop the agent
            _proxy_command("/api/stop")
            break

    text = str(payload.get("voice_summary", "") or "").strip()

    # voice = "e58b0d7efca34eb38d5c4985e378abcb"  # fish.audio uses its built-in default voice when reference_id is unset
    voice = "b545c585f631496c914815291da4e893"  # woman voice
    audio_format = "mp3"  # fish.audio TTSRequest default format

    if text:
        try:
            audio_bytes, _ = _synthesize_speech_payload(
                text, voice=voice, audio_format=audio_format
            )
            _play_audio_bytes(audio_bytes, audio_format=audio_format)
        except (audio.FishAudioError, ValueError) as exc:
            logging.error("Failed to synthesize voice notification: %s", exc)
            return

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
                return (
                    jsonify({"error": "attachments must contain non-empty paths"}),
                    400,
                )
            file_list.append(str(Path(item.strip().strip("\"'")).expanduser()))

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
        return (
            jsonify({"error": "Request body must contain audio bytes"}),
            HTTPStatus.BAD_REQUEST,
        )

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
        return (
            jsonify({"error": "JSON body with 'text' field is required"}),
            HTTPStatus.BAD_REQUEST,
        )

    voice = payload.get("voice")
    audio_format = payload.get("audio_format")

    try:
        audio_bytes, content_type = _synthesize_speech_payload(
            text, voice=voice, audio_format=audio_format
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

            return (
                jsonify(
                    {
                        "status": "success",
                        "message": "Call session started",
                        "call_active": True,
                        "connected_to_call_service": call_manager.connected,
                    }
                ),
                HTTPStatus.OK,
            )
        else:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Failed to start call session",
                        "call_active": False,
                    }
                ),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    except Exception as e:
        logging.error(f"Error starting call session: {e}")
        return (
            jsonify({"status": "error", "message": str(e), "call_active": False}),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@app.route("/api/call_ended", methods=["POST"])
def call_ended() -> Response:
    """Handle notification that the FaceTime call has ended."""
    payload = request.get_json(silent=True) or {}
    logging.info(f"Received call_ended notification: {payload}")

    try:
        # End the call session
        success = call_manager.end_call()

        if success:
            return (
                jsonify(
                    {
                        "status": "success",
                        "message": "Call session ended",
                        "call_active": False,
                    }
                ),
                HTTPStatus.OK,
            )
        else:
            return (
                jsonify(
                    {
                        "status": "info",
                        "message": "No active call to end",
                        "call_active": False,
                    }
                ),
                HTTPStatus.OK,
            )

    except Exception as e:
        logging.error(f"Error ending call session: {e}")
        return (
            jsonify({"status": "error", "message": str(e)}),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@app.route("/api/call_status", methods=["GET"])
def call_status() -> Response:
    """Get the current status of the call session."""
    return (
        jsonify(
            {
                "connected_to_service": call_manager.connected,
                "call_active": call_manager.call_active,
                "service_url": CALL_SERVICE_URL,
            }
        ),
        HTTPStatus.OK,
    )


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
                return (
                    jsonify({"error": f"Invalid base64 audio data: {e}"}),
                    HTTPStatus.BAD_REQUEST,
                )
        else:
            return jsonify({"error": "No audio data provided"}), HTTPStatus.BAD_REQUEST

    if not call_manager.call_active:
        return (
            jsonify({"status": "error", "message": "No active call session"}),
            HTTPStatus.BAD_REQUEST,
        )

    try:
        call_manager.send_audio_to_output(audio_bytes)
        return (
            jsonify({"status": "success", "bytes_sent": len(audio_bytes)}),
            HTTPStatus.OK,
        )
    except Exception as e:
        logging.error(f"Error sending audio to call: {e}")
        return (
            jsonify({"status": "error", "message": str(e)}),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


if __name__ == "__main__":
    debug = _env_bool("BACKEND_DEBUG", default=False)
    app.run(host=SERVER_HOST, port=int(SERVER_PORT), debug=debug)
