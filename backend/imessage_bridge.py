#!/usr/bin/env python3
"""
Continuously poll the local iMessage database for incoming messages and forward
the text to the Agent-S Flask server. Optionally limit forwarding to a specific
contact.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests


APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"
DEFAULT_CONTACT = None
DEFAULT_HOST = "http://127.0.0.1"
DEFAULT_PORT = 5001
DEFAULT_INTERVAL = 5.0

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    rowid: int
    text: str
    received_at: datetime
    conversation: str


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
                        COALESCE(chat.display_name, handle.id, chat.guid, 'Unknown') AS conversation
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
            conversation = row["conversation"] or "Unknown"
            messages.append(
                IncomingMessage(
                    rowid=rowid,
                    text=text,
                    received_at=received_at,
                    conversation=conversation,
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


class AgentSClient:
    """Lightweight client for sending prompts to the Agent-S server."""

    def __init__(self, base_url: str, session: Optional[requests.Session] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def send_prompt(self, prompt: str) -> None:
        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json={"prompt": prompt},
                timeout=30,
            )
            response.raise_for_status()
            logger.info("Forwarded prompt (%s chars) to Agent-S.", len(prompt))
        except requests.RequestException:
            logger.exception("Failed to forward prompt to Agent-S.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward inbound iMessages to the Agent-S server."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Base hostname for the Agent-S server (default: %(default)s).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="HTTP port of the Agent-S server (default: %(default)s).",
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
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    base_url = f"{args.host}:{args.port}"
    client = AgentSClient(base_url)

    poller = IMessagesPoller(args.contact, args.interval)

    def handle_message(message: IncomingMessage) -> None:
        source = args.contact or message.conversation
        if not message.text:
            logger.info("Ignoring empty message from %s.", source)
            return
        logger.info(
            "Received message from %s at %s: %s",
            source,
            message.received_at.isoformat(),
            message.text,
        )
        client.send_prompt(message.text)

    poller.run_forever(handle_message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
