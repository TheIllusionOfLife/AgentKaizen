"""Tests for _weave_compat module."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentkaizen._weave_compat import HAS_WEAVE, weave_init, weave_op


def test_has_weave_is_bool():
    assert isinstance(HAS_WEAVE, bool)


def test_weave_op_returns_decorator():
    decorator = weave_op(name="test_op")
    assert callable(decorator)


def test_weave_op_identity_when_no_weave(monkeypatch):
    import agentkaizen._weave_compat as compat

    monkeypatch.setattr(compat, "HAS_WEAVE", False)

    decorator = compat.weave_op(name="test_op")

    def my_fn(x):
        return x + 1

    wrapped = decorator(my_fn)
    assert wrapped is my_fn
    assert wrapped(5) == 6


def test_weave_init_noop_when_no_weave(monkeypatch):
    import agentkaizen._weave_compat as compat

    monkeypatch.setattr(compat, "HAS_WEAVE", False)
    # Should not raise
    compat.weave_init("test/project")


def test_weave_op_preserves_function_behavior():
    """weave_op decorator (with or without weave) should preserve function behavior."""
    decorator = weave_op()

    def add(a, b):
        return a + b

    wrapped = decorator(add)
    assert wrapped(2, 3) == 5
