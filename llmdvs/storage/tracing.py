"""Tracing helpers for agent runs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from ..agent.state import ActionRequest, ActionResult


@dataclass
class TraceLogger:
    """Append-only JSONL trace writer."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append_step(
        self,
        *,
        step: int,
        thought: str | None,
        action: ActionRequest,
        result: ActionResult,
    ) -> None:
        record: Dict[str, Any] = {
            "step": step,
            "thought": thought,
            "action": {"type": action.type.value, "args": action.args},
            "success": result.success,
            "error": result.error,
            "signals": result.signals,
        }
        if result.observation is not None:
            record["observation"] = result.observation.to_log_dict()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

