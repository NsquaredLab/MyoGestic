"""Tests for FilterProcessor / PostProcessor and the chain() composite.

ImGui rendering needs a live context, so we exercise the pure state /
parameter / composition logic here (not ``.ui()``).
"""

import numpy as np
import pytest

from myogestic.outputs import chain
from myogestic.outputs.filters import GaussianFilter, IdentityFilter, OneEuroFilter
from myogestic.widgets import (
    BUILTIN_FILTERS,
    FilterParam,
    FilterProcessor,
    FilterSpec,
    PostProcessor,
)

# --- PostProcessor preset ---------------------------------------------------


def test_postprocessor_defaults_to_one_euro():
    p = PostProcessor(hz=32)
    assert p.name == "one_euro"
    assert isinstance(p.filter, OneEuroFilter)
    assert p.filter.hz == 32.0


def test_postprocessor_callable_reset_and_timestamp():
    p = PostProcessor(hz=50)
    p(np.array([1.0]))
    p(np.array([2.0]))
    assert p.filter._x_prev is not None  # type: ignore
    p.reset()
    assert p.filter._x_prev is None  # type: ignore
    out = p(np.array([10.0], dtype=np.float32), timestamp=0.1)
    assert out.shape == (1,)


# --- FilterProcessor: selection + validation --------------------------------


def test_default_none_selects_first_spec():
    assert FilterProcessor().name == BUILTIN_FILTERS[0].key  # "identity"


def test_explicit_default_constructs_named_filter():
    assert isinstance(FilterProcessor(default="gaussian").filter, GaussianFilter)
    assert isinstance(FilterProcessor(default="identity").filter, IdentityFilter)


@pytest.mark.parametrize(
    "bad",
    [
        lambda: FilterProcessor([]),  # empty palette
        lambda: FilterProcessor(default="kalman"),  # unknown default
        lambda: FilterProcessor(  # duplicate spec keys
            [
                FilterSpec("a", "A", lambda **k: IdentityFilter()),
                FilterSpec("a", "B", lambda **k: IdentityFilter()),
            ]
        ),
        lambda: FilterProcessor(  # param default out of range
            [
                FilterSpec(
                    "g", "G", lambda **k: IdentityFilter(), params=(FilterParam("p", "p", 0, 1, 5),)
                )
            ]
        ),
    ],
)
def test_validation_rejects(bad):
    with pytest.raises(ValueError):
        bad()


# --- FilterProcessor: live tuning semantics ---------------------------------


def test_one_euro_reconfigures_in_place():
    """Tuning one_euro mutates the existing filter (preserves smoothing history)."""
    p = PostProcessor(hz=32)
    before = p.filter
    p._apply_param("beta", 0.05)
    assert p.filter is before
    assert p.filter.beta == 0.05  # type: ignore


def test_gaussian_rebuilds_on_change():
    """Tuning gaussian rebuilds (its kernel weights are derived at construction)."""
    p = FilterProcessor(default="gaussian")
    before = p.filter
    p._apply_param("sigma", 2.0)
    assert p.filter is not before


def test_param_values_persist_across_selection():
    p = FilterProcessor(default="gaussian")
    p._apply_param("sigma", 3.0)
    p._select("identity")
    p._select("gaussian")
    assert p.filter.sigma == 3.0  # type: ignore  # value remembered, filter fresh


def test_custom_filterspec():
    seen = {}

    def build(*, hz, gain):
        seen["gain"] = gain
        return GaussianFilter(int(gain))

    spec = FilterSpec(
        "my", "My", build, params=(FilterParam("gain", "gain", 1, 10, 3, kind="int"),)
    )
    p = FilterProcessor([*BUILTIN_FILTERS, spec], hz=10, default="my")
    assert isinstance(p.filter, GaussianFilter)
    assert seen["gain"] == 3


# --- chain() ----------------------------------------------------------------


class _Add:
    def __init__(self, k):
        self.k = k

    def reset(self):
        pass

    def __call__(self, x, timestamp=None):
        return x + self.k


def test_chain_composes_left_to_right():
    # (x + 1) then * 2
    class _Scale(_Add):
        def __call__(self, x, timestamp=None):
            return x * self.k

    c = chain(_Add(1), _Scale(2))
    assert np.allclose(c(np.array([1.0, 2.0])), [4.0, 6.0])


def test_chain_forwards_timestamp_and_resets_all():
    seen, resets = [], []

    class _F:
        def __init__(self, i):
            self.i = i

        def reset(self):
            resets.append(self.i)

        def __call__(self, x, timestamp=None):
            seen.append((self.i, timestamp))
            return x

    c = chain(_F(0), _F(1))
    c(np.array([1.0]), timestamp=3.5)
    assert seen == [(0, 3.5), (1, 3.5)]
    c.reset()
    assert resets == [0, 1]


def test_empty_chain_is_identity():
    x = np.array([5.0, 6.0])
    assert np.array_equal(chain()(x), x)


# --- headless render (uses the shared `imgui_frame` fixture from conftest) ---


def test_ui_renders_all_branches(imgui_frame):
    """Every filter's panel (buttons + sliders + details) renders without error.

    Guards the render path — e.g. the button-wrap math — that the pure-logic
    tests can't reach.
    """
    p = PostProcessor(hz=32)
    for key in ("one_euro", "gaussian", "identity"):
        p._select(key)
        imgui_frame(p.ui)
    # Tuning paths: reconfigure (one_euro) and rebuild (gaussian).
    p._select("one_euro")
    p._apply_param("beta", 0.05)
    imgui_frame(p.ui)
    # A wide palette exercises the dropdown with many entries.
    extras = [FilterSpec(f"x{i}", f"F{i}", lambda **k: IdentityFilter()) for i in range(8)]
    wide = FilterProcessor([*BUILTIN_FILTERS, *extras], hz=32, widget_id="wide")
    imgui_frame(wide.ui)


def test_ui_survives_midframe_selection_switch(imgui_frame):
    """A filter switch *during* a render must pair the new filter's sliders
    with its own value dict — not a stale spec's keys (regression: KeyError)."""

    class _Switch(FilterProcessor):
        def _render_combo(self):  # simulate the user picking a filter this frame
            self._select("gaussian")

    p = _Switch(default="one_euro")  # header renders one_euro, then it switches
    imgui_frame(p.ui)  # must not raise (params re-fetch the current selection)
    assert p.name == "gaussian"


def test_ui_renders_when_too_narrow_for_inline_reset(imgui_frame):
    """In a panel too narrow for icon + Reset side by side, Reset drops to its
    own line below — the whole panel must still render (Reset stays reachable)."""
    from imgui_bundle import imgui

    p = PostProcessor(hz=32)

    def draw():
        imgui.begin_child("narrow", imgui.ImVec2(40.0, 220.0))
        p.ui()
        imgui.end_child()

    imgui_frame(draw)


def test_reset_button_stays_visible_at_every_width(imgui_frame, monkeypatch):
    """Reset is prioritized: it must render fully *inside* the panel at any
    width (regression: the delay text once pushed Reset off-screen)."""
    from imgui_bundle import icons_fontawesome_6 as fa
    from imgui_bundle import imgui

    seen: list[float] = []
    real = imgui.small_button

    def spy(label, *a, **k):
        seen.append(imgui.get_cursor_screen_pos().x)  # left edge of the button
        return real(label, *a, **k)

    monkeypatch.setattr(imgui, "small_button", spy)
    p = PostProcessor(hz=32)
    results: list[tuple[int, float, float, float]] = []

    for w in (300, 250, 180, 130, 100, 45):

        def draw(w=w):
            imgui.begin_child("c", imgui.ImVec2(float(w), 300))
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            reset_w = (
                imgui.calc_text_size(fa.ICON_FA_ROTATE_LEFT).x
                + imgui.get_style().frame_padding.x * 2
            )
            seen.clear()
            p.ui()
            imgui.end_child()
            results.append((w, seen[-1], right, reset_w))

        imgui_frame(draw)

    for w, reset_x, right, reset_w in results:
        assert reset_x + reset_w <= right + 1.0, f"Reset off-screen at {w}px"
