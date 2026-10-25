"""Upstream v0.6.0 data fixes ported to this fork: null-safe Yahoo news
(#1458), crypto-aware Reddit communities (#1461) and currency-labelled
Yahoo fundamentals (#1456). All hermetic: Yahoo and Reddit are stubbed."""

from __future__ import annotations

import pytest

from tradingagents.dataflows import reddit, y_finance, yfinance_news


# ---------------------------------------------------------------------------
# Yahoo news: a null field in one article must not cost the whole ticker
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNullSafeNews:
    def test_null_provider_and_title_in_nested_article(self):
        data = yfinance_news._extract_article_data({"content": {
            "title": None, "summary": None, "provider": None,
            "canonicalUrl": None, "clickThroughUrl": None, "pubDate": None}})
        assert data["title"] == "No title"
        assert data["publisher"] == "Unknown"
        assert data["summary"] == "" and data["link"] == ""

    def test_content_that_is_not_a_dict(self):
        data = yfinance_news._extract_article_data({"content": None})
        assert data["title"] == "No title" and data["publisher"] == "Unknown"

    def test_null_fields_in_flat_article(self):
        data = yfinance_news._extract_article_data(
            {"title": None, "summary": None, "publisher": None, "link": None})
        assert data["title"] == "No title" and data["publisher"] == "Unknown"

    def test_good_article_unchanged(self):
        data = yfinance_news._extract_article_data({"content": {
            "title": "NVDA beats", "summary": "Strong quarter.",
            "provider": {"displayName": "Reuters"},
            "canonicalUrl": {"url": "https://x.test/a"}, "pubDate": "2026-10-01T12:00:00Z"}})
        assert data["title"] == "NVDA beats" and data["publisher"] == "Reuters"
        assert data["link"] == "https://x.test/a" and data["pub_date"] is not None

    def test_one_bad_article_keeps_the_rest(self, monkeypatch):
        class Ticker:
            def __init__(self, *_): pass
            def get_news(self, count=None):
                return [
                    {"content": {"title": "Good one", "provider": {"displayName": "AP"},
                                 "pubDate": "2026-10-01T12:00:00Z"}},
                    {"content": {"title": None, "provider": None, "pubDate": None}},
                ]
        monkeypatch.setattr(yfinance_news.yf, "Ticker", Ticker)
        monkeypatch.setattr(yfinance_news, "get_config", lambda: {"news_article_limit": 20})
        out = yfinance_news.get_news_yfinance("NVDA", "2026-09-25", "2026-10-02")
        assert "Error fetching news" not in out
        assert "Good one" in out and "No title" in out


# ---------------------------------------------------------------------------
# Reddit: crypto tickers read crypto communities
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCryptoSubreddits:
    @pytest.mark.parametrize("ticker,expected", [
        ("BTC-USD", ("Bitcoin", "CryptoCurrency", "CryptoMarkets")),
        ("eth-usd", ("ethereum", "CryptoCurrency", "CryptoMarkets")),
        ("SOL-USDT", ("solana", "CryptoCurrency", "CryptoMarkets")),
        ("DOGE-USD", ("CryptoCurrency", "CryptoMarkets")),
        ("AAPL", reddit.DEFAULT_SUBREDDITS),
        ("BRK-B", reddit.DEFAULT_SUBREDDITS),      # share class, not a coin pair
        ("", reddit.DEFAULT_SUBREDDITS),
    ])
    def test_subreddits_for(self, ticker, expected):
        assert reddit.subreddits_for(ticker) == expected

    def _capture(self, monkeypatch):
        seen = []
        monkeypatch.setattr(reddit, "_fetch_subreddit",
                            lambda ticker, sub, limit, timeout: seen.append(sub) or [])
        return seen

    def test_fetch_defaults_follow_the_ticker(self, monkeypatch):
        seen = self._capture(monkeypatch)
        reddit.fetch_reddit_posts("BTC-USD", inter_request_delay=0)
        assert seen == ["Bitcoin", "CryptoCurrency", "CryptoMarkets"]
        seen.clear()
        reddit.fetch_reddit_posts("AAPL", inter_request_delay=0)
        assert seen == list(reddit.DEFAULT_SUBREDDITS)

    def test_explicit_subreddits_still_win_and_generators_work(self, monkeypatch):
        seen = self._capture(monkeypatch)
        out = reddit.fetch_reddit_posts("BTC-USD", subreddits=(s for s in ["a", "b"]),
                                        inter_request_delay=0)
        assert seen == ["a", "b"]
        assert "r/a" in out and "r/b" in out     # the empty-result message lists both


# ---------------------------------------------------------------------------
# Fundamentals: every money figure names its currency
# ---------------------------------------------------------------------------


def _fundamentals(monkeypatch, info):
    class Ticker:
        def __init__(self, *_): self.info = info
    monkeypatch.setattr(y_finance.yf, "Ticker", Ticker)
    out = y_finance.get_fundamentals("X")
    return {ln.split(": ", 1)[0]: ln.split(": ", 1)[1] for ln in out.splitlines() if ": " in ln}


@pytest.mark.unit
class TestFundamentalCurrencies:
    def test_us_stock(self, monkeypatch):
        f = _fundamentals(monkeypatch, {
            "currency": "USD", "financialCurrency": "USD", "marketCap": 3e12,
            "fiftyTwoWeekHigh": 150.0, "totalRevenue": 1e11, "trailingPE": 30.0})
        assert f["Market Cap"] == "3000000000000.0 USD"
        assert f["52 Week High"] == "150.0 USD"
        assert f["Revenue (TTM)"] == "100000000000.0 USD"
        assert f["PE Ratio (TTM)"] == "30.0"            # ratios stay unlabeled

    def test_london_pence_vs_pounds(self, monkeypatch):
        f = _fundamentals(monkeypatch, {
            "currency": "GBp", "financialCurrency": "GBP", "marketCap": 5e10,
            "fiftyTwoWeekHigh": 2500.0, "totalRevenue": 2e10})
        assert f["52 Week High"].endswith("GBp")        # price exactly as quoted
        assert f["Market Cap"].endswith("GBP")          # market cap in pounds
        assert f["Revenue (TTM)"].endswith("GBP")

    def test_adr_reports_in_its_own_currency(self, monkeypatch):
        f = _fundamentals(monkeypatch, {
            "currency": "USD", "financialCurrency": "TWD", "marketCap": 9e11,
            "totalRevenue": 2.9e12, "netIncomeToCommon": 1.1e12})
        assert f["Market Cap"].endswith("USD")
        assert f["Revenue (TTM)"].endswith("TWD")
        assert f["Net Income"].endswith("TWD")

    def test_missing_currency_leaves_values_unlabeled(self, monkeypatch):
        f = _fundamentals(monkeypatch, {"marketCap": 1000, "totalRevenue": 5})
        assert f["Market Cap"] == "1000" and f["Revenue (TTM)"] == "5"

    def test_reporting_currency_falls_back_to_trading_currency(self, monkeypatch):
        f = _fundamentals(monkeypatch, {"currency": "EUR", "totalRevenue": 5})
        assert f["Revenue (TTM)"] == "5 EUR"
