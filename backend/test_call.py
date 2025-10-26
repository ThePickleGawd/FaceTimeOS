"""CLI client for interacting with the audio call server."""
from __future__ import annotations

import argparse
import base64
import logging
import os
import threading
import time
from pathlib import Path

import socketio
from dotenv import load_dotenv, dotenv_values
from pydub import AudioSegment

# Load environment configuration from ../.env
BACKEND_DIR = Path(__file__).resolve().parent
DOTENV_PATH = (BACKEND_DIR / ".." / ".env").resolve()
ENV_VARS = dotenv_values(DOTENV_PATH)
load_dotenv(dotenv_path=DOTENV_PATH)

LOGGER = logging.getLogger(__name__)


def _default_host() -> str:
    host = (
        ENV_VARS.get("CALL_SERVICE_CLIENT_HOST")
        or ENV_VARS.get("CALL_SERVICE_HOST")
        or os.getenv("CALL_SERVICE_CLIENT_HOST")
        or os.getenv("CALL_SERVICE_HOST")
    )
    return host.strip()


def _build_url(host: str, port: int) -> str:
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host
    if host in {"", "0.0.0.0"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _run_send(args: argparse.Namespace, url: str) -> None:
    file_path = args.file.expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    audio_segment = AudioSegment.from_file(file_path)
    audio_segment = audio_segment.set_frame_rate(48000).set_channels(2).set_sample_width(2)

    audio_bytes = audio_segment.raw_data
    if not audio_bytes:
        raise ValueError("Audio file decoded to empty audio stream")

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    ack_event = threading.Event()
    error_holder: dict[str, str | None] = {"message": None}

    sio = socketio.Client(logger=False, engineio_logger=False)

    @sio.event
    def connect():  # pragma: no cover
        LOGGER.info("Connected to %s", url)
        LOGGER.info(f"Sending audio_input event with {len(audio_b64)} bytes (base64)")
        sio.emit("audio_input", {"audio": audio_b64})
        LOGGER.info("audio_input event emitted")

    @sio.on("audio_received")
    def handle_audio_received(_):  # pragma: no cover
        LOGGER.info("Server acknowledged audio input")
        ack_event.set()

    @sio.on("error")
    def handle_error(data):  # pragma: no cover
        message = (data or {}).get("message")
        LOGGER.error("Server error: %s", message or "unknown error")
        error_holder["message"] = message or "Unknown error"
        ack_event.set()

    @sio.event
    def disconnect():  # pragma: no cover
        LOGGER.info("Disconnected from server")
        if not ack_event.is_set():
            LOGGER.warning("Disconnected without receiving acknowledgement")
        ack_event.set()

    LOGGER.info("Sending audio file %s", file_path)
    sio.connect(url, transports=["polling"])  # pragma: no cover

    if not ack_event.wait(timeout=args.timeout):
        LOGGER.warning("Timed out waiting for server acknowledgement")

    if sio.connected:
        sio.disconnect()

    if error_holder["message"]:
        raise RuntimeError(error_holder["message"])


def _run_receive(args: argparse.Namespace, url: str) -> None:
    file_path = args.file.expanduser()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    stop_event = threading.Event()
    audio_buffer = []
    buffer_lock = threading.Lock()
    sio = socketio.Client(logger=False, engineio_logger=False)

    @sio.event
    def connect():  # pragma: no cover
        LOGGER.info("Connected to %s", url)
        if args.start_recording:
            LOGGER.info("Requesting server to start recording")
            sio.emit("start_recording")

    @sio.event
    def disconnect():  # pragma: no cover
        LOGGER.info("Disconnected from server")
        stop_event.set()

    @sio.on("recording_started")
    def handle_recording_started(_data):  # pragma: no cover
        LOGGER.info("Server started recording")

    @sio.on("recording_stopped")
    def handle_recording_stopped(_data):  # pragma: no cover
        LOGGER.info("Server stopped recording")
        stop_event.set()

    @sio.on("recording_error")
    def handle_recording_error(data):  # pragma: no cover
        message = (data or {}).get("message", "Unknown error")
        LOGGER.error("Recording error: %s", message)
        stop_event.set()

    @sio.on("audio_stream")
    def handle_audio_stream(data):  # pragma: no cover
        audio_b64 = (data or {}).get("audio")
        if not audio_b64:
            LOGGER.debug("Received audio_stream event without audio payload")
            return
        audio_bytes = base64.b64decode(audio_b64)
        with buffer_lock:
            audio_buffer.append(audio_bytes)

    LOGGER.info("Collecting streamed audio...")
    sio.connect(url, transports=["polling"])  # pragma: no cover

    try:
        if args.duration:
            deadline = time.time() + args.duration
            while time.time() < deadline and not stop_event.is_set():
                time.sleep(0.1)
            if args.stop_on_exit and sio.connected:
                LOGGER.info("Stopping recording after duration elapses")
                sio.emit("stop_recording")
        else:
            while not stop_event.is_set():
                time.sleep(0.1)
    except KeyboardInterrupt:  # pragma: no cover
        LOGGER.info("Interrupted by user")
        if args.stop_on_exit and sio.connected:
            LOGGER.info("Requesting server to stop recording")
            sio.emit("stop_recording")
    finally:
        stop_event.set()
        if sio.connected:
            sio.disconnect()

    # Convert collected audio to MP3
    LOGGER.info("Converting audio to MP3...")
    with buffer_lock:
        if audio_buffer:
            combined_bytes = b"".join(audio_buffer)
            # Create AudioSegment from raw bytes (16-bit signed, 48kHz, stereo)
            audio_segment = AudioSegment(
                data=combined_bytes,
                sample_width=2,  # 16-bit
                frame_rate=48000,
                channels=2
            )
            # Export as MP3
            audio_segment.export(file_path, format="mp3")
            LOGGER.info("Saved MP3 file to %s", file_path)
        else:
            LOGGER.warning("No audio data received")



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interact with the audio call server")
    host_default = _default_host()
    port_default = int(
        ENV_VARS.get("CALL_SERVICE_PORT")
        or os.getenv("CALL_SERVICE_PORT")
    )

    parser.add_argument("--host", default=host_default, help=f"Server host (default: {host_default})")
    parser.add_argument("--port", type=int, default=port_default, help=f"Server port (default: {port_default})")
    parser.add_argument("--timeout", type=float, default=5.0, help="Seconds to wait for server responses")

    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send", help="Send an audio file to be played on the server output")
    send_parser.add_argument("file", type=Path, help="Path to the audio file to send")

    receive_parser = subparsers.add_parser("receive", help="Receive streamed audio and write it to a file as MP3")
    receive_parser.add_argument("file", type=Path, help="Path where streamed audio should be written (as MP3)")
    receive_parser.add_argument("--duration", type=float, default=None, help="Stop after the given number of seconds")
    receive_parser.add_argument("--no-start", dest="start_recording", action="store_false", help="Do not request recording on connect")
    receive_parser.add_argument("--no-stop", dest="stop_on_exit", action="store_false", help="Do not request stop when exiting")
    receive_parser.set_defaults(start_recording=True, stop_on_exit=True)

    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = _build_parser()
    args = parser.parse_args()

    url = _build_url(args.host, args.port)

    if args.command == "send":
        _run_send(args, url)
    elif args.command == "receive":
        _run_receive(args, url)
    else:  # pragma: no cover
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
