from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cache_read_per_million: float

    @property
    def cache_write_per_million(self) -> float:
        # The supplied price list has no separate cache-write price.
        return self.input_per_million


MODEL_PRICING: Dict[str, ModelPricing] = {
    "gpt-5.6-luna": ModelPricing(0.3600, 2.8800, 0.1400),
    "gpt-5.6-sol": ModelPricing(0.8000, 6.4000, 0.2500),
    "gpt-5.6-terra": ModelPricing(0.4000, 3.2000, 0.1500),
    "gpt-6-astra": ModelPricing(1.6000, 12.8000, 0.4800),
    "deepseek-v4-flash-0731": ModelPricing(1.5000, 4.5000, 0.0500),
    "deepseek-v4-pro": ModelPricing(2.0000, 4.0000, 0.0400),
    "deepseek-v4-pro-0813": ModelPricing(4.5000, 14.0000, 0.1500),
}


def _key(model: str) -> str:
    return " ".join(str(model or "").strip().lower().split())


def get_pricing(model: str) -> Optional[ModelPricing]:
    key = _key(model)
    if key in MODEL_PRICING:
        return MODEL_PRICING[key]
    # Keep older/local model labels compatible with the supplied price cards.
    aliases = {
        "deepseek-v4-flash": "deepseek-v4-flash-0731",
        "deepseek-v4-flash-0731": "deepseek-v4-flash-0731",
    }
    alias = aliases.get(key)
    return MODEL_PRICING.get(alias) if alias else None


def cost_cny(
    model: str,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_output_tokens: int = 0,
) -> Optional[float]:
    pricing = get_pricing(model)
    if pricing is None:
        return None

    input_tokens = max(0, int(input_tokens or 0))
    cached_input_tokens = max(0, int(cached_input_tokens or 0))
    cache_write_input_tokens = max(0, int(cache_write_input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    reasoning_output_tokens = max(0, int(reasoning_output_tokens or 0))
    normal_input = max(
        0, input_tokens - cached_input_tokens - cache_write_input_tokens
    )
    amount = (
        normal_input * pricing.input_per_million
        + cached_input_tokens * pricing.cache_read_per_million
        + cache_write_input_tokens * pricing.cache_write_per_million
        + output_tokens * pricing.output_per_million
    )
    return amount / 1_000_000


def cost_from_row(row: Dict[str, Any]) -> Optional[float]:
    return cost_cny(
        row.get("model", ""),
        row.get("input_tokens", 0),
        row.get("cached_input_tokens", 0),
        row.get("cache_write_input_tokens", 0),
        row.get("output_tokens", 0),
        row.get("reasoning_output_tokens", 0),
    )


def cost_sql() -> str:
    model = "LOWER(COALESCE(t.model, ''))"
    normal_input = "MAX(0, tr.input_tokens - tr.cached_input_tokens - tr.cache_write_input_tokens)"
    return f"""
        COALESCE(SUM(
            CASE
                WHEN {model} = 'gpt-5.6-luna' THEN
                    ({normal_input} * 0.3600
                     + tr.cached_input_tokens * 0.1400
                     + tr.cache_write_input_tokens * 0.3600
                     + tr.output_tokens * 2.8800)
                WHEN {model} = 'gpt-5.6-sol' THEN
                    ({normal_input} * 0.8000
                     + tr.cached_input_tokens * 0.2500
                     + tr.cache_write_input_tokens * 0.8000
                     + tr.output_tokens * 6.4000)
                WHEN {model} = 'gpt-5.6-terra' THEN
                    ({normal_input} * 0.4000
                     + tr.cached_input_tokens * 0.1500
                     + tr.cache_write_input_tokens * 0.4000
                     + tr.output_tokens * 3.2000)
                WHEN {model} = 'gpt-6-astra' THEN
                    ({normal_input} * 1.6000
                     + tr.cached_input_tokens * 0.4800
                     + tr.cache_write_input_tokens * 1.6000
                     + tr.output_tokens * 12.8000)
                WHEN {model} IN ('deepseek-v4-flash', 'deepseek-v4-flash-0731') THEN
                    ({normal_input} * 1.5000
                     + tr.cached_input_tokens * 0.0500
                     + tr.cache_write_input_tokens * 1.5000
                     + tr.output_tokens * 4.5000)
                WHEN {model} = 'deepseek-v4-pro' THEN
                    ({normal_input} * 2.0000
                     + tr.cached_input_tokens * 0.0400
                     + tr.cache_write_input_tokens * 2.0000
                     + tr.output_tokens * 4.0000)
                WHEN {model} = 'deepseek-v4-pro-0813' THEN
                    ({normal_input} * 4.5000
                     + tr.cached_input_tokens * 0.1500
                     + tr.cache_write_input_tokens * 4.5000
                     + tr.output_tokens * 14.0000)
                ELSE 0
            END
        ), 0) / 1000000.0 AS cost_cny
    """
