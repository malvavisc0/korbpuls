"""FastAPI application with HTML routes and protected API routes."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi import Path as URLPath
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from llama_index.core.agent.workflow import FunctionAgent
from pydantic import BaseModel

from korbpuls import presenters
from korbpuls.ai import AIConfig
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
from korbpuls.auth import validate_api_key
from korbpuls.cache import CacheDir, CacheMiss, LigaMeta
from korbpuls.korb_client import (
    KorbError,
    run_download,
    run_ergebnisse,
    run_predict,
    run_schedule,
)
from korbpuls.korb_client import run_standings as korb_standings
from korbpuls.korb_client import run_team as korb_team
from korbpuls.slugify import slugify

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
app = FastAPI(title="korbPuls")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["app_version"] = __import__("korbpuls").__version__


def validate_ligaid_format(ligaid: str) -> bool:
    """Validate ligaid is digits only.

    Args:
        ligaid: String to validate

    Returns:
        True if ligaid contains only digits
    """
    return bool(re.fullmatch(r"\d+", ligaid))


def format_datetime(dt: datetime) -> str:
    """Format datetime for display.

    Args:
        dt: Datetime to format

    Returns:
        German-formatted date string
    """
    return dt.strftime("%d.%m.%Y %H:%M")


def fetch_and_cache_league(ligaid: str) -> None:
    """Fetch all league data from korb and cache to disk.

    Runs as a background task. Handles errors internally by
    writing status.json instead of propagating exceptions.

    Preserves existing AI analyses when the downloaded data
    is identical to the previously cached data.

    Args:
        ligaid: League ID number
    """
    cache_dir = CacheDir(ligaid)
    cache_dir.ensure_exists()

    # Snapshot old data hash before overwriting
    old_hash = cache_dir.compute_data_hash()

    try:
        run_download(ligaid)

        standings_data = korb_standings(ligaid)
        cache_dir.write_json("standings.json", standings_data)

        league_name: str = standings_data.get("liga_name", "")
        liga_slug = slugify(league_name)

        team_slugs: dict[str, str] = {}
        for team in standings_data.get("standings", []):
            name: str = team["name"]
            team_slugs[slugify(name)] = name

        schedule_data = run_schedule(ligaid)
        cache_dir.write_json("schedule.json", schedule_data)

        ergebnisse_data = run_ergebnisse(ligaid)
        cache_dir.write_json("ergebnisse.json", ergebnisse_data)

        # Prediction may fail for finalized seasons — non-fatal
        try:
            predict_data = run_predict(ligaid)
        except KorbError:
            predict_data = {
                "liga_name": league_name,
                "liga_number": standings_data.get("liga_number", 0),
                "ligaid": int(ligaid),
                "predictions": [],
                "standings": [],
                "finalized": True,
            }
        cache_dir.write_json("predict.json", predict_data)

        for ts, team_name in team_slugs.items():
            try:
                team_data = korb_team(ligaid, team_name)
                cache_dir.write_team_json(ts, team_data)
            except KorbError:
                pass

        meta = LigaMeta(
            ligaid=ligaid,
            league_name=league_name,
            liga_slug=liga_slug,
            cached_at=format_datetime(datetime.now(ZoneInfo("Europe/Berlin"))),
            team_slugs=team_slugs,
        )
        cache_dir.write_meta(meta)

        # Compare new data with old — preserve AI work if unchanged
        new_hash = cache_dir.compute_data_hash()
        if old_hash and old_hash == new_hash:
            cache_dir.touch_ai_files()
            logger.info(
                "Data unchanged for liga %s — AI analyses preserved",
                ligaid,
            )
        else:
            cache_dir.clear_ai_files()
            if old_hash:
                logger.info(
                    "Data changed for liga %s — AI analyses invalidated",
                    ligaid,
                )

        cache_dir.write_status("ready")
    except KorbError as e:
        cache_dir.write_status("error", str(e))
    except Exception as e:
        cache_dir.write_status("error", f"Unerwarteter Fehler: {e}")


async def _retry_agent(
    agent: FunctionAgent,
    prompt: str,
    output_cls: type,
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> Any:
    """Run an AI agent with retry logic and exponential backoff.

    Handles two failure modes:
    1. agent.run() raises an exception (network/timeout)
    2. get_pydantic_model() returns None because the LLM
       didn't produce valid structured output — the most
       common cause of "works on second try" failures.

    Args:
        agent: FunctionAgent instance
        prompt: User message prompt
        output_cls: Pydantic model class for structured output
        max_attempts: Maximum number of attempts (default 3)
        base_delay: Base delay in seconds between retries

    Returns:
        Parsed Pydantic model from the agent response

    Raises:
        RuntimeError: When all retries are exhausted
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await agent.run(
                user_msg=prompt,
                max_iterations=50,
                debug=True,
            )
            result = response.get_pydantic_model(output_cls)
            if result is None:
                # get_pydantic_model returns None silently
                # when structured_response is None or when
                # Pydantic validation fails — treat as retry
                raise RuntimeError(
                    "LLM returned no valid structured output"
                    f" (structured_response="
                    f"{response.structured_response!r})"
                )
            return result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "AI agent attempt %d/%d failed: %s: %s",
                attempt,
                max_attempts,
                type(exc).__name__,
                exc,
            )
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def _run_team_analysis(
    config: AIConfig, ligaid: str, team_slug: str, team_name: str
) -> None:
    """Background task: generate AI team analysis with retry."""
    cache = CacheDir(ligaid)
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
            f"Analyze the team '{team_name}' following the skill steps. "
            f"Use the exact name '{team_name}' (or the full official "
            "name from the standings data) in the output — never "
            "'Team X' or any placeholder. "
            "Return 2-3 <p> elements with 10-15 sentences of "
            "detailed, honest basketball analysis covering identity, "
            "strengths, weaknesses, and comparative assessment. "
            "Use <strong> sparingly. No markdown. No jargon. "
            "Correct German with proper umlauts (ä, ö, ü, ß). "
            "Do NOT copy or paraphrase the examples from the skill. "
            "Sound like an expert analyst."
        )
        result: TeamAnalysis = await _retry_agent(
            analyst,
            prompt,
            TeamAnalysis,
        )
        cache.write_ai_analysis(team_slug, result.conclusion)
    except Exception:
        logger.exception(
            "AI team analysis failed after all retries for %s/%s",
            ligaid,
            team_slug,
        )
        cache.write_ai_analysis_failed(team_slug)


async def _run_prediction_narrative(config: AIConfig, ligaid: str) -> None:
    """Background task: generate AI prediction narrative with retry."""
    cache = CacheDir(ligaid)
    try:
        oracle = get_oracle(
            api_base=config.api_base,
            api_key=config.api_key,
            model=config.model,
        )
        prompt = (
            f"LIGA_ID={ligaid}\n"
            f"LANGUAGE=de\n\n"
            "Analyze this league following the skill steps. "
            "Use the exact team names from the standings data — "
            "never 'Team A', 'Team B', or any placeholder. "
            "Return two separate fields:\n"
            "- table: raw HTML <table> with Team/W/L/Pts/Diff\n"
            "- explanation: a single <p> element with 3-5 "
            "sentences of flowing basketball analysis. "
            "No markdown. No jargon. "
            "Correct German with proper umlauts (ä, ö, ü, ß). "
            "Do NOT copy or paraphrase the examples from the "
            "skill. Sound like a journalist."
        )
        result: LeaguePrediction = await _retry_agent(
            oracle,
            prompt,
            LeaguePrediction,
        )
        cache.write_ai_prediction(result.table, result.explanation)
    except Exception:
        logger.exception(
            "AI prediction narrative failed after all retries for %s",
            ligaid,
        )
        cache.write_ai_prediction_failed()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render homepage with Liga-ID input form."""
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/", response_class=RedirectResponse)
async def fetch_league(
    background_tasks: BackgroundTasks,
    ligaid: str = Form(...),
) -> RedirectResponse:
    """Accept Liga-ID, fetch all data, redirect to loading page."""
    if not validate_ligaid_format(ligaid):
        raise HTTPException(
            status_code=400,
            detail="Ungültige Liga-ID. Bitte nur Ziffern eingeben.",
        )

    cache_dir = CacheDir(ligaid)

    # Fresh cache → redirect directly to standings
    if cache_dir.is_cache_fresh():
        meta = cache_dir.read_meta()
        return RedirectResponse(
            url=f"/liga/{meta.ligaid}/{meta.liga_slug}",
            status_code=302,
        )

    # Already pending → redirect to loading page
    status = cache_dir.read_status()
    if status["status"] == "pending":
        return RedirectResponse(
            url=f"/liga/{ligaid}/laden",
            status_code=302,
        )

    # Start background fetch and redirect to loading page
    cache_dir.clear_data_files()
    cache_dir.ensure_exists()
    cache_dir.write_status("pending")
    background_tasks.add_task(fetch_and_cache_league, ligaid)
    return RedirectResponse(
        url=f"/liga/{ligaid}/laden",
        status_code=302,
    )


@app.get("/liga/{ligaid}", response_class=RedirectResponse)
async def redirect_liga(
    ligaid: str = URLPath(..., pattern=r"\d+"),
) -> RedirectResponse:
    """Redirect /liga/{ligaid} to canonical URL with slug."""
    cache_dir = CacheDir(ligaid)
    if not cache_dir.liga_exists():
        raise HTTPException(status_code=404, detail="Liga nicht gefunden")

    meta = cache_dir.read_meta()
    return RedirectResponse(
        url=f"/liga/{ligaid}/{meta.liga_slug}",
        status_code=301,
    )


# --- Literal sub-routes MUST come before the {liga_slug} catch-all ---


@app.post(
    "/liga/{ligaid}/aktualisieren",
    response_class=RedirectResponse,
)
async def refresh_league(
    background_tasks: BackgroundTasks,
    ligaid: str = URLPath(..., pattern=r"\d+"),
) -> RedirectResponse:
    """Re-fetch all data for a league (bypasses TTL)."""
    cache_dir = CacheDir(ligaid)
    if not cache_dir.liga_exists():
        raise HTTPException(status_code=404, detail="Liga nicht gefunden")

    cache_dir.clear_data_files()
    cache_dir.ensure_exists()
    cache_dir.write_status("pending")
    background_tasks.add_task(fetch_and_cache_league, ligaid)
    return RedirectResponse(
        url=f"/liga/{ligaid}/laden",
        status_code=302,
    )


@app.get(
    "/liga/{ligaid}/laden",
    response_class=HTMLResponse,
    response_model=None,
)
async def loading_page(
    request: Request,
    background_tasks: BackgroundTasks,
    ligaid: str = URLPath(..., pattern=r"\d+"),
) -> HTMLResponse | RedirectResponse:
    """Loading page that auto-refreshes until data is ready."""
    cache_dir = CacheDir(ligaid)
    status = cache_dir.read_status()

    if status["status"] == "pending":
        return templates.TemplateResponse(
            request,
            "loading.html",
            {"ligaid": ligaid},
        )

    if status["status"] == "ready":
        meta = cache_dir.read_meta()
        return RedirectResponse(
            url=f"/liga/{ligaid}/{meta.liga_slug}",
            status_code=302,
        )

    if status["status"] == "error":
        # If the error is very recent (< 10s), it is likely a race
        # condition where the background task failed before the
        # browser followed the redirect.  Auto-retry once.
        status_path = cache_dir.base_path / "status.json"
        if status_path.exists():
            age = time.time() - status_path.stat().st_mtime
            if age < 10:
                cache_dir.clear_data_files()
                cache_dir.ensure_exists()
                cache_dir.write_status("pending")
                background_tasks.add_task(
                    fetch_and_cache_league,
                    ligaid,
                )
                return templates.TemplateResponse(
                    request,
                    "loading.html",
                    {"ligaid": ligaid},
                )

        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "message": "Fehler",
                "hint": status.get("error", "Download fehlgeschlagen"),
                "retry_url": f"/liga/{ligaid}/aktualisieren",
            },
        )

    # unknown or stale
    raise HTTPException(
        status_code=404,
        detail="Liga nicht gefunden",
    )


# --- Parameterized {liga_slug} catch-all routes ---


@app.get("/liga/{ligaid}/{liga_slug}", response_class=HTMLResponse)
async def standings_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render standings page."""
    ai_enabled = AIConfig.from_env() is not None
    try:
        view = presenters.present_standings(ligaid, ai_enabled=ai_enabled)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e

    cache = CacheDir(ligaid)
    ctx = view.model_dump()
    ctx["generating"] = request.query_params.get("generating") == "1"
    ctx["generation_failed"] = cache.read_standings_narrative_failed()
    return templates.TemplateResponse(
        request,
        "standings.html",
        ctx,
    )


@app.get(
    "/liga/{ligaid}/{liga_slug}/team/{team_slug}",
    response_class=HTMLResponse,
)
async def team_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
    team_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render team detail page."""
    ai_enabled = AIConfig.from_env() is not None
    try:
        view = presenters.present_team(ligaid, team_slug, ai_enabled=ai_enabled)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        ) from e

    cache = CacheDir(ligaid)
    ctx = view.model_dump()
    ctx["generating"] = request.query_params.get("generating") == "1"
    ctx["generation_failed"] = cache.read_ai_analysis_failed(team_slug)
    return templates.TemplateResponse(
        request,
        "team.html",
        ctx,
    )


@app.get(
    "/liga/{ligaid}/{liga_slug}/spielplan",
    response_class=HTMLResponse,
)
async def schedule_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render schedule page."""
    try:
        view = presenters.present_schedule(ligaid)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e

    return templates.TemplateResponse(
        request,
        "schedule.html",
        view.model_dump(),
    )


@app.get(
    "/liga/{ligaid}/{liga_slug}/ergebnisse",
    response_class=HTMLResponse,
)
async def ergebnisse_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render ergebnisse page."""
    try:
        view = presenters.present_ergebnisse(ligaid)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e

    return templates.TemplateResponse(
        request,
        "ergebnisse.html",
        view.model_dump(),
    )


@app.get(
    "/liga/{ligaid}/{liga_slug}/prognose",
    response_class=HTMLResponse,
)
async def prediction_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render prediction page."""
    ai_enabled = AIConfig.from_env() is not None
    try:
        view = presenters.present_prediction(ligaid, ai_enabled=ai_enabled)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e

    if not view.prediction_eligible:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "message": "Prognose nicht verfügbar",
                "hint": view.prediction_ineligible_reason,
                "retry_url": None,
            },
        )

    cache = CacheDir(ligaid)
    ctx = view.model_dump()
    ctx["generating"] = request.query_params.get("generating") == "1"
    ctx["generation_failed"] = cache.read_ai_prediction_failed()
    return templates.TemplateResponse(
        request,
        "prediction.html",
        ctx,
    )


@app.post(
    "/liga/{ligaid}/{liga_slug}/team/{team_slug}/ki-analyse",
    response_class=RedirectResponse,
)
async def generate_team_ai(
    background_tasks: BackgroundTasks,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
    team_slug: str = URLPath(...),
) -> RedirectResponse:
    """Trigger AI team analysis generation."""
    config = AIConfig.from_env()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="KI-Funktion nicht konfiguriert",
        )

    cache = CacheDir(ligaid)
    team_url = f"/liga/{ligaid}/{liga_slug}/team/{team_slug}"

    # Check eligibility (need >= 4 games)
    try:
        view = presenters.present_team(ligaid, team_slug, ai_enabled=True)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        ) from e
    if not view.ai_analysis_eligible:
        raise HTTPException(
            status_code=403,
            detail=(view.ai_analysis_ineligible_reason or "Nicht genug Spieldaten"),
        )

    # Cache-first: return cached if data hasn't changed
    if cache.is_ai_analysis_fresh(team_slug):
        return RedirectResponse(url=team_url, status_code=302)

    # Resolve team name from meta
    meta = cache.read_meta()
    team_name = meta.team_slugs.get(team_slug)
    if not team_name:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        )

    cache.clear_ai_analysis_failed(team_slug)
    background_tasks.add_task(
        _run_team_analysis,
        config,
        ligaid,
        team_slug,
        team_name,
    )

    return RedirectResponse(url=f"{team_url}?generating=1", status_code=302)


@app.post(
    "/liga/{ligaid}/{liga_slug}/prognose/ki-analyse",
    response_class=RedirectResponse,
)
async def generate_prediction_ai(
    background_tasks: BackgroundTasks,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> RedirectResponse:
    """Trigger AI prediction narrative generation."""
    config = AIConfig.from_env()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="KI-Funktion nicht konfiguriert",
        )

    cache = CacheDir(ligaid)
    prediction_url = f"/liga/{ligaid}/{liga_slug}/prognose"

    # Block if prediction is not eligible
    try:
        view = presenters.present_prediction(ligaid)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e
    if not view.prediction_eligible:
        reason = view.prediction_ineligible_reason or "Prognose nicht verfügbar"
        raise HTTPException(
            status_code=403,
            detail=reason,
        )
    # Cache-first: return cached if data hasn't changed
    if cache.is_ai_prediction_fresh():
        return RedirectResponse(url=prediction_url, status_code=302)

    cache.clear_ai_prediction_failed()
    background_tasks.add_task(_run_prediction_narrative, config, ligaid)

    return RedirectResponse(
        url=f"{prediction_url}?generating=1",
        status_code=302,
    )


async def _run_standings_narrative(config: AIConfig, ligaid: str) -> None:
    """Background task: generate AI standings narrative."""
    cache = CacheDir(ligaid)
    try:
        commentator = get_commentator(
            api_base=config.api_base,
            api_key=config.api_key,
            model=config.model,
        )
        prompt = (
            f"LIGA_ID={ligaid}\n"
            f"LANGUAGE=de\n\n"
            "Describe the current league standings following "
            "the skill steps. Use the exact team names from "
            "the standings data — never 'Team A', 'Team B', "
            "or any placeholder. "
            "Return a single <p> element with 3-5 sentences "
            "of accessible, conversational league analysis. "
            "No markdown. No jargon. "
            "Correct German with proper umlauts (ä, ö, ü, ß). "
            "Do NOT copy or paraphrase the examples from "
            "the skill. Write like a local sports columnist."
        )
        result: StandingsNarrative = await _retry_agent(
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


async def _run_matchup_preview(
    config: AIConfig,
    ligaid: str,
    home_slug: str,
    away_slug: str,
    home_name: str,
    away_name: str,
) -> None:
    """Background task: generate AI matchup preview."""
    cache = CacheDir(ligaid)
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
            f"Analyze the matchup between '{home_name}' "
            f"(home) and '{away_name}' (away) following the "
            "skill steps. Use the exact team names from the "
            "standings data — never 'Team A', 'Team B', or "
            "any placeholder. "
            "Return 2-3 <p> elements with 8-12 sentences of "
            "detailed matchup analysis. "
            "No markdown. No jargon. "
            "Correct German with proper umlauts (ä, ö, ü, ß). "
            "Do NOT copy or paraphrase the examples from the "
            "skill. Sound like a basketball scout."
        )
        result: MatchupPreview = await _retry_agent(
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


@app.post(
    "/liga/{ligaid}/{liga_slug}/ki-ueberblick",
    response_class=RedirectResponse,
)
async def generate_standings_narrative(
    background_tasks: BackgroundTasks,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> RedirectResponse:
    """Trigger AI standings narrative generation."""
    config = AIConfig.from_env()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="KI-Funktion nicht konfiguriert",
        )

    cache = CacheDir(ligaid)
    standings_url = f"/liga/{ligaid}/{liga_slug}"

    if not cache.liga_exists():
        raise HTTPException(status_code=404, detail="Liga nicht gefunden")

    if cache.is_standings_narrative_fresh():
        return RedirectResponse(url=standings_url, status_code=302)

    cache.clear_standings_narrative_failed()
    background_tasks.add_task(_run_standings_narrative, config, ligaid)
    return RedirectResponse(
        url=f"{standings_url}?generating=1",
        status_code=302,
    )


@app.get(
    "/liga/{ligaid}/{liga_slug}/spielplan/vorschau/{home_slug}/{away_slug}",
    response_class=HTMLResponse,
)
async def matchup_preview_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
    home_slug: str = URLPath(...),
    away_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render matchup preview page."""
    ai_enabled = AIConfig.from_env() is not None
    try:
        view = presenters.present_matchup(
            ligaid,
            home_slug,
            away_slug,
            ai_enabled=ai_enabled,
        )
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Matchup nicht gefunden",
        ) from e

    cache = CacheDir(ligaid)
    ctx = view.model_dump()
    ctx["generating"] = request.query_params.get("generating") == "1"
    ctx["generation_failed"] = cache.read_matchup_preview_failed(home_slug, away_slug)
    return templates.TemplateResponse(
        request,
        "matchup.html",
        ctx,
    )


@app.post(
    "/liga/{ligaid}/{liga_slug}/spielplan"
    "/vorschau/{home_slug}/{away_slug}/ki-generieren",
    response_class=RedirectResponse,
)
async def generate_matchup_preview(
    background_tasks: BackgroundTasks,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
    home_slug: str = URLPath(...),
    away_slug: str = URLPath(...),
) -> RedirectResponse:
    """Trigger AI matchup preview generation."""
    config = AIConfig.from_env()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="KI-Funktion nicht konfiguriert",
        )

    cache = CacheDir(ligaid)
    matchup_url = (
        f"/liga/{ligaid}/{liga_slug}/spielplan/vorschau/{home_slug}/{away_slug}"
    )

    meta = cache.read_meta()
    home_name = meta.team_slugs.get(home_slug)
    away_name = meta.team_slugs.get(away_slug)
    if not home_name or not away_name:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        )

    if cache.is_matchup_preview_fresh(home_slug, away_slug):
        return RedirectResponse(url=matchup_url, status_code=302)

    cache.clear_matchup_preview_failed(home_slug, away_slug)
    background_tasks.add_task(
        _run_matchup_preview,
        config,
        ligaid,
        home_slug,
        away_slug,
        home_name,
        away_name,
    )
    return RedirectResponse(
        url=f"{matchup_url}?generating=1",
        status_code=302,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> HTMLResponse | JSONResponse:
    """Handle HTTP exceptions with error page or JSON for API routes."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "Fehler", "hint": exc.detail, "retry_url": None},
        status_code=exc.status_code,
    )


class StandingsResponse(BaseModel):
    """API response for standings."""

    liga_name: str
    liga_number: int
    ligaid: int
    standings: list[dict[str, Any]]


class ScheduleResponse(BaseModel):
    """API response for schedule."""

    liga_name: str
    liga_number: int
    ligaid: int
    schedule: list[dict[str, Any]]


class PredictResponse(BaseModel):
    """API response for predictions."""

    liga_name: str
    liga_number: int
    ligaid: int
    predictions: list[dict[str, Any]]
    standings: list[dict[str, Any]]


class TeamResponse(BaseModel):
    """API response for team data."""

    liga_name: str
    liga_number: int
    ligaid: int
    team: str
    results: list[dict[str, Any]]


class ErgebnisseResponse(BaseModel):
    """API response for ergebnisse."""

    liga_name: str
    liga_number: int
    ligaid: int
    ergebnisse: list[dict[str, Any]]


def _read_api_cache(ligaid: str, filename: str) -> dict[str, Any]:
    """Read cached JSON for API endpoints.

    Args:
        ligaid: League ID
        filename: Cache file name

    Returns:
        Raw JSON data

    Raises:
        HTTPException: If cache not found
    """
    try:
        return CacheDir(ligaid).read_json(filename)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e


@app.get(
    "/api/liga/{ligaid}/standings",
    response_model=StandingsResponse,
)
async def api_standings(
    ligaid: str = URLPath(..., pattern=r"\d+"),
    _api_key: str = Depends(validate_api_key),
) -> StandingsResponse:
    """Get standings as JSON (protected)."""
    raw = _read_api_cache(ligaid, "standings.json")
    return StandingsResponse(
        liga_name=raw["liga_name"],
        liga_number=raw["liga_number"],
        ligaid=raw["ligaid"],
        standings=raw.get("standings", []),
    )


@app.get(
    "/api/liga/{ligaid}/spielplan",
    response_model=ScheduleResponse,
)
async def api_schedule(
    ligaid: str = URLPath(..., pattern=r"\d+"),
    _api_key: str = Depends(validate_api_key),
) -> ScheduleResponse:
    """Get schedule as JSON (protected)."""
    raw = _read_api_cache(ligaid, "schedule.json")
    return ScheduleResponse(
        liga_name=raw["liga_name"],
        liga_number=raw["liga_number"],
        ligaid=raw["ligaid"],
        schedule=raw.get("schedule", []),
    )


@app.get(
    "/api/liga/{ligaid}/prognose",
    response_model=PredictResponse,
)
async def api_predict(
    ligaid: str = URLPath(..., pattern=r"\d+"),
    _api_key: str = Depends(validate_api_key),
) -> PredictResponse:
    """Get predictions as JSON (protected)."""
    raw = _read_api_cache(ligaid, "predict.json")
    return PredictResponse(
        liga_name=raw["liga_name"],
        liga_number=raw["liga_number"],
        ligaid=raw["ligaid"],
        predictions=raw.get("predictions", []),
        standings=raw.get("standings", []),
    )


@app.get(
    "/api/liga/{ligaid}/team/{team_slug}",
    response_model=TeamResponse,
)
async def api_team(
    ligaid: str = URLPath(..., pattern=r"\d+"),
    team_slug: str = URLPath(...),
    _api_key: str = Depends(validate_api_key),
) -> TeamResponse:
    """Get team data as JSON (protected)."""
    cache_dir = CacheDir(ligaid)
    try:
        meta = cache_dir.read_meta()
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Liga nicht gefunden",
        ) from e

    if team_slug not in meta.team_slugs:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        )

    try:
        raw = cache_dir.read_team_json(team_slug)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Teamdaten nicht gefunden",
        ) from e

    return TeamResponse(
        liga_name=raw["liga_name"],
        liga_number=raw["liga_number"],
        ligaid=raw["ligaid"],
        team=raw["team"],
        results=raw.get("results", []),
    )


@app.get(
    "/api/liga/{ligaid}/ergebnisse",
    response_model=ErgebnisseResponse,
)
async def api_ergebnisse(
    ligaid: str = URLPath(..., pattern=r"\d+"),
    _api_key: str = Depends(validate_api_key),
) -> ErgebnisseResponse:
    """Get game results as JSON (protected)."""
    raw = _read_api_cache(ligaid, "ergebnisse.json")
    return ErgebnisseResponse(
        liga_name=raw["liga_name"],
        liga_number=raw["liga_number"],
        ligaid=raw["ligaid"],
        ergebnisse=raw.get("ergebnisse", []),
    )
