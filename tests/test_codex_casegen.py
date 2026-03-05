import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_casegen


def test_build_case_from_call_output():
    call_output = {
        "prompt": "Explain repo",
        "final_message": "This repo tracks codex outputs.",
        "returncode": 0,
    }

    case = codex_casegen.build_case_from_call_output(call_output, max_chars_padding=20)

    assert case["prompt"] == "Explain repo"
    assert case["must_contain"] == []
    assert case["must_not_contain"] == []
    assert case["max_chars"] == len("This repo tracks codex outputs.") + 20
    assert case["require_json"] is False
    assert case["required_sections"] == []
    assert case["require_file_paths"] is False


def test_deduplicate_cases_by_prompt_keeps_first():
    cases = [
        {"prompt": "p1", "max_chars": 10, "must_contain": [], "must_not_contain": []},
        {"prompt": "p1", "max_chars": 20, "must_contain": [], "must_not_contain": []},
        {"prompt": "p2", "max_chars": 30, "must_contain": [], "must_not_contain": []},
    ]

    deduped = codex_casegen.deduplicate_cases_by_prompt(cases)

    assert [c["prompt"] for c in deduped] == ["p1", "p2"]
    assert deduped[0]["max_chars"] == 10


def test_redact_prompt_applies_patterns():
    prompt = "token=abc123 and email user@example.com"
    redacted = codex_casegen.redact_prompt(prompt, [r"abc123", r"[\w.-]+@[\w.-]+"])
    assert "[REDACTED]" in redacted
    assert "abc123" not in redacted
    assert "user@example.com" not in redacted


def test_fetch_recent_codex_cases_dedupes_on_the_fly(monkeypatch):
    calls = [
        SimpleNamespace(
            op_name="run_codex_exec_traced",
            output={"prompt": "dup", "final_message": "a", "returncode": 0},
        ),
        SimpleNamespace(
            op_name="run_codex_exec_traced",
            output={"prompt": "dup", "final_message": "b", "returncode": 0},
        ),
        SimpleNamespace(
            op_name="run_codex_exec_traced",
            output={"prompt": "unique", "final_message": "c", "returncode": 0},
        ),
    ]

    class FakeClient:
        def get_calls(self, **_kwargs):
            return calls

    monkeypatch.setattr(
        codex_casegen.weave_client_context, "get_weave_client", lambda: FakeClient()
    )

    result = codex_casegen.fetch_recent_codex_cases(
        limit=2,
        op_substring="run_codex_exec_traced",
        max_chars_padding=1,
        redact_patterns=[],
    )

    assert [case["prompt"] for case in result] == ["dup", "unique"]
