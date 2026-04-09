"""AI agent tools — scoped korb CLI access."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any


_KORB_CMD = shlex.split(os.environ.get("KORB_CMD", "uv run korb"))


def run_korb_command(args: str, timeout: int = 60) -> dict[str, Any]:
    """Execute a korb CLI command and return the result.

    This tool only runs the korb CLI with the provided arguments.
    The korb binary path is handled automatically — pass only
    the subcommand and flags, e.g. '--json --ligaid 51491 standings'.

    Args:
        args: korb subcommand and flags (do NOT include 'uv run korb')
        timeout: Maximum execution time in seconds

    Returns:
        Dict with success, stdout (parsed JSON when possible), stderr, error
    """
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

        # Try to parse JSON output
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
