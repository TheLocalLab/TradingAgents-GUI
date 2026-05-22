import logging
import os
import random
import time
from typing import Any, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .api_key_env import get_api_key_env
from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

_logger = logging.getLogger(__name__)

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "max_tokens",
    "callbacks", "http_client", "http_async_client",
)

_TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    OSError,
)

_STUB_USER = "Please proceed with the analysis described above."


def _input_to_messages(input_: Any) -> list:
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    return []


def _ensure_user_turn(input_: Any) -> Any:
    """Guarantee at least one non-system message for Anthropic's API.

    Anthropic routes SystemMessage to the ``system`` parameter and
    requires at least one entry in the ``messages`` array. A
    system-only conversation (common on the first agent hop) violates
    this and returns HTTP 400 ``messages: at least one message is
    required``.

    The fix: if all messages are SystemMessage, prepend a stub
    HumanMessage so the ``messages`` array is non-empty. If the first
    non-system message is an AIMessage (e.g. from a tool-call hop),
    also prepend a HumanMessage so the assistant turn isn't the first
    entry.
    """
    msgs = _input_to_messages(input_)
    if not msgs:
        return input_

    non_system = [m for m in msgs if not isinstance(m, SystemMessage)]
    if not non_system or not isinstance(non_system[0], HumanMessage):
        return [HumanMessage(content=_STUB_USER)] + msgs
    return input_


def _is_transient_anthropic_error(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    exc_name = type(exc).__name__
    if exc_name in ("APIConnectionError", "APITimeoutError", "RemoteProtocolError"):
        return True
    cause = exc.__cause__
    if cause and _is_transient_anthropic_error(cause):
        return True
    return False


def _retry_on_transient(fn, *, attempts: int = 4, base_delay: float = 2.0):
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except (ValueError, KeyError, TypeError, AttributeError,
                AssertionError, NotImplementedError) as exc:
            raise
        except Exception as exc:
            if not _is_transient_anthropic_error(exc) or i == attempts - 1:
                raise
            last_exc = exc
            delay = base_delay * (2 ** i) + random.uniform(0, 0.5)
            _logger.warning(
                "transient Anthropic error (%s) — retrying in %.1fs (attempt %d/%d)",
                exc, delay, i + 1, attempts,
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc


class NormalizedChatAnthropic(ChatAnthropic):
    """ChatAnthropic with normalized content output and transient-error retry.

    Claude models with extended thinking or tool use return content as a
    list of typed blocks. This normalizes to string for consistent
    downstream handling.

    Anthropic's server occasionally disconnects mid-request (``Server
    disconnected without sending a response``) or times out on long
    thinking-mode calls. The SDK's built-in ``max_retries`` only covers
    HTTP 429/500/503; it does **not** retry ``APIConnectionError`` from
    a dropped TCP connection. We catch those here with exponential
    backoff so a single network hiccup doesn't kill a multi-minute
    analysis run.
    """

    def invoke(self, input, config=None, **kwargs):
        _super_invoke = super().invoke
        input = _ensure_user_turn(input)
        return normalize_content(
            _retry_on_transient(lambda: _super_invoke(input, config, **kwargs))
        )


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic Claude models."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """Return configured ChatAnthropic instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        api_key_env = get_api_key_env("anthropic")
        api_key = self.kwargs.get("api_key") or os.environ.get(api_key_env)
        if api_key:
            llm_kwargs["api_key"] = api_key
        else:
            raise ValueError(
                f"API key for provider 'anthropic' is not set. "
                f"Please set the {api_key_env} environment variable "
                f"(e.g. add {api_key_env}=your_key to your .env file)."
            )

        effort = self.kwargs.get("effort")
        if effort:
            llm_kwargs["thinking"] = {"type": "enabled", "budget_tokens": _effort_to_budget(effort)}

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return NormalizedChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for Anthropic."""
        return validate_model("anthropic", self.model)


_EFFORT_BUDGET_MAP = {
    "low": 1024,
    "medium": 8192,
    "high": 32768,
}


def _effort_to_budget(effort: str) -> int:
    mapped = _EFFORT_BUDGET_MAP.get(effort.lower())
    if mapped:
        return mapped
    try:
        return int(effort)
    except (TypeError, ValueError):
        return 8192
