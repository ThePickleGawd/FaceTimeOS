#!/usr/bin/env python3
"""Quick manual tester for the ASI:One chat completions API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

import requests
from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


DEFAULT_ENDPOINT = "https://api.asi1.ai/v1/chat/completions"
DEFAULT_MODEL = "asi1-mini"
DEFAULT_HANDLE = "@computer-use-action-analysis"


def _format_history(history: Sequence[str]) -> str:
    if not history:
        return "None"
    return "\n".join(f"- {entry}" for entry in history)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Send a test prompt to the ASI:One API using the "
            "'computer-use-action-analysis' agent handle."
        )
    )
    parser.add_argument(
        "message",
        nargs="?",
        default=(
            "Agent reviewed the invoice email, downloaded the PDF attachment, "
            "saved it to Desktop, and opened the file in Preview for verification."
        ),
        help="Current notification message to summarize.",
    )
    parser.add_argument(
        "--style",
        default="notification_text",
        choices=("notification_text", "notification_voice"),
        help="Summary style to request (default: notification_text).",
    )
    parser.add_argument(
        "--history",
        nargs="*",
        default=None,
        metavar="TEXT",
        help=(
            "Optional notification history entries. "
            "Pass multiple strings to simulate existing context."
        ),
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help="Override the ASI:One API endpoint.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model identifier to use for the request.",
    )
    parser.add_argument(
        "--handle",
        default=DEFAULT_HANDLE,
        help="Agent handle to target in the prompt.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="Request timeout in seconds.",
    )

    args = parser.parse_args()

    api_key = os.getenv("ASI_ONE_API_KEY")
    if not api_key:
        parser.error(
            "ASI_ONE_API_KEY environment variable must be set with a valid API key."
        )

    system_prompt = (
        "Return a single concise summary of the desktop agent's activity. "
        "Avoid emojis and filler."
    )
    if args.style == "notification_voice":
        system_prompt = (
            "Return a short, natural-sounding spoken update about the desktop agent. "
            "Avoid emojis."
        )

    history_block = _format_history(args.history or [])
    user_content = (
        f"{args.handle}\n"
        f"Summary style: {args.style}\n"
        f"Recent notification history:\n{history_block}\n\n"
        f"Current observation:\n{args.message}"
    )

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            args.endpoint, headers=headers, json=payload, timeout=args.timeout
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[error] Request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        print(f"[error] Invalid JSON response: {exc}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        sys.exit(1)

    choices = data.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    summary = message.get("content", "").strip()

    print("=== Request Payload ===")
    print(json.dumps(payload, indent=2))
    print("\n=== Response ===")
    print(json.dumps(data, indent=2))
    print("\n=== Extracted Summary ===")
    print(summary or "<empty>")


if __name__ == "__main__":
    main()
