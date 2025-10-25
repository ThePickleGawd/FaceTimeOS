#!/usr/bin/env python3
"""
Simple CLI client for exercising the Agent-S Flask API.

Run app.py separately, then execute this script to interactively send prompts
and pause/resume/stop commands. Type `help` for available commands.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Dict

import requests


def _print_json(title: str, payload: Dict) -> None:
    """Render JSON payloads in a readable format."""
    pretty = json.dumps(payload, indent=2, sort_keys=True)
    print(f"{title}:\n{pretty}\n")


def send_prompt(base_url: str, prompt: str) -> None:
    response = requests.post(
        f"{base_url}/api/chat",
        json={"prompt": prompt},
        timeout=30,
    )
    _print_json("Response", response.json())


def send_simple_command(base_url: str, endpoint: str, name: str) -> None:
    response = requests.get(f"{base_url}{endpoint}", timeout=15)
    _print_json(f"{name} response", response.json())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interact with the Agent-S Flask API.")
    parser.add_argument(
        "--host",
        default="http://127.0.0.1",
        help="Base hostname for the running Agent-S server (default: %(default)s).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="HTTP port of the Agent-S server (default: %(default)s).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    base_url = f"{args.host}:{args.port}"

    print("Agent-S test client ready.")
    print("Type a prompt to start a run. Commands: pause | resume | stop | help | quit\n")

    commands: Dict[str, Callable[[], None]] = {
        "pause": lambda: send_simple_command(base_url, "/api/pause", "Pause"),
        "resume": lambda: send_simple_command(base_url, "/api/resume", "Resume"),
        "stop": lambda: send_simple_command(base_url, "/api/stop", "Stop"),
    }

    while True:
        try:
            user_input = input("Agent-S> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"quit", "exit"}:
            print("Goodbye.")
            break

        if user_input.lower() == "help":
            print(
                "Commands:\n"
                "  pause   Pause the current Agent-S run.\n"
                "  resume  Resume a paused Agent-S run.\n"
                "  stop    Stop the current Agent-S run.\n"
                "  exit    Quit the client (alias: quit, Ctrl-D).\n"
                "Any other text is sent as a prompt to /api/chat.\n"
            )
            continue

        command_handler = commands.get(user_input.lower())
        if command_handler:
            try:
                command_handler()
            except requests.RequestException as exc:
                print(f"[error] Failed to send command: {exc}\n")
            continue

        try:
            send_prompt(base_url, user_input)
        except requests.RequestException as exc:
            print(f"[error] Failed to send prompt: {exc}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
