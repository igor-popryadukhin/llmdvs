"""DOM and OCR extraction helpers."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft7Validator

from playwright.async_api import Page


class SchemaValidationError(RuntimeError):
    """Raised when the extracted payload does not satisfy the schema."""


class DOMExtractor:
    """Extract structured information from the currently loaded page."""

    def __init__(self, page: Page) -> None:
        self.page = page

    async def extract(self, schema: str) -> Any:
        if schema == "catalog_list_v1":
            payload = await self._extract_catalog_list()
        elif schema == "car_specs_v1":
            payload = await self._extract_car_specs()
        else:
            raise ValueError(f"Unsupported schema: {schema}")
        self._validate_schema(schema, payload)
        return payload

    async def _extract_catalog_list(self) -> List[Dict[str, Any]]:
        script = """
        () => {
          const candidates = Array.from(
            document.querySelectorAll('[data-llmdvs-item], article, li, .card, .item')
          );
          const visible = candidates
            .filter(el => {
              const rect = el.getBoundingClientRect();
              if (rect.width < 120 || rect.height < 80) {
                return false;
              }
              const style = window.getComputedStyle(el);
              return style && style.display !== 'none' && style.visibility !== 'hidden';
            })
            .slice(0, 80);
          const firstFilled = (...values) => {
            for (const value of values) {
              if (typeof value === 'string') {
                const trimmed = value.trim();
                if (trimmed) {
                  return trimmed;
                }
              }
            }
            return '';
          };
          return visible
            .map(el => {
              const titleEl = el.querySelector('[data-llmdvs-title], h1, h2, h3, h4, .title, .name');
              const priceEl = el.querySelector('[data-llmdvs-price], [class*="price" i], [data-price], [itemprop="price"]');
              const linkEl = el.querySelector('a[href]');
              const attrs = {};
              el.querySelectorAll('[data-attribute]').forEach(attr => {
                const key = attr.getAttribute('data-attribute');
                if (key) {
                  attrs[key] = attr.textContent.trim();
                }
              });
              const priceCandidate = firstFilled(
                priceEl && priceEl.textContent,
                priceEl && priceEl.getAttribute && priceEl.getAttribute('content'),
                priceEl && priceEl.getAttribute && priceEl.getAttribute('data-price'),
                priceEl && priceEl.getAttribute && priceEl.getAttribute('data-price-amount'),
                priceEl && priceEl.getAttribute && priceEl.getAttribute('aria-label'),
                priceEl && priceEl.getAttribute && priceEl.getAttribute('title'),
                el.getAttribute('data-price'),
                el.getAttribute('data-price-amount')
              );
              if (!priceCandidate) {
                return null;
              }
              const item = {
                title: titleEl ? titleEl.textContent.trim() : el.textContent.trim().slice(0, 120),
                price: priceCandidate,
                attrs,
              };
              if (linkEl && linkEl.href) {
                item.link = linkEl.href;
              }
              return item;
            })
            .filter(Boolean)
            .filter(item => item.title && item.price);
        }
        """
        return await self.page.evaluate(script)

    async def _extract_car_specs(self) -> Dict[str, Any]:
        script = """
        () => {
          const queryText = (selectorList) => {
            for (const selector of selectorList) {
              const node = document.querySelector(selector);
              if (node) {
                const text = node.textContent.trim();
                if (text) {
                  return text;
                }
              }
            }
            return null;
          };
          const attrs = {};
          document.querySelectorAll('[data-spec-key]').forEach(el => {
            const key = el.getAttribute('data-spec-key');
            if (!key) return;
            const valueNode = el.querySelector('[data-spec-value]') || el;
            attrs[key] = valueNode.textContent.trim();
          });
          const tableRows = Array.from(document.querySelectorAll('table tr'));
          tableRows.forEach(row => {
            const cells = row.querySelectorAll('th, td');
            if (cells.length >= 2) {
              const key = cells[0].textContent.trim();
              if (key) {
                attrs[key] = cells[1].textContent.trim();
              }
            }
          });
          return {
            brand: queryText(['[data-brand]', '[itemprop="brand"]', '.brand', 'meta[itemprop="brand"][content]']) || '',
            model: queryText(['[data-model]', '[itemprop="model"]', '.model', 'h1', 'title']) || '',
            trim: queryText(['[data-trim]', '.trim', '.configuration']) || '',
            years: queryText(['[data-years]', '.years', '.production']) || '',
            engine: queryText(['[data-engine]', '.engine', '.motor']) || '',
            transmission: queryText(['[data-transmission]', '.transmission', '.gearbox']) || '',
            attrs,
          };
        }
        """
        return await self.page.evaluate(script)

    def _validate_schema(self, schema_name: str, payload: Any) -> None:
        schema_path = self._schema_path(schema_name)
        with open(schema_path, "r", encoding="utf-8") as stream:
            schema = json.load(stream)
        validator = Draft7Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
        if errors:
            details = "; ".join(error.message for error in errors)
            raise SchemaValidationError(details)

    @staticmethod
    def _schema_path(schema_name: str) -> Path:
        package = "llmdvs.schemas"
        filename = f"{schema_name}.json"
        with resources.as_file(resources.files(package) / filename) as path:
            return Path(path)

