"""Author a TOML control map from what a target says it exports.

A control map is two vocabularies meeting: your own names on the left, addresses the
target publishes on the right. Writing one by hand means knowing the address syntax and
which addresses exist, which is a lot to ask of someone who just wants a finger to move.

`ControlMapEditor` asks the target instead. It lists what the renderer exports, with the
kind, range and states *it* declared, and lets a name be pointed at one by picking from
that list. The file stays the source of truth: this reads it, edits it and writes it back
with `myogestic.controls.dump_control_map`. There is no second store — close the app and
the TOML is all there is.

    editor = ControlMapEditor(pathlib.Path("my_controls.toml"), client=canonical_client)

    @app.ui
    def ui(ctx):
        if editor.ui():          # True on the frame a save lands
            reload_my_bus()

The return value is deliberately the *save* edge rather than every keystroke: rebuilding
a control bus is not something to do while someone is dragging a weight slider.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

from imgui_bundle import imgui

from myogestic.controls import (
    Binding,
    ControlMap,
    TargetRef,
    dump_control_map,
    load_control_map,
    resolve,
)
from myogestic.widgets.common import DANGER, SUCCESS, WARNING, muted, panel_header

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from myogestic.controls import Capability

#: What a new alias is called before the user renames it. Numbered on collision.
_NEW_ALIAS = "my_control"

# Layout. Every item here is sized explicitly, because ImGui's default item width is a
# fraction of the *window* — put two defaults on one line with `same_line` and the row is
# wider than the window, and widening the window makes the overflow worse rather than
# better. So: fixed budgets for the small controls, and whatever is left for the one that
# should grow.
#: Below this much room for a row, controls stack instead of sitting side by side.
_STACK_BELOW = 420.0
#: Item spacing allowance between two controls on one line.
_GAP = 12.0
#: Enough room for a weight slider to be draggable rather than a nub.
_WEIGHT_W = 130.0
#: The little remove-target button.
_DROP_W = 26.0
#: A name field wide enough for a real alias, but never more than half a wide row.
_NAME_MAX_W = 240.0
#: Which renderer stream a map drives, and what a target calls it. One control map is
#: bound by one target, and a target drives one hand — so a map that mixes the two is
#: refused at bind time. The editor knows which stream every control belongs to, so it can
#: keep that from being written in the first place.
_STREAM_NAMES = {"output": "MyoGestic_Output", "control_pose": "MyoGestic_ControlPose"}
_STREAM_LABELS = {"output": "the model's hand", "control_pose": "the operator's hand"}

#: The normalized signed domain a continuous control is expected to declare: `+1` is the
#: direction the control denotes, rest is `0`. Shown in a row only when a target declares
#: something *else*, because a fact repeated on every line is not a fact anyone reads —
#: and a one-way range buried among twenty identical ones is exactly what gets missed.
_SIGNED = (-1.0, 1.0)
#: A picker wide enough for the longest address there is. Capped, because a control that
#: grows without limit is not "responsive" — on a 1800 px window it became a 1000 px
#: dropdown holding a 20-character name, which reads as a layout mistake and puts the
#: weight beside it a screen away from the control it belongs to.
_PICKER_MAX_W = 380.0

_HEADER = (
    "Written by MyoGestic's control-map editor.\n"
    "This file is the source of truth — edit it here or by hand, whichever suits.\n"
    "  left  = your name for a model output, anything you like\n"
    "  right = a control the target declares (it owns the kind, range and states)"
)


def _leading_comments(text: str) -> str:
    """The comment block a file opens with, without the `#` markers.

    Re-emitted on save so a hand-written preamble survives a trip through the editor.
    Stops at the first line that is not a comment or blank, so it takes the header and
    nothing else.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            kept.append(stripped.lstrip("#").strip())
        elif not stripped:
            if kept:
                kept.append("")
        else:
            break
    return "\n".join(kept).strip()


def _label_w(label: str) -> float:
    """How much room a widget's trailing label needs, including its spacing."""
    return imgui.calc_text_size(label).x + _GAP


class ControlMapEditor:
    """Edit a TOML control map against a live target's manifest.

    Construct once with the file to edit, then call `ui` each frame.

    Parameters
    ----------
    path
        The TOML file. Read on the first frame and on **Reload**; written on **Save**.
        It does not have to exist yet — an absent file starts an empty map, so this
        doubles as a way to create one.
    client
        A `myogestic.vhi._client_v2.VhiCanonicalClient`, or anything with a
        ``capabilities()`` method returning a sequence of `myogestic.controls.Capability`.
        Called on **Connect** rather than every frame, because it blocks on an RPC.
        Without it the editor still opens the file and shows it; it just cannot offer a
        list to pick from or validate an address, and says so.
    stream
        Which renderer stream the map being edited drives — ``"output"`` (the model's
        hand, the default) or ``"control_pose"`` (the operator's). Must match the
        `myogestic.vhi.VhiTarget` that will bind it, because a target drives one hand:
        the picker offers only that stream's controls, and an address from the other one
        is reported as a problem rather than saved and refused later.
    title
        Panel header text.

    Notes
    -----
    Validation runs on every edit, not on save: an alias that collides, a weight out of
    range, two aliases aimed at one control. **Save is disabled while anything is
    invalid**, so the file on disk is never a file that would not load — which matters
    because something else is reading it.

    A save keeps the comment block the file opened with, so a hand-written preamble
    survives a round trip. Comments *between* entries do not: preserving those needs a
    comment-preserving TOML writer, and this says so rather than pretending.

    The editor holds its own working copy while editing, and that copy is discarded by
    **Reload**. It is not a second configuration store: nothing else reads it, it does
    not outlive the window, and every path out of it goes through the same
    `myogestic.controls.dump_control_map` a script would use.

    Examples
    --------
    >>> import pathlib
    >>> from myogestic.widgets import ControlMapEditor
    >>> editor = ControlMapEditor(pathlib.Path("hand.toml"))
    >>> editor.ui()                      # each frame, inside @app.ui
    """

    __slots__ = (
        "_capabilities", "_client", "_draft", "_error", "_filter", "_header", "_message",
        "_path", "_raw", "_raw_error", "_raw_open", "_stream", "_title", "_loaded",
    )

    def __init__(
        self,
        path: pathlib.Path,
        *,
        client: Any = None,
        stream: str = "output",
        title: str = "CONTROL MAP",
    ) -> None:
        if stream not in _STREAM_NAMES:
            raise ValueError(
                f"stream must be one of {sorted(_STREAM_NAMES)}, got {stream!r}"
            )
        self._path = path
        self._client = client
        self._stream = stream
        self._title = title
        #: alias -> [(address, weight)], plus the gates. A plain structure rather than a
        #: ControlMap because a half-edited map is not a valid one, and `Binding` is
        #: frozen on purpose.
        self._draft: list[dict[str, Any]] = []
        self._capabilities: tuple[Capability, ...] = ()
        self._filter = ""
        self._message = ""
        self._error = ""
        #: The file as text, for editing it directly. Filled when the text view is opened
        #: and when `Revert` is pressed — *not* every frame, because rewriting the buffer
        #: under someone's cursor is how a text box eats what you just typed.
        self._raw = ""
        self._raw_open = False
        self._raw_error = ""
        #: The comment block the file opened with, kept so a save does not erase what
        #: whoever wrote it was explaining. Only the *leading* block survives — comments
        #: interleaved with entries would need a comment-preserving TOML writer, and
        #: silently dropping those is stated in the class docstring rather than hidden.
        self._header = ""
        self._loaded = False

    # --- file -------------------------------------------------------------------

    def load(self) -> None:
        """Read the file into the working copy, replacing anything unsaved."""
        self._draft = []
        self._error = ""
        self._header = ""
        if not self._path.exists():
            self._message = f"{self._path.name} does not exist yet — Save will create it."
            self._loaded = True
            return
        self._header = _leading_comments(self._path.read_text())
        try:
            with self._path.open("rb") as handle:  # "rb" — tomllib requires binary
                control_map = load_control_map(tomllib.load(handle))
        except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
            # Shown rather than raised: the editor is the tool you would use to *fix*
            # a broken file, so it has to survive opening one.
            self._error = str(exc)
            self._message = ""
            self._loaded = True
            return
        for binding in control_map.bindings.values():
            self._draft.append(
                {
                    "alias": binding.alias,
                    "targets": [[ref.address, float(ref.weight)] for ref in binding.targets],
                    "debounce_s": float(binding.debounce_s),
                    "threshold_fraction": binding.threshold_fraction,
                }
            )
        self._message = f"Loaded {len(self._draft)} control(s) from {self._path.name}."
        self._loaded = True

    def raw_text(self) -> str:
        """The working copy as TOML text, for editing by hand.

        The file's own bytes when nothing has been changed in the fields, so opening the
        text view shows exactly what is on disk — comments and all. Once the fields have
        diverged it is rendered from them instead, because showing stale text next to
        live fields is worse than losing the comments.
        """
        rendered = dump_control_map(self.as_control_map() or ControlMap(bindings={}))
        if not self._path.exists():
            return rendered
        on_disk = self._path.read_text()
        try:
            same = load_control_map(tomllib.loads(on_disk)).as_dict() == (
                self.as_control_map() or ControlMap(bindings={})
            ).as_dict()
        except (tomllib.TOMLDecodeError, ValueError):
            return on_disk        # unparseable: show it so it can be fixed by hand
        return on_disk if same else rendered

    def apply_raw(self, text: str) -> bool:
        """Replace the working copy from TOML text. False (with a reason) if it will not load.

        The other direction of the same contract the fields obey: nothing invalid gets in,
        so `Save` still cannot write a file that would not load back.
        """
        self._raw_error = ""
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            self._raw_error = f"Not valid TOML: {exc}"
            return False
        if "dofs" not in raw:
            self._raw_error = 'No [dofs] table — a control map needs one.'
            return False
        try:
            control_map = load_control_map(raw)
        except ValueError as exc:
            self._raw_error = str(exc)
            return False
        self._draft = [
            {
                "alias": binding.alias,
                "targets": [[ref.address, float(ref.weight)] for ref in binding.targets],
                "debounce_s": float(binding.debounce_s),
                "threshold_fraction": binding.threshold_fraction,
            }
            for binding in control_map.bindings.values()
        ]
        self._message = f"Applied {len(self._draft)} control(s) from the text."
        return True

    def save(self) -> bool:
        """Write the working copy back as TOML. False if it would not load."""
        control_map = self.as_control_map()
        if control_map is None:
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            dump_control_map(control_map, header=self._header or _HEADER)
        )
        self._message = f"Saved {len(self._draft)} control(s) to {self._path.name}."
        return True

    def as_control_map(self) -> ControlMap | None:
        """The working copy as a `ControlMap`, or None if it is not valid.

        Built through `Binding`/`TargetRef` directly rather than by rendering TOML and
        parsing it back, so the editor cannot produce a file its own loader rejects.
        """
        if self.problems():
            return None
        bindings: dict[str, Binding] = {}
        for entry in self._draft:
            bindings[entry["alias"]] = Binding(
                alias=entry["alias"],
                targets=tuple(
                    TargetRef(address=address, weight=weight)
                    for address, weight in entry["targets"]
                ),
                debounce_s=entry["debounce_s"],
                threshold_fraction=entry["threshold_fraction"],
            )
        return ControlMap(bindings=bindings)

    # --- validation -------------------------------------------------------------

    def problems(self) -> list[str]:
        """Everything wrong with the working copy right now, in reading order.

        Cheap enough to call every frame. Checked here rather than at save because a
        disabled Save button with a reason beside it is a better answer than a rejected
        write.
        """
        found: list[str] = []
        seen: dict[str, int] = {}
        exported = {cap.address for cap in self._capabilities}
        # Two aliases on one *channel* is the conflict a target refuses, and the short
        # and axis forms of a control share a channel — so this is keyed on the channel
        # the manifest reports, not on the address text.
        channels: dict[tuple[str, int], list[str]] = {}
        by_address = {cap.address: cap for cap in self._capabilities}

        for entry in self._draft:
            alias = entry["alias"].strip()
            if not alias:
                found.append("A control has no name.")
            elif alias in seen:
                found.append(f"{alias!r} is used twice — each name must be its own.")
            seen[alias] = seen.get(alias, 0) + 1

            if not entry["targets"]:
                found.append(f"{alias or '(unnamed)'} points at nothing yet.")
            for address, weight in entry["targets"]:
                if not address:
                    found.append(f"{alias}: a target has no control chosen.")
                    continue
                if self._capabilities and address not in exported:
                    found.append(f"{alias}: the target does not export {address!r}.")
                other = self._wrong_stream(address)
                if other is not None:
                    found.append(
                        f"{alias}: {address} drives "
                        f"{_STREAM_LABELS['control_pose' if self._stream == 'output' else 'output']}"
                        f", but this map drives {_STREAM_LABELS[self._stream]}. One map "
                        f"controls one hand — remove it, or put it in the map for that hand."
                    )
                if not -1.0 <= weight <= 1.0 or weight == 0.0:
                    found.append(
                        f"{alias}: weight {weight} is outside [-1, 1] or zero. A weight "
                        f"scales a value, so it cannot invent range; a negative one "
                        f"needs a target that declares signed motion."
                    )
                cap = by_address.get(address)
                if cap is not None and getattr(cap, "channel", -1) >= 0:
                    slot = (getattr(cap, "stream_name", ""), cap.channel)
                    channels.setdefault(slot, []).append(alias)

            fraction = entry["threshold_fraction"]
            if fraction is not None and not 0.0 <= fraction <= 1.0:
                found.append(f"{alias}: threshold_fraction must be between 0 and 1.")

        for (stream, channel), owners in channels.items():
            distinct = sorted(set(owners))
            if len(distinct) > 1:
                where = f"{stream} channel {channel}" if stream else f"channel {channel}"
                found.append(
                    f"{' and '.join(distinct)} both reach the same control ({where}). "
                    f"One control cannot take two outputs."
                )
        return found

    # --- editing ----------------------------------------------------------------

    def add_control(self, alias: str = "", address: str = "") -> None:
        """Add a control, named and pointed however the caller likes."""
        taken = {entry["alias"] for entry in self._draft}
        name = alias or _NEW_ALIAS
        suffix = 2
        while name in taken:
            name = f"{alias or _NEW_ALIAS}_{suffix}"
            suffix += 1
        self._draft.append(
            {
                "alias": name,
                "targets": [[address, 1.0]] if address else [],
                "debounce_s": 0.0,
                "threshold_fraction": None,
            }
        )

    # --- rendering --------------------------------------------------------------

    def ui(self) -> bool:
        """Render the editor. Returns True on the frame a save succeeded."""
        if not self._loaded:
            self.load()
        panel_header(self._title)
        saved = False

        # The four actions, wrapped rather than truncated: on a narrow panel they run
        # onto a second line instead of the last one falling off the edge. These are the
        # controls a user cannot do without, so they come first and they always fit.
        can_save = not self.problems()
        for index, (label, handler, disabled) in enumerate(
            (
                ("Connect", self._connect, False),
                ("Save", None, not can_save),
                ("Reload", self.load, False),
                ("Add control", self.add_control, False),
            )
        ):
            if index and self._room_for(imgui.calc_text_size(label).x + 24.0):
                imgui.same_line()
            imgui.begin_disabled(disabled)
            if imgui.button(label):
                if label == "Save":
                    saved = self.save()
                else:
                    handler()
            imgui.end_disabled()

        # `text_wrapped` throughout: a path or a refusal is as long as it is, and on a
        # narrow panel an unwrapped line is simply cut off mid-word.
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(str(self._path))
        imgui.pop_style_color()
        if self._capabilities:
            colour, note = SUCCESS, (
                f"{len(self._capabilities)} controls available from the target"
            )
        else:
            colour, note = WARNING, (
                "Not connected — press Connect to list what the target exports. "
                "Until then a control has to be typed and cannot be checked."
            )
        imgui.push_style_color(imgui.Col_.text, colour)
        imgui.text_wrapped(note)
        imgui.pop_style_color()
        if self._error or self._message:
            imgui.push_style_color(
                imgui.Col_.text, DANGER if self._error else muted()
            )
            imgui.text_wrapped(self._error or self._message)
            imgui.pop_style_color()

        imgui.separator()
        for index, entry in enumerate(list(self._draft)):
            self._entry_ui(index, entry)

        problems = self.problems()
        if problems:
            imgui.separator()
            imgui.text_colored(DANGER, "Cannot save yet:")
            for problem in problems:
                imgui.bullet()
                imgui.text_wrapped(problem)

        saved = self._raw_ui() or saved
        return saved

    def _raw_ui(self) -> bool:
        """Edit the file as text. Returns True if a save happened from here."""
        imgui.separator()
        opened = imgui.collapsing_header("Edit as text (TOML)")
        if opened and not self._raw_open:
            # Filled on open, not per frame: see `_raw`.
            self._raw = self.raw_text()
        self._raw_open = bool(opened)
        if not opened:
            return False

        # Width -1 is ImGui's "fill what is left", which it computes *after* deciding
        # whether the panel needs a vertical scrollbar. Passing the available width
        # measured beforehand is 16 px too wide exactly when that scrollbar appears.
        avail = imgui.get_content_region_avail()
        changed, self._raw = imgui.input_text_multiline(
            "##raw", self._raw, imgui.ImVec2(-1.0, max(120.0, avail.y - 60.0))
        )
        # Wrapped like the action row above: these labels are long enough that on a
        # narrow panel one of the three would otherwise sit past the edge.
        saved = False
        if imgui.button("Apply to fields"):
            self.apply_raw(self._raw)
        if self._room_for(_label_w("Apply and save") + 24.0):
            imgui.same_line()
        # `save()` refuses on its own if the applied text still has problems, so the
        # button is one call rather than a check-then-act.
        if imgui.button("Apply and save") and self.apply_raw(self._raw):
            saved = self.save()
        if self._room_for(_label_w("Revert text") + 24.0):
            imgui.same_line()
        if imgui.button("Revert text"):
            self._raw = self.raw_text()
            self._raw_error = ""
        if self._raw_error:
            imgui.push_style_color(imgui.Col_.text, DANGER)
            imgui.text_wrapped(self._raw_error)
            imgui.pop_style_color()
        else:
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped(
                "Type freely — nothing reaches the file until it parses and resolves."
            )
            imgui.pop_style_color()
        return saved

    def _connect(self) -> None:
        """Ask the target what it exports. Blocking, so only on a click."""
        fetch = getattr(self._client, "capabilities", None)
        capabilities = fetch() if callable(fetch) else None
        if not capabilities:
            self._capabilities = ()
            self._message = "No target answered — launch it, then Connect again."
            return
        self._capabilities = tuple(capabilities)
        self._message = ""

    def _entry_ui(self, index: int, entry: dict[str, Any]) -> None:
        """One control: its name, its targets, its gates."""
        imgui.push_id(f"dof{index}")
        avail = imgui.get_content_region_avail().x
        stacked = avail < _STACK_BELOW

        buttons = (
            _label_w("Add target") + _label_w("Remove") + 24.0 if not stacked else 0.0
        )
        imgui.set_next_item_width(
            min(_NAME_MAX_W, max(90.0, avail - _label_w("name") - buttons))
        )
        changed, alias = imgui.input_text("name", entry["alias"])
        if changed:
            entry["alias"] = alias
        if not stacked:
            imgui.same_line()
        if imgui.button("Add target"):
            entry["targets"].append(["", 1.0])
        imgui.same_line()
        if imgui.button("Remove"):
            self._draft.remove(entry)
            imgui.pop_id()
            return

        dropped = None
        for slot, pair in enumerate(list(entry["targets"])):
            imgui.push_id(f"t{slot}")
            imgui.indent()
            if self._target_ui(pair, drop=len(entry["targets"]) > 1):
                dropped = pair
            imgui.unindent()
            imgui.pop_id()
        if dropped is not None:
            # Removed after the loop, never during it: mutating the list mid-iteration
            # shifts every later row's ImGui id, which moves keyboard focus and can
            # discard a half-typed name.
            entry["targets"].remove(dropped)

        self._gates_ui(entry)
        imgui.separator()
        imgui.pop_id()

    @staticmethod
    def _room_for(needed: float) -> bool:
        """Whether `needed` more pixels fit beside the item just drawn.

        Measured from that item's right edge, not from `get_content_region_avail`. After
        an item the cursor is already at the start of the *next* line, so the available
        width is the whole line — asking it "does one more button fit?" always answers yes,
        and the `same_line` that follows then puts the button back on the full line whether
        it fits or not. That is what left the text view's three buttons 16 px over at a
        320 px panel while each of them measured fine alone.
        """
        # This build of the bindings exposes no `get_window_content_region_max`, so the
        # right edge is derived: window origin + width, less the padding on both sides.
        style = imgui.get_style()
        right = imgui.get_item_rect_max().x + style.item_spacing.x + needed
        limit = (
            imgui.get_window_pos().x
            + imgui.get_window_width()
            - style.window_padding.x
            - imgui.get_style().scrollbar_size
        )
        return right <= limit

    def _target_ui(self, pair: list[Any], *, drop: bool) -> bool:
        """One route: which control, at what weight, and a way to remove it.

        Wide enough and it is one line, with the picker taking the slack. Narrow and the
        weight moves below it — a row that would not fit is reflowed rather than clipped,
        because a weight slider pushed off the edge cannot be dragged at all.

        Returns whether this target should be removed.
        """
        avail = imgui.get_content_region_avail().x
        stacked = avail < _STACK_BELOW
        # A label is drawn *after* its widget and is not part of `set_next_item_width`, so
        # every label on the row has to be reserved too. Forgetting them is what left this
        # overflowing by a constant ~80 px at every width once the widgets themselves fit.
        # -1..1 rather than 0..1: a signed target can take a negative weight, and a
        # slider that cannot reach one would make a valid file unsavable.
        reserved = (
            0.0
            if stacked
            else (
                _WEIGHT_W
                + _label_w("weight")
                + (_DROP_W + _GAP if drop else 0.0)
                + _GAP * 2
            )
        )
        self._picker(
            pair,
            width=min(_PICKER_MAX_W, max(120.0, avail - reserved - _label_w("control"))),
        )

        if not stacked:
            imgui.same_line()
        imgui.set_next_item_width(_WEIGHT_W)
        changed, weight = imgui.slider_float("weight", pair[1], -1.0, 1.0)
        if changed:
            pair[1] = round(weight, 2)
        if not drop:
            return False
        imgui.same_line()
        clicked = imgui.button("x")
        if not clicked and imgui.is_item_hovered():
            imgui.set_tooltip("Remove this target")
        return clicked

    def _offered(self) -> list[Capability]:
        """The controls this map may use: its own stream's, plus the held states.

        A discrete control travels over gRPC rather than a pose stream, so it belongs to
        neither hand and is always on offer.
        """
        wanted = _STREAM_NAMES[self._stream]
        return [
            cap
            for cap in self._capabilities
            if cap.kind != "continuous"
            or not getattr(cap, "stream_name", "")
            or cap.stream_name == wanted
        ]

    def _wrong_stream(self, address: str) -> Capability | None:
        """The capability for `address` if it belongs to the *other* hand."""
        wanted = _STREAM_NAMES[self._stream]
        for cap in self._capabilities:
            if cap.address == address and cap.kind == "continuous":
                name = getattr(cap, "stream_name", "")
                if name and name != wanted:
                    return cap
        return None

    def _picker(self, pair: list[Any], *, width: float) -> None:
        """Choose a control from what the target exports, or type one when offline."""
        address = pair[0]
        imgui.set_next_item_width(width)
        if not self._capabilities:
            changed, typed = imgui.input_text("control", address)
            if changed:
                pair[0] = typed
            return
        label = address or "choose a control..."
        # A combo popup sizes itself to its contents, and a `-1` item inside it means
        # "fill the available width" — which in a popup that has not been sized yet is
        # unbounded, so the search field grew the popup to the whole display. Constrain
        # the popup and give the field a real width instead.
        popup_w = max(width, _PICKER_MAX_W)
        imgui.set_next_window_size_constraints(
            imgui.ImVec2(width, 0.0), imgui.ImVec2(popup_w, 320.0)
        )
        if imgui.begin_combo("control", label):
            imgui.set_next_item_width(popup_w - _label_w("search") - 24.0)
            changed, self._filter = imgui.input_text("search", self._filter)
            for cap in self._offered():
                if self._filter and self._filter.lower() not in cap.address.lower():
                    continue
                selected, _ = imgui.selectable(self._describe(cap), cap.address == address)
                if imgui.is_item_hovered():
                    peers = self._peers(cap)
                    if peers:
                        imgui.set_tooltip(
                            "The same control as:\n  " + "\n  ".join(peers)
                        )
                if selected:
                    pair[0] = cap.address
            imgui.end_combo()
        # What the target declared about the *selected* control, on hover: read once,
        # rather than repeated down every row of the list.
        cap = next((c for c in self._capabilities if c.address == address), None)
        if cap is not None and imgui.is_item_hovered():
            imgui.set_tooltip(f"{cap.address}\n{self._summary(cap)}")

    def _describe(self, cap: Capability) -> str:
        """One row of the picker: the address, what it takes, and where it goes.

        The address **verbatim**, not a prettier short form of it. A shortened name is a
        second vocabulary for the same thing: you would read `thumb` here and have to know
        it means `vhi.prediction.thumb` in the file. One name, the real one, and the list
        reads the way the file does.

        The range is shown only when it is *not* the signed `[-1, +1]` every control here
        declares — see `_SIGNED`. The full facts of whatever is selected are on the
        picker's own tooltip, so nothing is lost by leaving the usual case unsaid.

        The channel is shown because it is the only thing that reveals the list's one
        surprise — a renderer publishes the short and the explicit-axis form of a control
        as two addresses on **one** channel, so two rows can mean the same physical
        control. Two rows with the same `ch` are the same control.
        """
        if cap.kind != "continuous":
            return f"{cap.address}   {len(cap.states)} states   over gRPC"
        where = f"ch{cap.channel}" if cap.channel >= 0 else "not streamed"
        usual = abs(cap.lo - _SIGNED[0]) < 1e-6 and abs(cap.hi - _SIGNED[1]) < 1e-6
        span = "" if usual else f"   [{cap.lo:+.1f}..{cap.hi:+.1f}]"
        return f"{cap.address}{span}   {where}"

    def _peers(self, cap: Capability) -> list[str]:
        """Other addresses that land on the same control as this one."""
        if getattr(cap, "channel", -1) < 0:
            return []
        return [
            other.address
            for other in self._capabilities
            if other.address != cap.address
            and getattr(other, "channel", -1) == cap.channel
            and getattr(other, "stream_name", "") == getattr(cap, "stream_name", "")
        ]

    @staticmethod
    def _summary(cap: Capability) -> str:
        """What the target declared about the chosen control."""
        if cap.kind == "continuous":
            where = f"channel {cap.channel}" if cap.channel >= 0 else "not streamed"
            return f"number {cap.lo:+.1f}..{cap.hi:+.1f}, {where}"
        states = ", ".join(cap.states[:3])
        more = "..." if len(cap.states) > 3 else ""
        return f"held state: {states}{more}"

    def _gates_ui(self, entry: dict[str, Any]) -> None:
        """`threshold_fraction` and `debounce_s`, in plain words."""
        imgui.indent()
        gated = entry["threshold_fraction"] is not None
        # A short label, with the explanation in the tooltip: a long checkbox label is
        # the one thing in ImGui that cannot wrap.
        changed, gated = imgui.checkbox("classifier probability", gated)
        if changed:
            entry["threshold_fraction"] = 0.5 if gated else None
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Tick this when the model outputs a confidence in 0..1 rather than a\n"
                "position. It is turned into a plain on/off at the cutoff below, and\n"
                "then travels the same weighted path a regressor's value does."
            )
        if entry["threshold_fraction"] is not None:
            imgui.set_next_item_width(_WEIGHT_W)
            changed, fraction = imgui.slider_float(
                "on at or above", float(entry["threshold_fraction"]), 0.0, 1.0
            )
            if changed:
                entry["threshold_fraction"] = round(fraction, 2)

        imgui.set_next_item_width(_WEIGHT_W)
        changed, debounce = imgui.slider_float("hold for (s)", entry["debounce_s"], 0.0, 1.0)
        if changed:
            entry["debounce_s"] = round(debounce, 2)
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "For a held-state control: how long a state must stay put before it\n"
                "counts. Stops a flickering classifier from chattering. 0 disables it."
            )
        imgui.unindent()

    # --- resolution preview -----------------------------------------------------

    def resolved_summary(self) -> str:
        """What the target would make of the working copy, or why it would refuse.

        The last question the file cannot answer on its own: `resolve` is where the
        target's semantics arrive, so this is the difference between a map that parses
        and one that works.
        """
        if not self._capabilities:
            return "Not connected, so nothing has been checked against a target."
        control_map = self.as_control_map()
        if control_map is None:
            return "Not valid yet — see the problems listed above."
        try:
            controls = resolve(control_map, list(self._capabilities))
        except ValueError as exc:
            return str(exc).splitlines()[0]
        lines = []
        for alias, dof in controls.dofs.items():
            if hasattr(dof, "states"):
                lines.append(f"{alias}: held state, rest {dof.rest!r}")
            else:
                routes = ", ".join(
                    f"{ref.address.split('.')[-1]} x{ref.weight}"
                    for ref in controls.routes[alias]
                )
                gate = (
                    f" (on at >= {dof.threshold_fraction})"
                    if dof.threshold_fraction is not None
                    else ""
                )
                lines.append(f"{alias}: number{gate} -> {routes}")
        return "\n".join(lines)

    @property
    def path(self) -> pathlib.Path:
        """The file being edited."""
        return self._path

    @property
    def capabilities(self) -> Sequence[Capability]:
        """What the target reported on the last `Connect`."""
        return self._capabilities


__all__ = ["ControlMapEditor"]
