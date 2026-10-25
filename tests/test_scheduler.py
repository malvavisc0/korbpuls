"""Tests for season completion and scheduler archiving decisions."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from korbpuls import cache, scheduler
from korbpuls.bbtime import BB_TZ


def _date(days: int) -> str:
    value = datetime.now(BB_TZ) + timedelta(days=days)
    return value.strftime("%d.%m.%Y 10:00")


def test_schedule_has_results_matches_fixtures_not_counts() -> None:
    schedule = {
        "schedule": [
            {"home": "A", "away": "B"},
            {"home": "C", "away": "D"},
        ]
    }
    results = {
        "ergebnisse": [
            {"home": "A", "away": "B"},
            {"home": "X", "away": "Y"},
        ]
    }

    assert scheduler.schedule_has_results(schedule, results) is False


def test_schedule_has_results_accepts_all_fixtures() -> None:
    schedule = {"schedule": [{"home": "A", "away": "B"}]}
    results = {"ergebnisse": [{"home": "A", "away": "B"}]}

    assert scheduler.schedule_has_results(schedule, results) is True


def test_season_is_not_finished_on_a_game_day() -> None:
    schedule = {
        "schedule": [{"date": _date(0), "home": "A", "away": "B", "cancelled": False}]
    }
    old_schedule = {
        "schedule": [{"date": _date(-1), "home": "A", "away": "B", "cancelled": False}]
    }

    assert scheduler.is_season_finished(schedule) is False
    assert scheduler.is_season_finished(old_schedule) is True


@pytest.fixture
def finished_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> cache.CacheDir:
    """Create a complete, finished league cache."""
    monkeypatch.setattr(cache, "CACHE_ROOT", tmp_path)
    league = cache.CacheDir("99999")
    league.ensure_exists()
    league.write_meta(
        cache.LigaMeta(
            ligaid="99999",
            league_name="Test League",
            liga_slug="test-league",
            cached_at="24.10.2026 17:00",
            team_slugs={"a": "A", "b": "B"},
            archived=False,
        )
    )
    league.write_json("standings.json", {"standings": []})
    league.write_json("predict.json", {"predictions": []})
    league.write_json(
        "schedule.json",
        {
            "schedule": [
                {
                    "date": _date(-1),
                    "home": "A",
                    "away": "B",
                    "cancelled": False,
                }
            ]
        },
    )
    league.write_status("ready")
    return league


def test_complete_finished_season_is_archived(
    finished_cache: cache.CacheDir,
) -> None:
    finished_cache.write_json(
        "ergebnisse.json",
        {
            "ergebnisse": [
                {
                    "date": _date(-1),
                    "home": "A",
                    "away": "B",
                    "home_score": 80,
                    "away_score": 70,
                }
            ]
        },
    )

    assert scheduler._should_refresh_league(finished_cache) is False
    assert finished_cache.read_meta().archived is True


def test_missing_result_keeps_season_refreshing(
    finished_cache: cache.CacheDir,
) -> None:
    finished_cache.write_json("ergebnisse.json", {"ergebnisse": []})

    assert scheduler._should_refresh_league(finished_cache) is True
    assert finished_cache.read_meta().archived is False
