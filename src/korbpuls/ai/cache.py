"""AI artifact cache and generation locks."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import cast

from korbpuls.ai.validation import is_valid_html_paragraphs
from korbpuls.atomic_json import write_json_atomic


class AICacheMixin:
    """AI artifact caching and generation locks for a league cache."""

    base_path: Path
    teams_path: Path

    @staticmethod
    def is_ai_file(path: Path) -> bool:
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
                if f.suffix == ".json" and self.is_ai_file(f):
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
                if f.suffix == ".json" and self.is_ai_file(f):
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

    def read_ai_analysis(self, team_slug: str) -> str | None:
        """Read cached AI team analysis.

        Invalid or malformed cache entries are removed and marked failed
        so the UI can offer regeneration instead of rendering garbage.

        Returns:
            Analysis paragraph or None if not cached or invalid
        """
        path = self.teams_path / f"{team_slug}_analysis.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = None
        analysis = data.get("analysis") if isinstance(data, dict) else None
        if not is_valid_html_paragraphs(analysis, max_paragraphs=3):
            path.unlink(missing_ok=True)
            self.write_ai_analysis_failed(team_slug)
            return None
        return cast(str, analysis)

    def write_ai_analysis(self, team_slug: str, analysis: str) -> None:
        """Write AI team analysis to cache."""
        write_json_atomic(
            self.teams_path / f"{team_slug}_analysis.json",
            {"analysis": analysis},
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

        Invalid or malformed cache entries are removed and marked failed.

        Returns:
            Dict with 'table' and 'explanation' keys, or None
        """
        path = self.base_path / "prediction_narrative.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = None
        if not isinstance(data, dict):
            path.unlink(missing_ok=True)
            self.write_ai_prediction_failed()
            return None
        table = data.get("table")
        explanation = data.get("explanation")
        if (
            not isinstance(table, str)
            or "<table" not in table.lower()
            or "</table>" not in table.lower()
            or not isinstance(explanation, str)
            or not is_valid_html_paragraphs(explanation, max_paragraphs=1)
        ):
            path.unlink(missing_ok=True)
            self.write_ai_prediction_failed()
            return None
        return {"table": table, "explanation": explanation}

    def write_ai_prediction(self, table: str, explanation: str) -> None:
        """Write AI prediction narrative to cache."""
        write_json_atomic(
            self.base_path / "prediction_narrative.json",
            {"table": table, "explanation": explanation},
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

        Invalid or malformed cache entries are removed and marked failed
        so the UI shows a failure state instead of rendering garbage.

        Returns:
            Narrative HTML or None if not cached or invalid
        """
        path = self.base_path / "standings_narrative.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = None
        narrative = data.get("narrative") if isinstance(data, dict) else None
        if not is_valid_html_paragraphs(narrative, max_paragraphs=1):
            path.unlink(missing_ok=True)
            self.write_standings_narrative_failed()
            return None
        return cast(str, narrative)

    def write_standings_narrative(self, narrative: str) -> None:
        """Write AI standings narrative to cache."""
        write_json_atomic(
            self.base_path / "standings_narrative.json",
            {"narrative": narrative},
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

        Invalid or malformed cache entries are removed and marked failed.

        Returns:
            Analysis HTML or None if not cached or invalid
        """
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = None
        analysis = data.get("analysis") if isinstance(data, dict) else None
        if not is_valid_html_paragraphs(analysis, max_paragraphs=3):
            path.unlink(missing_ok=True)
            self.write_matchup_preview_failed(home_slug, away_slug)
            return None
        return cast(str, analysis)

    def write_matchup_preview(
        self, home_slug: str, away_slug: str, analysis: str
    ) -> None:
        """Write AI matchup preview to cache."""
        key = self._matchup_key(home_slug, away_slug)
        write_json_atomic(
            self.teams_path / f"{key}.json",
            {"analysis": analysis},
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
        write_json_atomic(path, {"failed": True})

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
        write_json_atomic(path, {"failed": True})

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
        write_json_atomic(path, {"failed": True})

    def read_standings_narrative_failed(self) -> bool:
        """Check if AI standings narrative has a failure marker."""
        path = self.base_path / "standings_narrative_failed.json"
        return path.exists()

    def clear_standings_narrative_failed(self) -> None:
        """Remove failure marker for AI standings narrative."""
        path = self.base_path / "standings_narrative_failed.json"
        if path.exists():
            path.unlink()

    # -- AI generation locks ------------------------------------------------

    def _ai_pending_path(self, scope: str, key: str = "") -> Path:
        """Return the in-progress marker path for an AI artifact."""
        if scope == "standings":
            return self.base_path / "standings_narrative_generating.json"
        if scope == "prediction":
            return self.base_path / "prediction_narrative_generating.json"
        if scope == "analysis":
            return self.teams_path / f"{key}_analysis_generating.json"
        if scope == "preview":
            return self.teams_path / f"{key}_generating.json"
        raise ValueError(f"Unknown AI generation scope: {scope}")

    def is_ai_generation_pending(
        self,
        scope: str,
        key: str = "",
        *,
        max_age_seconds: int = 600,
    ) -> bool:
        """Whether an AI generation is already running.

        Stale markers left behind by a crashed task are removed after
        ``max_age_seconds`` so generation cannot be blocked forever.
        """
        path = self._ai_pending_path(scope, key)
        if not path.exists():
            return False
        if time.time() - path.stat().st_mtime > max_age_seconds:
            path.unlink(missing_ok=True)
            return False
        return True

    def try_begin_ai_generation(
        self,
        scope: str,
        key: str = "",
        *,
        max_age_seconds: int = 600,
    ) -> bool:
        """Atomically acquire an AI generation lock.

        Uses exclusive file creation so two workers cannot generate the
        same artifact at the same time. Stale locks from crashed tasks
        expire after ``max_age_seconds``.
        """
        path = self._ai_pending_path(scope, key)
        if path.exists() and (time.time() - path.stat().st_mtime > max_age_seconds):
            path.unlink(missing_ok=True)
        try:
            fd = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            return False
        try:
            os.write(fd, b'{"pending":true}')
        finally:
            os.close(fd)
        return True

    def clear_ai_generation_pending(self, scope: str, key: str = "") -> None:
        """Clear an AI generation marker."""
        self._ai_pending_path(scope, key).unlink(missing_ok=True)

    def write_matchup_preview_failed(self, home_slug: str, away_slug: str) -> None:
        """Write a failure marker for AI matchup preview."""
        key = self._matchup_key(home_slug, away_slug)
        path = self.teams_path / f"{key}_failed.json"
        write_json_atomic(path, {"failed": True})

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
