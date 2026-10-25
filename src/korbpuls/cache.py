"""Cache management for JSON files on disk."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from korbpuls.ai.cache import AICacheMixin
from korbpuls.atomic_json import write_json_atomic
from korbpuls.settings import load_config

load_config()

CACHE_ROOT = Path(os.environ.get("CACHE_DIR", "files"))


class CacheMiss(Exception):
    """Raised when requested cached data is not found."""


class LigaMeta(BaseModel):
    """Metadata about a cached league."""

    ligaid: str
    league_name: str
    liga_slug: str
    cached_at: str
    team_slugs: dict[str, str]
    # Sticky flag set once a season is finished; freezes the cache.
    archived: bool = False


class CacheDir(AICacheMixin):
    """Manage cache directory for a league."""

    def __init__(self, ligaid: str) -> None:
        """Initialize cache directory for a league.

        Args:
            ligaid: League ID
        """
        self.ligaid = ligaid
        self.base_path = CACHE_ROOT / ligaid
        self.teams_path = self.base_path / "teams"

    @classmethod
    def list_all_league_ids(cls) -> list[str]:
        """Return ligaid strings for all cached leagues.

        Scans CACHE_ROOT for subdirectories that contain a
        meta.json file, indicating a fully-fetched league.

        Returns:
            Sorted list of ligaid strings.
        """
        if not CACHE_ROOT.exists():
            return []
        return sorted(
            d.name
            for d in CACHE_ROOT.iterdir()
            if d.is_dir() and (d / "meta.json").exists()
        )

    def ensure_exists(self) -> None:
        """Create cache directory structure if it doesn't exist."""
        self.teams_path.mkdir(parents=True, exist_ok=True)

    def compute_data_hash(self) -> str:
        """Compute a SHA-256 hash of all cached data files.

        Includes standings, schedule, ergebnisse, predict, and
        per-team data files. Excludes meta, status, and AI files.

        Returns:
            Hex digest string, or empty string if no data files exist.
        """
        hasher = hashlib.sha256()
        found = False

        data_names = [
            "standings.json",
            "schedule.json",
            "ergebnisse.json",
            "predict.json",
        ]
        for name in sorted(data_names):
            path = self.base_path / name
            if path.exists():
                hasher.update(path.read_bytes())
                found = True

        # Include per-team data files (exclude AI files)
        if self.teams_path.exists():
            team_files = sorted(
                f
                for f in self.teams_path.iterdir()
                if f.suffix == ".json" and not self.is_ai_file(f)
            )
            for f in team_files:
                hasher.update(f.read_bytes())
                found = True

        return hasher.hexdigest() if found else ""

    def write_json(self, filename: str, data: dict[str, Any]) -> None:
        """Write JSON data to a file atomically.

        Args:
            filename: Name of the file (e.g., 'standings.json')
            data: Dictionary to write as JSON
        """
        write_json_atomic(self.base_path / filename, data)

    def read_json(self, filename: str) -> dict[str, Any]:
        """Read JSON data from a file.

        Args:
            filename: Name of the file

        Returns:
            Parsed JSON data

        Raises:
            CacheMiss: If file doesn't exist
        """
        path = self.base_path / filename
        if not path.exists():
            raise CacheMiss(f"Cache file not found: {filename}")
        return cast(dict[str, Any], json.loads(path.read_text()))

    def write_meta(self, meta: LigaMeta) -> None:
        """Write meta.json file.

        Args:
            meta: LigaMeta instance
        """
        self.write_json("meta.json", meta.model_dump())

    def read_meta(self) -> LigaMeta:
        """Read meta.json file.

        Returns:
            LigaMeta instance

        Raises:
            CacheMiss: If meta.json doesn't exist
        """
        data = self.read_json("meta.json")
        return LigaMeta(**data)

    def has_all_data(self) -> bool:
        """Check if all required cache files exist.

        Returns:
            True if standings, schedule, predict, ergebnisse, and meta exist
        """
        required = [
            "standings.json",
            "schedule.json",
            "predict.json",
            "ergebnisse.json",
            "meta.json",
        ]
        return all((self.base_path / f).exists() for f in required)

    def read_team_json(self, team_slug: str) -> dict[str, Any]:
        """Read team JSON file.

        Args:
            team_slug: Team slug string

        Returns:
            Parsed JSON data

        Raises:
            CacheMiss: If team file doesn't exist
        """
        path = self.teams_path / f"{team_slug}.json"
        if not path.exists():
            raise CacheMiss(f"Team cache file not found: {team_slug}")
        return cast(dict[str, Any], json.loads(path.read_text()))

    def write_team_json(self, team_slug: str, data: dict[str, Any]) -> None:
        """Write team JSON file.

        Args:
            team_slug: Team slug string
            data: Team data dictionary
        """
        write_json_atomic(self.teams_path / f"{team_slug}.json", data)

    def liga_exists(self) -> bool:
        """Check if league cache directory exists.

        Returns:
            True if base directory exists
        """
        return self.base_path.exists()

    def write_status(
        self,
        status: str,
        error: str | None = None,
        attempts: int = 0,
    ) -> None:
        """Write status.json to track download progress.

        Args:
            status: One of "pending", "ready", "error"
            error: Optional error message when status is "error"
            attempts: Number of fetch attempts made for this cycle
                (used to cap automatic retries from the loading page)
        """
        data: dict[str, Any] = {"status": status, "attempts": attempts}
        if error is not None:
            data["error"] = error
        self.write_json("status.json", data)

    def read_status(self) -> dict[str, str]:
        """Read status.json to check download progress.

        Returns:
            Dict with "status" key and optionally "error" key.
            Returns {"status": "unknown"} if file is missing.
            Returns {"status": "stale"} if pending status is
            older than 10 minutes.
        """
        path = self.base_path / "status.json"
        if not path.exists():
            return {"status": "unknown"}

        try:
            data = cast(dict[str, str], json.loads(path.read_text()))
        except json.JSONDecodeError:
            # Corrupted (e.g. crash mid-write by an older version) —
            # treat as stale so the interrupted fetch gets retried.
            return {"status": "stale"}
        status = data.get("status", "unknown")

        # Staleness check: if pending for more than 10 minutes, treat as stale
        if status == "pending":
            mtime = path.stat().st_mtime
            if time.time() - mtime > 600:  # 10 minutes
                return {"status": "stale"}

        return data

    def is_cache_fresh(self, ttl_seconds: int = 3600) -> bool:
        """Check if cached data is fresh based on meta.json mtime.

        Args:
            ttl_seconds: Time-to-live in seconds (default 1 hour)

        Returns:
            True if meta.json exists and its mtime is within TTL
        """
        meta_path = self.base_path / "meta.json"
        if not meta_path.exists():
            return False
        mtime = meta_path.stat().st_mtime
        return (time.time() - mtime) < ttl_seconds
