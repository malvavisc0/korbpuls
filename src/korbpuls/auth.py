"""API key validation for protected /api/* routes."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

KORBPULS_API_KEY = os.environ.get("KORBPULS_API_KEY")
if not KORBPULS_API_KEY:
    raise RuntimeError("KORBPULS_API_KEY environment variable not set")


async def validate_api_key(x_api_key: str = Header(...)) -> str:
    """Validate X-API-Key header against environment variable.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: If key doesn't match
    """
    if x_api_key != KORBPULS_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
