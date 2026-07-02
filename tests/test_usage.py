"""Token/cost accounting, model-price prefix matching, and the budget guard."""

import usage
from events import StepCallbackHandler


def test_price_prefix_matches_longest():
    assert usage._price("gpt-4o-mini-2024") == usage.PRICES["gpt-4o-mini"]
    assert usage._price("gpt-4o-2024-08-06") == usage.PRICES["gpt-4o"]
    assert usage._price("some-unknown-model") == (usage._DEFAULT_IN, usage._DEFAULT_OUT)


def test_record_accumulates_totals_and_stages():
    tid = "t-acc"
    usage.reset(tid)
    usage.record(tid, "coding", "gpt-4o", 1000, 500)      # 0.0025 + 0.005 = 0.0075
    snap = usage.record(tid, "review", "gpt-4o", 2000, 0)  # +0.005
    t = snap["totals"]
    assert t["prompt"] == 3000 and t["completion"] == 500 and t["total"] == 3500
    assert t["calls"] == 2
    assert round(t["cost_usd"], 4) == 0.0125
    assert snap["by_stage"]["coding"]["total"] == 1500
    assert snap["by_stage"]["review"]["total"] == 2000
    usage.reset(tid)


def test_reset_clears_run():
    tid = "t-reset"
    usage.record(tid, "coding", "gpt-4o", 10, 10)
    usage.reset(tid)
    assert usage.totals(tid)["totals"]["total"] == 0


def test_over_budget(monkeypatch):
    tid = "t-budget"
    usage.reset(tid)
    monkeypatch.setattr(usage, "RUN_BUDGET_USD", 0.01)
    usage.record(tid, "coding", "gpt-4o", 1000, 0)   # $0.0025 < budget
    assert usage.over_budget(tid) is False
    usage.record(tid, "coding", "gpt-4o", 4000, 0)   # +$0.01 -> $0.0125 >= budget
    assert usage.over_budget(tid) is True
    usage.reset(tid)


def test_budget_disabled_by_default(monkeypatch):
    tid = "t-nobudget"
    usage.reset(tid)
    monkeypatch.setattr(usage, "RUN_BUDGET_USD", 0)
    usage.record(tid, "coding", "gpt-4o", 10_000_000, 10_000_000)
    assert usage.over_budget(tid) is False
    usage.reset(tid)


class _Msg:
    def __init__(self, um):
        self.usage_metadata = um


class _Resp:
    def __init__(self, llm_output=None, generations=None):
        self.llm_output = llm_output
        self.generations = generations or []


def test_extract_usage_from_llm_output():
    r = _Resp(llm_output={"token_usage": {"prompt_tokens": 12, "completion_tokens": 3}})
    assert StepCallbackHandler._extract_usage(r) == (12, 3)


def test_extract_usage_from_usage_metadata():
    r = _Resp(generations=[[_Msg.__new__(_Msg)]])
    r.generations[0][0] = type("G", (), {"message": _Msg({"input_tokens": 7, "output_tokens": 2})})()
    assert StepCallbackHandler._extract_usage(r) == (7, 2)


def test_extract_usage_none_when_absent():
    assert StepCallbackHandler._extract_usage(_Resp()) is None
