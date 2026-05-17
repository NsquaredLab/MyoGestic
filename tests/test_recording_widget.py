"""Tests for myogestic.widgets.recording.

Tests the pure-logic helpers — full widget rendering needs ImGui context.
"""

from myogestic.widgets.recording import _safe_label_index


def test_safe_label_index_in_range():
    assert _safe_label_index(0, 3) == 0
    assert _safe_label_index(2, 3) == 2


def test_safe_label_index_negative():
    """-1 means 'no class selected' — preserved as-is."""
    assert _safe_label_index(-1, 3) == -1


def test_safe_label_index_out_of_range_clamps_to_negative_one():
    """Stale index from a previous CLASSES list is reset to -1, not silently
    coerced into a different class. The bug this guards against: a session
    with CLASSES=['A','B','C','D'] leaves current_label=3, then user reduces
    to CLASSES=['A','B'] — without this clamp, label 3 would wrap or write
    a class index that doesn't exist."""
    assert _safe_label_index(3, 2) == -1
    assert _safe_label_index(99, 5) == -1
    assert _safe_label_index(-2, 3) == -1   # weird negatives also rejected


def test_safe_label_index_zero_classes():
    """Edge: no class_names — every index is invalid."""
    assert _safe_label_index(0, 0) == -1
    assert _safe_label_index(-1, 0) == -1


def test_state_colors_default_entries():
    """Core states are populated; ml states get added by myogestic.ml.widgets."""
    from myogestic.core import AppState
    from myogestic.widgets.recording import STATE_COLORS

    assert AppState.IDLE in STATE_COLORS
    assert AppState.RECORDING in STATE_COLORS
