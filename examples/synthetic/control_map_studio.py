"""Control-map studio — edit the TOML, and drive whatever it names.

The shortest path from a TOML control map to a hand that moves. No model, no EMG, no
training: one slider per name in the file, sent straight through a `RemoteTarget` to VHI's
**predicted** hand.

Run with:
    uv run --extra grpc --extra keyboard python examples/synthetic/control_map_studio.py

Workflow:
    1. Launch "VHI Hand" → VHI appears
    2. Click "Connect" → the file resolves against what VHI says it exports
    3. Drag a slider → that hand moves

It opens on a blank, untitled map; `+` adds another, `Open...` loads one from disk, and each
is a tab you can close. The **active tab is the one that is running** — switching tabs rebinds
the bus to that map and disarms the keyboard. The file is watched, so editing it in any editor
moves the panel and the sliders with no button; `Save as...` keeps working wherever it lands.

The map can also name **keys**, which is why this is a studio rather than a VHI demo::

    [dofs]
    close = "vhi.prediction.index"          # a finger
    walk  = "keyboard.hold.letter.w"        # held while the control is above 0.5
    fire  = "keyboard.tap.edit.space"       # one press per crossing

Both targets share the one file and the one bus. Key sending starts **disarmed** — see the
KEYBOARD panel — because a resolved map types into whatever window has focus.

Needs a VHI 2.x build. A pre-2.0 VHI has no manifest to resolve against and is refused with
the upgrade command rather than driven on a guess.
"""

import os
import pathlib
import sys
import tomllib

from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd

from myogestic import App, Context, Fr, Grid, Layout, Px
from myogestic._theme import mono_font
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.keyboard import KeyboardTarget
from myogestic.remote import RemoteTarget
from myogestic.vhi import virtual_hand
from myogestic.widgets import AppHeader, ControlMapEditor, ProcessLauncher
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary_button,
    push_selected,
    tinted_row,
    ui_px,
)

#: Where the editor *starts*. After `Save as...`, `editor.path` is the answer, not this.
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "playground.toml"

vhi = virtual_hand()
vhi_control = vhi.control_client()

# A key is a two-state discrete control, so nothing in the map format or the bus knows the
# difference between pressing `w` and bending a finger. Starts DISARMED and sends nothing
# until the Send keys chip is selected: a resolved map types into whatever window has focus, so
# a twitchy signal on `keyboard.tap.edit.enter` would act on your terminal.
keys = KeyboardTarget()

app = App("Control-map studio")

# Everything below is rebuilt whenever the file changes: one entry per alias *in the file*.
levels: dict[str, float] = {}
#: alias -> the states a held control accepts, from the target's manifest. A discrete control
#: takes one of *its* names over gRPC, not a slider value on the pose stream.
states: dict[str, tuple[str, ...]] = {}
#: The state each held control is currently showing.
chosen: dict[str, str] = {}
#: Aliases being typed into rather than dragged, holding the field's text as a float. Keyed by
#: alias so more than one can be open at once.
typing: dict[str, float] = {}
#: Aliases whose field opened this frame and still needs the caret. ImGui takes focus for the
#: *next* item declared, so it must be requested before the widget, not after.
focus_pending: set[str] = set()
bus: ControlBus | None = None
status = "Press Connect. The keyboard needs nothing running; the hand needs VHI."
failure = ""
#: alias -> why it is not being driven. These get a line of text, never a slider.
waiting: dict[str, str] = {}


# The picker offers every address both targets export — model hand, operator hand, keyboard —
# because which of them this app drives is the map's answer, not this file's.
def _new_document(path=None) -> ControlMapEditor:
    """One open map, offering everything both targets export."""
    return ControlMapEditor(path, clients=[vhi_control, keys], title="EDIT THE MAP")


#: Every open map, in tab order. The widget stays single-document; the app owns the collection.
documents: list[ControlMapEditor] = [_new_document()]
#: Index into `documents`. The active tab is the one that drives the targets.
active = 0
#: A pending `Open...` dialog, polled the way the editor polls its own Save-as.
open_dialog = None
#: Documents a close was requested for while they had unsaved edits.
confirm_close: set[int] = set()
#: Files opened this session, most recent first — survives closing a tab.
recent: list[pathlib.Path] = []
#: The last reason arming failed. This app draws no log panel, so `app.ctx.log` goes nowhere.
keyboard_error = ""
#: id(document) -> how many controls its targets offered when the bus was last built.
caps_seen: dict[int, int] = {}


def editor() -> ControlMapEditor:
    """The document in front of the user, and therefore the one being driven."""
    return documents[active]


# `launchable` not `launcher`: an unlaunchable target must not stop this app from opening.
processes = ProcessLauncher(vhi.launchable())
header = AppHeader("Control map studio", show_state=False)

# Two arrangements, picked per frame from the window's width: a Grid's column count and
# proportions are fixed at construction, and a 50/50 split is wrong at both ends — at 700 px
# each half is too narrow for the editor's rows, at 2000 px the sliders get a thousand pixels
# they have no use for. `Px` for the control column so every pixel gained goes to the editor.
# Both numbers are pixels at UI scale 1.0, so the switch happens at the same size relative
# to the text on every screen.
STACK_BELOW = 900.0
CONTROLS_W = 420.0

layout = Layout(
    wide=Grid.areas(
        """
        header     header
        processes  editor
        drive      editor
        keyboard   editor
        """,
        row_height=[Px(52), Px(140), Fr(1), Fr(0.7)],
        col_width=[Px(CONTROLS_W), Fr(1)],
        bare=("header",),
    ),
    # `Fr(2)` for the editor: the slider panel above it is empty
    # until Connect, and an even split left the editor cut off mid-row.
    narrow=Grid.areas(
        """
        header
        processes
        drive
        keyboard
        editor
        """,
        row_height=[Px(52), Px(140), Fr(1), Fr(0.7), Fr(2)],
        bare=("header",),
    ),
    breakpoint=Px(STACK_BELOW),
)


#: Namespace -> client, in merge order. One list rather than a literal per function, because
#: the editor's picker and these sliders must not disagree about who owns a first segment.
TARGETS = (("vhi", vhi_control), ("keyboard", keys))


def _manifests() -> tuple[list, list[str]]:
    """Ask every target now: its manifest merged, plus the namespaces that did not answer.

    Same merge `ControlMapEditor` does for its picker: the address rule namespaces controls by
    first segment, so two targets cannot mean different things by one name.

    Blocking, so this is for a press. `_editor_manifest` is the answer for a rebuild that
    nobody clicked.
    """
    merged: dict[str, object] = {}
    absent: list[str] = []
    for namespace, client in TARGETS:
        answered = client.capabilities()
        if not answered:
            absent.append(namespace)
            continue
        for cap in answered:
            merged.setdefault(cap.address, cap)
    return list(merged.values()), absent


def _editor_manifest() -> tuple[list, list[str]]:
    """The same thing, out of what the editor's worker last heard. No RPC.

    A rebuild triggered *by that answer changing* must not ask again: it would be a second
    blocking round trip on the render thread for a fact already in hand, and it can see a
    different state than the one that triggered it.
    """
    capabilities = list(editor().capabilities)
    present = {cap.address.split(".", 1)[0] for cap in capabilities}
    return capabilities, [namespace for namespace, _ in TARGETS if namespace not in present]


def _split(control_map, capabilities, absent):
    """The part of the map that can be driven now, and why the rest cannot.

    An alias is bindable when *every* address it routes to is in the merged manifest — a
    fan-out half of which is missing would move some fingers and not others.
    """
    from myogestic.controls import ControlMap

    known = {cap.address for cap in capabilities}
    ok, why = {}, {}
    for alias, binding in control_map.bindings.items():
        missing = [ref.address for ref in binding.targets if ref.address not in known]
        if not missing:
            ok[alias] = binding
            continue
        namespaces = sorted({address.split(".")[0] for address in missing})
        silent = [n for n in namespaces if n in absent]
        why[alias] = (
            f"{', '.join(missing)} — {', '.join(silent)} has not answered"
            if silent
            else f"{', '.join(missing)} — no target exports this"
        )
    return ControlMap(bindings=ok), why


def _connect(known: tuple[list, list[str]] | None = None) -> None:
    """(Re)read the file and resolve it against whatever the targets export.

    Rebuilt from scratch each time: a stale slider for an alias that no longer exists would
    send a value nothing reads.

    Parameters
    ----------
    known
        A manifest already in hand, as `_manifests` returns it. Passed by
        `_rebuild_if_the_manifest_changed`, which runs without a click and must not spend a
        blocking round trip per target on the render thread. Omitted by every caller that
        *is* a click, where asking again is the point of pressing the button.
    """
    global bus, levels, states, status, failure, waiting, keyboard_error
    failure = ""
    # The arm is carried across the rebuild: this also runs without a click, and a switch that
    # flicks itself off mid-use is worse than one that stays on. `_switch_to` and
    # `_close_document` disarm *before* calling this and so read back False here.
    was_armed = keys.armed
    # Cleared here rather than only where it is rebuilt: the early returns below skip that
    # assignment, and `_waiting_ui` would go on listing the *previous* map's controls.
    waiting = {}
    # A reload can rename any alias, so a field left open would type into a control that is gone.
    typing.clear()
    focus_pending.clear()
    if bus is not None:
        bus.stop()
        bus = None
    # `editor.path`, not CONTROL_FILE: `Save as...` moves the editor to a new file.
    path = editor().path
    if path is None:
        # The file is the source of truth; the editor's save triggers this again.
        status = "Untitled — save it, and it will start driving."
        return
    try:
        with path.open("rb") as handle:  # "rb" — tomllib requires binary
            control_map = load_control_map(tomllib.load(handle))
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        # A recent path may have moved, or the file be caught half-saved by another program.
        # Reported, not raised: an exception in a click handler takes the window down.
        failure = str(exc)
        status = f"{path.name} could not be read."
        return
    try:
        # Every target, not just VHI: `KeyboardTarget.capabilities()` answers from local data,
        # so a keyboard-only map resolves with nothing launched. Inside the `try` because a
        # target too old for this client's vocabulary raises rather than going quiet.
        capabilities, absent = _manifests() if known is None else known
        bindable, waiting = _split(control_map, capabilities, absent)
        if not bindable.bindings:
            status = "Nothing in this file can be driven yet."
            return
        controls = resolve(bindable, capabilities)
        # One target for the whole map: it publishes a stream per address it drives, each named
        # for that address, so this file states neither a hand nor a width.
        vhi_target = RemoteTarget(client=vhi_control, interface=vhi)
        # `ControlBus` checks that *someone* claims every alias, so a keyboard address in a
        # VHI-only app is caught here rather than looking like a control that holds still.
        new_bus = ControlBus(controls, targets=[vhi_target, keys], hz=32)
        # The bus binds on construction, but VHI may have come up since — settle it explicitly.
        vhi_target.negotiate()
    except ValueError as exc:
        # A refusal names the address it could not place, or the two aliases aiming at one
        # control. Show it instead of leaving a dead slider.
        failure = str(exc)
        status = "That map cannot be driven by this VHI."
        return
    bus = new_bus
    if was_armed and not keys.armed:
        # Only on the path that rebuilt: the early returns leave no bus and no claims to be
        # armed *for*. `arm` refuses out loud, so this cannot silently come back half-on.
        try:
            keys.arm()
        except RuntimeError as exc:
            keyboard_error = str(exc)
    levels = {alias: 0.0 for alias, dof in controls.dofs.items() if not hasattr(dof, "states")}
    states = {
        alias: tuple(dof.states) for alias, dof in controls.dofs.items() if hasattr(dof, "states")
    }
    app.ctx.control_space = control_map
    held = f" and {len(states)} held state(s)" if states else ""
    held += f", {len(waiting)} waiting" if waiting else ""
    status = f"Driving {len(levels)} control(s){held} from {path.name}."


def _rebuild_if_the_manifest_changed() -> None:
    """Rebuild when the active map's targets start — or stop — offering something.

    The editor re-asks its targets on a timer, so a target launched from the PROCESS panel
    turns up in *its* picker with no click, while these sliders stayed on the manifest as it
    stood at the last `Connect`. Watching the count the editor already publishes also covers a
    target going away, and connects on the very first frame since `caps_seen` starts empty.
    """
    offered = len(editor().capabilities)
    if caps_seen.get(id(editor())) != offered:
        caps_seen[id(editor())] = offered
        _connect(_editor_manifest())


@app.ui
def studio_ui(ctx: Context) -> None:
    """Sliders and the editor: side by side when there is room, stacked when not."""
    with layout["header"]:
        header.ui(ctx)

    with layout["processes"]:
        processes.ui()

    with layout["drive"]:
        _drive_ui()

    with layout["keyboard"]:
        _keyboard_ui()

    with layout["editor"]:
        _tabs_ui()
        # The editor writes the file the sliders were built from, so a save rebuilds them.
        if editor().ui():
            _connect()
        _rebuild_if_the_manifest_changed()


def _drive_ui() -> None:
    """The active map's state, connection action and captioned controls."""
    tone = DANGER if failure else SUCCESS if bus is not None else IDLE
    panel_header("DRIVE THE MAP", status=tone)
    with tinted_row(tone):
        imgui.align_text_to_frame_padding()
        imgui.text_unformatted(
            "Connection failed" if failure else "Driving" if bus else "Not connected"
        )
    _caption(editor().label)
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(failure or status)
    if bus is None:
        imgui.text_wrapped("Save a map, then Connect. Launch VHI first for hand controls.")
    imgui.pop_style_color()
    if primary_button("Connect / Reload", size=(imgui.get_content_region_avail().x, 0)):
        _connect()
    if bus is not None:
        _sliders_ui()
    _waiting_ui()


def _caption(label: str, value: float | None = None) -> None:
    """Keep the alias above its field, with a mono value and the full name on hover."""
    style = imgui.get_style()
    room = imgui.get_content_region_avail().x
    right = imgui.get_cursor_pos_x() + room
    text = f"{value:.3f}" if value is not None else ""
    font = mono_font()
    if font is not None:
        imgui.push_font(font, style.font_size_base)
    value_w = imgui.calc_text_size(text).x
    if font is not None:
        imgui.pop_font()
    available = room - value_w - style.item_spacing.x if text else room
    shown = label
    while shown and imgui.calc_text_size(shown + ("…" if shown != label else "")).x > available:
        shown = shown[:-1]
    imgui.text_colored(muted(), shown + ("…" if shown != label else ""))
    imgui.set_item_tooltip(label)
    if text:
        imgui.same_line()
        imgui.set_cursor_pos_x(right - value_w)
        mono_text(text)


def _sliders_ui() -> None:
    """One slider per control in the file, sized to the column it is in.

    Captions sit above the sliders; two columns become one when tracks would be too narrow.

    **Double-click a slider to type a value instead.** ImGui already offers Ctrl+Click for
    this; double-click is the gesture people reach for first, wired to the same thing.
    """
    assert bus is not None
    changed = False
    columns = 2 if imgui.get_content_region_avail().x >= ui_px(480) else 1
    if imgui.begin_table("map-controls", columns, imgui.TableFlags_.sizing_stretch_same):
        for alias in levels:
            imgui.table_next_column()
            _caption(alias, levels[alias])
            label = f"##{alias}"
            width = imgui.get_content_region_avail().x
            imgui.set_next_item_width(width)
            if alias in typing:
                changed = _typed_value_ui(alias, width, None) or changed
                continue
            before = levels[alias]
            edited, levels[alias] = imgui.slider_float(label, levels[alias], -1.0, 1.0)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Drag, or double-click (or Ctrl+Click) to type a value")
            if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                # A click on the track jumps the value to where it landed, so by the second click
                # the number has already moved. Put it back — a double-click means "type".
                levels[alias] = before
                typing[alias] = before
                focus_pending.add(alias)
                edited = False
            changed = changed or edited
        imgui.end_table()
    if imgui.button("Rest"):
        levels.update(dict.fromkeys(levels, 0.0))
        changed = True
    if changed:
        bus.push(levels)
    _held_states_ui()


def _keyboard_ui() -> None:
    """A keyboard card, with an arm switch when the map actually names a key.

    The selected chip stays armed until switched off; `KeyboardTarget.stop` lets go of
    everything on exit.
    """
    global keyboard_error
    # Asked before the click, not after: without it the switch flicks on, `arm` refuses, it
    # flicks back, and the reason goes to `app.ctx.log`, which this app never draws.
    refusal = keys.arm_refusal if keys.claims else ""
    armed = keys.armed
    problem = (refusal or keyboard_error) if keys.claims else ""
    tone = DANGER if problem else WARNING if armed else IDLE
    state = "Cannot send keys" if problem else "Armed" if armed else "Disarmed"
    panel_header("KEYBOARD", status=tone)
    with tinted_row(tone):
        imgui.align_text_to_frame_padding()
        imgui.text_unformatted(state if keys.claims else "No keys mapped")
    if not keys.claims:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("No keys mapped. Add a keyboard control to the map, then Connect.")
        imgui.pop_style_color()
        return
    imgui.begin_disabled(bool(refusal) and not armed)
    if armed:
        push_selected()
    changed = imgui.button("Send keys")
    if armed:
        pop_selected()
    imgui.end_disabled()
    if changed:
        try:
            keys.disarm() if armed else keys.arm()
            keyboard_error = ""
        except RuntimeError as exc:
            keyboard_error = str(exc)
    if refusal or keyboard_error:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(refusal or keyboard_error)
        imgui.pop_style_color()
        if primary_button("Grant access...", size=(imgui.get_content_region_avail().x, 0)):
            # It cannot grant anything — only the user can, in System Settings. What it does is
            # register this binary in the Accessibility list and open the pane.
            keyboard_error = keys.request_accessibility() or keyboard_error
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Asks macOS and opens the Accessibility list with this program in it.\n"
                "You still have to switch it on, then restart MyoGestic."
            )
        if imgui.button("Copy the path"):
            # For a dismissed prompt or a hand-edited list: the path must be exact and is long.
            imgui.set_clipboard_text(os.path.realpath(sys.executable))
        return
    mono_text(str(len(keys.claims)))
    imgui.same_line()
    imgui.text_colored(muted(), "mapped keys")
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(
        "Keys are typing into whatever window has focus."
        if keys.armed
        else "Select Send keys to enable keyboard output."
    )
    imgui.pop_style_color()


def _typed_value_ui(alias: str, width: float, label: str | None) -> bool:
    """The double-clicked slider, as a field. True when a value was committed.

    Enter commits, and so does clicking away having typed something; Escape abandons, because
    ImGui restores the value it opened with. The slider comes back either way.
    """
    if alias in focus_pending:
        imgui.set_keyboard_focus_here()
        focus_pending.discard(alias)
    # ImGui has no style var for centring text inside an input, so the *field* is centred
    # instead: sized to its number, in the middle of the span the slider filled.
    start_x = imgui.get_cursor_pos_x()
    style = imgui.get_style()
    field_w = min(
        width,
        imgui.calc_text_size(f"{typing[alias]:.3f}").x + style.frame_padding.x * 2.0 + ui_px(8),
    )
    imgui.set_cursor_pos_x(start_x + (width - field_w) * 0.5)
    imgui.set_next_item_width(field_w)
    # A **different ImGui id** from the slider it replaces. The mouse is still down from the
    # second click, and handed the slider's id ImGui sees the active widget change type
    # underneath itself and drops the field on the frame it appeared.
    field_id = f"##{alias}_typed"
    # No `enter_returns_true`: `input_float` is `InputScalar` underneath and ImGui asserts that
    # flag is *not* set on it — passing it raised out of the render callback and took the window
    # down. `is_item_deactivated_after_edit` is the supported "did this commit".
    _, value = imgui.input_float(field_id, typing[alias], 0.0, 0.0, "%.3f")
    # Read **before** the label is submitted: `is_item_*` answers about the last item, and a
    # label never deactivates, so the field would commit nothing and never close.
    committed = imgui.is_item_deactivated_after_edit()
    dismissed = imgui.is_item_deactivated()
    typing[alias] = value
    if label is not None:
        # Where `slider_float` would have drawn it: past the full span, not past the field.
        imgui.same_line(start_x + width + style.item_inner_spacing.x)
        imgui.text_unformatted(label)
    if committed:
        # The bus clips anyway; this is about not *displaying* a value the hand cannot reach.
        levels[alias] = min(1.0, max(-1.0, value))
        typing.pop(alias, None)
        return True
    if dismissed:
        typing.pop(alias, None)
    return False


def _switch_to(index: int) -> None:
    """Make a document the active one, and therefore the running one.

    Disarms the keyboard on the way: a map you have navigated away from must not keep sending
    keystrokes, and re-arming is one click.
    """
    global active
    if index == active:
        return
    active = index
    keys.disarm()
    _connect()


def _open_document(path: pathlib.Path) -> None:
    """Open a file in a new tab, or focus it if it is already open."""
    resolved = path.resolve()
    if resolved in recent:
        recent.remove(resolved)
    recent.insert(0, resolved)
    del recent[8:]
    for index, document in enumerate(documents):
        if document.path is not None and document.path.resolve() == resolved:
            _switch_to(index)
            return
    documents.append(_new_document(path))
    _switch_to(len(documents) - 1)


def _close_document(index: int) -> None:
    """Drop a document. The last one is replaced rather than removed.

    An app with no document has nothing to look at and no way back, so closing the last tab
    hands back a blank one instead.
    """
    global active
    # Before the document goes: `caps_seen` is keyed by `id`, and CPython reuses the id of a
    # collected object — a new document on a dead one's id would skip its rebuild.
    caps_seen.pop(id(documents[index]), None)
    documents.pop(index)
    if not documents:
        documents.append(_new_document())
    active = min(active if index > active else max(0, active - 1), len(documents) - 1)
    keys.disarm()
    _connect()


def _tab_label(index: int, among: list[ControlMapEditor] | None = None) -> str:
    """What a tab says. Untitled maps are numbered in tab order.

    `among` is the list to number within, and passing the frame's own snapshot is not optional
    during a render: indexing the live `documents` while the caller iterates a copy raised
    `IndexError` past `end_tab_bar()`, which ImGui answers with a process-killing assert.
    """
    within = documents if among is None else among
    document = within[index]
    if document.path is not None:
        return document.label
    nth = 1 + sum(1 for earlier in within[:index] if earlier.path is None)
    return "Untitled" if nth == 1 else f"Untitled {nth}"


def _tabs_ui() -> None:
    """One tab per open map, a `+` for a new one, and a way to open a file.

    The first tab bar in this repo; `segmented` is the house control for one-of-N, but has no
    per-item close button and no scrolling row.
    """
    global open_dialog
    _poll_open_dialog()
    flags = (
        imgui.TabBarFlags_.auto_select_new_tabs
        | imgui.TabBarFlags_.fitting_policy_scroll
        | imgui.TabBarFlags_.tab_list_popup_button
    )
    if not imgui.begin_tab_bar("maps", flags):
        return
    # Nothing structural happens inside the bar: adding or removing a document mid-loop changes
    # the list being walked, and an exception in there skips `end_tab_bar` — which ImGui answers
    # with a process-killing assert rather than a traceback.
    snapshot = list(documents)
    close_at: int | None = None
    switch_to: int | None = None
    add_blank = False
    for index, document in enumerate(snapshot):
        dirty = "*" if document._dirty() else ""
        # `##doc{index}`: two untitled maps share a visible label, and one ImGui id is one tab.
        selected, keep = imgui.begin_tab_item(
            f"{_tab_label(index, snapshot)}{dirty}##doc{index}", True
        )
        if selected:
            if index != active:
                switch_to = index
            imgui.end_tab_item()
        if keep is False:
            close_at = index
    if imgui.tab_item_button("+", imgui.TabItemFlags_.trailing):
        add_blank = True
    if imgui.is_item_hovered():
        imgui.set_tooltip("A new, empty map")
    # A caret rather than an "Open..." tab: a button shaped like a tab reads as a document.
    show_menu = imgui.tab_item_button("v", imgui.TabItemFlags_.trailing)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Open a file, an example, or something recent")
    imgui.end_tab_bar()
    if show_menu:
        # After `end_tab_bar`: a popup begun inside the bar nests into it.
        imgui.open_popup("documents")
    _documents_menu()

    # Apply now the bar is closed. Close last: it renumbers, so a switch or an add settles first.
    if switch_to is not None:
        _switch_to(switch_to)
    if add_blank:
        documents.append(_new_document())
        _switch_to(len(documents) - 1)
    if close_at is not None and close_at < len(documents):
        if documents[close_at]._dirty():
            confirm_close.add(close_at)
            imgui.open_popup("close without saving?")
        else:
            _close_document(close_at)
    _confirm_close_ui()


def _documents_menu() -> None:
    """Everything that opens a map: a file, one of the shipped examples, or a recent one.

    The studio starts on a blank map, so `examples/controls/` is only reachable from here.
    """
    global open_dialog
    if not imgui.begin_popup("documents"):
        return
    if imgui.menu_item_simple("New empty map"):
        documents.append(_new_document())
        _switch_to(len(documents) - 1)
    if imgui.menu_item_simple("Open a file..."):
        open_dialog = pfd.open_file(
            "Open a control map", str(CONTROL_FILE.parent), ["TOML", "*.toml"]
        )
    examples = sorted(CONTROL_FILE.parent.glob("*.toml"))
    if imgui.begin_menu("Open an example", bool(examples)):
        for example in examples:
            if imgui.menu_item_simple(example.name):
                _open_document(example)
        imgui.end_menu()
    # This session only: persisting it would need a config store this app does not have.
    if imgui.begin_menu("Open recent", bool(recent)):
        for path in recent:
            if imgui.menu_item_simple(path.name):
                _open_document(path)
        imgui.end_menu()
    imgui.end_popup()


def _poll_open_dialog() -> None:
    """Collect an `Open...` result once the dialog has one. Same shape as the editor's
    Save-as, and for the same reason: `pfd` hands back a handle, not an answer."""
    global open_dialog
    if open_dialog is None or not open_dialog.ready():
        return
    result = open_dialog.result()
    open_dialog = None
    if result:
        _open_document(pathlib.Path(result[0] if isinstance(result, list) else result))


def _confirm_close_ui() -> None:
    """Ask before dropping unsaved edits. A modal, because it is destructive and there is
    exactly one right moment to answer it."""
    if not confirm_close:
        return
    index = next(iter(confirm_close))
    opened, _ = imgui.begin_popup_modal("close without saving?", None)
    if not opened:
        return
    document = documents[index] if index < len(documents) else None
    imgui.text_wrapped(
        f"{_tab_label(index) if document else 'That map'} has unsaved edits. Closing it loses them."
    )
    imgui.spacing()
    if imgui.button("Discard and close"):
        confirm_close.discard(index)
        if document is not None:
            _close_document(index)
        imgui.close_current_popup()
    imgui.same_line()
    if imgui.button("Keep it open"):
        confirm_close.discard(index)
        imgui.close_current_popup()
    imgui.end_popup()


def _waiting_ui() -> None:
    """Controls in the file that nothing can drive yet, and what is missing.

    Deliberately *not* sliders: one for a control whose target has not answered would move and
    do nothing, so it gets a sentence naming what is absent instead.
    """
    if not waiting:
        return
    with tinted_row(WARNING):
        imgui.align_text_to_frame_padding()
        imgui.text_unformatted("Waiting for targets")
    imgui.push_style_color(imgui.Col_.text, muted())
    for alias, why in waiting.items():
        imgui.text_wrapped(f"{alias}: {why}")
    imgui.pop_style_color()


def _held_states_ui() -> None:
    """A picker per held control: choose one of the states the target declared.

    `bus.select` rather than `bus.push`: a held state is delivered on change and rebases its own
    stability gate, so the next frame's push does not re-fire what was just chosen.
    """
    assert bus is not None
    if not states:
        return
    columns = 2 if imgui.get_content_region_avail().x >= ui_px(480) else 1
    if imgui.begin_table("held-controls", columns, imgui.TableFlags_.sizing_stretch_same):
        for alias, options in states.items():
            imgui.table_next_column()
            _caption(alias)
            imgui.set_next_item_width(imgui.get_content_region_avail().x)
            if imgui.begin_combo(f"##{alias}", chosen.get(alias, options[0])):
                for state in options:
                    selected, _ = imgui.selectable(state, chosen.get(alias) == state)
                    if selected:
                        chosen[alias] = state
                        bus.select(alias, state)
                imgui.end_combo()
        imgui.end_table()


def main() -> None:
    """Run until the window closes, then rest the hand."""
    try:
        app.run()
    finally:
        # Rest the hand and let that frame land before the outlet's thread dies.
        if bus is not None:
            bus.stop()  # reaches both targets: rests the hand, lifts every key
        keys.stop()  # and again, in case the bus was never built
        vhi_control.stop()


if __name__ == "__main__":
    main()
