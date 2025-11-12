"""Virtual cursor overlay helpers."""
from __future__ import annotations


def cursor_init_script() -> str:
    """Return a script that injects the virtual cursor element."""

    return """
(() => {
  if (window.__llmdvs_cursor) {
    return;
  }
  const cursor = document.createElement('div');
  cursor.id = '__llmdvs_cursor';
  cursor.style.position = 'fixed';
  cursor.style.top = '0';
  cursor.style.left = '0';
  cursor.style.width = '18px';
  cursor.style.height = '18px';
  cursor.style.marginLeft = '-9px';
  cursor.style.marginTop = '-9px';
  cursor.style.borderRadius = '50%';
  cursor.style.background = 'rgba(255, 99, 71, 0.9)';
  cursor.style.border = '2px solid rgba(255, 255, 255, 0.9)';
  cursor.style.boxShadow = '0 0 10px rgba(255, 99, 71, 0.65)';
  cursor.style.transition = 'transform 0.2s ease-out';
  cursor.style.transform = 'translate(-100px, -100px)';
  cursor.style.pointerEvents = 'none';
  cursor.style.zIndex = '2147483647';
  document.body.appendChild(cursor);
  window.__llmdvs_cursor = cursor;
})();
"""


def cursor_move_script() -> str:
    """Return a script that animates the virtual cursor position."""

    return """
((x, y, duration) => {
  let cursor = window.__llmdvs_cursor;
  if (!cursor) {
    return false;
  }
  const clampedDuration = Math.max(0.05, Math.min(duration || 0.2, 1));
  cursor.style.transitionDuration = `${clampedDuration}s`;
  cursor.style.transform = `translate(${x}px, ${y}px)`;
  return true;
})
"""
