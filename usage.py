"""Per-run token + cost accounting, with a soft budget guard.

Fed by `StepCallbackHandler` on every LLM response (see events.py). Thread-safe
because runs execute concurrently in a ThreadPoolExecutor. Totals persist across
a HITL pause/resume (keyed by task_id) and are reset when the run truly ends.
"""

import os
import threading

# USD per 1,000 tokens: model-name prefix -> (input_price, output_price).
# Longest matching prefix wins (so "gpt-4o-mini" beats "gpt-4o").
PRICES = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1": (0.002, 0.008),
    "o4-mini": (0.0011, 0.0044),
}

# Fallback price for unknown models (defaults to gpt-4o); overridable via env.
_DEFAULT_IN = float(os.environ.get("OPENAI_PRICE_IN", "0.0025"))
_DEFAULT_OUT = float(os.environ.get("OPENAI_PRICE_OUT", "0.01"))

# Soft per-run budget in USD; 0 (default) disables the guard.
RUN_BUDGET_USD = float(os.environ.get("RUN_BUDGET_USD", "0") or 0)

_lock = threading.Lock()
_runs: dict[str, dict] = {}


def _price(model: str | None) -> tuple[float, float]:
    if model:
        for key in sorted(PRICES, key=len, reverse=True):
            if model.startswith(key):
                return PRICES[key]
    return _DEFAULT_IN, _DEFAULT_OUT


def _blank() -> dict:
    return {"prompt": 0, "completion": 0, "total": 0, "cost_usd": 0.0, "calls": 0}


def _snapshot(r: dict) -> dict:
    return {
        "totals": dict(r["totals"]),
        "by_stage": {k: dict(v) for k, v in r["by_stage"].items()},
    }


def record(task_id: str, stage: str, model: str | None,
           prompt_tokens: int, completion_tokens: int) -> dict:
    """Accumulate one LLM call's usage into the run + stage totals; return a snapshot."""
    pin, pout = _price(model)
    cost = (prompt_tokens / 1000.0) * pin + (completion_tokens / 1000.0) * pout
    with _lock:
        r = _runs.setdefault(task_id, {"totals": _blank(), "by_stage": {}})
        for bucket in (r["totals"], r["by_stage"].setdefault(stage or "?", _blank())):
            bucket["prompt"] += prompt_tokens
            bucket["completion"] += completion_tokens
            bucket["total"] += prompt_tokens + completion_tokens
            bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 6)
            bucket["calls"] += 1
        return _snapshot(r)


def totals(task_id: str) -> dict:
    with _lock:
        r = _runs.get(task_id)
        return _snapshot(r) if r else {"totals": _blank(), "by_stage": {}}


def over_budget(task_id: str) -> bool:
    """True once a run's accumulated cost reaches RUN_BUDGET_USD (if configured)."""
    if RUN_BUDGET_USD <= 0:
        return False
    with _lock:
        r = _runs.get(task_id)
        return bool(r and r["totals"]["cost_usd"] >= RUN_BUDGET_USD)


def reset(task_id: str) -> None:
    with _lock:
        _runs.pop(task_id, None)
