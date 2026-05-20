"""Chat session storage and orchestration.

Multi-session chat with per-session pinned reports. Sessions live as JSON
files under ``~/.tradingagents/chat/<id>.json`` so they persist across
restarts and can be inspected / deleted with a text editor.

Design notes:

  * **Pinned reports** are stored as `(ticker, date)` pairs. The actual
    report markdown is re-read from disk at send time so a user who
    re-runs an analysis automatically sees the fresh report in subsequent
    messages. (Locking the report text in at pin time would mean stale
    chats after a re-run.)

  * **System prompt** is built from a base instruction + every pinned
    report concatenated as `## {ticker} — {date}` sections. The full
    prompt is regenerated per turn — cheap, and avoids drift.

  * **Token counter** is a rough char/4 heuristic by default; if the
    optional ``tiktoken`` package is installed we use that for OpenAI-style
    models. The UI surfaces this as a "running context size" indicator
    with a warning band when approaching the model's window.

  * **Streaming** uses the same SSE pattern as run streaming so the
    frontend already has the plumbing.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

CHAT_DIR = Path.home() / ".tradingagents" / "chat"
CHAT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def count_tokens(text: str, model: str = "") -> int:
    """Return a token-count estimate for ``text``.

    Uses tiktoken when available (gives accurate counts for OpenAI-family
    models and reasonable approximations for others). Falls back to a
    chars/4 heuristic, which is within ~20% for English prose.
    """
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore
        try:
            enc = tiktoken.encoding_for_model(model) if model else tiktoken.get_encoding("cl100k_base")
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 4)


# Per-model context windows. Approximate; used only for the warning UI.
CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-5.5":            1_000_000,
    "gpt-5.5-pro":        1_000_000,
    "gpt-5.4":            1_000_000,
    "gpt-5.4-mini":       1_000_000,
    "gpt-5.4-nano":         400_000,
    "gpt-5.2":              400_000,
    "gpt-4.1":            1_000_000,
    # Anthropic
    "claude-opus-4-7":      200_000,
    "claude-opus-4-6":      200_000,
    "claude-opus-4-5":      200_000,
    "claude-sonnet-4-6":    200_000,
    "claude-sonnet-4-5":    200_000,
    "claude-haiku-4-5":     200_000,
    # Google
    "gemini-3.1-pro-preview":  2_000_000,
    "gemini-3-flash-preview":  1_000_000,
    "gemini-3.1-flash-lite":   1_000_000,
    "gemini-2.5-pro":          2_000_000,
    "gemini-2.5-flash":        1_000_000,
    # DeepSeek
    "deepseek-v4-pro":        128_000,
    "deepseek-v4-flash":      128_000,
    "deepseek-chat":          128_000,
    "deepseek-reasoner":      128_000,
}


def context_window(model: str) -> int:
    """Return a published context window (in tokens) for ``model``.

    Default: 128k — the smallest modern window. Conservative so users don't
    silently overflow before we warn them.
    """
    return CONTEXT_WINDOWS.get(model, 128_000)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful trading-research assistant inside the TradingAgents "
    "local GUI. The user may pin past multi-agent analysis reports to this "
    "chat. When reports are pinned they appear below in a block delimited "
    "by '=== ATTACHED REPORTS ===' and '=== END ATTACHED REPORTS ===', "
    "with each individual report wrapped in '<<<BEGIN-REPORT … >>>' and "
    "'<<<END-REPORT>>>' markers. Those reports ARE in your context — when "
    "asked about them, answer directly from their content. Never claim "
    "no report is attached when those markers are present.\n\n"
    "Be concise by default, expand on request. Never fabricate trade ideas "
    "or claim certainty; surface uncertainty plainly. Always remind the user "
    "this is educational software, not financial advice."
)


class ChatSession:
    """One named chat conversation with optional pinned reports."""

    def __init__(self, *, id: Optional[str] = None, name: str = "New chat",
                 provider: str = "openai", model: str = "gpt-5.4-mini",
                 attached_reports: Optional[list[dict]] = None,
                 messages: Optional[list[dict]] = None,
                 created_at: Optional[float] = None,
                 updated_at: Optional[float] = None,
                 system_prompt: Optional[str] = None):
        self.id            = id or uuid.uuid4().hex[:12]
        self.name          = name
        self.provider      = provider
        self.model         = model
        self.attached      = list(attached_reports or [])
        self.messages      = list(messages or [])
        self.created_at    = created_at or time.time()
        self.updated_at    = updated_at or time.time()
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # ----- Persistence ------------------------------------------------------

    @property
    def path(self) -> Path:
        return CHAT_DIR / f"{self.id}.json"

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "name":           self.name,
            "provider":       self.provider,
            "model":          self.model,
            "attached":       self.attached,
            "messages":       self.messages,
            "created_at":     self.created_at,
            "updated_at":     self.updated_at,
            "system_prompt":  self.system_prompt,
        }

    def save(self) -> None:
        self.updated_at = time.time()
        self.path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, sid: str) -> Optional["ChatSession"]:
        f = CHAT_DIR / f"{sid}.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("failed loading chat %s", sid)
            return None
        return cls(
            id            = data.get("id", sid),
            name          = data.get("name", "Unnamed"),
            provider      = data.get("provider", "openai"),
            model         = data.get("model", "gpt-5.4-mini"),
            attached_reports = data.get("attached") or [],
            messages      = data.get("messages") or [],
            created_at    = data.get("created_at"),
            updated_at    = data.get("updated_at"),
            system_prompt = data.get("system_prompt"),
        )

    @classmethod
    def list_summaries(cls) -> list[dict]:
        """Lightweight metadata-only listing for the sidebar."""
        out = []
        for f in CHAT_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            msgs = data.get("messages") or []
            out.append({
                "id":          data.get("id", f.stem),
                "name":        data.get("name", "Untitled"),
                "model":       data.get("model"),
                "updated_at":  data.get("updated_at", f.stat().st_mtime),
                "msg_count":   len(msgs),
                "attached":    len(data.get("attached") or []),
            })
        out.sort(key=lambda s: s["updated_at"], reverse=True)
        return out

    def delete(self) -> None:
        if self.path.exists():
            self.path.unlink()

    # ----- Mutation ---------------------------------------------------------

    def add_message(self, role: str, content: str) -> dict:
        msg = {"role": role, "content": content, "ts": time.time()}
        self.messages.append(msg)
        self.save()
        return msg

    def pin_report(self, ticker: str, date: str) -> None:
        item = {"ticker": ticker, "date": date}
        if item not in self.attached:
            self.attached.append(item)
            self.save()

    def unpin_report(self, ticker: str, date: str) -> None:
        self.attached = [a for a in self.attached
                         if not (a.get("ticker") == ticker and a.get("date") == date)]
        self.save()

    # ----- Prompt assembly --------------------------------------------------

    def assembled_system_prompt(self, results_base: Path) -> str:
        """Build the system message: base prompt + every pinned report inline.

        Pinned reports are wrapped in explicit BEGIN/END markers and a
        directive header. Smaller Ollama models in particular often
        miss "attached reports" embedded as plain markdown headings, so
        the wrapping makes the boundary unambiguous and tells the model
        what to do with the content.
        """
        parts: list[str] = [self.system_prompt.strip()]

        if not self.attached:
            return parts[0]

        parts.append("")
        parts.append(
            f"=== ATTACHED REPORTS ({len(self.attached)}) ===\n"
            "The user has pinned the following TradingAgents analysis "
            "report(s) to this conversation. Treat the content between "
            "<<<BEGIN-REPORT>>> and <<<END-REPORT>>> as authoritative "
            "context that you HAVE in front of you — refer to it by "
            "ticker and date, quote from it when helpful, and answer "
            "questions about it directly. Do NOT tell the user there is "
            "no report attached; the reports are below."
        )

        for ref in self.attached:
            ticker = ref.get("ticker", "?")
            date   = ref.get("date",   "?")
            body   = _load_report(results_base, ticker, date)
            header = f"<<<BEGIN-REPORT ticker={ticker} date={date}>>>"
            footer = "<<<END-REPORT>>>"
            if not body:
                parts.append(
                    f"{header}\n"
                    f"_(report file not found on disk — expected "
                    f"results_dir/{ticker}/{date}/reports/complete_report.md. "
                    f"User should re-run the analysis or check the "
                    f"results_dir setting.)_\n"
                    f"{footer}"
                )
            else:
                parts.append(f"{header}\n\n{body.strip()}\n\n{footer}")

        parts.append("=== END ATTACHED REPORTS ===")
        return "\n\n".join(parts)

    def token_estimate(self, results_base: Path) -> dict:
        """Return token counts for the *next* turn: system + history + buffer."""
        system = self.assembled_system_prompt(results_base)
        sys_tokens = count_tokens(system, self.model)
        hist_tokens = sum(count_tokens(m.get("content", ""), self.model)
                          for m in self.messages)
        total = sys_tokens + hist_tokens
        window = context_window(self.model)
        return {
            "system_tokens":  sys_tokens,
            "history_tokens": hist_tokens,
            "total_tokens":   total,
            "context_window": window,
            "ratio":          round(total / window, 3) if window else 0,
        }


# ---------------------------------------------------------------------------
# Report lookup
# ---------------------------------------------------------------------------

def _load_report(results_base: Path, ticker: str, date: str) -> Optional[str]:
    """Read the saved complete_report.md for a ticker+date, if it exists."""
    p = results_base / ticker / date / "reports" / "complete_report.md"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Streaming completion
# ---------------------------------------------------------------------------

def _extract_text(chunk) -> str:
    """Pull the visible text out of a langchain stream chunk.

    Different providers expose ``content`` in incompatible shapes:

    * **String** (OpenAI chat-completions, most providers) — return as-is.
    * **List of typed blocks** (Gemini 3, Anthropic, OpenAI Responses API) —
      e.g. ``[{"type":"text","text":"Hi"}, {"type":"reasoning", …}]``. We
      keep only ``text``-type blocks and drop reasoning/thinking blocks
      so the chat UI doesn't render the model's scratchpad.
    * **Empty list** — was the old failure mode; the previous code fell
      through to ``str(chunk)`` and printed the entire ``AIMessageChunk
      (content=[], additional_kwargs={…})`` repr. We now return ``""``
      and skip the chunk.

    The function never returns ``None`` — callers can use the truthy
    check ``if not piece: continue`` and trust empty strings to mean
    "nothing visible in this chunk".
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type") or ""
            # Skip reasoning / thinking / function-call blocks — the user
            # only wants the model's spoken answer in the chat bubble.
            if btype in ("reasoning", "thinking", "function_call",
                         "tool_use", "tool_call"):
                continue
            text = block.get("text") or block.get("content")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""



def _synth_report_exchange(session: "ChatSession",
                           results_base: Path) -> tuple[str, str]:
    """Build a synthetic ``(user, assistant)`` turn pair that surfaces the
    pinned report content into the conversation history.

    Why: smaller Ollama models (qwen2.5:0.5b, llama3.2:1b, gemma2:2b, etc.)
    routinely fail to attend to long system prompts on the **first** turn —
    they treat the system block as boilerplate. By the second turn they
    pick it up because they now have conversation history to anchor on.
    Injecting a synthetic exchange at the start of every conversation
    moves the pinned report content into "history" from turn one.

    The pair is rebuilt fresh on each call (not persisted to disk) so
    pin/unpin changes are always reflected.

    Returns ``("", "")`` if nothing useful can be loaded — caller checks
    the truthiness before appending.
    """
    if not session.attached:
        return "", ""

    blocks: list[str] = []
    found_any = False
    for ref in session.attached:
        ticker = ref.get("ticker", "?")
        date   = ref.get("date",   "?")
        body   = _load_report(results_base, ticker, date)
        if body:
            blocks.append(
                f"<<<BEGIN-REPORT ticker={ticker} date={date}>>>\n\n"
                f"{body.strip()}\n\n"
                f"<<<END-REPORT>>>"
            )
            found_any = True
        else:
            blocks.append(
                f"<<<BEGIN-REPORT ticker={ticker} date={date}>>>\n"
                f"_(report file not found on disk — user can re-run.)_\n"
                f"<<<END-REPORT>>>"
            )

    if not found_any:
        return "", ""

    summary = ", ".join(
        f"{r.get('ticker','?')} ({r.get('date','?')})" for r in session.attached
    )
    user_msg = (
        f"I've pinned the following TradingAgents report(s) to this "
        f"conversation: {summary}. Here is the full content. Please use it "
        f"as authoritative context — reference it directly when I ask, "
        f"quote from it when helpful, and don't claim it's not attached.\n\n"
        + "\n\n".join(blocks)
    )
    ack = (
        f"Got it — I have the pinned report(s) for {summary} in front of me. "
        f"I'll reference the content directly when you ask about it. What "
        f"would you like to know?"
    )
    return user_msg, ack


def stream_reply(session: ChatSession, results_base: Path,
                 user_content: str) -> Iterator[dict]:
    """Generate a streamed assistant reply for ``user_content``.

    Yields SSE-friendly dicts:
      {"type": "user_saved",  "message": {...}}        # echoes the saved user msg
      {"type": "token",       "token":   "..."}        # partial assistant output
      {"type": "assistant",   "message": {...}}        # final saved assistant msg
      {"type": "error",       "message": "..."}
      {"type": "done"}
    """
    # Save the user's message first so it survives a mid-stream crash.
    user_msg = session.add_message("user", user_content)
    yield {"type": "user_saved", "message": user_msg}

    try:
        from tradingagents.llm_clients import create_llm_client
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    except Exception as e:
        yield {"type": "error", "message": f"LLM client unavailable: {e}"}
        yield {"type": "done"}
        return

    # Build the message list. Pinned reports go into BOTH the system
    # message AND a synthetic user+assistant exchange at the front of
    # the history. Smaller Ollama models routinely under-weight a long
    # system message on the very first turn but pay strong attention to
    # conversation history — duplicating the content (system for big
    # models, history for small models) costs us some tokens but makes
    # "what's in this report?" actually work across the full provider
    # matrix on every turn instead of only after a second send.
    system_text = session.assembled_system_prompt(results_base)
    system      = SystemMessage(content=system_text)
    lc_messages: list = [system]

    if session.attached:
        report_user, report_ack = _synth_report_exchange(session, results_base)
        if report_user:
            lc_messages.append(HumanMessage(content=report_user))
            lc_messages.append(AIMessage(content=report_ack))

    for m in session.messages:
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_messages.append(AIMessage(content=m["content"]))

    try:
        client = create_llm_client(provider=session.provider, model=session.model)
        llm = client.get_llm()
    except Exception as e:
        yield {"type": "error", "message": f"Could not init {session.provider}/{session.model}: {e}"}
        yield {"type": "done"}
        return

    full: list[str] = []
    try:
        # langchain LLMs support .stream() returning token-by-token chunks.
        for chunk in llm.stream(lc_messages):
            piece = _extract_text(chunk)
            if not piece:
                continue
            full.append(piece)
            yield {"type": "token", "token": piece}
    except Exception as e:
        # Some clients don't support streaming; fall back to a single invoke.
        if not full:
            try:
                res = llm.invoke(lc_messages)
                piece = _extract_text(res)
                if piece:
                    full.append(piece)
                    yield {"type": "token", "token": piece}
            except Exception as e2:
                yield {"type": "error", "message": f"LLM call failed: {e2}"}
                yield {"type": "done"}
                return
        else:
            logger.exception("stream interrupted")
            yield {"type": "error", "message": f"Stream interrupted: {e}"}
            # Fall through — we'll still save what we got.

    content = "".join(full).strip()
    if content:
        msg = session.add_message("assistant", content)
        yield {"type": "assistant", "message": msg}
    yield {"type": "done"}
