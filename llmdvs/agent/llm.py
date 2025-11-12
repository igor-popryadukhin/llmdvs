"""LLM planning helpers used by the agent loop."""
from __future__ import annotations

import asyncio
import json
import os
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

from openai import OpenAI

from .state import ActionRequest, ActionType, Goal
from ..memory.session import SessionMemory


DEFAULT_SYSTEM_PROMPT = dedent(
    """
    You are an autonomous web agent that must achieve the user's data extraction
    goal by thinking and acting in a ReAct-style loop. Each reply MUST be valid
    JSON. Always prefer minimal, precise actions, rely on DOM extraction first,
    and keep track of past reflections. Never invent observations or skip
    validation of the last tool result.
    """
)


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


class OpenAIReActLLM:
    """Planner that uses the OpenAI GPT API for autonomous control and reflection."""

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.2,
        system_prompt: Optional[str] = None,
        api_key: Optional[str] = None,
        max_history: int = 6,
        reflection_limit: int = 5,
        use_responses_api: Optional[bool] = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAI API key is not configured. Provide api_key or set OPENAI_API_KEY."
            )
        self.client = OpenAI(api_key=key)
        self.model = model
        self.temperature = temperature
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.max_history = max_history
        self.reflection_limit = reflection_limit
        if use_responses_api is None:
            self._use_responses_api = model.startswith(("gpt-5", "o1", "gpt-4.1"))
        else:
            self._use_responses_api = bool(use_responses_api)
        self._reflections: List[str] = []

    async def propose_action(self, goal: Goal, memory: SessionMemory) -> ActionRequest:
        messages = self._build_action_messages(goal, memory)
        content = await self._complete(messages)
        data = self._extract_json(content, context="action proposal")
        return ActionRequest.model_validate(data)

    async def reflect(self, goal: Goal, memory: SessionMemory, result_success: bool) -> None:
        if not memory.actions:
            return
        messages = self._build_reflection_messages(goal, memory, result_success)
        content = await self._complete(messages)
        data = self._extract_json(content, context="reflection")
        note = data.get("reflection")
        if isinstance(note, str) and note.strip():
            self._reflections.append(note.strip())
            if len(self._reflections) > self.reflection_limit:
                self._reflections = self._reflections[-self.reflection_limit :]

    async def _complete(self, messages: Sequence[Dict[str, str]]) -> str:
        def _call() -> str:
            if self._use_responses_api:
                response = self.client.responses.create(
                    model=self.model,
                    temperature=self.temperature,
                    input=[
                        {
                            "role": message["role"],
                            "content": [{"type": "text", "text": message["content"]}],
                        }
                        for message in messages
                    ],
                )
                return self._extract_text_from_responses(response)

            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                response_format={"type": "json_object"},
                messages=list(messages),
            )
            return response.choices[0].message.content or ""

        return await asyncio.to_thread(_call)

    def _build_action_messages(
        self, goal: Goal, memory: SessionMemory
    ) -> List[Dict[str, str]]:
        history = self._format_history(memory)
        reflections = "\n".join(f"- {note}" for note in self._reflections[-self.reflection_limit :])
        observation = self._summarise_observation(memory.last_observation())
        prompt = dedent(
            f"""
            Goal: {goal.description}
            Constraints: {json.dumps(goal.constraints)}
            Recent reflection notes:\n{reflections or "(none)"}
            Recent steps:\n{history or "(no previous actions)"}
            Latest observation:\n{observation or "(none)"}

            Respond with a JSON object containing the next action to execute using
            the following schema:
            {{
              "thought": "brief reasoning",
              "action": {{"type": "ACTION_NAME", "args": {{...}}}},
              "postcondition": "expected outcome"
            }}
            The action.type must be one of {list(ActionType.__members__.keys())}.
            """
        )
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

    def _build_reflection_messages(
        self, goal: Goal, memory: SessionMemory, result_success: bool
    ) -> List[Dict[str, str]]:
        last_action = memory.actions[-1]
        last_result = memory.results[-1]
        observation = self._summarise_observation(last_result.observation)
        status = "success" if result_success else f"failure: {last_result.error or 'unknown'}"
        prompt = dedent(
            f"""
            Reflect on the previous action to improve future decisions.
            Goal: {goal.description}
            Action taken: {last_action.type.value} with args {json.dumps(last_action.args)}
            Result: {status}
            Observation: {observation or "(none)"}

            Respond with JSON of the form:
            {{
              "reflection": "short lesson learned",
              "adjustments": ["optional follow-up strategy notes"]
            }}
            Keep it concise but actionable.
            """
        )
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

    def _format_history(self, memory: SessionMemory) -> str:
        if not memory.actions:
            return ""
        segments: List[str] = []
        for idx, (action, result) in enumerate(
            zip(memory.actions[-self.max_history :], memory.results[-self.max_history :]),
            start=max(0, memory.step_count - self.max_history) + 1,
        ):
            outcome = "success" if result.success else f"error: {result.error or 'unknown'}"
            segments.append(
                f"Step {idx}: {action.type.value} args={json.dumps(action.args)} -> {outcome}"
            )
        return "\n".join(segments)

    @staticmethod
    def _summarise_observation(observation: Optional[Any]) -> str:
        if observation is None:
            return ""
        visible = ""
        if getattr(observation, "visible_texts", None):
            visible = ", ".join(getattr(observation, "visible_texts")[:5])
        detected = getattr(observation, "detected_signals", {}) or {}
        return (
            f"url={getattr(observation, 'url', '')}, scroll={getattr(observation, 'scroll', {})}, "
            f"signals={detected}, texts={visible}"
        )

    @staticmethod
    def _extract_json(content: str, *, context: str) -> Dict[str, Any]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Failed to parse {context} response as JSON: {content}") from exc
        if "action" in data and not isinstance(data["action"], dict):
            raise RuntimeError(f"Invalid action payload returned for {context}")
        if "type" not in data and "action" in data:
            data = data["action"] | {"thought": data.get("thought"), "postcondition": data.get("postcondition")}
        return data

    @staticmethod
    def _extract_text_from_responses(response: Any) -> str:
        output = getattr(response, "output", None)
        if output:
            for item in output:
                if getattr(item, "type", None) != "message":
                    continue
                message = getattr(item, "message", None)
                if not message:
                    continue
                for content in getattr(message, "content", []) or []:
                    if getattr(content, "type", None) == "text":
                        text = getattr(content, "text", "")
                        if text:
                            return text
        text_output = getattr(response, "output_text", None)
        if text_output:
            return text_output
        raise RuntimeError("OpenAI response did not include text output")

