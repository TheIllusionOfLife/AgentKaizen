import json
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_weave


def test_parse_codex_jsonl_extracts_output_usage_and_keeps_events():
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "first"},
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "final"},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }
        ),
    ]

    parsed = codex_weave.parse_codex_jsonl(lines)

    assert parsed.final_message == "final"
    assert parsed.usage == {"input_tokens": 10, "output_tokens": 2}
    assert len(parsed.events) == 4
    assert parsed.malformed_lines == 0


def test_parse_codex_jsonl_tracks_malformed_lines():
    parsed = codex_weave.parse_codex_jsonl(["not-json", '{"type":"turn.started"}'])

    assert parsed.malformed_lines == 1
    assert len(parsed.events) == 1


def test_build_codex_command_includes_passed_options():
    cmd = codex_weave.build_codex_command(
        prompt="hello",
        model="o3",
        sandbox="workspace-write",
        profile="default",
        codex_args=["--skip-git-repo-check"],
    )

    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--model" in cmd
    assert "--sandbox" in cmd
    assert "--profile" in cmd
    assert cmd[-1] == "hello"


def test_main_returns_error_when_wandb_api_key_missing(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = codex_weave.main(["--prompt", "hello"])

    out = capsys.readouterr()
    assert rc == 2
    assert "WANDB_API_KEY" in out.err


def test_load_wandb_api_key_from_env_file(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text("WANDB_API_KEY=abc123\nOTHER=value\n", encoding="utf-8")

    loaded = codex_weave.load_wandb_api_key_from_env_file(env_file)

    assert loaded == "abc123"


def test_main_reads_wandb_api_key_from_dotenv_local(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text("WANDB_API_KEY=x\n", encoding="utf-8")

    class FakeWeave:
        def init(self, _project):
            return None

        def op(self):
            def deco(fn):
                return fn

            return deco

    def fake_run(cmd, capture_output, text):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "ok"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ),
            ]
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(codex_weave, "weave", FakeWeave())
    monkeypatch.setattr(codex_weave.subprocess, "run", fake_run)

    rc = codex_weave.main(["--prompt", "Say only: ok"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "ok"


def test_main_prints_final_message_and_propagates_exit(monkeypatch, capsys):
    monkeypatch.setenv("WANDB_API_KEY", "x")

    class FakeWeave:
        def init(self, _project):
            return None

        def op(self):
            def deco(fn):
                return fn

            return deco

    def fake_run(cmd, capture_output, text):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "ok"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ),
            ]
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(codex_weave, "weave", FakeWeave())
    monkeypatch.setattr(codex_weave.subprocess, "run", fake_run)

    rc = codex_weave.main(["--prompt", "Say only: ok"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "ok"


def test_main_guardrail_warn_does_not_fail_exit(monkeypatch, capsys):
    monkeypatch.setenv("WANDB_API_KEY", "x")

    class FakeWeave:
        def init(self, _project):
            return None

        def op(self):
            def deco(fn):
                return fn

            return deco

    def fake_run(cmd, capture_output, text):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "bad"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ),
            ]
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(codex_weave, "weave", FakeWeave())
    monkeypatch.setattr(codex_weave.subprocess, "run", fake_run)

    rc = codex_weave.main(
        [
            "--prompt",
            "Say only: ok",
            "--must-contain",
            "ok",
            "--guardrail-mode",
            "warn",
        ]
    )

    out = capsys.readouterr()
    assert rc == 0
    assert "Guardrail violations" in out.err


def test_main_guardrail_fail_sets_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setenv("WANDB_API_KEY", "x")

    class FakeWeave:
        def init(self, _project):
            return None

        def op(self):
            def deco(fn):
                return fn

            return deco

    def fake_run(cmd, capture_output, text):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "bad"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ),
            ]
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(codex_weave, "weave", FakeWeave())
    monkeypatch.setattr(codex_weave.subprocess, "run", fake_run)

    rc = codex_weave.main(
        [
            "--prompt",
            "Say only: ok",
            "--must-contain",
            "ok",
            "--guardrail-mode",
            "fail",
        ]
    )

    out = capsys.readouterr()
    assert rc == 3
    assert "Guardrail violations" in out.err


def test_main_guardrail_require_json(monkeypatch, capsys):
    monkeypatch.setenv("WANDB_API_KEY", "x")

    class FakeWeave:
        def init(self, _project):
            return None

        def op(self):
            def deco(fn):
                return fn

            return deco

    def fake_run(cmd, capture_output, text):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "not json"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ),
            ]
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(codex_weave, "weave", FakeWeave())
    monkeypatch.setattr(codex_weave.subprocess, "run", fake_run)

    rc = codex_weave.main(
        [
            "--prompt",
            "Return JSON",
            "--require-json",
            "--guardrail-mode",
            "fail",
        ]
    )

    out = capsys.readouterr()
    assert rc == 3
    assert "Guardrail violations" in out.err
