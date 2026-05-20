from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor
from .tool_guard import normalize_date, tool_safe


def _coerce_lookback(v, default=30) -> int:
    """LLMs sometimes pass look_back_days as a string. Coerce defensively."""
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@tool
@tool_safe
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    """
    Retrieve a single technical indicator for a given ticker symbol.
    Uses the configured technical_indicators vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        indicator (str): A single technical indicator name, e.g. 'rsi', 'macd'. Call this tool once per indicator.
        curr_date (str): The current trading date you are trading on, YYYY-mm-dd
        look_back_days (int): How many days to look back, default is 30
    Returns:
        str: A formatted dataframe containing the technical indicators for the specified ticker symbol and indicator.
    """
    if not symbol or not str(symbol).strip():
        return "<tool-error: missing ticker symbol — call again with the ticker.>"
    if not indicator:
        return "<tool-error: missing indicator — call again with e.g. 'rsi' or 'macd'.>"
    curr_date      = normalize_date(curr_date)
    look_back_days = _coerce_lookback(look_back_days, default=30)
    # LLMs sometimes pass multiple indicators as a comma-separated string;
    # split and process each individually.
    indicators = [i.strip().lower() for i in str(indicator).split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            results.append(route_to_vendor("get_indicators", str(symbol).strip().upper(),
                                           ind, curr_date, look_back_days))
        except ValueError as e:
            results.append(f"<{ind}: {e}>")
        except Exception as e:  # noqa: BLE001
            results.append(f"<{ind}: {type(e).__name__}: {e}>")
    return "\n\n".join(results)