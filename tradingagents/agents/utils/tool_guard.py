"""Shared safety helpers for ``@tool``-decorated agent tools.

Two failure modes we now see in practice with Z.AI / GLM (and occasionally
DeepSeek) tool-calling:

1. The LLM emits the call with an **empty string** where a YYYY-MM-DD date
   was expected. ``datetime.strptime("", "%Y-%m-%d")`` raises ValueError,
   which propagates up through langgraph's tool node and aborts the
   entire run.

2. The LLM passes a **malformed** date like ``"2026/05/19"`` or
   ``"yesterday"``. Same failure mode.

This module gives every tool two things:
  * ``normalize_date(value, *, default_offset_days=0)`` — best-effort
    parsing with a sensible default (today + offset) for empty inputs.
  * ``tool_safe(fn)`` — decorator that converts any exception inside the
    tool body into a human-readable error **string** returned to the
    LLM. The LLM can then re-call the tool with corrected arguments
    rather than the whole graph crashing.

Both helpers are deliberately stateless so they're safe to reuse from
any agent tool without import cycles.
"""

from __future__ import annotations

import functools
import logging
import re
import traceback
from datetime import datetime, timedelta
from typing import Any, Callable

_logger = logging.getLogger(__name__)

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOOSE_RE = re.compile(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$")


def normalize_date(
    value: Any,
    *,
    default_offset_days: int = 0,
    today: datetime | None = None,
) -> str:
    """Return a YYYY-MM-DD date string for ``value``.

    Empty / None / whitespace → today + ``default_offset_days``.
    Already valid YYYY-MM-DD → returned unchanged.
    ``2026/05/19``, ``2026.05.19``, ``2026-5-9`` → reformatted.
    Anything else → ``ValueError`` (caller decides how to surface).
    """
    base = today or datetime.utcnow()
    if value is None:
        return (base + timedelta(days=default_offset_days)).strftime("%Y-%m-%d")
    if not isinstance(value, str):
        # Some providers pass dates as datetime objects directly.
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        # Anything else — try str() and fall through.
        value = str(value)
    s = value.strip()
    if not s or s.lower() in {"none", "null", "today"}:
        return (base + timedelta(days=default_offset_days)).strftime("%Y-%m-%d")
    if _ISO_RE.match(s):
        # Validate that it's a real date (Feb 30 etc.)
        datetime.strptime(s, "%Y-%m-%d")
        return s
    m = _LOOSE_RE.match(s)
    if m:
        y, mo, d = m.groups()
        dt = datetime(int(y), int(mo), int(d))
        return dt.strftime("%Y-%m-%d")
    raise ValueError(
        f"Bad date {value!r}: expected YYYY-MM-DD (e.g. '2026-05-19')."
    )


def tool_safe(fn: Callable) -> Callable:
    """Decorator: catch any exception inside the tool and return an
    error string instead of letting it bubble up through langgraph.

    Important: returning a string means the LLM sees the failure as the
    tool's *output* and can choose to retry with corrected arguments.
    Raising would abort the whole graph (langgraph's default tool-error
    behavior re-raises after a single attempt).
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            # Likely a bad-argument case the LLM can fix on retry.
            _logger.warning("tool %s argument error: %s", fn.__name__, exc)
            return f"<tool-error: {exc}>  (please correct the arguments and call again)"
        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            _logger.warning(
                "tool %s failed (%s): %s\n%s",
                fn.__name__, type(exc).__name__, exc, traceback.format_exc(),
            )
            return (
                f"<tool-error: {type(exc).__name__}: {exc}>  "
                f"(transient — try a different ticker, date, or call later)"
            )

    return wrapper
