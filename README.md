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
  technical specification.
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

## Running a Scenario

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

2. Execute the plan with the CLI:

```bash
llmdvs run scenario.json --headless
```

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
* The default `StaticPlanLLM` executes deterministic plans. Hooking up a real multimodal LLM only
  requires implementing the `LLMInterface` protocol and providing ReAct-style prompts.

Refer to the technical specification in the task description for the complete roadmap of future
iterations.
