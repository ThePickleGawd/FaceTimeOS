"""Tests for the audio microservice Flask application."""
from __future__ import annotations

import io
from typing import Any

import pytest

import main


class _StubFishAudioClient:
    """Stubbed fish.audio client returning canned responses for tests."""

    def __init__(self, transcript: str = "stub transcript", audio_payload: bytes | None = None) -> None:
        self.transcript = transcript
        self.audio_payload = audio_payload or b"fake-bytes"

    def transcribe_audio(self, audio_bytes: bytes, *, language: str | None = None) -> str:
        assert audio_bytes, "transcribe_audio should receive audio bytes"
        return self.transcript

    def synthesize_speech(self, text: str, *, voice: str | None = None, audio_format: str | None = None) -> bytes:
        assert text, "synthesize_speech should receive text"
        return self.audio_payload


@pytest.fixture(name="client")
def flask_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Provide a Flask test client with a stubbed FishAudioClient."""

    stub = _StubFishAudioClient()
    monkeypatch.setattr(main, "FishAudioClient", lambda: stub)
    app = main.create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_transcribe_success(client: Any) -> None:
    response = client.post(
        "/transcribe",
        data={"file": (io.BytesIO(b"audio-bytes"), "sample.wav"), "language": "en"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body == {"text": "stub transcript"}


def test_transcribe_missing_file_is_400(client: Any) -> None:
    response = client.post("/transcribe")

    assert response.status_code == 400
    assert response.get_json()["error"]


def test_synthesize_success(client: Any) -> None:
    response = client.post("/synthesize", json={"text": "Hello", "audio_format": "mp3"})

    assert response.status_code == 200
    assert response.data == b"fake-bytes"
    assert response.mimetype == "audio/mpeg"


def test_synthesize_missing_text_is_400(client: Any) -> None:
    response = client.post("/synthesize", json={})

    assert response.status_code == 400
    assert response.get_json()["error"]
