"""Subprocess calls to korb CLI with JSON parsing."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any, cast

from korbpuls.cache import CACHE_ROOT

KORB_CMD = shlex.split(os.environ.get("KORB_CMD", "uv run korb"))
KORB_TIMEOUT_SECONDS = 60.0


def korb_cwd() -> str:
    """Working directory for korb subprocesses.

    korb resolves its HTML files relative to CWD as
    ``files/<ligaid>/{ergebnisse,spielplan}.html``.  Pointing CWD at
    the cache root (the persistent volume in production) keeps those
    downloads on the volume so AI agent tool calls still find them
    after container restarts.  Locally the cache root *is* the
    ``files/`` dir, so CWD must be its parent for the paths to line
    up with the pre-existing layout.
    """
    root = CACHE_ROOT
    if root.name == "files":
        return str(root.parent)
    return str(root)


class KorbError(Exception):
    """Raised when korb CLI invocation fails."""


def run_korb(
    args: list[str],
    timeout: float = KORB_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run korb with the configured command and working directory.

    Args:
        args: Arguments appended to the configured korb command
        timeout: Maximum runtime in seconds

    Returns:
        Completed process with captured text output

    Raises:
        subprocess.TimeoutExpired: If korb exceeds *timeout*
    """
    return subprocess.run(
        [*KORB_CMD, *args],
        capture_output=True,
        text=True,
        cwd=korb_cwd(),
        timeout=timeout,
        check=False,
    )


def _run_korb(args: list[str]) -> dict[str, Any]:
    """Run korb CLI command and parse JSON output.

    Args:
        args: Command-line arguments for korb

    Returns:
        Parsed JSON response from korb

    Raises:
        KorbError: If command fails or output is not valid JSON
    """
    try:
        result = run_korb(args)
    except subprocess.TimeoutExpired as exc:
        raise KorbError(f"korb timed out after {KORB_TIMEOUT_SECONDS:g}s") from exc

    if result.returncode != 0:
        raise KorbError(f"korb command failed: {result.stderr}")

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
    try:
        result = run_korb(["--ligaid", ligaid, "download"])
    except subprocess.TimeoutExpired as exc:
        raise KorbError(
            f"korb download timed out after {KORB_TIMEOUT_SECONDS:g}s"
        ) from exc
    if result.returncode != 0:
        raise KorbError(f"korb download failed: {result.stderr}")


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
