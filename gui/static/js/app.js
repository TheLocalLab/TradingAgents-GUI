/* ═════════════════════════════════════════════════════════════
   TradingAgents GUI — Client Logic
   ═════════════════════════════════════════════════════════════ */

// ─── State ───
let currentProvider = "openai";
let availableProviders = [];
let evtSource = null;
let currentReportSections = {};
let analysisStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };

// ─── Initialization ───
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initDateInput();
  initAnalystCards();
  initOsTabs();
  
  loadProviders();
  loadEnvVars();
  loadReportsList();
  
  document.getElementById("vendor-core").addEventListener("change", markConfigUnsaved);
  document.getElementById("vendor-technical").addEventListener("change", markConfigUnsaved);
  document.getElementById("vendor-fundamental").addEventListener("change", markConfigUnsaved);
  document.getElementById("vendor-news").addEventListener("change", markConfigUnsaved);
  
  checkStatus();
});

// ─── UI & Tabs ───
function initTabs() {
  const btns = document.querySelectorAll(".nav-btn");
  const panels = document.querySelectorAll(".tab-panel");
  
  btns.forEach(btn => {
    btn.addEventListener("click", () => {
      btns.forEach(b => b.classList.remove("active"));
      panels.forEach(p => p.classList.remove("active"));
      
      btn.classList.add("active");
      const tabId = btn.getAttribute("data-tab");
      document.getElementById("tab-" + tabId).classList.add("active");
      
      if (tabId === "history") loadHistory();
      if (tabId === "reports") loadReportsList();
    });
  });
}

function initDateInput() {
  const d = new Date();
  const todayStr = d.toISOString().split("T")[0];
  const input = document.getElementById("date-input");
  input.value = todayStr;
  input.max = todayStr;
}

function initAnalystCards() {
  const cards = document.querySelectorAll(".analyst-card");
  cards.forEach(card => {
    card.addEventListener("click", () => {
      const checkbox = card.querySelector("input");
      checkbox.checked = !checkbox.checked;
      if (checkbox.checked) card.classList.add("checked");
      else card.classList.remove("checked");
    });
  });
}

function initOsTabs() {
  const btns = document.querySelectorAll(".os-tab");
  btns.forEach(btn => {
    btn.addEventListener("click", () => {
      btns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const os = btn.getAttribute("data-os");
      if (os === "windows") {
        document.getElementById("venv-cmd-windows").style.display = "block";
        document.getElementById("venv-cmd-mac").style.display = "none";
      } else {
        document.getElementById("venv-cmd-windows").style.display = "none";
        document.getElementById("venv-cmd-mac").style.display = "block";
      }
    });
  });
}

// ─── Toasts ───
function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 250);
  }, 3000);
}

// ─── API Keys & Env ───
async function loadEnvVars() {
  try {
    const res = await fetch("/api/env");
    const data = await res.json();
    renderApiKeys(data);
  } catch (e) {
    console.error("Failed to load env vars", e);
  }
}

function renderApiKeys(envData) {
  const llmContainer = document.getElementById("llm-keys");
  const dataContainer = document.getElementById("data-keys");
  const entContainer = document.getElementById("enterprise-keys");
  
  llmContainer.innerHTML = "";
  dataContainer.innerHTML = "";
  entContainer.innerHTML = "";
  
  const providers = [
    { key: "OPENAI_API_KEY", label: "OpenAI API Key", group: llmContainer },
    { key: "GOOGLE_API_KEY", label: "Google (Gemini) API Key", group: llmContainer },
    { key: "ANTHROPIC_API_KEY", label: "Anthropic API Key", group: llmContainer },
    { key: "XAI_API_KEY", label: "xAI API Key", group: llmContainer },
    { key: "DEEPSEEK_API_KEY", label: "DeepSeek API Key", group: llmContainer },
    { key: "DASHSCOPE_API_KEY", label: "Qwen (DashScope) API Key", group: llmContainer },
    { key: "ZHIPU_API_KEY", label: "GLM (Zhipu) API Key", group: llmContainer },
    { key: "OPENROUTER_API_KEY", label: "OpenRouter API Key", group: llmContainer },
    
    { key: "ALPHA_VANTAGE_API_KEY", label: "Alpha Vantage API Key", group: dataContainer },
    
    { key: "AZURE_OPENAI_API_KEY", label: "Azure API Key", group: entContainer },
    { key: "AZURE_OPENAI_ENDPOINT", label: "Azure Endpoint URL", group: entContainer, type: "text" },
    { key: "AZURE_OPENAI_DEPLOYMENT_NAME", label: "Azure Deployment Name", group: entContainer, type: "text" }
  ];
  
  providers.forEach(p => {
    const row = document.createElement("div");
    row.className = "key-row";
    const val = envData[p.key] || "";
    const inputType = p.type || "password";
    const isMasked = val.includes("*");
    const placeholder = isMasked ? val : `Enter ${p.label}`;
    
    row.innerHTML = `
      <div class="key-label">${p.label}</div>
      <input type="${inputType}" id="env-${p.key}" placeholder="${placeholder}">
    `;
    
    // Pre-fill masked values as placeholder so user knows a key exists
    const input = row.querySelector("input");
    if (isMasked) {
      input.dataset.masked = "true";
      input.placeholder = val;
    }
    
    if (inputType === "password") {
      const toggle = document.createElement("button");
      toggle.className = "key-toggle";
      toggle.innerHTML = "\uD83D\uDC41\uFE0F";
      toggle.title = "Toggle Visibility";
      toggle.onclick = () => {
        if (input.type === "password") {
          input.type = "text";
          toggle.innerHTML = "\uD83D\uDC48";
        } else {
          input.type = "password";
          toggle.innerHTML = "\uD83D\uDC41\uFE0F";
        }
      };
      row.appendChild(toggle);
    }
    
    const providerKeyMap = {
      "OPENAI_API_KEY": "openai",
      "GOOGLE_API_KEY": "google",
      "ANTHROPIC_API_KEY": "anthropic",
      "XAI_API_KEY": "xai",
      "DEEPSEEK_API_KEY": "deepseek",
      "DASHSCOPE_API_KEY": "qwen",
      "ZHIPU_API_KEY": "glm",
      "OPENROUTER_API_KEY": "openrouter",
      "ALPHA_VANTAGE_API_KEY": "alpha_vantage",
    };
    
    const testProvider = providerKeyMap[p.key];
    if (testProvider && p.group === llmContainer) {
      const testBtn = document.createElement("button");
      testBtn.className = "btn btn-ghost btn-sm key-test-btn";
      testBtn.innerHTML = "\uD83E\uDDEA Test";
      testBtn.onclick = () => testApiKey(testProvider, document.getElementById(`env-${p.key}`).value);
      row.appendChild(testBtn);
    }
    
    p.group.appendChild(row);
  });
}

async function testApiKey(provider, key) {
  if (!key) {
    showToast("Please enter an API key first", "error");
    return;
  }
  
  showToast(`Testing ${provider} key...`);
  try {
    const res = await fetch("/api/test_key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, api_key: key })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`${provider} key is valid!`, "success");
    } else {
      showToast(`${provider} error: ${data.error}`, "error");
    }
  } catch (e) {
    showToast("Failed to test API key", "error");
  }
}

async function saveApiKeys() {
  const inputs = document.querySelectorAll("[id^='env-']");
  const data = {};
  inputs.forEach(input => {
    const key = input.id.replace("env-", "");
    const value = input.value;
    if (value && !input.dataset.masked) {
      data[key] = value;
    }
  });
  
  try {
    const res = await fetch("/api/env", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    if (res.ok) {
      const msg = document.getElementById("keys-saved-msg");
      msg.style.display = "inline-block";
      setTimeout(() => msg.style.display = "none", 3000);
      showToast("API keys saved successfully", "success");
      loadEnvVars();
    }
  } catch (e) {
    showToast("Failed to save API keys", "error");
  }
}

// ─── Config & Models ───
async function loadProviders() {
  try {
    // 1) Pull saved Configuration-tab state first so we know what to select.
    //    Server-side blob survives restarts AND moving to a different browser.
    let saved = {};
    try {
      const r = await fetch("/api/ui_state");
      saved = (await r.json()) || {};
    } catch {}
    if (saved.provider) currentProvider = saved.provider;

    const res = await fetch("/api/providers");
    availableProviders = await res.json();
    renderProviderGrid();
    await updateModelsForProvider(currentProvider);

    // 2) After models render, re-apply saved quick/deep model selections.
    //    If the saved value isn't in the new <select>'s option list (e.g.
    //    a stale custom id), leave whatever default the dropdown picked.
    const setIfPresent = (id, val) => {
      const el = document.getElementById(id);
      if (!el || !val) return;
      const has = Array.from(el.options).some(o => o.value === val);
      if (has) el.value = val;
    };
    setIfPresent("quick-model-select", saved.quick_model);
    setIfPresent("deep-model-select",  saved.deep_model);
    setIfPresent("language-select",    saved.language);
    setIfPresent("vendor-core",        saved.vendor_core);
    setIfPresent("vendor-technical",   saved.vendor_technical);
    setIfPresent("vendor-fundamental", saved.vendor_fundamental);
    setIfPresent("vendor-news",        saved.vendor_news);
    // Provider-specific custom fields render lazily — wait a tick.
    setTimeout(() => {
      setIfPresent("custom-quick-model", saved.custom_quick_model);
      setIfPresent("custom-deep-model",  saved.custom_deep_model);
      setIfPresent("custom-backend-url", saved.custom_backend_url);
      setIfPresent("openai-effort",      saved.openai_effort);
      setIfPresent("anthropic-effort",   saved.anthropic_effort);
      setIfPresent("google-thinking",    saved.google_thinking);
    }, 50);
  } catch (e) {
    console.error("Failed to load providers", e);
  }
}

function renderProviderGrid() {
  const container = document.getElementById("provider-grid");
  container.innerHTML = "";
  
  availableProviders.forEach(p => {
    const chip = document.createElement("button");
    chip.className = `provider-chip ${p.key === currentProvider ? "selected" : ""}`;
    chip.textContent = p.label;
    chip.onclick = () => selectProvider(p.key);
    container.appendChild(chip);
  });
}

async function selectProvider(key) {
  currentProvider = key;
  renderProviderGrid();
  await updateModelsForProvider(key);
  markConfigUnsaved();
  // Auto-persist — provider switching is a click on a button, so the
  // generic "change" listener doesn't pick it up.
  if (typeof _autoSaveConfig === "function") _autoSaveConfig();
}

async function updateModelsForProvider(providerKey) {
  try {
    const [quickRes, deepRes] = await Promise.all([
      fetch(`/api/models?provider=${providerKey}&mode=quick`),
      fetch(`/api/models?provider=${providerKey}&mode=deep`)
    ]);
    
    const quickGroups = await quickRes.json();
    const deepGroups = await deepRes.json();
    
    const qSelect = document.getElementById("quick-model-select");
    const dSelect = document.getElementById("deep-model-select");
    
    const renderSelect = (selectElement, data) => {
      selectElement.innerHTML = "";
      if (data.length === 0) {
        selectElement.innerHTML = `<option value="">(Enter manually below)</option>`;
        return;
      }
      
      if (data[0] && data[0].options) {
        data.forEach(group => {
          const optgroup = document.createElement("optgroup");
          optgroup.label = group.label;
          group.options.forEach(m => {
            const opt = document.createElement("option");
            opt.value = m.value;
            opt.textContent = m.label;
            if (m.is_custom) opt.dataset.custom = "true";
            optgroup.appendChild(opt);
          });
          selectElement.appendChild(optgroup);
        });
      } else {
        data.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m.value;
          opt.textContent = m.label;
          if (m.is_custom) opt.dataset.custom = "true";
          selectElement.appendChild(opt);
        });
      }
    };
    
    renderSelect(qSelect, quickGroups);
    renderSelect(dSelect, deepGroups);
    
    renderProviderSettings(providerKey);
    
  } catch (e) {
    console.error("Failed to update models", e);
  }
}

function renderProviderSettings(providerKey) {
  const container = document.getElementById("provider-settings");
  container.innerHTML = "";
  
  if (providerKey === "openai") {
    container.innerHTML = `
      <div class="provider-option-group">
        <h4>OpenAI Reasoning Effort</h4>
        <select id="openai-effort">
          <option value="">Default</option>
          <option value="low">Low (Faster)</option>
          <option value="medium">Medium (Balanced)</option>
          <option value="high">High (More thorough)</option>
        </select>
        <span class="form-hint" style="display:block;margin-top:0.3rem">Controls thinking effort for reasoning models.</span>
      </div>
    `;
    document.getElementById("openai-effort").addEventListener("change", markConfigUnsaved);
  } else if (providerKey === "anthropic") {
    container.innerHTML = `
      <div class="provider-option-group">
        <h4>Claude Extended Thinking</h4>
        <select id="anthropic-effort">
          <option value="">Default (Disabled)</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <span class="form-hint" style="display:block;margin-top:0.3rem">Enables extended thinking for Claude 4.5+ models.</span>
      </div>
    `;
    document.getElementById("anthropic-effort").addEventListener("change", markConfigUnsaved);
  } else if (providerKey === "google") {
    container.innerHTML = `
      <div class="provider-option-group">
        <h4>Gemini Thinking Level</h4>
        <select id="google-thinking">
          <option value="">Default</option>
          <option value="minimal">Minimal / Disabled</option>
          <option value="high">High (Enabled)</option>
        </select>
      </div>
    `;
    document.getElementById("google-thinking").addEventListener("change", markConfigUnsaved);
  } else if (providerKey === "openrouter" || providerKey === "azure" || providerKey === "ollama") {
    container.innerHTML = `
      <div class="provider-option-group">
        <h4>Custom Model Strings</h4>
        <div class="form-row">
          <div class="form-group flex1">
            <label>Quick Model ID${providerKey === "azure" ? " / Deployment Name" : ""}</label>
            <input type="text" id="custom-quick-model" placeholder="${providerKey === "azure" ? "e.g. gpt-4.1" : "e.g. google/gemma-2..."}">
          </div>
          <div class="form-group flex1">
            <label>Deep Model ID${providerKey === "azure" ? " / Deployment Name" : ""}</label>
            <input type="text" id="custom-deep-model" placeholder="${providerKey === "azure" ? "e.g. gpt-5.4" : "e.g. anthropic/claude-3.5..."}">
          </div>
        </div>
        ${providerKey === "ollama" ? `
        <div class="form-group" style="margin-top:0.75rem">
          <label>Ollama Server URL</label>
          <input type="text" id="custom-backend-url" value="http://localhost:11434/v1" placeholder="http://localhost:11434/v1">
          <span class="form-hint">URL of your local Ollama instance</span>
        </div>` : ""}
      </div>
    `;
    document.getElementById("custom-quick-model")?.addEventListener("input", markConfigUnsaved);
    document.getElementById("custom-deep-model")?.addEventListener("input", markConfigUnsaved);
    document.getElementById("custom-backend-url")?.addEventListener("input", markConfigUnsaved);
  }
}

function markConfigUnsaved() {
  document.getElementById("config-saved-msg").style.display = "none";
}

function _snapshotConfigState() {
  // Snapshot the Configuration-tab state into a flat blob the server stores.
  const v = (id) => document.getElementById(id)?.value || "";
  return {
    provider:            currentProvider,
    quick_model:         v("quick-model-select"),
    deep_model:          v("deep-model-select"),
    language:            v("language-select"),
    vendor_core:         v("vendor-core"),
    vendor_technical:    v("vendor-technical"),
    vendor_fundamental:  v("vendor-fundamental"),
    vendor_news:         v("vendor-news"),
    custom_quick_model:  v("custom-quick-model"),
    custom_deep_model:   v("custom-deep-model"),
    custom_backend_url:  v("custom-backend-url"),
    openai_effort:       v("openai-effort"),
    anthropic_effort:    v("anthropic-effort"),
    google_thinking:     v("google-thinking"),
  };
}

async function saveConfig() {
  const msg = document.getElementById("config-saved-msg");
  try {
    const res = await fetch("/api/ui_state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_snapshotConfigState()),
    });
    const data = await res.json();
    if (!data.ok) throw new Error("save failed");
    if (msg) {
      msg.style.display = "inline-block";
      setTimeout(() => msg.style.display = "none", 3000);
    }
    showToast("Configuration saved — will be loaded on next restart", "success");
  } catch (e) {
    showToast("Save failed: " + e.message, "error");
  }
}

// Auto-save Configuration-tab changes (debounced) so the user never has
// to remember to click "Save". The explicit button is kept for UX feedback.
let _configAutoSaveTimer = null;
function _autoSaveConfig() {
  clearTimeout(_configAutoSaveTimer);
  _configAutoSaveTimer = setTimeout(() => {
    fetch("/api/ui_state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_snapshotConfigState()),
    }).catch(() => {});
  }, 400);
}
document.addEventListener("change", (e) => {
  if (e.target.closest && e.target.closest("#tab-config")) _autoSaveConfig();
}, true);

// ─── Analysis Runner ───
let timerInterval = null;
let startTime = null;

async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.running && evtSource === null) {
      connectEventStream();
      setUiRunning(true);
    }
  } catch (e) {
    console.error("Status check failed", e);
  }
}

async function startAnalysis() {
  const ticker = document.getElementById("ticker-input").value.trim().toUpperCase();
  if (!ticker) {
    showToast("Please enter a ticker symbol", "error");
    document.getElementById("ticker-input").focus();
    return;
  }
  
  const date = document.getElementById("date-input").value;
  
  const analysts = [];
  // v2 redesign uses .analyst-card-v2; fall back to legacy .analyst-card just in case
  document.querySelectorAll(".analyst-card-v2.checked input[type=checkbox], .analyst-card.checked input[type=checkbox]")
    .forEach(el => analysts.push(el.value));
  if (analysts.length === 0) {
    showToast("Please select at least one analyst", "error");
    return;
  }
  
  // v2 redesign uses #depth-input (hidden, driven by seg-control)
  const depth = (document.getElementById("depth-select") || document.getElementById("depth-input"))?.value || "3";
  const lang = document.getElementById("language-select").value;
  const checkpoint = document.getElementById("checkpoint-check").checked;
  const clearChecks = document.getElementById("clear-check").checked;
  
  let quickModel = document.getElementById("quick-model-select").value;
  let deepModel = document.getElementById("deep-model-select").value;
  
  if (currentProvider === "openrouter" || currentProvider === "azure" || currentProvider === "ollama") {
    quickModel = document.getElementById("custom-quick-model")?.value || quickModel;
    deepModel = document.getElementById("custom-deep-model")?.value || deepModel;
  }
  
  const googleThinking = document.getElementById("google-thinking")?.value || null;
  const openaiEffort = document.getElementById("openai-effort")?.value || null;
  const anthropicEffort = document.getElementById("anthropic-effort")?.value || null;
  
  let backendUrl = null;
  if (currentProvider === "openrouter" || currentProvider === "azure" || currentProvider === "ollama") {
    const customUrl = document.getElementById("custom-backend-url")?.value;
    if (customUrl) backendUrl = customUrl;
    else {
      const providerData = availableProviders.find(p => p.key === currentProvider);
      backendUrl = providerData ? providerData.url : null;
    }
  } else {
    const providerData = availableProviders.find(p => p.key === currentProvider);
    backendUrl = providerData ? providerData.url : null;
  }
  
  const dataVendors = {
    core_stock_apis: document.getElementById("vendor-core").value,
    technical_indicators: document.getElementById("vendor-technical").value,
    fundamental_data: document.getElementById("vendor-fundamental").value,
    news_data: document.getElementById("vendor-news").value,
  };
  
  const payload = {
    ticker,
    date,
    analysts,
    provider: currentProvider,
    quick_model: quickModel,
    deep_model: deepModel,
    research_depth: depth,
    output_language: lang,
    checkpoint,
    clear_checkpoints: clearChecks,
    backend_url: backendUrl,
    google_thinking_level: googleThinking,
    openai_reasoning_effort: openaiEffort,
    anthropic_effort: anthropicEffort,
    data_vendors: dataVendors,
  };
  
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    
    if (res.ok) {
      resetUiForNewRun();
      connectEventStream();
      setUiRunning(true);
      showToast(`Analysis started for ${ticker}`);
    } else {
      const err = await res.json();
      showToast(err.error || "Failed to start analysis", "error");
    }
  } catch (e) {
    showToast("Network error starting analysis", "error");
  }
}

async function stopAnalysis() {
  // The v2 backend supports cooperative cancellation via /api/stop. The
  // running graph finishes its current node, then aborts cleanly.
  try {
    const res = await fetch("/api/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (data.ok) {
      showToast("Stopping — finishing current step then aborting...", "info");
    } else {
      showToast("Nothing running to stop.", "info");
    }
  } catch (e) {
    showToast("Failed to send stop signal: " + e.message, "error");
  }
}

function setUiRunning(isRunning) {
  const runBtn = document.getElementById("run-btn");
  const stopBtn = document.getElementById("stop-btn");
  const globalStatus = document.getElementById("global-status");
  const dot = globalStatus.querySelector(".status-dot");
  const txt = globalStatus.querySelector(".status-text");
  
  if (isRunning) {
    runBtn.style.display = "none";
    dot.className = "status-dot running";
    txt.textContent = "RUNNING";
    startTime = Date.now();
    timerInterval = setInterval(updateTimer, 1000);
  } else {
    runBtn.style.display = "inline-flex";
    stopBtn.style.display = "none";
    dot.className = "status-dot done";
    txt.textContent = "DONE";
    clearInterval(timerInterval);
    if (evtSource) {
      evtSource.close();
      evtSource = null;
    }
  }
}

function updateTimer() {
  if (!startTime) return;
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(elapsed / 60).toString().padStart(2, "0");
  const s = (elapsed % 60).toString().padStart(2, "0");
  document.getElementById("stat-elapsed").textContent = `\u23f1 ${m}:${s}`;
}

function clearFeed() {
  const feed = document.getElementById("message-feed");
  feed.innerHTML = `
    <div class="feed-placeholder">
      <div class="feed-icon">\uD83E\uDD16</div>
      <p>Analysis output will appear here when you run an analysis.</p>
    </div>
  `;
}

function resetUiForNewRun() {
  clearFeed();
  document.getElementById("stat-agents").textContent = "AGENTS 0/0";
  document.getElementById("stat-reports").textContent = "REPORTS 0/0";
  document.getElementById("stat-elapsed").textContent = "\u23f1 00:00";
  document.getElementById("stat-llm").textContent = "LLM 0";
  document.getElementById("stat-tools").textContent = "TOOLS 0";
  document.getElementById("stat-tokens").textContent = "TOKENS 0\u2191 0\u2193";
  document.getElementById("report-preview-card").style.display = "none";
  currentReportSections = {};
  analysisStats = { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 };
  
  document.querySelectorAll(".agent-chip").forEach(chip => {
    chip.className = "agent-chip pending";
  });
}

// ─── Event Stream Handling ───
function connectEventStream() {
  if (evtSource) evtSource.close();
  
  evtSource = new EventSource("/api/stream");
  
  evtSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    
    if (data.type === "ping") return;
    
    if (data.type === "status") {
      appendFeedEntry("status", data.message);
    } else if (data.type === "agents_init") {
      updateAgentsUI(data.agents);
    } else if (data.type === "agents_update") {
      updateAgentsUI(data.agents);
    } else if (data.type === "agent_update") {
      updateAgentsUI(data.agents);
      if (data.status === "completed") {
        appendFeedEntry("agent", `${data.agent} completed.`);
      } else if (data.status === "error") {
        appendFeedEntry("error", `${data.agent} encountered an error.`);
      }
    } else if (data.type === "tool_call") {
      appendFeedEntry("tool", `${data.tool}`, data.node);
    } else if (data.type === "message") {
      appendFeedEntry("message", data.content, data.node);
    } else if (data.type === "chunk") {
      handleChunkData(data.state);
    } else if (data.type === "stats") {
      updateStats(data.stats);
    } else if (data.type === "final_report") {
      appendFeedEntry("done", "Full analysis complete. All reports generated.");
      setUiRunning(false);
      showToast("Analysis complete!", "success");
    } else if (data.type === "error") {
      appendFeedEntry("error", data.message);
      setUiRunning(false);
      showToast("Analysis encountered an error", "error");
    }
  };
  
  evtSource.onerror = (e) => {
    console.error("SSE Error", e);
  };
}

function appendFeedEntry(type, text, source = null) {
  const feed = document.getElementById("message-feed");
  const placeholder = feed.querySelector(".feed-placeholder");
  if (placeholder) placeholder.remove();
  
  const d = new Date();
  const timeStr = d.toLocaleTimeString([], {hour12: false});
  
  let badgeClass = type;
  let badgeText = type.toUpperCase();
  if (source) badgeText = source.replace(/_/g, " ").toUpperCase();
  
  const entry = document.createElement("div");
  entry.className = `feed-entry type-${type}`;
  entry.innerHTML = `
    <div class="feed-time">${timeStr}</div>
    <div class="feed-badge ${badgeClass}">${badgeText}</div>
    <div class="feed-text">${escapeHtml(text)}</div>
  `;
  
  feed.appendChild(entry);
  // Keep at most 200 entries for performance
  while (feed.children.length > 200) {
    feed.removeChild(feed.firstChild);
  }
  feed.scrollTop = feed.scrollHeight;
}

function updateAgentsUI(agentsDict) {
  let completed = 0;
  let total = Object.keys(agentsDict).length;
  
  for (const [name, status] of Object.entries(agentsDict)) {
    const idSafeName = name.replace(/\s+/g, "-");
    const chip = document.getElementById(`agent-${idSafeName}`);
    if (chip) {
      chip.className = `agent-chip ${status}`;
      if (status === "completed") completed++;
    }
  }
  
document.getElementById("stat-agents").textContent = "AGENTS " + completed + "/" + total;
}

function updateStats(stats) {
  if (!stats) return;
  analysisStats.llm_calls = stats.llm_calls || analysisStats.llm_calls;
  analysisStats.tool_calls = stats.tool_calls || analysisStats.tool_calls;
  analysisStats.tokens_in = stats.tokens_in || analysisStats.tokens_in;
  analysisStats.tokens_out = stats.tokens_out || analysisStats.tokens_out;
  
  document.getElementById("stat-llm").textContent = "LLM " + analysisStats.llm_calls;
  document.getElementById("stat-tools").textContent = "TOOLS " + analysisStats.tool_calls;
  const tin = analysisStats.tokens_in >= 1000 ? (analysisStats.tokens_in / 1000).toFixed(1) + "k" : analysisStats.tokens_in;
  const tout = analysisStats.tokens_out >= 1000 ? (analysisStats.tokens_out / 1000).toFixed(1) + "k" : analysisStats.tokens_out;
  document.getElementById("stat-tokens").textContent = "TOKENS " + tin + "↑ " + tout + "↓";
}

function handleChunkData(state) {
  let changed = false;
  
  const reportKeys = [
    "market_report", "sentiment_report", "news_report", "fundamentals_report",
    "investment_plan", "trader_investment_plan", "final_trade_decision"
  ];
  
  reportKeys.forEach(k => {
    if (state[k]) {
      currentReportSections[k] = state[k];
      changed = true;
    }
  });
  
  // Handle debate states - create display-friendly sections
  if (state.investment_debate_state) {
    const debate = state.investment_debate_state;
    const parts = [];
    if (typeof debate === "object") {
      if (debate.bull_history) parts.push(`### Bull Researcher\n${debate.bull_history}`);
      if (debate.bear_history) parts.push(`### Bear Researcher\n${debate.bear_history}`);
      if (debate.judge_decision) parts.push(`### Research Manager Decision\n${debate.judge_decision}`);
    }
    if (parts.length) {
      currentReportSections["investment_debate"] = parts.join("\n\n");
      changed = true;
    }
  }
  
  if (state.risk_debate_state) {
    const risk = state.risk_debate_state;
    const parts = [];
    if (typeof risk === "object") {
      if (risk.aggressive_history) parts.push(`### Aggressive Analyst\n${risk.aggressive_history}`);
      if (risk.conservative_history) parts.push(`### Conservative Analyst\n${risk.conservative_history}`);
      if (risk.neutral_history) parts.push(`### Neutral Analyst\n${risk.neutral_history}`);
      if (risk.judge_decision) parts.push(`### Portfolio Manager Decision\n${risk.judge_decision}`);
    }
    if (parts.length) {
      currentReportSections["risk_debate"] = parts.join("\n\n");
      changed = true;
    }
  }
  
  if (changed) {
    document.getElementById("stat-reports").textContent = "REPORTS " + Object.keys(currentReportSections).length;
    renderReportPreview();
  }
}

function renderReportPreview() {
  const card = document.getElementById("report-preview-card");
  card.style.display = "block";
  
  const tabsContainer = document.getElementById("report-tabs");
  tabsContainer.innerHTML = "";
  
  const contentContainer = document.getElementById("report-content");
  
  const NAMES = {
    "market_report": "Market",
    "sentiment_report": "Sentiment",
    "news_report": "News",
    "fundamentals_report": "Fundamentals",
    "investment_plan": "Research",
    "investment_debate": "Debate",
    "trader_investment_plan": "Trader",
    "risk_debate": "Risk Debate",
    "final_trade_decision": "Portfolio Mgr"
  };
  
  for (const key of Object.keys(currentReportSections)) {
    const btn = document.createElement("button");
    btn.className = "report-tab";
    btn.textContent = NAMES[key] || key;
    btn.onclick = () => {
      document.querySelectorAll(".report-tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      contentContainer.innerHTML = marked.parse(currentReportSections[key]);
    };
    tabsContainer.appendChild(btn);
  }
  
  const keys = Object.keys(currentReportSections);
  if (keys.length > 0) {
    const latestKey = keys[keys.length - 1];
    const targetBtn = Array.from(tabsContainer.children).find(b => b.textContent === (NAMES[latestKey] || latestKey));
    if (targetBtn) targetBtn.click();
  }
}

// ─── Reports & History ───
async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    const container = document.getElementById("history-content");
    if (data.content) {
      container.innerHTML = marked.parse(data.content);
    } else {
      container.innerHTML = `<div class="feed-placeholder"><p>No history found yet. Run an analysis to start building memory.</p></div>`;
    }
  } catch (e) {
    showToast("Failed to load history", "error");
  }
}

async function loadReportsList() {
  try {
    const res = await fetch("/api/reports");
    const data = await res.json();
    const list = document.getElementById("reports-list");
    
    if (!data.reports || data.reports.length === 0) {
      list.innerHTML = `<div class="feed-placeholder"><p>No saved reports found.</p></div>`;
      return;
    }
    
    list.innerHTML = "";
    data.reports.forEach((r, idx) => {
      const item = document.createElement("div");
      item.className = "report-item";
      item.innerHTML = `
        <div class="report-item-ticker">${r.ticker}</div>
        <div class="report-item-date">${r.date}</div>
      `;
      item.onclick = () => {
        document.querySelectorAll(".report-item").forEach(i => i.classList.remove("active"));
        item.classList.add("active");
        readReportFile(r.path, `${r.ticker} (${r.date})`);
      };
      list.appendChild(item);
      
      if (idx === 0) item.click();
    });
  } catch (e) {
    console.error(e);
  }
}

async function readReportFile(path, title) {
  try {
    const res = await fetch(`/api/reports/read?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    
    document.getElementById("report-reader-title").textContent = title;
    
    if (res.ok) {
      const contentEl = document.getElementById("report-reader");
      contentEl.innerHTML = marked.parse(data.content);
      // Add download button
      const existingBtn = document.getElementById("download-report-btn");
      if (existingBtn) existingBtn.remove();
      const dlBtn = document.createElement("button");
      dlBtn.id = "download-report-btn";
      dlBtn.className = "btn btn-ghost btn-sm";
      dlBtn.innerHTML = "\uD83D\uDCC4 Download";
      dlBtn.style.marginLeft = "0.5rem";
      dlBtn.onclick = () => {
        window.open(`/api/reports/download?path=${encodeURIComponent(path)}`, "_blank");
      };
      document.getElementById("report-reader-title").parentElement.appendChild(dlBtn);
    } else {
      document.getElementById("report-reader").innerHTML = `<p style="color:var(--danger)">Error: ${data.error}</p>`;
    }
  } catch (e) {
    showToast("Failed to read report", "error");
  }
}

// ─── Utilities ───
function escapeHtml(unsafe) {
    return (unsafe||"").toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

function closeModal() {
  document.getElementById("modal-overlay").style.display = "none";
}