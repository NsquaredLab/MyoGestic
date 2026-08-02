"""Does the UI still fit when the window is narrow? Measured, not eyeballed.

ImGui's layout engine needs no window and no target — a context, a display size and a
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
from myogestic.widgets.common import label_column

imgui = pytest.importorskip("imgui_bundle").imgui

#: Widths worth checking: a cramped side panel, a half-screen window, a laptop, a wide
#: desktop. The first two are where a fixed-width row shows up; the last is where a
#: fraction-of-window one does.
WIDTHS = (320, 420, 560, 720, 1000, 1600)

FINGERS = ("thumb", "index", "middle", "ring", "little")
MANIFEST = [
    *(
        Capability(f"vhi.prediction.{digit}", "continuous", -1.0, 1.0, 0.0)
        for digit in FINGERS
    ),
    Capability("vhi.prediction.thumb.abduction", "continuous", -1.0, 1.0, 0.0),
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
    # there is no target, and irrelevant to layout.
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

    @pytest.mark.parametrize("width", WIDTHS)
    def test_the_conflict_banner_fits_too(self, _context, tmp_path, width):
        """It only draws when the file changed under unsaved edits, so the width sweep
        above never reaches it — and it adds two more buttons to an already-full row."""
        editor = _editor(tmp_path)
        editor._conflict = True
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
        editor.add_control("clash", "vhi.prediction.thumb")
        # `thumb` is already mapped by BUSY, so a second alias reaching it is the
        # collision, not an unknown address. Asserting the *reason* is what stops this
        # passing on the wrong error.
        assert any("same control" in problem for problem in editor.problems()), (
            editor.problems()
        )
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

        # Matched as a suffix: the labels now carry a leading glyph (`FLOPPY_DISK  Save`),
        # and what this class is about is that the *action* is reachable, not how it is
        # spelled. Save-as is deliberately absent — Save covers the untitled case by routing
        # to the same dialog, so it is the one that cannot be worked around.
        for label in ("Connect", "Save", "Reload", "Add control"):
            drawn = [x for name, x in seen if name.endswith(label)]
            assert drawn, f"{label} was not drawn at {width} px"
            assert max(drawn) <= right + 1.0, (
                f"{label} extends past the panel at {width} px "
                f"({max(drawn):.0f} > {right:.0f})"
            )



class TestAddControlSitsWithTheControls:
    """`Add control` is drawn under the last control row, not in the file-command row.

    Placement is the whole signal. Beside `Save` / `Save as...` / `Reload` it reads as a
    fourth thing you do to the *file*; under the rows it reads as what it is — one more row,
    appended where the new row will appear. It is also the only control on screen when the
    map is empty, which is exactly when it is the thing to press.

    Asserted by y rather than by source order, because y is the claim: this is about where the
    button *appears*. Mutation-checked — moving the call back up beside `Reload` fails both
    assertions. (A stray `same_line()` at the current call site does not, and cannot: the row
    above ends with an item that has already broken the line, so there is no line to join.)
    """

    @staticmethod
    def _ys(io, editor) -> list[tuple[str, float]]:
        """Every button's label and the y it was drawn at, over one settled frame."""
        seen: list[tuple[str, float]] = []
        original = imgui.button

        def spy(label, *args, **kwargs):
            result = original(label, *args, **kwargs)
            seen.append((label, imgui.get_item_rect_min().y))
            return result

        imgui.button = spy
        try:
            io.display_size = imgui.ImVec2(900, 1400)
            for _ in range(3):  # ImGui needs a frame to settle its layout
                seen.clear()
                imgui.new_frame()
                imgui.set_next_window_pos(imgui.ImVec2(0, 0))
                imgui.set_next_window_size(imgui.ImVec2(860, 1400))
                imgui.begin("place", None, imgui.WindowFlags_.no_saved_settings)
                editor.ui()
                imgui.end()
                imgui.end_frame()
        finally:
            imgui.button = original
        return seen

    @staticmethod
    def _at(seen, suffix) -> list[float]:
        drawn = [y for label, y in seen if label.endswith(suffix)]
        assert drawn, f"{suffix!r} was not drawn at all"
        return drawn

    def test_it_is_below_the_file_commands(self, _context, tmp_path):
        seen = self._ys(_context, _editor(tmp_path))
        assert min(self._at(seen, "Add control")) > max(self._at(seen, "Save")), (
            "Add control is level with or above Save — it is back in the file-command row"
        )

    def test_it_is_below_the_last_control_row(self, _context, tmp_path):
        """With two controls it has to be under *both*, not between them."""
        editor = _editor(tmp_path)
        editor.add_control()
        editor.add_control()
        seen = self._ys(_context, editor)
        rows = self._at(seen, "Remove control")
        assert len(rows) >= 2, "expected one Remove per control row"
        assert min(self._at(seen, "Add control")) > max(rows)

    def test_an_empty_map_still_offers_it(self, _context, tmp_path):
        """No rows, so it is the only thing to press — and it must still be drawn."""
        path = tmp_path / "empty.toml"
        path.write_text("[dofs]\n")
        editor = ControlMapEditor(path)
        editor.load()
        self._at(self._ys(_context, editor), "Add control")

    def test_add_target_follows_the_same_rule(self, _context, tmp_path):
        """`Add target` appends to the target list, so it goes at the end of *that* list.

        It was up in the name row beside `Remove control` — one indent level above the rows it
        adds, and giving an append the same weight as a delete.
        """
        from imgui_bundle import icons_fontawesome_6 as fa

        editor = _editor(tmp_path)
        seen = self._ys(_context, editor)
        # BUSY's first control has five targets, so this has to clear the last of them.
        assert min(self._at(seen, "Add target")) > max(self._at(seen, fa.ICON_FA_XMARK)), (
            "Add target is not below the target rows it appends to"
        )
        assert min(self._at(seen, "Add target")) > min(self._at(seen, "Remove control")), (
            "Add target is still up on the name row"
        )



class TestTheProbabilityGateIsAToggle:
    """The gate is a sticky on/off, so it is the contract's toggle, not an `imgui.checkbox`.

    `CLAUDE.md`: *use `push_selected`/`pop_selected` for any sticky on/off control*. It was the
    only labelled checkbox in the app, and at this theme's frame padding an unticked box is a
    tall empty rounded rectangle — which reads as a text field, not as an off switch.

    Clicked twice here rather than inspected, because the risk in swapping a `checkbox` for a
    `button` is the return value: `checkbox` hands back the new state, `button` only says it
    was pressed, so the toggle has to be derived instead of assigned.
    """

    @staticmethod
    def _click(io, editor, label, frames=1):
        """Render `frames` frames with `label` reporting a click, and nothing else clicked."""
        original = imgui.button

        def spy(text, *args, **kwargs):
            original(text, *args, **kwargs)
            return text.endswith(label)

        imgui.button = spy
        try:
            io.display_size = imgui.ImVec2(900, 1400)
            for _ in range(frames):
                imgui.new_frame()
                imgui.set_next_window_pos(imgui.ImVec2(0, 0))
                imgui.set_next_window_size(imgui.ImVec2(860, 1400))
                imgui.begin("gate", None, imgui.WindowFlags_.no_saved_settings)
                editor.ui()
                imgui.end()
                imgui.end_frame()
        finally:
            imgui.button = original

    def test_it_is_drawn_as_a_button(self, _context, tmp_path):
        editor = _editor(tmp_path)
        seen = TestAddControlSitsWithTheControls._ys(_context, editor)
        assert any(label == "Treat as probability" for label, _ in seen), (
            "the gate is not among the buttons drawn — it is still a checkbox"
        )

    def test_clicking_turns_it_on_with_a_cutoff_then_off_again(self, _context, tmp_path):
        editor = _editor(tmp_path)
        assert editor._draft[0]["threshold_fraction"] is None
        self._click(_context, editor, "Treat as probability")
        assert editor._draft[0]["threshold_fraction"] == 0.5, "one click should arm the gate"
        self._click(_context, editor, "Treat as probability")
        assert editor._draft[0]["threshold_fraction"] is None, "a second click should disarm it"



class TestTheLabelColumnLinesFieldsUp:
    """`common.label_column` — the ragged left edge, and the trap in fixing it.

    Two gates labelled "On at or above" and "Hold for" started their sliders at two different
    x, because each label was measured on its own. One column measured across the group fixes
    that; `same_line`'s absolute `offset_from_start_x` form looks like the way to do it and is
    not, because it measures from the window edge and ignores `imgui.indent` — which is
    exactly where these rows live.
    """

    LABELS = ("On at or above", "Hold for")

    @staticmethod
    def _run(io, draw, width=900):
        """Run `draw` in a settled frame and hand it a list to record positions into."""
        marks: list[tuple[str, float, float]] = []
        io.display_size = imgui.ImVec2(width + 40, 1400)
        for _ in range(3):
            marks.clear()
            imgui.new_frame()
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(width, 1400))
            imgui.begin("col", None, imgui.WindowFlags_.no_saved_settings)
            draw(marks)
            imgui.end()
            imgui.end_frame()
        return marks

    def _row(self, marks, label, value=0.5):
        label_column(label, self.LABELS)
        imgui.slider_float(f"##{label}", value, 0.0, 1.0, "")
        marks.append((label, imgui.get_item_rect_min().x, imgui.get_item_rect_max().x))

    def test_both_fields_start_at_the_same_x(self, _context):
        marks = self._run(_context, lambda m: [self._row(m, x) for x in self.LABELS])
        assert marks[0][1] == pytest.approx(marks[1][1], abs=1.0), (
            f"the fields start at different x: {marks}"
        )

    def test_it_survives_an_indent(self, _context):
        """The field must clear its own label, and shift with the indent rather than ignore it.

        `same_line(offset_from_start_x=column)` passes the first assertion and fails the
        second: at an indent deeper than the column it puts the field *left* of the label it
        belongs to, i.e. on top of it.
        """

        def draw(marks):
            self._row(marks, "Hold for")
            imgui.indent()
            imgui.indent()
            label_column("Hold for", self.LABELS)
            label_right = imgui.get_item_rect_max().x
            imgui.slider_float("##indented", 0.5, 0.0, 1.0, "")
            marks.append(("indented", imgui.get_item_rect_min().x, label_right))
            imgui.unindent()
            imgui.unindent()

        flat, indented = self._run(_context, draw)
        assert indented[1] > indented[2], "the field overlaps the label it is indented under"
        assert indented[1] > flat[1], "the field ignored the indent"

    def test_a_narrow_panel_stacks_instead_of_shrinking(self, _context):
        """Below a usable field width the label goes above it, rather than to a sliver."""
        wide = self._run(_context, lambda m: self._row(m, "On at or above"), width=900)
        narrow = self._run(_context, lambda m: self._row(m, "On at or above"), width=180)
        assert wide[0][1] > 100.0, "wide should put the field beside the label"
        assert narrow[0][1] < 30.0, "narrow should put the field on its own line"
        assert narrow[0][2] - narrow[0][1] > 90.0, "and it should still be usable"



class TestTheActionsShareOneRow:
    """Four buttons on one line when they fit, with a gap where the subject changes.

    `Connect` had a row to itself because it sat beside a note about the target. The note is
    gone — how many addresses a target publishes is not something anyone reads — so the row
    was a line spent on a gap. It keeps the gap, as a gap.
    """

    ACTIONS = ("Connect", "Save", "Save as...", "Reload")

    def _row(self, io, editor, width):
        """Every action button, as (label, x, y), from a settled frame at `width`."""
        seen: list[tuple[str, float, float]] = []
        original = imgui.button

        def spy(label, *args, **kwargs):
            result = original(label, *args, **kwargs)
            if label.endswith(self.ACTIONS):
                seen.append((label, imgui.get_item_rect_min().x, imgui.get_item_rect_min().y))
            return result

        imgui.button = spy
        try:
            io.display_size = imgui.ImVec2(width + 40, 1400)
            for _ in range(3):
                seen.clear()
                imgui.new_frame()
                imgui.set_next_window_pos(imgui.ImVec2(0, 0))
                imgui.set_next_window_size(imgui.ImVec2(width, 1400))
                imgui.begin(f"actions_row{width}", None, imgui.WindowFlags_.no_saved_settings)
                editor.ui()
                imgui.end()
                imgui.end_frame()
        finally:
            imgui.button = original
        return seen[: len(self.ACTIONS)]

    @pytest.mark.parametrize("width", (420, 560, 720, 1000, 1600))
    def test_they_all_share_one_line_when_there_is_room(self, _context, tmp_path, width):
        row = self._row(_context, _editor(tmp_path), width)
        assert len(row) == len(self.ACTIONS), f"an action went missing: {row}"
        assert len({y for _, _, y in row}) == 1, f"the actions wrapped at {width} px: {row}"

    def test_a_narrow_panel_still_wraps_rather_than_clips(self, _context, tmp_path):
        """320 px cannot hold four, so one drops to a second line — never off the edge."""
        row = self._row(_context, _editor(tmp_path), 320)
        assert len({y for _, _, y in row}) > 1, "four buttons cannot fit 320 px"

    def test_the_gap_marks_where_the_subject_changes(self, _context, tmp_path):
        """Re-asking the targets and writing the file are two subjects, so `_GROUP_GAP`.

        Measured as a comparison, not against a pixel count: what matters is that the break
        before Save is wider than the ordinary spacing between the file buttons.
        """
        row = {label.split("  ")[-1]: x for label, x, _ in self._row(_context, _editor(tmp_path), 900)}
        before_save = row["Save"] - row["Connect"]
        between_file_buttons = row["Reload"] - row["Save as..."]
        assert before_save > between_file_buttons, (
            f"no visible break before Save: {row}"
        )



class TestOnlyTheGatesThatApplyAreDrawn:
    """A gate that cannot apply to the chosen control is not drawn at all.

    Both were drawn always, disabled, with the reason on hover. That is two permanent rows per
    control spent on settings that do not apply to the continuous DOFs almost every map is made
    of — and "Steady for" then sat there *enabled* whenever the address could not be checked,
    which is every freshly added control, since it has no address yet.

    Two exceptions, both so the editor cannot hide state it refuses to save.
    """

    @staticmethod
    def _labels(io, editor):
        """Every button and label drawn for one settled frame."""
        seen: list[str] = []
        original_button, original_text = imgui.button, imgui.text

        def spy_button(label, *args, **kwargs):
            seen.append(label)
            return original_button(label, *args, **kwargs)

        def spy_text(label, *args, **kwargs):
            seen.append(label)
            return original_text(label, *args, **kwargs)

        imgui.button, imgui.text = spy_button, spy_text
        try:
            io.display_size = imgui.ImVec2(940, 1400)
            for _ in range(3):
                seen.clear()
                imgui.new_frame()
                imgui.set_next_window_pos(imgui.ImVec2(0, 0))
                imgui.set_next_window_size(imgui.ImVec2(900, 1400))
                imgui.begin("gates", None, imgui.WindowFlags_.no_saved_settings)
                editor.ui()
                imgui.end()
                imgui.end_frame()
        finally:
            imgui.button, imgui.text = original_button, original_text
        return seen

    @staticmethod
    def _editor_for(tmp_path, body):
        path = tmp_path / "g.toml"
        path.write_text(body)
        editor = ControlMapEditor(path, client=_Client())
        editor.load()
        editor._connect()
        return editor

    def test_a_number_is_not_offered_a_debounce(self, _context, tmp_path):
        """`vhi.prediction.index` is continuous — it has no state transition to hold."""
        editor = self._editor_for(tmp_path, '[dofs]\na = "vhi.prediction.index"\n')
        drawn = self._labels(_context, editor)
        assert "Steady for" not in drawn
        assert any(label.endswith("Add target") for label in drawn), "the row still drew"

    def test_a_held_state_is(self, _context, tmp_path):
        """`vhi.control.gesture` has exactly two states, so both gates apply."""
        editor = self._editor_for(tmp_path, '[dofs]\na = "vhi.control.gesture"\n')
        drawn = self._labels(_context, editor)
        assert "Steady for" in drawn
        assert "Treat as probability" in drawn

    def test_a_control_with_no_address_yet_is_offered_neither(self, _context, tmp_path):
        """The state every control is in the moment it is added: nothing to gate."""
        editor = self._editor_for(tmp_path, '[dofs]\na = "vhi.control.gesture"\n')
        editor.add_control()          # appended with no target
        drawn = self._labels(_context, editor)
        assert drawn.count("Steady for") == 1, "the empty control was offered a debounce"

    def test_a_value_the_control_refuses_is_still_shown_and_editable(self, _context, tmp_path):
        """The dead end this replaced: disabled *and* set, so `problems` blocked the save and
        the only way to clear it was the text view."""
        editor = self._editor_for(
            tmp_path,
            '[dofs]\na = { target = "vhi.prediction.index", debounce_s = 0.3 }\n',
        )
        assert editor._draft[0]["debounce_s"] == 0.3
        assert any("no state transition" in p for p in editor.problems()), (
            "a debounce on a continuous DOF should still block the save"
        )
        assert "Steady for" in self._labels(_context, editor), (
            "a value in the file must stay visible, or it cannot be cleared here"
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
            / "control_map_studio.py"
        ).read_text(encoding="utf-8")
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

    def test_a_slider_can_be_typed_into(self):
        """Double-click opens a field, and the click that opened it does not move the value.

        Clicking a slider track jumps the value to the click position, so the second click
        of a double-click arrives on an already-changed number. Restoring it is the whole
        difference between "type an exact value" and "set a random one, then type".
        """
        source = self._source()
        assert "is_mouse_double_clicked" in source
        assert "levels[alias] = before" in source, "the jump must be undone"
        assert "set_keyboard_focus_here" in source, "the field must take the caret"

    def test_a_typed_value_is_clamped_to_the_range_the_slider_offers(self):
        """A field that accepted 5.0 would show a number the hand will never reach.

        Pinned against the slider's own bounds rather than as literals: if the slider
        domain ever changes, a clamp left behind at the old one is exactly the mismatch
        this catches.
        """
        source = self._source()
        assert "imgui.slider_float(label, levels[alias], -1.0, 1.0)" in source
        assert "min(1.0, max(-1.0, value))" in source

    def test_an_open_field_is_closed_when_the_map_reloads(self):
        """Hot reload can rename or drop any alias, and a field left open on a vanished
        one would be typing into nothing."""
        source = self._source()
        assert "typing.clear()" in source
        assert "focus_pending.clear()" in source

    def _source(self) -> str:
        return (
            pathlib.Path(__file__).resolve().parent.parent
            / "examples"
            / "synthetic"
            / "control_map_studio.py"
        ).read_text(encoding="utf-8")

    def test_both_layouts_are_declared_and_differ(self):
        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "examples"
            / "synthetic"
            / "control_map_studio.py"
        ).read_text(encoding="utf-8")
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
            / "control_map_editor.py"
        ).read_text(encoding="utf-8")
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
        return pytest.importorskip("examples.synthetic.control_map_studio")

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


class TestTheStudioHoldsSeveralDocuments:
    """Tabs: one editor per open map, the active one driving the targets."""

    @pytest.fixture
    def studio(self):
        module = pytest.importorskip("examples.synthetic.control_map_studio")
        module.documents[:] = [module._new_document()]
        module.active = 0
        return module

    def test_it_starts_on_one_blank_untitled_map(self, studio):
        assert len(studio.documents) == 1
        assert studio.documents[0].path is None
        assert studio._tab_label(0) == "Untitled"

    def test_untitled_maps_are_numbered_for_the_reader(self, studio):
        """The widget calls them all "Untitled"; which one of several is the app's question."""
        studio.documents.append(studio._new_document())
        studio.documents.append(studio._new_document())
        assert [studio._tab_label(i) for i in range(3)] == [
            "Untitled",
            "Untitled 2",
            "Untitled 3",
        ]

    def test_opening_a_file_twice_focuses_it_rather_than_duplicating(self, studio):
        studio._open_document(studio.CONTROL_FILE)
        first = studio.active
        studio._open_document(studio.CONTROL_FILE)
        assert studio.active == first
        assert sum(1 for d in studio.documents if d.path is not None) == 1

    def test_closing_the_last_document_leaves_a_blank_one(self, studio):
        """An app with no document has nothing to look at and no obvious way back."""
        studio._close_document(0)
        assert len(studio.documents) == 1
        assert studio.documents[0].path is None

    def test_switching_disarms_the_keyboard(self, studio):
        """A map you navigated away from must not keep sending keystrokes."""
        studio.documents.append(studio._new_document())
        studio.keys._armed = True          # as `arm()` would leave it
        studio._switch_to(1)
        assert studio.keys.armed is False

    def test_closing_also_disarms(self, studio):
        studio.documents.append(studio._new_document())
        studio.active = 1
        studio.keys._armed = True
        studio._close_document(1)
        assert studio.keys.armed is False


class TestTheTabBarSurvivesAClose:
    """Closing the active tab killed the app, and the mechanism is worth pinning.

    `_tab_label` indexed the *live* document list while the render loop walked a copy. A
    close shrank the live list, the next label raised `IndexError`, and that escaped past
    `end_tab_bar()` — which ImGui answers with `IM_ASSERT(Missing EndTabBar())`, aborting the
    process instead of raising. So a mistake in one label took the whole studio down.
    """

    @pytest.fixture
    def studio(self):
        module = pytest.importorskip("examples.synthetic.control_map_studio")
        module.documents[:] = [module._new_document()]
        module.active = 0
        return module

    def test_a_label_is_numbered_within_the_list_it_is_given(self, studio):
        """The fix: labels read the caller's snapshot, not mutable global state."""
        snapshot = [studio._new_document(), studio._new_document()]
        assert studio._tab_label(1, snapshot) == "Untitled 2"

    def test_a_stale_index_cannot_reach_past_the_live_list(self, studio):
        """The exact crash: a snapshot longer than `documents`, as a close leaves it."""
        snapshot = [studio._new_document(), studio._new_document()]
        assert len(studio.documents) == 1 < len(snapshot)
        assert studio._tab_label(1, snapshot)          # must not raise

    def test_rendering_the_bar_pairs_begin_and_end(self, _context, studio):
        """A frame that leaves a tab bar open is what turns a Python error into an abort, so
        render it for real rather than trusting the shape of the code."""
        studio.documents.append(studio._new_document())
        studio._open_document(studio.CONTROL_FILE)
        # Two frames: the second is the one that would trip an unbalanced stack.
        for _ in range(2):
            _overflow(_context, 900, studio._tabs_ui)

    def test_a_close_is_applied_after_the_bar_not_during_it(self, studio):
        """Bookkeeping only, but it is the invariant the crash violated: the list may not
        change while it is being walked."""
        import inspect

        source = inspect.getsource(studio._tabs_ui)
        body = source.split("imgui.end_tab_bar()")
        assert len(body) == 2, "one end_tab_bar, or this check means nothing"
        before, after = body
        assert "_close_document(" not in before
        assert "documents.append(" not in before
        assert "_close_document(" in after


class TestTheDocumentsMenu:
    """Opening a map moved off the tab strip.

    A tab strip is for tabs, so a button shaped like one reading "Open..." looked like a
    document by that name. Everything that *makes* a tab now lives behind a caret next to
    the `+`, which is where you already look for another one.
    """

    @pytest.fixture
    def studio(self):
        module = pytest.importorskip("examples.synthetic.control_map_studio")
        module.documents[:] = [module._new_document()]
        module.active = 0
        module.recent.clear()
        return module

    def test_the_tab_strip_has_no_open_button_left(self, studio):
        import inspect

        source = inspect.getsource(studio._tabs_ui)
        assert 'tab_item_button("Open' not in source
        assert 'tab_item_button("+"' in source

    def test_the_examples_are_reachable(self, studio):
        """The studio starts blank now, so examples/controls went from "the file you opened
        into" to invisible. The menu is what keeps them findable."""
        examples = sorted(studio.CONTROL_FILE.parent.glob("*.toml"))
        assert examples, "the shipped maps are what the menu lists"
        studio._open_document(examples[0])
        assert studio.documents[studio.active].path == examples[0]

    def test_recent_remembers_what_was_closed(self, studio):
        """Its whole use: reopening a tab you just closed."""
        studio._open_document(studio.CONTROL_FILE)
        opened_at = studio.active
        studio._close_document(opened_at)
        assert studio.CONTROL_FILE.resolve() in studio.recent

    def test_recent_is_most_recent_first_and_deduped(self, studio):
        examples = sorted(studio.CONTROL_FILE.parent.glob("*.toml"))[:2]
        studio._open_document(examples[0])
        studio._open_document(examples[1])
        studio._open_document(examples[0])
        assert studio.recent[0] == examples[0].resolve()
        assert len(studio.recent) == 2

    def test_recent_is_bounded(self, studio):
        """A menu that grows without limit is a menu nobody scrolls."""
        for n in range(20):
            studio._open_document(studio.CONTROL_FILE.parent / f"nope{n}.toml")
        assert len(studio.recent) <= 8

    def test_rendering_the_bar_and_menu_pairs_up(self, _context, studio):
        """Popups and tab bars are separate ImGui stacks, and an unbalanced one aborts the
        process rather than raising — so render it rather than trusting the shape."""
        studio._open_document(studio.CONTROL_FILE)
        for _ in range(2):
            _overflow(_context, 900, studio._tabs_ui)


def test_opening_a_file_that_is_gone_does_not_crash(tmp_path):
    """The recent list makes this ordinary: a path that has moved since it was opened.

    `_connect` runs from a click, so an unguarded `open()` here took the window down rather
    than the tab — the same failure shape as the tab-close crash.
    """
    studio = pytest.importorskip("examples.synthetic.control_map_studio")
    studio.documents[:] = [studio._new_document()]
    studio.active = 0
    studio._open_document(tmp_path / "never-existed.toml")
    assert "could not be read" in studio.status or "Untitled" in studio.status


class TestTheStudioFollowsWhatTheTargetsOffer:
    """Launching a target has to reach the sliders, not just the editor's picker."""

    @pytest.fixture
    def studio(self):
        module = pytest.importorskip("examples.synthetic.control_map_studio")
        module.documents[:] = [module._new_document()]
        module.active = 0
        module.bus = None
        module.caps_seen.clear()
        return module

    def test_a_target_coming_up_or_going_away_rebuilds_the_bus(self, studio, monkeypatch):
        """The asymmetry behind "the VHI stuff only shows up sometimes".

        `_connect` was reachable only from a button, a tab switch or a save, so after
        pressing Launch the editor's dropdown filled itself while DRIVE THE MAP went on
        saying "Press Connect" — the manifest had changed and nothing here noticed.
        """
        from myogestic.controls import Capability

        calls = []
        monkeypatch.setattr(studio, "_connect", lambda known=None: calls.append(1))

        studio._rebuild_if_the_manifest_changed()
        assert len(calls) == 1, "the first frame must connect rather than wait for a click"

        for _ in range(5):
            studio._rebuild_if_the_manifest_changed()
        assert len(calls) == 1, "it rebuilt on a frame where nothing had changed"

        studio.documents[0]._capabilities = (
            Capability("vhi.prediction.index", "continuous", -1.0, 1.0, 0.0),
        )
        studio._rebuild_if_the_manifest_changed()
        assert len(calls) == 2, "a target that came up did not reach the sliders"

        studio.documents[0]._capabilities = ()
        studio._rebuild_if_the_manifest_changed()
        assert len(calls) == 3, "a target that went away left its sliders behind"

    def test_a_connect_that_returns_early_clears_the_old_waiting_list(self, studio):
        """`waiting` is drawn unconditionally, so a stale one belongs to the wrong map.

        It was assigned only on the path that reaches `_split`, and `_connect` returns before
        that for an untitled map and for a file that will not read — so an Untitled tab
        reported undrivable controls out of the map you had just navigated away from.
        """
        studio.waiting = {"close": "vhi.prediction.index — vhi has not answered"}
        studio._connect()          # the active document is untitled: an early return
        assert studio.waiting == {}, "the previous map's controls were still listed"
        assert "Untitled" in studio.status

    def test_closing_a_document_forgets_its_manifest_count(self, studio, monkeypatch):
        """`caps_seen` is keyed by `id`, and CPython reuses ids of collected objects.

        A new document inheriting a dead one's entry, with the same number of controls
        offered, would read as "nothing has changed" and never build a bus at all.
        """
        monkeypatch.setattr(studio, "_connect", lambda known=None: None)
        studio.documents.append(studio._new_document())
        doomed = studio.documents[1]
        studio._rebuild_if_the_manifest_changed()          # records the active one
        studio.caps_seen[id(doomed)] = 99

        studio._close_document(1)

        assert id(doomed) not in studio.caps_seen, "a closed document's count outlived it"

    def test_the_render_loop_actually_reaches_the_rebuild_check(
        self, studio, _context, monkeypatch
    ):
        """A helper nothing calls is not a fix.

        The direct-call test pins the helper's logic; this pins the wiring. Deleting the
        call from `studio_ui` left the whole suite green, which is the same class of gap as
        the bug being fixed — the render loop never asked.
        """
        calls = []
        monkeypatch.setattr(studio, "_connect", lambda known=None: calls.append(1))
        studio.caps_seen.clear()

        _overflow(_context, 900, lambda: studio.studio_ui(studio.app.ctx))

        assert calls, "studio_ui never reached the manifest check"

    def test_an_automatic_rebuild_does_not_disarm_the_keyboard(
        self, studio, monkeypatch, tmp_path
    ):
        """`bus.stop()` lifts every key, which is right on the way out and wrong here.

        Rebuilding used to follow a click only, so disarming was something the user had
        just asked for. It now also follows a target turning up, and an arm switch that
        flicks itself off mid-session — silently, since nothing here draws a log — is worse
        than one that stays on. `_switch_to` and `_close_document` still disarm on purpose:
        they do it *before* calling `_connect`, so the arm they see is already False.
        """
        from myogestic.controls import Capability

        class _Keys:
            def __init__(self):
                self.armed = False
                self.claims = frozenset({"walk"})

            def arm(self):
                self.armed = True

            def disarm(self):
                self.armed = False

            def stop(self):
                self.disarm()

            def capabilities(self):
                return [
                    Capability("keyboard.hold.letter.w", "discrete", 0.0, 1.0, 0.0,
                               states=("up", "down"))
                ]

        class _Target:
            def stop(self):
                pass

            def negotiate(self):
                return False

        class _Bus:
            def __init__(self, controls, targets=(), hz=0):
                self.targets = list(targets)

            def stop(self):
                for target in self.targets:
                    target.stop()

        fake_keys = _Keys()
        monkeypatch.setattr(studio, "keys", fake_keys)
        monkeypatch.setattr(studio, "RemoteTarget", lambda **kw: _Target())
        monkeypatch.setattr(studio, "ControlBus", _Bus)

        path = tmp_path / "keys.toml"
        path.write_text('[dofs]\nwalk = "keyboard.hold.letter.w"\n')
        studio.documents[:] = [studio._new_document(path)]
        studio.active = 0
        studio.bus = None

        studio._connect()
        assert studio.bus is not None, studio.status

        studio._connect()                     # a rebuild while it was never armed
        assert not fake_keys.armed, "a rebuild armed a keyboard nobody had switched on"

        fake_keys.arm()                       # the user ticks "Send keys to the system"
        studio._connect()                     # a target turned up: an automatic rebuild

        assert fake_keys.armed, "launching a target switched the keyboard off"

    def test_switching_tabs_still_disarms_on_purpose(self, studio, monkeypatch, tmp_path):
        """The carry must not resurrect a disarm the app asked for."""

        class _Keys:
            def __init__(self):
                self.armed = True

            def disarm(self):
                self.armed = False

        fake_keys = _Keys()
        monkeypatch.setattr(studio, "keys", fake_keys)
        monkeypatch.setattr(studio, "_connect", lambda known=None: None)
        studio.documents.append(studio._new_document())

        studio._switch_to(1)

        assert not fake_keys.armed, "a tab switch must leave the keyboard disarmed"

    def test_an_automatic_rebuild_does_not_re_ask_the_targets(
        self, studio, monkeypatch, tmp_path
    ):
        """No click happened, so nobody is waiting through a round trip — and the editor's
        worker already fetched the very answer that triggered this."""
        handed = []
        monkeypatch.setattr(studio, "_connect", lambda known=None: handed.append(known))
        monkeypatch.setattr(
            studio, "_manifests", lambda: pytest.fail("the render thread re-asked")
        )
        studio.caps_seen.clear()

        studio._rebuild_if_the_manifest_changed()

        assert handed and handed[0] is not None, "it re-asked instead of reusing"

    def test_the_editors_manifest_names_the_targets_that_said_nothing(self, studio):
        """`absent` is read back off the addresses, so it cannot drift from the merge."""
        from myogestic.controls import Capability

        studio.documents[0]._capabilities = (
            Capability("keyboard.hold.letter.w", "discrete", 0.0, 1.0, 0.0,
                       states=("up", "down")),
        )
        capabilities, absent = studio._editor_manifest()
        assert [c.address for c in capabilities] == ["keyboard.hold.letter.w"]
        assert absent == ["vhi"]

        studio.documents[0]._capabilities = ()
        assert studio._editor_manifest()[1] == ["vhi", "keyboard"]

    def test_a_press_still_asks_for_itself(self, studio, monkeypatch, tmp_path):
        """The button exists to re-ask; reusing a cached manifest there would defeat it."""
        asked = []
        monkeypatch.setattr(studio, "_manifests", lambda: (asked.append(1), ([], ["vhi"]))[1])
        path = tmp_path / "press.toml"
        path.write_text('[dofs]\nwalk = "keyboard.hold.letter.w"\n')
        studio.documents[:] = [studio._new_document(path)]
        studio.active = 0
        studio.bus = None

        studio._connect()

        assert asked, "a bare _connect() must ask the targets itself"
