"""Flask microservice that exposes fish.audio ASR and TTS endpoints."""
from __future__ import annotations

import io
import logging
import os
from http import HTTPStatus
from typing import Dict
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import BadRequest

from fish_client import FishAudioClient, FishAudioError

DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"

load_dotenv(dotenv_path=DOTENV_PATH)

_AUDIO_FORMAT_CONTENT_TYPES: Dict[str, str] = {
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "wav": "audio/wav",
    "pcm": "audio/L16",
    "ogg": "audio/ogg",
}
_DEFAULT_AUDIO_CONTENT_TYPE = "audio/mpeg"


def create_app() -> Flask:
    """Application factory to create and configure the Flask app."""
    app = Flask(__name__)
    client = FishAudioClient()

    @app.errorhandler(BadRequest)
    def handle_bad_request(error: BadRequest):
        response = {"error": str(error.description or error)}
        return jsonify(response), HTTPStatus.BAD_REQUEST

    @app.errorhandler(FishAudioError)
    def handle_fish_audio_error(error: FishAudioError):
        app.logger.error("fish.audio error: %s", error)
        response = {"error": str(error)}
        return jsonify(response), HTTPStatus.BAD_GATEWAY

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):  # pragma: no cover - defensive
        app.logger.exception("Unexpected error while handling request")
        response = {"error": "Internal server error"}
        return jsonify(response), HTTPStatus.INTERNAL_SERVER_ERROR

    @app.route("/transcribe", methods=["POST"])
    def transcribe() -> Response:
        """Transcribe an uploaded audio file via fish.audio ASR."""
        if "file" not in request.files:
            raise BadRequest("Missing audio file under form field 'file'")

        file_storage = request.files["file"]
        audio_bytes = file_storage.read()
        if not audio_bytes:
            raise BadRequest("Uploaded file is empty")

        language = request.form.get("language")
        transcript = client.transcribe_audio(audio_bytes, language=language)
        return jsonify({"text": transcript}), HTTPStatus.OK

    @app.route("/synthesize", methods=["POST"])
    def synthesize() -> Response:
        """Synthesize speech for the provided text via fish.audio TTS."""
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        if not text or not str(text).strip():
            raise BadRequest("JSON body with non-empty 'text' field is required")

        voice = payload.get("voice")
        audio_format = payload.get("audio_format")

        audio_bytes = client.synthesize_speech(str(text), voice=voice, audio_format=audio_format)

        content_type = _AUDIO_FORMAT_CONTENT_TYPES.get(str(audio_format).lower(), _DEFAULT_AUDIO_CONTENT_TYPE)
        return Response(io.BytesIO(audio_bytes).getvalue(), mimetype=content_type)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    application = create_app()
    load_dotenv(dotenv_path=DOTENV_PATH)
    host = os.getenv("AUDIO_SERVICE_HOST")
    port = int(os.getenv("AUDIO_SERVICE_PORT"))
    application.run(host=host, port=port)
