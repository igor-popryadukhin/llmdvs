"""Data models describing the agent state and lifecycle."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ActionType(str, Enum):
    """Supported action primitives for the agent."""

    CLICK_CELL = "CLICK_CELL"
    CLICK_XY = "CLICK_XY"
    TYPE = "TYPE"
    SCROLL = "SCROLL"
    WAIT = "WAIT"
    NAVIGATE = "NAVIGATE"
    EXTRACT_DOM = "EXTRACT_DOM"
    EXTRACT_OCR = "EXTRACT_OCR"
    ASSERT = "ASSERT"
    END = "END"


class Goal(BaseModel):
    """Represents the high level task that the agent should achieve."""

    description: str
    constraints: Dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Configurable parameters that control the agent behaviour."""

    max_steps: int = 150
    max_retries: int = 5
    min_delay_ms: int = 800
    screenshot_dir: Path = Field(default_factory=lambda: Path("artifacts"))
    log_path: Path = Field(default_factory=lambda: Path("artifacts") / "trace.jsonl")


class ActionRequest(BaseModel):
    """An action that the agent wants to perform through a tool."""

    model_config = ConfigDict(populate_by_name=True)

    type: ActionType = Field(
        validation_alias=AliasChoices("type", "action"),
        serialization_alias="type",
    )
    args: Dict[str, Any] = Field(default_factory=dict)
    thought: Optional[str] = None
    postcondition: Optional[str] = None

    @field_validator("args", mode="before")
    @classmethod
    def _ensure_dict(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("Action args must be a mapping")
        return value


class ActionResult(BaseModel):
    """Return value from tool execution."""

    success: bool
    observation: Optional["Observation"] = None
    error: Optional[str] = None
    signals: Dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    """Snapshot of the browser state after executing an action."""

    url: str
    viewport: Dict[str, Any]
    scroll: Dict[str, Any]
    screenshot: Optional[Path] = None
    dom_snapshot: Optional[str] = None
    detected_signals: Dict[str, Any] = Field(default_factory=dict)
    visible_texts: List[str] = Field(default_factory=list)

    def to_log_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        if self.screenshot is not None:
            data["screenshot"] = str(self.screenshot)
        return data


Observation.model_rebuild()

