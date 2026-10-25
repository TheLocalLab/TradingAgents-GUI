"""Tests for the analyst tool-round cap (upstream #1420) and the optional
output-token cap (upstream #1204)."""

from __future__ import annotations

import importlib
import uuid
from typing import Any, List, Optional

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

import tradingagents.default_config as default_config_module
from tradingagents.graph import setup as graph_setup
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup, count_tool_rounds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@tool
def ping(x: str = "") -> str:
    """Return a fixed string."""
    return "pong"


SEEN_NUDGES: List[str] = []     # last message of every tool-less (wrap-up) call


class LoopingLLM(BaseChatModel):
    """Stub model: asks for a tool on every call while tools are bound, and
    writes a plain report when they are not (the wrap-up turn)."""

    tools_bound: bool = False

    @property
    def _llm_type(self) -> str:
        return "looping-stub"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools_bound": True})

    def with_structured_output(self, *a, **kw):
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self.tools_bound:
            msg = AIMessage(content="", tool_calls=[
                {"name": "ping", "args": {"x": "a"}, "id": uuid.uuid4().hex[:8]}])
        else:
            SEEN_NUDGES.append(str(messages[-1].content))
            msg = AIMessage(content="WRAP-UP REPORT")
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _fake_market_analyst(llm):
    """Same shape as the real node: tool-call turn => empty report."""
    def node(state):
        result = llm.bind_tools([ping]).invoke(state["messages"])
        return {"messages": [result],
                "market_report": "" if result.tool_calls else result.content}
    return node


def _build(monkeypatch, cap):
    monkeypatch.setattr(graph_setup, "create_market_analyst", _fake_market_analyst)
    llm = LoopingLLM()
    setup = GraphSetup(llm, llm, {"market": ToolNode([ping])},
                       ConditionalLogic(), max_tool_rounds=cap)
    return setup.setup_graph(["market"]).compile()


def _initial_state():
    return {"company_of_interest": "NVDA", "trade_date": "2026-10-01",
            "messages": [HumanMessage(content="NVDA")],
            "investment_debate_state": {"bull_history": "", "bear_history": "",
                                        "judge_decision": "", "count": 0},
            "risk_debate_state": {"aggressive_history": "", "conservative_history": "",
                                  "neutral_history": "", "judge_decision": "", "count": 0}}


# ---------------------------------------------------------------------------
# Tool-round cap
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_count_tool_rounds_counts_only_tool_requests():
    msgs = [HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"name": "ping", "args": {}, "id": "1"}]),
            AIMessage(content="plain answer"),
            AIMessage(content="", tool_calls=[{"name": "ping", "args": {}, "id": "2"}])]
    assert count_tool_rounds(msgs) == 2
    assert count_tool_rounds([]) == 0


@pytest.mark.unit
def test_runaway_analyst_is_wrapped_up_instead_of_looping(monkeypatch):
    SEEN_NUDGES.clear()
    graph = _build(monkeypatch, cap=3)
    order, report = [], ""
    for chunk in graph.stream(_initial_state(), config={"recursion_limit": 50}):
        for node, state in chunk.items():
            order.append(node)
            if isinstance(state, dict) and state.get("market_report"):
                report = state["market_report"]
        if "Msg Clear Market" in chunk:     # analyst phase is over
            break

    assert order.count("tools_market") == 3, order      # exactly the cap
    assert "Wrap Up Market" in order
    assert order.index("Wrap Up Market") < order.index("Msg Clear Market")
    assert report == "WRAP-UP REPORT"
    # The wrap-up turn told the model to stop calling tools and name the target.
    nudge = SEEN_NUDGES[-1]
    assert "tool-call budget" in nudge and "NVDA" in nudge and "2026-10-01" in nudge


@pytest.mark.unit
def test_cap_disabled_keeps_original_loop_wiring(monkeypatch):
    graph = _build(monkeypatch, cap=0)
    assert "Wrap Up Market" not in graph.get_graph().nodes


@pytest.mark.unit
def test_cap_node_present_by_default(monkeypatch):
    graph = _build(monkeypatch, cap=20)
    assert "Wrap Up Market" in graph.get_graph().nodes


@pytest.mark.unit
def test_graph_rejects_cap_that_cannot_fit_in_recursion_limit():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    cfg = dict(default_config_module.DEFAULT_CONFIG,
               max_tool_rounds=60, max_recur_limit=100)
    with pytest.raises(ValueError, match="max_tool_rounds"):
        TradingAgentsGraph(["market"], config=cfg)


# ---------------------------------------------------------------------------
# Config / env
# ---------------------------------------------------------------------------


def _reload(monkeypatch, **env):
    for k in ("TRADINGAGENTS_MAX_TOOL_ROUNDS", "TRADINGAGENTS_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(default_config_module)


@pytest.mark.unit
def test_defaults(monkeypatch):
    dc = _reload(monkeypatch)
    assert dc.DEFAULT_CONFIG["max_tool_rounds"] == 20
    assert dc.DEFAULT_CONFIG["max_tokens"] is None


@pytest.mark.unit
def test_env_overrides_coerce_to_int(monkeypatch):
    dc = _reload(monkeypatch, TRADINGAGENTS_MAX_TOOL_ROUNDS="7",
                 TRADINGAGENTS_MAX_TOKENS="4096")
    assert dc.DEFAULT_CONFIG["max_tool_rounds"] == 7
    assert dc.DEFAULT_CONFIG["max_tokens"] == 4096


@pytest.mark.unit
def test_bad_max_tokens_fails_loudly(monkeypatch):
    with pytest.raises(ValueError, match="TRADINGAGENTS_MAX_TOKENS"):
        _reload(monkeypatch, TRADINGAGENTS_MAX_TOKENS="lots")
    _reload(monkeypatch)    # restore a clean module for later tests


# ---------------------------------------------------------------------------
# max_tokens reaches each client
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_max_tokens_reaches_openai_client():
    from tradingagents.llm_clients.openai_client import OpenAIClient
    llm = OpenAIClient("gpt-5.4-mini", provider="openai", api_key="k", max_tokens=1234).get_llm()
    assert (getattr(llm, "max_tokens", None) or getattr(llm, "max_completion_tokens", None)) == 1234


@pytest.mark.unit
def test_max_tokens_maps_to_gemini_max_output_tokens():
    from tradingagents.llm_clients.google_client import GoogleClient
    llm = GoogleClient("gemini-3.8-flash", api_key="k", max_tokens=777).get_llm()
    assert llm.max_output_tokens == 777


@pytest.mark.unit
def test_max_tokens_reaches_anthropic_client():
    from tradingagents.llm_clients.anthropic_client import AnthropicClient
    llm = AnthropicClient("claude-sonnet-5", api_key="k", max_tokens=555).get_llm()
    assert llm.max_tokens == 555


@pytest.mark.unit
def test_provider_kwargs_forward_max_tokens():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    g = TradingAgentsGraph.__new__(TradingAgentsGraph)
    g.config = {"llm_provider": "openai", "max_tokens": 321}
    assert g._get_provider_kwargs()["max_tokens"] == 321
    g.config = {"llm_provider": "openai", "max_tokens": None}
    assert "max_tokens" not in g._get_provider_kwargs()


# ---------------------------------------------------------------------------
# GUI run manager copes with the new wrap-up node in the stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_manager_captures_report_from_wrap_up_chunk():
    from gui.run_manager import Run, _handle_node_chunk

    run = Run({"ticker": "NVDA", "date": "2026-10-01"})
    chunk_state = {"messages": [AIMessage(content="WRAP-UP REPORT")],
                   "market_report": "WRAP-UP REPORT"}
    _handle_node_chunk(run, "Wrap Up Market", chunk_state, {}, {}, "deep", "quick")

    assert run.reports["market_report"] == "WRAP-UP REPORT"
    # LLM calls are counted by the callback, not by re-counting stream messages.
    assert run.stats["llm_calls"] == 0


@pytest.mark.unit
def test_tool_node_results_are_counted_as_tool_calls():
    from langchain_core.messages import ToolMessage
    from gui.run_manager import Run, _handle_node_chunk

    run = Run({"ticker": "NVDA", "date": "2026-10-01"})
    state = {"messages": [ToolMessage(content="pong", name="ping", tool_call_id="1"),
                          ToolMessage(content="pong", name="ping", tool_call_id="2")]}
    _handle_node_chunk(run, "tools_market", state, {}, {}, "deep", "quick")
    assert run.stats["tool_calls"] == 2


@pytest.mark.unit
def test_stats_callback_counts_calls_tokens_and_cost():
    from langchain_core.outputs import ChatGeneration, LLMResult
    from gui.run_manager import Run, _RunStatsCallback
    from gui.stats import estimate_cost

    run = Run({"ticker": "NVDA", "date": "2026-10-01"})
    cb = _RunStatsCallback(run, fallback_model="gpt-5.4-mini")

    def result(in_t, out_t, model):
        msg = AIMessage(content="x", usage_metadata={"input_tokens": in_t, "output_tokens": out_t,
                                                     "total_tokens": in_t + out_t},
                        response_metadata={"model_name": model})
        return LLMResult(generations=[[ChatGeneration(message=msg)]])

    cb.on_llm_end(result(1000, 200, "gpt-5.4-mini"))
    cb.on_llm_end(result(500, 100, "gpt-5.4"))
    assert run.stats["llm_calls"] == 2
    assert run.stats["tokens_in"] == 1500 and run.stats["tokens_out"] == 300
    expected = round(estimate_cost(1000, 200, "gpt-5.4-mini") + estimate_cost(500, 100, "gpt-5.4"), 4)
    assert run.stats["cost_usd"] == expected


@pytest.mark.unit
def test_stats_callback_falls_back_to_llm_output_usage():
    from langchain_core.outputs import Generation, LLMResult
    from gui.run_manager import Run, _RunStatsCallback

    run = Run({"ticker": "NVDA", "date": "2026-10-01"})
    cb = _RunStatsCallback(run, fallback_model="unknown-model")
    cb.on_llm_end(LLMResult(generations=[[Generation(text="x")]],
                            llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}))
    assert run.stats["llm_calls"] == 1
    assert run.stats["tokens_in"] == 7 and run.stats["tokens_out"] == 3
