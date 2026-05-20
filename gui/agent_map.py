"""Single source of truth for analyst / agent / report metadata.

Centralises the four dicts that used to be duplicated across app.py and the
frontend. When upstream renames a node, edit this file only.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Analyst metadata — keyed by the framework's analyst type string.
# Upstream uses these keys in `selected_analysts` and the LangGraph node
# names are produced via `f"{key.capitalize()} Analyst"` (see
# tradingagents/graph/setup.py).
# ---------------------------------------------------------------------------

ANALYSTS = {
    "market": {
        "display":  "Market Analyst",
        "report":   "market_report",
        "icon":     "📊",
        "blurb":    "Price action, moving averages, technical indicators.",
    },
    "social": {
        "display":  "Sentiment Analyst",     # renamed from "Social" in v0.2.5
        "report":   "sentiment_report",
        "icon":     "💬",
        "blurb":    "Reddit + StockTwits sentiment, retail chatter.",
    },
    "news": {
        "display":  "News Analyst",
        "report":   "news_report",
        "icon":     "📰",
        "blurb":    "Ticker headlines plus macro / global news.",
    },
    "fundamentals": {
        "display":  "Fundamentals Analyst",
        "report":   "fundamentals_report",
        "icon":     "📑",
        "blurb":    "Income statement, balance sheet, cashflow, insiders.",
    },
}


# Fixed agents that always run regardless of analyst selection.
FIXED_TEAMS: dict[str, list[str]] = {
    "Research":        ["Bull Researcher", "Bear Researcher", "Research Manager"],
    "Trading":         ["Trader"],
    "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
    "Portfolio":       ["Portfolio Manager"],
}


# Pretty section titles for the report viewer and exports.
SECTION_TITLES = {
    "market_report":          "Market Analysis",
    "sentiment_report":       "Sentiment Analysis",
    "news_report":            "News Analysis",
    "fundamentals_report":    "Fundamentals Analysis",
    "investment_plan":        "Research Team Decision",
    "trader_investment_plan": "Trading Team Plan",
    "final_trade_decision":   "Portfolio Decision",
}


# Report-section key -> (analyst key that produces it, finalising agent name).
# analyst is None for sections always produced.
REPORT_SECTIONS: dict[str, tuple[str | None, str]] = {
    **{a["report"]: (k, a["display"]) for k, a in ANALYSTS.items()},
    "investment_plan":        (None, "Research Manager"),
    "trader_investment_plan": (None, "Trader"),
    "final_trade_decision":   (None, "Portfolio Manager"),
}


# ---------------------------------------------------------------------------
# Node-name resolution.
#
# v0.2.5's GraphSetup creates analyst nodes named e.g. "Market Analyst" (the
# display name, with a space). Researcher/risk/portfolio nodes use their own
# fixed display names. Tool nodes are "tools_{analyst_key}". The old GUI
# expected `{analyst_key}_analyst` style names — that never matched and
# caused the analyst-progression heuristic to silently fail.
# ---------------------------------------------------------------------------

# Reverse lookup: human display name -> analyst type key (or None for fixed agents).
DISPLAY_TO_KEY = {meta["display"]: k for k, meta in ANALYSTS.items()}


def node_to_agent_display(node_name: str) -> str | None:
    """Map a LangGraph node name to its human-readable agent display name.

    Returns None for tool / unknown nodes.
    """
    if not node_name:
        return None
    # Analyst nodes come through as e.g. "Market Analyst" already.
    if node_name in DISPLAY_TO_KEY:
        return node_name
    # Fixed agents — those nodes are added with their exact display name too.
    for team_agents in FIXED_TEAMS.values():
        if node_name in team_agents:
            return node_name
    # Tool nodes: "tools_market" -> "Market Analyst"
    if node_name.startswith("tools_"):
        key = node_name[len("tools_"):]
        if key in ANALYSTS:
            return ANALYSTS[key]["display"]
    return None


def build_initial_roster(selected_analysts: list[str]) -> dict[str, str]:
    """Return {agent_display: 'pending'} for every agent that will run."""
    roster: dict[str, str] = {}
    for key in selected_analysts:
        if key in ANALYSTS:
            roster[ANALYSTS[key]["display"]] = "pending"
    for team_agents in FIXED_TEAMS.values():
        for agent in team_agents:
            roster[agent] = "pending"
    return roster


def analyst_for_section(section: str) -> str | None:
    """Return the analyst type that produces a given report section."""
    if section in REPORT_SECTIONS:
        return REPORT_SECTIONS[section][0]
    return None
