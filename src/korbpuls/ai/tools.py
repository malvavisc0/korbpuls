"""AI agent tools — scoped korb CLI access."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

_KORB_CMD = shlex.split(os.environ.get("KORB_CMD", "uv run korb"))


def run_korb_command(args: str, timeout: int = 60) -> dict[str, Any]:
    """Run `korb <args>` and return {success, stdout, stderr, error}."""
    cmd = [*_KORB_CMD, *shlex.split(args)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return {
                "success": False,
                "stdout": stdout,
                "stderr": stderr,
                "error": f"korb exited with code {result.returncode}",
            }

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = stdout

        return {"success": True, "stdout": parsed, "stderr": stderr, "error": None}

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Command timed out after {timeout} seconds",
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Unexpected error: {e}",
        }
