from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor
from .tool_guard import normalize_date, tool_safe


@tool
@tool_safe
def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve stock price data (OHLCV) for a given ticker symbol.
    Uses the configured core_stock_apis vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted dataframe containing the stock price data for the specified ticker symbol in the specified date range.
    """
    # Default empty/None to a sensible window. Z.AI in particular often
    # forgets to pass the date pair on the first tool-call hop.
    end_date   = normalize_date(end_date)
    start_date = normalize_date(start_date, default_offset_days=-30)
    if not symbol or not str(symbol).strip():
        return "<tool-error: missing ticker symbol — call again with the ticker.>"
    return route_to_vendor("get_stock_data", str(symbol).strip().upper(), start_date, end_date)
