"""Command line client for interacting with the audio microservice."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

import requests

DEFAULT_BASE_URL = os.getenv("AUDIO_SERVICE_URL", "http://127.0.0.1:5001")
DEFAULT_TIMEOUT = float(os.getenv("AUDIO_CLIENT_TIMEOUT", "30"))


class AudioServiceError(RuntimeError):
    """Raised when the audio service responds with an error payload."""


def _normalize_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        raise AudioServiceError("base_url must include http:// or https:// scheme")
    return base


def transcribe(
    base_url: str,
    file_path: Path,
    *,
    language: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Send the local audio file to the service and return the transcript text."""
    normalized_url = _normalize_base_url(base_url)
    if not file_path.exists() or not file_path.is_file():
        raise AudioServiceError(f"Audio file does not exist: {file_path}")

    files = {
        "file": (file_path.name, file_path.open("rb"), "application/octet-stream"),
    }
    data = {"language": language} if language else None

    try:
        response = requests.post(
            f"{normalized_url}/transcribe",
            files=files,
            data=data,
            timeout=timeout,
        )
    finally:
        files["file"][1].close()

    if response.status_code >= 400:
        raise AudioServiceError(
            f"Transcription request failed ({response.status_code}): {response.text.strip()}"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise AudioServiceError("Transcription response did not contain valid JSON") from exc

    transcript = payload.get("text")
    if not transcript:
        raise AudioServiceError("Transcription response missing 'text' field")

    return transcript


def synthesize(
    base_url: str,
    text: str,
    *,
    voice: Optional[str] = None,
    audio_format: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[bytes, str]:
    """Request speech synthesis for text and return the audio bytes and MIME type."""
    normalized_url = _normalize_base_url(base_url)
    stripped_text = text.strip()
    if not stripped_text:
        raise AudioServiceError("Text to synthesize must not be empty")

    payload = {"text": stripped_text}
    if voice:
        payload["voice"] = voice
    if audio_format:
        payload["audio_format"] = audio_format

    response = requests.post(
        f"{normalized_url}/synthesize",
        json=payload,
        timeout=timeout,
    )

    if response.status_code >= 400:
        raise AudioServiceError(
            f"Synthesis request failed ({response.status_code}): {response.text.strip()}"
        )

    content_type = response.headers.get("Content-Type", "audio/mpeg")
    if not response.content:
        raise AudioServiceError("Synthesis response did not return any audio data")

    return response.content, content_type


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI client for the audio microservice")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for the audio service (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    transcribe_parser = subparsers.add_parser("transcribe", help="Transcribe an audio file")
    transcribe_parser.add_argument("file", type=Path, help="Path to the audio file to transcribe")
    transcribe_parser.add_argument("--language", help="Optional language hint for transcription")

    synthesize_parser = subparsers.add_parser("synthesize", help="Synthesize speech from text")
    synthesize_parser.add_argument("text", help="Text to convert to speech")
    synthesize_parser.add_argument(
        "--voice",
        help="Optional voice identifier understood by the backend",
    )
    synthesize_parser.add_argument(
        "--audio-format",
        help="Desired audio format (e.g. mp3, wav, pcm)",
    )
    synthesize_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Where to save the synthesized audio (defaults to stdout if omitted)",
    )

    return parser


def _handle_transcribe(args: argparse.Namespace) -> int:
    transcript = transcribe(
        base_url=args.base_url,
        file_path=args.file,
        language=args.language,
        timeout=args.timeout,
    )
    print(transcript)
    return 0


def _handle_synthesize(args: argparse.Namespace) -> int:
    audio_bytes, content_type = synthesize(
        base_url=args.base_url,
        text=args.text,
        voice=args.voice,
        audio_format=args.audio_format,
        timeout=args.timeout,
    )

    output_path: Optional[Path] = args.output
    if output_path:
        output_path.write_bytes(audio_bytes)
        print(f"Saved audio ({content_type}) to {output_path}")
    else:
        # Write raw audio bytes to stdout buffer for piping to other tools
        sys.stdout.buffer.write(audio_bytes)
        sys.stdout.flush()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "transcribe":
            return _handle_transcribe(args)
        if args.command == "synthesize":
            return _handle_synthesize(args)
        parser.error("Unknown command")
    except AudioServiceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
