"""In-memory representation of the agent session state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..agent.state import ActionRequest, ActionResult


@dataclass
class SessionMemory:
    """Stores the executed actions and their outcomes."""

    actions: List[ActionRequest] = field(default_factory=list)
    results: List[ActionResult] = field(default_factory=list)

    def append(self, action: ActionRequest, result: ActionResult) -> None:
        self.actions.append(action)
        self.results.append(result)

    @property
    def step_count(self) -> int:
        return len(self.actions)

    def last_observation(self):
        if not self.results:
            return None
        return self.results[-1].observation

