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

    p = PostProcessor(hz=32, compact=False)

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
    p = PostProcessor(hz=32, compact=False)
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


@pytest.mark.parametrize("key", ["one_euro", "gaussian", "identity"])
@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_compact_row_and_popover_keep_all_filter_controls(imgui_frame, monkeypatch, key, scale):
    from imgui_bundle import icons_fontawesome_6 as fa
    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets.panels import filter_processor

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(1400, 1000)
    p = PostProcessor(hz=32, compact=True)
    p._select(key)
    spec = next(s for s in BUILTIN_FILTERS if s.key == key)
    texts, sliders, buttons, combos = [], [], [], []
    text, colored = imgui.text_unformatted, imgui.text_colored

    def plain(label):
        texts.append(label)
        text(label)

    def color(tone, label):
        texts.append(label)
        colored(tone, label)

    monkeypatch.setattr(imgui, "text_unformatted", plain)
    monkeypatch.setattr(imgui, "text_colored", color)
    real_combo, real_button = imgui.combo, imgui.small_button
    click = {"value": False}
    selected = []
    push, pop = filter_processor.push_selected, filter_processor.pop_selected

    def select():
        selected.append("push")
        push()

    def unselect():
        selected.append("pop")
        pop()

    monkeypatch.setattr(filter_processor, "push_selected", select)
    monkeypatch.setattr(filter_processor, "pop_selected", unselect)

    def combo(label, current, names):
        combos.append(names)
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = real_combo(label, current, names)
        assert imgui.get_item_rect_max().x <= right + 1
        return result

    def button(label):
        buttons.append(label)
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        real_button(label)
        assert imgui.get_item_rect_max().x <= right + 1
        return click["value"] and label.startswith(fa.ICON_FA_SLIDERS)

    for name in ("slider_float", "slider_int"):
        real = getattr(imgui, name)

        def slider(label, *args, real=real):
            sliders.append(label)
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = real(label, *args)
            assert imgui.get_item_rect_max().x <= right + 1
            return result

        monkeypatch.setattr(imgui, name, slider)
    monkeypatch.setattr(imgui, "combo", combo)
    monkeypatch.setattr(imgui, "small_button", button)
    def draw():
        imgui.begin_child("compact-narrow", imgui.ImVec2(320, 380))
        p.ui()
        imgui.end_child()

    imgui_frame(draw)
    assert combos == [[s.name for s in BUILTIN_FILTERS]]
    assert "Smoothing" in texts
    assert any(b.startswith(fa.ICON_FA_SLIDERS) for b in buttons)
    assert sliders == []
    assert selected == []
    if key == "one_euro":
        assert "159 ms" in texts
    click["value"] = True
    imgui_frame(draw)
    click["value"] = False
    sliders.clear()
    imgui_frame(draw)
    assert sliders == [f"##{param.key}" for param in spec.params]
    assert any(b.startswith(fa.ICON_FA_ROTATE_LEFT) for b in buttons)
    assert spec.description in texts
    assert selected == ["push", "pop"]


def test_post_processor_defaults_to_compact():
    assert PostProcessor()._compact is True
    assert PostProcessor(compact=False)._compact is False


@pytest.mark.parametrize("factory", [FilterProcessor, lambda: PostProcessor(compact=False)])
@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("width", [320, 620])
def test_full_panel_has_captioned_sliders_and_mono_values(
    imgui_frame, monkeypatch, factory, scale, width,
):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets.panels import filter_processor as module

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    processor = factory()
    processor._select("gaussian")
    captions, values, headers = {}, [], []
    text = imgui.text_unformatted
    mono, header = module.mono_text, module.panel_header_button

    def caption(label):
        captions[label] = imgui.get_cursor_screen_pos().y
        text(label)

    def value(label, *args):
        values.append(label)
        mono(label, *args)

    def reset(*args, **kwargs):
        headers.append(args)
        return header(*args, **kwargs)

    monkeypatch.setattr(imgui, "text_unformatted", caption)
    monkeypatch.setattr(module, "mono_text", value)
    monkeypatch.setattr(module, "panel_header_button", reset)
    for name in ("slider_int", "slider_float"):
        real = getattr(imgui, name)

        def slider(label, *args, real=real):
            param = next(p for p in processor._by_key["gaussian"].params if label == f"##{p.key}")
            assert param.label in captions, "each slider needs its caption above it"
            assert imgui.get_cursor_screen_pos().y > captions[param.label]
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = real(label, *args)
            assert imgui.get_item_rect_max().x <= right + 1
            return result

        monkeypatch.setattr(imgui, name, slider)

    def draw():
        imgui.begin_child("parameters", imgui.ImVec2(width, 380))
        processor.ui()
        imgui.end_child()

    imgui_frame(draw)
    assert len(headers) == 1
    assert "50 ms" in values
    assert "5" in values and "1.00" in values
