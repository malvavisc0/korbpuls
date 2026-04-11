"""AI agent definitions for team analysis and league prediction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai_like import OpenAILike
from pydantic import BaseModel, Field

from korbpuls.ai.tools import run_korb_command

SKILLS_DIR = Path(__file__).parent / "skills"


class TeamAnalysis(BaseModel):
    """Structured output for team analysis."""

    conclusion: str = Field(
        description=(
            "A single HTML <p> element containing 4-6 sentences of "
            "flowing, analytical prose. Use <strong> tags sparingly "
            "for team names and one or two key stats. Explain WHY "
            "things matter, not just WHAT the numbers are. "
            "No markdown, no bullet lists, no headings. "
            "Must be wrapped in <p>...</p> tags."
        ),
    )


class LeaguePrediction(BaseModel):
    """Structured output for league prediction."""

    table: str = Field(
        description=(
            "ONLY the raw HTML <table> element with thead/tbody. "
            "No markdown, no title, no explanation."
        ),
    )
    explanation: str = Field(
        description=(
            "A single HTML <p> element containing 3-5 sentences of "
            "flowing analysis. Explain the reasoning behind the "
            "predicted standings — why certain teams rise or fall, "
            "what matchups matter, and what trends drive the outcome. "
            "Use <strong> sparingly for team names. No markdown, no "
            "bullet lists, no headings. Must be wrapped in <p>...</p>."
        ),
    )


def _load_skill(filename: str) -> str:
    """Load a skill markdown file."""
    return (SKILLS_DIR / filename).read_text(encoding="utf-8")


def _make_llm(api_base: str, api_key: str, model: str) -> OpenAILike:
    """Create a configured OpenAI-compatible LLM instance."""
    llm_kwargs: dict[str, Any] = {
        "model": model,
        "api_base": api_base,
        "api_key": api_key,
        "is_chat_model": True,
        "is_function_calling_model": True,
        "timeout": 300,
        "default_headers": {
            "X-Title": "KorbPuls.de",
            "HTTP-Referer": "https://korbpuls.de",
        },
    }
    return OpenAILike(**llm_kwargs)


def get_analyst(
    api_base: str,
    api_key: str,
    model: str,
    language: str = "de",
) -> FunctionAgent:
    """Create and return the Analyst agent."""
    skill = _load_skill("TEAM_ANALYSIS.md")

    return FunctionAgent(
        name="Analyst",
        description="Analyze one basketball team in a short paragraph.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            "You are the basketball team analysis agent.\n\n"
            "Call `run_korb_command` with only flags and subcommand; "
            "the binary is prepended automatically. Do not include "
            "'uv run korb'.\n"
            f"Write the final answer in {language}.\n"
            "Return only structured output that satisfies the schema "
            "exactly.\n\n"
            f"Follow these instructions step by step:\n\n{skill}"
        ),
        output_cls=TeamAnalysis,
    )


def get_oracle(
    api_base: str,
    api_key: str,
    model: str,
    language: str = "de",
) -> FunctionAgent:
    """Create and return the Oracle agent."""
    skill = _load_skill("LEAGUE_PREDICTION.md")

    return FunctionAgent(
        name="Oracle",
        description="Predict league standings and explain them.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            "You are the basketball league prediction agent.\n\n"
            "Call `run_korb_command` with only flags and subcommand; "
            "the binary is prepended automatically. Do not include "
            "'uv run korb'.\n"
            f"Write the final explanation in {language}.\n"
            "Return only structured output that satisfies the schema "
            "exactly.\n\n"
            f"Follow these instructions step by step:\n\n{skill}"
        ),
        output_cls=LeaguePrediction,
    )
