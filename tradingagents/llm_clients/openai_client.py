import logging
import os
import random
import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .api_key_env import get_api_key_env
from .base_client import BaseLLMClient, normalize_content
from .capabilities import get_capabilities
from .validators import validate_model


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with normalized content output and capability-aware binding.

    The Responses API returns content as a list of typed blocks
    (reasoning, text, etc.). ``invoke`` normalizes to string for
    consistent downstream handling.

    ``with_structured_output`` consults the per-model capability table
    (``capabilities.get_capabilities``) to pick the method and to decide
    whether ``tool_choice`` may be sent. Models that reject ``tool_choice``
    (e.g. DeepSeek V4 and reasoner — per their official tool-calling
    guide) still bind the schema as a tool, but no ``tool_choice``
    parameter is sent.

    Provider-specific quirks beyond structured-output (e.g. DeepSeek's
    reasoning_content roundtrip) live in subclasses so this base class
    stays small.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def with_structured_output(self, schema, *, method=None, **kwargs):
        caps = get_capabilities(self.model_name)
        if caps.preferred_structured_method == "none":
            raise NotImplementedError(
                f"{self.model_name} has no structured-output method available; "
                f"agent factories will fall back to free-text generation."
            )
        method = method or caps.preferred_structured_method
        # When the model rejects tool_choice, suppress langchain's hardcoded
        # value. The schema is still bound as a tool — exactly what
        # DeepSeek's official tool-calling examples do.
        if method == "function_calling" and not caps.supports_tool_choice:
            kwargs.setdefault("tool_choice", None)
        return super().with_structured_output(schema, method=method, **kwargs)


def _input_to_messages(input_: Any) -> list:
    """Normalise a langchain LLM input to a list of message objects.

    Accepts a list of messages, a ``ChatPromptValue`` (from a
    ChatPromptTemplate), or anything else (treated as no messages).
    Used by providers that need to walk the outgoing message history;
    in particular DeepSeek thinking-mode propagation must work for
    both bare-list invocations and ChatPromptTemplate-driven ones, so
    treating only ``list`` here would silently skip half the call sites.
    """
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    return []


class DeepSeekChatOpenAI(NormalizedChatOpenAI):
    """DeepSeek-specific overrides on top of the OpenAI-compatible client.

    Thinking-mode round-trip is the only DeepSeek-specific behavior that
    stays here. When DeepSeek's thinking models return a response with
    ``reasoning_content``, that field must be echoed back as part of the
    assistant message on the next turn or the API fails with HTTP 400.
    ``_create_chat_result`` captures it on receive and
    ``_get_request_payload`` re-attaches it on send.

    Tool-choice handling for V4 and reasoner — those models reject the
    ``tool_choice`` parameter — is handled by the capability dispatch in
    ``NormalizedChatOpenAI.with_structured_output``, not here.
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        outgoing = payload.get("messages", [])
        for message_dict, message in zip(outgoing, _input_to_messages(input_)):
            if not isinstance(message, AIMessage):
                continue
            reasoning = message.additional_kwargs.get("reasoning_content")
            if reasoning is not None:
                message_dict["reasoning_content"] = reasoning
        return payload

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for generation, choice in zip(
            chat_result.generations, response_dict.get("choices", [])
        ):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return chat_result


_logger = logging.getLogger(__name__)

# HTTP-ish status codes embedded in the response body that we treat as
# transient — worth retrying with backoff. OpenRouter returns these in
# the body alongside HTTP 200, so langchain's built-in retry path doesn't
# see them as failure and never retries on its own.
_TRANSIENT_CODES = frozenset({408, 429, 500, 502, 503, 504, 524})


def _is_transient_openrouter_error(exc: Exception) -> bool:
    """Return True if ``exc`` looks like a retryable OpenRouter/downstream-
    provider hiccup. OpenRouter wraps downstream errors as::

        ValueError({'message': 'Provider returned error', 'code': 502})

    The ``code`` field carries the downstream HTTP status. We retry on the
    usual transient set (502/503/504, 429 rate-limit, 500, 408 timeout).
    """
    if not exc.args:
        return False
    payload = exc.args[0]
    if isinstance(payload, dict):
        code = payload.get("code")
        try:
            return int(code) in _TRANSIENT_CODES
        except (TypeError, ValueError):
            return False
    if isinstance(payload, str):
        # Older shapes string-formatted the dict — match the code substring.
        return any(f"'code': {c}" in payload or f'"code": {c}' in payload
                   for c in _TRANSIENT_CODES)
    return False


def _retry_on_transient(fn, *, attempts: int = 4, base_delay: float = 1.5):
    """Run ``fn()`` up to ``attempts`` times, retrying on transient
    OpenRouter / downstream-provider errors with exponential backoff +
    jitter. Re-raises the last exception if every attempt fails.

    Why this and not langchain's built-in ``max_retries``: that retry
    path only triggers on HTTP-level errors from the OpenAI SDK. The
    failures we see come back as HTTP 200 with the error embedded in
    the JSON body, so they bypass that path entirely.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — broad catch on purpose
            if not _is_transient_openrouter_error(exc) or i == attempts - 1:
                raise
            last_exc = exc
            delay = base_delay * (2 ** i) + random.uniform(0, 0.5)
            _logger.warning(
                "transient OpenRouter/provider error (%s) — retrying in %.1fs (attempt %d/%d)",
                exc, delay, i + 1, attempts,
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc  # pragma: no cover — defensive


def _coerce_content_to_string(content: Any) -> str:
    """Collapse langchain's multimodal content-block list into a plain string.

    langchain's ChatPromptTemplate often emits ``content`` as a list of
    typed blocks (``[{"type":"text","text":"…"}, …]``) — fine for OpenAI but
    rejected by Z.AI / GLM with HTTP 400 ``1214 The messages parameter is
    illegal``. We flatten the list to its concatenated text payload, which
    is what those providers expect on every role.
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Common shapes: {"type":"text","text":"…"} and
                # {"type":"input_text","text":"…"}; fall back to ``text``
                # or ``content`` whatever is present.
                txt = block.get("text") or block.get("content")
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)
    return str(content)


def _sanitize_messages_for_strict_providers(messages: list[dict]) -> None:
    """In-place fix for downstream providers that reject the shapes
    langchain emits by default.

    Z.AI's GLM endpoint (reached directly via ``glm``/``glm-cn`` or proxied
    via OpenRouter) returns ``1214 The messages parameter is illegal`` for
    several variations:

    1. ``content`` is a list of typed blocks (multimodal/text-blocks shape)
       instead of a plain string — emitted by ChatPromptTemplate.
    2. ``content`` is an empty string on an assistant turn that carries
       ``tool_calls`` — emitted on every tool-call hop.
    3. ``name`` field present on roles that don't expect it (system/user)
       or on ``tool`` messages alongside ``tool_call_id``.
    4. ``content`` is ``None``.

    The compatible-everywhere normalization:
    - Coerce content to a string on every message.
    - On assistant turns with ``tool_calls`` and empty content, drop the
      ``content`` key (Z.AI accepts a missing key, rejects an empty string).
    - On every other empty-content message, replace with a single space.
    - Strip ``name`` from system/user/tool roles.
    """
    for msg in messages:
        role = msg.get("role")
        # 1) Coerce content to a string regardless of role.
        if "content" in msg:
            msg["content"] = _coerce_content_to_string(msg["content"])
        # 2) Empty-content rules.
        if role == "assistant" and msg.get("tool_calls"):
            if msg.get("content", "") == "":
                msg.pop("content", None)
        elif msg.get("content", "") == "":
            msg["content"] = " "
        # 3) Strip ``name`` where it causes trouble.
        if role in ("system", "user", "tool") and "name" in msg:
            msg.pop("name", None)


def _squash_system_into_human(messages: list) -> list:
    """Fold any SystemMessage(s) into the first HumanMessage that follows.

    Z.AI / GLM (whether reached directly via the ``glm``/``glm-cn`` route
    or proxied through OpenRouter) rejects conversations that contain a
    ``system`` role with ``1214 The messages parameter is illegal``. The
    fix is to prepend the system text to the first user turn and drop
    the system message entirely — semantically identical, accepted
    everywhere.

    Also drops messages with empty content unless they carry tool_calls
    (Z.AI rejects empty content there too).
    """
    cleaned: list = []
    system_text = ""

    for m in messages:
        content = m.content.strip() if isinstance(m.content, str) else m.content
        if not content and not getattr(m, "tool_calls", None):
            continue

        if isinstance(m, SystemMessage):
            if isinstance(content, str):
                system_text += content + "\n\n"
            elif isinstance(content, list):
                # Flatten content blocks ({type:text, text:...}) to a string.
                for block in content:
                    if isinstance(block, str):
                        system_text += block + "\n\n"
                    elif isinstance(block, dict):
                        t = block.get("text") or block.get("content")
                        if isinstance(t, str):
                            system_text += t + "\n\n"
            continue

        if isinstance(m, HumanMessage) and system_text:
            if isinstance(m.content, str):
                m = HumanMessage(content=system_text + m.content)
            elif isinstance(m.content, list):
                m = HumanMessage(content=[{"type": "text", "text": system_text}] + m.content)
            else:
                m = HumanMessage(content=system_text + str(m.content))
            system_text = ""

        cleaned.append(m)

    # If we accumulated system text but never saw a human message after it,
    # synthesize one so the request has a valid user turn.
    if system_text:
        cleaned.insert(0, HumanMessage(content=system_text))

    return cleaned


class _OpenRouterTransientRetryMixin:
    """Adds OpenRouter-aware transient-error retry to ``invoke``.

    OpenRouter returns HTTP 200 with ``{"error": {...}, "code": 5xx}`` in
    the body when its downstream provider (Z.AI, Anthropic, Google, …)
    hiccups. langchain raises that as a ``ValueError`` from inside
    ``_create_chat_result`` — which is not caught by its own
    ``max_retries`` path. We catch it here and retry with exponential
    backoff before letting the agent loop see the failure.
    """

    def invoke(self, input, config=None, **kwargs):
        return _retry_on_transient(
            lambda: super(_OpenRouterTransientRetryMixin, self).invoke(input, config, **kwargs)
        )


class ZhipuChatOpenAI(_OpenRouterTransientRetryMixin, NormalizedChatOpenAI):
    """Z.AI / GLM-compatible payload shaping.

    Applies in two cases:
      1. Direct ``glm``/``glm-cn`` provider route.
      2. OpenRouter route when the model id contains ``glm`` (which
         OpenRouter forwards to Z.AI's backend).

    Steps applied to every outgoing request:
      * Squash SystemMessage(s) into the first HumanMessage (Z.AI rejects
        the ``system`` role outright on this route).
      * Strip empty-content messages that don't carry tool_calls.
      * Run the generic sanitizer (flatten multimodal content lists,
        drop empty content on tool-call assistant turns, strip stray
        ``name`` fields on system/user/tool roles).
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = _squash_system_into_human(_input_to_messages(input_))
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        _sanitize_messages_for_strict_providers(payload.get("messages", []))
        return payload


class OpenRouterChatOpenAI(_OpenRouterTransientRetryMixin, NormalizedChatOpenAI):
    """OpenRouter-specific overrides.

    OpenRouter forwards to dozens of downstream providers and most of
    them tolerate langchain's default payload shape. Apply only the
    light-touch sanitizer (flatten content blocks, drop stray ``name``
    fields, drop empty-content tool-call turns) — when the model is a
    Z.AI/GLM route we instead dispatch to ``ZhipuChatOpenAI`` at
    construction time, which does the full system-message squash.
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        _sanitize_messages_for_strict_providers(payload.get("messages", []))
        return payload


class MinimaxChatOpenAI(NormalizedChatOpenAI):
    """MiniMax-specific overrides on top of the OpenAI-compatible client.

    M2.x reasoning models embed ``<think>...</think>`` blocks directly in
    ``message.content`` by default, which would pollute saved reports.
    Per platform.minimax.io/docs/api-reference/text-openai-api, setting
    ``reasoning_split=True`` in the request body redirects the thinking
    block into ``reasoning_details`` so ``content`` stays clean.

    Tool-choice handling for M2.x — those models accept only the string
    enum ``{"none", "auto"}`` and reject langchain's function-spec dict —
    is handled by the capability dispatch in
    ``NormalizedChatOpenAI.with_structured_output``, not here.
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload.setdefault("reasoning_split", True)
        return payload


# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# Provider base URLs. API-key env vars live in api_key_env.PROVIDER_API_KEY_ENV
# (one canonical mapping consulted by both this client and the CLI's
# interactive key-prompt). Dual-region providers (qwen/glm/minimax) keep
# separate endpoints because international and China accounts cannot share
# credentials (#758).
_PROVIDER_BASE_URL = {
    "xai":        "https://api.x.ai/v1",
    "deepseek":   "https://api.deepseek.com",
    "qwen":       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "qwen-cn":    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm":        "https://api.z.ai/api/paas/v4/",
    "glm-cn":     "https://open.bigmodel.cn/api/paas/v4/",
    "minimax":    "https://api.minimax.io/v1",
    "minimax-cn": "https://api.minimaxi.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama":     "http://localhost:11434/v1",
}


def _resolve_provider_base_url(provider: str) -> Optional[str]:
    """Default base URL for ``provider``, with env-var overrides where defined.

    Currently only Ollama supports an env-var override (``OLLAMA_BASE_URL``),
    matching the convention in the broader Ollama tooling ecosystem so users
    can point at a remote ollama-serve without editing code. The check is
    call-time, not import-time, so tests that monkeypatch the env after
    import behave correctly.
    """
    if provider == "ollama":
        env_url = os.environ.get("OLLAMA_BASE_URL")
        if env_url:
            return env_url
    return _PROVIDER_BASE_URL.get(provider)


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers.

    For native OpenAI models, uses the Responses API (/v1/responses) which
    supports reasoning_effort with function tools across all model families
    (GPT-4.1, GPT-5). Third-party compatible providers (xAI, OpenRouter,
    Ollama) use standard Chat Completions.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        # Provider-specific base URL and auth. An explicit base_url on the
        # client (e.g. a corporate proxy) takes precedence over the
        # provider default so users can route through their own gateway.
        if self.provider in _PROVIDER_BASE_URL:
            llm_kwargs["base_url"] = self.base_url or _resolve_provider_base_url(self.provider)
            api_key_env = get_api_key_env(self.provider)
            if api_key_env:
                api_key = os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
                else:
                    raise ValueError(
                        f"API key for provider '{self.provider}' is not set. "
                        f"Please set the {api_key_env} environment variable "
                        f"(e.g. add {api_key_env}=your_key to your .env file)."
                    )
            else:
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # Forward user-provided kwargs
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Native OpenAI: use Responses API for consistent behavior across
        # all model families. Third-party providers use Chat Completions.
        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        # Provider-specific quirks live in their own subclasses so the
        # base NormalizedChatOpenAI stays free of provider branches.
        # When OpenRouter is routing to a Z.AI/GLM model, the downstream
        # provider's strictness kicks in — switch to the system-squash
        # subclass instead of the lighter sanitizer-only one.
        is_glm_via_openrouter = (
            self.provider == "openrouter" and "glm" in (self.model or "").lower()
        )

        if self.provider == "deepseek":
            chat_cls = DeepSeekChatOpenAI
        elif self.provider in ("minimax", "minimax-cn"):
            chat_cls = MinimaxChatOpenAI
        elif self.provider in ("glm", "glm-cn") or is_glm_via_openrouter:
            chat_cls = ZhipuChatOpenAI
        elif self.provider == "openrouter":
            # OpenRouter recommends app-attribution headers; harmless if absent.
            referer = os.environ.get("OPENROUTER_HTTP_REFERER") or "https://github.com/TradingAgents"
            title   = os.environ.get("OPENROUTER_APP_TITLE")    or "TradingAgents"
            existing = llm_kwargs.get("default_headers") or {}
            llm_kwargs["default_headers"] = {
                "HTTP-Referer": referer,
                "X-Title":      title,
                **existing,
            }
            chat_cls = OpenRouterChatOpenAI
        else:
            chat_cls = NormalizedChatOpenAI
        return chat_cls(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
