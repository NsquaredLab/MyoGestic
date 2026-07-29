"""Does the UI still fit when the window is narrow? Measured, not eyeballed.

ImGui's layout engine needs no window and no renderer — a context, a display size and a
frame are enough — so the real `ui()` methods can be run at a chosen width and asked what
they actually did. That is what these tests do.

The metric is ImGui's own: with a horizontal scrollbar enabled, `get_scroll_max_x()` is
the window's content extent minus its visible width, i.e. exactly how many pixels stuck
out. Zero means everything fit. It counts the whole frame rather than one item, which
matters because the failure mode here was a *row* being too wide, not any single control.

The bug this pins is worth stating, because it is easy to write again. ImGui's default
item width is a fraction of the **window**, and a label is drawn *after* its widget and is
not covered by `set_next_item_width`. Put two default-width widgets on one line with
`same_line` and the row is wider than the window — and widening the window makes the
overflow *worse*, not better. Before the fix this editor overflowed by 497 px at a 360 px
panel and 789 px at 1400 px.
"""

from __future__ import annotations

import pathlib

import pytest

from myogestic.controls import Capability
from myogestic.widgets import ControlMapEditor

imgui = pytest.importorskip("imgui_bundle").imgui

#: Widths worth checking: a cramped side panel, a half-screen window, a laptop, a wide
#: desktop. The first two are where a fixed-width row shows up; the last is where a
#: fraction-of-window one does.
WIDTHS = (320, 420, 560, 720, 1000, 1600)

FINGERS = ("thumb", "index", "middle", "ring", "little")
MANIFEST = [
    *(
        Capability(
            f"vhi.prediction.{digit}", "continuous", -1.0, 1.0, 0.0, channel=channel,
            stream_name="MyoGestic_Output",
        )
        for channel, digit in enumerate(FINGERS)
    ),
    Capability(
        "vhi.prediction.thumb.abduction", "continuous", -1.0, 1.0, 0.0, channel=1,
        stream_name="MyoGestic_Output",
    ),
    Capability(
        "vhi.control.gesture", "discrete", states=("Rest", "Fist"), rest_state="Rest",
    ),
]

#: A five-way weighted fan-out plus a 1:1 — the widest thing the editor has to draw, and
#: what `examples/controls/playground.toml` actually contains.
BUSY = "[dofs]\ncname = [\n" + "".join(
    f'  {{ target = "vhi.prediction.{digit}", weight = 0.6 }},\n' for digit in FINGERS
) + ']\nthumb_spread = "vhi.prediction.thumb.abduction"\n'


class _Client:
    def capabilities(self):
        return MANIFEST


@pytest.fixture(scope="module")
def _context():
    """One ImGui context for the module: creating them per test leaks the current one."""
    imgui.create_context()
    io = imgui.get_io()
    io.delta_time = 1 / 60
    io.fonts.add_font_default()
    # Without this ImGui asserts that the font atlas was never uploaded — true, since
    # there is no renderer, and irrelevant to layout.
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    yield io
    imgui.destroy_context()


#: Distinct window per measurement. A reused ImGui window keeps its content extent from
#: the previous frame, so sharing one made a test's result depend on what ran before it.
_probe = 0


def _overflow(io, width: int, draw) -> float:
    """Pixels of content that did not fit a panel `width` wide.

    The value is read from the **last** of several frames, not the widest. ImGui reports
    the content extent of the frame *before* the current one, so the first pass over a new
    window reports nothing useful and an early pass may still be settling a combo id or a
    wrap position.
    """
    global _probe
    _probe += 1
    io.display_size = imgui.ImVec2(width + 40, 1400)
    overflow = 0.0
    for _ in range(4):
        imgui.new_frame()
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1400))
        imgui.begin(
            f"panel{_probe}",
            None,
            imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.horizontal_scrollbar,
        )
        draw()
        overflow = imgui.get_scroll_max_x()
        imgui.end()
        imgui.end_frame()
    return overflow


def _editor(tmp_path: pathlib.Path, *, connected: bool = True) -> ControlMapEditor:
    path = tmp_path / "controls.toml"
    path.write_text(BUSY)
    editor = ControlMapEditor(path, client=_Client() if connected else None)
    editor.load()
    if connected:
        editor._connect()
    return editor


class TestTheEditorFitsTheWidthItIsGiven:
    @pytest.mark.parametrize("width", WIDTHS)
    def test_nothing_overflows(self, _context, tmp_path, width):
        editor = _editor(tmp_path)
        assert _overflow(_context, width, editor.ui) == pytest.approx(0.0, abs=1.0)

    @pytest.mark.parametrize("width", WIDTHS)
    def test_nothing_overflows_offline_either(self, _context, tmp_path, width):
        """Offline the picker is a text field, which is a different width entirely."""
        editor = _editor(tmp_path, connected=False)
        assert _overflow(_context, width, editor.ui) == pytest.approx(0.0, abs=1.0)

    def test_widening_the_window_does_not_make_it_worse(self, _context, tmp_path):
        """The signature of the original bug: overflow grew with width, because each
        item took a fraction of the window and three sat on one line."""
        editor = _editor(tmp_path)
        overflows = [_overflow(_context, w, editor.ui) for w in WIDTHS]
        assert overflows == sorted(overflows), overflows
        assert max(overflows) == pytest.approx(0.0, abs=1.0)

    @pytest.mark.parametrize("width", (320, 1600))
    def test_a_problem_list_does_not_overflow(self, _context, tmp_path, width):
        """The longest strings in the widget, and they only appear when something is
        wrong — which is the worst moment for them to be cut off."""
        editor = _editor(tmp_path)
        editor.add_control("clash", "vhi.prediction.thumb.flexion")
        assert editor.problems(), "expected the collision to be reported"
        assert _overflow(_context, width, editor.ui) == pytest.approx(0.0, abs=1.0)

    @pytest.mark.parametrize("width", (320, 1600))
    def test_a_long_path_does_not_overflow(self, _context, tmp_path, width):
        """The file path is shown in full and is as long as the user's disk makes it."""
        deep = tmp_path.joinpath(*(f"a-rather-long-directory-name-{n}" for n in range(6)))
        deep.mkdir(parents=True)
        path = deep / "controls.toml"
        path.write_text(BUSY)
        editor = ControlMapEditor(path, client=_Client())
        editor.load()
        editor._connect()
        assert _overflow(_context, width, editor.ui) == pytest.approx(0.0, abs=1.0)


def _widest_overhang(io, width: int, draw, watch) -> float:
    """How far past the panel's content edge the item drawn by `watch` reaches.

    A second metric, and the honest one for a full-width item. `_overflow` enables a
    horizontal scrollbar so ImGui will report a content extent — but that flag *changes*
    how a `-1` ("fill available") width resolves, so it reports a false overhang for the
    one item in this widget that uses it. This renders in a plain window and compares the
    item's own right edge to the window's content edge, which nothing perturbs.
    """
    seen = [0.0]
    original = getattr(imgui, watch)

    def spy(*args, **kwargs):
        result = original(*args, **kwargs)
        style = imgui.get_style()
        limit = (
            imgui.get_window_pos().x + imgui.get_window_width() - style.window_padding.x
        )
        seen[0] = imgui.get_item_rect_max().x - limit
        return result

    setattr(imgui, watch, spy)
    try:
        io.display_size = imgui.ImVec2(width + 40, 1400)
        for _ in range(4):
            imgui.new_frame()
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(width, 1400))
            imgui.begin("plain", None, imgui.WindowFlags_.no_saved_settings)
            draw()
            imgui.end()
            imgui.end_frame()
    finally:
        setattr(imgui, watch, original)
    return seen[0]


class TestTheTextViewFitsToo:
    """The free-text editor is the widest thing in the panel when it is open."""

    @staticmethod
    def _open(editor):
        editor._raw = editor.raw_text()

        def draw():
            original = imgui.collapsing_header
            imgui.collapsing_header = lambda label, *a, **k: True   # as if expanded
            try:
                editor.ui()
            finally:
                imgui.collapsing_header = original

        return draw

    @pytest.mark.parametrize("width", (240, *WIDTHS))
    def test_the_text_box_stays_inside_the_panel(self, _context, tmp_path, width):
        """Measured on the box's own edge, since it is the one `-1`-width item here."""
        editor = _editor(tmp_path)
        overhang = _widest_overhang(
            _context, width, self._open(editor), "input_text_multiline"
        )
        assert overhang <= 0.0, f"the text box is {overhang:.0f}px past the edge"

    @pytest.mark.parametrize("width", (240, *WIDTHS))
    def test_the_apply_buttons_stay_inside_the_panel(self, _context, tmp_path, width):
        """Three long labels; below ~420px they have to wrap rather than run off."""
        editor = _editor(tmp_path)
        overhang = _widest_overhang(_context, width, self._open(editor), "button")
        assert overhang <= 0.0, f"a button is {overhang:.0f}px past the edge"


class TestTheActionsStayReachable:
    """Save and Reload are the two things a user cannot work around."""

    @pytest.mark.parametrize("width", WIDTHS)
    def test_every_action_is_drawn_inside_the_panel(self, _context, tmp_path, width):
        editor = _editor(tmp_path)
        seen: list[tuple[str, float]] = []
        original = imgui.button

        def spy(label, *args, **kwargs):
            result = original(label, *args, **kwargs)
            seen.append((label, imgui.get_item_rect_max().x))
            return result

        imgui.button = spy
        try:
            io = _context
            io.display_size = imgui.ImVec2(width + 40, 1400)
            for _ in range(3):
                seen.clear()
                imgui.new_frame()
                imgui.set_next_window_pos(imgui.ImVec2(0, 0))
                imgui.set_next_window_size(imgui.ImVec2(width, 1400))
                imgui.begin(f"actions{width}", None, imgui.WindowFlags_.no_saved_settings)
                right = imgui.get_window_pos().x + imgui.get_window_width()
                editor.ui()
                imgui.end()
                imgui.end_frame()
        finally:
            imgui.button = original

        for label in ("Connect", "Save", "Reload", "Add control"):
            drawn = [x for name, x in seen if name == label]
            assert drawn, f"{label} was not drawn at {width} px"
            assert max(drawn) <= right + 1.0, (
                f"{label} extends past the panel at {width} px "
                f"({max(drawn):.0f} > {right:.0f})"
            )


class TestThePlaygroundPicksALayoutForTheWidth:
    """The reflow itself: proportions are chosen per frame, not fixed at construction."""

    @pytest.fixture(scope="class")
    def module(self):
        """The playground's layout constants, without importing the app.

        Importing it would build an LSL outlet and a gRPC client, and `launcher()` raises
        when no VHI is installed. The layout decision is the part under test, so it is
        read out of the source instead — which also keeps the two from drifting, since a
        renamed constant fails here.
        """
        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "examples"
            / "synthetic"
            / "vhi_playground.py"
        ).read_text()
        namespace: dict[str, object] = {}
        for line in source.splitlines():
            if line.startswith(("STACK_BELOW", "CONTROLS_W")):
                exec(line, namespace)  # noqa: S102 - two float literals from our own file
        return namespace

    def test_it_declares_a_breakpoint_and_a_control_column(self, module):
        assert module["STACK_BELOW"] > 0
        assert module["CONTROLS_W"] > 0

    def test_the_control_column_fits_inside_the_breakpoint(self, module):
        """Below the breakpoint the layout stacks, so the column must fit above it —
        with room left for the editor, or the split would be pointless."""
        assert module["CONTROLS_W"] < module["STACK_BELOW"] * 0.6

    def test_the_control_column_is_wide_enough_for_a_slider(self, module):
        """A slider narrower than this cannot be dragged to a useful value."""
        assert module["CONTROLS_W"] >= 260.0

    def test_both_layouts_are_declared_and_differ(self):
        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "examples"
            / "synthetic"
            / "vhi_playground.py"
        ).read_text()
        assert "WIDE = Grid(" in source
        assert "NARROW = Grid(" in source
        # The whole point: the wide layout gives the editor the slack, so the control
        # column is Px and the editor column is Fr.
        assert "col_width=[Px(CONTROLS_W), Fr(1)]" in source


class TestThePickerPopupIsBounded:
    """A combo popup sizes itself to its contents, so an unbounded child fills the screen.

    That is what happened: the search field inside the popup asked for `-1` (fill the
    available width), and in a popup with no size yet that is unbounded — the dropdown
    grew to the whole display. The constraint is applied on every frame the picker draws,
    whether or not the popup is open, so it can be checked without opening one.
    """

    @pytest.mark.parametrize("width", WIDTHS)
    def test_the_popup_is_constrained_before_it_opens(self, _context, tmp_path, width):
        editor = _editor(tmp_path)
        seen: list[tuple[float, float]] = []
        original = imgui.set_next_window_size_constraints

        def spy(size_min, size_max, *args, **kwargs):
            seen.append((size_min.x, size_max.x))
            return original(size_min, size_max, *args, **kwargs)

        imgui.set_next_window_size_constraints = spy
        try:
            _overflow(_context, width, editor.ui)
        finally:
            imgui.set_next_window_size_constraints = original

        assert seen, "the picker must constrain its popup"
        for lo, hi in seen:
            assert hi <= 640.0, f"popup allowed to reach {hi:.0f}px at a {width}px panel"
            assert lo <= hi, (lo, hi)

    def test_the_search_field_is_not_unbounded(self):
        """`set_next_item_width(-1)` inside the popup is the bug; keep it out."""
        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "myogestic"
            / "widgets"
            / "vhi"
            / "control_map_editor.py"
        ).read_text()
        popup = source.split("begin_combo")[1].split("end_combo")[0]
        assert "set_next_item_width(-1)" not in popup


class TestThePlaygroundsOwnSlidersFit:
    """The other half of the window: one slider per control in the file.

    A slider is the control that must not be squeezed — a 60-pixel one cannot be dragged
    to a useful value — so below a threshold its label moves above it, which buys the
    label's width back for the track. Tested against the real function, with the module's
    bus and levels stood in, because that sizing is where a squeezed slider would come
    from.
    """

    @pytest.fixture(scope="class")
    def playground(self):
        """The real module. Importable now that it uses `launchable()`."""
        return pytest.importorskip("examples.synthetic.vhi_playground")

    @pytest.fixture
    def wired(self, playground):
        """Stand in a bus and some controls, then put it back."""

        class Bus:
            def push(self, values):
                return values

        levels = dict.fromkeys(
            ("close", "thumb_spread", "a_rather_long_control_name"), 0.0
        )
        before = (playground.bus, dict(playground.levels))
        playground.bus, playground.levels = Bus(), levels
        yield playground
        playground.bus, playground.levels = before[0], before[1]

    @pytest.mark.parametrize("width", (240, *WIDTHS))
    def test_no_slider_reaches_past_the_panel(self, _context, wired, width):
        overhang = _widest_overhang(_context, width, wired._sliders_ui, "slider_float")
        assert overhang <= 0.0, f"a slider is {overhang:.0f}px past the edge at {width}px"

    @pytest.mark.parametrize("width", (240, *WIDTHS))
    def test_the_rest_button_stays_inside_the_panel(self, _context, wired, width):
        overhang = _widest_overhang(_context, width, wired._sliders_ui, "button")
        assert overhang <= 0.0, f"Rest is {overhang:.0f}px past the edge at {width}px"

    def test_a_slider_keeps_a_usable_track_when_narrow(self, _context, wired):
        """The point of moving the label above it: the track keeps the whole width."""
        widths: list[float] = []
        original = imgui.slider_float

        def spy(label, *args, **kwargs):
            result = original(label, *args, **kwargs)
            widths.append(imgui.get_item_rect_max().x - imgui.get_item_rect_min().x)
            return result

        imgui.slider_float = spy
        try:
            _overflow(_context, 260, wired._sliders_ui)
        finally:
            imgui.slider_float = original
        assert widths, "no sliders drawn"
        assert min(widths) >= 150.0, f"narrowest track was {min(widths):.0f}px"
