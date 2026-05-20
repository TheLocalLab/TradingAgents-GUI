from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


# Brevity-level instruction text. Tunable here without touching analysts.
_BREVITY_INSTRUCTIONS = {
    "concise": (
        " Be concise. Aim for ~300 words total — single paragraph per section, "
        "tight bullets, no preamble or filler. Skip exhaustive caveats. "
        "Cap the final summary table to the 5 most important rows."
    ),
    "standard": "",  # default — no extra instruction
    "comprehensive": (
        " Write a thorough, detailed report. Cover every relevant angle, "
        "include nuance, edge cases, and supporting evidence. Use multi-row "
        "summary tables where appropriate. Length is not a concern."
    ),
}


def get_brevity_instruction() -> str:
    """Return a prompt instruction for the configured report-length preference.

    Honors ``config["report_brevity"]`` — one of:
      * ``"concise"``        — short, focused output (~300 words)
      * ``"standard"``       — current default behavior, no extra instruction
      * ``"comprehensive"``  — long, detailed output

    Returns empty string for the default ("standard"), so existing users
    see no behavior change unless they opt in.
    """
    from tradingagents.dataflows.config import get_config
    level = (get_config().get("report_brevity") or "standard").strip().lower()
    return _BREVITY_INSTRUCTIONS.get(level, "")


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
