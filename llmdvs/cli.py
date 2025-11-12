"""Command line interface for launching agent runs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .agent.core import VisualScraperAgent
from .agent.llm import OpenAIReActLLM, StaticPlanLLM
from .agent.state import AgentConfig, Goal
from .tools.browser import PlaywrightToolset

app = typer.Typer(help="LLM-driven visual scraper prototype")
console = Console()


def _config_from_constraints(constraints: dict) -> AgentConfig:
    base = AgentConfig()
    rate_limit = constraints.get("rate_limit", {}) if isinstance(constraints, dict) else {}
    return AgentConfig(
        max_steps=constraints.get("max_steps", base.max_steps),
        max_retries=constraints.get("max_retries", base.max_retries),
        min_delay_ms=rate_limit.get("min_delay_ms", base.min_delay_ms),
        screenshot_dir=base.screenshot_dir,
        log_path=base.log_path,
    )


@app.command()
def run(
    scenario: Path = typer.Argument(..., exists=True, help="Path to scenario JSON"),
    headless: bool = typer.Option(False, help="Run browser in headless mode"),
    user_agent: Optional[str] = typer.Option(None, help="Override browser User-Agent"),
) -> None:
    """Execute a scraping scenario from disk."""
    with scenario.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    goal = Goal(description=data["goal"], constraints=data.get("constraints", {}))
    config = _config_from_constraints(data.get("constraints", {}))
    config.screenshot_dir.mkdir(parents=True, exist_ok=True)

    llm = _load_llm(data)

    async def _runner() -> None:
        async with PlaywrightToolset(
            screenshot_dir=config.screenshot_dir,
            headless=headless,
            user_agent=user_agent,
        ) as tools:
            agent = VisualScraperAgent(config=config, toolset=tools, llm=llm)
            result = await agent.run(goal)
            table = Table(title="Agent Run Summary")
            table.add_column("Goal")
            table.add_column("Success")
            table.add_column("Steps", justify="right")
            table.add_row(result.goal.description, "✅" if result.success else "❌", str(result.steps))
            console.print(table)
            if result.errors:
                console.print("[bold red]Errors:")
                for err in result.errors:
                    console.print(f" • {err}")

    asyncio.run(_runner())


def _load_llm(payload: dict):
    llm_spec = payload.get("llm", {}) if isinstance(payload, dict) else {}
    if isinstance(llm_spec, dict):
        llm_type = llm_spec.get("type")
        if llm_type == "openai":
            return OpenAIReActLLM(
                model=llm_spec.get("model", "gpt-4o-mini"),
                temperature=float(llm_spec.get("temperature", 0.2)),
                system_prompt=llm_spec.get("system_prompt"),
                api_key=llm_spec.get("api_key"),
                max_history=int(llm_spec.get("max_history", 6)),
                reflection_limit=int(llm_spec.get("reflection_limit", 5)),
            )
    plan = payload.get("plan", []) if isinstance(payload, dict) else []
    if not plan:
        raise typer.BadParameter(
            "Scenario must provide either a static plan or an 'llm' configuration."
        )
    return StaticPlanLLM(plan)


if __name__ == "__main__":
    app()

