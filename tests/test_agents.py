"""Tests for AI output validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from korbpuls.ai.agents import StandingsNarrative, TeamAnalysis


def test_standings_narrative_accepts_single_html_paragraph() -> None:
    result = StandingsNarrative(
        narrative="<p>Ein <strong>Team</strong> führt die Tabelle an.</p>"
    )

    assert result.narrative.startswith("<p>")
    assert result.narrative.endswith("</p>")


@pytest.mark.parametrize(
    "invalid",
    [
        "Hmm, I need the actual standings data before writing.",
        "Die Tabelle ist spannend.",
        "<p>Ein Absatz.</p><p>Ein zweiter Absatz.</p>",
        "<p>Ich rufe run_korb_command auf.</p>",
        "<p>Ein Absatz.</p> Zusätzlicher Text",
    ],
)
def test_standings_narrative_rejects_plain_or_process_output(
    invalid: str,
) -> None:
    with pytest.raises(ValidationError):
        StandingsNarrative(narrative=invalid)


def test_team_analysis_rejects_process_text() -> None:
    with pytest.raises(ValidationError):
        TeamAnalysis(conclusion="I'll fetch the team data now and write a draft.")
