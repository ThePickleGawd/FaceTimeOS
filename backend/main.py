"""HTTP bridge between Agent S and the UI server."""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv


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


if __name__ == "__main__":
	debug = _env_bool("BACKEND_DEBUG", default=False)
	app.run(host=SERVER_HOST, port=int(SERVER_PORT), debug=debug)
