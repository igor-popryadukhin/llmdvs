"""Browser tooling built on top of Playwright."""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..agent.state import ActionRequest, ActionResult, Observation
from .extractors import DOMExtractor, SchemaValidationError
from .grid import GridSpec, overlay_script

logger = structlog.get_logger(__name__)


@dataclass
class ScreenshotInfo:
    path: Path
    width: int
    height: int
    dpr: float
    scroll_x: float
    scroll_y: float


class PlaywrightToolset:
    """Wrap Playwright operations for use by the agent."""

    def __init__(
        self,
        *,
        screenshot_dir: Path,
        grid_rows: int = 12,
        grid_cols: int = 8,
        headless: bool = False,
        user_agent: Optional[str] = None,
    ) -> None:
        self.screenshot_dir = screenshot_dir
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols
        self.headless = headless
        self.user_agent = user_agent
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "PlaywrightToolset":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=self.headless)
        context_args = {}
        if self.user_agent:
            context_args["user_agent"] = self.user_agent
        self.context = await self.browser.new_context(**context_args)
        self.page = await self.context.new_page()
        await self.page.set_viewport_size({"width": 1280, "height": 720})
        logger.info("playwright_started", headless=self.headless)

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("playwright_closed")

    async def execute(self, action: ActionRequest) -> ActionResult:
        if not self.page:
            raise RuntimeError("Toolset has not been started")
        try:
            handler = getattr(self, f"_handle_{action.type.value.lower()}")
        except AttributeError:
            return ActionResult(success=False, error=f"Action {action.type} is not supported")
        try:
            signals = await handler(action)
            observation = await self._capture_observation()
            return ActionResult(success=True, observation=observation, signals=signals or {})
        except SchemaValidationError as err:
            return ActionResult(success=False, error=str(err))
        except Exception as err:  # pragma: no cover - runtime safety
            logger.exception("action_failed", action=action.type.value)
            return ActionResult(success=False, error=str(err))

    async def _handle_navigate(self, action: ActionRequest) -> dict:
        assert self.page
        url = action.args.get("url")
        if not url:
            raise ValueError("NAVIGATE action requires 'url'")
        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(action.args.get("delay", 0.5))
        return {"navigated": url}

    async def _handle_click_cell(self, action: ActionRequest) -> dict:
        assert self.page
        cell = action.args.get("cell")
        jitter = action.args.get("jitter", True)
        if not cell:
            raise ValueError("CLICK_CELL requires 'cell'")
        info = await self._ensure_metrics()
        grid = GridSpec(self.grid_rows, self.grid_cols, info.dpr)
        page_x, page_y = grid.to_page_coordinates(
            cell,
            info.width,
            info.height,
            info.scroll_x,
            info.scroll_y,
        )
        if jitter:
            page_x += random.uniform(-3, 3)
            page_y += random.uniform(-3, 3)
        await self.page.mouse.click(page_x, page_y, delay=action.args.get("delay", 50))
        await asyncio.sleep(action.args.get("post_delay", 0.3))
        return {"clicked": {"cell": cell, "page_x": page_x, "page_y": page_y}}

    async def _handle_click_xy(self, action: ActionRequest) -> dict:
        assert self.page
        x = action.args.get("x")
        y = action.args.get("y")
        if x is None or y is None:
            raise ValueError("CLICK_XY requires 'x' and 'y'")
        await self.page.mouse.click(x, y, delay=action.args.get("delay", 50))
        await asyncio.sleep(action.args.get("post_delay", 0.3))
        return {"clicked": {"x": x, "y": y}}

    async def _handle_type(self, action: ActionRequest) -> dict:
        assert self.page
        text = action.args.get("text")
        if text is None:
            raise ValueError("TYPE requires 'text'")
        selector = action.args.get("selector")
        cell = action.args.get("cell")
        if selector:
            await self.page.fill(selector, text)
        elif cell:
            info = await self._ensure_metrics()
            grid = GridSpec(self.grid_rows, self.grid_cols, info.dpr)
            page_x, page_y = grid.to_page_coordinates(
                cell,
                info.width,
                info.height,
                info.scroll_x,
                info.scroll_y,
            )
            await self.page.mouse.click(page_x, page_y)
            await asyncio.sleep(0.2)
            await self.page.keyboard.type(text)
        else:
            raise ValueError("TYPE requires either 'selector' or 'cell'")
        if action.args.get("submit"):
            await self.page.keyboard.press("Enter")
        await asyncio.sleep(action.args.get("post_delay", 0.3))
        return {"typed": len(text)}

    async def _handle_scroll(self, action: ActionRequest) -> dict:
        assert self.page
        direction = action.args.get("direction", "down")
        amount = action.args.get("amount", 600)
        if direction not in {"down", "up"}:
            raise ValueError("SCROLL direction must be 'down' or 'up'")
        delta = amount if direction == "down" else -amount
        await self.page.mouse.wheel(0, delta)
        await asyncio.sleep(action.args.get("post_delay", 0.3))
        return {"scrolled": {"direction": direction, "amount": amount}}

    async def _handle_wait(self, action: ActionRequest) -> dict:
        assert self.page
        wait_for = action.args.get("for", "time")
        value = action.args.get("value", 1.0)
        if wait_for == "time":
            await asyncio.sleep(float(value))
        elif wait_for == "selector":
            await self.page.wait_for_selector(value, timeout=action.args.get("timeout", 5000))
        elif wait_for == "networkidle":
            await self.page.wait_for_load_state("networkidle")
        else:
            raise ValueError(f"Unsupported WAIT target: {wait_for}")
        return {"waited": wait_for}

    async def _handle_extract_dom(self, action: ActionRequest) -> dict:
        assert self.page
        schema = action.args.get("schema")
        if not schema:
            raise ValueError("EXTRACT_DOM requires 'schema'")
        extractor = DOMExtractor(self.page)
        payload = await extractor.extract(schema)
        logger.info("dom_extracted", schema=schema, items=len(payload) if isinstance(payload, list) else 1)
        return {"extracted": payload, "schema": schema}

    async def _handle_extract_ocr(self, action: ActionRequest) -> dict:
        raise NotImplementedError("OCR extraction is not yet implemented")

    async def _handle_assert(self, action: ActionRequest) -> dict:
        assert self.page
        condition = action.args.get("condition")
        if not condition:
            raise ValueError("ASSERT requires 'condition'")
        result = await self.page.evaluate(condition)
        if not result:
            raise AssertionError(f"Assertion failed: {condition}")
        return {"asserted": condition}

    async def _handle_end(self, action: ActionRequest) -> dict:
        logger.info("session_marked_complete", status=action.args.get("status", "unknown"))
        return {"status": action.args.get("status")}

    async def _ensure_metrics(self) -> ScreenshotInfo:
        assert self.page
        metrics = await self.page.evaluate(
            "({width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio, "
            "scrollX: window.scrollX, scrollY: window.scrollY})"
        )
        return ScreenshotInfo(
            path=self.screenshot_dir,
            width=int(metrics["width"] * metrics["dpr"]),
            height=int(metrics["height"] * metrics["dpr"]),
            dpr=float(metrics["dpr"]),
            scroll_x=float(metrics["scrollX"]),
            scroll_y=float(metrics["scrollY"]),
        )

    async def _capture_observation(self) -> Observation:
        assert self.page
        metrics = await self.page.evaluate(
            "({width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio, "
            "scrollX: window.scrollX, scrollY: window.scrollY})"
        )
        loop = asyncio.get_running_loop()
        screenshot_path = self.screenshot_dir / f"step_{int(loop.time()*1000)}.png"
        await self.page.add_script_tag(content=overlay_script(self.grid_rows, self.grid_cols))
        await self.page.screenshot(path=str(screenshot_path), full_page=False)
        dom_content = await self.page.content()
        texts = await self.page.evaluate(
            "Array.from(document.querySelectorAll('body *'))"
            ".filter(el => el.childElementCount === 0)"
            ".map(el => el.textContent.trim()).filter(Boolean).slice(0, 500)"
        )
        return Observation(
            url=self.page.url,
            viewport={"width": metrics["width"], "height": metrics["height"], "dpr": metrics["dpr"]},
            scroll={"x": metrics["scrollX"], "y": metrics["scrollY"]},
            screenshot=screenshot_path,
            dom_snapshot=dom_content[:200000],
            visible_texts=texts,
        )

