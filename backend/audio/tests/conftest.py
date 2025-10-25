"""Test configuration for the audio microservice package."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable when running pytest via `uv run pytest`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
