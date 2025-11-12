# llmdvs — LLM-Driven Visual Scraper

This repository contains a prototype implementation of a fully autonomous visual web scraper
driven by a multimodal LLM. The goal of the project is to demonstrate how a planning agent can
control a browser, interact with user interfaces using a grid overlay, extract data through DOM
queries or OCR, and validate its own progress using a self-critique loop.

## Features

* **Agentic control loop** — The `VisualScraperAgent` coordinates a ReAct-style cycle of
  `Thought → Action → Observation`, keeping track of memory, retries and JSONL traces for replay.
* **Playwright toolset** — Browser operations (navigation, clicking via grid cells, typing,
  scrolling, DOM extraction, assertions) are exposed to the agent through a single asynchronous
  toolset wrapper with automatic screenshot capture and overlay rendering.
* **Scenario execution** — Deterministic scenarios can be provided as JSON plans and executed via
  the CLI. Each step is represented by an action descriptor compatible with the action DSL from the
  technical specification. Alternatively, scenarios can delegate planning and self-correction to an
  OpenAI GPT model through the built-in ReAct planner.
* **Structured extraction** — Built-in extractors target the `catalog_list_v1` and
  `car_specs_v1` schemas with validation powered by `jsonschema`.
* **Tracing and artifacts** — Every action is stored in a JSONL trace along with rich observations
  (DOM snapshot, viewport metrics, visible texts) and PNG screenshots that include the clickable
  grid overlay.

## Installation

```bash
pip install -e .
playwright install chromium
```

## Launch Instructions

1. (Optional) Create and activate a virtual environment before installing the
   package:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install the project and download the Chromium browser that Playwright
   drives:

   ```bash
   pip install -e .
   playwright install chromium
   ```

3. (Optional) Configure OpenAI credentials if you want the agent to plan its
   own steps. Set the `OPENAI_API_KEY` environment variable or provide an API
   key inside the scenario JSON `llm` block.

4. Run the CLI with a scenario file. You can use the provided
   `examples/sample_catalog_plan.json` (static plan) or the adaptive
   `examples/sample_openai_scenario.json`:

   ```bash
   llmdvs run examples/sample_catalog_plan.json --headless
   ```

   The command launches Chromium, executes the scenario step by step, and
   writes screenshots plus JSONL traces into the default `artifacts/`
   directory defined in `AgentConfig`. Override the viewport and overlay
   sizing from the CLI when necessary, for example:

   ```bash
   llmdvs run examples/sample_openai_scenario.json \
     --viewport-width 1680 --viewport-height 1050 \
     --grid-rows 30 --grid-cols 18
   ```

## Creating a Scenario

1. Create a scenario file that matches the specification:

```json
{
  "goal": "Extract the first 20 catalog entries for brand=Toyota",
  "constraints": {
    "max_steps": 50,
    "max_retries": 3,
    "rate_limit": {"min_delay_ms": 800}
  },
  "plan": [
    {"action": "NAVIGATE", "args": {"url": "https://example.com"}},
    {"action": "WAIT", "args": {"for": "networkidle"}},
    {"action": "EXTRACT_DOM", "args": {"schema": "catalog_list_v1"}},
    {"action": "END", "args": {"status": "success"}}
  ]
}
```

For adaptive runs, include an `llm` section so GPT plans and validates every
step autonomously:

```json
{
  "goal": "Audit the Toyota catalog page and collect pricing rows",
  "constraints": {"max_steps": 80, "max_retries": 3},
  "llm": {
    "type": "openai",
    "model": "gpt-4o-mini",
    "temperature": 0.2,
    "max_history": 6,
    "reflection_limit": 5
  }
}
```

### Viewport and grid configuration

The agent captures screenshots with a grid overlay so actions can be
addressed by cell labels. By default, the grid is rendered with 24 rows and 16
columns over a 1600×900 viewport. You can adjust these values either through
CLI flags (see above) or directly inside the scenario JSON via an optional
`ui` block:

```json
{
  "goal": "Explore the catalog with a dense grid",
  "constraints": {"max_steps": 100},
  "llm": {"type": "openai", "model": "gpt-4o-mini"},
  "ui": {
    "grid_rows": 28,
    "grid_cols": 20,
    "viewport": {"width": 1720, "height": 1080}
  }
}
```

The CLI will merge CLI-specified overrides with the scenario file, allowing
experimentation per target site without editing code.

Screenshots and trace logs are stored under `artifacts/` by default.

## Project Structure

```
llmdvs/
  agent/        # agent state models, LLM interfaces, and the control loop implementation
  tools/        # Playwright toolset, grid overlay utilities, DOM extractors
  memory/       # lightweight session memory containers
  storage/      # tracing utilities and artifact management
  schemas/      # JSON schemas for structured extraction targets
```

## Notes

* OCR extraction is scaffolded but not yet implemented; the toolset raises a `NotImplementedError`
  so that future iterations can plug in Tesseract/EasyOCR.
* The default `StaticPlanLLM` executes deterministic plans, while
  `OpenAIReActLLM` integrates the GPT Responses API for self-directed
  planning and self-critique loops. Both implementations conform to the
  shared `LLMInterface` protocol.

Refer to the technical specification in the task description for the complete roadmap of future
iterations.
