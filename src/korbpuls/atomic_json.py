"""Atomic JSON file writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically so readers never see partial data."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)
