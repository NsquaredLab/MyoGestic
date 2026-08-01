"""Author a TOML control map from what a target says it exports.

A control map is two vocabularies meeting: your own names on the left, addresses the
target publishes on the right. `ControlMapEditor` asks the target for the right-hand
side — it lists what the renderer exports, with the kind, range and states *it*
declared, and lets a name be pointed at one by picking from that list. The file stays
the source of truth: this reads it, edits it and writes it back with
`myogestic.controls.dump_control_map`.

    editor = ControlMapEditor(pathlib.Path("my_controls.toml"), client=control_client)

    @app.ui
    def ui(ctx):
        if editor.ui():          # True on the frame the map changed
            reload_my_bus()

The return value is an *edge*, not every keystroke. Three things raise it: a save, a
reload, and a `Save As` that moves to a new file.

The file is **watched**. Edit it in any editor and save, and this panel follows on the next
frame; a caller keying off the return value rebuilds with it. If the panel has unsaved edits
when that happens nothing is overwritten — the change is reported, and the choice between
the two versions is offered.
"""

from __future__ import annotations

import logging
import pathlib
import threading
import time
import tomllib
from typing import TYPE_CHECKING, Any

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd

from myogestic.controls import (
    Binding,
    ControlMap,
    TargetRef,
    dump_control_map,
    is_address,
    load_control_map,
    resolve,
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    WARNING,
    destructive_button,
    label_column,
    muted,
    panel_header,
    pop_selected,
    push_selected,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from myogestic.controls import Capability

log = logging.getLogger("myogestic.control_map_editor")


def _unanswered_line(namespace: str, addresses: list[str]) -> str:
    """One line for a target that has not answered, and what it costs this map.

    One format string, shared by [`ControlMapEditor.warnings`][] and the panel that draws
    it, so the two cannot drift.
    """
    n = len(addresses)
    return (
        f"{namespace} has not answered — {n} address{'' if n == 1 else 'es'} "
        f"cannot be checked. Saves either way."
    )

def _search_hint(all_answered: bool) -> str:
    """The picker's search-box placeholder.

    The box doubles as address *entry*: a well-formed address typed into it is offered even
    when no target exports it, which is how a map is authored against a renderer that is not
    running. Only said when a target is silent — with everything answered the tree below is
    the whole list of what is possible.
    """
    return f"{fa.ICON_FA_MAGNIFYING_GLASS}  search" + (
        "" if all_answered else ", or type an address"
    )


#: What a Connect press says when it did not reach every target. Named because `_adopt`
#: compares it by value to retire it once the target turns up.
_NO_ANSWER = "A target did not answer — is it running?"

#: Messages a background round may clear on its own, because each reports a condition that
#: round just re-tested. Anything else in `_message` is the user's own ("Saved 3
#: control(s)…") and is not a retry's to wipe.
_TRANSIENT = (_NO_ANSWER,)

#: What a new alias is called before the user renames it. Numbered on collision.
_NEW_ALIAS = "my_control"

# Layout. Every item here is sized explicitly, because ImGui's default item width is a
# fraction of the *window* — put two defaults on one line with `same_line` and the row is
# wider than the window, and widening the window makes it worse. So: fixed budgets for the
# small controls, and whatever is left for the one that should grow.
#: Below this much room for a row, controls stack instead of sitting side by side.
_STACK_BELOW = 420.0
#: Item spacing allowance between two controls on one line.
_GAP = 12.0
#: Between two groups of buttons on one row: enough to read as a break, cheaper than a line.
_GROUP_GAP = 24.0
#: Enough room for a weight slider to be draggable rather than a nub.
_WEIGHT_W = 130.0
#: A name field wide enough for a real alias, but never more than half a wide row.
_NAME_MAX_W = 240.0
#: The two rows of one control share a label column, so `Name` and `Target` line up.
_ROW_LABELS = ("Name", "Target")
#: And so do the two gates.
_GATE_LABELS = ("On at or above", "Steady for")
#: Widest each value readout gets, reserved so the slider before it never runs it off the
#: edge. Measured from the string, not guessed: "+0.60" and "100%" are not the same width.
_WEIGHT_READOUT = "+0.00"
_PERCENT_READOUT = "100%"
_SECONDS_READOUT = "0.00 s"
#: Which addresses pose the operator's hand — and it is not a filter. A map may name any
#: address any target offers; which stream carries it is the target's business, settled
#: from the manifest at bind time, so nothing here chooses a hand. But the renderer
#: *refuses* one combination: streaming a pose to the operator's hand while also commanding
#: it a movement drives that hand two ways, so it takes one or the other. That is a
#: refusal, not a preference, and warning about it needs knowing which controls are the
#: operator's. Nothing else here does.
#:
#: Matched on the address, which is the only name there is: each control is carried by its
#: own stream, named after the address itself.
_CONTROL_POSE_PREFIX = "vhi.control.pose."

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


#: Where a node keeps its own capability, if it has one. A segment can be both a control
#: and a parent — `vhi.prediction.index` is selectable while `vhi.prediction.wrist` only
#: contains things — so the leaf cannot simply *be* the node.
_LEAF = ""


def address_tree(capabilities: Sequence[Capability]) -> dict[str, Any]:
    """Nest capabilities by their address segments.

    An address is dotted by contract (`myogestic.controls` fixes that, and reserves the
    first segment for the target), so the dots already describe a hierarchy and this only
    has to read it. Nothing here knows what a renderer or a keyboard is: the same code
    organises 19 VHI controls and 214 keys because both spell their addresses the same way.

    Parameters
    ----------
    capabilities
        What to arrange. Usually the picker's already-filtered offering.

    Returns
    -------
    dict
        Nested one level per segment. A node holds its own capability under `_LEAF` when
        the path to it is itself an address, and its children under their segment names.

    Examples
    --------
    >>> from myogestic.controls import Capability
    >>> from myogestic.widgets.vhi.control_map_editor import address_tree
    >>> tree = address_tree([Capability("keyboard.tap.edit.space", "discrete")])
    >>> sorted(tree["keyboard"]["tap"]["edit"])
    ['space']
    """
    root: dict[str, Any] = {}
    for cap in capabilities:
        node = root
        for segment in cap.address.split("."):
            node = node.setdefault(segment, {})
        node[_LEAF] = cap
    return root


def _label_w(label: str) -> float:
    """How much room a widget's trailing label needs, including its spacing."""
    return imgui.calc_text_size(label).x + _GAP


class ControlMapEditor:
    """Edit a TOML control map against a live target's manifest.

    Construct once with the file to edit, then call `ui` each frame.

    Parameters
    ----------
    path
        The TOML file to start on. Read on the first frame, on **Reload**, and whenever it
        changes on disk; written on **Save**. It does not have to exist yet — an absent
        file starts an empty map, so this doubles as a way to create one.

        Not fixed for the life of the editor: **Save as...** writes elsewhere and the
        editor *follows*, so read `path` rather than remembering what was passed in.
    client
        A `myogestic.vhi._control.VhiControlClient`, or anything with a
        ``capabilities()`` method returning a sequence of `myogestic.controls.Capability`.
        Called on **Connect** rather than every frame, because it blocks on an RPC.
        Without it the editor still opens the file and shows it; it just cannot offer a
        list to pick from or validate an address, and says so.
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

    That working copy is also why the file watch asks before acting. An external write is
    picked up silently when the copy still matches the file — the ordinary case, and what
    makes editing the TOML in another window feel immediate. When it does not match, the
    draft is the only place those edits exist, so it is left alone until the user chooses.

    Examples
    --------
    >>> import pathlib
    >>> from myogestic.widgets import ControlMapEditor
    >>> editor = ControlMapEditor(pathlib.Path("hand.toml"))
    >>> editor.ui()                      # each frame, inside @app.ui
    """

    __slots__ = (
        "_answered", "_capabilities", "_client", "_conflict", "_fetched", "_fetching",
        "_last_attempt", "_refetch", "_draft", "_error", "_filter", "_header",
        "_asked", "_baseline", "_clients", "_message", "_path", "_raw", "_raw_error", "_raw_open",
        "_refusal",
        "_all_answered", "_open_picker", "_save_as", "_stamp",
        "_title", "_loaded",
    )

    def __init__(
        self,
        path: pathlib.Path | None = None,
        *,
        client: Any = None,
        clients: Sequence[Any] | None = None,
        title: str = "CONTROL MAP",
    ) -> None:
        self._path = path
        #: Every source of a manifest, in the order they were given. One target used to be
        #: the only possibility; a configuration can now name controls on several — a
        #: renderer and a keyboard, say — and the picker has to offer all of them or half
        #: the addresses look like typos.
        self._clients: tuple[Any, ...] = tuple(
            c for c in ([client] if clients is None else list(clients)) if c is not None
        )
        self._client = self._clients[0] if self._clients else None
        self._title = title
        #: alias -> [(address, weight)], plus the gates. A plain structure rather than a
        #: ControlMap because a half-edited map is not a valid one, and `Binding` is
        #: frozen on purpose.
        self._draft: list[dict[str, Any]] = []
        self._capabilities: tuple[Capability, ...] = ()
        self._filter = ""
        #: Address namespaces some target has answered for. Empty until `Connect`.
        self._answered: frozenset[str] = frozenset()
        self._message = ""
        self._error = ""
        #: The file as text, for editing it directly. Filled when the text view is opened
        #: and when `Revert` is pressed — *not* every frame, because rewriting the buffer
        #: under someone's cursor is how a text box eats what you just typed.
        self._raw = ""
        self._raw_open = False
        self._raw_error = ""
        #: Why a target that *did* answer was rejected — a version mismatch, say. Kept
        #: apart from silence because they are opposite diagnoses that used to render as
        #: one line: "is it running?" about a renderer that is running and answering.
        self._refusal = ""
        #: The comment block the file opened with, kept so a save does not erase what
        #: whoever wrote it was explaining. Only the *leading* block survives — comments
        #: interleaved with entries would need a comment-preserving TOML writer, and
        #: silently dropping those is stated in the class docstring rather than hidden.
        self._header = ""
        self._loaded = False
        #: ``(st_mtime_ns, st_size)`` when this editor last read or wrote the file, or None
        #: for a file that was not there. Both parts, and *ns* rather than seconds: an
        #: editor that rewrites in place can land inside the same whole second as the save
        #: that preceded it, and a same-length rewrite would then look unchanged.
        self._stamp: tuple[int, int] | None = None
        #: The working copy as of the last load or save — the *baseline* of the three-way
        #: comparison. "Has the user edited anything" is draft-vs-baseline; comparing the
        #: draft with what is currently on disk answers a different question and gets this
        #: wrong the moment the file changes underneath, because a draft loaded from the old
        #: contents naturally differs from the new ones.
        self._baseline: dict[str, Any] | None = None
        #: Set when the file changed underneath unsaved edits. Nothing is reloaded while
        #: this is set — the draft is the only copy of what the user typed, so the choice
        #: is theirs to make.
        self._conflict = False
        #: The pending `Save As` dialog. Polled rather than awaited: `pfd` hands back a
        #: handle and the answer arrives some frames later.
        self._save_as: Any = None
        #: Whether the picker popup was open last frame, so opening it can be detected.
        #: Which picker's popup is open, as its ImGui id, or 0. Not a bool: see `_note_open`.
        self._open_picker = 0
        #: Whether every client has answered. The retry's stop condition — see `_adopt`.
        self._all_answered = False
        #: A worker's manifests waiting to be adopted on the render thread, or None. One
        #: assignment of an immutable value, which is the whole of the thread safety here.
        self._fetched: list[Sequence[Capability]] | None = None
        #: Whether a worker is out asking, so only one ever is.
        self._fetching = False
        #: When one last went out, to space the retries.
        self._last_attempt = 0.0
        #: Set by the button to skip the retry gap once.
        self._refetch = False
        #: Whether the fetch in flight came from the button rather than the timer. Only a
        #: press gets an answer in words — a timer that reported every round would be back to
        #: printing "1 target(s) did not answer" forever.
        self._asked = False

    # --- file -------------------------------------------------------------------

    @property
    def label(self) -> str:
        """What to call this map in a message or a tab — its filename, or "Untitled"."""
        return self._path.name if self._path is not None else "Untitled"

    def _on_disk(self) -> pathlib.Path | None:
        """The file, if there is one and it exists.

        The one place that answers "is there anything to read": an untitled map has no path
        at all, and a named one may not have been written yet. Both are ordinary states, and
        collapsing them here keeps every reader from repeating the pair of checks.
        """
        if self._path is None:
            return None
        return self._path if self._path.exists() else None

    def load(self) -> None:
        """Read the file into the working copy, replacing anything unsaved."""
        self._draft = []
        self._error = ""
        self._header = ""
        self._conflict = False
        self._stamp = self._current_stamp()
        if self._on_disk() is None:
            self._message = (
                "Untitled — press Save to choose a location."
                if self._path is None
                else f"{self.label} does not exist yet — Save will create it."
            )
            self._baseline = self._snapshot()
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
            self._baseline = self._snapshot()
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
        self._message = f"Loaded {len(self._draft)} control(s) from {self.label}."
        self._baseline = self._snapshot()
        self._loaded = True

    def raw_text(self) -> str:
        """The working copy as TOML text, for editing by hand.

        The file's own bytes when nothing has been changed in the fields, so opening the
        text view shows exactly what is on disk — comments and all. Once the fields have
        diverged it is rendered from them instead, because showing stale text next to
        live fields is worse than losing the comments.
        """
        rendered = dump_control_map(self.as_control_map() or ControlMap(bindings={}))
        if self._on_disk() is None:
            return rendered
        if self._unparseable_on_disk():
            return self._path.read_text()   # show it so it can be fixed by hand
        return self._path.read_text() if self._matches_disk() else rendered

    def _unparseable_on_disk(self) -> bool:
        """Whether the file cannot be loaded at all. False when there is no file."""
        if self._on_disk() is None:
            return False
        try:
            load_control_map(tomllib.loads(self._path.read_text()))
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            return True
        return False

    def _matches_disk(self) -> bool:
        """Whether the working copy still says what the file says.

        The test for "is there unsaved work here", used both to decide what the text view
        shows and to decide whether an external change may be picked up silently. One
        implementation on purpose: two could disagree, and then the text view would show
        the file while the reload guard believed the draft had diverged.

        A file that will not parse does **not** match, so a reload asks rather than acts.
        """
        if self._on_disk() is None:
            return False
        try:
            on_disk = load_control_map(tomllib.loads(self._path.read_text())).as_control_space()
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            return False
        mine = (self.as_control_map() or ControlMap(bindings={})).as_control_space()
        return on_disk == mine

    def _snapshot(self) -> dict[str, Any]:
        """The working copy in a comparable form."""
        return (self.as_control_map() or ControlMap(bindings={})).as_control_space()

    def _dirty(self) -> bool:
        """Whether reloading would throw away something the user typed.

        Against the **baseline**, not against the file: the question is whether this panel
        has been edited since it last agreed with disk. Comparing with the current file
        would call every external change a conflict, because the draft was loaded from the
        contents that change replaced.

        One case beyond the fields: the text view holds TOML that only reaches the draft on
        **Apply**, so an untouched draft can still be sitting under half-written text.
        Reloading then refreshes that buffer and the typing is gone.
        """
        if self._raw_open and self._raw != self.raw_text():
            return True
        return self._baseline is not None and self._snapshot() != self._baseline

    def _current_stamp(self) -> tuple[int, int] | None:
        """The file's ``(mtime_ns, size)``, or None when it is not there."""
        if self._path is None:
            return None
        try:
            info = self._path.stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def _stale_on_disk(self) -> bool:
        """Whether the file has been written since this editor last read or wrote it."""
        current = self._current_stamp()
        if current is None:
            # Absent is not stale: `load` already treats a missing file as "Save will
            # create it", and reporting a change every frame for a file that is simply not
            # there yet would make the banner permanent.
            return False
        return current != self._stamp

    def poll_disk(self) -> bool:
        """Pick up an external change, and finish a pending `Save As`.

        Returns True when the working copy changed as a result, so a caller that built
        something from this file — a bus, a set of sliders — knows to rebuild it.

        Called from `ui` every frame. A `stat` per frame is microseconds, and the
        alternative is a watcher thread whose callback would have to be marshalled back
        onto the render frame anyway.
        """
        changed = self._finish_save_as()
        if not self._stale_on_disk():
            return changed
        if self._dirty() or self._unparseable_on_disk():
            # Do not touch the draft. Whoever is typing owns it until they say otherwise —
            # and a file that will not parse is exactly what catching an editor mid-save
            # looks like, so that is surfaced rather than loaded over the top.
            self._conflict = True
            return changed
        self.load()
        self._message = f"Reloaded {self.label} — it changed on disk."
        if self._raw_open:
            self._raw = self.raw_text()
        return True

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
        if self._path is None:
            # Untitled. Refused rather than written somewhere arbitrary — a file the user
            # cannot find again is worse than a save that did not happen. The UI turns this
            # into the Save-as dialog, so it is not a dead end.
            self._message = "Untitled — choose a location with Save as..."
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            dump_control_map(control_map, header=self._header or _HEADER)
        )
        # Re-stamp immediately: the write just changed the file, and without this the very
        # next `poll_disk` would report our own save as an external change.
        self._stamp = self._current_stamp()
        self._baseline = self._snapshot()
        self._conflict = False
        self._message = f"Saved {len(self._draft)} control(s) to {self.label}."
        return True

    def save_as(self, path: pathlib.Path) -> bool:
        """Write the working copy to `path` and continue editing **there**.

        The editor follows the file: later saves go to the new path, the change watch
        follows it, and a caller reading `path` rebuilds from it. Reads as "save a copy and
        keep working on the copy", which is what an editor normally means by Save As — and
        in the playground it is also the only coherent choice, because the sliders are built
        from whatever file this editor is on.

        The original is left exactly as it was. False, and the path unchanged, if the
        working copy would not load back.
        """
        previous = self._path
        self._path = pathlib.Path(path)
        if self.save():
            return True
        self._path = previous
        return False

    def take_disk_version(self) -> bool:
        """Resolve a conflict by discarding the draft and reloading. Always changes."""
        self.load()
        self._message = f"Reloaded {self.label}, discarding the unsaved edits."
        if self._raw_open:
            self._raw = self.raw_text()
        return True

    def keep_mine(self) -> None:
        """Resolve a conflict by keeping the draft and ignoring what is on disk.

        Re-stamps, so the same external change is not reported again on the next frame —
        otherwise dismissing the banner would only make it reappear.
        """
        self._conflict = False
        self._stamp = self._current_stamp()
        self._message = (
            f"Keeping the unsaved edits. {self.label} on disk is newer — Save "
            f"overwrites it."
        )

    def _finish_save_as(self) -> bool:
        """Collect the result of a pending `Save As` dialog, if it has one yet."""
        dialog = self._save_as
        if dialog is None or not dialog.ready():
            return False
        result = dialog.result()
        self._save_as = None
        if not result:
            return False            # cancelled: the path must not move
        return self.save_as(pathlib.Path(result))

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

    def _unverifiable(self, address: str) -> bool:
        """Whether nothing that could vouch for `address` has answered yet.

        The rule `_gate_rules` already states and this used to contradict: unknowable is
        allowed, because refusing on a guess blocks a valid file.
        """
        if not address:
            return False
        return address.split(".", 1)[0] not in self._answered

    def unanswered(self) -> dict[str, list[str]]:
        """Namespaces nothing has answered for, each with this map's addresses under it.

        The data behind [`warnings`][]. Public because two callers want the namespaces and
        not the prose: `resolved_summary` used to recover them by splitting the sentences
        back apart on their quote marks.
        """
        found: dict[str, list[str]] = {}
        for entry in self._draft:
            for address, _weight in entry["targets"]:
                if self._unverifiable(address):
                    found.setdefault(address.split(".", 1)[0], []).append(address)
        return found

    def warnings(self) -> list[str]:
        """What cannot be checked yet — never a reason to refuse a save.

        Separate from `problems` on purpose: one is about the file, which the editor owns,
        and the other is about which programs happen to be running, which it does not. A
        map naming a Virtual Hand control is a valid map with the renderer switched off.

        **One line per silent namespace, not per address.** It was per address, which made a
        single fact — "VHI is not running" — into a five-bullet list that said the same
        sentence five times with a different address in the middle. Which addresses is the
        detail; the UI hangs it on the line's tooltip.
        """
        return [_unanswered_line(ns, addrs) for ns, addrs in sorted(self.unanswered().items())]

    def problems(self) -> list[str]:
        """Everything wrong with the working copy right now, in reading order.

        Cheap enough to call every frame. Checked here rather than at save because a
        disabled Save button with a reason beside it is a better answer than a rejected
        write.
        """
        found: list[str] = []
        seen: dict[str, int] = {}
        exported = {cap.address for cap in self._capabilities}
        # Two aliases on one control is the conflict a target refuses. Keyed on the
        # address, which *is* the physical control's identity: a renderer advertises one
        # spelling per control and gives each its own stream, so two addresses are two
        # controls and one address is one control, with nothing to collapse first.
        controls: dict[str, list[str]] = {}
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
                if self._unverifiable(address):
                    # Not a problem with the *file*. Whether some program is running is not
                    # a property of a TOML, and blocking Save on it made a valid map
                    # unsavable the moment one of several targets was down. Reported by
                    # `warnings`, which does not block.
                    pass
                elif self._answered and address not in exported:
                    # Its namespace answered and does not have it: a typo, or a map written
                    # for a newer build. Checkable, so it is caught.
                    found.append(f"{alias}: the target does not export {address!r}.")
                if not -1.0 <= weight <= 1.0 or weight == 0.0:
                    found.append(
                        f"{alias}: weight {weight} is outside [-1, 1] or zero. A weight "
                        f"scales a value, so it cannot invent range; a negative one "
                        f"needs a target that declares signed motion."
                    )
                cap = by_address.get(address)
                if cap is not None and cap.kind == "continuous":
                    # Continuous only: two aliases holding one *state* is a different
                    # thing, gated by the pose-versus-movement check below.
                    controls.setdefault(cap.address, []).append(alias)

            fraction = entry["threshold_fraction"]
            if fraction is not None and not 0.0 <= fraction <= 1.0:
                found.append(f"{alias}: threshold_fraction must be between 0 and 1.")
            no_threshold, no_debounce = self._gate_rules(entry)
            if fraction is not None and no_threshold:
                found.append(f"{alias}: {no_threshold}.")
            if entry["debounce_s"] and no_debounce:
                found.append(f"{alias}: {no_debounce}.")

        # The renderer's own exclusion, learned from its refusal: streaming a pose to the
        # control hand and commanding it a movement would both drive that hand, so it
        # accepts one or the other. Caught here rather than at the handshake.
        posed = [
            entry["alias"]
            for entry in self._draft
            for address, _ in entry["targets"]
            if (cap := by_address.get(address)) is not None
            and cap.kind == "continuous"
            and cap.address.startswith(_CONTROL_POSE_PREFIX)
        ]
        held = [
            entry["alias"]
            for entry in self._draft
            for address, _ in entry["targets"]
            if (cap := by_address.get(address)) is not None and cap.kind != "continuous"
        ]
        if posed and held:
            found.append(
                f"{sorted(set(posed))} stream a pose to the operator's hand while "
                f"{sorted(set(held))} command it a movement. Both drive that hand, so the "
                f"renderer accepts one or the other — keep the pose, or keep the movement."
            )

        for address, owners in controls.items():
            distinct = sorted(set(owners))
            if len(distinct) > 1:
                found.append(
                    f"{' and '.join(distinct)} both reach the same control ({address}). "
                    f"One control cannot take two outputs."
                )
        return found

    # --- editing ----------------------------------------------------------------

    def add_control(self, alias: str = "", address: str = "") -> None:
        """Add a control, named and pointed however the caller likes.

        A placeholder name is always numbered — `my_control_1`, `my_control_2` — rather
        than leaving the first one bare and numbering the rest from two. The sequence reads
        and sorts the same way all the way down, and there is no first-one-is-special case.

        A name the caller *asked* for is kept as it is when it is free, because that is
        what they asked for; only a collision gets the lowest free suffix.
        """
        taken = {entry["alias"] for entry in self._draft}
        stem = alias or _NEW_ALIAS
        name = stem if alias and stem not in taken else ""
        suffix = 1
        while not name or name in taken:
            name = f"{stem}_{suffix}"
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
        """Render the editor. Returns True on the frame the map changed.

        "Changed" is a save, a reload — whether pressed or picked up from disk — or a
        `Save As` that moved to a new file. All three mean the same thing to a caller: the
        control map it built something from is no longer the one in front of it.
        """
        if not self._loaded:
            self.load()
        # Polled *before* the header: it can raise the conflict flag, and the dot reports it.
        saved = self.poll_disk()
        self.poll_connect()
        dot, detail = self._status()
        panel_header(self._title, status=dot)
        imgui.set_item_tooltip(detail)

        # One row for every action, wrapping only when a button genuinely does not fit —
        # `Connect` had a row of its own for a subject the row no longer states, which spent a
        # whole line on a gap. It keeps the gap, as a gap: re-asking the targets and writing
        # the file are different subjects, and `_GROUP_GAP` is what says so now.
        #
        # Labels stay: the contract reserves icon-only for the header's one action, and six
        # places in this code tell a user to press "Connect" by name. The glyphs are the ones
        # the repo already uses for these meanings (`ml/widgets.py` pairs FLOPPY_DISK with the
        # word "Save", `widgets/vhi/palette.py` pairs ARROWS_ROTATE with re-fetching).
        can_save = not self.problems()
        for index, (label, handler, disabled, gap) in enumerate(
            (
                (f"{fa.ICON_FA_ARROWS_ROTATE}  Connect", None, False, 0.0),
                (f"{fa.ICON_FA_FLOPPY_DISK}  Save", None, not can_save, _GROUP_GAP),
                # Same content, so the same validity rule: an editor that refused Save and
                # allowed Save As would write the broken file to a different name.
                ("Save as...", None, not can_save or self._save_as is not None, 0.0),
                ("Reload", self.load, False, 0.0),
            )
        ):
            if index and self._room_for(imgui.calc_text_size(label).x + 24.0 + gap):
                imgui.same_line(0.0, imgui.get_style().item_spacing.x + gap)
            imgui.begin_disabled(disabled)
            if imgui.button(label):
                if label.endswith("Connect"):
                    # Ask again now rather than waiting out the retry gap. Off-thread, so a
                    # target that is not listening costs a spinner-free second, not a frozen
                    # window.
                    self._refetch = True
                    self.poll_connect()
                elif label.endswith("Save") and self._path is None:
                    # Untitled: Save has nowhere to go, so it *is* Save as. Better than a
                    # disabled button whose reason is somewhere else on screen.
                    self._save_as = pfd.save_file(
                        "Save the control map as", str(pathlib.Path.cwd())
                    )
                elif label.endswith("Save"):
                    saved = self.save() or saved
                elif label == "Save as...":
                    self._save_as = pfd.save_file(
                        "Save the control map as", str(self._path.parent if self._path else pathlib.Path.cwd())
                    )
                else:
                    # Reload reports a change too. It did not before, so pressing it
                    # reloaded this panel while whatever was built from the file kept
                    # running the old map.
                    handler()
                    saved = True
            imgui.end_disabled()
            if label.endswith("Connect"):
                imgui.set_item_tooltip(
                    "Re-ask every target what it exports. This happens on its own too — "
                    "the button is for when you have just launched one."
                )

        # What a silent target costs *this* map: the one line about the connection worth
        # printing, and only when the map actually names an address nothing can vouch for.
        # It was a bulleted block at the bottom, one bullet per address, so a single fact
        # ("VHI is not running") arrived as five identical sentences. Which addresses is the
        # detail, so it goes on the tooltip.
        silent = self.unanswered()
        for namespace, addresses in sorted(silent.items()):
            imgui.push_style_color(imgui.Col_.text, WARNING)
            imgui.text_wrapped(_unanswered_line(namespace, addresses))
            imgui.pop_style_color()
            imgui.set_item_tooltip("\n".join(addresses))

        # A target can be silent while this map names nothing of its own. The loop above is
        # per *named* address, so that case said nothing at all: the picker simply had no
        # branch for the renderer, with nothing on screen to say why — which reads as "this
        # is the whole list of what is possible" rather than "one target has not answered".
        # It also has to say what to do about it, because you *can* author against a target
        # that is not running: a typed address is offered, and saves.
        if not self._all_answered and not silent:
            imgui.push_style_color(imgui.Col_.text, WARNING)
            imgui.text_wrapped(
                "A target has not answered, so its controls are not in the list. "
                "Type its address in the search box to use one anyway."
            )
            imgui.pop_style_color()

        if self._conflict:
            saved = self._conflict_ui() or saved
        # `_refusal` is read live rather than copied into `_message`, because it is a
        # standing fact about the pair of programs and not a line an event left behind:
        # copied, it outlived the thing it reported, and the panel went on telling someone
        # who had just updated their renderer to update their renderer.
        if self._error or self._refusal or self._message:
            imgui.push_style_color(
                imgui.Col_.text, DANGER if self._error else muted()
            )
            imgui.text_wrapped(self._error or self._refusal or self._message)
            imgui.pop_style_color()

        imgui.separator()
        for index, entry in enumerate(list(self._draft)):
            self._entry_ui(index, entry)

        # Under the last row, because that is where the row it adds will appear — and it is
        # the only thing on screen when the map is empty, which is exactly when it is the
        # thing to press. It used to sit in the row above beside Save, where it read as a
        # file command and set the panel's "the map changed" return value on every click.
        if imgui.button(f"{fa.ICON_FA_PLUS}  Add control"):
            self.add_control()
        imgui.set_item_tooltip(
            "Append a control. Name it, then pick what it drives from the dropdown."
        )

        problems = self.problems()
        if problems:
            imgui.separator()
            imgui.text_colored(DANGER, "Cannot save yet:")
            for problem in problems:
                imgui.bullet()
                imgui.text_wrapped(problem)
        # No "cannot be checked yet" block here: that is connection state, and it is reported
        # once, up beside the connection state. What is left at the bottom is only what stops
        # a save — which is the panel's own subject.

        saved = self._raw_ui() or saved
        return saved

    def _conflict_ui(self) -> bool:
        """The file changed under unsaved edits. Ask, and change nothing until told.

        Both answers are non-destructive on their own terms: one takes the file and says
        the edits went, the other keeps the edits and says the file on disk is newer. What
        is not offered is doing nothing forever — the banner stays until it is answered,
        because a silently-diverged editor is how you overwrite someone else's change.
        """
        changed = False
        imgui.push_style_color(imgui.Col_.text, DANGER)
        imgui.text_wrapped(
            f"{self.label} changed on disk while this panel has unsaved edits. "
            f"Nothing has been touched yet."
        )
        imgui.pop_style_color()
        if imgui.button("Reload from disk"):
            changed = self.take_disk_version()
        if self._room_for(imgui.calc_text_size("Keep my edits").x + 24.0):
            imgui.same_line()
        if imgui.button("Keep my edits"):
            self.keep_mine()
        return changed

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

    #: How long to wait before asking the targets again.
    #:
    #: Not a stall budget, which is what this comment used to claim: a renderer that is not
    #: running *refuses* the connection, so `capabilities()` is back in single-digit
    #: milliseconds (measured: 7 ms cold, 0.08 ms after). The client's two-second deadline
    #: only applies when something holds the port without answering, which is the rare case.
    #: So this is a politeness interval — often enough that a renderer starting or stopping
    #: shows up within a few seconds, rare enough that it is not a round trip per frame.
    _RETRY_EVERY_S = 5.0

    def poll_connect(self) -> None:
        """Ask silent targets what they export, off the render thread.

        Called every frame from `ui`. Connecting was click-only because
        `VhiControlClient.capabilities()` blocks for its RPC timeout when nothing is
        listening, and a two-second stall per frame is not a thing a UI can do. But that is
        an argument against blocking *here*, not against connecting at all — a
        `KeyboardTarget` answers from a local list and never needed a click in the first
        place.

        So the ask happens on a worker and the answer is adopted on the next frame, the same
        shape `poll_disk` and the `Save as...` dialog already use. The button remains, and
        `ARROWS_ROTATE` is honest for it: with this running, pressing it means *re-fetch
        now*, which is what that glyph means everywhere else in the app.

        **It keeps asking after everyone has answered.** It used to stop, on the reasoning
        that there was nothing left to ask — which reads the manifest as a fact that only
        arrives. A target can also *go away*: closing the renderer mid-session left this
        panel offering its controls and vouching for a map it could no longer check, which
        is worse than an empty picker because it is not empty, it is wrong. What made
        stopping look necessary was the two-second stall in `_RETRY_EVERY_S`'s old comment;
        a target that is down costs about 7 ms, so there is nothing to save.
        """
        pending, self._fetched = self._fetched, None
        if pending is not None:
            self._adopt(pending)
        if self._fetching or (
            not self._refetch
            and time.monotonic() - self._last_attempt < self._RETRY_EVERY_S
        ):
            return
        self._asked = self._asked or self._refetch  # a press, not the timer
        self._refetch = False
        self._fetching = True
        self._last_attempt = time.monotonic()
        threading.Thread(target=self._fetch, name="control-map-connect", daemon=True).start()

    def _fetch(self) -> None:
        """Ask every client, on a worker thread. Never touches UI state."""
        answers: list[Sequence[Capability]] = []
        refusals: list[str] = []
        try:
            for client in self._clients:
                # One `try` per client, not one around the loop. It used to wrap the whole
                # loop, so the first client to raise took every client after it down with
                # it — one unhappy target emptied the entire picker, including a
                # `KeyboardTarget` that answers off a local list and cannot fail.
                try:
                    fetch = getattr(client, "capabilities", None)
                    got = fetch() if callable(fetch) else None
                except ValueError as exc:
                    # A refusal, not an absence. The renderer answered and was rejected —
                    # a vocabulary older than this client speaks, say — and swallowing that
                    # into a DEBUG line rendered it as "is it running?", which is the exact
                    # silence the gate was added to abolish, on the surface a user is most
                    # likely looking at.
                    refusals.append(str(exc))
                    continue
                except Exception:  # noqa: BLE001 - a worker may not take the app down
                    log.debug("a target raised while reporting its manifest", exc_info=True)
                    continue
                if got:
                    answers.append(got)
        finally:
            # Always, or `_fetching` stays True and the editor never asks anything again.
            self._refusal = " ".join(refusals)
            self._fetched = answers
            self._fetching = False

    def _connect(self) -> None:
        """Ask every target what it exports, right now, blocking.

        What the button does. `poll_connect` is what happens without one.

        Merged into one manifest, because a control map is one file and it may name
        controls on several targets. Duplicate addresses keep the first source's answer —
        the address rule namespaces targets by their first segment precisely so two of
        them cannot mean different things by one name, so a duplicate is a bug in a
        manifest rather than something to arbitrate here.
        """
        answers: list[Sequence[Capability]] = []
        refusals: list[str] = []
        for client in self._clients:
            fetch = getattr(client, "capabilities", None)
            try:
                got = fetch() if callable(fetch) else None
            except ValueError as exc:
                # A target that answered and was *refused* — the version gate, say. Held
                # rather than raised: this runs from a click, so a raise takes the window
                # down; and held rather than dropped, because reporting a renderer that is
                # up and talking as one that "did not answer" is precisely the silent
                # failure the refusal exists to end.
                refusals.append(str(exc))
                continue
            if got:
                answers.append(got)
        self._refusal = " ".join(refusals)
        self._adopt(answers)

    def _adopt(self, answers: list[Sequence[Capability]]) -> None:
        """Take a set of manifests as the truth. Render thread only."""
        merged: dict[str, Capability] = {}
        for capabilities in answers:
            for cap in capabilities:
                merged.setdefault(cap.address, cap)
        self._capabilities = tuple(merged.values())
        # Which *targets* have spoken, by the first address segment the address rule
        # reserves for exactly that. With one target "the manifest is empty" meant "I know
        # nothing"; with two it means "I know about one of them", and an address belonging to
        # the silent one is unverifiable rather than wrong. Same namespace reasoning
        # `VhiTarget` uses to decide what is its to render, so the two cannot disagree.
        self._answered = frozenset(
            address.split(".", 1)[0] for address in merged
        )
        # Every *client*, not every namespace that turned up. `_answered` being non-empty was
        # the retry's stop condition, and a `KeyboardTarget` answers instantly from a local
        # list — so the first frame filled it, the retry stopped for good, and a VHI launched
        # afterwards was never asked again. It looked like "VHI is running and I still cannot
        # pick it", because that is exactly what it was.
        self._all_answered = len(answers) == len(self._clients)
        # Silent unless the user *asked*. "214 controls from keyboard" and "1 target(s) did
        # not answer" were two permanent lines of plumbing: how many addresses a target
        # happens to publish is not a thing anyone reads, and with connecting on a timer
        # "did not answer" is a running commentary on a background retry. What is worth
        # saying — this map names a target that has not answered, so it cannot be checked —
        # is said by `unanswered`, once, and only when the map actually names one.
        if self._all_answered and (self._asked or self._message in _TRANSIENT):
            # Retired by the *timer*, not only by the next press. The retry is what notices a
            # target coming up, so without this the line a press left behind outlived the
            # fact it reported: the picker offered the renderer's controls, the warning above
            # cleared, and this still said it had not answered. Compared by value because
            # `_message` also carries "Saved 3 control(s)…", which a background round has no
            # business wiping.
            self._message = ""
        elif self._asked:
            # A pressed button with no visible effect is worse than the noise. Only the
            # explicit press gets a word back; the timer stays quiet.
            #
            # The test was `not merged` — "*nothing* answered" — which cannot fire in an app
            # holding a `KeyboardTarget`, because that one always answers. So pressing
            # Connect with the renderer closed cleared the message instead of setting one,
            # and looked exactly like a press that had worked.
            self._message = _NO_ANSWER
        self._asked = False

    def _entry_ui(self, index: int, entry: dict[str, Any]) -> None:
        """One control: its name, its targets, its gates."""
        imgui.push_id(f"dof{index}")
        avail = imgui.get_content_region_avail().x
        stacked = avail < _STACK_BELOW

        remove = f"{fa.ICON_FA_TRASH}  Remove control"
        label_column(
            "Name",
            _ROW_LABELS,
            reserve=0.0 if stacked else _label_w(remove) + 24.0,
            max_width=_NAME_MAX_W,
        )
        changed, alias = imgui.input_text("##name", entry["alias"])
        if changed:
            entry["alias"] = alias
        if not stacked:
            imgui.same_line()
        # The only action left on this row, because it is the only one that acts on the *row*.
        # It was sat beside `Add target`, which acts on the list below — two buttons of equal
        # weight for a delete and an append, and neither next to what it did.
        if destructive_button(remove, tooltip="Delete this control and all of its targets."):
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

        # At the end of the list it appends to, indented with it — the same rule as
        # `+ Add control` at the end of the control list, and the same glyph. Up in the name
        # row it was one indent level above the rows it added.
        imgui.indent()
        if imgui.button(f"{fa.ICON_FA_PLUS}  Add target"):
            entry["targets"].append(["", 1.0])
        imgui.set_item_tooltip(
            "Drive this control from another address too. Several targets are summed, each "
            "scaled by its weight."
        )
        imgui.unindent()

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
                + _label_w("Weight")
                + _label_w(_WEIGHT_READOUT)
                + (_label_w(fa.ICON_FA_XMARK) + 24.0 + _GAP if drop else 0.0)
                + _GAP * 2
            )
        )
        self._picker(
            pair,
            width=label_column(
                "Target", _ROW_LABELS, reserve=reserved, max_width=_PICKER_MAX_W
            ),
        )

        if not stacked:
            imgui.same_line()
        imgui.align_text_to_frame_padding()
        imgui.text("Weight")
        imgui.same_line()
        imgui.set_next_item_width(_WEIGHT_W)
        # The value is drawn after the track rather than inside it: a number centred in a
        # wide flat frame is what an input field looks like, which is why this row read as
        # three text boxes.
        changed, weight = imgui.slider_float("##weight", pair[1], -1.0, 1.0, "")
        if changed:
            pair[1] = round(weight, 2)
        imgui.same_line()
        imgui.text_colored(muted(), f"{pair[1]:+.2f}")
        if not drop:
            return False
        imgui.same_line()
        # A glyph, not the letter "x", and destructive like the control-level delete it is a
        # smaller version of. The label stays off: at this size the tooltip is the label, and
        # the row already says which target it belongs to.
        return destructive_button(fa.ICON_FA_XMARK, tooltip="Remove this target.")

    def _offered(self, current: str = "") -> list[Capability]:
        """The controls worth offering: every address every connected manifest exports.

        No reduction and no filtering. There used to be two of each — drop a continuous
        control the manifest gave no channel, and collapse several addresses that shared
        one channel down to the shortest — and both are gone with the fields they read.
        A renderer advertises one spelling per control and gives each its own stream, so
        every address on this list is a distinct thing a map can point at, and an address
        that is not on it is not exported at all.

        `current` is accepted and unused: nothing is collapsed away, so there is no longer
        anything for it to rescue. Kept so the picker's call site does not have to know
        that.
        """
        return list(self._capabilities)

    def _gate_rules(self, entry: dict[str, Any]) -> tuple[str, str]:
        """Why `threshold_fraction` / `debounce_s` cannot apply to this entry, or "".

        The single place that knows, so the checkbox that offers a gate and the validation
        that refuses one cannot disagree — the bug this exists to stop is a UI that offers
        what the resolver will reject, which then surfaces as a refusal from the bus, layers
        away from the click.

        Empty strings mean "allowed". Unknowable — offline, or an address the target does
        not export — is also allowed: refusing on a guess would block a valid file.
        """
        address = entry["targets"][0][0] if entry["targets"] else ""
        cap = next((c for c in self._capabilities if c.address == address), None)
        if cap is None:
            return "", ""
        if cap.kind == "continuous":
            # A number has no state transition to hold, and the bus applies the stability
            # gate to discrete DOFs only — so a debounce here would silently do nothing.
            return "", "a number has no state transition to hold — this is for held states"
        if len(cap.states) != 2:
            # A single number cannot pick among more than two states, and inventing an
            # ordering over states nobody declared would be worse than refusing.
            return (
                f"{address.split('.')[-1]} has {len(cap.states)} states, so a probability "
                f"cannot pick one — send the state name instead",
                "",
            )
        return "", ""

    def _note_open(self, key: int, opened: bool) -> bool:
        """Record which picker is open, clearing the search on the frame it opens.

        Returns whether *this* call is that frame.

        Keyed by which picker, because one bool for the whole panel cannot say it. Every
        picker writes the flag once per frame, so the closed ones drawn *after* the open one
        overwrite its `True` with `False`; the open one then reads "it was closed" on every
        following frame and clears the search on each of them. Typing into it was therefore
        impossible from the second row of the second control onwards, and worked only in a map
        whose open picker happened to be the last one drawn — which is why it looked
        intermittent rather than broken.

        The search itself is still one string, deliberately: only one popup can be open, and a
        per-row search that survived closing would hide the list next time it opened.
        """
        if opened and self._open_picker != key:
            self._open_picker = key
            self._filter = ""
            return True
        if not opened and self._open_picker == key:
            self._open_picker = 0
        return False

    def _picker(self, pair: list[Any], *, width: float) -> None:
        """Choose a control from what the target exports, or type one when offline."""
        address = pair[0]
        imgui.set_next_item_width(width)
        if not self._capabilities:
            changed, typed = imgui.input_text("##control", address)
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
        key = imgui.get_id("##control")  # unique per row: `_entry_ui` pushed the row's id
        opened = imgui.begin_combo("##control", label)
        just_opened = self._note_open(key, opened)
        if opened:
            imgui.set_next_item_width(popup_w - 24.0)
            if just_opened:
                # Click, then type. The list is long enough that searching is the normal way
                # to use it, so the search box is where the keyboard should already be.
                imgui.set_keyboard_focus_here()
            changed, self._filter = imgui.input_text_with_hint(
                "##search", _search_hint(self._all_answered), self._filter
            )
            # The search box doubles as address *entry*. Offline this widget is a plain text
            # field and an address can be typed; connected, it used to become a tree and the
            # only way to set a control was picking a leaf — so a target that has not been
            # reached yet, or one whose address you already know, became unreachable the
            # moment anything answered. Typing a well-formed address offers it here.
            typed = self._typed_offer()
            if typed:
                if imgui.selectable(f'use "{typed}"', False)[0]:
                    pair[0] = typed
                    imgui.close_current_popup()
                imgui.set_item_tooltip(
                    "No connected target exports this. It will be saved as written and "
                    "refused at bind time if nothing renders it."
                )
                imgui.separator()
            # Filter *before* building the tree rather than while walking it: a pruned tree
            # has no branches that lead nowhere, so "open everything" is the whole of the
            # search behaviour instead of a per-node judgement about what still matches.
            offered = [
                cap
                for cap in self._offered(current=address)
                if not self._filter or self._filter.lower() in cap.address.lower()
            ]
            if offered:
                self._tree_ui(address_tree(offered), address, pair)
            else:
                imgui.text_disabled("nothing matches that")
            imgui.end_combo()
        # What the target declared about the *selected* control, on hover: read once,
        # rather than repeated down every row of the list.
        cap = next((c for c in self._capabilities if c.address == address), None)
        if cap is not None and imgui.is_item_hovered():
            imgui.set_tooltip(f"{cap.address}\n{self._summary(cap)}")

    def _status(self) -> tuple[imgui.ImVec4, str]:
        """The header dot for *this map*, and the same news as text.

        `CIRCLE` means "the live state of whatever this panel controls", and this panel
        controls a **file**, not a renderer. So the dot answers "can this map be saved and
        is it in step with disk" — the target's reachability is a different subject and gets
        its own line beside Connect.

        Grey unless something needs doing. A dot that is green whenever nothing is wrong is
        a dot nobody looks at.
        """
        problems = self.problems()
        where = str(self._path) if self._path else "Untitled — not saved yet"
        if self._error:
            return DANGER, f"{where}\nThat file will not load — see the message below."
        if self._conflict:
            return DANGER, f"{where}\nChanged on disk under unsaved edits — answer the banner."
        if problems:
            more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
            return WARNING, f"{where}\nCannot save yet: {problems[0]}{more}"
        if self._dirty():
            return WARNING, f"{where}\nUnsaved edits."
        return IDLE, f"{where}\nSaved, and it matches the file on disk."

    def _typed_offer(self) -> str:
        """The search text, when it is an address worth offering as one. Else "".

        Offered only when it is **well-formed** and **not already in the manifest**: a
        malformed one would be written and then refused by the loader, and one the target
        exports is in the tree below, where its declared kind and range are visible.

        This exists because the picker used to lose free-text entry the moment any target
        answered — offline it is a text field, connected it was a tree and nothing else. So
        an address you know but nothing has advertised yet became unreachable exactly when
        the app was working, which is backwards.
        """
        typed = self._filter.strip()
        if not is_address(typed):
            return ""
        if typed in {cap.address for cap in self._capabilities}:
            return ""
        return typed

    def _tree_ui(self, nodes: dict[str, Any], address: str, pair: list[Any]) -> None:
        """Walk one level of the address tree, deepening on every dot.

        A flat list was fine for six controls and unusable for the two hundred a keyboard
        exports. The tree costs nothing to derive — the addresses already say where they
        belong — and it is the same shape in the picker as it is in the file.
        """
        for segment in sorted(nodes):
            node = nodes[segment]
            leaf = node.get(_LEAF)
            children = {name: sub for name, sub in node.items() if name != _LEAF}
            if leaf is not None and not children:
                self._leaf_ui(segment, leaf, address, pair)
                continue
            # A branch that is *also* a control shows both: the row that selects it, then
            # what hangs off it. `vhi.prediction.thumb` was exactly this before the rename,
            # and another target may well do it again.
            if self._filter:
                # Every remaining branch leads to a match, because the pruning already
                # happened. Opening them is what makes typing feel like searching.
                imgui.set_next_item_open(True)
            open_ = imgui.tree_node(segment)
            if open_:
                if leaf is not None:
                    self._leaf_ui("(this one)", leaf, address, pair)
                self._tree_ui(children, address, pair)
                imgui.tree_pop()

    def _leaf_ui(self, segment: str, cap: Capability, address: str, pair: list[Any]) -> None:
        """One selectable control, labelled by its last segment.

        The *path* to the row is the address, so repeating it in full on every row would
        only cost width — but the tooltip still gives it verbatim, because the file spells
        it that way and one vocabulary is the rule.
        """
        selected, _ = imgui.selectable(f"{segment}{self._detail(cap)}", cap.address == address)
        if imgui.is_item_hovered():
            imgui.set_tooltip(f"{cap.address}\n{self._summary(cap)}")
        if selected:
            pair[0] = cap.address

    #: Above this many states a row lists the count instead of the names. Two or three fit
    #: and *are* the useful fact — `up / down` says what a key does where "2 states" says
    #: nothing. Seventeen do not fit and would push the row off the edge.
    _NAME_STATES_UPTO = 3

    def _detail(self, cap: Capability) -> str:
        """What a row adds after its name: what it accepts, or an unusual range."""
        if cap.kind != "continuous":
            if 0 < len(cap.states) <= self._NAME_STATES_UPTO:
                return f"   {' / '.join(cap.states)}"
            return f"   {len(cap.states)} states"
        usual = abs(cap.lo - _SIGNED[0]) < 1e-6 and abs(cap.hi - _SIGNED[1]) < 1e-6
        return "" if usual else f"   [{cap.lo:+.1f}..{cap.hi:+.1f}]"

    def _describe(self, cap: Capability) -> str:
        """One row of the picker: the address, what it takes, and where it goes.

        The address **verbatim**, not a prettier short form of it. A shortened name is a
        second vocabulary for the same thing: you would read `thumb` here and have to know
        it means `vhi.prediction.thumb` in the file. One name, the real one, and the list
        reads the way the file does.

        No wire detail either. There is none left to show: a control's stream is named for
        its address, so the address on this row is the whole of the transport.

        The range appears only when it is *not* the signed `[-1, +1]` every control here
        declares (see `_SIGNED`), because a fact repeated on every row is one nobody reads.
        The full facts of whatever is selected are on the picker's own tooltip.
        """
        return f"{cap.address}{self._detail(cap)}"

    @staticmethod
    def _summary(cap: Capability) -> str:
        """What the target declared about the chosen control."""
        if cap.kind == "continuous":
            return f"number {cap.lo:+.1f}..{cap.hi:+.1f}, on its own stream"
        if 0 < len(cap.states) <= 3:
            # The names are the whole story at this size, so say them rather than counting
            # them: a reader who sees "2 states" still has to go and find out which two.
            return f"held state, one of: {' / '.join(cap.states)}"
        shown = ", ".join(cap.states[:3])
        return f"held state, one of {len(cap.states)}: {shown}, ..."

    def _gates_ui(self, entry: dict[str, Any]) -> None:
        """`threshold_fraction` and `debounce_s`, in plain words.

        **Only the gates that can apply are drawn.** They used to be drawn always, disabled,
        with the reason on hover — which spent two permanent rows per control on settings that
        do not apply to the continuous DOFs almost every map is made of. `_gate_rules` already
        knows; a reason now means "do not offer" rather than "offer, greyed".

        Two exceptions, both so the editor cannot hide state it is refusing to save:

        * a value already in the file is always shown, and shown **enabled**, so it can be
          cleared. Disabled-but-set was a dead end — `problems` blocked the save and the only
          way to fix it was the text view;
        * an address nothing has answered for keeps both, because "cannot apply" is not
          something to assert about a control no one has described yet.
        """
        no_threshold, no_debounce = self._gate_rules(entry)
        gated = entry["threshold_fraction"] is not None
        address = entry["targets"][0][0] if entry["targets"] else ""
        # `bool(address)`: with no target chosen there is nothing to gate at all, which is the
        # state a control is in the moment it is added.
        show_threshold = bool(address) and (not no_threshold or gated)
        show_debounce = bool(address) and (not no_debounce or bool(entry["debounce_s"]))
        if not (show_threshold or show_debounce):
            return
        imgui.indent()
        # A named band rather than a bare indent: the row above is *what* this control drives,
        # and these two are *when* it fires. Indentation alone left four unrelated-looking
        # rows in a stack with nothing saying which belonged to which.
        imgui.separator_text("Activation")
        # A sticky on/off, so the contract's toggle — `push_selected`'s accent tint and
        # underline — rather than a checkbox. It *was* an `imgui.checkbox`, the only labelled
        # one in the app, and at this theme's frame padding its empty rounded box read as a
        # text field waiting to be typed into. Short label, explanation on hover: a long
        # label is the one thing in ImGui that cannot wrap.
        if show_threshold:
            if gated:
                push_selected()
            # "classifier probability" named the input, not what the button does — and as a
            # bare noun beside a cutoff slider it read like a second label for that slider.
            if imgui.button("Treat as probability"):
                entry["threshold_fraction"] = None if gated else 0.5
            if gated:
                pop_selected()  # reads the button's rect, so it has to be the next call
            imgui.set_item_tooltip(
                "Turn this on when the model outputs a confidence in 0..1 rather than a\n"
                "position. It becomes a plain on/off at the cutoff below, and then travels\n"
                "the same weighted path a regressor's value does."
            )
        # Both gates share one label column, so their tracks share a left edge — two labels
        # of different lengths were starting their sliders at two different x. The reading
        # order is the app's own (`signals/_controls.py` draws "Window" then its slider), and
        # the unit goes on the value, in what the operator thinks in: a probability is a
        # percentage, not a two-decimal fraction.
        # Re-read rather than reuse `gated`: the button above may have flipped it *this frame*,
        # in either direction, and `gated` is the state from before the click.
        if entry["threshold_fraction"] is not None:
            label_column("On at or above", _GATE_LABELS, reserve=_label_w(_PERCENT_READOUT))
            changed, fraction = imgui.slider_float(
                "##threshold", float(entry["threshold_fraction"]), 0.0, 1.0, ""
            )
            if changed:
                entry["threshold_fraction"] = round(fraction, 2)
            imgui.same_line()
            imgui.text_colored(muted(), f"{entry['threshold_fraction']:.0%}")

        if show_debounce:
            # One group, so hovering the label explains the same thing as hovering the slider.
            imgui.begin_group()
            # "Hold for" was ambiguous exactly where it matters: half these addresses are
            # `keyboard.hold.*`, so it read as "hold the key down this long". It is the
            # opposite — how long the *input* must stop changing before it is believed.
            label_column("Steady for", _GATE_LABELS, reserve=_label_w(_SECONDS_READOUT))
            changed, debounce = imgui.slider_float(
                "##debounce", entry["debounce_s"], 0.0, 1.0, ""
            )
            if changed:
                entry["debounce_s"] = round(debounce, 2)
            imgui.same_line()
            imgui.text_colored(muted(), f"{entry['debounce_s']:.2f} s")
            imgui.end_group()
            explain = (
                "How long the predicted state must stay put before it counts. A classifier\n"
                "flickering between two states holds the last one until it settles, instead\n"
                "of chattering. 0 turns it off — every prediction acts immediately."
            )
            if no_debounce:
                # Only reachable via the second exception above: a value is in the file that
                # this control will not accept. Say so here, since this is the one place it
                # can be cleared.
                explain += f"\n\nThis control will not accept one: {no_debounce}."
            imgui.set_item_tooltip(explain)
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
        if silent := self.unanswered():
            # `resolve` validates every address against the manifest, so asking it about a
            # map naming a silent target's control gets a refusal that reads as "your file is
            # wrong" when the truth is "nothing has answered for it". Say which, and preview
            # nothing rather than something misleading.
            namespaces = sorted(silent)
            return (
                f"Nothing from {', '.join(namespaces)} has answered, so this cannot be "
                f"previewed yet. The file is still saveable — launch the target and press "
                f"Connect to check it."
            )
        try:
            controls = resolve(control_map, list(self._capabilities))
        except ValueError as exc:
            return str(exc).splitlines()[0]
        lines = []
        for alias, dof in controls.dofs.items():
            if hasattr(dof, "states"):
                lines.append(f"{alias}: held state, rest {dof.rest!r}")
            else:
                # The address in full. A last segment is a second, shorter vocabulary for
                # the same control — you would read `index` here and have to know it means
                # `vhi.prediction.index` in the file, and with two targets in one map the
                # short form is not even unique.
                routes = ", ".join(
                    f"{ref.address} x{ref.weight}" for ref in controls.routes[alias]
                )
                gate = (
                    f" (on at >= {dof.threshold_fraction})"
                    if dof.threshold_fraction is not None
                    else ""
                )
                lines.append(f"{alias}: number{gate} -> {routes}")
        return "\n".join(lines)

    @property
    def path(self) -> pathlib.Path | None:
        """The file being edited, or None while this map is untitled."""
        return self._path

    @property
    def capabilities(self) -> Sequence[Capability]:
        """What the target reported on the last `Connect`."""
        return self._capabilities


__all__ = ["ControlMapEditor"]
