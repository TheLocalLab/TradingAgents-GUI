"""Server-side persistence for Configuration-tab UI state.

Lightweight JSON store at ``~/.tradingagents/ui_state.json`` for the
"sticky" settings the Configuration tab manages: chosen LLM provider,
quick/deep model IDs, custom backend URL, reasoning effort, data-vendor
selections. Survives server restarts and follows the user across
browsers (unlike localStorage).

Intentionally narrow API — get the whole blob, set the whole blob.
The blob is opaque; the front-end snapshots what it cares about.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    return Path.home() / ".tradingagents" / "ui_state.json"


class UIStateStore:
    """One JSON file. Whole-blob get/set. Atomic writes."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def merge(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Shallow-merge ``updates`` into the existing blob and persist."""
        current = self.get()
        current.update(updates or {})
        self._write_atomic(current)
        return current

    def replace(self, blob: dict[str, Any]) -> dict[str, Any]:
        """Replace the entire blob (no merge)."""
        clean = blob if isinstance(blob, dict) else {}
        self._write_atomic(clean)
        return clean

    # ----------------------------------------------------------------
    def _write_atomic(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".uistate-", suffix=".tmp",
                                   dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
