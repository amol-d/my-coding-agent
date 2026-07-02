"""Structured plan parsing + rendering, and that criteria reach coding/review."""

from agents.planning import _parse_plan, _render_plan_text
from agents.coding import _system_prompt


def test_parse_plan_normalizes_shape():
    raw = ('```json\n{"summary":"add health endpoint","approach":"new route",'
           '"files_to_touch":[{"path":"app/health.py","change":"add route"}],'
           '"acceptance_criteria":["GET /health returns 200"," "],'
           '"test_strategy":"unit test the route","risks":["none"]}\n```')
    plan = _parse_plan(raw)
    assert plan["summary"] == "add health endpoint"
    assert plan["acceptance_criteria"] == ["GET /health returns 200"]   # blanks dropped
    assert plan["files_to_touch"][0]["path"] == "app/health.py"
    assert plan["risks"] == ["none"]


def test_render_plan_text_includes_sections():
    plan = {
        "summary": "S", "approach": "A",
        "files_to_touch": [{"path": "x.py", "change": "edit"}, "y.py"],
        "acceptance_criteria": ["C1", "C2"],
        "test_strategy": "T", "risks": ["R1"],
    }
    md = _render_plan_text(plan)
    assert "## Summary" in md and "## Acceptance criteria" in md
    assert "- [ ] C1" in md and "- [ ] C2" in md
    assert "`x.py` — edit" in md and "`y.py`" in md
    assert "## Test strategy" in md and "## Risks" in md


def test_render_plan_text_empty_plan_is_empty():
    assert _render_plan_text({"summary": "", "acceptance_criteria": []}) == ""


def test_acceptance_criteria_reach_coding_prompt():
    sp = _system_prompt("arch", "plan text", ["GET /health returns 200", "handles empty body"], "")
    assert "ACCEPTANCE CRITERIA" in sp
    assert "GET /health returns 200" in sp and "handles empty body" in sp


def test_coding_prompt_without_criteria_omits_section():
    sp = _system_prompt("arch", "plan text", [], "")
    assert "ACCEPTANCE CRITERIA" not in sp
