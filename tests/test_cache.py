"""Tests for atomic cache writes and cache round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest

from korbpuls import cache


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> cache.CacheDir:
    """Create an isolated league cache under a temporary root."""
    monkeypatch.setattr(cache, "CACHE_ROOT", tmp_path)
    league = cache.CacheDir("99999")
    league.ensure_exists()
    return league


def test_write_json_is_atomic(cache_dir: cache.CacheDir) -> None:
    cache_dir.write_json("standings.json", {"standings": []})

    assert cache_dir.read_json("standings.json") == {"standings": []}
    assert not (cache_dir.base_path / "standings.json.tmp").exists()


def test_ai_cache_round_trip(cache_dir: cache.CacheDir) -> None:
    cache_dir.write_ai_analysis("team-a", "<p>Analysis</p>")
    cache_dir.write_ai_prediction("<table></table>", "<p>Explanation</p>")
    cache_dir.write_standings_narrative("<p>Narrative</p>")
    cache_dir.write_matchup_preview("home", "away", "<p>Preview</p>")

    assert cache_dir.read_ai_analysis("team-a") == "<p>Analysis</p>"
    assert cache_dir.read_ai_prediction() == {
        "table": "<table></table>",
        "explanation": "<p>Explanation</p>",
    }
    assert cache_dir.read_standings_narrative() == "<p>Narrative</p>"
    assert cache_dir.read_matchup_preview("home", "away") == "<p>Preview</p>"


def test_failure_markers_are_atomic(cache_dir: cache.CacheDir) -> None:
    cache_dir.write_ai_analysis_failed("team-a")

    assert cache_dir.read_ai_analysis_failed("team-a") is True
    assert not (cache_dir.teams_path / "team-a_analysis_failed.json.tmp").exists()
