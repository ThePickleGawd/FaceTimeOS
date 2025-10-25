#!/usr/bin/env python3
"""
Standalone harness for summarize_action that prints the model output.

The prompt encourages the desktop agent to leverage Codex after noticing the
Codex logo in image.png. Requires OPENAI_API_KEY to be set.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from importlib import reload
from pathlib import Path
from typing import Any, Dict, List


def load_module() -> Any:
    """
    Import (or reload) action_analysis_agent so environment overrides apply.
    """
    import src.s3.action_analysis_agent as module

    return reload(module)


def encode_image(path: Path) -> Dict[str, str]:
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "resource", "mime_type": "image/png", "contents": data}


def build_payload(prompt: str, history: List[str], image_path: Path) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": prompt},
        encode_image(image_path),
    ]
    return {"content": content, "history": history}


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY before running.", file=sys.stderr)
        return 1

    image_path = Path("image.png")
    if not image_path.exists():
        print(f"Missing image asset: {image_path}", file=sys.stderr)
        return 1

    module = load_module()
    payload = build_payload(
        prompt=(
            "The desktop shows the Codex logo. Guide the computer-use agent "
            "to open Codex, review active projects, and draft automation steps."
        ),
        history=[
            "Observed developer tooling shortcuts",
            "Captured IDE preparation steps for Codex",
        ],
        image_path=image_path,
    )

    try:
        summary = module.summarize_action(payload["content"], payload["history"])
    except Exception as exc:
        print(f"[error] summarize_action failed: {exc}", file=sys.stderr)
        return 1

    output = {
        "prompt": payload["content"][0]["text"],
        "history": payload["history"],
        "summary": summary,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
