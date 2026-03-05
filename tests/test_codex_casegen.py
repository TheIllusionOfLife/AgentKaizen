import pathlib
import sys

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


def test_deduplicate_cases_by_prompt_keeps_first():
    cases = [
        {"prompt": "p1", "max_chars": 10, "must_contain": [], "must_not_contain": []},
        {"prompt": "p1", "max_chars": 20, "must_contain": [], "must_not_contain": []},
        {"prompt": "p2", "max_chars": 30, "must_contain": [], "must_not_contain": []},
    ]

    deduped = codex_casegen.deduplicate_cases_by_prompt(cases)

    assert [c["prompt"] for c in deduped] == ["p1", "p2"]
    assert deduped[0]["max_chars"] == 10
