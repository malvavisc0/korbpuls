"""Background scheduler for daily league data refresh."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from korbpuls.cache import CacheDir, CacheMiss

logger = logging.getLogger(__name__)

# Daily refresh time in Europe/Berlin
_REFRESH_HOUR = 17
_REFRESH_TZ = ZoneInfo("Europe/Berlin")

# Seconds to wait between league refreshes to throttle korb CLI
_LEAGUE_DELAY = 5.0


def _seconds_until_next_refresh() -> float:
    """Calculate seconds until the next daily refresh time.

    Returns:
        Number of seconds until 17:00 Europe/Berlin.
    """
    now = datetime.now(_REFRESH_TZ)
    target = now.replace(hour=_REFRESH_HOUR, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _is_season_finished(schedule_data: dict[str, Any]) -> bool:
    """Check whether all scheduled games are in the past.

    Works directly with raw schedule JSON to avoid circular
    imports with the presenters module.

    Args:
        schedule_data: Raw schedule.json content

    Returns:
        True if no future non-cancelled games remain.
    """
    now = datetime.now(UTC)
    for game in schedule_data.get("schedule", []):
        if game.get("cancelled", False):
            continue
        try:
            game_date = datetime.strptime(game["date"], "%d.%m.%Y %H:%M").replace(
                tzinfo=UTC
            )
            if game_date > now:
                return False
        except (ValueError, KeyError):
            continue
    return True


def _last_game_date(schedule_data: dict[str, Any]) -> datetime | None:
    """Find the date of the last non-cancelled game.

    Args:
        schedule_data: Raw schedule.json content

    Returns:
        Datetime of the last game, or None if no games found.
    """
    last: datetime | None = None
    for game in schedule_data.get("schedule", []):
        if game.get("cancelled", False):
            continue
        try:
            game_date = datetime.strptime(game["date"], "%d.%m.%Y %H:%M").replace(
                tzinfo=UTC
            )
            if last is None or game_date > last:
                last = game_date
        except (ValueError, KeyError):
            continue
    return last


# Grace period (days after last scheduled game) during which
# the scheduler keeps trying to collect missing results.
_GRACE_DAYS = 7


def _has_all_results(cache: CacheDir, schedule_data: dict[str, Any]) -> bool:
    """Check whether all non-cancelled games have results recorded.

    Compares the number of non-cancelled games in the schedule
    against the number of entries in ergebnisse.json.

    Args:
        cache: CacheDir for the league
        schedule_data: Raw schedule.json content

    Returns:
        True if ergebnisse count >= non-cancelled game count.
    """
    try:
        ergebnisse_data = cache.read_json("ergebnisse.json")
    except CacheMiss:
        return False

    expected = sum(
        1 for g in schedule_data.get("schedule", []) if not g.get("cancelled", False)
    )
    actual = len(ergebnisse_data.get("ergebnisse", []))
    return actual >= expected


def _should_refresh_league(cache: CacheDir) -> bool:
    """Determine whether a cached league needs a daily refresh.

    Decision logic:
    - Active season (future games exist): always refresh.
    - Finished season, all results collected: stop.
    - Finished season, missing results, within 7-day grace
      window after last scheduled game: keep refreshing.
    - Finished season, past grace window: stop (give up).

    Args:
        cache: CacheDir for the league

    Returns:
        True if the league should be re-fetched.
    """
    if not cache.has_all_data():
        return False

    # Check for pending/in-progress fetches — skip those
    status = cache.read_status()
    if status.get("status") in ("pending", "stale"):
        return False

    try:
        schedule_data = cache.read_json("schedule.json")
    except CacheMiss:
        return False

    if not _is_season_finished(schedule_data):
        return True  # active season — always refresh

    # Season dates are all past — check if results are complete
    if _has_all_results(cache, schedule_data):
        return False  # nothing more to collect

    # Missing results — are we still within the grace period?
    last_game_dt = _last_game_date(schedule_data)
    if last_game_dt is None:
        return False

    grace_deadline = last_game_dt + timedelta(days=_GRACE_DAYS)
    return datetime.now(UTC) <= grace_deadline  # within grace period?


async def daily_refresh_loop(
    fetch_fn: Callable[[str], Coroutine[Any, Any, None]],
) -> None:
    """Run the daily refresh cycle at 17:00 Europe/Berlin.

    This coroutine runs as a long-lived background task.  It
    sleeps until the next 17:00, then iterates over all cached
    leagues and calls *fetch_fn* for each one that qualifies.

    Args:
        fetch_fn: Async callable that accepts a ligaid string
            and performs the full fetch + AI generation cycle
            (e.g. ``_fetch_and_auto_generate``).
    """
    while True:
        wait = _seconds_until_next_refresh()
        target = datetime.now(_REFRESH_TZ) + timedelta(seconds=wait)
        logger.info(
            "Daily refresh scheduled for %s (in %.0f minutes)",
            target.strftime("%H:%M %Z"),
            wait / 60,
        )
        await asyncio.sleep(wait)

        logger.info("Daily refresh starting...")
        league_ids = CacheDir.list_all_league_ids()

        if not league_ids:
            logger.info("Daily refresh: no cached leagues found")
            continue

        refreshed = 0
        skipped = 0
        for ligaid in league_ids:
            cache = CacheDir(ligaid)
            try:
                if not _should_refresh_league(cache):
                    skipped += 1
                    continue

                logger.info("Daily refresh: refreshing liga %s", ligaid)
                await fetch_fn(ligaid)
                refreshed += 1
            except Exception:
                logger.exception("Daily refresh: failed for liga %s", ligaid)

            # Throttle between leagues
            await asyncio.sleep(_LEAGUE_DELAY)

        logger.info(
            "Daily refresh complete: %d refreshed, %d skipped",
            refreshed,
            skipped,
        )
