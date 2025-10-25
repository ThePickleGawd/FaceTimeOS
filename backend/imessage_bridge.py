#!/usr/bin/env python3
"""
Continuously poll the local iMessage database for incoming messages and forward
the text to the Agent-S Flask server. Optionally limit forwarding to a specific
contact.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv


APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"
PICTURES_DIR = Path.home() / "Pictures"
IMESSAGE_COMMAND = "imessage"
DEFAULT_CONTACT = None
DEFAULT_INTERVAL = 5.0
DEFAULT_LOG_LEVEL = "INFO"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

BACKEND_TIMEOUT = 30

SERVER_HOST = os.environ["SERVER_HOST"]
SERVER_PORT = os.environ["SERVER_PORT"]
IMESSAGE_BRIDGE_HOST = os.environ["IMESSAGE_BRIDGE_HOST"]
IMESSAGE_BRIDGE_PORT = int(os.environ["IMESSAGE_BRIDGE_PORT"])
BACKEND_BASE_URL = os.getenv(
    "BACKEND_BASE_URL",
    f"http://{SERVER_HOST}:{SERVER_PORT}",
)

logger = logging.getLogger(__name__)
app = Flask(__name__)


class IMessageSendError(RuntimeError):
    """Raised when an outbound iMessage cannot be delivered."""


def _ensure_in_pictures(path: Path) -> Path:
    """Ensure the attachment resides in the Pictures folder, moving if necessary."""
    source = Path(path).expanduser()
    if not source.exists():
        raise ValueError(f"attachment not found: {source}")

    try:
        PICTURES_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.exception("Failed to ensure Pictures directory exists at %s", PICTURES_DIR)
        raise IMessageSendError("Unable to prepare the Pictures directory.") from exc

    try:
        source_resolved = source.resolve()
    except OSError:
        source_resolved = source

    try:
        pictures_resolved = PICTURES_DIR.resolve()
    except OSError:
        pictures_resolved = PICTURES_DIR

    if source_resolved.parent == pictures_resolved:
        return source_resolved

    destination = pictures_resolved / source_resolved.name
    if destination.exists():
        destination = pictures_resolved / f"{source_resolved.stem}_{uuid.uuid4().hex}{source_resolved.suffix}"

    try:
        moved_path = Path(shutil.move(str(source_resolved), str(destination)))
    except OSError as exc:
        logger.exception("Failed to move attachment %s into %s", source_resolved, pictures_resolved)
        raise IMessageSendError("Unable to move attachment into the Pictures folder.") from exc

    return moved_path.resolve()


def send_imessage(
    target: str,
    text: Optional[str] = None,
    attachments: Optional[Iterable[Path | str]] = None,
) -> None:
    """Send an iMessage to a phone number, email, or chat identifier via the CLI."""

    if not isinstance(target, str) or not target.strip():
        raise ValueError("target is required")
    target_handle = target.strip()

    if text is not None and not isinstance(text, str):
        raise ValueError("text must be a string")

    message_body = text or ""
    if isinstance(message_body, str) and not message_body.strip():
        message_body = ""

    attachment_paths: list[Path] = []
    if attachments:
        for raw_attachment in attachments:
            if not isinstance(raw_attachment, (str, Path)):
                raise ValueError("attachments must be filesystem paths")
            attachment_paths.append(_ensure_in_pictures(Path(raw_attachment)))

    if not message_body and attachment_paths:
        message_body = "image"

    if not message_body and not attachment_paths:
        raise ValueError("either text or attachments must be provided")

    imessage_cli = shutil.which(IMESSAGE_COMMAND)
    if not imessage_cli:
        raise IMessageSendError(
            "imessage CLI not found. Install it with `brew install imessage-ruby`."
        )

    command = [
        imessage_cli,
        "--text",
        message_body,
        "--contacts",
        target_handle,
    ]

    for attachment_path in attachment_paths:
        command.extend(["--attachment", str(attachment_path)])

    logger.info(
        "Sending iMessage via CLI to %s with %d attachment(s)",
        target_handle,
        len(attachment_paths),
    )

    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        logger.exception("imessage CLI missing while sending to %s", target_handle)
        raise IMessageSendError(
            "imessage CLI not found. Install it with `brew install imessage-ruby`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        logger.exception("imessage CLI failed while sending to %s", target_handle)
        raise IMessageSendError("imessage CLI failed to send the message.") from exc
    else:
        logger.info("Successfully sent iMessage to %s", target_handle)


@dataclass
class IncomingMessage:
    rowid: int
    text: str
    received_at: datetime
    display_name: str
    phone_number: str
    conversation: str
    is_group: bool


def apple_time_to_datetime(raw_value: Optional[int]) -> datetime:
    """Convert Apple's Core Data timestamp to a timezone-aware datetime."""
    if raw_value is None:
        return datetime.now(timezone.utc)
    seconds = raw_value / 1_000_000_000 if raw_value > 1_000_000_000 else raw_value
    return APPLE_EPOCH + timedelta(seconds=seconds)


def open_chat_db() -> Optional[sqlite3.Connection]:
    """Open the Messages chat database in read-only mode."""
    if not CHAT_DB_PATH.exists():
        logger.error("Messages database not found at %s", CHAT_DB_PATH)
        return None
    try:
        return sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        logger.exception("Unable to open Messages database.")
        return None


class IMessagesPoller:
    """Poll the Messages database for new inbound messages."""

    def __init__(self, contact_name: Optional[str], interval: float) -> None:
        self.contact_name = contact_name
        self.interval = interval
        self._last_rowid = self._latest_rowid_for_contact()

    def _contact_filter_clause(self) -> tuple[str, tuple]:
        if not self.contact_name:
            return "", ()
        return (
            """
            AND (
                chat.display_name = ?
                OR chat.guid = ?
                OR COALESCE(handle.id, '') = ?
            )
            """,
            (self.contact_name, self.contact_name, self.contact_name),
        )

    def _latest_rowid_for_contact(self) -> int:
        connection = open_chat_db()
        if connection is None:
            return 0
        filter_clause, params = self._contact_filter_clause()
        with closing(connection) as conn:
            cursor = conn.execute(
                f"""
                SELECT COALESCE(MAX(message.ROWID), 0)
                FROM message
                JOIN chat_message_join cmj ON cmj.message_id = message.ROWID
                JOIN chat ON chat.ROWID = cmj.chat_id
                LEFT JOIN handle ON handle.ROWID = message.handle_id
                WHERE message.is_from_me = 0
                {filter_clause}
                """,
                params,
            )
            row = cursor.fetchone()
        return int(row[0]) if row and row[0] else 0

    def _fetch_new_messages(self) -> Iterable[IncomingMessage]:
        connection = open_chat_db()
        if connection is None:
            return []

        try:
            with closing(connection) as conn:
                conn.row_factory = sqlite3.Row
                filter_clause, params = self._contact_filter_clause()
                cursor = conn.execute(
                    f"""
                    SELECT DISTINCT
                        message.ROWID AS rowid,
                        COALESCE(message.text, '') AS text,
                        message.date AS message_date,
                        COALESCE(chat.display_name, '') AS display_name,
                        COALESCE(handle.id, '') AS phone_number,
                        COALESCE(chat.display_name, handle.id, chat.guid, 'Unknown') AS conversation,
                        (SELECT COUNT(*) FROM chat_handle_join chj WHERE chj.chat_id = chat.ROWID) > 1 AS is_group
                    FROM message
                    JOIN chat_message_join cmj ON cmj.message_id = message.ROWID
                    JOIN chat ON chat.ROWID = cmj.chat_id
                    LEFT JOIN handle ON handle.ROWID = message.handle_id
                    WHERE message.is_from_me = 0
                    AND message.ROWID > ?
                    {filter_clause}
                    ORDER BY message.ROWID ASC
                    """,
                    (self._last_rowid, *params),
                )
                rows = cursor.fetchall()
        except sqlite3.Error:
            logger.exception("Failed to read from Messages database.")
            return []

        messages = []
        for row in rows:
            rowid = int(row["rowid"]) 
            text = row["text"] or ""
            received_at = apple_time_to_datetime(row["message_date"])
            display_name = row["display_name"] or ""
            phone_number = row["phone_number"] or ""
            conversation = row["conversation"] or "Unknown"
            is_group = bool(row["is_group"]) if "is_group" in row.keys() else False
            messages.append(
                IncomingMessage(
                    rowid=rowid,
                    text=text,
                    received_at=received_at,
                    display_name=display_name,
                    phone_number=phone_number,
                    conversation=conversation,
                    is_group=is_group,
                )
            )
        return messages

    def run_forever(self, handler: Callable[[IncomingMessage], None]) -> None:
        logger.info(
            "Starting iMessage polling for %s at rowid %s",
            self.contact_name or "all contacts",
            self._last_rowid,
        )
        while True:
            for message in self._fetch_new_messages():
                self._last_rowid = max(self._last_rowid, message.rowid)
                handler(message)
            time.sleep(self.interval)


class BackendClient:
    """HTTP client for delivering iMessage payloads to the backend server."""

    def __init__(self, base_url: str, session: Optional[requests.Session] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def deliver_message(self, payload: Dict[str, Any]) -> None:
        try:
            response = self.session.post(
                f"{self.base_url}/api/new_imessage",
                json=payload,
                timeout=BACKEND_TIMEOUT,
            )
            response.raise_for_status()
            logger.info("Delivered message %s to backend.", payload.get("rowid"))
        except requests.RequestException:
            logger.exception("Failed to deliver message to backend.")


@dataclass
class BridgeConfig:
    backend_base_url: str
    contact_filter: Optional[str]
    poll_interval: float
    listen_host: str
    listen_port: int
    log_level: str


bridge_config: Optional[BridgeConfig] = None
backend_client: Optional[BackendClient] = None
poller_thread: Optional[threading.Thread] = None


def _make_message_handler(config: BridgeConfig, client: BackendClient) -> Callable[[IncomingMessage], None]:
    def handle_message(message: IncomingMessage) -> None:
        if message.is_group:
            group_name = message.display_name or message.conversation
            sender = message.phone_number or "Unknown"
            contact_label = f"{group_name} — {sender}"
        else:
            contact_label = message.display_name or message.phone_number or message.conversation

        source = config.contact_filter or contact_label
        if not message.text:
            logger.info("Ignoring empty message from %s.", source)
            return

        logger.info(
            "Received message from %s at %s: %s",
            source,
            message.received_at.isoformat(),
            message.text,
        )
        client.deliver_message(
            {
                "rowid": message.rowid,
                "text": message.text,
                "received_at": message.received_at.isoformat(),
                "display_name": message.display_name,
                "phone_number": message.phone_number,
                "conversation": message.conversation,
                "is_group": message.is_group,
                "contact_label": contact_label,
                "source": source,
            }
        )

    return handle_message


def _run_poller_loop(config: BridgeConfig, client: BackendClient) -> None:
    poller = IMessagesPoller(config.contact_filter, config.poll_interval)
    handler = _make_message_handler(config, client)
    poller.run_forever(handler)


def _configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.setLevel(numeric_level)


def _normalize_attachments(raw: Optional[list]) -> Optional[list[str]]:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("attachments must be a list")
    normalized: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("attachments must contain non-empty paths")
        normalized.append(str(Path(item.strip().strip("\"'" )).expanduser()))
    return normalized


@app.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"status": "ok"}), 200


@app.route("/api/send_imessage", methods=["POST"])
def api_send_imessage() -> Any:
    payload = request.get_json(silent=True) or {}
    target = payload.get("target")
    text = payload.get("text")
    attachments = payload.get("attachments")
    logger.info("Send iMessage request for target=%s", target)

    if not isinstance(target, str) or not target.strip():
        return jsonify({"error": "target is required"}), 400
    if text is not None and not isinstance(text, str):
        return jsonify({"error": "text must be a string"}), 400

    try:
        file_list = _normalize_attachments(attachments)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    message_text = text
    if isinstance(message_text, str) and not message_text.strip():
        message_text = None
    if message_text is None and not (file_list or []):
        return jsonify({"error": "text or attachments must be provided"}), 400

    try:
        send_imessage(target.strip(), message_text, file_list)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except IMessageSendError as exc:
        logger.error("Failed to send outbound iMessage: %s", exc)
        return jsonify({"status": "failed", "error": str(exc)}), 500

    return jsonify({"status": "sent"}), 200


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the iMessage bridge HTTP service.")
    parser.add_argument(
        "--backend-base-url",
        default=BACKEND_BASE_URL,
        help="Base URL for the backend main.py service (default: %(default)s).",
    )
    parser.add_argument(
        "--contact",
        default=DEFAULT_CONTACT,
        help=(
            "Display name, GUID, or handle of the iMessage contact to monitor. "
            "Leave unset to forward messages from any contact."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Polling interval in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--listen-host",
        default=IMESSAGE_BRIDGE_HOST,
        help="Host interface for the bridge HTTP server (default: %(default)s).",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=IMESSAGE_BRIDGE_PORT,
        help="Port for the bridge HTTP server (default: %(default)s).",
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        help="Logging level (default: %(default)s).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    config = BridgeConfig(
        backend_base_url=args.backend_base_url.rstrip("/"),
        contact_filter=args.contact,
        poll_interval=args.interval,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        log_level=args.log_level,
    )

    global bridge_config
    global backend_client
    global poller_thread

    bridge_config = config
    backend_client = BackendClient(config.backend_base_url)

    poller_thread = threading.Thread(
        target=_run_poller_loop,
        args=(config, backend_client),
        name="imessage-poller",
        daemon=True,
    )
    poller_thread.start()

    app.config["BRIDGE_CONFIG"] = config
    app.config["BACKEND_CLIENT"] = backend_client

    app.run(host=config.listen_host, port=config.listen_port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
