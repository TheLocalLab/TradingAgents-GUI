"""Run lifecycle management — extracted from the original gui/app.py.

Key changes from the old in-app.py implementation:

  * **Real stop / cancel.** A ``threading.Event`` per run, polled between
    graph chunks. The old Stop button on the UI hit a function that just
    posted a toast.
  * **Centralised agent / node mapping** via gui.agent_map — kills the
    fragile string-matching on node names.
  * **Multi-run support.** ``RunManager`` keys runs by id, lets clients
    target a specific run's event stream, and preserves recent runs for
    history. Backward-compat: when callers don't specify a run id we fall
    through to the most-recent run.
  * **Live cost tracking.** Tokens-in/out plus a USD estimate updated in
    real time via the price table in gui.stats.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
import traceback
import uuid
from copy import deepcopy
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from .agent_map import (
    ANALYSTS,
    FIXED_TEAMS,
    REPORT_SECTIONS,
    SECTION_TITLES,
    build_initial_roster,
    node_to_agent_display,
)
from .stats import estimate_cost

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class Run:
    """One analysis run, in-flight or completed."""

    def __init__(self, params: dict):
        self.id = uuid.uuid4().hex[:12]
        self.params = params
        self.ticker: str = params.get("ticker", "?").upper()
        self.date:   str = params.get("date", datetime.date.today().isoformat())
        self.selected: list[str] = list(params.get("analysts") or [])
        self.status: str = "queued"
        self.started_at: float = time.time()
        self.ended_at: float | None = None
        self.error: str | None = None
        self.decision: str | None = None

        self.roster: dict[str, str] = build_initial_roster(self.selected)
        self.reports: dict[str, str] = {s: "" for s in REPORT_SECTIONS}
        self.stats = {
            "llm_calls": 0, "tool_calls": 0,
            "tokens_in": 0, "tokens_out": 0,
            "cost_usd": 0.0, "elapsed_s": 0.0,
        }

        # Event fan-out
        self.queue: Queue = Queue()
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None

    def emit(self, event: dict) -> None:
        event.setdefault("run_id", self.id)
        self.queue.put(event)

    def stop(self) -> None:
        self.cancel_event.set()
        self.emit({"type": "status", "message": "🛑 Stop requested — finishing current step then aborting."})

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def snapshot(self) -> dict:
        return {
            "run_id":   self.id,
            "ticker":   self.ticker,
            "date":     self.date,
            "status":   self.status,
            "started":  self.started_at,
            "ended":    self.ended_at,
            "error":    self.error,
            "decision": self.decision,
            "selected": self.selected,
            "agents":   dict(self.roster),
            "reports":  {k: v for k, v in self.reports.items() if v},
            "stats":    dict(self.stats),
        }


# ---------------------------------------------------------------------------
# RunManager
# ---------------------------------------------------------------------------


_DEFAULT_RUNS_PATH = Path.home() / ".tradingagents" / "runs.json"


class RunManager:
    """Tracks active and recent runs.

    Run metadata (status, ticker, date, decision, stats) is persisted to a
    JSON file under ``~/.tradingagents/runs.json`` so the history survives
    server restarts. The persisted entries are a small subset of ``Run`` —
    not the live queue / threading.Event, which are obviously not
    serializable. On startup we load the file and skip anything that was
    in-flight (those threads are gone; we mark them ``error``).
    """

    def __init__(self, max_recent: int = 25,
                 persist_path: Path | None = None):
        self.runs: dict[str, Run] = {}
        self.order: list[str] = []
        self.max_recent = max_recent
        self._lock = threading.Lock()
        # Most recent run id — the SSE stream falls back to this when the
        # client doesn't specify a run.
        self.current_id: str | None = None
        self._persist_path = persist_path or _DEFAULT_RUNS_PATH
        self._load_persisted()

    def get(self, run_id: str | None) -> Run | None:
        if not run_id:
            return self.runs.get(self.current_id) if self.current_id else None
        return self.runs.get(run_id)

    def list(self) -> list[Run]:
        return [self.runs[i] for i in reversed(self.order) if i in self.runs]

    def is_anything_running(self) -> bool:
        return any(r.status == "running" for r in self.runs.values())

    def start(self, params: dict) -> Run:
        run = Run(params)
        with self._lock:
            self.runs[run.id] = run
            self.order.append(run.id)
            self.current_id = run.id
            # Evict oldest completed runs once we exceed the cap.
            while len(self.order) > self.max_recent:
                oldest_id = self.order[0]
                oldest = self.runs.get(oldest_id)
                if oldest and oldest.status in ("completed", "stopped", "error"):
                    self.order.pop(0)
                    self.runs.pop(oldest_id, None)
                else:
                    break

        run.thread = threading.Thread(
            target=_worker, args=(run, self.persist),
            name=f"run-{run.id}", daemon=True,
        )
        run.thread.start()
        # Persist immediately so a crash during the run still leaves a
        # 'queued' record visible after restart (which will be flipped to
        # 'error' on next load).
        self.persist()
        return run

    def stop(self, run_id: str | None = None) -> bool:
        run = self.get(run_id)
        if not run or run.status not in ("running", "queued"):
            return False
        run.stop()
        return True

    # --------------------------------------------------------------- persistence

    def persist(self) -> None:
        """Write the current run list to disk. Best-effort — failures are
        logged but never raise into the agent loop or HTTP handlers."""
        snapshot = {
            "version": 1,
            "current_id": self.current_id,
            "order": self.order,
            "runs": {rid: _run_to_dict(r) for rid, r in self.runs.items()},
        }
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            import os
            import tempfile
            fd, tmp = tempfile.mkstemp(prefix=".runs-", suffix=".tmp",
                                       dir=str(self._persist_path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._persist_path)
            except Exception:
                try: os.unlink(tmp)
                except OSError: pass
                raise
        except Exception:
            logger.exception("RunManager.persist failed")

    def _load_persisted(self) -> None:
        """Restore runs from disk. ``running``/``queued`` states from a
        previous server lifetime become ``error`` (those threads are gone)."""
        if not self._persist_path.exists():
            return
        try:
            with self._persist_path.open("r", encoding="utf-8") as f:
                snapshot = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        order = snapshot.get("order") or []
        runs  = snapshot.get("runs")  or {}
        for rid in order:
            data = runs.get(rid)
            if not data:
                continue
            run = _run_from_dict(data)
            if run is not None:
                self.runs[rid] = run
                self.order.append(rid)
        # current_id is informational — clear it so a fresh SSE client doesn't
        # try to subscribe to a non-running run.
        self.current_id = None


# ---------------------------------------------------------------------------
# Snapshot helpers — Run <-> JSON
# ---------------------------------------------------------------------------


_SERIALIZABLE_RUN_FIELDS = (
    "id", "ticker", "date", "selected", "status",
    "started_at", "ended_at", "error", "decision",
    "roster", "reports", "stats", "params",
)


def _run_to_dict(run: Run) -> dict:
    """Pluck only the JSON-safe bits off ``Run`` for on-disk persistence."""
    return {k: getattr(run, k, None) for k in _SERIALIZABLE_RUN_FIELDS}


def _run_from_dict(data: dict) -> Run | None:
    """Reconstruct a Run from its on-disk dict. Returns ``None`` if the dict
    is malformed. In-flight states (``running``/``queued``) are rewritten to
    ``error`` since the worker thread is obviously gone."""
    try:
        params = data.get("params") or {}
        run = Run(params)
        run.id      = data.get("id", run.id)
        run.ticker  = data.get("ticker", run.ticker)
        run.date    = data.get("date",   run.date)
        run.selected = list(data.get("selected") or [])
        # Restore final fields first, then apply the "running -> error" flip
        # so the synthetic error message isn't overwritten by the disk value
        # (which would be None for a run that was still in flight).
        run.started_at = float(data.get("started_at") or time.time())
        run.ended_at   = data.get("ended_at")
        run.error      = data.get("error")
        run.decision   = data.get("decision")
        run.status     = data.get("status", "error")
        if run.status in ("running", "queued"):
            run.status = "error"
            run.error  = run.error or "Run did not complete (server restart)."
            run.ended_at = run.ended_at or time.time()
        run.roster     = dict(data.get("roster") or {})
        run.reports    = dict(data.get("reports") or {})
        run.stats.update(data.get("stats") or {})
        return run
    except Exception:
        logger.exception("RunManager: failed to rehydrate run from %r", data)
        return None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _worker(run: Run, persist_cb=None) -> None:
    """Execute the trading graph for a single Run, emitting events to its queue.

    ``persist_cb`` is called whenever ``run.status`` changes to a terminal
    state (completed / stopped / error) so the on-disk run-history JSON
    stays in sync without each call site having to remember.
    """
    try:
        run.status = "running"
        run.emit({"type": "status", "message": f"🚀 Starting analysis: {run.ticker} on {run.date}"})

        # Push initial roster so the UI lights up before the first chunk lands.
        if run.selected:
            first_key = next((k for k in run.selected if k in ANALYSTS), None)
            if first_key:
                first_display = ANALYSTS[first_key]["display"]
                run.roster[first_display] = "in_progress"
        run.emit({"type": "agents_init", "agents": dict(run.roster)})

        # Late imports keep the module import-light (these touch ML libs).
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.graph.checkpointer import clear_all_checkpoints

        config = _build_config(run.params, DEFAULT_CONFIG)

        if run.params.get("clear_checkpoints"):
            try:
                n = clear_all_checkpoints(config["data_cache_dir"])
                run.emit({"type": "status", "message": f"🗑 Cleared {n} checkpoint(s)"})
            except Exception:
                logger.exception("clear_checkpoints failed")

        # Where the saved report lives on disk.
        results_dir = Path(config["results_dir"]) / run.ticker / run.date / "reports"
        results_dir.mkdir(parents=True, exist_ok=True)

        graph = TradingAgentsGraph(
            run.selected,
            config=config,
            debug=True,
        )

        debate_state: dict = {}
        risk_state:   dict = {}
        final_state:  dict = {}

        init_state = {
            "trade_date":              run.date,
            "company_of_interest":     run.ticker,
            "investment_debate_state": {"bull_history": "", "bear_history": "",
                                        "judge_decision": "", "count": 0},
            "risk_debate_state":       {"aggressive_history": "", "conservative_history": "",
                                        "neutral_history": "", "judge_decision": "", "count": 0},
            "messages": [],
        }
        stream_cfg = {"recursion_limit": config.get("max_recur_limit", 100)}

        deep_model  = config.get("deep_think_llm", "")
        quick_model = config.get("quick_think_llm", "")

        for chunk in graph.graph.stream(init_state, config=stream_cfg):
            if run.is_cancelled():
                break
            final_state.update(chunk)
            for node_name, state in chunk.items():
                _handle_node_chunk(run, node_name, state, debate_state, risk_state,
                                   deep_model, quick_model)

        if run.is_cancelled():
            run.status = "stopped"
        else:
            # Settle: every agent → completed, persist reports, surface decision.
            for agent in run.roster:
                run.roster[agent] = "completed"
            run.emit({"type": "agents_update", "agents": dict(run.roster)})

            for section in run.reports:
                if section in final_state and final_state[section]:
                    run.reports[section] = str(final_state[section])

            if debate_state.get("bull_history") or debate_state.get("bear_history"):
                # Format a combined debate report so the existing UI sees it.
                run.reports["investment_plan"] = _format_debate(debate_state)
            if risk_state.get("aggressive_history") or risk_state.get("conservative_history"):
                run.reports["final_trade_decision"] = _format_risk(risk_state)

            run.decision = (str(final_state.get("final_trade_decision", "")).strip() or None)

            _persist_reports(run, results_dir, debate_state, risk_state)

            run.status = "completed"
            run.emit({
                "type":     "final_report",
                "sections": {k: v for k, v in run.reports.items() if v},
                "ticker":   run.ticker,
                "date":     run.date,
                "decision": run.decision,
            })

    except Exception as exc:
        logger.exception("run %s failed", run.id)
        run.error = f"{type(exc).__name__}: {exc}"
        run.status = "error"
        # Mark the currently-in-progress agent as errored for UI feedback.
        for agent, status in run.roster.items():
            if status == "in_progress":
                run.roster[agent] = "error"
                run.emit({"type": "agent_update", "agent": agent, "status": "error",
                          "agents": dict(run.roster)})
                break
        run.emit({"type": "error",
                  "message": run.error,
                  "traceback": traceback.format_exc()})
    finally:
        run.ended_at = time.time()
        run.stats["elapsed_s"] = round(run.ended_at - run.started_at, 2)
        # Final status broadcast for clients that joined late or stayed on
        # other tabs while the run was in flight.
        run.emit({"type": "stats", "stats": dict(run.stats)})
        run.emit({"type": "done", "stopped": run.status == "stopped",
                  "status": run.status, "error": run.error})
        # Persist on completion so the run survives a restart with final
        # stats, decision, and any error message intact.
        if persist_cb is not None:
            try:
                persist_cb()
            except Exception:
                logger.exception("RunManager persist hook failed at run end")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_int(v, default=None):
    """Coerce HTML-form numeric values to int. The form sends ``"3"`` not
    ``3`` for the depth segmented control, and downstream graph code does
    ``2 * max_debate_rounds`` then compares against int counters — without
    this coercion the multiplication string-replicates (``"33"``) and the
    comparison blows up with ``int >= str``."""
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _build_config(params: dict, default_config: dict) -> dict:
    """Translate the request payload into a framework config dict."""
    cfg = deepcopy(default_config)
    # Research-depth segmented control sends a string; the graph multiplies
    # it and compares against int counters, so coerce up front.
    depth_int = _coerce_int(params.get("research_depth"), default=3)
    # Standard knobs
    overrides = {
        "llm_provider":             params.get("provider"),
        "quick_think_llm":          params.get("quick_model"),
        "deep_think_llm":           params.get("deep_model"),
        "max_debate_rounds":        depth_int,
        "max_risk_discuss_rounds":  depth_int,
        "output_language":          params.get("output_language"),
        "checkpoint_enabled":       params.get("checkpoint"),
        "backend_url":              params.get("backend_url"),
        "google_thinking_level":    params.get("google_thinking_level"),
        "openai_reasoning_effort":  params.get("openai_reasoning_effort"),
        "anthropic_effort":         params.get("anthropic_effort"),
        # New: report-length preference — affects prompt instruction added by
        # the framework when the key is present.
        "report_brevity":           params.get("report_brevity"),
    }
    for k, v in overrides.items():
        if v is not None and v != "":
            cfg[k] = v
    # Data vendors (only override what the caller actually set so we don't
    # nuke nested keys with a partial dict).
    vendors = params.get("data_vendors") or {}
    if isinstance(vendors, dict) and vendors:
        cfg.setdefault("data_vendors", {}).update(vendors)
    return cfg


def _handle_node_chunk(run: Run, node_name: str, state: Any,
                       debate_state: dict, risk_state: dict,
                       deep_model: str, quick_model: str) -> None:
    """Process a single (node_name, state) pair from the graph stream."""

    # Tool / agent completion bookkeeping
    agent_display = node_to_agent_display(node_name)
    if agent_display and agent_display in run.roster:
        if run.roster[agent_display] != "completed":
            run.roster[agent_display] = "completed"
            run.emit({"type": "agent_update", "agent": agent_display,
                      "status": "completed", "agents": dict(run.roster)})
        _advance_in_progress(run, agent_display)

    # Tool-only nodes: count the tool call, skip report extraction.
    if node_name.startswith("tools_"):
        if isinstance(state, dict):
            for msg in _iter_messages(state.get("messages")):
                for tc in getattr(msg, "tool_calls", None) or []:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?")
                    run.stats["tool_calls"] += 1
                    run.emit({"type": "tool_call", "tool": str(name), "node": node_name})
        return

    if not isinstance(state, dict):
        return

    # Top-level report fields
    event_state: dict = {}
    for section in run.reports:
        if state.get(section):
            run.reports[section] = str(state[section])
            event_state[section] = str(state[section])

    # Investment debate
    if state.get("investment_debate_state"):
        d = state["investment_debate_state"]
        for k in ("bull_history", "bear_history", "judge_decision"):
            if d.get(k):
                debate_state[k] = d[k]
        event_state["investment_debate_state"] = dict(debate_state)

    # Risk debate
    if state.get("risk_debate_state"):
        r = state["risk_debate_state"]
        for k in ("aggressive_history", "conservative_history", "neutral_history", "judge_decision"):
            if r.get(k):
                risk_state[k] = r[k]
        event_state["risk_debate_state"] = dict(risk_state)

    # Messages + token usage
    for msg in _iter_messages(state.get("messages")):
        content = getattr(msg, "content", "")
        msg_type = type(msg).__name__.replace("Message", "")
        if content:
            run.emit({"type": "message", "msg_type": msg_type,
                      "content": str(content)[:2000], "node": node_name})
        if msg_type == "AI":
            run.stats["llm_calls"] += 1
            usage = getattr(msg, "usage_metadata", None) or {}
            if usage:
                in_t  = int(usage.get("input_tokens")  or 0)
                out_t = int(usage.get("output_tokens") or 0)
                run.stats["tokens_in"]  += in_t
                run.stats["tokens_out"] += out_t
                # Cost: deep model when we're in research/trader/risk, quick otherwise.
                model = deep_model if _is_deep_model_node(node_name) else quick_model
                run.stats["cost_usd"] = round(
                    run.stats["cost_usd"] + estimate_cost(in_t, out_t, model), 4
                )

    run.stats["elapsed_s"] = round(time.time() - run.started_at, 2)
    run.emit({"type": "stats", "stats": dict(run.stats)})

    if event_state:
        run.emit({"type": "chunk", "node": node_name, "state": event_state})


def _is_deep_model_node(node_name: str) -> bool:
    """Deep-thinking models drive these higher-cost nodes."""
    return node_name in {
        "Research Manager", "Bull Researcher", "Bear Researcher",
        "Trader", "Aggressive Analyst", "Neutral Analyst",
        "Conservative Analyst", "Portfolio Manager",
    }


_NEXT_AFTER_FIXED = {
    "Bull Researcher":     "Bear Researcher",
    "Bear Researcher":     "Research Manager",
    "Research Manager":    "Trader",
    "Trader":              "Aggressive Analyst",
    "Aggressive Analyst":  "Neutral Analyst",
    "Neutral Analyst":     "Conservative Analyst",
    "Conservative Analyst":"Portfolio Manager",
}


def _advance_in_progress(run: Run, just_completed_display: str) -> None:
    """Move the next pending agent to in_progress after one finishes."""
    # Analyst path: walk the selected analyst order
    analyst_displays = [ANALYSTS[k]["display"] for k in run.selected if k in ANALYSTS]
    if just_completed_display in analyst_displays:
        idx = analyst_displays.index(just_completed_display)
        if idx + 1 < len(analyst_displays):
            _maybe_in_progress(run, analyst_displays[idx + 1])
        else:
            # All analysts done — wake the research team.
            _maybe_in_progress(run, "Bull Researcher")
            _maybe_in_progress(run, "Bear Researcher")
            _maybe_in_progress(run, "Research Manager")
        return

    nxt = _NEXT_AFTER_FIXED.get(just_completed_display)
    if nxt:
        _maybe_in_progress(run, nxt)


def _maybe_in_progress(run: Run, display: str) -> None:
    """Promote a pending agent to in_progress and emit an update."""
    if run.roster.get(display) == "pending":
        run.roster[display] = "in_progress"
        run.emit({"type": "agent_update", "agent": display,
                  "status": "in_progress", "agents": dict(run.roster)})


def _iter_messages(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ---------------------------------------------------------------------------
# Report formatting + persistence
# ---------------------------------------------------------------------------


def _format_debate(debate: dict) -> str:
    parts = []
    if debate.get("bull_history"):    parts.append(f"### Bull Researcher\n{debate['bull_history']}")
    if debate.get("bear_history"):    parts.append(f"### Bear Researcher\n{debate['bear_history']}")
    if debate.get("judge_decision"):  parts.append(f"### Research Manager Decision\n{debate['judge_decision']}")
    return "\n\n".join(parts)


def _format_risk(risk: dict) -> str:
    parts = []
    if risk.get("aggressive_history"):    parts.append(f"### Aggressive Analyst\n{risk['aggressive_history']}")
    if risk.get("neutral_history"):       parts.append(f"### Neutral Analyst\n{risk['neutral_history']}")
    if risk.get("conservative_history"):  parts.append(f"### Conservative Analyst\n{risk['conservative_history']}")
    if risk.get("judge_decision"):        parts.append(f"### Portfolio Manager Decision\n{risk['judge_decision']}")
    return "\n\n".join(parts)


def _persist_reports(run: Run, save_path: Path,
                     debate_state: dict, risk_state: dict) -> None:
    """Write per-section + combined markdown files to disk."""
    SECTION_PATHS = {
        "market_report":          "1_analysts/market.md",
        "sentiment_report":       "1_analysts/sentiment.md",
        "news_report":            "1_analysts/news.md",
        "fundamentals_report":    "1_analysts/fundamentals.md",
        "investment_plan":        "2_research/investment_plan.md",
        "trader_investment_plan": "3_trading/trader.md",
        "final_trade_decision":   "5_portfolio/decision.md",
    }
    parts = [f"# Trading Analysis Report: {run.ticker}\n",
             f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M:%S}_\n",
             f"_Decision_: **{run.decision or 'N/A'}**\n",
             ""]
    for section, rel in SECTION_PATHS.items():
        body = run.reports.get(section)
        if body:
            (save_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (save_path / rel).write_text(body, encoding="utf-8")
            parts.append(f"## {SECTION_TITLES.get(section, section)}\n\n{body}\n")

    if debate_state and any(debate_state.values()):
        debate_dir = save_path / "2_research"
        debate_dir.mkdir(parents=True, exist_ok=True)
        for k, name in (("bull_history","bull.md"),
                        ("bear_history","bear.md"),
                        ("judge_decision","manager.md")):
            if debate_state.get(k):
                (debate_dir / name).write_text(debate_state[k], encoding="utf-8")

    if risk_state and any(risk_state.values()):
        risk_dir = save_path / "4_risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        for k, name in (("aggressive_history","aggressive.md"),
                        ("conservative_history","conservative.md"),
                        ("neutral_history","neutral.md")):
            if risk_state.get(k):
                (risk_dir / name).write_text(risk_state[k], encoding="utf-8")
        if risk_state.get("judge_decision"):
            (save_path / "5_portfolio").mkdir(parents=True, exist_ok=True)
            (save_path / "5_portfolio" / "risk_decision.md").write_text(
                risk_state["judge_decision"], encoding="utf-8")

    # Combined master file
    (save_path / "complete_report.md").write_text("\n".join(parts), encoding="utf-8")

    # Run metadata blob for the reports index.
    meta = {
        "run_id":   run.id,
        "ticker":   run.ticker,
        "date":     run.date,
        "decision": run.decision,
        "stats":    run.stats,
        "saved_at": time.time(),
    }
    (save_path / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
