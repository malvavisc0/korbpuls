"""Tests for presenter date/day logic and slug handling."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from korbpuls.bbtime import BB_TZ
from korbpuls.presenters import (
    TeamSlugs,
    _get_upcoming_games,
    _is_season_finished,
    _parse_schedule_game,
    _predicted_standings,
    _today_games,
)


def _date(days: int, time: str = "10:00") -> str:
    value = datetime.now(BB_TZ) + timedelta(days=days)
    return f"{value.strftime('%d.%m.%Y')} {time}"


def _game(home: str, away: str, days: int = 0, time: str = "10:00") -> dict[str, Any]:
    return {
        "date": _date(days, time),
        "home": home,
        "away": away,
        "venue": "Halle",
        "cancelled": False,
    }


def test_team_slugs_use_registered_canonical_slug() -> None:
    slugs = TeamSlugs({"custom-slug": "Team A", "team-a-2": "Team-A"})

    assert slugs.slug_for("Team A") == "custom-slug"
    assert slugs.slug_for("Team-A") == "team-a-2"
    assert slugs.slug_for("Unknown Team") == "unknown-team"


def test_today_games_attach_scores_and_sort_by_time() -> None:
    slugs = TeamSlugs({"a": "A", "b": "B", "c": "C"})
    schedule = {
        "schedule": [
            _game("C", "A", time="12:00"),
            _game("A", "B", time="10:00"),
            _game("B", "C", days=1),
        ]
    }
    ergebnisse = {
        "ergebnisse": [
            {
                "date": _date(0),
                "home": "A",
                "away": "B",
                "home_score": 80,
                "away_score": 70,
            }
        ]
    }

    games = _today_games(schedule, ergebnisse, slugs)

    assert [game.time for game in games] == ["10:00", "12:00"]
    assert games[0].played is True
    assert (games[0].home_score, games[0].away_score) == (80, 70)
    assert games[1].played is False
    assert games[1].home_slug == "c"


def test_season_is_not_finished_on_a_game_day() -> None:
    slugs = TeamSlugs({})
    today_game = _parse_schedule_game(_game("A", "B"), slugs)
    yesterday_game = _parse_schedule_game(_game("A", "B", days=-1), slugs)

    assert _is_season_finished([today_game]) is False
    assert _is_season_finished([yesterday_game]) is True


def test_unparseable_schedule_date_keeps_season_open() -> None:
    slugs = TeamSlugs({})
    game = _parse_schedule_game(_game("A", "B"), slugs)
    game.date = "TBD"

    assert _is_season_finished([game]) is False


def test_upcoming_games_keep_today_until_result_exists() -> None:
    slugs = TeamSlugs({"a": "A", "b": "B", "c": "C"})
    schedule = {
        "schedule": [
            _game("A", "B"),
            _game("A", "C", days=1),
            _game("B", "C", days=2),
        ]
    }
    ergebnisse = {
        "ergebnisse": [
            {
                "date": _date(0),
                "home": "B",
                "away": "C",
                "home_score": 50,
                "away_score": 60,
            }
        ]
    }

    games = _get_upcoming_games(schedule, "A", ergebnisse, slugs)

    assert [(game.home, game.away) for game in games] == [
        ("A", "B"),
        ("A", "C"),
    ]
    assert all(game.home_slug for game in games)


def test_predicted_standings_use_canonical_slugs() -> None:
    data = {
        "standings": [
            {
                "name": "Team A",
                "w": 1,
                "l": 0,
                "pf": 80,
                "pa": 70,
                "diff": 10,
                "pts": 2,
            }
        ]
    }

    rows = _predicted_standings(data, TeamSlugs({"custom": "Team A"}))

    assert rows[0].slug == "custom"
