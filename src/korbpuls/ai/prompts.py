"""Prompt builders for AI agents."""

from __future__ import annotations

import json
from typing import Any


def build_standings_narrative_prompt(
    ligaid: str,
    standings_data: dict[str, Any],
) -> str:
    """Build the Commentator prompt from cached standings data."""
    rows = standings_data.get("standings", [])
    standings_payload = json.dumps(
        [
            {
                "rank": rank,
                "team": row.get("name", ""),
                "gp": row.get("gp", 0),
                "w": row.get("w", 0),
                "l": row.get("l", 0),
                "d": row.get("d", 0),
                "pts": row.get("pts", 0),
                "diff": row.get("diff", 0),
                "pf": row.get("pf", 0),
                "pa": row.get("pa", 0),
                "avg_pf": row.get("avg_pf", 0),
                "avg_pa": row.get("avg_pa", 0),
            }
            for rank, row in enumerate(rows, start=1)
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"LIGA_ID={ligaid}\n"
        f"LANGUAGE=de\n"
        f"LEAGUE_NAME={standings_data.get('liga_name', '')}\n"
        f"STANDINGS_JSON={standings_payload}\n\n"
        "The standings above are current and complete. Use them "
        "directly. Use only facts in STANDINGS_JSON. Mention at most "
        "three teams. Do not name opponents from games, describe "
        "specific matchups, or state scorelines; use only rank, "
        "points, record, and differential. Do not call tools. Do not "
        "describe your process, do not mention missing data, and do "
        "not write a draft. Return only the final narrative required "
        "by the schema: one HTML <p> with 3-5 German sentences."
    )
