import json
import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_weave

from conftest import set_wandb_target_env


def _stdout(final_message: str, usage: dict[str, int] | None = None) -> str:
    usage_obj = usage or {"input_tokens": 1, "output_tokens": 1}
    return "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": final_message},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": usage_obj}),
        ]
    )


@pytest.fixture
def fake_weave(monkeypatch):
    class FakeWeave:
        def __init__(self):
            self.calls = []

        def init(self, _project):
            return None

        def op(self, **_kwargs):
            def deco(fn):
                def wrapped(*args, **kwargs):
                    result = fn(*args, **kwargs)
                    self.calls.append(result)
                    return result

                return wrapped

            return deco

    fake = FakeWeave()
    monkeypatch.setattr(codex_weave, "weave", fake)
    return fake


@pytest.fixture
def fake_subprocess_run(monkeypatch):
    def _install(
        *,
        final_message: str = "ok",
        returncode: int = 0,
        stderr: str = "",
        usage: dict[str, int] | None = None,
        raise_timeout: bool = False,
    ):
        def fake_run(cmd, capture_output, text, timeout):
            del cmd, capture_output, text
            if raise_timeout:
                raise codex_weave.subprocess.TimeoutExpired(
                    cmd="codex", timeout=timeout
                )
            return SimpleNamespace(
                returncode=returncode,
                stdout=_stdout(final_message, usage),
                stderr=stderr,
            )

        monkeypatch.setattr(codex_weave.subprocess, "run", fake_run)

    return _install


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


def test_parse_codex_jsonl_ignores_non_dict_events():
    parsed = codex_weave.parse_codex_jsonl(['"scalar"', "[]"])
    assert parsed.events == []
    assert parsed.final_message == ""
    assert parsed.usage == {}


def test_build_codex_command_includes_passed_options():
    cmd = codex_weave.build_codex_command(
        prompt="hello",
        model="o3",
        sandbox="workspace-write",
        profile="default",
        image_paths=["diagram.png"],
        codex_args=["--skip-git-repo-check"],
    )

    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--model" in cmd
    assert "--sandbox" in cmd
    assert "--profile" in cmd
    assert "--image" in cmd
    assert cmd[-1] == "hello"


def test_build_prompt_content_preserves_text_and_images(tmp_path):
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"fake-image")

    content = codex_weave.build_prompt_content(
        prompt="Explain this image",
        image_paths=[str(image_path)],
    )

    assert content == [
        {"type": "input_text", "text": "Explain this image"},
        {
            "type": "input_image",
            "image_path": codex_weave._sanitize_path(str(image_path)),
        },
    ]


def test_default_pii_redaction_fields_cover_input_content():
    assert "input_content" in codex_weave.DEFAULT_PII_REDACTION_FIELDS


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


def test_load_wandb_env_from_env_file_reads_supported_fields(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "WANDB_API_KEY=abc123",
                "WANDB_ENTITY=team-name",
                "WANDB_PROJECT=project-name",
                "WANDB_BASE_URL=https://example.invalid",
                "OTHER=value",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = codex_weave.load_wandb_env_from_env_file(env_file)

    assert loaded == {
        "WANDB_API_KEY": "abc123",
        "WANDB_ENTITY": "team-name",
        "WANDB_PROJECT": "project-name",
        "WANDB_BASE_URL": "https://example.invalid",
    }


def test_load_wandb_env_from_env_file_supports_common_dotenv_forms(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "export WANDB_API_KEY='abc123'",
                'WANDB_ENTITY="team-name"',
                "WANDB_PROJECT=project-name # inline comment",
                "WANDB_BASE_URL=https://example.invalid",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = codex_weave.load_wandb_env_from_env_file(env_file)

    assert loaded == {
        "WANDB_API_KEY": "abc123",
        "WANDB_ENTITY": "team-name",
        "WANDB_PROJECT": "project-name",
        "WANDB_BASE_URL": "https://example.invalid",
    }


def test_ensure_wandb_env_uses_dotenv_local_without_overwriting_env(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("WANDB_API_KEY", "env-key")
    monkeypatch.setenv("WANDB_ENTITY", "env-entity")
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "WANDB_API_KEY=file-key",
                "WANDB_ENTITY=file-entity",
                "WANDB_PROJECT=file-project",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = codex_weave.ensure_wandb_env()

    assert loaded["WANDB_API_KEY"] == "env-key"
    assert loaded["WANDB_ENTITY"] == "env-entity"
    assert loaded["WANDB_PROJECT"] == "file-project"
    assert os.environ["WANDB_API_KEY"] == "env-key"
    assert os.environ["WANDB_ENTITY"] == "env-entity"
    assert os.environ["WANDB_PROJECT"] == "file-project"


def test_resolve_weave_project_uses_cli_values_over_env(monkeypatch):
    monkeypatch.setenv("WANDB_ENTITY", "env-entity")
    monkeypatch.setenv("WANDB_PROJECT", "env-project")

    project_path = codex_weave.resolve_weave_project(
        entity="cli-entity",
        project="cli-project",
    )

    assert project_path == "cli-entity/cli-project"


def test_resolve_weave_project_reads_env_defaults(monkeypatch):
    monkeypatch.setenv("WANDB_ENTITY", "env-entity")
    monkeypatch.setenv("WANDB_PROJECT", "env-project")

    project_path = codex_weave.resolve_weave_project(entity=None, project=None)

    assert project_path == "env-entity/env-project"


def test_resolve_weave_project_requires_entity_and_project(monkeypatch):
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)

    try:
        codex_weave.resolve_weave_project(entity=None, project=None)
    except ValueError as exc:
        assert "--entity" in str(exc)
        assert "--project" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_resolve_weave_project_infers_entity_from_wandb_viewer(monkeypatch):
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.setenv("WANDB_PROJECT", "env-project")
    monkeypatch.setattr(
        codex_weave,
        "infer_wandb_entity",
        lambda: "viewer-entity",
    )

    project_path = codex_weave.resolve_weave_project(entity=None, project=None)

    assert project_path == "viewer-entity/env-project"


def test_resolve_weave_project_requires_project_even_with_inferred_entity(monkeypatch):
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    monkeypatch.setattr(
        codex_weave,
        "infer_wandb_entity",
        lambda: "viewer-entity",
    )

    try:
        codex_weave.resolve_weave_project(entity=None, project=None)
    except ValueError as exc:
        assert "WANDB_PROJECT" in str(exc)
        assert ".env.local" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_main_reads_wandb_api_key_from_dotenv_local(
    monkeypatch, capsys, tmp_path, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    set_wandb_target_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text("WANDB_API_KEY=x\n", encoding="utf-8")
    fake_subprocess_run(final_message="ok")

    rc = codex_weave.main(["--prompt", "Say only: ok"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "ok"


def test_main_reads_wandb_target_from_dotenv_local(
    monkeypatch, capsys, tmp_path, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_ENTITY", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "WANDB_API_KEY=x",
                "WANDB_ENTITY=file-entity",
                "WANDB_PROJECT=file-project",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_subprocess_run(final_message="ok")

    rc = codex_weave.main(["--prompt", "Say only: ok"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "ok"


def test_main_prints_final_message_and_propagates_exit(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(final_message="ok", returncode=0)

    rc = codex_weave.main(["--prompt", "Say only: ok"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "ok"


def test_main_traces_multimodal_prompt_content(
    monkeypatch, capsys, tmp_path, fake_weave, fake_subprocess_run
):
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"fake-image")
    fake_subprocess_run(final_message="ok", returncode=0)

    rc = codex_weave.main(
        [
            "--prompt",
            "Explain this image",
            "--image",
            str(image_path),
        ]
    )

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "ok"
    assert fake_weave.calls[-1]["input_content"] == [
        {"type": "input_text", "text": "Explain this image"},
        {
            "type": "input_image",
            "image_path": codex_weave._sanitize_path(str(image_path)),
        },
    ]
    assert fake_weave.calls[-1]["modalities"] == ["text", "image"]
    assert fake_weave.calls[-1]["prompt"] == "Explain this image"


def test_main_applies_builtin_pii_redaction_to_trace_payload(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(final_message="Contact user@example.com", returncode=0)
    monkeypatch.setattr(codex_weave, "configure_weave_pii_redaction", lambda: None)
    monkeypatch.setattr(
        codex_weave,
        "apply_builtin_pii_redaction",
        lambda value, enabled=True: {
            **value,
            "final_message": "[REDACTED]" if enabled else value["final_message"],
        },
    )

    rc = codex_weave.main(["--prompt", "Say only: ok"])

    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "[REDACTED]"


def test_main_guardrail_warn_does_not_fail_exit(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(final_message="bad", returncode=0)

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


def test_main_guardrail_fail_sets_nonzero_exit(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(final_message="bad", returncode=0)

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


def test_main_guardrail_require_json(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(final_message="not json", returncode=0)

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


def test_main_guardrail_require_section_and_paths(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(final_message="no citation here", returncode=0)

    rc = codex_weave.main(
        [
            "--prompt",
            "Return answer",
            "--required-section",
            "Summary",
            "--require-file-paths",
            "--guardrail-mode",
            "fail",
        ]
    )

    out = capsys.readouterr()
    assert rc == 3
    assert "Guardrail violations" in out.err


def test_main_times_out_with_clear_error(
    monkeypatch, capsys, fake_weave, fake_subprocess_run
):
    del fake_weave
    monkeypatch.setenv("WANDB_API_KEY", "x")
    set_wandb_target_env(monkeypatch)
    fake_subprocess_run(raise_timeout=True)

    rc = codex_weave.main(["--prompt", "hello", "--timeout-seconds", "1"])

    out = capsys.readouterr()
    assert rc == 124
    assert "timed out" in out.err
