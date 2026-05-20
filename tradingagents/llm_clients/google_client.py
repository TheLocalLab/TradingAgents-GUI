from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


def _input_to_messages(input_) -> list:
    """Coerce a langchain LLM input (list / ChatPromptValue / string) into
    a flat list of message objects. Returns the original ``input_`` form
    when we can't normalize."""
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    if isinstance(input_, str):
        return [HumanMessage(content=input_)]
    return []


_STUB_USER = "Please proceed with the analysis described above."


def _ensure_user_turn(input_):
    """Make the outgoing message list valid for Gemini's strict
    ``contents`` grammar.

    Gemini imposes two rules on top of what OpenAI/Anthropic accept:

    1. ``contents`` must contain at least one entry. langchain-google-
       genai routes system text to ``systemInstruction``, so a list with
       only ``SystemMessage`` ends up with **empty** ``contents`` and
       fails with ``contents are required``.

    2. Every ``function_call`` turn (an ``AIMessage`` carrying
       ``tool_calls``) must be preceded by either a ``user`` turn or a
       ``function_response`` turn. langgraph's first tool-call hop
       hands us ``[AIMessage(tool_calls=…), ToolMessage(…)]`` — the
       AIMessage is the function_call and has no user turn before it,
       so Gemini rejects with ``function call turn comes immediately
       after a user turn``.

    The fix: split system from the rest, then guarantee the rest *starts*
    with a HumanMessage. If the first non-system message is anything else
    (AIMessage, ToolMessage) or the rest is empty, **prepend** a stub
    HumanMessage. Appending wouldn't help — the offending function_call
    is at index 0 of contents.
    """
    msgs = _input_to_messages(input_)
    systems = [m for m in msgs if isinstance(m, SystemMessage)]
    rest    = [m for m in msgs if not isinstance(m, SystemMessage)]

    if not rest or not isinstance(rest[0], HumanMessage):
        rest = [HumanMessage(content=_STUB_USER)] + rest

    return systems + rest


class NormalizedChatGoogleGenerativeAI(ChatGoogleGenerativeAI):
    """ChatGoogleGenerativeAI with normalized content output and an
    empty-contents guard.

    Two layers on top of the stock ChatGoogleGenerativeAI:

    1. **Empty-contents guard** — Gemini rejects a request whose
       ``contents`` array is empty (system-only conversations). Pre-pend
       a user-turn placeholder when needed so the first hop of every
       agent ("here is the system prompt, now go") works without the
       agent having to seed a dummy HumanMessage itself.

    2. **Content normalization** — Gemini 3 returns content as a list of
       typed blocks; collapse to a string so downstream code can treat
       every provider uniformly.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(_ensure_user_turn(input), config, **kwargs))


class GoogleClient(BaseLLMClient):
    """Client for Google Gemini models."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """Return configured ChatGoogleGenerativeAI instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in ("timeout", "max_retries", "callbacks", "http_client", "http_async_client"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Unified api_key maps to provider-specific google_api_key
        google_api_key = self.kwargs.get("api_key") or self.kwargs.get("google_api_key")
        if google_api_key:
            llm_kwargs["google_api_key"] = google_api_key

        # Map thinking_level to appropriate API param based on model
        # Gemini 3 Pro: low, high
        # Gemini 3 Flash: minimal, low, medium, high
        # Gemini 2.5: thinking_budget (0=disable, -1=dynamic)
        thinking_level = self.kwargs.get("thinking_level")
        if thinking_level:
            model_lower = self.model.lower()
            if "gemini-3" in model_lower:
                # Gemini 3 Pro doesn't support "minimal", use "low" instead
                if "pro" in model_lower and thinking_level == "minimal":
                    thinking_level = "low"
                llm_kwargs["thinking_level"] = thinking_level
            else:
                # Gemini 2.5: map to thinking_budget
                llm_kwargs["thinking_budget"] = -1 if thinking_level == "high" else 0

        return NormalizedChatGoogleGenerativeAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for Google."""
        return validate_model("google", self.model)
