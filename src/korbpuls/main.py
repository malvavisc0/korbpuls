"""FastAPI application with HTML routes and protected API routes."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
)
from fastapi import (
    Path as URLPath,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from korbpuls import presenters
from korbpuls.auth import validate_api_key
from korbpuls.cache import CacheDir, CacheMiss, LigaMeta
from korbpuls.korb_client import (
    KorbError,
    run_download,
    run_predict,
    run_schedule,
)
from korbpuls.korb_client import run_standings as korb_standings
from korbpuls.korb_client import run_team as korb_team
from korbpuls.slugify import slugify

BASE_DIR = Path(__file__).parent
app = FastAPI(title="korbPuls")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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

    Args:
        ligaid: League ID number
    """
    cache_dir = CacheDir(ligaid)
    cache_dir.ensure_exists()

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
        cache_dir.write_status("ready")
    except KorbError as e:
        cache_dir.write_status("error", str(e))
    except Exception as e:
        cache_dir.write_status("error", f"Unerwarteter Fehler: {e}")


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
    try:
        view = presenters.present_standings(ligaid)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e

    return templates.TemplateResponse(
        request,
        "standings.html",
        view.model_dump(),
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
    try:
        view = presenters.present_team(ligaid, team_slug)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Team nicht gefunden",
        ) from e

    return templates.TemplateResponse(
        request,
        "team.html",
        view.model_dump(),
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
    "/liga/{ligaid}/{liga_slug}/prognose",
    response_class=HTMLResponse,
)
async def prediction_page(
    request: Request,
    ligaid: str = URLPath(..., pattern=r"\d+"),
    liga_slug: str = URLPath(...),
) -> HTMLResponse:
    """Render prediction page."""
    try:
        view = presenters.present_prediction(ligaid)
    except CacheMiss as e:
        raise HTTPException(
            status_code=404,
            detail="Daten nicht gefunden",
        ) from e

    return templates.TemplateResponse(
        request,
        "prediction.html",
        view.model_dump(),
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
        {"message": "Fehler", "hint": exc.detail},
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
