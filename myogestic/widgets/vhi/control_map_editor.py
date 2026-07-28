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

_HEADER = (
    "Written by MyoGestic's control-map editor.\n"
    "This file is the source of truth — edit it here or by hand, whichever suits.\n"
    "  left  = your name for a model output, anything you like\n"
    "  right = a control the target declares (it owns the kind, range and states)"
)


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
    title
        Panel header text.

    Notes
    -----
    Validation runs on every edit, not on save: an alias that collides, a weight out of
    range, two aliases aimed at one control. **Save is disabled while anything is
    invalid**, so the file on disk is never a file that would not load — which matters
    because something else is reading it.

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
        "_capabilities", "_client", "_draft", "_error", "_filter", "_message",
        "_path", "_title", "_loaded",
    )

    def __init__(
        self,
        path: pathlib.Path,
        *,
        client: Any = None,
        title: str = "CONTROL MAP",
    ) -> None:
        self._path = path
        self._client = client
        self._title = title
        #: alias -> [(address, weight)], plus the gates. A plain structure rather than a
        #: ControlMap because a half-edited map is not a valid one, and `Binding` is
        #: frozen on purpose.
        self._draft: list[dict[str, Any]] = []
        self._capabilities: tuple[Capability, ...] = ()
        self._filter = ""
        self._message = ""
        self._error = ""
        self._loaded = False

    # --- file -------------------------------------------------------------------

    def load(self) -> None:
        """Read the file into the working copy, replacing anything unsaved."""
        self._draft = []
        self._error = ""
        if not self._path.exists():
            self._message = f"{self._path.name} does not exist yet — Save will create it."
            self._loaded = True
            return
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

    def save(self) -> bool:
        """Write the working copy back as TOML. False if it would not load."""
        control_map = self.as_control_map()
        if control_map is None:
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(dump_control_map(control_map, header=_HEADER))
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

        if imgui.button("Connect"):
            self._connect()
        imgui.same_line()
        can_save = not self.problems()
        imgui.begin_disabled(not can_save)
        if imgui.button("Save"):
            saved = self.save()
        imgui.end_disabled()
        imgui.same_line()
        if imgui.button("Reload"):
            self.load()
        imgui.same_line()
        if imgui.button("Add control"):
            self.add_control()

        imgui.text_colored(muted(), str(self._path))
        if self._capabilities:
            imgui.text_colored(
                SUCCESS, f"{len(self._capabilities)} controls available from the target"
            )
        else:
            imgui.text_colored(
                WARNING,
                "Not connected — press Connect to list what the target exports. "
                "Until then a control has to be typed and cannot be checked.",
            )
        if self._error:
            imgui.text_colored(DANGER, self._error)
        elif self._message:
            imgui.text_colored(muted(), self._message)

        imgui.separator()
        for index, entry in enumerate(list(self._draft)):
            self._entry_ui(index, entry)

        problems = self.problems()
        if problems:
            imgui.separator()
            imgui.text_colored(DANGER, "Cannot save yet:")
            for problem in problems:
                imgui.bullet_text(problem)
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
        changed, alias = imgui.input_text("name", entry["alias"])
        if changed:
            entry["alias"] = alias
        imgui.same_line()
        if imgui.button("Remove"):
            self._draft.remove(entry)
            imgui.pop_id()
            return
        imgui.same_line()
        if imgui.button("Add target"):
            entry["targets"].append(["", 1.0])

        for slot, pair in enumerate(list(entry["targets"])):
            imgui.push_id(f"t{slot}")
            imgui.indent()
            self._picker(pair)
            imgui.same_line()
            # -1..1 rather than 0..1: a signed target can take a negative weight, and a
            # slider that cannot reach one would make a valid file unsavable.
            changed, weight = imgui.slider_float("weight", pair[1], -1.0, 1.0)
            if changed:
                pair[1] = round(weight, 2)
            imgui.same_line()
            if imgui.button("x") and len(entry["targets"]) > 1:
                entry["targets"].remove(pair)
            elif slot > 0 and imgui.is_item_hovered():
                imgui.set_tooltip("Remove this target")
            imgui.unindent()
            imgui.pop_id()

        self._gates_ui(entry)
        imgui.separator()
        imgui.pop_id()

    def _picker(self, pair: list[Any]) -> None:
        """Choose a control from what the target exports, or type one when offline."""
        address = pair[0]
        if not self._capabilities:
            changed, typed = imgui.input_text("control", address)
            if changed:
                pair[0] = typed
            return
        label = address or "choose a control..."
        if imgui.begin_combo("control", label):
            changed, self._filter = imgui.input_text("search", self._filter)
            for cap in self._capabilities:
                if self._filter and self._filter.lower() not in cap.address.lower():
                    continue
                selected, _ = imgui.selectable(self._describe(cap), cap.address == address)
                if selected:
                    pair[0] = cap.address
            imgui.end_combo()
        cap = next((c for c in self._capabilities if c.address == address), None)
        if cap is not None:
            imgui.same_line()
            imgui.text_colored(muted(), self._summary(cap))

    @staticmethod
    def _describe(cap: Capability) -> str:
        """A capability as a line someone can choose from without knowing gRPC."""
        # The last two segments read like a name ("index.flexion"); the full address is
        # still there for anyone who wants it.
        short = ".".join(cap.address.split(".")[-2:])
        if cap.kind == "continuous":
            return f"{short}   [{cap.lo:+.0f}..{cap.hi:+.0f}]   {cap.address}"
        return f"{short}   {len(cap.states)} states   {cap.address}"

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
        changed, gated = imgui.checkbox("this output is a classifier probability", gated)
        if changed:
            entry["threshold_fraction"] = 0.5 if gated else None
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Tick this when the model outputs a confidence in 0..1 rather than a\n"
                "position. It is turned into a plain on/off at the cutoff below, and\n"
                "then travels the same weighted path a regressor's value does."
            )
        if entry["threshold_fraction"] is not None:
            changed, fraction = imgui.slider_float(
                "on at or above", float(entry["threshold_fraction"]), 0.0, 1.0
            )
            if changed:
                entry["threshold_fraction"] = round(fraction, 2)

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
