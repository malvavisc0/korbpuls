"""AI agent tools — scoped korb CLI access."""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

from korbpuls.korb_client import KORB_TIMEOUT_SECONDS, run_korb


def run_korb_command(
    args: str,
    timeout: float = KORB_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run `korb <args>` and return {success, stdout, stderr, error}."""
    try:
        result = run_korb(shlex.split(args), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Command timed out after {timeout:g} seconds",
        }
    except OSError as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Could not run korb: {exc}",
        }

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
