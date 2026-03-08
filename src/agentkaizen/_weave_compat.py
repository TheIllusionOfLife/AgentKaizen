"""Weave availability check with thin pass-through shims."""

from __future__ import annotations

try:
    import weave as _weave

    HAS_WEAVE = True
except ImportError:
    _weave = None  # type: ignore[assignment]
    HAS_WEAVE = False


def weave_init(project_path: str) -> None:
    """Call weave.init() if available, otherwise no-op."""
    if HAS_WEAVE:
        _weave.init(project_path)


def weave_op(**kwargs):  # noqa: ANN201
    """Return weave.op() decorator if available, otherwise identity decorator."""
    if HAS_WEAVE:
        return _weave.op(**kwargs)
    return lambda fn: fn
