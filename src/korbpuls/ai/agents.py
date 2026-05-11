"""AI agent definitions for team analysis and league prediction."""

from __future__ import annotations

from pathlib import Path

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai_like import OpenAILike  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from korbpuls.ai.tools import run_korb_command

SKILLS_DIR = Path(__file__).parent / "skills"


class TeamAnalysis(BaseModel):
    """Structured output for team analysis."""

    conclusion: str = Field(
        description=(
            "2-3 HTML <p> elements containing 10-15 sentences of "
            "detailed, honest basketball analysis. Use <strong> tags "
            "sparingly for team names and key stats. Cover identity, "
            "strengths, weaknesses, and comparative assessment. "
            "No markdown, no bullet lists, no headings. "
            "Each paragraph must be wrapped in <p>...</p> tags."
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


class StandingsNarrative(BaseModel):
    """Structured output for standings narrative."""

    narrative: str = Field(
        description=(
            "A single HTML <p> element containing 3-5 sentences of "
            "accessible league analysis. Cover the most interesting "
            "storyline from the current standings. Use <strong> "
            "sparingly for team names. No markdown, no bullet lists, "
            "no headings. Must be wrapped in <p>...</p>."
        ),
    )


class MatchupPreview(BaseModel):
    """Structured output for matchup preview."""

    analysis: str = Field(
        description=(
            "2-3 HTML <p> elements containing 8-12 sentences of "
            "detailed matchup analysis comparing two teams. Cover "
            "standings comparison, recent form, head-to-head history, "
            "and what to watch for. Use <strong> sparingly for team "
            "names. No markdown, no bullet lists, no headings. "
            "Each paragraph must be wrapped in <p>...</p> tags."
        ),
    )


_COMMON_INSTRUCTIONS = (
    "Call `run_korb_command` with only flags and subcommand; "
    "the binary is prepended automatically.\n"
    "Always use the exact team names from the standings data "
    "— never placeholders.\n"
    "Write grammatically correct German with proper umlauts "
    "(ä, ö, ü, ß). Characters like û or ô do not exist.\n"
    "Generate original analysis from the data. Never copy or "
    "paraphrase examples from the skill.\n"
    "Always use HTML, never Markdown. No jargon.\n"
    "Return only the structured output required by the schema."
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
        timeout=300,
        default_headers={
            "X-Title": "KorbPuls.de",
            "HTTP-Referer": "https://korbpuls.de",
        },
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
        description="Analyze one basketball team in a short paragraph.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            f"{_COMMON_INSTRUCTIONS}\n"
            f"Write the final answer in {language}.\n\n"
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
            f"{_COMMON_INSTRUCTIONS}\n"
            f"Write the final explanation in {language}.\n\n"
            f"Follow these instructions step by step:\n\n{skill}"
        ),
        output_cls=LeaguePrediction,
    )


def get_commentator(
    api_base: str,
    api_key: str,
    model: str,
    language: str = "de",
) -> FunctionAgent:
    """Create and return the Commentator agent."""
    skill = _load_skill("STANDINGS_NARRATIVE.md")

    return FunctionAgent(
        name="Commentator",
        description="Write a brief standings overview for a league.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            f"{_COMMON_INSTRUCTIONS}\n"
            f"Write the final narrative in {language}.\n\n"
            f"Follow these instructions step by step:\n\n{skill}"
        ),
        output_cls=StandingsNarrative,
    )


def get_scout(
    api_base: str,
    api_key: str,
    model: str,
    language: str = "de",
) -> FunctionAgent:
    """Create and return the Scout agent."""
    skill = _load_skill("MATCHUP_PREVIEW.md")

    return FunctionAgent(
        name="Scout",
        description="Analyze a matchup between two basketball teams.",
        llm=_make_llm(api_base, api_key, model),
        tools=[run_korb_command],
        system_prompt=(
            f"{_COMMON_INSTRUCTIONS}\n"
            f"Write the final analysis in {language}.\n\n"
            f"Follow these instructions step by step:\n\n{skill}"
        ),
        output_cls=MatchupPreview,
    )
