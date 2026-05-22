"""Provider catalog — driven by upstream's api_key_env.PROVIDER_API_KEY_ENV.

Single source of truth for:
  * Which providers exist
  * Which env var holds each provider's key
  * How to label them for humans
  * How to test a key (endpoint + auth header pattern)

When upstream adds a provider to ``api_key_env.PROVIDER_API_KEY_ENV``, the GUI
picks it up automatically — no edits here required for the basic listing.
The TEST_RECIPES dict below still needs an entry for key-validation testing,
but a missing recipe gracefully falls back to "key saved but not verified".
"""

from __future__ import annotations

from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV


# Human labels for the provider dropdown. Anything not listed falls back to
# the provider id itself.
PROVIDER_LABELS = {
    "openai":     "OpenAI",
    "anthropic":  "Anthropic (Claude)",
    "google":     "Google (Gemini)",
    "azure":      "Azure OpenAI",
    "xai":        "xAI (Grok)",
    "deepseek":   "DeepSeek",
    "qwen":       "Qwen (Alibaba — International)",
    "qwen-cn":    "Qwen (Alibaba — China)",
    "glm":        "GLM / Z.AI (International)",
    "glm-cn":     "GLM / BigModel (China)",
    "minimax":    "MiniMax (International)",
    "minimax-cn": "MiniMax (China)",
    "openrouter": "OpenRouter",
    "ollama":     "Ollama (Local)",
}


# Default backend URLs surfaced in the UI as a hint. None = framework picks.
PROVIDER_DEFAULT_URLS = {
    "openai":     "https://api.openai.com/v1",
    "anthropic":  "https://api.anthropic.com",
    "google":     None,
    "xai":        "https://api.x.ai/v1",
    "deepseek":   "https://api.deepseek.com",
    "qwen":       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "qwen-cn":    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm":        "https://api.z.ai/api/paas/v4/",
    "glm-cn":     "https://open.bigmodel.cn/api/paas/v4/",
    "minimax":    "https://api.minimax.io/v1",
    "minimax-cn": "https://api.minimaxi.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "azure":      None,
    "ollama":     "http://localhost:11434/v1",
}


# Free-form notes shown beneath the model dropdown.
PROVIDER_NOTES = {
    "openrouter": "Pick any model ID from openrouter.ai (e.g. anthropic/claude-sonnet-4.6).",
    "azure":      "Use your Azure deployment name as the model ID.",
    "ollama":     "Models you've pulled locally via `ollama pull` appear here.",
}


# How to validate each provider's key. Each recipe is a dict:
#   url:        the HTTPS endpoint to hit (GET unless body provided)
#   header:     dict template for auth (use {key} placeholder)
#   query_key:  if set, the API key is passed as a query string param instead
#   body:       optional JSON body; if set, a POST is sent
#
# An entry of None means "save without testing" — used for providers that
# either don't authenticate (ollama) or have no cheap probe endpoint.
TEST_RECIPES: dict[str, dict | None] = {
    "openai":     {"url": "https://api.openai.com/v1/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "anthropic":  {"url": "https://api.anthropic.com/v1/messages",
                   "header": {"x-api-key": "{key}",
                              "anthropic-version": "2023-06-01",
                              "content-type": "application/json"},
                   "body": {"model": "claude-haiku-4-5",
                            "max_tokens": 1,
                            "messages": [{"role": "user", "content": "hi"}]}},
    "google":     {"url": "https://generativelanguage.googleapis.com/v1beta/models",
                   "query_key": "key"},
    "xai":        {"url": "https://api.x.ai/v1/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "deepseek":   {"url": "https://api.deepseek.com/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "qwen":       {"url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "qwen-cn":    {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "glm":        {"url": "https://api.z.ai/api/paas/v4/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "glm-cn":     {"url": "https://open.bigmodel.cn/api/paas/v4/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "minimax":    {"url": "https://api.minimax.io/v1/models",
                   "header": {"Authorization": "Bearer {key}"}},
    "minimax-cn": {"url": "https://api.minimaxi.com/v1/models",
                    "header": {"Authorization": "Bearer {key}"}},
    "openrouter": {"url": "https://openrouter.ai/api/v1/auth/key",
                   "header": {"Authorization": "Bearer {key}"}},
    "azure":      None,   # endpoint + deployment vary too much per user
    "ollama":     None,   # local, no auth
}


def provider_list() -> list[dict]:
    """Return the canonical provider list for the GUI, ordered by label.

    The order puts cloud / well-known providers first (so 'openai' is at the
    top), with niche / local providers (ollama) trailing.
    """
    preferred_order = [
        "openai", "anthropic", "google", "xai", "deepseek",
        "openrouter", "qwen", "qwen-cn", "glm", "glm-cn",
        "minimax", "minimax-cn", "azure", "ollama",
    ]
    seen = set()
    ordered = []
    for pid in preferred_order:
        if pid in PROVIDER_API_KEY_ENV:
            ordered.append(pid); seen.add(pid)
    # Append anything upstream added that we don't know about.
    for pid in PROVIDER_API_KEY_ENV:
        if pid not in seen:
            ordered.append(pid)

    out = []
    for pid in ordered:
        env_var = PROVIDER_API_KEY_ENV[pid]
        out.append({
            "key":              pid,
            "label":            PROVIDER_LABELS.get(pid, pid),
            "url":              PROVIDER_DEFAULT_URLS.get(pid),
            "api_key_env":      env_var,
            "requires_api_key": env_var is not None,
            "notes":            PROVIDER_NOTES.get(pid),
            "testable":         TEST_RECIPES.get(pid) is not None,
        })
    return out


def env_keys_for_ui() -> list[str]:
    """The set of env-var rows to surface in the API Keys tab.

    Every provider env var, plus a few useful extras (data vendor keys,
    endpoints, etc.). De-duplicated, stable order.
    """
    keys: list[str] = []
    for env_var in PROVIDER_API_KEY_ENV.values():
        if env_var:
            keys.append(env_var)
    # Optional extras
    extras = [
        "OPENAI_BASE_URL",
        "OLLAMA_BASE_URL",
        "ALPHA_VANTAGE_API_KEY",
        "FINNHUB_API_KEY",
        # Azure has multiple fields
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        "TRADINGAGENTS_RESULTS_DIR",
    ]
    for e in extras:
        if e not in keys:
            keys.append(e)
    return keys
