"""Graph routing decisions — pure functions that steer the whole pipeline."""

from graph import (
    route_after_ingest, route_after_git_ops, route_after_plan, route_after_coding,
    should_retry_code, should_proceed_commit, route_after_commit_gate,
    route_post_commit, route_post_pr, route_after_deploy_gate,
    MAX_CODE_RETRIES,
)


def test_route_after_coding_aborts_on_error():
    assert route_after_coding({}) == "review"
    assert route_after_coding({"error": "Could not create worktree: ..."}) == "abort"


def test_ingest_routes_git_ops_vs_plan():
    assert route_after_ingest({"intent_type": "git_ops"}) == "git_ops"
    assert route_after_ingest({"intent_type": "code_change"}) == "plan"
    assert route_after_ingest({"intent_type": "mixed"}) == "plan"
    assert route_after_ingest({"error": "x", "intent_type": "git_ops"}) == "abort"


def test_git_ops_gate():
    assert route_after_git_ops({"hitl_decisions": {"git_ops": "approved"}}) == "pr"
    assert route_after_git_ops({"hitl_decisions": {"git_ops": "override"}}) == "pr"
    assert route_after_git_ops({"hitl_decisions": {"git_ops": "abort"}}) == "end"
    assert route_after_git_ops({"error": "x"}) == "end"


def test_plan_gate():
    assert route_after_plan({"hitl_decisions": {"plan": "approved"}}) == "coding"
    assert route_after_plan({"hitl_decisions": {"plan": "override"}}) == "coding"
    assert route_after_plan({"hitl_decisions": {"plan": "rejected"}}) == "revise"
    assert route_after_plan({"error": "x"}) == "abort"


def test_should_retry_code():
    assert should_retry_code({"hitl_decisions": {"code_review": "rejected"}}) == "retry_code"
    assert should_retry_code({"hitl_decisions": {"code_review": "approved"}}) == "proceed_to_tests"
    assert should_retry_code({"error": "x"}) == "proceed_to_tests"
    # budget exhausted -> stop retrying even on rejection
    assert should_retry_code({"hitl_decisions": {"code_review": "rejected"},
                              "code_retry_count": MAX_CODE_RETRIES}) == "proceed_to_tests"


def test_should_proceed_commit():
    assert should_proceed_commit({"hitl_decisions": {"test_review": "approved"}}) == "commit_gate"
    assert should_proceed_commit({"hitl_decisions": {"test_review": "override"}}) == "commit_gate"
    assert should_proceed_commit({"hitl_decisions": {"test_review": "rejected"}}) == "retry_code"
    assert should_proceed_commit({"hitl_decisions": {"test_review": "abort"}}) == "abort"
    assert should_proceed_commit({"error": "x"}) == "commit_gate"


def test_commit_gate():
    assert route_after_commit_gate({"hitl_decisions": {"commit": "approved"}}) == "commit"
    assert route_after_commit_gate({"hitl_decisions": {"commit": "abort"}}) == "abort"
    assert route_after_commit_gate({"error": "x"}) == "abort"


def test_post_commit_options():
    assert route_post_commit({"options": {"create_pr": True}}) == "pr"
    assert route_post_commit({"options": {"deploy": True}}) == "deploy_gate"
    assert route_post_commit({"options": {"create_pr": True, "deploy": True}}) == "pr"
    assert route_post_commit({"options": {}}) == "end"
    assert route_post_commit({"error": "x", "options": {"create_pr": True}}) == "end"


def test_post_pr_options():
    assert route_post_pr({"options": {"deploy": True}}) == "deploy_gate"
    assert route_post_pr({"options": {}}) == "end"
    assert route_post_pr({"error": "x", "options": {"deploy": True}}) == "end"


def test_deploy_gate():
    assert route_after_deploy_gate({"hitl_decisions": {"deploy_gate": "approved"}}) == "deploy"
    assert route_after_deploy_gate({"hitl_decisions": {"deploy_gate": "abort"}}) == "end"
    assert route_after_deploy_gate({"error": "x"}) == "end"
