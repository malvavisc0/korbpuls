"""Subprocess calls to korb CLI with JSON parsing."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any, cast

_KORB_CMD = shlex.split(os.environ.get("KORB_CMD", "uv run korb"))


class KorbError(Exception):
    """Raised when korb CLI invocation fails."""


def _run_korb(args: list[str]) -> dict[str, Any]:
    """Run korb CLI command and parse JSON output.

    Args:
        args: Command-line arguments for korb

    Returns:
        Parsed JSON response from korb

    Raises:
        KorbError: If command fails or output is not valid JSON
    """
    cmd = [*_KORB_CMD, *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise KorbError(f"korb command failed: {e.stderr}") from e

    try:
        return cast(dict[str, Any], json.loads(result.stdout))
    except json.JSONDecodeError as e:
        raise KorbError(f"korb output is not valid JSON: {e}") from e


def run_download(ligaid: str) -> None:
    """Download HTML files for a league.

    Args:
        ligaid: League ID number

    Note:
        The download command outputs plain text, not JSON.
    """
    cmd = [*_KORB_CMD, "--ligaid", ligaid, "download"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise KorbError(f"korb download failed: {e.stderr}") from e


def run_standings(ligaid: str) -> dict[str, Any]:
    """Get standings for a league.

    Args:
        ligaid: League ID number

    Returns:
        JSON response with standings data
    """
    return _run_korb(["--ligaid", ligaid, "--json", "standings"])


def run_schedule(ligaid: str) -> dict[str, Any]:
    """Get schedule for a league.

    Args:
        ligaid: League ID number

    Returns:
        JSON response with schedule data
    """
    return _run_korb(["--ligaid", ligaid, "--json", "schedule"])


def run_predict(ligaid: str) -> dict[str, Any]:
    """Get predictions for a league.

    Args:
        ligaid: League ID number

    Returns:
        JSON response with predictions and final standings
    """
    return _run_korb(["--ligaid", ligaid, "--json", "predict"])


def run_ergebnisse(ligaid: str) -> dict[str, Any]:
    """Get game results for a league.

    Args:
        ligaid: League ID number

    Returns:
        JSON response with game results
    """
    return _run_korb(["--ligaid", ligaid, "--json", "ergebnisse"])


def run_team(ligaid: str, team_name: str) -> dict[str, Any]:
    """Get team results.

    Args:
        ligaid: League ID number
        team_name: Full team name

    Returns:
        JSON response with team results
    """
    return _run_korb(["--ligaid", ligaid, "--json", "team", team_name])
