"""Bootstrap .env loading before modules read configuration at import time."""

from __future__ import annotations

from dotenv import load_dotenv


def load_config() -> None:
    """Load ``.env`` without overriding real environment variables.

    Python modules such as ``cache`` and ``korb_client`` read
    configuration at import time, so this must run before those
    imports.  Calling it more than once is safe.
    """
    load_dotenv()
