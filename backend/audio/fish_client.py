"""Client wrapper around the fish.audio SDK for ASR and TTS operations."""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from fish_audio_sdk import ASRRequest, Session, TTSRequest  # type: ignore


class FishAudioError(RuntimeError):
    """Raised when the fish.audio SDK returns an error or unexpected payload."""


class FishAudioClient:
    """Lightweight fish.audio client with convenience helpers for ASR and TTS."""

    def __init__(self, api_key: Optional[str] = None, session_factory: Optional[Callable[[], Session]] = None) -> None:
        self._api_key = api_key or os.getenv("FISH_API_KEY")
        if not self._api_key:
            raise FishAudioError(
                "FISH_API_KEY is not set. Provide it via environment variable or pass it explicitly."
            )

        self._session_factory = session_factory or (lambda: Session(self._api_key))
        self._logger = logging.getLogger(__name__)

    def _build_session(self) -> Session:
        try:
            return self._session_factory()
        except Exception as exc:  # pragma: no cover - defensive: SDK specifics may vary
            self._logger.exception("Unable to initialize fish.audio session")
            raise FishAudioError("Failed to initialize fish.audio session") from exc

    def transcribe_audio(self, audio_bytes: bytes, *, language: Optional[str] = None) -> str:
        """Send raw audio bytes to the fish.audio ASR endpoint and return transcript."""
        if not audio_bytes:
            raise FishAudioError("audio_bytes must not be empty")

        session = self._build_session()
        try:
            request = ASRRequest(audio=audio_bytes, language=language)
            response = session.asr(request)
        except Exception as exc:  # pragma: no cover - delegate SDK errors
            self._logger.exception("fish.audio ASR request failed")
            raise FishAudioError("fish.audio ASR request failed") from exc

        # Response has .text attribute directly
        transcript = getattr(response, "text", None)
        if not transcript:
            self._logger.error("fish.audio ASR response missing text field: %s", response)
            raise FishAudioError("fish.audio ASR response did not contain transcript text")

        return transcript

    def synthesize_speech(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        audio_format: Optional[str] = None,
    ) -> bytes:
        """Generate speech audio for the provided text using fish.audio TTS."""
        stripped_text = text.strip()
        if not stripped_text:
            raise FishAudioError("text must not be empty")

        session = self._build_session()
        try:
            request = TTSRequest(text=stripped_text, reference_id=voice, format=audio_format)
            chunks = session.tts(request)
        except Exception as exc:  # pragma: no cover - delegate SDK errors
            self._logger.exception("fish.audio TTS request failed")
            raise FishAudioError("fish.audio TTS request failed") from exc

        audio_bytes = bytearray()
        for chunk in chunks:
            if chunk:  # Skip None/empty chunks
                audio_bytes.extend(chunk)

        if not audio_bytes:
            self._logger.error("fish.audio TTS response returned no audio data")
            raise FishAudioError("fish.audio TTS response returned no audio data")

        return bytes(audio_bytes)
