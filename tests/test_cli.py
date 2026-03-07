"""Tests for agentkaizen.cli subcommand dispatch."""

from __future__ import annotations

from agentkaizen import cli


def _make_recorder(return_code: int = 0):
    """Return a fake main() that records its argv and returns return_code."""
    calls: list[list[str] | None] = []

    def fake_main(argv=None):
        calls.append(argv)
        return return_code

    fake_main.calls = calls  # type: ignore[attr-defined]
    return fake_main


# ---------------------------------------------------------------------------
# Top-level help / no args
# ---------------------------------------------------------------------------


def test_cli_no_args_prints_help_and_returns_nonzero(capsys):
    rc = cli.main([])
    out = capsys.readouterr()
    assert rc != 0
    assert "agentkaizen" in out.err


def test_cli_help_flag_returns_zero(capsys):
    rc = cli.main(["--help"])
    out = capsys.readouterr()
    assert rc == 0
    assert "agentkaizen" in (out.out + out.err)


# ---------------------------------------------------------------------------
# run subcommand
# ---------------------------------------------------------------------------


def test_cli_run_dispatches_to_oneshot(monkeypatch):
    fake = _make_recorder()
    monkeypatch.setattr(cli, "_run_main", fake)
    rc = cli.main(["run", "--prompt", "hello"])
    assert rc == 0
    assert fake.calls == [["--prompt", "hello"]]


# ---------------------------------------------------------------------------
# eval subcommand
# ---------------------------------------------------------------------------


def test_cli_eval_dispatches_to_evals(monkeypatch):
    fake = _make_recorder()
    monkeypatch.setattr(cli, "_eval_main", fake)
    rc = cli.main(["eval", "--cases", "evals/cases"])
    assert rc == 0
    assert fake.calls == [["--cases", "evals/cases"]]


def test_cli_eval_casegen_dispatches_to_casegen(monkeypatch):
    fake = _make_recorder()
    monkeypatch.setattr(cli, "_casegen_main", fake)
    rc = cli.main(["eval", "casegen", "--limit", "5"])
    assert rc == 0
    assert fake.calls == [["--limit", "5"]]


# ---------------------------------------------------------------------------
# session subcommand
# ---------------------------------------------------------------------------


def test_cli_session_sync_dispatches_to_session_sync(monkeypatch):
    fake = _make_recorder()
    monkeypatch.setattr(cli, "_session_sync_main", fake)
    rc = cli.main(["session", "sync", "--once"])
    assert rc == 0
    assert fake.calls == [["--once"]]


def test_cli_session_score_dispatches_to_session_score(monkeypatch):
    fake = _make_recorder()
    monkeypatch.setattr(cli, "_session_score_main", fake)
    rc = cli.main(["session", "score", "--trace-file", "trace.json"])
    assert rc == 0
    assert fake.calls == [["--trace-file", "trace.json"]]


def test_cli_session_no_subcommand_shows_help_and_fails(capsys):
    rc = cli.main(["session"])
    out = capsys.readouterr()
    assert rc != 0
    assert "session" in (out.out + out.err).lower()


def test_cli_session_help_flag_returns_zero(capsys):
    rc = cli.main(["session", "--help"])
    out = capsys.readouterr()
    assert rc == 0
    assert "session" in (out.out + out.err).lower()


def test_cli_session_dash_h_flag_returns_zero(capsys):
    rc = cli.main(["session", "-h"])
    out = capsys.readouterr()
    assert rc == 0
    assert "session" in (out.out + out.err).lower()


# ---------------------------------------------------------------------------
# Unknown subcommand
# ---------------------------------------------------------------------------


def test_cli_unknown_subcommand_returns_nonzero(capsys):
    rc = cli.main(["notacommand"])
    capsys.readouterr()
    assert rc != 0


# ---------------------------------------------------------------------------
# Propagation of exit codes
# ---------------------------------------------------------------------------


def test_cli_propagates_nonzero_exit_code(monkeypatch):
    fake = _make_recorder(return_code=2)
    monkeypatch.setattr(cli, "_run_main", fake)
    rc = cli.main(["run", "--prompt", "x"])
    assert rc == 2
