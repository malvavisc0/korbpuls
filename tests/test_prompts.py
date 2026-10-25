"""Tests for AI prompt builders."""

from __future__ import annotations

from korbpuls.ai.prompts import build_standings_narrative_prompt


def test_standings_prompt_injects_standings_data() -> None:
    prompt = build_standings_narrative_prompt(
        "99999",
        {
            "liga_name": "Testliga",
            "standings": [
                {
                    "name": "Team A",
                    "gp": 1,
                    "w": 1,
                    "l": 0,
                    "d": 0,
                    "pts": 2,
                    "diff": 10,
                    "pf": 50,
                    "pa": 40,
                    "avg_pf": 50,
                    "avg_pa": 40,
                }
            ],
        },
    )

    assert "LIGA_ID=99999" in prompt
    assert "LEAGUE_NAME=Testliga" in prompt
    assert '"team":"Team A"' in prompt
    assert "Do not call tools" in prompt
    assert "one HTML <p>" in prompt
