"""Atomic, mask-aware .env management for the GUI.

Two real bugs in the old hand-rolled approach:
  * Clearing a masked field (the placeholder text) saved as blank,
    silently wiping the existing key.
  * `set_key` from python-dotenv writes one key at a time, no
    atomicity — a power-loss mid-write could corrupt .env.

This module fixes both:
  * The frontend sends ``KEEP_SENTINEL`` (a constant string) for any field
    the user did not modify. Anything else is treated as an explicit
    set-or-clear.
  * Writes go to a temp file in the same dir then atomically replace, with
    a ``.env.bak`` backup of the previous file.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from dotenv import dotenv_values

KEEP_SENTINEL = "__keep__"

_SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$", re.IGNORECASE)


def is_secret(name: str) -> bool:
    """Heuristic: env vars ending in KEY/TOKEN/SECRET/PASSWORD are masked."""
    return bool(_SECRET_RE.search(name))


def mask(value: str) -> str:
    """Return a display-safe masked version of a secret value."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}…{value[-4:]}"


class EnvStore:
    """File-backed env-var store with safe writes."""

    def __init__(self, env_path: Path, extra_paths: Optional[Iterable[Path]] = None):
        self.path = Path(env_path)
        self.extras = [Path(p) for p in (extra_paths or []) if Path(p).exists()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    # ---- Read --------------------------------------------------------------

    def all(self) -> dict[str, str]:
        """Merged view: primary .env + any extras (extras lose ties to primary)."""
        merged: dict[str, str] = {}
        for extra in self.extras:
            merged.update({k: v for k, v in dotenv_values(extra).items() if v is not None})
        merged.update({k: v for k, v in dotenv_values(self.path).items() if v is not None})
        return merged

    def get(self, name: str) -> Optional[str]:
        return self.all().get(name)

    def display(self, keys: Iterable[str]) -> dict[str, dict]:
        """Build the GUI-friendly view of a specific list of env vars."""
        current = self.all()
        out = {}
        for k in keys:
            value = current.get(k, "")
            out[k] = {
                "set":       bool(value),
                "value":     mask(value) if (value and is_secret(k)) else value,
                "is_secret": is_secret(k),
            }
        return out

    # ---- Write -------------------------------------------------------------

    def update(self, updates: dict[str, Optional[str]]) -> dict:
        """Apply a batch of updates atomically to the primary .env file.

        Rules:
          * value == KEEP_SENTINEL → leave existing value alone
          * value is None or ""    → remove the key entirely
          * anything else (str)    → upsert
        """
        # Read only the primary file — never mutate extras.
        current = {k: v for k, v in dotenv_values(self.path).items() if v is not None}
        changed = {"set": [], "cleared": [], "kept": []}

        for key, new in updates.items():
            if new == KEEP_SENTINEL:
                changed["kept"].append(key)
                continue
            if new is None or new == "":
                if key in current:
                    current.pop(key)
                    changed["cleared"].append(key)
            else:
                if current.get(key) != new:
                    current[key] = new
                    changed["set"].append(key)

        self._write_atomic(current)

        # Reflect in the live process so subsequent runs see the new values.
        for k, v in current.items():
            os.environ[k] = v
        for k in changed["cleared"]:
            os.environ.pop(k, None)

        return changed

    def _write_atomic(self, contents: dict[str, str]) -> None:
        # Snapshot the previous file as .env.bak so a botched write is recoverable.
        if self.path.exists() and self.path.stat().st_size:
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))

        fd, tmp_path = tempfile.mkstemp(
            prefix=".env.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
                fp.write("# Managed by TradingAgents GUI. Manual edits preserved on next save.\n")
                for k in sorted(contents):
                    fp.write(f"{k}={_escape(contents[k])}\n")
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise


def _escape(value: str) -> str:
    """Quote env values that contain whitespace or shell-special chars."""
    if not value:
        return ""
    if re.search(r"[\s\"#'$\\]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
