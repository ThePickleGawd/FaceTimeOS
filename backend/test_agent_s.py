#!/usr/bin/env python3
"""
Agent-S mock server that receives iMessages from main.py, processes them with an LLM,
and sends responses back via the send_imessage endpoint.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

LOG_LEVEL = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)

app = Flask(__name__)
logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Configuration
AGENT_HOST = os.environ["AGENT_HOST"]
AGENT_PORT = int(os.environ["AGENT_PORT"])
SERVER_HOST = os.environ["SERVER_HOST"]
SERVER_PORT = int(os.environ["SERVER_PORT"])
BACKEND_BASE_URL = os.getenv(
    "BACKEND_BASE_URL",
    f"http://{SERVER_HOST}:{SERVER_PORT}",
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LLM_ENABLED = OPENAI_API_KEY is not None


def call_llm(prompt: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Call LLM API to generate a response."""
    if not LLM_ENABLED:
        logger.warning("LLM not enabled, using mock response")
        if not prompt:
            return "Hello! I'm here to help."
        return "Thanks for reaching out. I'll get back to you soon."

    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        system_prompt = "You are a helpful AI assistant responding to iMessages. Keep responses concise and friendly."
        if metadata:
            context = f"\n\nContext: {metadata}"
            system_prompt += context
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7,
        )
        
        return response.choices[0].message.content or "No response generated."
    except ImportError:
        logger.error("openai package not installed. Install with: pip install openai")
        return "Error: OpenAI package not installed."
    except Exception as exc:
        logger.exception("LLM call failed: %s", exc)
        return f"Error generating response: {exc}"


def send_imessage_response(target: str, text: str, attachments: Optional[list[str]] = None) -> bool:
    """Send iMessage response via main.py backend."""
    try:
        payload: Dict[str, Any] = {"target": target, "text": text}
        if attachments:
            payload["attachments"] = attachments
        
        response = requests.post(
            f"{BACKEND_BASE_URL}/api/send_imessage",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Successfully sent iMessage response to %s", target)
        return True
    except requests.RequestException as exc:
        logger.exception("Failed to send iMessage response: %s", exc)
        return False


@app.route("/api/chat", methods=["POST"])
def handle_chat() -> Any:
    """Handle incoming chat requests from main.py."""
    payload = request.get_json(silent=True) or {}
    prompt = payload.get("prompt", "")
    metadata = payload.get("metadata", {})
    
    logger.info("Received chat request: %s", prompt[:100])
    logger.debug("Full payload: %s", payload)
    
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    
    # Extract sender info from metadata if available
    sender = metadata.get("contact_label") or metadata.get("phone_number") or metadata.get("conversation")
    
    # Generate LLM response
    llm_response = call_llm(prompt, metadata)
    
    # Send response back via iMessage if we have sender info
    if sender:
        success = send_imessage_response(sender, llm_response)
        return jsonify({
            "status": "sent" if success else "failed",
            "response": llm_response,
            "target": sender
        }), 200
    else:
        logger.warning("No sender info in metadata, cannot send response")
        return jsonify({
            "status": "no_sender",
            "response": llm_response
        }), 200


@app.route("/api/pause", methods=["GET"])
def pause() -> Any:
    """Pause handler (no-op for now)."""
    logger.info("Pause request received")
    return jsonify({"status": "paused"}), 200


@app.route("/api/resume", methods=["GET"])
def resume() -> Any:
    """Resume handler (no-op for now)."""
    logger.info("Resume request received")
    return jsonify({"status": "resumed"}), 200


@app.route("/api/stop", methods=["GET"])
def stop() -> Any:
    """Stop handler (no-op for now)."""
    logger.info("Stop request received")
    return jsonify({"status": "stopped"}), 200


@app.route("/health", methods=["GET"])
def health() -> Any:
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "llm_enabled": LLM_ENABLED,
        "backend_url": BACKEND_BASE_URL
    }), 200


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent-S mock server with optional interactive CLI",
    )
    parser.add_argument(
        "--host",
        default=AGENT_HOST,
        help="Host interface for the Agent-S server (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=AGENT_PORT,
        help="Port for the Agent-S server (default: %(default)s)",
    )
    parser.add_argument(
        "--backend-url",
        default=BACKEND_BASE_URL,
        help="Base URL of the main backend (default: %(default)s)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.getenv("AGENT_DEBUG", "false").lower() in {"true", "1", "yes"},
        help="Run the Flask server in debug mode",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive CLI for sending outbound messages",
    )
    return parser


def run_server(host: str, port: int, debug: bool) -> None:
    logger.info("Starting Agent-S server on port %d", port)
    logger.info("Backend URL: %s", BACKEND_BASE_URL)
    logger.info("LLM enabled: %s", LLM_ENABLED)
    if LLM_ENABLED:
        logger.info("Using OpenAI model: %s", OPENAI_MODEL)

    app.run(host=host, port=port, debug=debug, use_reloader=False)


def interactive_shell() -> None:
    print("Interactive Agent-S CLI ready. Commands: outgoing | help | quit")
    while True:
        try:
            command = input("agent-cli> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not command:
            continue
        if command in {"quit", "exit"}:
            break
        if command in {"help", "?"}:
            print(
                "Commands:\n"
                "  outgoing  Send an outbound iMessage via the backend.\n"
                "  quit      Exit interactive mode.\n"
            )
            continue

        if command in {"outgoing", "out", "o"}:
            target = input("Target handle> ").strip()
            if not target:
                print("Target is required.")
                continue
            text = input("Message text> ").strip()
            attachments_raw = input(
                "Attachments (comma-separated paths, blank for none)> "
            ).strip()

            attachments_list: list[str] = []
            if attachments_raw:
                for chunk in attachments_raw.split(","):
                    cleaned = chunk.strip()
                    if not cleaned:
                        continue
                    cleaned = cleaned.strip("'\"")
                    expanded = str(Path(cleaned).expanduser())
                    attachments_list.append(expanded)

            if not text and not attachments_list:
                print("Provide a message or at least one attachment path.")
                continue

            attachments = attachments_list or None
            success = send_imessage_response(target, text, attachments)
            print("Status: {}".format("sent" if success else "failed"))
            continue

        print(f"Unknown command: {command}. Type 'help' for options.")

    print("Exiting interactive mode.")


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    BACKEND_BASE_URL = args.backend_url.rstrip("/")

    server_args = {
        "host": args.host,
        "port": args.port,
        "debug": args.debug,
    }

    if args.interactive:
        server_thread = threading.Thread(
            target=run_server,
            kwargs=server_args,
            daemon=True,
            name="agent_s_server",
        )
        server_thread.start()
        print(
            "Agent-S server running in background on http://{}:{}".format(
                args.host if args.host != "0.0.0.0" else "127.0.0.1",
                args.port,
            )
        )
        try:
            interactive_shell()
        finally:
            print("Stopping Agent-S server thread...")
    else:
        run_server(**server_args)
