/* ============================================================
   app_v2.js — Phase 4 frontend additions on top of app.js.
   Loaded AFTER app.js, so we can override specific globals.

   Responsibilities:
     * Drive the new segmented controls (depth + report length)
     * Cost estimate widget (header + run-button preview)
     * v2 pipeline stage classes + progress bar
     * v2 stats bar (cells)
     * Output-tab switching (Feed / Reports / Tool calls)
     * Tool-calls pane population
     * Final-decision card rendering
     * Sidebar version badge already updated server-side; nothing to do here.
   ============================================================ */

(() => {
  // ---- Server-mirrored UI preferences ----------------------------------
  // Keys we sync between localStorage and the server's ``ui_state.json``.
  // localStorage gives us instant paint on page load; the server is the
  // source of truth so values survive incognito tabs and other browsers.
  const _UI_MIRROR_KEYS = [
    "ta_theme",
    "ta_form_state",
    "reports_toc_collapsed",
    "chat_sessions_collapsed",
    "wizard_seen",
  ];

  /** Pull every mirrored key from the server and push into localStorage.
      Called synchronously at the very top of init so existing
      ``localStorage.getItem(...)`` call sites just work in incognito. */
  async function _bootstrapMirroredPrefs() {
    let serverState = {};
    try {
      const r = await fetch("/api/ui_state");
      serverState = (await r.json()) || {};
    } catch { return; }
    for (const k of _UI_MIRROR_KEYS) {
      const v = serverState[k];
      if (v === undefined || v === null) continue;
      try {
        // The server stores strings already (we POSTed them as strings),
        // so just write through. If it ever stores a non-string we'll
        // JSON-encode defensively.
        const out = typeof v === "string" ? v : JSON.stringify(v);
        localStorage.setItem(k, out);
      } catch { /* localStorage may be full or blocked — ignore */ }
    }
  }

  /** Write-through helper: writes to localStorage AND debounced-POSTs to
      ``/api/ui_state`` so the value survives both a server restart and
      switching to an incognito window. */
  const _mirrorDebounce = {};
  window.uiPrefSet = function(key, value) {
    try { localStorage.setItem(key, value); } catch {}
    clearTimeout(_mirrorDebounce[key]);
    _mirrorDebounce[key] = setTimeout(() => {
      const payload = { [key]: value };
      fetch("/api/ui_state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    }, 300);
  };

  // Kick off the bootstrap before init runs. Existing localStorage reads
  // throughout app.js / app_v2.js will see the server-loaded values.
  const _bootstrapPromise = _bootstrapMirroredPrefs();

  // ---- Stage mapping ----------------------------------------------------
  // Which agent display names belong to which pipeline stage. Keep in sync
  // with the HTML data-stage attributes on the .stage elements.
  const STAGE_AGENTS = {
    analysts:  ["Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst"],
    research:  ["Bull Researcher", "Bear Researcher", "Research Manager"],
    trader:    ["Trader"],
    risk:      ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
    portfolio: ["Portfolio Manager"],
  };

  // Final-decision text → mood (drives the decision card color & icon).
  function decisionMood(text) {
    const t = (text || "").toUpperCase();
    if (t.includes("BUY"))  return { color: "ok",   icon: "▲", label: "BUY" };
    if (t.includes("SELL")) return { color: "err",  icon: "▼", label: "SELL" };
    if (t.includes("HOLD")) return { color: "warn", icon: "▶", label: "HOLD" };
    return { color: "accent", icon: "★", label: "" };
  }

  // ---- Segmented controls ----------------------------------------------
  function initSegControls() {
    document.querySelectorAll(".seg-control").forEach(group => {
      const targetId = group.dataset.target;
      const target   = targetId ? document.getElementById(targetId) : null;
      group.querySelectorAll(".seg-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          group.querySelectorAll(".seg-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          if (target) {
            target.value = btn.dataset.value;
            target.dispatchEvent(new Event("change", { bubbles: true }));
          }
          // Refresh estimate when depth or brevity changes.
          refreshCostEstimate();
        });
      });
    });
  }

  // ---- Output-tab switching --------------------------------------------
  function initOutputTabs() {
    const tabs  = document.querySelectorAll(".output-tab");
    const panes = document.querySelectorAll(".output-pane");
    tabs.forEach(t => {
      t.addEventListener("click", () => {
        tabs.forEach(x => x.classList.remove("active"));
        panes.forEach(p => p.classList.remove("active"));
        t.classList.add("active");
        const which = t.dataset.otab;
        document.querySelector(`.output-pane[data-opane="${which}"]`)
          ?.classList.add("active");
      });
    });
  }

  // ---- Cost estimate ----------------------------------------------------
  let estimateDebounce;
  async function refreshCostEstimate() {
    clearTimeout(estimateDebounce);
    estimateDebounce = setTimeout(async () => {
      try {
        // Pull current form values
        const analysts = Array.from(
          document.querySelectorAll(".analyst-card-v2.checked input[type=checkbox]")
        ).map(c => c.value);
        const depth   = parseInt(document.getElementById("depth-input")?.value || "1");
        const quick   = document.getElementById("quick-model-select")?.value || "";
        const deep    = document.getElementById("deep-model-select")?.value || "";
        if (!analysts.length || !quick || !deep) {
          updateCostBadges("—", "—");
          return;
        }
        const res = await fetch("/api/estimate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            analysts,
            quick_model: quick,
            deep_model: deep,
            debate_rounds: depth,
            risk_rounds: depth,
          }),
        });
        const data = await res.json();
        const cost = `$${(data.cost_usd || 0).toFixed(3)}`;
        const note = data.pricing_known ? cost : `${cost}*`;
        updateCostBadges(note, note);
        // Tooltip when pricing is unknown
        const badge = document.getElementById("header-est-cost");
        if (badge) {
          badge.title = data.pricing_known
            ? `Estimated ${data.tokens_in.toLocaleString()} input / ${data.tokens_out.toLocaleString()} output tokens.`
            : "* Pricing not published for the selected model — actual cost may vary.";
        }
      } catch (e) {
        updateCostBadges("—", "—");
      }
    }, 250);
  }
  function updateCostBadges(headerVal, runVal) {
    const h = document.getElementById("header-est-cost");
    const r = document.getElementById("run-cost-value");
    if (h) h.textContent = headerVal;
    if (r) r.textContent = runVal;
  }

  // ---- Pipeline stage state machine ------------------------------------
  function recomputeStages() {
    let totalAgents = 0, completedAgents = 0;
    for (const [stage, agents] of Object.entries(STAGE_AGENTS)) {
      const stageEl = document.querySelector(`.stage[data-stage="${stage}"]`);
      if (!stageEl) continue;
      let stageTotal = 0, stageDone = 0, stageInProg = 0;
      for (const display of agents) {
        const id = `agent-${display.replace(/\s+/g, "-")}`;
        const el = document.getElementById(id);
        if (!el) continue;
        stageTotal++;
        totalAgents++;
        if (el.classList.contains("completed"))    { stageDone++; completedAgents++; }
        else if (el.classList.contains("in_progress")) { stageInProg++; }
      }
      stageEl.classList.remove("in-progress", "complete");
      if (stageTotal && stageDone === stageTotal) {
        stageEl.classList.add("complete");
      } else if (stageInProg > 0 || stageDone > 0) {
        stageEl.classList.add("in-progress");
      }
      const fill = stageEl.querySelector(".stage-bar-fill");
      if (fill) {
        const pct = stageTotal ? Math.round((stageDone / stageTotal) * 100) : 0;
        fill.style.width = `${pct}%`;
      }
    }
    // Overall progress bar
    const pct = totalAgents ? Math.round((completedAgents / totalAgents) * 100) : 0;
    const fill = document.getElementById("progress-fill");
    const lbl  = document.getElementById("progress-pct");
    if (fill) fill.style.width = `${pct}%`;
    if (lbl)  lbl.textContent  = `${pct}%`;
    // Status text
    const statusEl = document.getElementById("pipeline-status");
    if (statusEl) {
      if (completedAgents === totalAgents && totalAgents > 0) {
        statusEl.textContent = `Complete — ${completedAgents}/${totalAgents} agents finished.`;
      } else if (completedAgents > 0) {
        statusEl.textContent = `In progress — ${completedAgents}/${totalAgents} agents done.`;
      } else {
        statusEl.textContent = totalAgents
          ? "Run starting…"
          : "Waiting for run.";
      }
    }
    // Stat cell: agents
    const sa = document.getElementById("stat-agents");
    if (sa) sa.textContent = `${completedAgents}/${totalAgents}`;
  }

  // ---- Override the old per-event updater so it also drives the new UI -
  // The original updateAgentsUI sets `agent-chip` classes; the new stage
  // agents have `.stage-agent` instead. We update both class lists so the
  // legacy chips (if any remain) AND the new stage rows stay in sync.
  const origUpdateAgents = window.updateAgentsUI;
  window.updateAgentsUI = function(agentsDict) {
    if (typeof origUpdateAgents === "function") {
      try { origUpdateAgents(agentsDict); } catch (e) {}
    }
    for (const [name, status] of Object.entries(agentsDict)) {
      const id = `agent-${name.replace(/\s+/g, "-")}`;
      const el = document.getElementById(id);
      if (!el) continue;
      el.classList.remove("pending", "in_progress", "completed", "error");
      el.classList.add(status);
    }
    recomputeStages();
  };

  // ---- v2 stats bar (cells) --------------------------------------------
  const origUpdateStats = window.updateStats;
  window.updateStats = function(stats) {
    if (typeof origUpdateStats === "function") {
      try { origUpdateStats(stats); } catch (e) {}
    }
    if (!stats) return;
    const fmtTok = n => {
      n = n || 0;
      if (n >= 1_000_000) return (n/1_000_000).toFixed(2) + "M";
      if (n >= 1000)      return (n/1000).toFixed(1)  + "k";
      return String(n);
    };
    const tin   = fmtTok(stats.tokens_in  ?? window.analysisStats?.tokens_in  ?? 0);
    const tout  = fmtTok(stats.tokens_out ?? window.analysisStats?.tokens_out ?? 0);
    const cost  = stats.cost_usd != null ? `$${stats.cost_usd.toFixed(3)}` : "$0.000";
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setText("stat-llm",    String(stats.llm_calls  ?? 0));
    setText("stat-tools",  String(stats.tool_calls ?? 0));
    setText("stat-tokens", `${tin} / ${tout}`);
    setText("stat-cost",   cost);
  };

  // ---- v2 elapsed timer (MM:SS, no glyph prefix) -----------------------
  const origUpdateTimer = window.updateTimer;
  window.updateTimer = function() {
    if (!window.startTime) return;
    const elapsed = Math.floor((Date.now() - window.startTime) / 1000);
    const m = Math.floor(elapsed / 60).toString().padStart(2, "0");
    const s = (elapsed % 60).toString().padStart(2, "0");
    const el = document.getElementById("stat-elapsed");
    if (el) el.textContent = `${m}:${s}`;
  };

  // ---- Tool-calls pane --------------------------------------------------
  const origAppendFeed = window.appendFeedEntry;
  window.appendFeedEntry = function(type, text, source = null) {
    // Still call original (writes to #message-feed using old class names).
    if (typeof origAppendFeed === "function") {
      try { origAppendFeed(type, text, source); } catch (e) {}
    }
    // Mirror tool calls into the dedicated pane.
    if (type === "tool") {
      const pane = document.getElementById("tool-calls");
      if (pane) {
        pane.querySelector(".feed-placeholder")?.remove();
        const ts = new Date().toLocaleTimeString([], { hour12: false });
        const entry = document.createElement("div");
        entry.className = "tool-call-entry";
        entry.innerHTML = `
          <div class="tc-head">
            <span class="tc-time">${ts}</span>
            <span class="tc-name">${escapeHtml(text)}</span>
          </div>
          ${source ? `<div class="tc-args">${escapeHtml(String(source))}</div>` : ""}
        `;
        pane.appendChild(entry);
        while (pane.children.length > 100) pane.removeChild(pane.firstChild);
        pane.scrollTop = pane.scrollHeight;
      }
    }
    // Update feed-meta pill in the pane head.
    const meta = document.getElementById("feed-meta");
    if (meta && type) meta.textContent = type === "done" ? "Done" : "Streaming…";
  };

  // ---- Reset the v2 UI for a new run -----------------------------------
  const origReset = window.resetUiForNewRun;
  window.resetUiForNewRun = function() {
    if (typeof origReset === "function") {
      try { origReset(); } catch (e) {}
    }
    document.querySelectorAll(".stage-agent").forEach(el => {
      el.classList.remove("in_progress", "completed", "error");
      el.classList.add("pending");
    });
    document.querySelectorAll(".stage").forEach(s => s.classList.remove("in-progress", "complete"));
    document.querySelectorAll(".stage-bar-fill").forEach(b => b.style.width = "0%");
    const pf = document.getElementById("progress-fill");
    if (pf) pf.style.width = "0%";
    const pp = document.getElementById("progress-pct");
    if (pp) pp.textContent = "0%";
    document.getElementById("decision-card").style.display = "none";
    document.getElementById("stat-cost").textContent = "$0.000";
    document.getElementById("stat-tokens").textContent = "0 / 0";
    document.getElementById("stat-elapsed").textContent = "00:00";
    // Reset tool-calls pane
    const tc = document.getElementById("tool-calls");
    if (tc) tc.innerHTML = '<div class="feed-placeholder"><p>No tool calls yet.</p></div>';
    const meta = document.getElementById("feed-meta");
    if (meta) meta.textContent = "Running…";
  };

  // ---- Final decision card ---------------------------------------------
  function renderDecisionFromState(state) {
    const text = state?.final_trade_decision;
    if (!text) return;
    const card = document.getElementById("decision-card");
    const icon = document.getElementById("decision-icon");
    const body = document.getElementById("decision-text");
    if (!card || !icon || !body) return;
    const mood = decisionMood(text);
    // Stash the original markdown for copyDecision() and any other consumer.
    body.dataset.raw = text;
    // Render markdown — older versions showed the literal '### Heading\n**Action**'
    // characters because we set textContent. Use marked when present, fall
    // back to plain text so a missing CDN isn't fatal.
    if (window.marked && typeof window.marked.parse === "function") {
      body.innerHTML = window.marked.parse(text);
    } else {
      body.textContent = text;
    }
    icon.textContent = mood.icon;
    card.style.display = "flex";
    card.style.borderColor = mood.color === "ok"
      ? "var(--ok)"  : mood.color === "err"
      ? "var(--err)" : mood.color === "warn"
      ? "var(--warn, #f59e0b)" : "var(--accent)";
  }

  // Hook the chunk handler to also render the decision card on completion.
  const origChunk = window.handleChunkData;
  window.handleChunkData = function(state) {
    if (typeof origChunk === "function") {
      try { origChunk(state); } catch (e) {}
    }
    if (state?.final_trade_decision) renderDecisionFromState(state);
  };

  // ---- Hook startAnalysis to also send brevity + capture form changes --
  // The existing startAnalysis() reads from DOM; brevity is on a hidden
  // input named #brevity-input so it shows up automatically — but the old
  // function might not include it. We monkey-patch the fetch payload.
  const origFetch = window.fetch;
  window.fetch = function(url, opts) {
    if (url === "/api/analyze" && opts && opts.body) {
      try {
        const body = JSON.parse(opts.body);
        // Inject brevity + depth from hidden inputs.
        const brev = document.getElementById("brevity-input")?.value;
        const dep  = document.getElementById("depth-input")?.value;
        if (brev && !body.report_brevity) body.report_brevity = brev;
        if (dep  && !body.research_depth)  body.research_depth = parseInt(dep);
        // Also map "social" key in analysts to whatever the v0.2.5 framework
        // expects; upstream still uses "social", so this is a no-op now.
        opts = { ...opts, body: JSON.stringify(body) };
      } catch (e) {}
    }
    return origFetch.call(this, url, opts);
  };

  // ---- Copy-decision helper exposed to inline onclick ------------------
  window.copyDecision = async function() {
    const el = document.getElementById("decision-text");
    // Prefer the stashed markdown source so the clipboard gets the
    // headings, bullets, and bold markers intact. Fall back to rendered
    // text for older runs that pre-date the markdown render.
    const t = el?.dataset?.raw || el?.textContent || "";
    if (!t) return;
    try {
      await navigator.clipboard.writeText(t);
      window.showToast?.("Decision copied", "success");
    } catch {
      window.showToast?.("Copy failed", "error");
    }
  };

  // ---- Form-state persistence (localStorage) ---------------------------
  // Snapshots the Analyze form on every change and restores it on page
  // load. Survives server restarts because everything is in the user's
  // browser. Named server-side presets (below) layer on top of this.

  const FORM_STORAGE_KEY = "ta_form_state_v1";

  /** All form fields we know how to save+restore. Each entry describes the
      element id, the kind of value, and how to read/write it. */
  function _formFields() {
    return [
      { id: "ticker-input",        kind: "value" },
      { id: "date-input",          kind: "value" },
      { id: "depth-input",         kind: "value", seg: true },
      { id: "brevity-input",       kind: "value", seg: true },
      { id: "language-select",     kind: "value" },
      { id: "checkpoint-check",    kind: "checked" },
      { id: "clear-check",         kind: "checked" },
      { id: "quick-model-select",  kind: "value", lateBind: true },
      { id: "deep-model-select",   kind: "value", lateBind: true },
      { id: "custom-quick-model",  kind: "value", lateBind: true },
      { id: "custom-deep-model",   kind: "value", lateBind: true },
      { id: "custom-backend-url",  kind: "value", lateBind: true },
      { id: "google-thinking",     kind: "value", lateBind: true },
      { id: "openai-effort",       kind: "value", lateBind: true },
      { id: "anthropic-effort",    kind: "value", lateBind: true },
    ];
  }

  /** Read the current form state into a plain JSON object. */
  function snapshotForm() {
    const out = {};
    for (const f of _formFields()) {
      const el = document.getElementById(f.id);
      if (!el) continue;
      out[f.id] = (f.kind === "checked") ? !!el.checked : (el.value || "");
    }
    // Analyst card checked-state (4 cards).
    out._analysts = Array.from(
      document.querySelectorAll(".analyst-card-v2")
    ).map(c => ({ analyst: c.dataset.analyst,
                  checked: c.classList.contains("checked") }));
    // Current provider — the legacy app.js tracks this in a module-scoped
    // variable we can't read directly, but the provider's <button> on the
    // API Keys/Configuration tab is what `currentProvider` mirrors. We
    // also snapshot what's been picked in the UI.
    try { out.currentProvider = window.currentProvider || null; } catch {}
    return out;
  }

  /** Apply a snapshot to the form. Late-bound fields (provider/model)
      may not exist yet because they're rendered after a provider is
      selected — we re-apply on a short interval until they appear or
      timeout. */
  function restoreForm(state) {
    if (!state || typeof state !== "object") return;
    // 1) Simple fields available immediately.
    for (const f of _formFields()) {
      if (f.lateBind) continue;
      const el = document.getElementById(f.id);
      if (!el || !(f.id in state)) continue;
      if (f.kind === "checked") {
        el.checked = !!state[f.id];
      } else {
        el.value = state[f.id];
        // For segmented controls, also flip the active button.
        if (f.seg) _setSegActive(f.id, state[f.id]);
      }
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // 2) Analyst cards.
    if (Array.isArray(state._analysts)) {
      for (const a of state._analysts) {
        const card = document.querySelector(
          `.analyst-card-v2[data-analyst="${a.analyst}"]`);
        if (!card) continue;
        const cb = card.querySelector("input[type=checkbox]");
        const shouldBeChecked = !!a.checked;
        if (cb && cb.checked !== shouldBeChecked) {
          cb.checked = shouldBeChecked;
          cb.dispatchEvent(new Event("change", { bubbles: true }));
        }
        card.classList.toggle("checked", shouldBeChecked);
      }
    }
    // 3) Provider + late-bind fields. Provider drives model dropdowns,
    //    so kick the provider selection first then retry late binds.
    if (state.currentProvider) {
      const btn = document.querySelector(
        `[data-provider-key="${state.currentProvider}"]`);
      if (btn) btn.click();
    }
    _restoreLateBinds(state, 0);
  }

  function _setSegActive(targetId, value) {
    const grp = document.querySelector(`.seg-control[data-target="${targetId}"]`);
    if (!grp) return;
    grp.querySelectorAll(".seg-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.value === String(value));
    });
  }

  function _restoreLateBinds(state, tries) {
    let allFound = true;
    for (const f of _formFields()) {
      if (!f.lateBind) continue;
      if (!(f.id in state)) continue;
      const el = document.getElementById(f.id);
      if (!el) { allFound = false; continue; }
      // Only set the value if the option exists (for <select>) — otherwise
      // setting .value silently no-ops and we lose the saved choice.
      if (el.tagName === "SELECT") {
        const ok = Array.from(el.options).some(o => o.value === state[f.id]);
        if (!ok) { allFound = false; continue; }
      }
      el.value = state[f.id];
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (!allFound && tries < 20) {
      setTimeout(() => _restoreLateBinds(state, tries + 1), 250);
    }
  }

  let _persistDebounce;
  function _scheduleFormSave() {
    clearTimeout(_persistDebounce);
    _persistDebounce = setTimeout(() => {
      // Mirror to both localStorage (instant restore on next paint) and the
      // server (survives incognito + a different browser).
      try { window.uiPrefSet(FORM_STORAGE_KEY, JSON.stringify(snapshotForm())); }
      catch {}
    }, 250);
  }

  function initFormPersistence() {
    // Listen on every analyze-form input.
    const form = document.getElementById("tab-analyze") || document;
    form.addEventListener("input",  _scheduleFormSave, true);
    form.addEventListener("change", _scheduleFormSave, true);
    form.addEventListener("click",  (e) => {
      // Segmented controls fire on click before the input changes.
      if (e.target.closest(".seg-btn, .analyst-card-v2")) _scheduleFormSave();
    }, true);
    // Restore now.
    try {
      const raw = localStorage.getItem(FORM_STORAGE_KEY);
      if (raw) restoreForm(JSON.parse(raw));
    } catch {}
  }

  // ---- Server-side named presets ---------------------------------------

  let _presetsCache = [];

  /** Pull preset list from server and re-render the dropdown. */
  async function _reloadPresets() {
    try {
      const r = await fetch("/api/presets");
      _presetsCache = await r.json();
    } catch { _presetsCache = []; }
    const sel = document.getElementById("presets-select");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = `<option value="">— Saved presets —</option>` +
      _presetsCache.map(p =>
        `<option value="${p.id}" title="${escapeHtml(p.preview || "")}">${escapeHtml(p.name)}</option>`
      ).join("");
    if (prev && _presetsCache.some(p => p.id === prev)) sel.value = prev;
  }

  /** Save the current form as a named preset (overwrites by name). */
  window.savePreset = async function() {
    const cur = snapshotForm();
    const def = (cur["ticker-input"] || "preset").toUpperCase() + " · " +
                (cur["brevity-input"] || "std");
    const name = (window.prompt("Save current form as preset:", def) || "").trim();
    if (!name) return;
    try {
      const r = await fetch("/api/presets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, values: cur }),
      });
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || "save failed");
      await _reloadPresets();
      const sel = document.getElementById("presets-select");
      if (sel && data.preset) sel.value = data.preset.id;
      window.showToast?.("Preset saved: " + name, "success");
    } catch (e) {
      window.showToast?.("Save failed: " + e.message, "error");
    }
  };

  /** Load the preset currently selected in the dropdown. */
  window.loadSelectedPreset = async function() {
    const sel = document.getElementById("presets-select");
    if (!sel || !sel.value) {
      window.showToast?.("Pick a preset first", "warn");
      return;
    }
    try {
      const r = await fetch(`/api/presets/${sel.value}`);
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || "not found");
      restoreForm(data.preset.values || {});
      _scheduleFormSave();
      window.showToast?.("Loaded preset: " + (data.preset.name || ""), "success");
    } catch (e) {
      window.showToast?.("Load failed: " + e.message, "error");
    }
  };

  /** Delete the preset currently selected. */
  window.deleteSelectedPreset = async function() {
    const sel = document.getElementById("presets-select");
    if (!sel || !sel.value) {
      window.showToast?.("Pick a preset first", "warn");
      return;
    }
    const meta = _presetsCache.find(p => p.id === sel.value);
    if (!window.confirm(`Delete preset "${meta?.name || sel.value}"?`)) return;
    try {
      await fetch(`/api/presets/${sel.value}`, { method: "DELETE" });
      await _reloadPresets();
      window.showToast?.("Preset deleted", "success");
    } catch (e) {
      window.showToast?.("Delete failed: " + e.message, "error");
    }
  };

  function initPresetsUI() {
    // Initial load of dropdown contents.
    _reloadPresets();
  }

  // ---- Boot -------------------------------------------------------------
  function init() {
    initSegControls();
    initOutputTabs();
    // Re-render stages from any default agent state.
    recomputeStages();
    // Hook form changes to refresh the estimate.
    ["ticker-input", "date-input", "quick-model-select", "deep-model-select"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", refreshCostEstimate);
    });
    document.querySelectorAll(".analyst-card-v2 input[type=checkbox]").forEach(cb => {
      cb.addEventListener("change", () => {
        // Sync the .checked class so the wrapper card shows the right state.
        const card = cb.closest(".analyst-card-v2");
        if (card) card.classList.toggle("checked", cb.checked);
        // Update count badge.
        const count = document.querySelectorAll(".analyst-card-v2.checked").length;
        const total = document.querySelectorAll(".analyst-card-v2").length;
        const badge = document.getElementById("analyst-count-badge");
        if (badge) badge.textContent = `${count}/${total}`;
        refreshCostEstimate();
      });
    });
    // initAnalystCards in app.js wires the card click; we add the v2 card
    // class to that toggle by triggering a change event when checkbox flips.
    document.querySelectorAll(".analyst-card-v2").forEach(card => {
      card.addEventListener("click", (e) => {
        if (e.target.matches("input")) return;
        const cb = card.querySelector("input[type=checkbox]");
        if (cb) {
          cb.checked = !cb.checked;
          cb.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    });
    // Theme picker — persists choice in localStorage; reapplies on load.
    const applyTheme = (name) => {
      document.documentElement.dataset.theme = name;
      document.querySelectorAll(".theme-dot").forEach(d => {
        d.classList.toggle("active", d.dataset.theme === name);
      });
      try { window.uiPrefSet("ta_theme", name); } catch {}
    };
    const savedTheme = (() => { try { return localStorage.getItem("ta_theme"); } catch { return null; } })();
    applyTheme(savedTheme || "terminal");
    document.querySelectorAll(".theme-dot").forEach(dot => {
      dot.addEventListener("click", () => applyTheme(dot.dataset.theme));
    });
    // First estimate after providers/models settle.
    setTimeout(refreshCostEstimate, 1200);
  }

  // ====================================================================
  // PHASE 5 — Reports redesign
  // ====================================================================

  // State: currently opened report.
  window._currentReport = null;        // { ticker, date, path, decision, markdown }
  let _allReports = [];                 // cached list from /api/reports

  function decisionClass(text) {
    const t = (text || "").toUpperCase();
    if (t.includes("BUY"))  return "buy";
    if (t.includes("SELL")) return "sell";
    if (t.includes("HOLD")) return "hold";
    return "other";
  }

  /** Replace the legacy reports-list renderer with a v2 one. */
  window.loadReportsList = async function () {
    try {
      const res = await fetch("/api/reports");
      const data = await res.json();
      _allReports = data.reports || [];
      renderReportsListV2(filterReports(_allReports));
    } catch (e) {
      console.error("Failed to load reports", e);
    }
  };

  function filterReports(list) {
    const q = (document.getElementById("reports-search")?.value || "").trim().toLowerCase();
    if (!q) return list;
    return list.filter(r =>
      r.ticker.toLowerCase().includes(q)
      || r.date.toLowerCase().includes(q)
      || (r.decision || "").toLowerCase().includes(q)
    );
  }

  function renderReportsListV2(list) {
    const countEl = document.getElementById("reports-count");
    if (countEl) countEl.textContent = String(list.length);
    // The list is now driven by a <select> dropdown. We populate both the
    // hidden #reports-list (legacy) and the visible #reports-select.
    const select = document.getElementById("reports-select");
    if (select) {
      const prev = select.value;
      select.innerHTML = `<option value="">— ${list.length ? "Pick a report" : "No reports yet"} —</option>`;
      list.forEach((r, idx) => {
        const cls = decisionClass(r.decision);
        const tag = cls === "other" ? "—" : cls.toUpperCase();
        const opt = document.createElement("option");
        opt.value = String(idx);
        opt.textContent = `${r.ticker}  •  ${r.date}  •  ${tag}`;
        opt.dataset.path = r.path;
        select.appendChild(opt);
      });
      // Cache for openReportFromSelect.
      window._reportsCache = list;
      // Try to restore previous selection.
      if (prev && select.querySelector(`option[value="${prev}"]`)) select.value = prev;
    }
  }

  /** Open a report by its index in the cached filtered list. */
  window.openReportFromSelect = function(idx) {
    const list = window._reportsCache || [];
    const r = list[parseInt(idx, 10)];
    if (r) openReport(r);
  };

  /** Toggle the TOC sidebar visibility. Persisted to localStorage + server. */
  window.toggleReportToc = function() {
    const layout = document.getElementById("reports-layout");
    if (!layout) return;
    const collapsed = layout.classList.toggle("toc-collapsed");
    try { window.uiPrefSet("reports_toc_collapsed", collapsed ? "1" : "0"); } catch {}
  };
  // Restore TOC state on boot.
  try {
    if (localStorage.getItem("reports_toc_collapsed") === "1") {
      document.addEventListener("DOMContentLoaded", () => {
        document.getElementById("reports-layout")?.classList.add("toc-collapsed");
      });
    }
  } catch {}

  async function openReport(r) {
    // Mark active in the list.
    document.querySelectorAll(".report-entry").forEach(e => e.classList.remove("active"));
    // Find the matching entry — match by ticker+date.
    const all = document.querySelectorAll(".report-entry");
    for (const node of all) {
      const t = node.querySelector(".report-entry-ticker")?.textContent;
      const d = node.querySelector(".report-entry-date")?.textContent;
      if (t === r.ticker && d === r.date) { node.classList.add("active"); break; }
    }
    // Fetch the markdown.
    let markdown = "";
    try {
      const res = await fetch(`/api/reports/read?path=${encodeURIComponent(r.path)}`);
      const body = await res.json();
      markdown = body.content || "";
    } catch (e) {
      markdown = `_Failed to load report: ${e.message}_`;
    }
    window._currentReport = { ...r, markdown };
    renderReportReader(markdown);
    renderReportSummaryBar(r);
    renderReportTOC(markdown);
  }

  function renderReportSummaryBar(r) {
    const bar = document.getElementById("report-summary-bar");
    if (!bar) return;
    bar.style.display = "flex";
    document.getElementById("rsb-ticker").textContent = r.ticker;
    document.getElementById("rsb-date").textContent = r.date;
    const txt = (r.decision || "no decision recorded").split(/[\n]/)[0];
    const dec = document.getElementById("rsb-decision");
    dec.textContent = txt.length > 120 ? txt.slice(0, 117) + "…" : txt;
    dec.className = "rsb-decision-text " + decisionClass(r.decision);
  }

  function renderReportReader(markdown) {
    const reader = document.getElementById("report-reader");
    if (!reader) return;
    reader.dataset.empty = "false";
    const html = window.marked ? marked.parse(markdown) : escapeHtml(markdown);
    reader.innerHTML = html;
    // Add IDs to every h2/h3 so TOC anchors work.
    let n = 0;
    reader.querySelectorAll("h2, h3").forEach(h => {
      h.id = `section-${++n}`;
    });
  }

  function renderReportTOC(markdown) {
    const toc = document.getElementById("report-toc");
    if (!toc) return;
    const reader = document.getElementById("report-reader");
    if (!reader) return;
    const headings = reader.querySelectorAll("h2, h3");
    if (!headings.length) {
      toc.innerHTML = `<p class="report-toc-empty">No sections.</p>`;
      return;
    }
    toc.innerHTML = "";
    headings.forEach(h => {
      const level = parseInt(h.tagName.substring(1));   // 2 or 3
      const a = document.createElement("a");
      a.className = `toc-link toc-level-${level}`;
      a.href = `#${h.id}`;
      a.textContent = h.textContent;
      a.addEventListener("click", (e) => {
        e.preventDefault();
        document.querySelectorAll(".toc-link").forEach(l => l.classList.remove("active"));
        a.classList.add("active");
        h.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      toc.appendChild(a);
    });
    // Highlight first by default.
    toc.querySelector(".toc-link")?.classList.add("active");

    // Reader scroll → highlight matching TOC entry.
    if (reader._scrollListener) reader.removeEventListener("scroll", reader._scrollListener);
    const handler = () => {
      const r = reader.getBoundingClientRect();
      let bestId = null, bestDist = Infinity;
      reader.querySelectorAll("h2, h3").forEach(h => {
        const hr = h.getBoundingClientRect();
        const dist = Math.abs(hr.top - r.top - 8);
        if (hr.top - r.top < 80 && dist < bestDist) {
          bestDist = dist; bestId = h.id;
        }
      });
      if (!bestId) return;
      toc.querySelectorAll(".toc-link").forEach(l => {
        l.classList.toggle("active", l.getAttribute("href") === `#${bestId}`);
      });
    };
    reader._scrollListener = handler;
    reader.addEventListener("scroll", handler);
  }

  /** Re-run on today's date, prefilled with the open report's ticker. */
  window.rerunReportToday = function () {
    const r = window._currentReport;
    if (!r) return;
    const ticker = document.getElementById("ticker-input");
    const date   = document.getElementById("date-input");
    if (ticker) ticker.value = r.ticker;
    if (date)   date.value   = new Date().toISOString().split("T")[0];
    // Switch to the Analyze tab.
    document.querySelector('.nav-btn[data-tab="analyze"]')?.click();
    window.showToast?.(`Loaded ${r.ticker} into the form — click Run Analysis.`, "info");
  };

  /** Export the current report in the chosen format via the export route.
      ``fmt`` is one of: 'md', 'html', 'pdf'. The 'pdf' option opens the
      report in a new tab and auto-triggers the browser's Save-as-PDF
      dialog — the zero-install path that works on every OS. (The previous
      server-side WeasyPrint path has been removed.) */
  window.exportReport = function (fmt) {
    const r = window._currentReport;
    if (!r) return;
    const url = `/api/reports/export?fmt=${encodeURIComponent(fmt)}&path=${encodeURIComponent(r.path)}`;
    window.open(url, "_blank");
    // Close the menu.
    document.getElementById("rsb-export-menu")?.parentElement?.classList.remove("open");
  };

  /** Delete current report (backend has no delete endpoint yet — placeholder). */
  window.deleteCurrentReport = async function () {
    const r = window._currentReport;
    if (!r) return;
    if (!confirm(`Delete report for ${r.ticker} on ${r.date}? This removes the local files; the run history is unaffected.`)) {
      return;
    }
    try {
      const res = await fetch(`/api/reports/delete?path=${encodeURIComponent(r.path)}`, { method: "POST" });
      if (res.ok) {
        window.showToast?.("Report deleted", "success");
        window._currentReport = null;
        document.getElementById("report-summary-bar").style.display = "none";
        document.getElementById("report-reader").dataset.empty = "true";
        document.getElementById("report-reader").innerHTML = `
          <div class="feed-placeholder">
            <div class="feed-icon">📋</div>
            <p>Report deleted. Pick another from the left.</p>
          </div>`;
        document.getElementById("report-toc").innerHTML = `<p class="report-toc-empty">Open a report to see its sections.</p>`;
        loadReportsList();
      } else {
        window.showToast?.("Delete failed: " + res.statusText, "error");
      }
    } catch (e) {
      window.showToast?.("Delete failed: " + e.message, "error");
    }
  };

  function wireReportsControls() {
    const search = document.getElementById("reports-search");
    if (search) {
      search.addEventListener("input", () => renderReportsListV2(filterReports(_allReports)));
    }
    const exportToggle = document.getElementById("rsb-export-toggle");
    if (exportToggle) {
      exportToggle.addEventListener("click", (e) => {
        e.stopPropagation();
        exportToggle.parentElement.classList.toggle("open");
      });
      document.addEventListener("click", () => {
        exportToggle.parentElement.classList.remove("open");
      });
    }
  }

  // ====================================================================
  // PHASE 6 — Health / Setup tab + first-run wizard
  // ====================================================================

  /** Install missing deps via POST /api/install_missing. */
  window.installMissingDeps = async function(includeOptional) {
    const btn = document.getElementById("install-missing-btn");
    const out = document.getElementById("install-missing-output");
    // (No optional checkbox right now — PDF export is now a zero-install
    // browser-print route, so there's nothing optional left to install.)
    const include = !!includeOptional;
    if (btn) { btn.disabled = true; btn.textContent = "Installing…"; }
    if (out) {
      out.style.display = "block";
      out.textContent = "Running pip install — this can take a minute on first run…\n";
    }
    try {
      const res = await fetch("/api/install_missing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_optional: !!include }),
      });
      const data = await res.json();
      if (out) {
        out.textContent =
          (data.cmd ? `$ ${data.cmd}\n\n` : "") +
          (data.output || data.message || "(no output)");
      }
      if (data.ok) {
        window.showToast?.(data.skipped
          ? "Nothing to install — all deps already present."
          : `Installed: ${(data.installed || []).join(", ")}`, "success");
        // Re-run the health check so the green checks light up.
        setTimeout(() => window.loadHealth?.(), 500);
      } else {
        window.showToast?.("Install failed — see output below.", "error");
      }
    } catch (e) {
      if (out) out.textContent = "Request failed: " + e.message;
      window.showToast?.("Install request failed: " + e.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "⬇ Install missing deps"; }
    }
  };

  /** Pull `/api/health/detailed` and render the diagnostic list. */
  window.loadHealth = async function () {
    try {
      const res = await fetch("/api/health/detailed");
      const data = await res.json();
      renderHealthChecks(data);
      // Auto-show wizard if no API key is set.
      const missingKey = (data.checks || []).find(c => c.key === "api_key" && !c.ok);
      if (missingKey && !localStorage.getItem("wizard_seen")) {
        openWizard();
      }
    } catch (e) {
      console.error("health check failed", e);
    }
  };

  function renderHealthChecks(data) {
    const list = document.getElementById("health-checks");
    if (!list) return;
    list.innerHTML = "";

    // Overall pill
    const overall = document.getElementById("health-overall");
    if (overall) {
      const txt = overall.querySelector(".health-overall-text");
      overall.classList.remove("ok", "warn", "err");
      if (data.ok) {
        overall.classList.add("ok"); txt.textContent = "All systems go";
      } else {
        const warnings = data.checks.filter(c => !c.ok).length;
        overall.classList.add(warnings > 1 ? "err" : "warn");
        txt.textContent = `${warnings} issue${warnings === 1 ? "" : "s"}`;
      }
    }

    // System info panel
    const sys = data.system || {};
    const setInfo = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v || "—"; };
    setInfo("health-info-gui",      sys.gui);
    setInfo("health-info-python",   sys.python);
    setInfo("health-info-platform", sys.platform);
    const fwCheck = (data.checks || []).find(c => c.key === "framework_version");
    setInfo("health-info-framework", fwCheck ? fwCheck.detail.split("•")[0].trim() : "—");

    // Check rows
    for (const c of data.checks || []) {
      const row = document.createElement("div");
      const state = c.ok ? "ok" : (c.optional ? "warn" : "err");
      row.className = `health-check ${state}`;
      row.innerHTML = `
        <span class="health-check-icon">${c.ok ? "✓" : (c.optional ? "!" : "✕")}</span>
        <div class="health-check-body">
          <div class="health-check-label">${escapeHtml(c.label)}</div>
          <div class="health-check-detail">${escapeHtml(c.detail || "")}</div>
          ${c.hint ? `<span class="health-check-hint">${escapeHtml(c.hint)}</span>` : ""}
        </div>
        ${c.optional ? `<span class="health-check-optional">optional</span>` : ""}
      `;
      list.appendChild(row);
    }
  }

  /** Switch to the named tab — used by Health quick-start links. */
  window.switchTab = function (name) {
    const btn = document.querySelector(`.nav-btn[data-tab="${name}"]`);
    if (btn) btn.click();
  };

  // ── First-run wizard ────────────────────────────────────────────────
  let _wizardStep = 1;
  let _wizardProvider = null;

  function openWizard() {
    document.getElementById("wizard-overlay").style.display = "flex";
    _wizardStep = 1; updateWizardSteps();
    populateWizardProviders();
  }
  window.closeWizard = function (skipping = false) {
    document.getElementById("wizard-overlay").style.display = "none";
    try { window.uiPrefSet("wizard_seen", "1"); } catch {}
    if (skipping) window.showToast?.("Wizard skipped. You can add keys any time from the API Keys tab.", "info");
  };
  function updateWizardSteps() {
    document.querySelectorAll(".wizard-step").forEach(s => {
      s.classList.toggle("active", parseInt(s.dataset.step) === _wizardStep);
    });
    document.querySelectorAll(".wizard-dot").forEach((d, i) => {
      d.classList.toggle("active", i < _wizardStep);
    });
    document.getElementById("wizard-back-btn").style.display = _wizardStep > 1 ? "" : "none";
    document.getElementById("wizard-next-btn").textContent = _wizardStep === 3 ? "Get started" : "Next →";
  }
  async function populateWizardProviders() {
    const container = document.getElementById("wizard-providers");
    if (!container) return;
    container.innerHTML = `<p class="form-hint">Loading…</p>`;
    try {
      const providers = await (await fetch("/api/providers")).json();
      container.innerHTML = "";
      for (const p of providers) {
        if (!p.requires_api_key) continue;   // Ollama etc. — skip in wizard
        const btn = document.createElement("button");
        btn.className = "wizard-provider";
        btn.innerHTML = `
          <div class="wizard-provider-name">${escapeHtml(p.label)}</div>
          <div class="wizard-provider-env">${escapeHtml(p.api_key_env || "")}</div>
        `;
        btn.addEventListener("click", () => {
          container.querySelectorAll(".wizard-provider").forEach(b => b.classList.remove("selected"));
          btn.classList.add("selected");
          _wizardProvider = p;
        });
        if (p.key === "openai") {
          btn.classList.add("selected");
          _wizardProvider = p;
        }
        container.appendChild(btn);
      }
    } catch (e) {
      container.innerHTML = `<p class="form-hint">Provider list unavailable.</p>`;
    }
  }
  window.wizardNext = async function () {
    if (_wizardStep === 1) {
      if (!_wizardProvider) {
        window.showToast?.("Pick a provider first.", "error"); return;
      }
      document.getElementById("wizard-env-name").textContent = _wizardProvider.api_key_env || "";
      _wizardStep = 2; updateWizardSteps(); return;
    }
    if (_wizardStep === 2) {
      const key = (document.getElementById("wizard-key-input").value || "").trim();
      if (!key) {
        window.showToast?.("Paste a key, or click Skip.", "error"); return;
      }
      // Save it.
      const updates = { [_wizardProvider.api_key_env]: key };
      try {
        await fetch("/api/env", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(updates),
        });
      } catch (e) {
        window.showToast?.("Save failed: " + e.message, "error"); return;
      }
      _wizardStep = 3; updateWizardSteps(); return;
    }
    // step 3 → close + reload state
    closeWizard(false);
    loadEnvVars(); loadHealth(); loadProviders?.();
    window.showToast?.("All set — head to Analyze to run your first analysis.", "success");
  };
  window.wizardBack = function () {
    if (_wizardStep > 1) { _wizardStep -= 1; updateWizardSteps(); }
  };
  window.wizardTestKey = async function () {
    const status = document.getElementById("wizard-test-status");
    const btn    = document.getElementById("wizard-test-btn");
    if (!_wizardProvider) return;
    const key = (document.getElementById("wizard-key-input").value || "").trim();
    if (!key) {
      status.className = "wizard-test-status err";
      status.textContent = "Enter a key first.";
      return;
    }
    btn.disabled = true; status.className = "wizard-test-status"; status.textContent = "Testing…";
    try {
      const res = await fetch("/api/test_key", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: _wizardProvider.key, api_key: key }),
      });
      const data = await res.json();
      if (data.ok) {
        status.className = "wizard-test-status ok";
        status.textContent = "✓ Connected";
      } else {
        status.className = "wizard-test-status err";
        status.textContent = "✕ " + (data.error || "auth failed");
      }
    } catch (e) {
      status.className = "wizard-test-status err";
      status.textContent = "✕ " + e.message;
    } finally {
      btn.disabled = false;
    }
  };

  // ── Hook tab switch so health auto-refreshes when the user opens Setup ─
  function wireHealthTab() {
    document.querySelectorAll('.nav-btn[data-tab="setup"]').forEach(b => {
      b.addEventListener("click", () => loadHealth());
    });
  }

  // ====================================================================
  // PHASE 8 — Chat tab
  // ====================================================================

  let _chat = {
    sessions:    [],
    activeId:    null,
    streamSrc:   null,
    pendingBubble: null,
  };

  function _deriveTitle(text) {
    let t = text.replace(/\n/g, " ").trim();
    if (t.length > 60) {
      const cut = t.lastIndexOf(" ", 57);
      t = t.slice(0, cut > 0 ? cut : 57) + "…";
    }
    return t || "New chat";
  }

  /** Load the sidebar session list. */
  async function chatLoadSessions() {
    try {
      const res  = await fetch("/api/chat/sessions");
      const data = await res.json();
      _chat.sessions = data.sessions || [];
      renderChatSessions();
    } catch (e) {
      console.error("chat sessions load failed", e);
    }
  }

  function renderChatSessions() {
    const c = document.getElementById("chat-sessions-list");
    if (!c) return;
    if (!_chat.sessions.length) {
      c.innerHTML = `<div class="feed-placeholder"><p>No chats yet — click <strong>＋ New</strong>.</p></div>`;
      return;
    }
    c.innerHTML = "";
    for (const s of _chat.sessions) {
      const entry = document.createElement("div");
      entry.className = "chat-session-entry" + (s.id === _chat.activeId ? " active" : "");
      entry.innerHTML = `
        <div class="chat-session-name-row">
          <div class="chat-session-name">${escapeHtml(s.name || "Untitled")}</div>
          <button class="chat-session-rename-btn" title="Rename" data-sid="${s.id}">✎</button>
        </div>
        <div class="chat-session-meta">
          <span>${s.msg_count || 0} msg</span>
          ${s.attached ? `<span class="chat-session-pin-count">${s.attached} pinned</span>` : ""}
        </div>
      `;
      entry.addEventListener("click", (e) => {
        if (e.target.closest(".chat-session-rename-btn")) return;
        chatOpenSession(s.id);
      });
      entry.querySelector(".chat-session-rename-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        _startSidebarRename(s.id, s.name || "");
      });
      c.appendChild(entry);
    }
  }

  function _startSidebarRename(sid, currentName) {
    const entry = document.querySelector(`.chat-session-rename-btn[data-sid="${sid}"]`)
      ?.closest(".chat-session-entry");
    if (!entry) return;
    const nameEl = entry.querySelector(".chat-session-name");
    if (!nameEl) return;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "chat-session-rename-input";
    input.value = currentName;
    input.placeholder = "Session name";
    nameEl.replaceWith(input);
    input.focus();
    input.select();
    const finish = async () => {
      const newName = input.value.trim() || "Untitled";
      await chatRename(sid, newName);
      if (_chat.activeId === sid) {
        const titleInp = document.getElementById("chat-title-input");
        if (titleInp) titleInp.value = newName;
      }
    };
    input.addEventListener("blur", finish);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") { input.value = currentName; input.blur(); }
    });
  }

  /** Create a new chat session and open it. */
  window.chatNewSession = async function () {
    // Pick a default model: first provider w/ a key, first model in catalog.
    let provider = "openai", model = "gpt-5.4-mini";
    try {
      const provs = await (await fetch("/api/chat/models")).json();
      if (Array.isArray(provs) && provs.length) {
        provider = provs[0].provider;
        const mods = await (await fetch(
          `/api/chat/models?provider=${encodeURIComponent(provider)}`)).json();
        if (Array.isArray(mods) && mods.length) model = mods[0].value;
      }
    } catch {}
    try {
      const res = await fetch("/api/chat/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "New chat", provider, model }),
      });
      const data = await res.json();
      await chatLoadSessions();
      if (data.session) chatOpenSession(data.session.id);
    } catch (e) {
      window.showToast?.("Could not create chat: " + e.message, "error");
    }
  };

  async function chatOpenSession(sid) {
    _chat.activeId = sid;
    renderChatSessions();
    // Hide empty state, show thread wrap.
    document.getElementById("chat-active-empty").style.display = "none";
    document.getElementById("chat-thread-wrap").style.display  = "flex";
    try {
      const res = await fetch(`/api/chat/sessions/${sid}`);
      const data = await res.json();
      const s = data.session || {};
      // Title
      const titleInp = document.getElementById("chat-title-input");
      titleInp.value = s.name || "Untitled";
      titleInp.onblur = () => chatRename(sid, titleInp.value);
      // Model dropdown
      await populateChatModelSelect(s.provider, s.model);
      // Token counter
      updateChatTokens(data.tokens);
      // Pins
      renderChatPins(s.attached || []);
      // Thread
      renderChatThread(s.messages || []);
    } catch (e) {
      window.showToast?.("Open chat failed: " + e.message, "error");
    }
  }

  /** Toggle chat session sidebar. Persisted. */
  window.toggleChatSessions = function() {
    const layout = document.getElementById("chat-layout");
    const expand = document.getElementById("chat-sessions-expand");
    if (!layout) return;
    const collapsed = layout.classList.toggle("sessions-collapsed");
    if (expand) expand.style.display = collapsed ? "" : "none";
    try { window.uiPrefSet("chat_sessions_collapsed", collapsed ? "1" : "0"); } catch {}
  };
  try {
    if (localStorage.getItem("chat_sessions_collapsed") === "1") {
      document.addEventListener("DOMContentLoaded", () => {
        document.getElementById("chat-layout")?.classList.add("sessions-collapsed");
        const exp = document.getElementById("chat-sessions-expand");
        if (exp) exp.style.display = "";
      });
    }
  } catch {}

  /** Force-refetch the chat provider+model list. Useful right after the user
      saves a new API key so newly-unlocked providers / models show up. */
  window.chatRefreshModels = async function() {
    const provSel = document.getElementById("chat-provider-select");
    const modSel  = document.getElementById("chat-model-select");
    if (!provSel || !modSel) return;
    const prevProv = provSel.value || "";
    const prevMod  = (modSel.value || "").split("|")[0];
    try {
      const btn = document.getElementById("chat-model-refresh");
      if (btn) btn.disabled = true;
      await populateChatModelSelect(prevProv, prevMod);
      window.showToast?.("Model list refreshed", "success");
    } catch (e) {
      window.showToast?.("Refresh failed: " + e.message, "error");
    } finally {
      const btn = document.getElementById("chat-model-refresh");
      if (btn) btn.disabled = false;
    }
  };

  /** Persist provider+model on the active session and update the token window. */
  async function _chatPatchModel(provider, model, ctx) {
    if (!_chat.activeId || !provider || !model) return;
    try {
      await fetch(`/api/chat/sessions/${_chat.activeId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      });
      const winEl = document.getElementById("chat-tokens-window");
      if (winEl) winEl.textContent = fmtTokenCount(parseInt(ctx) || 0);
    } catch {}
  }

  /** Load the models list for one provider into the model select. */
  async function _chatLoadModelsFor(provider, preselectModel) {
    const modSel = document.getElementById("chat-model-select");
    if (!modSel) return;
    modSel.innerHTML = "<option value=''>(loading…)</option>";
    let mods = [];
    try {
      const r = await fetch(`/api/chat/models?provider=${encodeURIComponent(provider)}`);
      mods = await r.json();
    } catch {}
    if (!Array.isArray(mods) || !mods.length) {
      modSel.innerHTML = `<option value=''>(no models for this provider)</option>`;
      return;
    }
    modSel.innerHTML = "";
    let matched = false;
    for (const m of mods) {
      const o = document.createElement("option");
      o.value = `${m.value}|${m.context || 128000}`;
      o.textContent = m.label;
      if (m.value === preselectModel) { o.selected = true; matched = true; }
      modSel.appendChild(o);
    }
    // If preselect wasn't in the list, pick the first and persist it so the
    // session never holds a model the provider can't serve.
    const chosen = matched ? preselectModel : mods[0].value;
    const ctx    = matched ? (mods.find(m => m.value === preselectModel)?.context)
                           : mods[0].context;
    if (!matched) modSel.selectedIndex = 0;
    modSel.onchange = () => {
      const [val, c] = modSel.value.split("|");
      const prov = document.getElementById("chat-provider-select").value;
      _chatPatchModel(prov, val, c);
    };
    if (!matched) _chatPatchModel(provider, chosen, ctx);
    else {
      const winEl = document.getElementById("chat-tokens-window");
      if (winEl) winEl.textContent = fmtTokenCount(parseInt(ctx) || 0);
    }
  }

  /** Populate the two-step provider→model picker.
      Cascade: providers with keys → models for the active provider. */
  async function populateChatModelSelect(currentProvider, currentModel) {
    const provSel = document.getElementById("chat-provider-select");
    const modSel  = document.getElementById("chat-model-select");
    if (!provSel || !modSel) return;
    provSel.innerHTML = "<option value=''>(loading…)</option>";
    modSel.innerHTML  = "<option value=''>—</option>";
    let provs = [];
    try {
      const r = await fetch("/api/chat/models");
      provs = await r.json();
    } catch {}
    if (!Array.isArray(provs) || !provs.length) {
      provSel.innerHTML = `<option value=''>(no API keys saved)</option>`;
      modSel.innerHTML  = `<option value=''>Add a key in the API Keys tab</option>`;
      return;
    }
    provSel.innerHTML = "";
    let provMatched = false;
    for (const p of provs) {
      const o = document.createElement("option");
      o.value = p.provider;
      o.textContent = p.label + (p.live ? "  (live)" : "");
      if (p.provider === currentProvider) { o.selected = true; provMatched = true; }
      provSel.appendChild(o);
    }
    if (!provMatched) provSel.selectedIndex = 0;
    const chosenProv = provSel.value;
    provSel.onchange = () => _chatLoadModelsFor(provSel.value, null);
    await _chatLoadModelsFor(chosenProv, currentModel);
  }

  function fmtTokenCount(n) {
    if (n >= 1_000_000) return `${(n/1_000_000).toFixed(1)}M`;
    if (n >= 1000)      return `${Math.round(n/1000)}k`;
    return String(n);
  }

  function updateChatTokens(tokens) {
    if (!tokens) return;
    const usedEl = document.getElementById("chat-tokens-used");
    const winEl  = document.getElementById("chat-tokens-window");
    const pill   = document.getElementById("chat-tokens-pill");
    if (usedEl) usedEl.textContent = fmtTokenCount(tokens.total_tokens || 0);
    if (winEl)  winEl.textContent  = fmtTokenCount(tokens.context_window || 0);
    if (pill) {
      pill.classList.remove("warn", "crit");
      const r = tokens.ratio || 0;
      if (r > 0.95) pill.classList.add("crit");
      else if (r > 0.8) pill.classList.add("warn");
      pill.title = `${tokens.system_tokens || 0} system + ${tokens.history_tokens || 0} history = ${tokens.total_tokens || 0} / ${tokens.context_window || 0}`;
    }
  }

  function renderChatPins(pins) {
    const c = document.getElementById("chat-pins");
    if (!c) return;
    c.innerHTML = "";
    if (!pins.length) {
      c.innerHTML = `<span class="chat-input-hint">No reports pinned. Pin one to ground the conversation.</span>`;
      return;
    }
    for (const p of pins) {
      const chip = document.createElement("span");
      chip.className = "chat-pin-chip";
      chip.innerHTML = `${escapeHtml(p.ticker)} • ${escapeHtml(p.date)}
        <button class="chat-pin-chip-x" title="Remove">×</button>`;
      chip.querySelector(".chat-pin-chip-x").addEventListener("click", () => chatUnpin(p));
      c.appendChild(chip);
    }
  }

  function renderChatThread(messages) {
    const thread = document.getElementById("chat-thread");
    if (!thread) return;
    thread.innerHTML = "";
    for (const m of messages) appendChatMessage(m, false);
    scrollChatToEnd();
  }

  function appendChatMessage(m, animate = true) {
    const thread = document.getElementById("chat-thread");
    if (!thread) return null;
    const wrap = document.createElement("div");
    wrap.className = `chat-msg ${m.role}`;
    const avatar = m.role === "user" ? "🧑" : "🤖";
    const html = window.marked ? marked.parse(m.content || "") : escapeHtml(m.content || "");
    wrap.innerHTML = `
      <div class="chat-msg-avatar">${avatar}</div>
      <div class="chat-msg-bubble">${html}</div>
    `;
    // Row direction (avatar left/right) is now driven by CSS via
    // `.chat-msg.user` / `.chat-msg.assistant` — no inline override.
    thread.appendChild(wrap);
    if (animate) scrollChatToEnd();
    return wrap;
  }

  function scrollChatToEnd() {
    const thread = document.getElementById("chat-thread");
    if (thread) thread.scrollTop = thread.scrollHeight;
  }

  /** Send the user's message; consume the SSE stream as the model replies. */
  window.chatSend = async function () {
    const inp = document.getElementById("chat-input");
    const text = (inp.value || "").trim();
    if (!text || !_chat.activeId) return;
    inp.value = "";
    const sendBtn = document.getElementById("chat-send-btn");
    sendBtn.disabled = true;

    const activeSession = _chat.sessions.find(s => s.id === _chat.activeId);
    const isUntitled = !activeSession || activeSession.name === "New chat" || activeSession.name === "Untitled";

    if (isUntitled) {
      const autoTitle = _deriveTitle(text);
      await chatRename(_chat.activeId, autoTitle);
      const titleInp = document.getElementById("chat-title-input");
      if (titleInp) titleInp.value = autoTitle;
    }

    // Optimistic user bubble.
    appendChatMessage({ role: "user", content: text });

    // Create a streaming assistant bubble.
    const aBubble = appendChatMessage({ role: "assistant", content: "" });
    const bubble  = aBubble.querySelector(".chat-msg-bubble");
    bubble.classList.add("streaming");
    _chat.pendingBubble = bubble;

    // Server-Sent Events. EventSource only supports GET, so we use fetch + ReadableStream.
    let assembled = "";
    try {
      const res = await fetch(`/api/chat/sessions/${_chat.activeId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "token") {
              assembled += event.token;
              bubble.innerHTML = window.marked
                ? marked.parse(assembled)
                : escapeHtml(assembled);
              scrollChatToEnd();
            } else if (event.type === "error") {
              bubble.innerHTML += `<p style="color:var(--err)">⚠ ${escapeHtml(event.message)}</p>`;
            } else if (event.type === "done") {
              bubble.classList.remove("streaming");
            }
          } catch {}
        }
      }
    } catch (e) {
      bubble.classList.remove("streaming");
      bubble.innerHTML += `<p style="color:var(--err)">⚠ ${escapeHtml(e.message)}</p>`;
    } finally {
      bubble.classList.remove("streaming");
      _chat.pendingBubble = null;
      sendBtn.disabled = false;
      // Refresh token count after a turn.
      try {
        const data = await (await fetch(`/api/chat/sessions/${_chat.activeId}`)).json();
        updateChatTokens(data.tokens);
        chatLoadSessions();   // updates message counts in sidebar
      } catch {}
    }
  };

  async function chatRename(sid, newName) {
    if (!newName.trim()) newName = "Untitled";
    await fetch(`/api/chat/sessions/${sid}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() }),
    });
    chatLoadSessions();
  }

  window.chatDelete = async function () {
    if (!_chat.activeId) return;
    if (!confirm("Delete this chat? This cannot be undone.")) return;
    await fetch(`/api/chat/sessions/${_chat.activeId}`, { method: "DELETE" });
    _chat.activeId = null;
    document.getElementById("chat-active-empty").style.display = "flex";
    document.getElementById("chat-thread-wrap").style.display  = "none";
    chatLoadSessions();
  };

  window.chatExport = function () {
    if (!_chat.activeId) return;
    // Compose markdown client-side from the current thread DOM.
    const lines = [];
    document.querySelectorAll("#chat-thread .chat-msg").forEach(m => {
      const role = m.classList.contains("user") ? "User" : "Assistant";
      const body = m.querySelector(".chat-msg-bubble")?.innerText || "";
      lines.push(`### ${role}\n\n${body}\n`);
    });
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = `chat_${_chat.activeId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Pin / Unpin reports ────────────────────────────────────
  window.chatOpenPinPicker = async function () {
    const pop = document.getElementById("chat-pin-picker");
    pop.style.display = "block";
    // Click outside to close.
    setTimeout(() => {
      document.addEventListener("click", _closePinPickerOutside, { once: true });
    }, 0);
    try {
      const data = await (await fetch("/api/reports")).json();
      const list = document.getElementById("chat-pin-list");
      list.innerHTML = "";
      // Find currently-pinned set.
      const sess = await (await fetch(`/api/chat/sessions/${_chat.activeId}`)).json();
      const pinnedSet = new Set((sess.session?.attached || [])
        .map(p => `${p.ticker}|${p.date}`));
      for (const r of data.reports || []) {
        const isPinned = pinnedSet.has(`${r.ticker}|${r.date}`);
        const e = document.createElement("div");
        e.className = "report-entry" + (isPinned ? " pinned" : "");
        e.innerHTML = `
          <div class="report-entry-line">
            <span class="report-entry-ticker">${escapeHtml(r.ticker)}</span>
            <span class="report-entry-date">${escapeHtml(r.date)}</span>
          </div>
          <div class="report-entry-decision">
            <span class="decision-pill ${decisionClass(r.decision)}">${(decisionClass(r.decision) === "other" ? "—" : decisionClass(r.decision).toUpperCase())}</span>
            ${isPinned ? "Pinned" : "Click to pin"}
          </div>`;
        e.addEventListener("click", async () => {
          if (isPinned) await chatUnpin(r);
          else          await chatPin(r);
          chatOpenPinPicker();  // re-render
        });
        list.appendChild(e);
      }
    } catch (e) {
      document.getElementById("chat-pin-list").innerHTML =
        `<p class="form-hint">Failed to load reports: ${escapeHtml(e.message)}</p>`;
    }
  };
  function _closePinPickerOutside(e) {
    const pop = document.getElementById("chat-pin-picker");
    if (!pop.contains(e.target)) chatClosePinPicker();
    else document.addEventListener("click", _closePinPickerOutside, { once: true });
  }
  window.chatClosePinPicker = function () {
    document.getElementById("chat-pin-picker").style.display = "none";
  };

  /** Show the assembled system context — what the model will actually see.
      Critical diagnostic when a pinned report doesn't seem to be working:
      tells you immediately whether the file was found, how many bytes,
      and what wrapper markers landed in the prompt. */
  window.chatShowSystemPreview = async function () {
    if (!_chat.activeId) {
      window.showToast?.("Open a chat first", "warn");
      return;
    }
    let data;
    try {
      const r = await fetch(`/api/chat/sessions/${_chat.activeId}/system_preview`);
      data = await r.json();
      if (data.error) throw new Error(data.error);
    } catch (e) {
      window.showToast?.("Preview failed: " + e.message, "error");
      return;
    }
    const pinLines = (data.pins || []).map(p =>
      p.found
        ? `  ✓ ${p.ticker} ${p.date} — ${(p.bytes/1024).toFixed(1)} KB · ${p.path}`
        : `  ✗ ${p.ticker} ${p.date} — NOT FOUND on disk · expected ${p.path}`
    ).join("\n") || "  (no reports pinned)";

    const win = window.open("", "_blank", "width=900,height=720");
    if (!win) {
      window.showToast?.("Allow popups to view the system context", "warn");
      return;
    }
    const tk = data.tokens || {};
    win.document.write(`
<!doctype html><html><head><title>Chat System Context</title>
<style>
  body { font: 13px/1.5 ui-monospace, monospace; background:#0b1220; color:#dbe5ff;
         margin:0; padding:1.2rem 1.4rem; }
  h2 { color:#69b3ff; font-size:.95rem; margin:1rem 0 .35rem; }
  .meta { color:#8ca8c8; margin-bottom:.7rem; white-space:pre-wrap; }
  pre  { background:#06090f; border:1px solid #1f2937; padding:.8rem 1rem;
         border-radius:6px; white-space:pre-wrap; word-break:break-word; }
  .ok  { color:#22c55e; } .miss { color:#ef4444; }
</style></head><body>
<h2>Pinned reports (${data.pins?.length || 0})</h2>
<div class="meta">${escapeHtml(pinLines).replace(/✓/g,'<span class="ok">✓</span>').replace(/✗/g,'<span class="miss">✗</span>')}</div>
<h2>Context size</h2>
<div class="meta">${data.char_count.toLocaleString()} characters · ` +
  `${(tk.total_tokens || 0).toLocaleString()} tokens of ${(tk.context_window || 0).toLocaleString()} window (` +
  `${((tk.ratio || 0) * 100).toFixed(1)}%)</div>
<h2>Full system prompt the model receives</h2>
<pre>${escapeHtml(data.system)}</pre>
</body></html>`);
    win.document.close();
  };

  async function chatPin(r) {
    if (!_chat.activeId) return;
    const res = await (await fetch(`/api/chat/sessions/${_chat.activeId}/pin`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: r.ticker, date: r.date }),
    })).json();
    renderChatPins(res.attached || []);
    updateChatTokens(res.tokens);
  }
  async function chatUnpin(r) {
    if (!_chat.activeId) return;
    const res = await (await fetch(`/api/chat/sessions/${_chat.activeId}/unpin`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: r.ticker, date: r.date }),
    })).json();
    renderChatPins(res.attached || []);
    updateChatTokens(res.tokens);
  }

  // ====================================================================
  // PHASE 9 — Header polish (live run pill, notifications, memory log)
  // ====================================================================

  window._currentRunActive = false;
  let _runStartTs = null;
  let _notifAsked = false;

  /** Refresh the live status pill based on the current run state. */
  function setStatusPill(state, ticker, detail) {
    const pill = document.getElementById("global-status");
    if (!pill) return;
    const dot   = pill.querySelector(".status-dot");
    const text  = pill.querySelector(".status-text");
    const det   = pill.querySelector("#status-detail");
    if (!dot || !text) return;
    dot.className = "status-dot " + state;
    text.textContent = state.toUpperCase();
    if (det) det.textContent = detail || (ticker || "");
    pill.dataset.active = (state === "running") ? "1" : "0";
    window._currentRunActive = (state === "running");
    // Title for screen readers
    pill.title = ticker ? `${state} — ${ticker}` : state;
  }

  /** Maybe ask for notification permission. Idempotent. */
  function askNotificationPermission() {
    if (_notifAsked) return;
    _notifAsked = true;
    try {
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
      }
    } catch {}
  }

  /** Fire a browser notification + an in-tab banner. */
  function fireNotification(title, body, kind = "info") {
    // Try native first.
    try {
      if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
        const n = new Notification(title, { body, icon: "/static/favicon.ico" });
        n.onclick = () => window.focus();
        return;
      }
    } catch {}
    // Fallback: in-tab banner.
    const b = document.createElement("div");
    b.className = `run-banner ${kind}`;
    const icon = kind === "success" ? "✓" : (kind === "error" ? "✕" : "ℹ");
    b.innerHTML = `
      <span class="run-banner-icon">${icon}</span>
      <span class="run-banner-body"><strong>${escapeHtml(title)}</strong><br>${escapeHtml(body)}</span>
      <button class="run-banner-close">✕</button>
    `;
    b.querySelector(".run-banner-close").onclick = () => b.remove();
    document.body.appendChild(b);
    setTimeout(() => b.remove(), 8000);
  }

  // ── Subclass the existing onmessage handler ────────────────────────
  // The base app.js sets up `evtSource` after startAnalysis(); we hook a
  // *second* listener that just drives the status pill + notifications.
  function attachStatusPillBridge() {
    // We can't directly listen to the same EventSource since app.js owns it.
    // Instead we poll a derived state from the existing DOM + /api/status.
    let lastStatus = "idle";
    let lastTicker = null;

    async function tick() {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        const ticker = (document.getElementById("ticker-input")?.value || "").toUpperCase() || lastTicker;
        if (data.running) {
          // Active run — pull the most-recent agent in_progress for context.
          const inProg = Array.from(document.querySelectorAll(".stage-agent.in_progress"))
            .map(el => el.querySelector(".sa-nm")?.textContent)
            .filter(Boolean)[0];
          setStatusPill("running", ticker, inProg ? `${ticker || "run"} • ${inProg}` : ticker);
          lastStatus = "running"; lastTicker = ticker;
          if (!_runStartTs) _runStartTs = Date.now();
        } else if (lastStatus === "running") {
          // Just transitioned to idle — fire the notification.
          const decision = document.getElementById("decision-text")?.textContent?.trim();
          const kind = decision && /buy|sell|hold/i.test(decision) ? "success" : "info";
          const elapsed = _runStartTs ? Math.round((Date.now() - _runStartTs) / 1000) : 0;
          fireNotification(
            `Analysis complete${lastTicker ? `: ${lastTicker}` : ""}`,
            decision
              ? decision.slice(0, 120)
              : `Run finished in ${elapsed}s.`,
            kind,
          );
          setStatusPill("done", lastTicker, decision ? decision.slice(0, 40) : "complete");
          lastStatus = "done"; _runStartTs = null;
        } else {
          // Idle (or just been cleared)
          setStatusPill(lastStatus === "idle" ? "idle" : lastStatus, lastTicker, "");
        }
      } catch (e) {
        // Don't spam the console if the server momentarily blips
      } finally {
        setTimeout(tick, 2200);
      }
    }
    setTimeout(tick, 1500);
  }

  // ── Ask for permission the first time the user clicks Run ──────────
  function wireNotificationPrompt() {
    const runBtn = document.getElementById("run-btn");
    if (runBtn) {
      runBtn.addEventListener("click", askNotificationPermission, { once: true });
    }
  }

  // ── Memory-log markdown rendering ──────────────────────────────────
  const origLoadHistory = window.loadHistory;
  window.loadHistory = async function () {
    // Re-fetch the usage card whenever the History tab loads.
    loadUsageStats();
    try {
      const res = await fetch("/api/history");
      const data = await res.json();
      const container = document.getElementById("history-content");
      if (!container) return;
      const md = data.content || "";
      if (!md.trim()) {
        container.innerHTML = `<div class="feed-placeholder"><p>No decision history yet. Run an analysis to start the memory log.</p></div>`;
        return;
      }
      container.innerHTML = window.marked ? marked.parse(md) : escapeHtml(md);
    } catch (e) {
      // Fall back to whatever the original did.
      if (typeof origLoadHistory === "function") origLoadHistory();
    }
  };

  // ── Usage stats card (lifetime aggregation) ─────────────────────────
  let _usageData = null;
  let _usageChartMode = "tokens";

  function _fmtNum(n) {
    if (n == null) return "—";
    n = Number(n);
    if (!isFinite(n)) return "—";
    if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + "B";
    if (n >= 1_000_000)     return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000)         return (n / 1_000).toFixed(1) + "k";
    return String(Math.round(n));
  }
  function _fmtCost(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    return "$" + Number(n).toFixed(2);
  }
  function _fmtElapsed(s) {
    if (s == null) return "—";
    s = Math.round(Number(s) || 0);
    if (s < 60)    return s + "s";
    if (s < 3600)  return Math.floor(s / 60) + "m " + String(s % 60).padStart(2, "0") + "s";
    if (s < 86400) return Math.floor(s / 3600) + "h " + String(Math.floor((s % 3600) / 60)).padStart(2, "0") + "m";
    return (s / 86400).toFixed(1) + "d";
  }

  window.loadUsageStats = async function () {
    try {
      const res = await fetch("/api/runs/stats");
      _usageData = await res.json();
    } catch {
      _usageData = null;
    }
    renderUsageStats();
  };

  function renderUsageStats() {
    const d = _usageData;
    if (!d) return;
    const L = d.lifetime || {};
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

    setText("usage-runs",  _fmtNum(L.run_count));
    setText("usage-llm",   _fmtNum(L.llm_calls));
    setText("usage-tools", _fmtNum(L.tool_calls));
    setText("usage-tokens", `${_fmtNum(L.tokens_in)} / ${_fmtNum(L.tokens_out)}`);
    setText("usage-total-tokens", _fmtNum(L.tokens_total));
    setText("usage-cost", _fmtCost(L.cost_usd));
    setText("usage-elapsed", _fmtElapsed(L.elapsed_s));

    const T = d.this_month || {};
    setText("usage-this-month-cost",   _fmtCost(T.cost_usd));
    setText("usage-this-month-runs",   _fmtNum(T.run_count));
    setText("usage-this-month-tokens", _fmtNum(T.tokens_total));

    const R = d.last_30d || {};
    setText("usage-30d-cost",   _fmtCost(R.cost_usd));
    setText("usage-30d-runs",   _fmtNum(R.run_count));
    setText("usage-30d-tokens", _fmtNum(R.tokens_total));

    _renderUsageChart();
    _renderBreakdown("usage-top-providers", d.top_providers || [],
                     p => `<span class="bd-key">${escapeHtml(p.name)}</span><span class="bd-val">${_fmtCost(p.cost_usd)} · ${_fmtNum(p.run_count)} runs</span>`);
    _renderBreakdown("usage-top-models",    d.top_models    || [],
                     p => `<span class="bd-key">${escapeHtml(p.name)}</span><span class="bd-val">${_fmtNum(p.tokens_total)} tok · ${_fmtCost(p.cost_usd)}</span>`);
    _renderBreakdown("usage-top-tickers",   d.top_tickers   || [],
                     p => `<span class="bd-key">${escapeHtml(p.name)}</span><span class="bd-val">${_fmtNum(p.run_count)} runs · ${_fmtCost(p.cost_usd)}</span>`);

    // Decision split as a small inline breakdown.
    const dec = d.decisions || {};
    const total = (dec.BUY||0) + (dec.SELL||0) + (dec.HOLD||0) + (dec.other||0);
    const decRows = [["BUY","ok"], ["HOLD","warn"], ["SELL","err"], ["other","mute"]].map(([k, tone]) => {
      const n = dec[k] || 0;
      const pct = total ? Math.round(100 * n / total) : 0;
      return `<li><span class="bd-key bd-tone-${tone}">${k}</span><span class="bd-val">${n} · ${pct}%</span></li>`;
    }).join("");
    const decEl = document.getElementById("usage-decisions");
    if (decEl) decEl.innerHTML = decRows || `<li class="muted">No completed runs yet.</li>`;
  }

  function _renderBreakdown(id, rows, fmt) {
    const ul = document.getElementById(id);
    if (!ul) return;
    if (!rows.length) {
      ul.innerHTML = `<li class="muted">No data yet.</li>`;
      return;
    }
    ul.innerHTML = rows.map(r => `<li>${fmt(r)}</li>`).join("");
  }

  function _renderUsageChart() {
    const wrap = document.getElementById("usage-chart");
    if (!wrap || !_usageData?.monthly) return;
    const series = _usageData.monthly.map(m => {
      const v = _usageChartMode === "cost"  ? m.cost_usd
              : _usageChartMode === "runs"  ? m.run_count
                                            : m.tokens_total;
      return { month: m.month, value: Number(v) || 0 };
    });
    const max = Math.max(1, ...series.map(s => s.value));
    const unit = _usageChartMode === "cost"  ? "cost"
               : _usageChartMode === "runs"  ? "runs"
                                             : "tokens";
    wrap.innerHTML = series.map(s => {
      const h = Math.max(2, Math.round(100 * s.value / max));
      const label = s.month.slice(5); // "MM"
      const tip = _usageChartMode === "cost" ? _fmtCost(s.value)
                : _usageChartMode === "runs" ? String(s.value)
                                             : _fmtNum(s.value);
      return `
        <div class="usage-bar-col" title="${s.month}: ${tip} ${unit}">
          <div class="usage-bar" style="height:${h}%"></div>
          <div class="usage-bar-label">${label}</div>
        </div>`;
    }).join("");
  }

  window.setUsageChartMode = function (mode) {
    _usageChartMode = mode;
    document.querySelectorAll(".usage-chart-mode").forEach(b => {
      b.classList.toggle("active", b.dataset.mode === mode);
    });
    _renderUsageChart();
  };

  // ── Wire keyboard shortcut + tab activation ────────────────
  function wireChat() {
    const inp = document.getElementById("chat-input");
    if (inp) {
      inp.addEventListener("keydown", (e) => {
        // Standard chat UX: Enter sends, Shift+Enter inserts a newline.
        // Ctrl/Cmd+Enter still works as a power-user alias for "send".
        if (e.key === "Enter" && !e.isComposing) {
          if (e.shiftKey) return;          // newline — let the textarea handle it
          e.preventDefault();
          chatSend();
        }
      });
    }
    document.querySelectorAll('.nav-btn[data-tab="chat"]').forEach(b => {
      b.addEventListener("click", () => chatLoadSessions());
    });
  }

  // Run reports/health/chat/header init after the original DOMContentLoaded init.
  const origInit = init;
  init = function() {                          // eslint-disable-line no-func-assign
    origInit();
    wireReportsControls();
    wireHealthTab();
    wireChat();
    wireNotificationPrompt();
    attachStatusPillBridge();
    // Also kick off a health check at boot so the Setup tab is ready and
    // the wizard can decide whether to auto-open.
    loadHealth();
    // Form-state persistence + preset loading. Run last so all other
    // initializers have wired their change listeners first.
    initFormPersistence();
    initPresetsUI();
  };

  // Wait for the server-state bootstrap to land before running init so the
  // original ``localStorage.getItem()`` call sites see the server-loaded
  // values on the very first paint (matters in incognito / fresh browsers).
  // A 1500ms cap means a slow server doesn't block the UI forever — we'll
  // still fall back to whatever localStorage has (or defaults).
  function _runInitAfterBootstrap() {
    const timeout = new Promise(r => setTimeout(r, 1500));
    Promise.race([_bootstrapPromise, timeout]).then(() => init());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _runInitAfterBootstrap);
  } else {
    _runInitAfterBootstrap();
  }
})();
