#!/usr/bin/env python3
"""Utility script to play audio through the call service REST API."""

from __future__ import annotations

import argparse
import base64
import logging
import os
from pathlib import Path
import sys

import requests
from dotenv import load_dotenv
from pydub import AudioSegment

# Load environment variables
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=DOTENV_PATH)

# Audio configuration (must match call.py settings)
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2

# Call service configuration
CALL_SERVICE_HOST = os.getenv("CALL_SERVICE_HOST", "127.0.0.1")
CALL_SERVICE_PORT = int(os.getenv("CALL_SERVICE_PORT", "5002"))
CALL_SERVICE_URL = f"http://{CALL_SERVICE_HOST}:{CALL_SERVICE_PORT}/audio_input"

# Setup logger
logger = logging.getLogger(__name__)


def _load_audio_bytes(path: Path) -> bytes:
    """Load and convert audio file to raw PCM bytes matching AudioManager config."""
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    # Load audio file using pydub (supports MP3, WAV, OGG, etc.)
    try:
        audio = AudioSegment.from_file(str(path))
    except Exception as exc:
        raise ValueError(f"Failed to load audio file {path}: {exc}") from exc
    
    # Convert to target format: 48kHz stereo, 16-bit PCM
    audio = audio.set_frame_rate(DEFAULT_SAMPLE_RATE)
    audio = audio.set_channels(DEFAULT_CHANNELS)
    audio = audio.set_sample_width(2)  # 2 bytes = 16-bit
    
    # Export as raw PCM bytes
    return audio.raw_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Play audio files (MP3, WAV, OGG, etc.) via call service REST API"
        )
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Path to an audio file (MP3, WAV, OGG, etc.) - will be converted to 48kHz stereo PCM",
    )
    parser.add_argument(
        "--base64",
        help="Base64-encoded 16-bit PCM audio matching 48kHz stereo configuration",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )

    if not args.file and not args.base64:
        parser.error("Provide either --file or --base64 audio input")

    if args.file and args.base64:
        parser.error("Choose either --file or --base64, not both")

    if args.file:
        audio_bytes = _load_audio_bytes(args.file)
    else:
        try:
            audio_bytes = base64.b64decode(args.base64)
        except Exception as exc:
            raise SystemExit(f"Failed to decode base64 audio: {exc}") from exc

    # Encode audio as base64
    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
    
    # Send to call service via REST API
    try:
        logger.info(f"Sending {len(audio_bytes)} bytes to call service at {CALL_SERVICE_URL}")
        response = requests.post(
            CALL_SERVICE_URL,
            json={'audio': audio_b64},
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Audio sent successfully: {response.json()}")
        else:
            logger.error(f"Failed to send audio: {response.status_code} - {response.text}")
            sys.exit(1)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to call service: {e}")
        logger.error(f"Make sure the call service is running at {CALL_SERVICE_URL}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)


if __name__ == "__main__":
    main()
