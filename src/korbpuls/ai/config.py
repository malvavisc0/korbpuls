"""AI configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AIConfig:
    """Configuration for AI agent connections."""

    api_base: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls) -> AIConfig | None:
        """Create config from environment variables.

        Returns None if any required variable is missing,
        which effectively disables AI features.
        """
        api_base = os.environ.get("OPENAILIKE_API_BASE", "")
        api_key = os.environ.get("OPENAILIKE_API_KEY", "")
        model = os.environ.get("OPENAILIKE_LLM", "")

        if not all([api_base, api_key, model]):
            return None

        return cls(api_base=api_base, api_key=api_key, model=model)
