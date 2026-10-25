"""Shared AI runtime helpers."""

from __future__ import annotations

import os
from contextlib import nullcontext
from functools import cache
from typing import Any

from langfuse import Langfuse
from llama_index.core.agent.workflow import FunctionAgent


@cache
def get_langfuse() -> Langfuse | None:
    """Return the shared Langfuse client, created once on first use.

    Returns None when ``LANGFUSE_SECRET_KEY`` is unset, so tracing is
    fully opt-in with zero overhead. The client is built once and reused
    for every agent call.
    """
    if not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    return Langfuse(
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        base_url=os.environ.get("LANGFUSE_BASE_URL"),
    )


async def run_agent_once(
    agent: FunctionAgent,
    prompt: str,
    output_cls: type,
) -> Any:
    """Run an AI agent once and parse its structured output.

    Raises if the agent call fails or the LLM returns no valid
    structured output. When Langfuse is configured, the call is wrapped
    in a trace observation that records input, output and any failure.
    """
    lf = get_langfuse()
    cm = (
        lf.start_as_current_observation(
            name=agent.name,
            as_type="chain",
            input=prompt,
            metadata={"agent": agent.name},
        )
        if lf is not None
        else nullcontext()
    )
    with cm as observation:
        try:
            response = await agent.run(
                user_msg=prompt,
                max_iterations=15,
                debug=os.environ.get("KORBPULS_AI_DEBUG", "").strip().lower()
                in {"1", "true", "yes", "on"},
            )
        except Exception as exc:
            if observation is not None:
                observation.update(level="ERROR", status_message=str(exc))
            raise
        result = response.get_pydantic_model(output_cls)  # type: ignore[attr-defined]
        if result is None:
            exc = RuntimeError(
                "LLM returned no valid structured output"
                f" (structured_response="
                f"{response.structured_response!r})"  # type: ignore[attr-defined]
            )
            if observation is not None:
                observation.update(level="ERROR", status_message=str(exc))
            raise exc
        if observation is not None:
            observation.update(
                output=response.structured_response  # type: ignore[attr-defined]
            )
    return result
