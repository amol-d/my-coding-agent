"""Directive merging — natural-language directives override UI toggles when stated."""

from agents.ingest import _merge_options


def test_nl_true_overrides_ui_false():
    merged = _merge_options({"create_pr": True, "deploy": None},
                            {"create_pr": False, "deploy": False})
    assert merged == {"create_pr": True, "deploy": False}


def test_nl_false_overrides_ui_true():
    merged = _merge_options({"create_pr": False, "deploy": None},
                            {"create_pr": True, "deploy": False})
    assert merged == {"create_pr": False, "deploy": False}


def test_ui_used_when_nl_silent():
    merged = _merge_options({"create_pr": None, "deploy": None},
                            {"create_pr": True, "deploy": True})
    assert merged == {"create_pr": True, "deploy": True}


def test_defaults_false_when_both_silent():
    merged = _merge_options({"create_pr": None, "deploy": None}, {})
    assert merged == {"create_pr": False, "deploy": False}
