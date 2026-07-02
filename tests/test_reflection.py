"""The reflect loop — auto-routing on blocking review / failing tests, and the
reflection-notes assembly the coding node acts on."""

from graph import route_after_review, route_after_testing, MAX_CODE_RETRIES
from agents.coding import _reflection_notes

BLOCK = [{"file": "a.py", "severity": "blocking", "comment": "null deref"}]
SUGG = [{"file": "a.py", "severity": "suggestion", "comment": "rename var"}]


def test_review_reflects_only_on_blocking():
    assert route_after_review({"review_comments": BLOCK, "code_retry_count": 0}) == "reflect"
    assert route_after_review({"review_comments": SUGG}) == "human"
    assert route_after_review({"review_comments": []}) == "human"


def test_review_respects_budget_and_errors():
    assert route_after_review({"review_comments": BLOCK,
                               "code_retry_count": MAX_CODE_RETRIES}) == "human"
    assert route_after_review({"review_comments": BLOCK, "error": "x"}) == "human"


def test_testing_reflects_on_real_failure_only():
    assert route_after_testing({"test_results": {"status": "failed"}}) == "reflect"
    for status in ("passed", "no_tests", "skipped", "runner_unavailable"):
        assert route_after_testing({"test_results": {"status": status}}) == "human"


def test_testing_respects_budget_and_errors():
    assert route_after_testing({"test_results": {"status": "failed"},
                                "code_retry_count": MAX_CODE_RETRIES}) == "human"
    assert route_after_testing({"test_results": {"status": "failed"}, "error": "x"}) == "human"


def test_reflection_notes_empty_on_first_pass():
    assert _reflection_notes({}) == ""


def test_reflection_notes_includes_blocking_only():
    assert "null deref" in _reflection_notes({"review_comments": BLOCK})
    assert _reflection_notes({"review_comments": SUGG}) == ""   # suggestions excluded


def test_reflection_notes_includes_test_failure():
    n = _reflection_notes({"test_results": {"status": "failed", "output": "AssertionError x",
                                            "test_command": "pytest -q"}})
    assert "FAILED" in n and "AssertionError x" in n and "pytest -q" in n


def test_reflection_notes_combines_all_signals():
    n = _reflection_notes({
        "review_comments": BLOCK,
        "test_results": {"status": "failed", "output": "e"},
        "hitl_feedback": {"code_review": "make it async"},
    })
    assert "BLOCKING" in n and "FAILED" in n and "REJECTED" in n and "make it async" in n
