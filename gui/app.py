"""TradingAgents GUI — Flask backend.

Routes serve a single-page UI that runs analyses, manages API keys and
provider/model selection, and browses saved reports. Heavy lifting lives in
the sibling modules:

  * gui.run_manager  — Run + RunManager, the actual graph driver
  * gui.providers    — provider catalog, key-test recipes
  * gui.env_store    — atomic .env IO with safe masking
  * gui.agent_map    — agent / report / node-name canonical metadata
  * gui.stats        — token pricing table + cost estimator
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# Make `tradingagents` importable when run from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

from . import __version__ as GUI_VERSION
from .agent_map import ANALYSTS, FIXED_TEAMS, SECTION_TITLES
from .chat import ChatSession, count_tokens, context_window, stream_reply
from .env_store import KEEP_SENTINEL, EnvStore
from .providers import (
    PROVIDER_NOTES,
    TEST_RECIPES,
    env_keys_for_ui,
    provider_list,
)
from .presets import PresetsStore
from .run_manager import RunManager
from .stats import estimate_run_cost, MODEL_PRICING
from .ui_state import UIStateStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths + bootstrap
# ---------------------------------------------------------------------------

PROJECT_ROOT      = Path(__file__).parent.parent
ENV_PATH          = PROJECT_ROOT / ".env"
ENV_ENTERPRISE    = PROJECT_ROOT / ".env.enterprise"
load_dotenv(ENV_PATH)
load_dotenv(ENV_ENTERPRISE, override=False)

env_store = EnvStore(ENV_PATH, extra_paths=[ENV_ENTERPRISE])
runs      = RunManager()
presets   = PresetsStore()
ui_state  = UIStateStore()

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", gui_version=GUI_VERSION)


# ---------------------------------------------------------------------------
# Health & meta
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({"ok": True, "version": GUI_VERSION, "ts": time.time()})


@app.route("/api/health/detailed")
def health_detailed():
    """A real diagnostic — runs system / dependency / config checks for the Setup tab.

    Each check returns ``ok`` (bool), ``label`` (display name), ``detail``
    (one-line human-readable explanation), and ``hint`` (action the user
    should take if not ``ok``). The Setup tab renders these as a stateful
    health card list.
    """
    import importlib
    import platform
    import shutil

    checks: list[dict] = []

    # 1. Python version
    pyver = platform.python_version_tuple()
    py_ok = (int(pyver[0]), int(pyver[1])) >= (3, 10)
    checks.append({
        "key":    "python",
        "ok":     py_ok,
        "label":  "Python 3.10+",
        "detail": f"Found Python {platform.python_version()}",
        "hint":   "Install Python 3.10 or newer from python.org and re-run install." if not py_ok else "",
    })

    # 2. Core dependencies
    required = [
        ("langchain_core", "langchain-core"),
        ("langgraph",      "langgraph"),
        ("yfinance",       "yfinance"),
        ("flask",          "flask"),
        ("dotenv",         "python-dotenv"),
    ]
    for module, pkg in required:
        try:
            importlib.import_module(module)
            checks.append({
                "key": f"dep_{pkg}", "ok": True,
                "label": pkg,
                "detail": "Installed",
                "hint": "",
            })
        except ImportError as e:
            checks.append({
                "key": f"dep_{pkg}", "ok": False,
                "label": pkg,
                "detail": str(e),
                "hint": f"Run install.bat / install.sh, or `pip install {pkg}` manually.",
            })

    # 3. Framework version + GUI version
    try:
        from tradingagents import __version__ as fw_version
    except Exception:
        fw_version = "?"
    checks.append({
        "key": "framework_version", "ok": True,
        "label": "Framework version",
        "detail": f"TradingAgents {fw_version} • GUI {GUI_VERSION}",
        "hint": "",
    })

    # 4. At least one provider key configured
    env_values = env_store.all()
    has_any_key = any(
        env_values.get(env_var)
        for env_var in PROVIDER_API_KEY_ENV.values()
        if env_var
    )
    checks.append({
        "key": "api_key", "ok": has_any_key,
        "label": "API key set",
        "detail": "At least one provider has a key in .env"
                  if has_any_key else "No provider keys configured",
        "hint": "Go to the API Keys tab and paste a key for at least one provider."
                if not has_any_key else "",
    })

    # 5. Results directory writable
    try:
        base = _results_base()
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".gui-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        rw_ok = True
        rw_detail = f"Writable: {base}"
        rw_hint = ""
    except Exception as e:
        rw_ok = False
        rw_detail = f"{type(e).__name__}: {e}"
        rw_hint = "Pick a writable folder for TRADINGAGENTS_RESULTS_DIR in the API Keys tab."
    checks.append({
        "key": "results_dir", "ok": rw_ok,
        "label": "Results directory writable",
        "detail": rw_detail,
        "hint": rw_hint,
    })

    # 6. Disk space (warn-only — not a hard fail)
    try:
        usage = shutil.disk_usage(str(_results_base()))
        free_gb = usage.free / (1024 ** 3)
        disk_ok = free_gb > 1.0
    except Exception:
        free_gb = 0
        disk_ok = True  # don't fail closed
    checks.append({
        "key": "disk_space", "ok": disk_ok,
        "label": "Free disk space",
        "detail": f"{free_gb:.1f} GB free",
        "hint": "Free up some space; reports are small but caches can grow." if not disk_ok else "",
    })

    # PDF export goes through the browser's Save-as-PDF dialog — no server-
    # side dependency to check. The old WeasyPrint health check lived here.

    overall = all(c["ok"] for c in checks if not c.get("optional"))
    return jsonify({
        "ok":     overall,
        "checks": checks,
        "system": {
            "python":   platform.python_version(),
            "platform": platform.platform(),
            "gui":      GUI_VERSION,
        },
    })


@app.route("/api/install_missing", methods=["POST"])
def install_missing():
    """Install missing dependencies into the *currently running* Python.

    This is a guardrailed convenience for the Setup tab. We:
      1. Re-run the dependency probe (same logic as ``/api/health/detailed``).
      2. Pip-install only the packages that import-fail.
      3. Use ``sys.executable -m pip`` so it always lands in the right env
         (the one the GUI is running from) — sidesteps the "wrong venv"
         footgun the user flagged.
      4. Stream stdout/stderr back to the caller as a JSON blob.

    The ``include_optional`` flag is preserved for forward-compat but
    currently has no optional packages to install (the previous WeasyPrint
    dependency has been replaced by the browser-print PDF route).
    """
    import importlib
    import subprocess
    import sys

    body = request.get_json(silent=True) or {}
    _ = bool(body.get("include_optional"))  # reserved for future optional deps

    required = [
        ("langchain_core", "langchain-core"),
        ("langgraph",      "langgraph"),
        ("yfinance",       "yfinance"),
        ("flask",          "flask"),
        ("dotenv",         "python-dotenv"),
        ("markdown",       "markdown"),
        ("jinja2",         "jinja2"),
    ]

    to_install: list[str] = []
    for module, pkg in required:
        try:
            importlib.import_module(module)
        except ImportError:
            to_install.append(pkg)

    if not to_install:
        return jsonify({
            "ok":      True,
            "skipped": True,
            "message": "All required dependencies are already installed.",
            "output":  "",
        })

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *to_install]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        return jsonify({
            "ok": False, "output": "pip install timed out after 10 minutes.",
            "installed": to_install,
        }), 500
    except Exception as e:
        return jsonify({
            "ok": False, "output": f"{type(e).__name__}: {e}",
            "installed": to_install,
        }), 500

    return jsonify({
        "ok":        ok,
        "installed": to_install,
        "cmd":       " ".join(cmd),
        "output":    output[-4000:],  # last 4KB is enough for the toast
    })


@app.route("/api/analysts")
def list_analysts():
    """Surface the analyst catalog so the form can drive itself from data."""
    return jsonify([
        {"key": k, **{kk: vv for kk, vv in meta.items()}}
        for k, meta in ANALYSTS.items()
    ])


@app.route("/api/teams")
def list_teams():
    return jsonify(FIXED_TEAMS)


@app.route("/api/section_titles")
def section_titles():
    return jsonify(SECTION_TITLES)


# ---------------------------------------------------------------------------
# Env / API keys
# ---------------------------------------------------------------------------

@app.route("/api/env", methods=["GET"])
def env_get():
    """Return env vars.

    Two response shapes for compatibility:
      * Legacy: flat {KEY: masked_value} — what the original MyFork frontend
        expects. Empty string when unset.
      * Structured (under ``values``): {KEY: {set, value, is_secret}} — the
        richer shape the redesigned tabs in Phase 4+ will consume.

    A `?structured=1` query param returns only the structured form.
    """
    structured = env_store.display(env_keys_for_ui())
    if request.args.get("structured"):
        return jsonify({"values": structured})
    # Legacy-flat: masked value (or "" if unset) at the top level.
    flat = {k: meta["value"] if meta["set"] else "" for k, meta in structured.items()}
    flat["values"] = structured  # also surface the new shape for new code
    return jsonify(flat)


@app.route("/api/env", methods=["POST"])
def env_save():
    data = request.get_json(silent=True) or {}
    # Backward-compat: the existing frontend sends a flat {KEY: value} dict.
    # If a value is missing it means "leave it alone" (KEEP_SENTINEL); if
    # explicitly empty string it means "clear it".
    updates = {}
    for k, v in data.items():
        # Frontend now sends KEEP_SENTINEL for untouched fields; the legacy
        # code sometimes simply omits them — either way is supported.
        if v == KEEP_SENTINEL:
            continue
        updates[k] = v
    result = env_store.update(updates)
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Providers + models
# ---------------------------------------------------------------------------

@app.route("/api/providers")
def providers_get():
    """Provider catalog. Augments each entry with `has_api_key` from the live env."""
    env_values = env_store.all()
    out = []
    for p in provider_list():
        env_var = p.get("api_key_env")
        out.append({**p, "has_api_key": bool(env_var and env_values.get(env_var))})
    return jsonify(out)


@app.route("/api/models")
def models_get():
    """Return the model list for a provider + mode.

    For static-catalog providers, pulls from upstream's MODEL_OPTIONS.
    For OpenRouter and Ollama, fetches live so users see only what's actually
    available against their account / local install.
    """
    provider = (request.args.get("provider") or "openai").lower()
    mode     = (request.args.get("mode")     or "quick").lower()

    if provider == "openrouter":
        return jsonify(_fetch_openrouter_models())
    if provider == "ollama":
        return jsonify(_fetch_ollama_models())

    options = MODEL_OPTIONS.get(provider, {}).get(mode, [])
    out = []
    for label, val in options:
        if val == "custom":
            out.append({"label": label, "value": "__custom__", "is_custom": True})
        else:
            out.append({"label": label, "value": val})
    return jsonify(out)


def _fetch_openrouter_models() -> list[dict]:
    """Grouped list of all OpenRouter models, with pricing surfaced in labels."""
    try:
        import requests
        key = env_store.get("OPENROUTER_API_KEY")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        res = requests.get("https://openrouter.ai/api/v1/models",
                           headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json().get("data", []) or []
    except Exception:
        logger.exception("openrouter model fetch failed")
        return []
    groups: dict[str, list[dict]] = {}
    for m in data:
        mid = m.get("id")
        if not mid:
            continue
        group = mid.split("/", 1)[0].capitalize() if "/" in mid else "Other"
        name  = m.get("name") or mid
        pricing = m.get("pricing") or {}
        p_in  = float(pricing.get("prompt") or 0) * 1_000_000
        p_out = float(pricing.get("completion") or 0) * 1_000_000
        suffix = (f" — ${p_in:.2f}/${p_out:.2f}/1M" if p_in or p_out else " — free")
        groups.setdefault(group, []).append({"label": f"{name}{suffix}", "value": mid})
    return [
        {"label": g, "options": sorted(groups[g], key=lambda x: x["label"])}
        for g in sorted(groups)
    ]


def _fetch_ollama_models() -> list[dict]:
    try:
        import requests
        base = (env_store.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        res = requests.get(f"{base}/api/tags", timeout=5)
        res.raise_for_status()
        tags = res.json().get("models", []) or []
    except Exception:
        return []
    return [{"label": m["name"], "value": m["name"]} for m in tags if m.get("name")]


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------

@app.route("/api/test_key", methods=["POST"])
def test_key():
    """Validate a provider key via the recipe in providers.TEST_RECIPES.

    Replaces the old 8-branch if/elif tower; new providers added to the
    framework get a single recipe entry and Just Work here.
    """
    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "").lower()
    api_key  = (body.get("api_key")  or "").strip()
    if not provider or not api_key:
        return jsonify({"ok": False, "error": "Provider and API key required"}), 400

    recipe = TEST_RECIPES.get(provider)
    if recipe is None:
        return jsonify({"ok": True,
                        "message": "Key saved (no automated test for this provider)."})

    import requests
    headers = {h: v.format(key=api_key) for h, v in (recipe.get("header") or {}).items()}
    params  = {recipe["query_key"]: api_key} if recipe.get("query_key") else None
    body_   = recipe.get("body")
    try:
        if body_:
            res = requests.post(recipe["url"], headers=headers, params=params,
                                json=body_, timeout=10)
        else:
            res = requests.get(recipe["url"], headers=headers, params=params, timeout=10)
        if res.status_code in (200, 201, 202):
            return jsonify({"ok": True})
        # Try to pull a useful error message.
        try:
            detail = (res.json().get("error") or {}).get("message") or res.text[:200]
        except Exception:
            detail = res.text[:200] or f"HTTP {res.status_code}"
        return jsonify({"ok": False, "error": str(detail)[:240]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:240]})


# ---------------------------------------------------------------------------
# Cost estimate
# ---------------------------------------------------------------------------

@app.route("/api/estimate", methods=["POST"])
def estimate():
    body = request.get_json(silent=True) or {}
    out = estimate_run_cost(
        analysts       = body.get("analysts") or [],
        quick_model    = body.get("quick_model") or "",
        deep_model     = body.get("deep_model")  or "",
        debate_rounds  = int(body.get("debate_rounds") or 1),
        risk_rounds    = int(body.get("risk_rounds")   or 1),
    )
    return jsonify(out)


@app.route("/api/pricing")
def pricing_table():
    return jsonify(MODEL_PRICING)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@app.route("/api/analyze", methods=["POST"])
def runs_start():
    if runs.is_anything_running():
        return jsonify({"error": "Analysis already running"}), 409
    params = request.get_json(silent=True) or {}
    ticker = (params.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "Ticker symbol is required"}), 400
    params["ticker"] = ticker
    run = runs.start(params)
    return jsonify({"ok": True, "run_id": run.id,
                    "message": f"Analysis started for {ticker} on {run.date}"})


@app.route("/api/stop", methods=["POST"])
def runs_stop():
    body = request.get_json(silent=True) or {}
    stopped = runs.stop(body.get("run_id"))
    return jsonify({"ok": stopped})


@app.route("/api/status")
def runs_status():
    """Backward-compat: was just `{running: bool}`. Now also surfaces the active run id."""
    current = runs.get(None)
    return jsonify({
        "running": bool(current and current.status == "running"),
        "run_id":  current.id if current else None,
        "status":  current.status if current else None,
    })


@app.route("/api/runs")
def runs_list():
    return jsonify({"runs": [r.snapshot() for r in runs.list()]})


@app.route("/api/runs/<run_id>")
def runs_get(run_id: str):
    run = runs.get(run_id)
    if not run:
        return jsonify({"error": "not found"}), 404
    return jsonify(run.snapshot())


@app.route("/api/stream")
def stream_events():
    """SSE — drains the current (or specified) run's event queue."""
    run_id = request.args.get("run_id")
    run = runs.get(run_id)

    @stream_with_context
    def event_stream():
        # If we don't have a run yet, surface a hint and keep the connection open.
        if not run:
            yield "data: " + json.dumps({"type": "ping", "message": "no active run"}) + "\n\n"
            return
        # Snapshot first so a client joining mid-run picks up the current state.
        yield "data: " + json.dumps({"type": "snapshot", "snapshot": run.snapshot()}) + "\n\n"
        while True:
            try:
                item = run.queue.get(timeout=20)
            except Exception:
                # Empty: keep-alive
                yield "data: {\"type\": \"ping\"}\n\n"
                continue
            yield "data: " + json.dumps(item, default=str) + "\n\n"
            if item.get("type") == "done":
                break

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/stats")
def stats_get():
    current = runs.get(None)
    return jsonify(current.stats if current else
                   {"llm_calls": 0, "tool_calls": 0, "tokens_in": 0,
                    "tokens_out": 0, "cost_usd": 0.0, "elapsed_s": 0.0})


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _results_base() -> Path:
    """Honor TRADINGAGENTS_RESULTS_DIR if set, else the home-dir default."""
    custom = os.environ.get("TRADINGAGENTS_RESULTS_DIR")
    if custom:
        return Path(custom)
    return Path.home() / ".tradingagents" / "logs"


@app.route("/api/history")
def history_get():
    mem = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
    if mem.exists():
        return jsonify({"content": mem.read_text(encoding="utf-8")})
    return jsonify({"content": ""})


@app.route("/api/reports")
def reports_list():
    base = _results_base()
    if not base.exists():
        return jsonify({"reports": []})
    out = []
    for ticker_dir in sorted(base.iterdir(), reverse=True):
        if not ticker_dir.is_dir():
            continue
        for date_dir in sorted(ticker_dir.iterdir(), reverse=True):
            report = date_dir / "reports" / "complete_report.md"
            if not report.exists():
                continue
            meta_path = date_dir / "reports" / "run.json"
            meta = {}
            if meta_path.exists():
                try: meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception: meta = {}
            out.append({
                "ticker":   ticker_dir.name,
                "date":     date_dir.name,
                "path":     str(report.relative_to(base)).replace("\\", "/"),
                "decision": meta.get("decision"),
                "saved_at": meta.get("saved_at") or report.stat().st_mtime,
                "size":     report.stat().st_size,
            })
    out.sort(key=lambda r: r["saved_at"], reverse=True)
    return jsonify({"reports": out[:100]})


@app.route("/api/reports/read")
def reports_read():
    path = request.args.get("path", "")
    resolved = _safe_report_path(path)
    if not resolved:
        return jsonify({"error": "Invalid path"}), 400
    return jsonify({"content": resolved.read_text(encoding="utf-8")})


@app.route("/api/reports/download")
def reports_download():
    path = request.args.get("path", "")
    resolved = _safe_report_path(path)
    if not resolved:
        return jsonify({"error": "Invalid path"}), 400
    return send_file(str(resolved), as_attachment=True, mimetype="text/markdown")


@app.route("/api/reports/delete", methods=["POST"])
def reports_delete():
    """Delete a saved report and its sibling per-section files.

    Removes the entire ``<ticker>/<date>/`` directory under the results dir,
    so all of ``complete_report.md``, ``run.json``, and the per-section
    files (``1_analysts/market.md``, etc.) go in one shot. The framework's
    persistent memory log is unaffected.
    """
    import shutil
    path = request.args.get("path", "")
    resolved = _safe_report_path(path)
    if not resolved:
        return jsonify({"error": "Invalid path"}), 400
    # ``resolved`` points at the complete_report.md; the date directory is
    # its grandparent (reports/complete_report.md -> reports -> <date>).
    date_dir = resolved.parent.parent
    base = _results_base().resolve()
    if not str(date_dir.resolve()).startswith(str(base)):
        return jsonify({"error": "Refusing to delete outside results dir"}), 403
    try:
        shutil.rmtree(date_dir)
    except Exception as e:
        return jsonify({"error": f"delete failed: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/api/reports/export")
def reports_export():
    """Export a report as .md / .html / .pdf."""
    fmt  = (request.args.get("fmt") or "md").lower()
    path = request.args.get("path", "")
    resolved = _safe_report_path(path)
    if not resolved:
        return jsonify({"error": "Invalid path"}), 400
    md = resolved.read_text(encoding="utf-8")
    if fmt == "md":
        return send_file(str(resolved), as_attachment=True, mimetype="text/markdown")
    if fmt == "html":
        # ``?print=1`` returns a print-friendly HTML view that auto-opens the
        # browser's Save-as-PDF dialog — the zero-install path to a PDF.
        print_mode = request.args.get("print") in ("1", "true", "yes")
        body = _render_html(md, resolved.stem, print_mode=print_mode)
        if print_mode:
            # Render inline so the page can auto-trigger window.print().
            return Response(body, mimetype="text/html")
        return Response(body, mimetype="text/html",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{resolved.stem}.html"'})
    if fmt == "pdf":
        # PDF export goes through the browser's Save-as-PDF dialog. We serve
        # the print-friendly HTML view inline; a small auto-print script in
        # ``_render_html(..., print_mode=True)`` opens the dialog on load.
        # This replaces the old WeasyPrint code path which broke on Windows
        # whenever GTK / Pango / Cairo native libs weren't installed.
        body = _render_html(md, resolved.stem, print_mode=True)
        return Response(body, mimetype="text/html")
    return jsonify({"error": "Unknown format"}), 400


def _safe_report_path(rel: str) -> Path | None:
    """Resolve a relative report path safely under the results dir."""
    base = _results_base()
    try:
        resolved = (base / rel).resolve()
        if not str(resolved).startswith(str(base.resolve())):
            return None
        if not resolved.exists() or resolved.suffix != ".md":
            return None
        return resolved
    except Exception:
        return None


_HTML_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
          max-width: 780px; margin: 2rem auto; padding: 0 1.2rem;
          color: #1d2330; line-height: 1.55; }}
  h1, h2, h3 {{ color: #0b1830; page-break-after: avoid; }}
  h1 {{ font-size: 1.7rem; border-bottom: 2px solid #0b1830; padding-bottom: .3rem; }}
  h2 {{ font-size: 1.3rem; margin-top: 1.6rem; }}
  pre, code {{ background: #f4f6fb; padding: .15em .35em; border-radius: 4px;
               font-family: 'Cascadia Code', 'Consolas', monospace; font-size: .9em; }}
  pre {{ padding: .8rem; overflow: auto; page-break-inside: avoid; }}
  blockquote {{ border-left: 3px solid #4e8cff; padding-left: .8rem; color: #445; }}
  table {{ border-collapse: collapse; width: 100%; margin: .7rem 0;
           page-break-inside: avoid; }}
  td, th {{ border: 1px solid #d4d9e3; padding: .35rem .6rem; }}
  th {{ background: #f4f6fb; text-align: left; }}
  /* Print-specific rules — keep the page tidy when saved as PDF */
  @media print {{
    body {{ margin: 0; max-width: none; padding: 0 .4in; font-size: 11pt; }}
    h1, h2, h3 {{ page-break-after: avoid; }}
    table, pre, blockquote {{ page-break-inside: avoid; }}
    .no-print {{ display: none !important; }}
  }}
  .print-banner {{
    background: #4e8cff; color: white; padding: .6rem 1rem; border-radius: 6px;
    margin-bottom: 1.2rem; font-size: .9rem;
  }}
  .print-banner button {{
    background: white; color: #0b1830; border: 0; padding: .3rem .7rem;
    border-radius: 4px; font-weight: 600; cursor: pointer; margin-left: .5rem;
  }}
</style>
</head><body>{banner}{body}{script}</body></html>"""

_PRINT_BANNER = """
<div class="print-banner no-print">
  Use your browser's print dialog to save this report as a PDF.
  <button onclick="window.print()">Print / Save as PDF</button>
</div>
"""

_AUTO_PRINT_SCRIPT = """
<script>
  // Wait a tick so layout settles before the dialog opens.
  window.addEventListener("load", () => setTimeout(() => window.print(), 250));
</script>
"""


def _render_html(md: str, title: str, *, print_mode: bool = False) -> str:
    try:
        import markdown as md_lib  # type: ignore
        body = md_lib.markdown(md, extensions=["fenced_code", "tables"])
    except ImportError:
        body = f"<pre>{md}</pre>"
    banner = _PRINT_BANNER if print_mode else ""
    script = _AUTO_PRINT_SCRIPT if print_mode else ""
    return _HTML_TEMPLATE.format(title=title, body=body, banner=banner, script=script)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.route("/api/chat/sessions", methods=["GET"])
def chat_list_sessions():
    return jsonify({"sessions": ChatSession.list_summaries()})


@app.route("/api/chat/sessions", methods=["POST"])
def chat_create_session():
    body = request.get_json(silent=True) or {}
    s = ChatSession(
        name      = body.get("name") or "New chat",
        provider  = body.get("provider") or "openai",
        model     = body.get("model")    or "gpt-5.4-mini",
        attached_reports = body.get("attached") or [],
    )
    s.save()
    return jsonify({"ok": True, "session": s.to_dict()})


@app.route("/api/chat/sessions/<sid>", methods=["GET"])
def chat_get_session(sid: str):
    s = ChatSession.load(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    return jsonify({"session": s.to_dict(),
                    "tokens": s.token_estimate(_results_base())})


@app.route("/api/chat/sessions/<sid>", methods=["PATCH"])
def chat_update_session(sid: str):
    s = ChatSession.load(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    # Whitelisted patchable fields. Note: messages are append-only via the
    # /messages POST route — not patchable here.
    for field in ("name", "provider", "model", "system_prompt"):
        if field in body:
            setattr(s, field, body[field])
    if "attached" in body:
        s.attached = list(body["attached"] or [])
    s.save()
    return jsonify({"ok": True, "session": s.to_dict()})


@app.route("/api/chat/sessions/<sid>", methods=["DELETE"])
def chat_delete_session(sid: str):
    s = ChatSession.load(sid)
    if s:
        s.delete()
    return jsonify({"ok": True})


@app.route("/api/chat/sessions/<sid>/pin", methods=["POST"])
def chat_pin_report(sid: str):
    s = ChatSession.load(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    s.pin_report(body.get("ticker", ""), body.get("date", ""))
    return jsonify({"ok": True, "attached": s.attached,
                    "tokens": s.token_estimate(_results_base())})


@app.route("/api/chat/sessions/<sid>/unpin", methods=["POST"])
def chat_unpin_report(sid: str):
    s = ChatSession.load(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    s.unpin_report(body.get("ticker", ""), body.get("date", ""))
    return jsonify({"ok": True, "attached": s.attached,
                    "tokens": s.token_estimate(_results_base())})


@app.route("/api/chat/sessions/<sid>/system_preview", methods=["GET"])
def chat_system_preview(sid: str):
    """Return the exact system message the LLM will receive for this session.

    Diagnostic — lets the user verify a pinned report is actually being
    surfaced into the prompt and isn't silently truncated, missing on
    disk, or otherwise broken before they ask the model about it.
    """
    s = ChatSession.load(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    base = _results_base()
    text = s.assembled_system_prompt(base)
    # Per-report status so the UI can flag missing files prominently.
    pin_info = []
    for ref in s.attached:
        ticker = ref.get("ticker", "")
        date   = ref.get("date",   "")
        path   = base / ticker / date / "reports" / "complete_report.md"
        if path.exists():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            pin_info.append({"ticker": ticker, "date": date,
                             "found": True, "bytes": size,
                             "path": str(path)})
        else:
            pin_info.append({"ticker": ticker, "date": date,
                             "found": False, "bytes": 0,
                             "path": str(path)})
    return jsonify({
        "system":     text,
        "char_count": len(text),
        "pins":       pin_info,
        "tokens":     s.token_estimate(base),
    })


@app.route("/api/chat/sessions/<sid>/messages", methods=["POST"])
def chat_send(sid: str):
    """Send a user message, stream the assistant reply as SSE."""
    s = ChatSession.load(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Empty message"}), 400
    # Optional one-off model override.
    if body.get("model"):
        s.model = body["model"]
    if body.get("provider"):
        s.provider = body["provider"]

    @stream_with_context
    def event_stream():
        for event in stream_reply(s, _results_base(), content):
            yield "data: " + json.dumps(event, default=str) + "\n\n"

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/chat/tokens", methods=["POST"])
def chat_token_estimate():
    """Cheap helper: count tokens in arbitrary text for the typing-indicator UI."""
    body = request.get_json(silent=True) or {}
    return jsonify({"tokens": count_tokens(body.get("text") or "",
                                           body.get("model") or "")})


def _chat_providers_with_keys() -> list[dict]:
    """Providers the user has an API key for (or that need none, like Ollama)."""
    env_values = env_store.all()
    out = []
    for p in provider_list():
        env_var = p.get("api_key_env")
        has_key = bool(env_var and env_values.get(env_var)) or not env_var
        if not has_key:
            continue
        # Live-fetch providers expose dynamic catalogs; static use MODEL_OPTIONS.
        live = p["key"] in ("openrouter", "ollama")
        out.append({"provider": p["key"], "label": p["label"], "live": live})
    return out


def _chat_models_for_provider(provider: str) -> list[dict]:
    """Flat model list for a single provider. Uses live fetch for OpenRouter
    and Ollama; falls back to MODEL_OPTIONS otherwise."""
    provider = (provider or "").lower()
    if provider == "openrouter":
        # _fetch_openrouter_models returns [{label, options:[{label,value}]}]
        flat = []
        seen = set()
        for grp in _fetch_openrouter_models():
            for m in grp.get("options", []):
                v = m.get("value")
                if not v or v in seen:
                    continue
                seen.add(v)
                flat.append({"label": f"{grp['label']} · {m['label']}",
                             "value": v, "context": context_window(v)})
        return flat
    if provider == "ollama":
        return [{"label": m["label"], "value": m["value"],
                 "context": context_window(m["value"])}
                for m in _fetch_ollama_models()]
    modes = MODEL_OPTIONS.get(provider, {})
    seen = set()
    models = []
    for opts in (modes.get("quick") or []) + (modes.get("deep") or []):
        label, val = opts
        if val in seen or val == "custom":
            continue
        seen.add(val)
        models.append({"label": label, "value": val,
                       "context": context_window(val)})
    return models


@app.route("/api/chat/models", methods=["GET"])
def chat_models():
    """Chat model picker data.

    - No params: returns the list of providers the user has keys for, each
      tagged ``live`` if the catalog is fetched dynamically.
    - ``?provider=X``: returns the flat model list for that provider, using
      live fetches for OpenRouter/Ollama so newly-added models appear without
      restart.
    - Legacy clients (no ``provider``, expecting grouped {provider, models}):
      pass ``?grouped=1`` to get the old shape.
    """
    provider = request.args.get("provider")
    if provider:
        return jsonify(_chat_models_for_provider(provider))
    if request.args.get("grouped") == "1":
        # Backwards-compat shape: [{provider, label, models:[...]}]
        out = []
        for p in _chat_providers_with_keys():
            out.append({"provider": p["provider"], "label": p["label"],
                        "models": _chat_models_for_provider(p["provider"])})
        return jsonify(out)
    return jsonify(_chat_providers_with_keys())


# ---------------------------------------------------------------------------
# Analyze-form presets
# ---------------------------------------------------------------------------

@app.route("/api/presets", methods=["GET"])
def presets_list():
    """List saved analyze-form presets. Returns metadata only — call
    ``/api/presets/<id>`` to fetch values for a specific preset."""
    return jsonify(presets.list())


@app.route("/api/presets", methods=["POST"])
def presets_create():
    """Create or update a preset by name (overwrites if same name exists).

    Body: ``{"name": "...", "values": { ...form snapshot... }}``
    """
    body = request.get_json(silent=True) or {}
    name   = (body.get("name") or "").strip()
    values = body.get("values") or {}
    if not name:
        return jsonify({"ok": False, "error": "Preset name required"}), 400
    if not isinstance(values, dict):
        return jsonify({"ok": False, "error": "values must be an object"}), 400
    data = presets.create(name, values)
    return jsonify({"ok": True, "preset": data})


@app.route("/api/presets/<pid>", methods=["GET"])
def presets_get(pid):
    data = presets.get(pid)
    if not data:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, "preset": data})


@app.route("/api/presets/<pid>", methods=["PATCH"])
def presets_update(pid):
    body = request.get_json(silent=True) or {}
    data = presets.update(pid, name=body.get("name"), values=body.get("values"))
    if not data:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, "preset": data})


@app.route("/api/presets/<pid>", methods=["DELETE"])
def presets_delete(pid):
    ok = presets.delete(pid)
    return jsonify({"ok": ok})


# ---------------------------------------------------------------------------
# Sticky Configuration-tab state (server-side, survives restarts/browsers)
# ---------------------------------------------------------------------------

@app.route("/api/ui_state", methods=["GET"])
def ui_state_get():
    """Return the saved Configuration-tab blob (provider, models, vendors…)."""
    return jsonify(ui_state.get())


@app.route("/api/ui_state", methods=["POST"])
def ui_state_set():
    """Merge an updates blob into the saved Configuration-tab state.

    The shape is opaque — the front-end snapshots whatever it wants to
    persist (typically: ``provider``, ``quick_model``, ``deep_model``,
    ``custom_backend_url``, ``reasoning_effort``, ``vendors``).
    """
    body = request.get_json(silent=True) or {}
    saved = ui_state.merge(body)
    return jsonify({"ok": True, "state": saved})


# ---------------------------------------------------------------------------
# Entry point — `tradingagents-gui` console script + `python -m gui`
# ---------------------------------------------------------------------------

def main() -> None:
    """Console script entry point. Uses Flask's built-in server for simplicity."""
    import argparse
    parser = argparse.ArgumentParser(prog="tradingagents-gui",
                                     description="Launch the local TradingAgents GUI.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default 127.0.0.1; use 0.0.0.0 for LAN).")
    parser.add_argument("--port", default=5000, type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"

    if not args.no_browser:
        import threading, webbrowser
        threading.Thread(
            target=lambda: (time.sleep(1.0), webbrowser.open(url)),
            daemon=True,
        ).start()

    # Encourage UTF-8 stdout on cp1252-locked Windows consoles.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    print("=" * 60)
    print(f"  TradingAgents GUI {GUI_VERSION}")
    print(f"  Open in your browser:  {url}")
    print("  Press Ctrl-C to stop.")
    print("=" * 60)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
