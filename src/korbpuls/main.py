"""FastAPI application with HTML routes and protected API routes."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import nh3
import sentry_sdk
from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi import Path as URLPath
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel

from korbpuls import presenters
from korbpuls.ai import AIConfig, AppConfig, telemetry_enabled
from korbpuls.ai.generation import (
    run_matchup_preview,
    run_prediction_narrative,
    run_standings_narrative,
    run_team_analysis,
)
from korbpuls.ai.runtime import get_langfuse
from korbpuls.auth import validate_api_key
from korbpuls.cache import CACHE_ROOT, CacheDir, CacheMiss, LigaMeta
from korbpuls.korb_client import (
    KorbError,
    run_download,
    run_ergebnisse,
    run_predict,
    run_schedule,
)
from korbpuls.korb_client import run_standings as korb_standings
from korbpuls.korb_client import run_team as korb_team
from korbpuls.scheduler import (
    daily_refresh_loop,
    is_season_finished,
    schedule_has_results,
)
from korbpuls.slugify import slugify

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


async def _recover_ai_analyses() -> None:
    """Scan cached leagues on startup and re-trigger missing AI.

    Handles two scenarios:
    1. Server restarted mid-task — data is ready but AI never ran.
    2. AI failed on a previous run — failure markers exist.

    In both cases, failure markers are cleared and AI generation
    is re-attempted.  This runs once at startup as a background
    task so it does not block uvicorn from accepting requests.
    """
    config = AIConfig.from_env()
    if config is None:
        logger.info("AI not configured — skipping AI recovery scan")
        return

    if not CACHE_ROOT.exists():
        return

    league_dirs = [d for d in CACHE_ROOT.iterdir() if d.is_dir()]
    logger.info(
        "Startup recovery scan: checking %d cached league(s)...",
        len(league_dirs),
    )

    recovered = 0
    for league_dir in sorted(league_dirs):
        cache = CacheDir(league_dir.name)
        if cache.read_status().get("status") != "ready" or not cache.has_all_data():
            continue
        if await _recover_league_ai(config, cache):
            recovered += 1

    logger.info(
        "Startup recovery scan complete. (%d league(s) needed AI recovery)",
        recovered,
    )


async def _recover_standings_narrative(config: AIConfig, cache: CacheDir) -> bool:
    """Re-run standings narrative if missing or previously failed.

    Skipped during off-season (no games played yet) so empty leagues
    never trigger an LLM call or a failure marker.
    """
    if not presenters.standings_ai_eligible(cache.ligaid):
        return False
    failed = cache.read_standings_narrative_failed()
    if cache.is_standings_narrative_fresh() and not failed:
        return False
    if failed:
        cache.clear_standings_narrative_failed()
        logger.info(
            "Startup recovery: clearing standings narrative failure marker for liga %s",
            cache.ligaid,
        )
    await run_standings_narrative(config, cache.ligaid)
    return True


async def _recover_prediction_narrative(config: AIConfig, cache: CacheDir) -> bool:
    """Re-run prediction narrative when eligible and missing or failed."""
    try:
        view = presenters.present_prediction(cache.ligaid)
    except CacheMiss:
        return False
    if not view.prediction_eligible:
        return False
    failed = cache.read_ai_prediction_failed()
    if cache.is_ai_prediction_fresh() and not failed:
        return False
    if failed:
        cache.clear_ai_prediction_failed()
        logger.info(
            "Startup recovery: clearing prediction narrative "
            "failure marker for liga %s",
            cache.ligaid,
        )
    await run_prediction_narrative(config, cache.ligaid)
    return True


async def _recover_league_ai(config: AIConfig, cache: CacheDir) -> bool:
    """Recover all AI artifacts for one league. Returns True if any ran."""
    standings_recovered = await _recover_standings_narrative(config, cache)
    prediction_recovered = await _recover_prediction_narrative(config, cache)
    return standings_recovered or prediction_recovered


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: recover AI analyses and start scheduler."""
    recovery_task = asyncio.create_task(_recover_ai_analyses())
    scheduler_task = asyncio.create_task(daily_refresh_loop(_fetch_and_auto_generate))
    yield
    # Ensure background tasks complete on shutdown
    for task in (recovery_task, scheduler_task):
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    # Flush any pending Langfuse events so traces are not lost
    lf = get_langfuse()
    if lf is not None:
        lf.flush()


app = FastAPI(title="korbPuls", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app_config = AppConfig.from_env()
if app_config is not None:
    sentry_sdk.init(
        app_config.sentry_dsn,
        send_default_pii=True,
        max_request_body_size="always",
        traces_sample_rate=0,
        send_client_reports=False,
        auto_session_tracking=False,
    )
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["app_version"] = __import__("korbpuls").__version__

# AI output is rendered as HTML but originates from an LLM fed with
# externally-controlled text (team names, scraped data).  Sanitize to
# a strict allowlist before it ever reaches a browser.
_AI_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "h3",
    "h4",
    "h5",
    "a",
    "span",
    "code",
    "blockquote",
}
_AI_ALLOWED_ATTRS = {"a": {"href", "title"}}


def ai_html(value: str) -> Markup:
    """Sanitize LLM-generated HTML for safe rendering."""
    return Markup(
        nh3.clean(value or "", tags=_AI_ALLOWED_TAGS, attributes=_AI_ALLOWED_ATTRS)
    )


templates.env.filters["ai_html"] = ai_html

_analytics_url = os.environ.get("RYBBIT_SCRIPT_URL", "") if telemetry_enabled() else ""
_analytics_site_id = os.environ.get("RYBBIT_SITE_ID", "") if _analytics_url else ""
templates.env.globals["analytics_script_url"] = _analytics_url
templates.env.globals["analytics_site_id"] = _analytics_site_id


def validate_ligaid_format(ligaid: str) -> bool:
    """Validate ligaid is digits only.

    Args:
        ligaid: String to validate

    Returns:
        True if ligaid contains only digits
    """
    return bool(re.fullmatch(r"\d+", ligaid))


def format_datetime(dt: datetime) -> str:
    """Format a datetime for display.

    Args:
        dt: Naive or aware datetime

    Returns:
        German-formatted date string
    """
    return dt.strftime("%d.%m.%Y %H:%M")


# One in-flight fetch per league: deduplicates concurrent refreshes
# triggered by user buttons, the loading-page retry, and the scheduler.
_fetch_claims_guard = threading.Lock()
_inflight_fetches: set[str] = set()


def _try_claim_fetch(ligaid: str) -> bool:
    """Claim exclusive fetch rights for a league.

    Returns:
        True if claimed (caller must run the fetch and release),
        False if a fetch for this league is already running.
    """
    with _fetch_claims_guard:
        if ligaid in _inflight_fetches:
            return False
        _inflight_fetches.add(ligaid)
        return True


def _release_fetch(ligaid: str) -> None:
    """Release the fetch claim for a league."""
    with _fetch_claims_guard:
        _inflight_fetches.discard(ligaid)


def fetch_and_cache_league(ligaid: str) -> bool:
    """Fetch all league data from korb and cache to disk.

    Runs as a background task. Handles errors internally by
    writing status.json instead of propagating exceptions.

    Preserves existing AI analyses when the downloaded data
    is identical to the previously cached data.

    Args:
        ligaid: League ID number

    Returns:
        True if data changed (or first fetch), False otherwise.
    """
    cache_dir = CacheDir(ligaid)
    cache_dir.ensure_exists()

    if not _try_claim_fetch(ligaid):
        logger.info("Fetch already in flight for liga %s — skipping", ligaid)
        return False
    try:
        return _fetch_and_cache_locked(ligaid, cache_dir)
    finally:
        _release_fetch(ligaid)


def _old_fetch_state(
    cache_dir: CacheDir,
) -> tuple[str, bool, dict[str, Any]]:
    """Read the previous hash, archive flag, and schedule before overwrite."""
    old_hash = cache_dir.compute_data_hash()
    old_archived = False
    with suppress(CacheMiss, FileNotFoundError):
        old_archived = cache_dir.read_meta().archived
    previous_schedule: dict[str, Any] = {}
    with suppress(CacheMiss, FileNotFoundError):
        previous_schedule = cache_dir.read_json("schedule.json")
    return old_hash, old_archived, previous_schedule


def _download_standings(
    ligaid: str,
    cache_dir: CacheDir,
) -> tuple[dict[str, Any], str, str]:
    """Fetch and cache standings, returning data, name, and slug."""
    data = korb_standings(ligaid)
    cache_dir.write_json("standings.json", data)
    league_name: str = data.get("liga_name", "")
    return data, league_name, slugify(league_name)


def _download_schedule(ligaid: str, cache_dir: CacheDir) -> dict[str, Any]:
    """Fetch and cache the schedule."""
    data = run_schedule(ligaid)
    cache_dir.write_json("schedule.json", data)
    return data


def _download_ergebnisse(ligaid: str, cache_dir: CacheDir) -> dict[str, Any]:
    """Fetch and cache game results."""
    data = run_ergebnisse(ligaid)
    cache_dir.write_json("ergebnisse.json", data)
    return data


def _download_predict(
    ligaid: str,
    cache_dir: CacheDir,
    league_name: str,
    standings_data: dict[str, Any],
) -> dict[str, Any]:
    """Fetch and cache predictions, tolerating finalized seasons."""
    try:
        data = run_predict(ligaid)
    except KorbError:
        data = {
            "liga_name": league_name,
            "liga_number": standings_data.get("liga_number", 0),
            "ligaid": int(ligaid),
            "predictions": [],
            "standings": [],
            "finalized": True,
        }
    cache_dir.write_json("predict.json", data)
    return data


def _download_teams(
    ligaid: str,
    cache_dir: CacheDir,
    team_slugs: dict[str, str],
) -> None:
    """Fetch and cache per-team results, skipping individual failures."""
    for slug, team_name in team_slugs.items():
        try:
            cache_dir.write_team_json(slug, korb_team(ligaid, team_name))
        except KorbError:
            logger.warning("Could not fetch team data for %s", team_name)


def _remove_orphaned_team_files(
    cache_dir: CacheDir,
    team_slugs: dict[str, str],
) -> None:
    """Remove cached team files for teams that left the league."""
    if not cache_dir.teams_path.exists():
        return
    for path in cache_dir.teams_path.iterdir():
        if (
            path.suffix == ".json"
            and not cache_dir.is_ai_file(path)
            and path.stem not in team_slugs
        ):
            path.unlink(missing_ok=True)


def _season_complete(
    schedule_data: dict[str, Any],
    ergebnisse_data: dict[str, Any],
) -> bool:
    """Whether a schedule is finished and every fixture has a result."""
    return (
        bool(schedule_data.get("schedule"))
        and is_season_finished(schedule_data)
        and schedule_has_results(schedule_data, ergebnisse_data)
    )


def _build_league_meta(
    *,
    ligaid: str,
    league_name: str,
    liga_slug: str,
    team_slugs: dict[str, str],
    old_archived: bool,
    previous_schedule: dict[str, Any],
    schedule_data: dict[str, Any],
    ergebnisse_data: dict[str, Any],
) -> LigaMeta:
    """Build league metadata, preserving the sticky archived flag."""
    return LigaMeta(
        ligaid=ligaid,
        league_name=league_name,
        liga_slug=liga_slug,
        cached_at=format_datetime(datetime.now(ZoneInfo("Europe/Berlin"))),
        team_slugs=team_slugs,
        archived=old_archived
        or _season_complete(previous_schedule, ergebnisse_data)
        or _season_complete(schedule_data, ergebnisse_data),
    )


def _sync_ai_files(cache_dir: CacheDir, old_hash: str) -> bool:
    """Preserve AI files when data is unchanged, otherwise clear them."""
    data_changed = not (old_hash and old_hash == cache_dir.compute_data_hash())
    if not data_changed:
        cache_dir.touch_ai_files()
        logger.info(
            "Data unchanged for liga %s — AI analyses preserved",
            cache_dir.ligaid,
        )
        return False
    cache_dir.clear_ai_files()
    if old_hash:
        logger.info(
            "Data changed for liga %s — AI analyses invalidated",
            cache_dir.ligaid,
        )
    return True


def _fetch_and_cache_locked(ligaid: str, cache_dir: CacheDir) -> bool:
    """Run the actual league fetch (caller holds the fetch claim).

    Writes are atomic, and existing data files are overwritten in
    place rather than deleted up front, so readers keep seeing the
    previous complete dataset while a refresh is running.
    """
    old_hash, old_archived, previous_schedule = _old_fetch_state(cache_dir)

    try:
        run_download(ligaid)
        standings_data, league_name, liga_slug = _download_standings(
            ligaid,
            cache_dir,
        )
        schedule_data = _download_schedule(ligaid, cache_dir)
        team_slugs = presenters.collect_team_slugs(standings_data, schedule_data)
        ergebnisse_data = _download_ergebnisse(ligaid, cache_dir)
        _download_predict(ligaid, cache_dir, league_name, standings_data)
        _download_teams(ligaid, cache_dir, team_slugs)
        _remove_orphaned_team_files(cache_dir, team_slugs)

        meta = _build_league_meta(
            ligaid=ligaid,
            league_name=league_name,
            liga_slug=liga_slug,
            team_slugs=team_slugs,
            old_archived=old_archived,
            previous_schedule=previous_schedule,
            schedule_data=schedule_data,
            ergebnisse_data=ergebnisse_data,
        )
        cache_dir.write_meta(meta)
        data_changed = _sync_ai_files(cache_dir, old_hash)
        cache_dir.write_status("ready")
        return data_changed
    except KorbError as exc:
        cache_dir.write_status("error", str(exc))
        return False
    except Exception as exc:
        cache_dir.write_status("error", f"Unerwarteter Fehler: {exc}")
        return False


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Health check endpoint for monitoring and Docker."""
    return {"status": "ok"}


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

    # Archived seasons are frozen — no re-fetch allowed
    with suppress(CacheMiss, FileNotFoundError):
        meta = cache_dir.read_meta()
        if meta.archived:
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

    # Start background fetch and redirect to loading page.
    # Existing data stays in place (atomic overwrite on success) so
    # visitors keep seeing the previous dataset during the refresh.
    cache_dir.ensure_exists()
    cache_dir.write_status("pending")
    background_tasks.add_task(_fetch_and_auto_generate, ligaid)
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

    with suppress(CacheMiss, FileNotFoundError):
        if cache_dir.read_meta().archived:
            raise HTTPException(
                status_code=403,
                detail="Saison ist archiviert — keine Aktualisierung mehr möglich.",
            )

    cache_dir.ensure_exists()
    cache_dir.write_status("pending")
    background_tasks.add_task(_fetch_and_auto_generate, ligaid)
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
    if not cache_dir.liga_exists():
        raise HTTPException(status_code=404, detail="Liga nicht gefunden")

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
        # browser followed the redirect.  Auto-retry once per fetch
        # cycle (tracked via attempts in status.json) so fast,
        # permanent failures (e.g. bogus league IDs) can't turn the
        # loading page into an infinite retry loop.
        status_path = cache_dir.base_path / "status.json"
        attempts = int(status.get("attempts", 0))
        if status_path.exists() and attempts < 1:
            age = time.time() - status_path.stat().st_mtime
            if age < 10:
                cache_dir.ensure_exists()
                cache_dir.write_status("pending", attempts=attempts + 1)
                background_tasks.add_task(
                    _fetch_and_auto_generate,
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

    # Stale: pending for > 10 minutes — treat as interrupted
    # task (e.g. server restart) and auto-retry the full fetch.
    if status["status"] == "stale":
        cache_dir.ensure_exists()
        cache_dir.write_status("pending")
        background_tasks.add_task(
            _fetch_and_auto_generate,
            ligaid,
        )
        return templates.TemplateResponse(
            request,
            "loading.html",
            {"ligaid": ligaid},
        )

    # unknown
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

    if cache.is_ai_generation_pending("analysis", team_slug):
        return RedirectResponse(url=f"{team_url}?generating=1", status_code=302)

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
        run_team_analysis,
        config,
        ligaid,
        team_slug,
        team_name,
    )

    return RedirectResponse(url=f"{team_url}?generating=1", status_code=302)


async def _fetch_and_auto_generate(ligaid: str) -> None:
    """Background: fetch data, then auto-generate AI.

    AI generation runs when:
    1. Data changed (new or updated league data), OR
    2. Data unchanged but AI analyses are missing or previously
       failed (e.g. server restart, transient LLM failure).

    In case 2, failure markers are cleared before retrying so
    the AI gets a fresh attempt.
    """
    data_changed = await asyncio.to_thread(
        fetch_and_cache_league,
        ligaid,
    )

    config = AIConfig.from_env()
    if config is None:
        return

    cache = CacheDir(ligaid)
    if cache.read_status()["status"] != "ready":
        return

    # Determine if AI generation is needed
    ai_needed = data_changed
    if not ai_needed:
        standings_missing = not cache.is_standings_narrative_fresh()
        standings_failed = cache.read_standings_narrative_failed()
        ai_needed = standings_missing or standings_failed

    if not ai_needed:
        return

    # Clear failure markers before retrying
    if cache.read_standings_narrative_failed():
        cache.clear_standings_narrative_failed()

    # Auto-generate standings narrative
    await run_standings_narrative(config, ligaid)

    # Auto-generate prediction narrative (if eligible)
    try:
        view = presenters.present_prediction(ligaid)
        if view.prediction_eligible:
            if cache.read_ai_prediction_failed():
                cache.clear_ai_prediction_failed()
            await run_prediction_narrative(config, ligaid)
    except CacheMiss:
        pass


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


def _matchup_generation_redirect(
    cache: CacheDir,
    home_slug: str,
    away_slug: str,
    matchup_url: str,
) -> RedirectResponse | None:
    """Return a redirect when a preview exists or is already generating."""
    if cache.is_matchup_preview_fresh(home_slug, away_slug):
        return RedirectResponse(url=matchup_url, status_code=302)
    preview_key = f"{home_slug}_vs_{away_slug}_preview"
    if cache.is_ai_generation_pending("preview", preview_key):
        return RedirectResponse(
            url=f"{matchup_url}?generating=1",
            status_code=302,
        )
    return None


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

    try:
        meta = cache.read_meta()
    except CacheMiss:
        raise HTTPException(status_code=404, detail="Liga nicht gefunden") from None
    home_name = meta.team_slugs.get(home_slug)
    away_name = meta.team_slugs.get(away_slug)
    if not home_name or not away_name:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        )

    # Block generation for already-played games or finished seasons
    try:
        view = presenters.present_matchup(
            ligaid,
            home_slug,
            away_slug,
            ai_enabled=True,
        )
        if view.is_played or view.is_finished:
            raise HTTPException(
                status_code=403,
                detail="Dieses Spiel wurde bereits ausgetragen.",
            )
        if not view.ai_eligible:
            raise HTTPException(
                status_code=403,
                detail=view.ai_ineligible_reason,
            )
    except CacheMiss:
        pass

    redirect = _matchup_generation_redirect(
        cache,
        home_slug,
        away_slug,
        matchup_url,
    )
    if redirect is not None:
        return redirect

    cache.clear_matchup_preview_failed(home_slug, away_slug)
    background_tasks.add_task(
        run_matchup_preview,
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
