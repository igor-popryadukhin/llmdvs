"""DOM and OCR extraction helpers."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Union

from jsonschema import Draft7Validator

from playwright.async_api import Page


class SchemaValidationError(RuntimeError):
    """Raised when the extracted payload does not satisfy the schema."""


class DOMExtractor:
    """Extract structured information from the currently loaded page."""

    def __init__(self, page: Page) -> None:
        self.page = page

    async def extract(self, schema: Union[str, Dict[str, Any]]) -> Any:
        if isinstance(schema, str):
            payload = await self._extract_named_schema(schema)
            self._validate_schema(schema, payload)
            return payload
        if isinstance(schema, dict):
            return await self._extract_custom_schema(schema)
        raise TypeError("schema must be a string or mapping definition")

    async def _extract_named_schema(self, schema: str) -> Any:
        if schema == "catalog_list_v1":
            payload = await self._extract_catalog_list()
        elif schema == "car_specs_v1":
            payload = await self._extract_car_specs()
        else:
            raise ValueError(f"Unsupported schema: {schema}")
        return payload

    async def _extract_custom_schema(self, schema: Dict[str, Any]) -> Any:
        script = """
        (schema) => {
          const isObject = (value) => value && typeof value === 'object' && !Array.isArray(value);

          const extractField = (root, spec) => {
            if (!isObject(spec)) {
              return null;
            }

            const elements = (() => {
              if (typeof spec.selector === 'string' && spec.selector.trim()) {
                return Array.from(root.querySelectorAll(spec.selector));
              }
              return [root];
            })();

            if (isObject(spec.properties)) {
              const records = elements.map((el) => {
                const entry = {};
                for (const [key, child] of Object.entries(spec.properties)) {
                  entry[key] = extractField(el, child);
                }
                return entry;
              }).filter((entry) => {
                return Object.values(entry).some((value) => {
                  if (value == null) {
                    return false;
                  }
                  if (Array.isArray(value)) {
                    return value.length > 0;
                  }
                  if (typeof value === 'string') {
                    return value.trim().length > 0;
                  }
                  if (typeof value === 'object') {
                    return Object.keys(value).length > 0;
                  }
                  return true;
                });
              });
              if (spec.single || spec.first) {
                return records[0] ?? null;
              }
              return records;
            }

            const projector = (el) => {
              const type = spec.type || (spec.attribute ? 'attribute' : 'text');
              if (type === 'attribute') {
                const attr = spec.attribute;
                if (!attr) {
                  return null;
                }
                const value = el.getAttribute(attr);
                return value === undefined ? null : value;
              }
              if (type === 'html') {
                return el.innerHTML;
              }
              if (type === 'value') {
                return 'value' in el ? el.value : null;
              }
              if (type === 'text') {
                const text = el.textContent || '';
                return spec.trim === false ? text : text.trim();
              }
              return null;
            };

            const values = elements.map(projector).filter((value) => {
              if (value == null) {
                return false;
              }
              if (typeof value === 'string') {
                return spec.keepEmpty ? true : value.trim().length > 0;
              }
              return true;
            });

            if (spec.all) {
              return values;
            }
            return values.length > 0 ? values[0] : null;
          };

          const walk = (root, definition) => {
            if (!isObject(definition)) {
              return null;
            }
            const result = {};
            for (const [key, spec] of Object.entries(definition)) {
              result[key] = extractField(root, spec);
            }
            return result;
          };

          return walk(document, schema);
        }
        """
        return await self.page.evaluate(script, schema)

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

