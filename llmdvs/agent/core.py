"""Core agent loop that orchestrates planning and tool execution."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List

import structlog

from .llm import LLMInterface
from .state import ActionType, AgentConfig, Goal
from ..memory.session import SessionMemory
from ..storage.tracing import TraceLogger
from ..tools.browser import PlaywrightToolset

logger = structlog.get_logger(__name__)


@dataclass
class AgentRunResult:
    """Summary of a completed agent session."""

    goal: Goal
    success: bool
    steps: int
    errors: List[str] = field(default_factory=list)


class VisualScraperAgent:
    """High level controller implementing the agent cycle."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        toolset: PlaywrightToolset,
        llm: LLMInterface,
    ) -> None:
        self.config = config
        self.toolset = toolset
        self.llm = llm
        self.trace_logger = TraceLogger(config.log_path)

    async def run(self, goal: Goal) -> AgentRunResult:
        memory = SessionMemory()
        errors: List[str] = []
        consecutive_failures = 0

        for step_index in range(self.config.max_steps):
            action = await self.llm.propose_action(goal, memory)
            logger.info("agent_action", step=step_index, action=action.type.value, thought=action.thought)

            if action.type == ActionType.END:
                result = await self.toolset.execute(action)
                memory.append(action, result)
                self.trace_logger.append_step(
                    step=memory.step_count,
                    thought=action.thought,
                    action=action,
                    result=result,
                )
                success = action.args.get("status") == "success"
                return AgentRunResult(goal=goal, success=success, steps=memory.step_count, errors=errors)

            result = await self.toolset.execute(action)
            memory.append(action, result)
            self.trace_logger.append_step(
                step=memory.step_count,
                thought=action.thought,
                action=action,
                result=result,
            )

            if not result.success:
                consecutive_failures += 1
                if result.error:
                    errors.append(result.error)
                logger.warning("action_failed", step=step_index, error=result.error)
                if consecutive_failures > self.config.max_retries:
                    logger.error("too_many_failures", limit=self.config.max_retries)
                    break
            else:
                consecutive_failures = 0

            await self.llm.reflect(goal, memory, result.success)
            await asyncio.sleep(self.config.min_delay_ms / 1000)

        return AgentRunResult(goal=goal, success=False, steps=memory.step_count, errors=errors)

