"""Regression tests for the upstream v0.7.0 quick wins: the stricter rating
parser (REVIEW sentinel), the refreshed model catalog, the Gemini request
timeout and the deepseek-flash capability entry."""

import pytest

from tradingagents.agents.utils.rating import (
    RATING_REVIEW,
    RATINGS_5_TIER,
    extract_rating,
    is_review,
    parse_rating,
)


# ---------------------------------------------------------------------------
# Rating parser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStrictRating:
    def test_quoted_rating_before_own_rating_does_not_win(self):
        """#1466: the PM's own Rating line beats a quoted "Consensus rating"."""
        text = "Consensus rating: Buy\n**Rating**: Hold\n\nBody."
        assert parse_rating(text) == "Hold"

    def test_own_rating_beats_quoted_rating(self):
        text = "**Rating**: Underweight\n\nThe consensus rating: Buy is stale."
        assert parse_rating(text) == "Underweight"

    def test_rating_word_in_prose_is_not_a_call(self):
        assert parse_rating("This is not a Sell, but nobody is buying.") == RATING_REVIEW

    def test_disagreeing_labels_without_an_opening_call_are_no_call(self):
        text = "Summary first.\n- Rating: Buy\n- Rating: Sell"
        assert parse_rating(text) == RATING_REVIEW

    def test_opening_rating_line_is_the_call(self):
        # The decision opens with its rating; later labels don't override it.
        assert parse_rating("Rating: Buy\n- Rating: Sell") == "Buy"

    def test_fullwidth_colon(self):
        assert parse_rating("Rating：Overweight") == "Overweight"

    def test_empty_and_none_like(self):
        assert parse_rating("") == RATING_REVIEW
        assert extract_rating("") is None

    def test_explicit_default_still_honoured(self):
        assert parse_rating("Plain prose.", default="Hold") == "Hold"

    def test_is_review(self):
        assert is_review("REVIEW") and not is_review("Buy")

    @pytest.mark.parametrize("tier", RATINGS_5_TIER)
    def test_all_tiers_round_trip(self, tier):
        assert parse_rating(f"**Rating**: {tier}\n\nBody.") == tier


# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelCatalog:
    @pytest.mark.parametrize("provider,model", [
        ("openai", "gpt-6-sol"), ("openai", "gpt-6-luna"),
        ("anthropic", "claude-opus-5-5"), ("anthropic", "claude-sonnet-5"),
        ("google", "gemini-3.8-flash"),
        ("xai", "grok-4.6"),
        ("deepseek", "deepseek-flash"),
        ("glm", "glm-5.3"), ("glm-cn", "glm-5.3-flash"),
        ("qwen", "qwen3.8-max"), ("qwen-cn", "qwen3.8-flash"),
        ("minimax", "MiniMax-M3"),
    ])
    def test_new_models_are_offered_and_known(self, provider, model):
        from tradingagents.llm_clients.model_catalog import (
            MODEL_OPTIONS, get_known_models)
        offered = {v for opts in MODEL_OPTIONS[provider].values() for _, v in opts}
        assert model in offered
        assert model in get_known_models()[provider]

    def test_previous_generation_stays_selectable(self):
        """Saved selections from before the refresh must still resolve."""
        from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
        deep = {v for _, v in MODEL_OPTIONS["openai"]["deep"]}
        quick = {v for _, v in MODEL_OPTIONS["openai"]["quick"]}
        assert "gpt-5.4" in deep and "gpt-5.4-mini" in quick

    @pytest.mark.parametrize("provider,model", [
        ("openai", "gpt-4.1"), ("anthropic", "claude-sonnet-4-5"),
        ("google", "gemini-2.5-pro"), ("deepseek", "deepseek-reasoner"),
    ])
    def test_retired_models_stay_valid_but_unlisted(self, provider, model):
        from tradingagents.llm_clients.model_catalog import (
            MODEL_OPTIONS, get_known_models)
        offered = {v for opts in MODEL_OPTIONS[provider].values() for _, v in opts}
        assert model in get_known_models()[provider]
        if provider != "deepseek":   # deepseek aliases are still in the picker
            assert model not in offered

    def test_every_option_has_label_and_value(self):
        from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
        for provider, modes in MODEL_OPTIONS.items():
            for mode, opts in modes.items():
                assert opts, (provider, mode)
                values = [v for _, v in opts]
                assert len(values) == len(set(values)), f"duplicate in {provider}/{mode}"
                assert all(lbl and val for lbl, val in opts)


# ---------------------------------------------------------------------------
# Gemini timeout + capabilities
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeminiTimeout:
    def _llm(self, **kw):
        from tradingagents.llm_clients.google_client import GoogleClient
        return GoogleClient("gemini-3.8-flash", api_key="test-key", **kw).get_llm()

    def test_default_timeout_applied(self):
        from tradingagents.llm_clients.google_client import REQUEST_TIMEOUT_SECONDS
        assert REQUEST_TIMEOUT_SECONDS == 600
        assert self._llm().timeout == REQUEST_TIMEOUT_SECONDS

    def test_explicit_timeout_wins(self):
        assert self._llm(timeout=42).timeout == 42


@pytest.mark.unit
def test_deepseek_flash_is_a_thinking_model():
    from tradingagents.llm_clients.capabilities import get_capabilities
    assert get_capabilities("deepseek-flash") == get_capabilities("deepseek-v4-flash")
    assert get_capabilities("deepseek-flash").supports_tool_choice is False
