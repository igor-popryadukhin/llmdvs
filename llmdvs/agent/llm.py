"""LLM planning helpers used by the agent loop."""
from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Protocol

from .state import ActionRequest, ActionType, Goal
from ..memory.session import SessionMemory


class LLMInterface(Protocol):
    """Protocol describing the hooks used by :class:`VisualScraperAgent`."""

    async def propose_action(self, goal: Goal, memory: SessionMemory) -> ActionRequest:
        ...

    async def reflect(self, goal: Goal, memory: SessionMemory, result_success: bool) -> None:
        ...


class StaticPlanLLM:
    """LLM stub that executes a predefined plan sequentially."""

    def __init__(self, plan: Iterable[Dict]) -> None:
        self.plan: List[ActionRequest] = [ActionRequest(**step) for step in plan]
        self._cursor = 0

    async def propose_action(self, goal: Goal, memory: SessionMemory) -> ActionRequest:
        await asyncio.sleep(0)  # allow cooperative scheduling
        if self._cursor < len(self.plan):
            action = self.plan[self._cursor]
            self._cursor += 1
            return action
        return ActionRequest(type=ActionType.END, args={"status": "success"})

    async def reflect(self, goal: Goal, memory: SessionMemory, result_success: bool) -> None:
        await asyncio.sleep(0)
        if not result_success and self._cursor < len(self.plan):
            # Retry the same action by stepping back one position
            self._cursor = max(0, self._cursor - 1)

