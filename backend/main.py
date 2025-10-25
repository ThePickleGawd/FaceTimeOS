import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request


app = Flask(__name__)

logger = logging.getLogger(__name__)

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"
CONTACT_DISPLAY_NAME = "Calvin Lu"
POLL_INTERVAL_SECONDS = 5.0


def apple_time_to_datetime(raw_value: Optional[int]) -> datetime:
    if raw_value is None:
        return datetime.now(timezone.utc)
    seconds = raw_value / 1_000_000_000 if raw_value > 1_000_000_000 else raw_value
    return APPLE_EPOCH + timedelta(seconds=seconds)


def open_chat_db() -> Optional[sqlite3.Connection]:
    if not CHAT_DB_PATH.exists():
        logger.warning("Messages database not found at %s", CHAT_DB_PATH)
        return None
    try:
        return sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        logger.exception("Unable to open Messages database.")
        return None


def latest_rowid_for_contact(contact_name: str) -> int:
    connection = open_chat_db()
    if connection is None:
        return 0
    with closing(connection) as conn:
        cursor = conn.execute(
            """
            SELECT COALESCE(MAX(message.ROWID), 0)
            FROM message
            JOIN chat_message_join cmj ON cmj.message_id = message.ROWID
            WHERE cmj.chat_id IN (
                SELECT ROWID FROM chat WHERE display_name = ?
            )
            AND message.is_from_me = 0
            """,
            (contact_name,),
        )
        row = cursor.fetchone()
    return int(row[0]) if row and row[0] else 0


def handle_incoming_message(message_text: str, received_at: datetime) -> None:
    logger.info(
        "Dummy handler invoked for incoming iMessage from %s at %s: %s",
        CONTACT_DISPLAY_NAME,
        received_at.isoformat(),
        message_text,
    )


def poll_imessages(contact_name: str, interval: float) -> None:
    last_seen_rowid = latest_rowid_for_contact(contact_name)
    logger.info("Starting iMessage polling for %s at rowid %s", contact_name, last_seen_rowid)
    while True:
        connection = open_chat_db()
        if connection is None:
            time.sleep(interval)
            continue

        try:
            with closing(connection) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT
                        message.ROWID AS rowid,
                        COALESCE(message.text, '') AS text,
                        message.date AS message_date
                    FROM message
                    JOIN chat_message_join cmj ON cmj.message_id = message.ROWID
                    WHERE cmj.chat_id IN (
                        SELECT ROWID FROM chat WHERE display_name = ?
                    )
                    AND message.is_from_me = 0
                    AND message.ROWID > ?
                    ORDER BY message.ROWID ASC
                    """,
                    (contact_name, last_seen_rowid),
                )
                rows = cursor.fetchall()
        except sqlite3.Error:
            logger.exception("Failed to read from Messages database.")
            time.sleep(interval)
            continue

        for row in rows:
            last_seen_rowid = max(last_seen_rowid, int(row["rowid"]))
            message_text = row["text"] or ""
            received_at = apple_time_to_datetime(row["message_date"])
            handle_incoming_message(message_text, received_at)

        time.sleep(interval)


def start_imessage_polling(contact_name: str, interval: float) -> None:
    thread = threading.Thread(
        target=poll_imessages,
        args=(contact_name, interval),
        daemon=True,
        name="imessage-poller",
    )
    thread.start()


@app.post("/api/completetask")
def complete_task():
    request.get_json(silent=True)
    return jsonify({"detail": "not implemented"}), 501


@app.post("/api/currentaction")
def current_action():
    request.get_json(silent=True)
    return jsonify({"detail": "not implemented"}), 501


@app.post("/api/chat")
def chat():
    request.get_json(silent=True)
    return jsonify({"detail": "not implemented"}), 501


@app.get("/api/stop")
def stop():
    return jsonify({"detail": "not implemented"}), 501


@app.get("/api/pause")
def pause():
    return jsonify({"detail": "not implemented"}), 501


@app.get("/api/resume")
def resume():
    return jsonify({"detail": "not implemented"}), 501


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    debug_mode = True
    app.debug = debug_mode
    if not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_imessage_polling(CONTACT_DISPLAY_NAME, POLL_INTERVAL_SECONDS)
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
