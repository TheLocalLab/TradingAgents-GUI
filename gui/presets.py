"""Form-preset storage for the Analyze tab.

Persists named bundles of analyze-form settings (ticker, analysts, depth,
language, brevity, provider, models, etc.) as JSON files under
``~/.tradingagents/presets/`` so they survive server restarts and can be
reloaded with one click. The dict shape is opaque to this module — the
front-end snapshots the form however it likes and we round-trip it.

Atomic writes (tempfile + os.replace) keep the file safe under concurrent
write attempts. A ``.bak`` of the previous contents is kept on every write
in case the user wants to recover by hand from disk.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-\.]+")
MAX_NAME_LEN = 80


def _default_dir() -> Path:
    return Path.home() / ".tradingagents" / "presets"


class PresetsStore:
    """JSON-on-disk store. One file per preset, named ``<id>.json``."""

    def __init__(self, base_dir: Path | None = None):
        self.dir = Path(base_dir) if base_dir else _default_dir()
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- public
    def list(self) -> list[dict[str, Any]]:
        """Return all preset metadata, newest-updated first."""
        out: list[dict[str, Any]] = []
        for p in self.dir.glob("*.json"):
            try:
                data = self._read(p)
                out.append({
                    "id":         data.get("id") or p.stem,
                    "name":       data.get("name") or p.stem,
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "preview":    self._preview(data.get("values", {})),
                })
            except Exception:
                continue
        out.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
        return out

    def get(self, pid: str) -> dict[str, Any] | None:
        path = self._path_for(pid)
        if not path.exists():
            return None
        return self._read(path)

    def create(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        """Create a new preset. If a preset with this name exists, overwrites it."""
        name = self._normalize_name(name)
        existing = self._find_by_name(name)
        now = int(time.time())
        if existing:
            existing["values"]     = values
            existing["updated_at"] = now
            self._write(self._path_for(existing["id"]), existing)
            return existing
        pid = uuid.uuid4().hex[:12]
        data = {
            "id":         pid,
            "name":       name,
            "created_at": now,
            "updated_at": now,
            "values":     values,
        }
        self._write(self._path_for(pid), data)
        return data

    def update(self, pid: str, *, name: str | None = None,
               values: dict[str, Any] | None = None) -> dict[str, Any] | None:
        data = self.get(pid)
        if not data:
            return None
        if name is not None:
            data["name"] = self._normalize_name(name)
        if values is not None:
            data["values"] = values
        data["updated_at"] = int(time.time())
        self._write(self._path_for(pid), data)
        return data

    def delete(self, pid: str) -> bool:
        path = self._path_for(pid)
        if not path.exists():
            return False
        # Move to .bak rather than rm so the file is still recoverable.
        bak = path.with_suffix(".json.bak")
        try:
            if bak.exists():
                bak.unlink()
            path.rename(bak)
        except OSError:
            path.unlink(missing_ok=True)
        return True

    # ---------------------------------------------------------------- helpers
    def _path_for(self, pid: str) -> Path:
        # Defensive: only allow our own id format.
        safe = re.sub(r"[^A-Za-z0-9_\-]", "", pid)[:64]
        return self.dir / f"{safe}.json"

    def _find_by_name(self, name: str) -> dict[str, Any] | None:
        target = name.lower()
        for p in self.dir.glob("*.json"):
            try:
                data = self._read(p)
                if (data.get("name") or "").lower() == target:
                    return data
            except Exception:
                continue
        return None

    @staticmethod
    def _normalize_name(name: str) -> str:
        s = _SAFE_NAME.sub("", (name or "").strip())[:MAX_NAME_LEN]
        return s or "Untitled preset"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write — tempfile in the same dir + os.replace.
        fd, tmp = tempfile.mkstemp(prefix=".preset-", suffix=".tmp",
                                   dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise

    @staticmethod
    def _preview(values: dict[str, Any]) -> str:
        """Two-or-three-line summary string surfaced in the dropdown."""
        ticker  = values.get("ticker") or "—"
        depth   = values.get("depth") or "—"
        brev    = values.get("brevity") or "—"
        prov    = values.get("provider") or "—"
        return f"{ticker} · depth {depth} · {brev} · {prov}"
