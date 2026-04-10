"""AI agent definitions for team analysis and league prediction."""

from __future__ import annotations

from pathlib import Path

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
    return OpenAILike(
        model=model,
        api_base=api_base,
        api_key=api_key,
        is_chat_model=True,
        is_function_calling_model=True,
        timeout=300,  # 5 minutes timeout for long-running commands
    )


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
        description="Analyze a single basketball team and produce a short paragraph.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            "You are the basketball team analysis agent.\n\n"
            "TOOL USAGE: Call `run_korb_command` with only the flags and "
            "subcommand. The korb binary is prepended automatically.\n"
            "Example: run_korb_command('--json --ligaid 51491 standings')\n"
            "Do NOT include 'uv run korb' in the args string.\n\n"
            f"Output language: {language}\n\n"
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
        description="Predict league final standings and produce an explanation.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            "You are the basketball league prediction agent.\n\n"
            "TOOL USAGE: Call `run_korb_command` with only the flags and "
            "subcommand. The korb binary is prepended automatically.\n"
            "Example: run_korb_command('--json --ligaid 51491 predict')\n"
            "Do NOT include 'uv run korb' in the args string.\n\n"
            f"Output language: {language}\n\n"
            f"Follow these instructions step by step:\n\n{skill}"
        ),
        output_cls=LeaguePrediction,
    )
