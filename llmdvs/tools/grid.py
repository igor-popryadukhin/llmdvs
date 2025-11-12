"""Utilities for working with the viewport grid overlay."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class GridSpec:
    rows: int
    cols: int
    dpr: float

    def cell_to_indices(self, label: str) -> Tuple[int, int]:
        """Convert a label like ``C5`` into zero based grid indices."""
        if len(label) < 2:
            raise ValueError(f"Invalid cell label: {label}")
        column_letter = label[0].upper()
        row_number = label[1:]
        if not column_letter.isalpha() or not row_number.isdigit():
            raise ValueError(f"Invalid cell label: {label}")
        col = ord(column_letter) - ord("A")
        row = int(row_number) - 1
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise ValueError(f"Cell {label} is outside of grid bounds {self.rows}x{self.cols}")
        return row, col

    def cell_center_px(self, label: str, img_width: int, img_height: int) -> Tuple[float, float]:
        """Return the device pixel coordinates of the center of a grid cell."""
        row, col = self.cell_to_indices(label)
        cell_width = img_width / self.cols
        cell_height = img_height / self.rows
        return (col + 0.5) * cell_width, (row + 0.5) * cell_height

    def to_page_coordinates(
        self,
        label: str,
        img_width: int,
        img_height: int,
        scroll_x: float,
        scroll_y: float,
    ) -> Tuple[float, float]:
        """Translate a cell label to CSS pixel coordinates on the page."""
        img_x, img_y = self.cell_center_px(label, img_width, img_height)
        page_x = img_x / self.dpr + scroll_x
        page_y = img_y / self.dpr + scroll_y
        return page_x, page_y


OVERLAY_INJECT_SCRIPT = """
(() => {
  const existing = document.getElementById('__llmdvs_grid');
  if (existing) {
    existing.remove();
  }
  const overlay = document.createElement('div');
  overlay.id = '__llmdvs_grid';
  overlay.style.position = 'fixed';
  overlay.style.inset = '0';
  overlay.style.zIndex = '2147483646';
  overlay.style.pointerEvents = 'none';
  overlay.style.display = 'grid';
  overlay.style.gridTemplateColumns = `repeat(${COLS}, 1fr)`;
  overlay.style.gridTemplateRows = `repeat(${ROWS}, 1fr)`;
  overlay.style.fontFamily = 'monospace';
  overlay.style.color = 'rgba(255,255,255,0.8)';
  overlay.style.textShadow = '0 0 2px rgba(0,0,0,0.7)';
  overlay.style.border = '2px solid rgba(255,255,255,0.4)';
  overlay.style.boxSizing = 'border-box';

  const cell = document.createElement('div');
  cell.style.border = '1px solid rgba(255,255,255,0.25)';
  cell.style.display = 'flex';
  cell.style.alignItems = 'center';
  cell.style.justifyContent = 'center';
  cell.style.fontSize = '0.8rem';

  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const clone = cell.cloneNode();
      const label = String.fromCharCode('A'.charCodeAt(0) + c) + (r + 1);
      clone.textContent = label;
      overlay.appendChild(clone);
    }
  }

  document.body.appendChild(overlay);
})();
"""


def overlay_script(rows: int, cols: int) -> str:
    """Return a JavaScript snippet for injecting the overlay."""
    return OVERLAY_INJECT_SCRIPT.replace("ROWS", str(rows)).replace("COLS", str(cols))

