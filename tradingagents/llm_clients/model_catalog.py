"""Shared model catalog for CLI selections and validation."""

from __future__ import annotations

from typing import Dict, List, Tuple

ModelOption = Tuple[str, str]
ProviderModeOptions = Dict[str, Dict[str, List[ModelOption]]]


# Shared model list for GLM via Z.AI (international) and BigModel (China).
# Source: docs.z.ai (GLM Coding Plan supported models + LLM guides).
# All GLM 4.7+ entries support thinking mode via thinking={"type":"enabled"}.
_GLM_MODELS: Dict[str, List[ModelOption]] = {
    "quick": [
        ("GLM-5.3-Flash - Fast, cost-efficient, 1M ctx", "glm-5.3-flash"),
        ("GLM-5-Turbo - Fast, switchable thinking modes", "glm-5-turbo"),
        ("GLM-4.7 - Previous-gen flagship", "glm-4.7"),
        ("GLM-4.5-Air - Lightweight, cost-efficient", "glm-4.5-air"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("GLM-5.3 - Latest flagship, 1M ctx", "glm-5.3"),
        ("GLM-5.2 - 744B, 1M ctx", "glm-5.2"),
        ("GLM-5.1 - Flagship, 204K ctx", "glm-5.1"),
        ("GLM-5 - Flagship, 204K ctx", "glm-5"),
        ("GLM-4.7 - Previous-gen flagship", "glm-4.7"),
        ("Custom model ID", "custom"),
    ],
}


# Shared model list for Qwen's global (dashscope-intl) and CN (dashscope) endpoints.
# Source: modelstudio.console.alibabacloud.com (Featured Models — Flagship + Cost-optimized).
#
# Only versioned IDs are exposed in the dropdown. The version-less aliases
# (qwen-plus, qwen-flash) are documented by Alibaba as auto-upgrading
# pointers ("backbone, latest, and snapshot ... have been upgraded to the
# Qwen3 series"), which means their behavior shifts when Alibaba rotates
# the backing model. Users who want a specific generation pick it
# explicitly; users who really want auto-latest can enter the alias via
# "Custom model ID".
_QWEN_MODELS: Dict[str, List[ModelOption]] = {
    "quick": [
        ("Qwen 3.8 Flash - Latest fast model, 1M ctx", "qwen3.8-flash"),
        ("Qwen 3.6 Flash - Fast, agentic coding + vision-language", "qwen3.6-flash"),
        ("Qwen 3.5 Flash - Previous-gen fast", "qwen3.5-flash"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("Qwen 3.8 Max - Latest flagship", "qwen3.8-max"),
        ("Qwen 3.8 Flash - Fast alternative, 1M ctx", "qwen3.8-flash"),
        ("Qwen 3.6 Plus - Flagship vision-language, agentic coding SOTA", "qwen3.6-plus"),
        ("Qwen 3.5 Plus - Previous-gen flagship", "qwen3.5-plus"),
        ("Qwen 3 Max - Specialized for agent programming + tool use", "qwen3-max"),
        ("Custom model ID", "custom"),
    ],
}


# Shared model list for MiniMax's global and CN endpoints (same IDs).
# Full official lineup per platform.minimax.io/docs/api-reference/text-openai-api.
# All M2.x models share a 204,800-token context window.
_MINIMAX_MODELS: Dict[str, List[ModelOption]] = {
    "quick": [
        ("MiniMax-M3 - Latest, 1M ctx, native multimodal", "MiniMax-M3"),
        ("MiniMax-M2.7-highspeed - Faster M2.7, 204K ctx, ~100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5-highspeed - Previous-gen highspeed, 204K ctx", "MiniMax-M2.5-highspeed"),
        ("MiniMax-M2.1-highspeed - M2.1 highspeed, 204K ctx", "MiniMax-M2.1-highspeed"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("MiniMax-M3 - Latest flagship, 1M ctx, multimodal coding/agent", "MiniMax-M3"),
        ("MiniMax-M2.7 - Previous flagship, 204K ctx", "MiniMax-M2.7"),
        ("MiniMax-M2.7-highspeed - Same quality as M2.7, ~100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5 - Previous-gen flagship, 204K ctx", "MiniMax-M2.5"),
        ("MiniMax-M2.1 - Earlier M2 line, 204K ctx", "MiniMax-M2.1"),
        ("MiniMax-M2 - Base M2, 204K ctx", "MiniMax-M2"),
        ("Custom model ID", "custom"),
    ],
}


MODEL_OPTIONS: ProviderModeOptions = {
    "openai": {
        "quick": [
            ("GPT-6 Luna - Fast, high-volume and cost-efficient", "gpt-6-luna"),
            ("GPT-5.6 Luna - Previous-gen fast tier", "gpt-5.6-luna"),
            ("GPT-5.6 Terra - Balances intelligence and cost", "gpt-5.6-terra"),
            ("GPT-5.4 Mini - Fast, strong coding and tool use", "gpt-5.4-mini"),
            ("GPT-5.4 Nano - Cheapest, high-volume tasks", "gpt-5.4-nano"),
        ],
        "deep": [
            ("GPT-6 Sol - Complex reasoning and analysis", "gpt-6-sol"),
            ("GPT-6 Astra - Hardest multi-step reasoning", "gpt-6-astra"),
            ("GPT-5.6 - Previous-gen reasoning (Sol)", "gpt-5.6"),
            ("GPT-5.5 - Earlier frontier, 1M context", "gpt-5.5"),
            ("GPT-5.4 - Previous-gen frontier, 1M context, cost-effective", "gpt-5.4"),
            ("GPT-5.5 Pro - Most capable, expensive ($30/$180 per 1M tokens)", "gpt-5.5-pro"),
        ],
    },
    "anthropic": {
        "quick": [
            ("Claude Sonnet 5 - Best speed and intelligence balance", "claude-sonnet-5"),
            ("Claude Sonnet 4.6 - Previous-gen balance of speed and intelligence", "claude-sonnet-4-6"),
            ("Claude Haiku 4.5 - Fastest with near-frontier intelligence", "claude-haiku-4-5"),
        ],
        "deep": [
            ("Claude Opus 5.5 - Frontier agentic and enterprise work", "claude-opus-5-5"),
            ("Claude Fable 5.1 - Most capable, demanding long-horizon reasoning", "claude-fable-5-1"),
            ("Claude Sonnet 5 - Near-frontier intelligence at Sonnet cost", "claude-sonnet-5"),
            ("Claude Opus 4.7 - Previous frontier, long-running agents and coding", "claude-opus-4-7"),
            ("Claude Opus 4.6 - Frontier intelligence, agents and coding", "claude-opus-4-6"),
        ],
    },
    "google": {
        "quick": [
            ("Gemini 3.8 Flash - Most capable Flash", "gemini-3.8-flash"),
            ("Gemini 3.5 Flash Lite - Fast and cost-efficient", "gemini-3.5-flash-lite"),
            ("Gemini 3.1 Flash Lite - Most cost-efficient", "gemini-3.1-flash-lite"),
            ("Gemini 3 Flash - Previous-gen fast (preview)", "gemini-3-flash-preview"),
        ],
        "deep": [
            ("Gemini 3.8 Flash - Most capable Flash, 1M context", "gemini-3.8-flash"),
            ("Gemini 3.1 Pro - Reasoning-first, complex workflows (preview)", "gemini-3.1-pro-preview"),
            ("Gemini 3.5 Flash - Previous Flash, strong agentic + coding", "gemini-3.5-flash"),
            ("Gemini 3 Flash - Previous-gen fast (preview)", "gemini-3-flash-preview"),
        ],
    },
    "xai": {
        "quick": [
            ("Grok 4.6 - Latest flagship, fastest, 500K ctx", "grok-4.6"),
            ("Grok Build 0.1 - Coding-specialized, 256K ctx", "grok-build-0.1"),
            ("Grok 4.20 (Non-Reasoning) - Previous-gen, speed-optimized", "grok-4.20-non-reasoning"),
        ],
        "deep": [
            ("Grok 4.6 - Latest flagship, 500K ctx", "grok-4.6"),
            ("Grok 4.5 - Previous flagship, coding and agentic", "grok-4.5"),
            ("Grok 4.3 - Older generation, 1M ctx", "grok-4.3"),
            ("Grok 4.20 (Reasoning) - Earlier frontier reasoning model", "grok-4.20-reasoning"),
        ],
    },
    "deepseek": {
        "quick": [
            ("DeepSeek Flash - V4.1 Flash, fast, 1M ctx", "deepseek-flash"),
            ("DeepSeek V4 Flash - V4 fast model", "deepseek-v4-flash"),
            ("DeepSeek V3.2", "deepseek-chat"),
            ("Custom model ID", "custom"),
        ],
        "deep": [
            ("DeepSeek V4 Pro - Flagship", "deepseek-v4-pro"),
            ("DeepSeek Flash - V4.1 Flash, fast, 1M ctx", "deepseek-flash"),
            ("DeepSeek V3.2 (thinking)", "deepseek-reasoner"),
            ("DeepSeek V3.2", "deepseek-chat"),
            ("Custom model ID", "custom"),
        ],
    },
    # Qwen: same model IDs across global (dashscope-intl) and China
    # (dashscope) endpoints, so the two provider keys share one model list.
    "qwen": _QWEN_MODELS,
    "qwen-cn": _QWEN_MODELS,
    # GLM: Z.AI (international) and BigModel (China) host the same model
    # IDs; the two provider keys share one model list.
    "glm": _GLM_MODELS,
    "glm-cn": _GLM_MODELS,
    # MiniMax: same model IDs across global (.io) and China (.com) regions,
    # so the two provider keys share one model list.
    "minimax": _MINIMAX_MODELS,
    "minimax-cn": _MINIMAX_MODELS,
    # OpenRouter: fetched dynamically. Azure: any deployed model name.
    # Ollama display labels intentionally omit a "local" marker — the
    # endpoint is now configurable via OLLAMA_BASE_URL, so the same labels
    # apply whether the user runs ollama-serve on localhost or against a
    # remote host. The actual resolved endpoint is surfaced separately by
    # cli.utils.confirm_ollama_endpoint() right after provider selection.
    # "Custom model ID" lets users pick any model they have pulled via
    # `ollama pull` beyond the three suggested defaults.
    "ollama": {
        "quick": [
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("Custom model ID", "custom"),
        ],
        "deep": [
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("Custom model ID", "custom"),
        ],
    },
}


def get_model_options(provider: str, mode: str) -> List[ModelOption]:
    """Return shared model options for a provider and selection mode."""
    return MODEL_OPTIONS[provider.lower()][mode]


# Served by the provider but no longer offered in the picker (retired from the
# menu, or deprecated aliases). Known to validation so a saved config naming one
# still runs without an unknown-model warning.
LEGACY_MODELS: Dict[str, List[str]] = {
    "openai": ["gpt-4.1", "gpt-5.2", "gpt-5.6-sol"],
    "anthropic": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-opus-5", "claude-fable-5"],
    "google": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
    "xai": ["grok-4.20", "grok-4-0709", "grok-4-fast-reasoning",
            "grok-4-fast-non-reasoning"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "qwen": ["qwen3.5-flash", "qwen3.5-plus", "qwen3-max"],
    "minimax": ["MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"],
}


def get_known_models() -> Dict[str, List[str]]:
    """Build known model names from the shared CLI catalog plus legacy IDs."""
    return {
        provider: sorted(
            {
                value
                for options in mode_options.values()
                for _, value in options
            }
            | set(LEGACY_MODELS.get(provider, []))
        )
        for provider, mode_options in MODEL_OPTIONS.items()
    }
