"""Shared parsing for basketball-bund.net date strings.

Dates from the upstream service are German wall-clock times
(Europe/Berlin), e.g. ``"15.03.2025 20:00"``.  They must be
interpreted in that zone — tagging them UTC shifts every
upcoming/finished comparison by +1h/+2h depending on DST.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BB_DATE_FORMAT = "%d.%m.%Y %H:%M"
BB_TZ = ZoneInfo("Europe/Berlin")


def parse_bb_datetime(value: str) -> datetime | None:
    """Parse a korb date string into an aware Europe/Berlin datetime.

    Args:
        value: Date string in ``%d.%m.%Y %H:%M`` format

    Returns:
        Timezone-aware datetime, or None when the string cannot be
        parsed (e.g. placeholder dates like "TBD").
    """
    try:
        return datetime.strptime(value, BB_DATE_FORMAT).replace(tzinfo=BB_TZ)
    except (ValueError, TypeError):
        return None
