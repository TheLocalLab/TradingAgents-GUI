from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor
from .tool_guard import normalize_date, tool_safe


def _norm_freq(v) -> str:
    """Coerce ``freq`` to ``annual`` / ``quarterly`` — never raise."""
    s = (str(v or "").strip().lower() or "quarterly")
    if s in ("annual", "annually", "yearly", "year", "a"):
        return "annual"
    return "quarterly"


def _norm_ticker(v) -> str:
    return str(v or "").strip().upper()


@tool
@tool_safe
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing comprehensive fundamental data
    """
    t = _norm_ticker(ticker)
    if not t:
        return "<tool-error: missing ticker symbol — call again with the ticker.>"
    return route_to_vendor("get_fundamentals", t, normalize_date(curr_date))


@tool
@tool_safe
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve balance sheet data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing balance sheet data
    """
    t = _norm_ticker(ticker)
    if not t:
        return "<tool-error: missing ticker symbol — call again with the ticker.>"
    return route_to_vendor("get_balance_sheet", t, _norm_freq(freq), normalize_date(curr_date))


@tool
@tool_safe
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve cash flow statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing cash flow statement data
    """
    t = _norm_ticker(ticker)
    if not t:
        return "<tool-error: missing ticker symbol — call again with the ticker.>"
    return route_to_vendor("get_cashflow", t, _norm_freq(freq), normalize_date(curr_date))


@tool
@tool_safe
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve income statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing income statement data
    """
    t = _norm_ticker(ticker)
    if not t:
        return "<tool-error: missing ticker symbol — call again with the ticker.>"
    return route_to_vendor("get_income_statement", t, _norm_freq(freq), normalize_date(curr_date))
