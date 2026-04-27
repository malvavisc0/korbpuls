"""Cache management for JSON files on disk."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

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


class CacheDir:
    """Manage cache directory for a league."""

    def __init__(self, ligaid: str) -> None:
        """Initialize cache directory for a league.

        Args:
            ligaid: League ID
        """
        self.ligaid = ligaid
        self.base_path = CACHE_ROOT / ligaid
        self.teams_path = self.base_path / "teams"

    def ensure_exists(self) -> None:
        """Create cache directory structure if it doesn't exist."""
        self.teams_path.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        """Remove the entire cache directory for this league."""
        if self.base_path.exists():
            shutil.rmtree(self.base_path)

    def clear_data_files(self) -> None:
        """Remove only data files, preserving AI analysis files.

        Deletes standings, schedule, ergebnisse, predict, meta,
        status, and per-team data files, but keeps AI analysis
        and AI failure marker files intact.
        """
        data_files = [
            "standings.json",
            "schedule.json",
            "ergebnisse.json",
            "predict.json",
            "meta.json",
            "status.json",
        ]
        for name in data_files:
            path = self.base_path / name
            if path.exists():
                path.unlink()

        # Remove per-team data files but keep AI files
        if self.teams_path.exists():
            for f in self.teams_path.iterdir():
                if f.suffix == ".json" and not self._is_ai_file(f):
                    f.unlink()

    @staticmethod
    def _is_ai_file(path: Path) -> bool:
        """Check if a path is an AI-related cache file.

        Matches files ending in _analysis, _analysis_failed,
        _preview, or _preview_failed.
        """
        stem = path.stem
        return any(
            stem.endswith(suffix)
            for suffix in (
                "_analysis",
                "_analysis_failed",
                "_preview",
                "_preview_failed",
            )
        )

    def clear_ai_files(self) -> None:
        """Remove all AI-related files (analysis + failure markers).

        Deletes per-team AI analyses, matchup previews,
        prediction narratives, standings narratives,
        and all failure marker files.
        """
        # Per-team AI files (analysis + preview)
        if self.teams_path.exists():
            for f in self.teams_path.iterdir():
                if f.suffix == ".json" and self._is_ai_file(f):
                    f.unlink()

        # League-level AI files + failure markers
        for name in [
            "prediction_narrative.json",
            "prediction_narrative_failed.json",
            "standings_narrative.json",
            "standings_narrative_failed.json",
        ]:
            path = self.base_path / name
            if path.exists():
                path.unlink()

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
                if f.suffix == ".json" and not self._is_ai_file(f)
            )
            for f in team_files:
                hasher.update(f.read_bytes())
                found = True

        return hasher.hexdigest() if found else ""

    def touch_ai_files(self) -> None:
        """Update mtime of all AI files to now.

        Keeps AI analyses "fresh" relative to meta.json so
        is_ai_analysis_fresh() / is_ai_prediction_fresh() /
        is_standings_narrative_fresh() / is_matchup_preview_fresh()
        continue to return True after a no-change re-fetch.
        """
        now = time.time()

        if self.teams_path.exists():
            for f in self.teams_path.iterdir():
                if f.suffix == ".json" and self._is_ai_file(f):
                    os.utime(f, (now, now))

        for name in [
            "prediction_narrative.json",
            "prediction_narrative_failed.json",
            "standings_narrative.json",
            "standings_narrative_failed.json",
        ]:
            path = self.base_path / name
            if path.exists():
                os.utime(path, (now, now))

    def write_json(self, filename: str, data: dict[str, Any]) -> None:
        """Write JSON data to a file.

        Args:
            filename: Name of the file (e.g., 'standings.json')
            data: Dictionary to write as JSON
        """
        path = self.base_path / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

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

    def team_file_exists(self, team_slug: str) -> bool:
        """Check if team cache file exists.

        Args:
            team_slug: Team slug string

        Returns:
            True if team file exists
        """
        return (self.teams_path / f"{team_slug}.json").exists()

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
        path = self.teams_path / f"{team_slug}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def liga_exists(self) -> bool:
        """Check if league cache directory exists.

        Returns:
            True if base directory exists
        """
        return self.base_path.exists()

    def write_status(self, status: str, error: str | None = None) -> None:
        """Write status.json to track download progress.

        Args:
            status: One of "pending", "ready", "error"
            error: Optional error message when status is "error"
        """
        data: dict[str, str] = {"status": status}
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

        data = cast(dict[str, str], json.loads(path.read_text()))
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

    def read_ai_analysis(self, team_slug: str) -> str | None:
        """Read cached AI team analysis.

        Returns:
            Analysis paragraph or None if not cached
        """
        path = self.teams_path / f"{team_slug}_analysis.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return data.get("analysis")

    def write_ai_analysis(self, team_slug: str, analysis: str) -> None:
        """Write AI team analysis to cache."""
        path = self.teams_path / f"{team_slug}_analysis.json"
        path.write_text(
            json.dumps(
                {"analysis": analysis},
                indent=2,
                ensure_ascii=False,
            )
        )

    def is_ai_analysis_fresh(self, team_slug: str) -> bool:
        """Check if AI analysis cache is fresh (newer than league data).

        Returns True if analysis exists AND meta.json hasn't been
        updated since the analysis was generated. This means the
        underlying league data hasn't changed.
        """
        ai_path = self.teams_path / f"{team_slug}_analysis.json"
        meta_path = self.base_path / "meta.json"
        if not ai_path.exists() or not meta_path.exists():
            return False
        return ai_path.stat().st_mtime >= meta_path.stat().st_mtime

    def read_ai_prediction(self) -> dict[str, str] | None:
        """Read cached AI prediction narrative.

        Returns:
            Dict with 'table' and 'explanation' keys, or None
        """
        path = self.base_path / "prediction_narrative.json"
        if not path.exists():
            return None
        return cast(dict[str, str], json.loads(path.read_text()))

    def write_ai_prediction(self, table: str, explanation: str) -> None:
        """Write AI prediction narrative to cache."""
        path = self.base_path / "prediction_narrative.json"
        path.write_text(
            json.dumps(
                {"table": table, "explanation": explanation},
                indent=2,
                ensure_ascii=False,
            )
        )

    def is_ai_prediction_fresh(self) -> bool:
        """Check if AI prediction cache is fresh (newer than league data).

        Returns True if prediction exists AND meta.json hasn't been
        updated since the prediction was generated.
        """
        ai_path = self.base_path / "prediction_narrative.json"
        meta_path = self.base_path / "meta.json"
        if not ai_path.exists() or not meta_path.exists():
            return False
        return ai_path.stat().st_mtime >= meta_path.stat().st_mtime

    # -- Standings narrative -------------------------------------------------

    def read_standings_narrative(self) -> str | None:
        """Read cached AI standings narrative.

        Returns:
            Narrative HTML or None if not cached
        """
        path = self.base_path / "standings_narrative.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return data.get("narrative")

    def write_standings_narrative(self, narrative: str) -> None:
        """Write AI standings narrative to cache."""
        path = self.base_path / "standings_narrative.json"
        path.write_text(
            json.dumps(
                {"narrative": narrative},
                indent=2,
                ensure_ascii=False,
            )
        )

    def is_standings_narrative_fresh(self) -> bool:
        """Check if standings narrative cache is fresh.

        Returns True if narrative exists AND meta.json hasn't been
        updated since the narrative was generated.
        """
        ai_path = self.base_path / "standings_narrative.json"
        meta_path = self.base_path / "meta.json"
        if not ai_path.exists() or not meta_path.exists():
            return False
        return ai_path.stat().st_mtime >= meta_path.stat().st_mtime

    # -- Matchup preview -----------------------------------------------------

    def _matchup_key(self, home_slug: str, away_slug: str) -> str:
        """Generate cache key for a matchup preview."""
        return f"{home_slug}_vs_{away_slug}_preview"

    def read_matchup_preview(self, home_slug: str, away_slug: str) -> str | None:
        """Read cached AI matchup preview.

        Returns:
            Analysis HTML or None if not cached
        """
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return data.get("analysis")

    def write_matchup_preview(
        self, home_slug: str, away_slug: str, analysis: str
    ) -> None:
        """Write AI matchup preview to cache."""
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}.json"
        path.write_text(
            json.dumps(
                {"analysis": analysis},
                indent=2,
                ensure_ascii=False,
            )
        )

    def is_matchup_preview_fresh(self, home_slug: str, away_slug: str) -> bool:
        """Check if matchup preview cache is fresh.

        Returns True if preview exists AND meta.json hasn't been
        updated since the preview was generated.
        """
        key = self._matchup_key(home_slug, away_slug)
        ai_path = self.teams_path / f"{key}.json"
        meta_path = self.base_path / "meta.json"
        if not ai_path.exists() or not meta_path.exists():
            return False
        return ai_path.stat().st_mtime >= meta_path.stat().st_mtime

    # -- AI failure markers --------------------------------------------------

    def write_ai_analysis_failed(self, team_slug: str) -> None:
        """Write a failure marker for AI team analysis.

        Args:
            team_slug: Team slug string
        """
        path = self.teams_path / f"{team_slug}_analysis_failed.json"
        path.write_text(json.dumps({"failed": True}))

    def read_ai_analysis_failed(self, team_slug: str) -> bool:
        """Check if AI team analysis has a failure marker.

        Args:
            team_slug: Team slug string

        Returns:
            True if the failure marker exists
        """
        path = self.teams_path / f"{team_slug}_analysis_failed.json"
        return path.exists()

    def clear_ai_analysis_failed(self, team_slug: str) -> None:
        """Remove failure marker for AI team analysis.

        Args:
            team_slug: Team slug string
        """
        path = self.teams_path / f"{team_slug}_analysis_failed.json"
        if path.exists():
            path.unlink()

    def write_ai_prediction_failed(self) -> None:
        """Write a failure marker for AI prediction narrative."""
        path = self.base_path / "prediction_narrative_failed.json"
        path.write_text(json.dumps({"failed": True}))

    def read_ai_prediction_failed(self) -> bool:
        """Check if AI prediction narrative has a failure marker.

        Returns:
            True if the failure marker exists
        """
        path = self.base_path / "prediction_narrative_failed.json"
        return path.exists()

    def clear_ai_prediction_failed(self) -> None:
        """Remove failure marker for AI prediction narrative."""
        path = self.base_path / "prediction_narrative_failed.json"
        if path.exists():
            path.unlink()

    def write_standings_narrative_failed(self) -> None:
        """Write a failure marker for AI standings narrative."""
        path = self.base_path / "standings_narrative_failed.json"
        path.write_text(json.dumps({"failed": True}))

    def read_standings_narrative_failed(self) -> bool:
        """Check if AI standings narrative has a failure marker."""
        path = self.base_path / "standings_narrative_failed.json"
        return path.exists()

    def clear_standings_narrative_failed(self) -> None:
        """Remove failure marker for AI standings narrative."""
        path = self.base_path / "standings_narrative_failed.json"
        if path.exists():
            path.unlink()

    def write_matchup_preview_failed(self, home_slug: str, away_slug: str) -> None:
        """Write a failure marker for AI matchup preview."""
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}_failed.json"
        path.write_text(json.dumps({"failed": True}))

    def read_matchup_preview_failed(self, home_slug: str, away_slug: str) -> bool:
        """Check if AI matchup preview has a failure marker."""
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}_failed.json"
        return path.exists()

    def clear_matchup_preview_failed(self, home_slug: str, away_slug: str) -> None:
        """Remove failure marker for AI matchup preview."""
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}_failed.json"
        if path.exists():
            path.unlink()
