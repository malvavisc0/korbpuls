"""Transform cached JSON into template view models and compute metrics."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from korbpuls.cache import CacheDir, CacheMiss
from korbpuls.slugify import slugify


class StandingsRow(BaseModel):
    """A single row in the standings table."""

    rank: int
    name: str
    slug: str
    gp: int
    w: int
    losses: int
    d: int
    pf: int
    pa: int
    diff: int
    pts: int
    avg_pf: float
    avg_pa: float


class StandingsView(BaseModel):
    """View model for the standings page."""

    liga_name: str
    liga_slug: str
    ligaid: str
    cached_at: str
    rows: list[StandingsRow]
    is_finished: bool = False
    prediction_eligible: bool = True


class GameResult(BaseModel):
    """A single game result for a team."""

    opponent: str
    opponent_slug: str
    home_away: str  # "Heim" or "Gast"
    our_score: int
    opp_score: int
    diff: int
    result: str  # "Sieg", "Niederlage", "Unentschieden"


class TeamMetrics(BaseModel):
    """Computed quality metrics for a team."""

    win_rate: float  # percentage
    avg_win_margin: float
    avg_loss_margin: float
    blowouts: int  # wins by >= 15
    close_games: int  # games decided by <= 5
    volatility: float  # stddev of point differential
    last_5: str  # e.g., "4 Siege, 1 Niederlage"
    current_streak: str  # e.g., "3 Siege in Folge"


class ScheduleGame(BaseModel):
    """A single game in the schedule."""

    nr: int
    day: int
    date: str
    home: str
    home_slug: str
    away: str
    away_slug: str
    venue: str
    cancelled: bool


class ScheduleView(BaseModel):
    """View model for the schedule page."""

    liga_name: str
    liga_slug: str
    ligaid: str
    games: list[ScheduleGame]
    is_finished: bool = False
    prediction_eligible: bool = True


class TeamView(BaseModel):
    """View model for the team detail page."""

    team_name: str
    team_slug: str
    liga_name: str
    liga_slug: str
    ligaid: str
    rank: int
    total_teams: int
    record: str
    points_summary: str
    avg_summary: str
    avg_pf: float
    avg_pa: float
    total_diff: int
    metrics: TeamMetrics
    results: list[GameResult]
    upcoming_games: list[ScheduleGame]
    is_finished: bool = False
    ai_analysis: str | None = None
    ai_enabled: bool = False
    ai_analysis_eligible: bool = False
    ai_analysis_ineligible_reason: str | None = None


class PredictionGame(BaseModel):
    """A predicted game result."""

    home: str
    home_slug: str
    away: str
    away_slug: str
    home_score: int
    away_score: int
    winner: str  # "home" or "away"


class PredictionStandingsRow(BaseModel):
    """A row in the predicted final standings."""

    rank: int
    name: str
    slug: str
    gp: int
    w: int
    losses: int
    d: int
    pf: int
    pa: int
    diff: int
    pts: int
    avg_pf: float
    avg_pa: float


class PredictionView(BaseModel):
    """View model for the prediction page."""

    liga_name: str
    liga_slug: str
    ligaid: str
    cached_at: str
    is_finished: bool
    prediction_eligible: bool = True
    prediction_ineligible_reason: str | None = None
    predictions: list[PredictionGame]
    standings: list[PredictionStandingsRow]
    ai_table: str | None = None
    ai_explanation: str | None = None
    ai_enabled: bool = False


_RESULT_MAP = {"W": "Sieg", "L": "Niederlage", "D": "Unentschieden"}


def _result_to_german(result: str) -> str:
    """Convert W/L/D result code to German display text.

    Args:
        result: 'W', 'L', or 'D'

    Returns:
        German translation
    """
    return _RESULT_MAP.get(result, result)


def _home_away_to_german(home_away: str) -> str:
    """Convert Home/Away to German.

    Args:
        home_away: 'Home' or 'Away'

    Returns:
        German translation
    """
    return "Heim" if home_away == "Home" else "Gast"


def _parse_schedule_game(game: dict[str, Any]) -> ScheduleGame:
    """Parse a raw schedule game dict into a ScheduleGame model.

    Args:
        game: Raw game dict from korb JSON

    Returns:
        ScheduleGame model
    """
    return ScheduleGame(
        nr=game["nr"],
        day=game["day"],
        date=game["date"],
        home=game["home"],
        home_slug=slugify(game["home"]),
        away=game["away"],
        away_slug=slugify(game["away"]),
        venue=game["venue"],
        cancelled=game.get("cancelled", False),
    )


def _parse_game_result(raw: dict[str, Any]) -> GameResult:
    """Parse a raw result dict into a GameResult model.

    Args:
        raw: Raw result dict from korb JSON

    Returns:
        GameResult model
    """
    return GameResult(
        opponent=raw["opponent"],
        opponent_slug=slugify(raw["opponent"]),
        home_away=_home_away_to_german(raw["home_away"]),
        our_score=raw["our_score"],
        opp_score=raw["opp_score"],
        diff=raw["diff"],
        result=_result_to_german(raw["result"]),
    )


def _compute_streak(results: list[GameResult]) -> str:
    """Compute current streak from most recent result backward.

    Args:
        results: List of game results, most recent last

    Returns:
        German string describing current streak, e.g. "3 Siege in Folge"
    """
    if not results:
        return ""

    # Work backward from most recent result
    streak_count = 0
    first_result = results[-1].result

    for r in reversed(results):
        if r.result == first_result:
            streak_count += 1
        else:
            break

    if streak_count == 0:
        return ""
    elif streak_count == 1:
        return f"1 {first_result}"
    else:
        if first_result == "Sieg":
            return f"{streak_count} Siege in Folge"
        elif first_result == "Niederlage":
            return f"{streak_count} Niederlagen in Folge"
        else:
            return f"{streak_count} {first_result}"


def _compute_metrics(results: list[GameResult]) -> TeamMetrics:
    """Compute quality metrics from game results.

    Args:
        results: List of game results

    Returns:
        Computed TeamMetrics
    """
    if not results:
        return TeamMetrics(
            win_rate=0.0,
            avg_win_margin=0.0,
            avg_loss_margin=0.0,
            blowouts=0,
            close_games=0,
            volatility=0.0,
            last_5="0 Siege, 0 Niederlagen",
            current_streak="",
        )

    wins = [r for r in results if r.result == "Sieg"]
    losses = [r for r in results if r.result == "Niederlage"]

    win_rate = (len(wins) / len(results)) * 100

    win_margins = [r.diff for r in wins]
    loss_margins = [abs(r.diff) for r in losses]

    avg_win = statistics.mean(win_margins) if win_margins else 0.0
    avg_loss = statistics.mean(loss_margins) if loss_margins else 0.0

    blowouts = sum(1 for r in wins if r.diff >= 15)
    close_games = sum(1 for r in results if abs(r.diff) <= 5)

    diffs = [r.diff for r in results]
    volatility = statistics.stdev(diffs) if len(diffs) > 1 else 0.0

    last_5_results = results[-5:]
    wins_l5 = sum(1 for r in last_5_results if r.result == "Sieg")
    losses_l5 = sum(1 for r in last_5_results if r.result == "Niederlage")

    last_5 = f"{wins_l5} Siege, {losses_l5} Niederlagen"
    current_streak = _compute_streak(results)

    return TeamMetrics(
        win_rate=win_rate,
        avg_win_margin=avg_win,
        avg_loss_margin=avg_loss,
        blowouts=blowouts,
        close_games=close_games,
        volatility=volatility,
        last_5=last_5,
        current_streak=current_streak,
    )


def _compute_summary(
    results: list[GameResult],
    team_name: str,
    cache: CacheDir,
) -> tuple[str, str, str]:
    """Compute record, points summary, and average summary strings.

    Args:
        results: Parsed game results
        team_name: Full team name for standings lookup
        cache: CacheDir to read standings from

    Returns:
        Tuple of (record, points_summary, avg_summary)
    """
    total = len(results)
    wins = sum(1 for r in results if r.result == "Sieg")
    losses = sum(1 for r in results if r.result == "Niederlage")
    draws = sum(1 for r in results if r.result == "Unentschieden")

    record = f"{wins} Siege · {losses} Niederlagen"
    if draws > 0:
        record += f" · {draws} Unentschieden"
    record += f" · {total} Spiele"

    # Try to get stats from standings for accuracy
    pts_summary, avg_summary = _summary_from_standings(team_name, cache)
    if not pts_summary:
        pts_summary, avg_summary = _summary_from_results(results)

    return record, pts_summary, avg_summary


def _summary_from_standings(team_name: str, cache: CacheDir) -> tuple[str, str]:
    """Extract points/avg summary from standings data.

    Args:
        team_name: Full team name
        cache: CacheDir to read standings from

    Returns:
        Tuple of (points_summary, avg_summary), empty if not found
    """
    try:
        standings_data = cache.read_json("standings.json")
    except CacheMiss:
        return "", ""

    for team in standings_data.get("standings", []):
        if team["name"] == team_name:
            pts = (
                f"{team['pf']} erzielt · {team['pa']} kassiert"
                f" · Differenz {team['diff']:+d}"
            )
            avg = f"{team['avg_pf']} erzielt" f" · {team['avg_pa']} kassiert"
            return pts, avg
    return "", ""


def _summary_from_results(
    results: list[GameResult],
) -> tuple[str, str]:
    """Compute points/avg summary from raw results.

    Args:
        results: List of game results

    Returns:
        Tuple of (points_summary, avg_summary)
    """
    total = len(results)
    total_pf = sum(r.our_score for r in results)
    total_pa = sum(r.opp_score for r in results)
    diff = total_pf - total_pa
    pts = f"{total_pf} erzielt · {total_pa} kassiert · Diff {diff:+d}"

    avg_pf = total_pf / total if total else 0.0
    avg_pa = total_pa / total if total else 0.0
    avg = f"{avg_pf:.1f} erzielt · {avg_pa:.1f} kassiert"

    return pts, avg


def _get_team_rank_and_total(team_name: str, cache: CacheDir) -> tuple[int, int]:
    """Look up team's current rank and total team count from standings.

    Args:
        team_name: Full team name
        cache: CacheDir to read standings from

    Returns:
        Tuple of (rank, total_teams), defaults to (0, 0) if not found
    """
    try:
        standings_data = cache.read_json("standings.json")
    except CacheMiss:
        return 0, 0

    standings_list = standings_data.get("standings", [])
    total_teams = len(standings_list)

    for rank, team in enumerate(standings_list, start=1):
        if team["name"] == team_name:
            return rank, total_teams

    return 0, total_teams


def _get_upcoming_games(
    schedule_data: dict[str, Any], team_name: str
) -> list[ScheduleGame]:
    """Filter upcoming non-cancelled games for a team.

    Args:
        schedule_data: Raw schedule JSON
        team_name: Full team name

    Returns:
        Sorted list of upcoming ScheduleGame entries
    """
    now = datetime.now(UTC)
    upcoming: list[ScheduleGame] = []

    for game in schedule_data.get("schedule", []):
        if game["home"] != team_name and game["away"] != team_name:
            continue
        if game.get("cancelled", False):
            continue
        try:
            game_date = datetime.strptime(game["date"], "%d.%m.%Y %H:%M").replace(
                tzinfo=UTC
            )
            if game_date > now:
                upcoming.append(_parse_schedule_game(game))
        except ValueError:
            continue

    upcoming.sort(key=lambda g: g.date)
    return upcoming


def _is_season_finished(schedule_games: list[ScheduleGame]) -> bool:
    """Detect if season is finished (no future non-cancelled games).

    Args:
        schedule_games: List of scheduled games

    Returns:
        True if season is finished, False if still running
    """
    now = datetime.now(UTC)
    for game in schedule_games:
        if game.cancelled:
            continue
        try:
            game_date = datetime.strptime(game.date, "%d.%m.%Y %H:%M").replace(
                tzinfo=UTC
            )
            if game_date > now:
                return False
        except ValueError:
            continue
    return True


def _check_prediction_eligible(
    cache: CacheDir,
    *,
    schedule_games: list[ScheduleGame] | None = None,
) -> tuple[bool, str | None]:
    """Check whether predictions are available for this league.

    Conditions:
    1. Season must not be finished.
    2. At least half of the total season matches must have
       been played (double round-robin: n × (n-1) total).

    Args:
        cache: CacheDir for the league
        schedule_games: Pre-loaded schedule games to avoid
            redundant file reads. Loaded from cache when *None*.

    Returns:
        Tuple of (eligible, reason). reason is a German error
        message when not eligible, None when eligible.
    """
    if schedule_games is None:
        schedule_data = cache.read_json("schedule.json")
        schedule_games = [
            _parse_schedule_game(g) for g in schedule_data.get("schedule", [])
        ]
    if _is_season_finished(schedule_games):
        return False, (
            "Die Saison ist bereits beendet. "
            "Prognosen sind nicht mehr nötig — "
            "der Endstand steht auf der Tabellenseite."
        )

    standings_data = cache.read_json("standings.json")
    teams = standings_data.get("standings", [])
    n = len(teams)
    if n < 2:
        return False, "Zu wenige Teams für eine Prognose."

    total_gp = sum(t.get("gp", 0) for t in teams)
    games_played = total_gp // 2
    total_season_games = n * (n - 1)
    half = total_season_games // 2

    if games_played < half:
        return False, (
            f"Noch nicht genug Spieldaten für eine Prognose. "
            f"Bisher {games_played} von {total_season_games} "
            f"Spielen absolviert — mindestens {half} nötig."
        )

    return True, None


def present_standings(ligaid: str) -> StandingsView:
    """Build view model for standings page.

    Args:
        ligaid: League ID

    Returns:
        StandingsView for template rendering

    Raises:
        CacheMiss: If cache files not found
    """
    cache = CacheDir(ligaid)
    meta = cache.read_meta()
    data = cache.read_json("standings.json")

    rows: list[StandingsRow] = []
    for rank, team in enumerate(data.get("standings", []), start=1):
        rows.append(
            StandingsRow(
                rank=rank,
                name=team["name"],
                slug=slugify(team["name"]),
                gp=team["gp"],
                w=team["w"],
                losses=team["l"],
                d=team["d"],
                pf=team["pf"],
                pa=team["pa"],
                diff=team["diff"],
                pts=team["pts"],
                avg_pf=team["avg_pf"],
                avg_pa=team["avg_pa"],
            )
        )

    # Load schedule once for both is_finished and eligibility
    schedule_data = cache.read_json("schedule.json")
    schedule_games = [
        _parse_schedule_game(g) for g in schedule_data.get("schedule", [])
    ]
    is_finished = _is_season_finished(schedule_games)
    eligible, _ = _check_prediction_eligible(
        cache,
        schedule_games=schedule_games,
    )

    return StandingsView(
        liga_name=meta.league_name,
        liga_slug=meta.liga_slug,
        ligaid=meta.ligaid,
        cached_at=meta.cached_at,
        rows=rows,
        is_finished=is_finished,
        prediction_eligible=eligible,
    )


def present_team(ligaid: str, team_slug: str, *, ai_enabled: bool = False) -> TeamView:
    """Build view model for team page.

    Args:
        ligaid: League ID
        team_slug: Team slug string
        ai_enabled: Whether AI features are enabled

    Returns:
        TeamView for template rendering

    Raises:
        CacheMiss: If cache files not found
    """
    cache = CacheDir(ligaid)
    meta = cache.read_meta()

    team_name = meta.team_slugs.get(team_slug)
    if not team_name:
        raise CacheMiss(f"Team slug not found: {team_slug}")

    team_data = cache.read_team_json(team_slug)
    results = [_parse_game_result(r) for r in team_data.get("results", [])]

    record, pts_summary, avg_summary = _compute_summary(
        results,
        team_name,
        cache,
    )
    metrics = _compute_metrics(results)
    rank, total_teams = _get_team_rank_and_total(team_name, cache)

    # Compute clean numeric averages and diff for stat cards
    total_games = len(results)
    total_pf = sum(r.our_score for r in results)
    total_pa = sum(r.opp_score for r in results)
    avg_pf = round(total_pf / total_games, 1) if total_games else 0.0
    avg_pa = round(total_pa / total_games, 1) if total_games else 0.0
    total_diff = total_pf - total_pa

    schedule_data = cache.read_json("schedule.json")
    upcoming = _get_upcoming_games(schedule_data, team_name)

    # Check if season is finished
    all_schedule_games = [
        _parse_schedule_game(g) for g in schedule_data.get("schedule", [])
    ]
    is_finished = _is_season_finished(all_schedule_games)

    ai_analysis = None
    if ai_enabled:
        ai_analysis = cache.read_ai_analysis(team_slug)

    # AI analysis eligibility: need >= 4 games
    min_games = 4
    games_played = len(results)
    ai_eligible = ai_enabled and games_played >= min_games
    ai_reason: str | None = None
    if ai_enabled and not ai_eligible:
        ai_reason = (
            f"Mindestens {min_games} Spiele nötig "
            f"— bisher {games_played} absolviert."
        )

    return TeamView(
        team_name=team_name,
        team_slug=team_slug,
        liga_name=meta.league_name,
        liga_slug=meta.liga_slug,
        ligaid=meta.ligaid,
        rank=rank,
        total_teams=total_teams,
        record=record,
        points_summary=pts_summary,
        avg_summary=avg_summary,
        avg_pf=avg_pf,
        avg_pa=avg_pa,
        total_diff=total_diff,
        metrics=metrics,
        results=results,
        upcoming_games=upcoming,
        is_finished=is_finished,
        ai_analysis=ai_analysis,
        ai_enabled=ai_enabled,
        ai_analysis_eligible=ai_eligible,
        ai_analysis_ineligible_reason=ai_reason,
    )


def present_schedule(ligaid: str) -> ScheduleView:
    """Build view model for schedule page.

    Args:
        ligaid: League ID

    Returns:
        ScheduleView for template rendering

    Raises:
        CacheMiss: If cache files not found
    """
    cache = CacheDir(ligaid)
    meta = cache.read_meta()
    data = cache.read_json("schedule.json")

    games = [_parse_schedule_game(g) for g in data.get("schedule", [])]
    games.sort(key=lambda g: g.date)

    is_finished = _is_season_finished(games)
    eligible, _ = _check_prediction_eligible(
        cache,
        schedule_games=games,
    )

    return ScheduleView(
        liga_name=meta.league_name,
        liga_slug=meta.liga_slug,
        ligaid=meta.ligaid,
        games=games,
        is_finished=is_finished,
        prediction_eligible=eligible,
    )


def present_prediction(ligaid: str, *, ai_enabled: bool = False) -> PredictionView:
    """Build view model for prediction page.

    Args:
        ligaid: League ID
        ai_enabled: Whether AI features are enabled

    Returns:
        PredictionView for template rendering

    Raises:
        CacheMiss: If cache files not found
    """
    cache = CacheDir(ligaid)
    meta = cache.read_meta()
    data = cache.read_json("predict.json")

    # Load schedule once for both is_finished and eligibility
    schedule_data = cache.read_json("schedule.json")
    schedule_games = [
        _parse_schedule_game(g) for g in schedule_data.get("schedule", [])
    ]
    is_finished = _is_season_finished(schedule_games)
    eligible, reason = _check_prediction_eligible(
        cache,
        schedule_games=schedule_games,
    )

    # Build predictions
    predictions = [
        PredictionGame(
            home=p["home"],
            home_slug=slugify(p["home"]),
            away=p["away"],
            away_slug=slugify(p["away"]),
            home_score=p["home_score"],
            away_score=p["away_score"],
            winner=p["winner"],
        )
        for p in data.get("predictions", [])
    ]

    # Build predicted standings
    standings = [
        PredictionStandingsRow(
            rank=rank,
            name=t["name"],
            slug=slugify(t["name"]),
            gp=t["gp"],
            w=t["w"],
            losses=t["l"],
            d=t["d"],
            pf=t["pf"],
            pa=t["pa"],
            diff=t["diff"],
            pts=t["pts"],
            avg_pf=t["avg_pf"],
            avg_pa=t["avg_pa"],
        )
        for rank, t in enumerate(data.get("standings", []), start=1)
    ]

    ai_table = None
    ai_explanation = None
    # Only load AI prediction if eligible and active
    if ai_enabled and eligible:
        narrative = cache.read_ai_prediction()
        if narrative:
            ai_table = narrative.get("table")
            ai_explanation = narrative.get("explanation")

    return PredictionView(
        liga_name=meta.league_name,
        liga_slug=meta.liga_slug,
        ligaid=meta.ligaid,
        cached_at=meta.cached_at,
        is_finished=is_finished,
        prediction_eligible=eligible,
        prediction_ineligible_reason=reason,
        predictions=predictions,
        standings=standings,
        ai_table=ai_table,
        ai_explanation=ai_explanation,
        ai_enabled=ai_enabled,
    )
