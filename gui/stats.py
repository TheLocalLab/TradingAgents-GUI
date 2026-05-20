"""Token-pricing table used by the cost estimator and live cost ticker.

Values are USD per 1 million tokens, formatted as (input_rate, output_rate).
Unknown models fall back to (0, 0) — the GUI surfaces this as "$0.000" with
a note that pricing is not published for the chosen model, rather than
silently lying.
"""

from __future__ import annotations

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # ---- OpenAI ----
    "gpt-5.5":          (1.25, 10.00),
    "gpt-5.5-pro":      (30.00, 180.00),
    "gpt-5.4":          (0.75, 6.00),
    "gpt-5.4-mini":     (0.15, 1.20),
    "gpt-5.4-nano":     (0.05, 0.40),
    "gpt-5.2":          (0.40, 3.20),
    "gpt-4.1":          (2.00, 8.00),
    # ---- Anthropic ----
    "claude-opus-4-7":   (15.00, 75.00),
    "claude-opus-4-6":   (15.00, 75.00),
    "claude-opus-4-5":   (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5":  (0.80, 4.00),
    # ---- Google ----
    "gemini-3.1-pro-preview":  (2.50, 10.00),
    "gemini-3-flash-preview":  (0.30, 2.50),
    "gemini-3.1-flash-lite":   (0.10, 0.40),
    "gemini-2.5-pro":          (1.25, 10.00),
    "gemini-2.5-flash":        (0.30, 2.50),
    "gemini-2.5-flash-lite":   (0.10, 0.40),
    # ---- DeepSeek ----
    "deepseek-v4-pro":   (0.55, 2.20),
    "deepseek-v4-flash": (0.15, 0.60),
    "deepseek-chat":     (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.20),
    # ---- xAI ----
    "grok-4.20-reasoning":      (3.00, 15.00),
    "grok-4.20-non-reasoning":  (3.00, 15.00),
    "grok-4-fast-reasoning":    (0.50, 2.00),
    "grok-4-fast-non-reasoning":(0.50, 2.00),
}


def price_for(model_id: str) -> tuple[float, float]:
    """Return (input_$/M_tokens, output_$/M_tokens). Unknown → (0,0)."""
    return MODEL_PRICING.get(model_id, (0.0, 0.0))


def estimate_cost(tokens_in: int, tokens_out: int, model: str) -> float:
    """Estimate USD cost given a token count and a model id."""
    inp, out = price_for(model)
    return (tokens_in * inp + tokens_out * out) / 1_000_000


def estimate_run_cost(
    analysts: list[str],
    quick_model: str,
    deep_model: str,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
) -> dict:
    """Heuristic pre-run estimate. Conservative (rounds up) so users aren't surprised.

    Numbers are calibrated from a handful of real runs against gpt-5.4-mini /
    gpt-5.4. They scale roughly linearly with the analyst count and the
    number of debate rounds.
    """
    # Per-analyst budgets (input / output tokens) at the quick-think tier.
    per_analyst_in  = 30_000
    per_analyst_out = 3_000
    # Per debate round at the deep-think tier.
    per_round_in    = 15_000
    per_round_out   = 2_000

    tokens_in  = per_analyst_in  * len(analysts)
    tokens_out = per_analyst_out * len(analysts)
    tokens_in  += per_round_in  * (debate_rounds + risk_rounds)
    tokens_out += per_round_out * (debate_rounds + risk_rounds)

    # Assume analysts hit quick model, debate hits deep model.
    quick_in,  quick_out  = price_for(quick_model)
    deep_in,   deep_out   = price_for(deep_model)
    analyst_cost = (per_analyst_in * len(analysts) * quick_in
                    + per_analyst_out * len(analysts) * quick_out) / 1_000_000
    debate_cost  = (per_round_in * (debate_rounds + risk_rounds) * deep_in
                    + per_round_out * (debate_rounds + risk_rounds) * deep_out) / 1_000_000

    pricing_known = (quick_in or quick_out or deep_in or deep_out) > 0
    return {
        "tokens_in":   tokens_in,
        "tokens_out":  tokens_out,
        "cost_usd":    round(analyst_cost + debate_cost, 3),
        "pricing_known": pricing_known,
    }
