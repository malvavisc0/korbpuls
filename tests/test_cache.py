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


def test_invalid_standings_narrative_is_discarded(
    cache_dir: cache.CacheDir,
) -> None:
    cache_dir.write_standings_narrative("Hmm, I need the standings data.")

    assert cache_dir.read_standings_narrative() is None
    assert not (cache_dir.base_path / "standings_narrative.json").exists()
    assert cache_dir.read_standings_narrative_failed() is True


def test_malformed_ai_cache_is_discarded(
    cache_dir: cache.CacheDir,
) -> None:
    path = cache_dir.teams_path / "team-a_analysis.json"
    path.write_text("{not valid json")

    assert cache_dir.read_ai_analysis("team-a") is None
    assert not path.exists()
    assert cache_dir.read_ai_analysis_failed("team-a") is True


def test_invalid_matchup_preview_is_discarded(
    cache_dir: cache.CacheDir,
) -> None:
    cache_dir.write_matchup_preview(
        "home",
        "away",
        "Text outside a paragraph.<p>Only one paragraph.</p>",
    )

    assert cache_dir.read_matchup_preview("home", "away") is None
    assert cache_dir.read_matchup_preview_failed("home", "away") is True


def test_invalid_prediction_narrative_is_discarded(
    cache_dir: cache.CacheDir,
) -> None:
    cache_dir.write_ai_prediction(
        "<table></table>",
        "I'll fetch the prediction data now.",
    )

    assert cache_dir.read_ai_prediction() is None
    assert cache_dir.read_ai_prediction_failed() is True


def test_ai_generation_lock_is_exclusive(
    cache_dir: cache.CacheDir,
) -> None:
    assert cache_dir.try_begin_ai_generation("analysis", "team-a") is True
    assert cache_dir.is_ai_generation_pending("analysis", "team-a") is True
    assert cache_dir.try_begin_ai_generation("analysis", "team-a") is False

    cache_dir.clear_ai_generation_pending("analysis", "team-a")

    assert cache_dir.is_ai_generation_pending("analysis", "team-a") is False
    assert cache_dir.try_begin_ai_generation("analysis", "team-a") is True
