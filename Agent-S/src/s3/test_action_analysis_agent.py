#!/usr/bin/env python3
"""
Quick CLI harness to exercise `summarize_action` from `action_analysis_agent`.

Example:
    OPENAI_API_KEY=... python gui_agents/s3/test_action_analysis_agent.py \\
        "Open browser and search for the budget report." \\
        --history "Opened email app" "Read finance thread" \\
        --image screenshots/state.png
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any, Dict, List

from src.s3.action_analysis_agent import summarize_action


def encode_image(path: Path) -> Dict[str, Any]:
    mime_type, _ = mimetypes.guess_type(path)
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError(f"Unsupported image mime type for {path}")

    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "resource", "mime_type": mime_type, "contents": data}


def build_content(prompt: str, images: List[Path]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in images:
        content.append(encode_image(image_path))
    return content


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call summarize_action with custom prompt/history/input images."
    )
    parser.add_argument(
        "prompt", help="Free-form text representing the agent's thoughts."
    )
    parser.add_argument(
        "--history",
        nargs="*",
        default=[],
        help="Previous summaries to seed the trajectory context.",
    )
    parser.add_argument(
        "--image",
        dest="images",
        action="append",
        default=[],
        type=Path,
        help="Optional image(s) to include (can specify multiple).",
    )
    parser.add_argument(
        "--max-history",
        type=int,
        default=None,
        help="Trim the provided history to this many most-recent entries.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    history = args.history
    if args.max_history is not None:
        history = history[-args.max_history :]

    try:
        content = build_content(args.prompt, args.images)
        summary = summarize_action(content, history)
    except Exception as exc:  # surface API errors clearly
        print(f"[error] summarize_action failed: {exc}", file=sys.stderr)
        return 1

    output = {
        "prompt": args.prompt,
        "history": history,
        "images": [str(path) for path in args.images],
        "summary": summary,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
