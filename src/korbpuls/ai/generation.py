"""AI generation tasks for league narratives and analyses."""

from __future__ import annotations

import logging

from korbpuls import presenters
from korbpuls.ai.agents import (
    LeaguePrediction,
    MatchupPreview,
    StandingsNarrative,
    TeamAnalysis,
    get_analyst,
    get_commentator,
    get_oracle,
    get_scout,
)
from korbpuls.ai.config import AIConfig
from korbpuls.ai.prompts import build_standings_narrative_prompt
from korbpuls.ai.runtime import run_agent_once
from korbpuls.cache import CacheDir

logger = logging.getLogger(__name__)


async def run_team_analysis(
    config: AIConfig, ligaid: str, team_slug: str, team_name: str
) -> None:
    """Background task: generate AI team analysis."""
    cache = CacheDir(ligaid)
    if not cache.try_begin_ai_generation("analysis", team_slug):
        return
    try:
        analyst = get_analyst(
            api_base=config.api_base,
            api_key=config.api_key,
            model=config.model,
        )
        prompt = (
            f"TEAM_NAME={team_name}\n"
            f"LIGA_ID={ligaid}\n"
            f"LANGUAGE=de\n\n"
            f"Analyze the team '{team_name}' following the skill steps."
        )
        result: TeamAnalysis = await run_agent_once(
            analyst,
            prompt,
            TeamAnalysis,
        )
        cache.write_ai_analysis(team_slug, result.conclusion)
    except Exception:
        logger.exception(
            "AI team analysis failed for %s/%s",
            ligaid,
            team_slug,
        )
        cache.write_ai_analysis_failed(team_slug)
    finally:
        cache.clear_ai_generation_pending("analysis", team_slug)


async def run_prediction_narrative(config: AIConfig, ligaid: str) -> None:
    """Background task: generate AI prediction narrative."""
    cache = CacheDir(ligaid)
    if not cache.try_begin_ai_generation("prediction"):
        return
    try:
        oracle = get_oracle(
            api_base=config.api_base,
            api_key=config.api_key,
            model=config.model,
        )
        prompt = (
            f"LIGA_ID={ligaid}\n"
            f"LANGUAGE=de\n\n"
            "Analyze this league following the skill steps."
        )
        result: LeaguePrediction = await run_agent_once(
            oracle,
            prompt,
            LeaguePrediction,
        )
        cache.write_ai_prediction(result.table, result.explanation)
    except Exception:
        logger.exception(
            "AI prediction narrative failed for %s",
            ligaid,
        )
        cache.write_ai_prediction_failed()
    finally:
        cache.clear_ai_generation_pending("prediction")


async def run_standings_narrative(config: AIConfig, ligaid: str) -> None:
    """Background task: generate AI standings narrative.

    No-ops during off-season (no games played yet) so an empty
    standings table never triggers an LLM call.
    """
    if not presenters.standings_ai_eligible(ligaid):
        return
    cache = CacheDir(ligaid)
    if not cache.try_begin_ai_generation("standings"):
        return
    try:
        standings_data = cache.read_json("standings.json")
        if not standings_data.get("standings"):
            return
        commentator = get_commentator(
            api_base=config.api_base,
            api_key=config.api_key,
            model=config.model,
        )
        prompt = build_standings_narrative_prompt(ligaid, standings_data)
        result: StandingsNarrative = await run_agent_once(
            commentator,
            prompt,
            StandingsNarrative,
        )
        cache.write_standings_narrative(result.narrative)
    except Exception:
        logger.exception(
            "AI standings narrative failed for %s",
            ligaid,
        )
        cache.write_standings_narrative_failed()
    finally:
        cache.clear_ai_generation_pending("standings")


async def run_matchup_preview(
    config: AIConfig,
    ligaid: str,
    home_slug: str,
    away_slug: str,
    home_name: str,
    away_name: str,
) -> None:
    """Background task: generate AI matchup preview."""
    cache = CacheDir(ligaid)
    preview_key = f"{home_slug}_vs_{away_slug}_preview"
    if not cache.try_begin_ai_generation("preview", preview_key):
        return
    try:
        scout = get_scout(
            api_base=config.api_base,
            api_key=config.api_key,
            model=config.model,
        )
        prompt = (
            f"HOME_TEAM={home_name}\n"
            f"AWAY_TEAM={away_name}\n"
            f"LIGA_ID={ligaid}\n"
            f"LANGUAGE=de\n\n"
            f"Analyze the matchup between '{home_name}' (home) "
            f"and '{away_name}' (away) following the skill steps."
        )
        result: MatchupPreview = await run_agent_once(
            scout,
            prompt,
            MatchupPreview,
        )
        cache.write_matchup_preview(home_slug, away_slug, result.analysis)
    except Exception:
        logger.exception(
            "AI matchup preview failed for %s/%s vs %s",
            ligaid,
            home_slug,
            away_slug,
        )
        cache.write_matchup_preview_failed(home_slug, away_slug)
    finally:
        cache.clear_ai_generation_pending("preview", preview_key)
