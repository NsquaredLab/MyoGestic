"""Control-map studio — edit the TOML, and drive whatever it names.

The shortest path from a TOML control map to a hand that moves. No model, no EMG, no
training: one slider per name in the file, sent straight through a `VhiTarget` to VHI's
**predicted** hand.

Run with:
    uv run --extra grpc --extra keyboard python examples/synthetic/control_map_studio.py

Workflow:
    1. Launch "VHI Hand" → the renderer appears
    2. Click "Connect" → the file resolves against what VHI says it exports
    3. Drag a slider → that hand moves

It opens on a **blank, untitled map**. `+` adds another, `Open...` loads one from disk, and
each is a tab you can close. The **active tab is the one that is running** — switching tabs
rebinds the bus to that map and disarms the keyboard, since a map you have navigated away
from must not keep sending keystrokes.

Then try changing something. `examples/controls/playground.toml` (via `Open...`) maps a name
of yours onto a control VHI declares; `close` fans out to all five digits.
Edit the weight **in any editor and save** — the file is watched, so the panel and the
sliders follow with no button. Or edit it in the panel and press **Save**. The file is the
source of truth either way.

**Save as...** writes the map somewhere else and keeps working there, so the sliders follow
it too. That file need not be in this repo — which is the point, but it also means the map
driving the hand may not be version-controlled.

The map can also name **keys**, which is why this is a studio rather than a VHI demo::

    [dofs]
    close = "vhi.prediction.index"          # a finger
    walk  = "keyboard.hold.letter.w"        # held while the control is above 0.5
    fire  = "keyboard.tap.edit.space"       # one press per crossing

Both targets share the one file and the one bus. Key sending starts **disarmed** — see the
KEYBOARD panel — because a resolved map types into whatever window has focus.

Needs a VHI 2.x build. A pre-2.0 renderer has no manifest to resolve against and is
refused with the upgrade command rather than driven on a guess.
"""

import os
import pathlib
import sys
import tomllib

from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd

from myogestic import App, Fr, Grid, Px
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.keyboard import KeyboardTarget
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.widgets import AppLogo, ControlMapEditor, ProcessLauncher
from myogestic.widgets.common import DANGER, SUCCESS, WARNING, muted, panel_header

#: Where the editor *starts*. It can be sent elsewhere with `Save as...`, after which
#: `editor.path` is the answer and this is only history.
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "playground.toml"

vhi = virtual_hand()
vhi_control = vhi.control_client()

# The second target, and the reason this is no longer "the VHI playground". A key is a
# two-state discrete control, so nothing in the map format or the bus knows the difference
# between pressing `w` and bending a finger.
#
# It starts DISARMED and sends nothing until the checkbox below is ticked. That is not
# ceremony: a resolved map types into whatever window has focus, so a twitchy signal on
# `keyboard.tap.edit.enter` would act on your terminal.
keys = KeyboardTarget()

app = App("Control-map studio")

# Everything below is rebuilt whenever the file changes, so none of it can be module
# state: `levels` has one entry per alias *in the file*, and the bus is resolved against
# the manifest, which needs VHI up.
levels: dict[str, float] = {}
#: alias -> the states a held control accepts, straight from the target's manifest. A
#: discrete control cannot be driven by a slider: it takes one of *its* names, and it goes
#: over gRPC rather than the pose stream. Without this, mapping `vhi.control.gesture` here
#: produced a control the app could not command at all — mapped, resolved, and inert.
states: dict[str, tuple[str, ...]] = {}
#: The state each held control is currently showing, so the picker has something to say.
chosen: dict[str, str] = {}
#: Aliases being typed into rather than dragged, holding the field's current text as a
#: float. Keyed by alias so more than one can be open, and cleared on commit or abandon.
typing: dict[str, float] = {}
#: Aliases whose field was opened this frame and still needs the caret put in it. ImGui
#: takes focus for the *next* item declared, so it has to be requested before the widget
#: rather than after, which means remembering that it is owed.
focus_pending: set[str] = set()
bus: ControlBus | None = None
status = "Press Connect. The keyboard needs nothing running; the hand needs VHI."
failure = ""
#: alias -> why it is not being driven. A control whose target has not answered is *not*
#: given a slider: a slider that sends nowhere is the failure this whole standard exists to
#: prevent, so it gets a line of text saying what is missing instead.
waiting: dict[str, str] = {}

# `stream="output"` is the default, and stating it is the point: this app drives the
# model's hand, so the editor offers that hand's controls and refuses one from the
# operator's before it can be saved. Without it the picker would offer all 23 and the
# refusal would arrive from the bus, three layers from the click that caused it.
def _new_document(path=None) -> ControlMapEditor:
    """One open map. `stream="output"` is stated on purpose: this app drives the model's
    hand, so the picker offers that hand's controls and refuses one from the operator's
    before it can be saved, rather than letting the bus refuse it three layers later."""
    return ControlMapEditor(
        path, clients=[vhi_control, keys], stream="output", title="EDIT THE MAP"
    )


#: Every open map, in tab order. The widget stays single-document — one class, one job —
#: and the app owns the collection, which is where a tab bar belongs.
documents: list[ControlMapEditor] = [_new_document()]
#: Index into `documents`. The active tab is the one that drives the targets, so this is
#: also "which map is running".
active = 0
#: A pending `Open...` dialog, polled the way the editor polls its own Save-as.
open_dialog = None
#: Documents a close was requested for while they had unsaved edits, so the prompt can be
#: shown instead of losing the work.
confirm_close: set[int] = set()
#: Files opened this session, most recent first. Survives closing a tab, which is the whole
#: point of it — reopening something you just closed.
recent: list[pathlib.Path] = []
#: The last reason arming failed, kept so it stays on screen. `app.ctx.log` was the original
#: home and this app draws no log panel, so the explanation went nowhere.
keyboard_error = ""
#: id(document) -> how many controls its targets were offering when the bus was last built.
#: The editor re-asks the targets on a timer, so launching VHI fills *its* picker on its own;
#: the sliders were built from the manifest as it stood at the last `Connect` and nothing
#: rebuilt them. So the two panels disagreed after a launch, and the way out was a button
#: nothing told you had become necessary.
caps_seen: dict[int, int] = {}


def editor() -> ControlMapEditor:
    """The document in front of the user, and therefore the one being driven."""
    return documents[active]
# `launchable` not `launcher`: an unlaunchable renderer must not stop this app from
# opening — a renderer that is already running needs no button, and the reason is
# logged either way.
processes = ProcessLauncher(vhi.launchable())
logo = AppLogo()

LOGO_CELL_W = 260
WORDMARK_ASPECT = 800 / 540
LOGO_H = Px(LOGO_CELL_W / WORDMARK_ASPECT)

# Two layouts, picked per frame from the window's actual width. A Grid's Fr tracks already
# stretch, but the *number* of columns and their proportions are fixed at construction —
# and a 50/50 split is the wrong answer at both ends: at 700 px each half is too narrow
# for the editor's rows, and at 2000 px the sliders get a thousand pixels they have no use
# for. So: stacked below the breakpoint, and a fixed-width control column beside a
# stretching editor above it.
#
# `Px` for the control column rather than `Fr` is the point — the sliders need a usable
# width, not a proportional one, so every pixel the window gains goes to the editor, which
# is the part that can use it.
STACK_BELOW = 900.0
CONTROLS_W = 420.0

WIDE = Grid(
    3,
    2,
    row_height=[LOGO_H, Px(90), Fr(1)],
    col_width=[Px(CONTROLS_W), Fr(1)],
)
NARROW = Grid(
    4,
    1,
    # A shorter wordmark than the wide layout gets: on a narrow window the logo, the
    # launcher and an unconnected slider panel filled better than half the height before
    # any content appeared, and the logo is the only one of the three that is decoration.
    # The editor gets twice the leftover height, because it is the part that has rows to
    # show: an even split left it cut off mid-row while the slider panel above it — often
    # empty, since it has nothing to show until Connect — sat on half the window.
    row_height=[Px(90), Px(90), Fr(1), Fr(2)],
    col_width=[Fr(1)],
)


#: Namespace -> client, in merge order. One list rather than a literal per function, because
#: the editor's picker and these sliders must not disagree about who owns a first segment.
TARGETS = (("vhi", vhi_control), ("keyboard", keys))


def _manifests() -> tuple[list, list[str]]:
    """Ask every target now: its manifest merged, plus the namespaces that did not answer.

    Same merge `ControlMapEditor` does for its picker, for the same reason: one file may
    name controls on several targets, and the address rule namespaces them by first segment
    so two cannot mean different things by one name.

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

    The editor asks the same two clients on a background thread and publishes the answer,
    so a rebuild triggered *by that answer changing* has no business asking again on the
    render thread: it is a second blocking round trip for a fact already in hand, and it can
    see a different state than the one that triggered it, which is a rebuild against
    something nobody observed.

    Which namespaces are absent is read back off the addresses rather than tracked
    separately — a client that answers contributes addresses under its own first segment,
    and one that says nothing contributes none, which is the same test `_manifests` makes.
    """
    capabilities = list(editor().capabilities)
    present = {cap.address.split(".", 1)[0] for cap in capabilities}
    return capabilities, [namespace for namespace, _ in TARGETS if namespace not in present]


def _split(control_map, capabilities, absent):
    """The part of the map that can be driven now, and why the rest cannot.

    An alias is bindable when *every* address it routes to is in the merged manifest — a
    fan-out half of which is missing is not half-drivable, it is a control that would move
    some fingers and not others.

    Local to this app on purpose. It is the only one binding several targets; if a second
    needs it, that is the point to promote it to `myogestic.controls` rather than now.
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

    Rebuilding from scratch each time is deliberate — a stale slider for an alias that no
    longer exists would send a value nothing reads.

    Parameters
    ----------
    known
        A manifest already in hand, as `_manifests` returns it. Passed by
        `_rebuild_if_the_manifest_changed`, which runs without a click and therefore must
        not spend a blocking round trip per target on the render thread for an answer the
        editor's worker fetched seconds ago. Omitted by every caller that *is* a click,
        where asking again is the point of pressing the button.

    Binding still costs a `capabilities()` RPC either way — fast against a renderer that
    is up, and fast against one that is not, since a refused connection comes back at
    once. The client's full two-second deadline needs something holding the port
    without answering.
    """
    global bus, levels, states, status, failure, waiting, keyboard_error
    failure = ""
    # `bus.stop()` below reaches *every* target, and resting the hand and lifting the keys is
    # what that should do on the way out. But this now also runs without a click — when a
    # renderer turns up or goes away — and an arm switch that flicks itself off while you are
    # using it is worse than one that stays on: you armed it, VHI launched, and your keys
    # quietly stopped working with the checkbox unticked and no reason given. So the arm is
    # carried across the rebuild. `_switch_to` and `_close_document` disarm *before* calling
    # this, deliberately, and read back False here — their disarm survives.
    was_armed = keys.armed
    # Cleared here, not only where it is rebuilt below: the early returns (untitled, or a
    # file that would not read) skipped the assignment, so `_waiting_ui` went on listing the
    # *previous* map's undrivable controls under a map that does not contain them.
    waiting = {}
    # A reload can rename or remove any alias, so a field left open would be typing into a
    # control that no longer exists.
    typing.clear()
    focus_pending.clear()
    if bus is not None:
        bus.stop()
        bus = None
    # `editor.path`, not CONTROL_FILE: `Save as...` moves the editor to a new file, and
    # rebuilding from the old one would leave the sliders driving a map nobody is editing.
    path = editor().path
    if path is None:
        # The file is the source of truth, and an untitled map has no file. Save it and this
        # runs again — the editor's save already triggers a rebuild.
        status = "Untitled — save it, and it will start driving."
        return
    try:
        with path.open("rb") as handle:  # "rb" — tomllib requires binary
            control_map = load_control_map(tomllib.load(handle))
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        # A path from the recent list may have moved since, and a file being written by
        # another program can be caught half-saved. Reported, not raised: this runs from a
        # click, and an exception here would take the window down rather than the tab.
        failure = str(exc)
        status = f"{path.name} could not be read."
        return
    # Every target, not just VHI. `KeyboardTarget.capabilities()` answers from local data,
    # so a keyboard-only map resolves with nothing launched at all — the gate that used to
    # sit here made testing a key wait on a renderer it never needed.
    capabilities, absent = _manifests() if known is None else known
    bindable, waiting = _split(control_map, capabilities, absent)
    if not bindable.bindings:
        status = "Nothing in this file can be driven yet."
        return
    try:
        controls = resolve(bindable, capabilities)
        # `interface=` rather than a prebuilt outlet: the target sizes and owns the stream
        # so this file does not have to know how wide the renderer's pose is.
        target = VhiTarget(client=vhi_control, interface=vhi)
        # Both targets share one map. `ControlBus` checks that *someone* claims every
        # alias, so a keyboard address in a VHI-only app is caught here rather than
        # rendering nowhere and looking like a control that works and holds still.
        new_bus = ControlBus(controls, targets=[target, keys], hz=32)
        # Constructing the bus binds the target, which negotiates — but VHI may have
        # come up between the two, so settle it explicitly rather than on the next tick.
        target.negotiate()
    except ValueError as exc:
        # A refusal is the useful case: it names the address it could not place, or the
        # two aliases aiming at one control. Show it instead of leaving a dead slider.
        failure = str(exc)
        status = "That map cannot be rendered by this VHI."
        return
    bus = new_bus
    if was_armed and not keys.armed:
        # Only here, on the path that actually rebuilt: the early returns above leave no bus
        # and no claims, so there is nothing to be armed *for*. `arm` refuses out loud when
        # it cannot press — the same refusal the checkbox reports — so it cannot silently
        # come back half-on.
        try:
            keys.arm()
        except RuntimeError as exc:
            keyboard_error = str(exc)
    levels = {
        alias: 0.0 for alias, dof in controls.dofs.items() if not hasattr(dof, "states")
    }
    states = {
        alias: tuple(dof.states)
        for alias, dof in controls.dofs.items()
        if hasattr(dof, "states")
    }
    app.ctx.control_space = control_map
    held = f" and {len(states)} held state(s)" if states else ""
    held += f", {len(waiting)} waiting" if waiting else ""
    status = f"Driving {len(levels)} control(s){held} from {path.name}."


def _rebuild_if_the_manifest_changed() -> None:
    """Rebuild when the active map's targets start — or stop — offering something.

    The editor re-asks its targets on a timer, so a renderer launched from the PROCESS panel
    turns up in *its* picker a second or two later with no click. The sliders here were built
    from the manifest as it stood at the last `Connect`, and nothing rebuilt them — so after
    a launch the two panels disagreed, and the way out was a button nothing said had become
    necessary. Watching the count the editor already publishes needs no second connection of
    its own, and covers the renderer going away as well as arriving.

    It is also what connects on the very first frame, since `caps_seen` starts empty: the
    panel now opens with the real answer instead of "Press Connect".
    """
    offered = len(editor().capabilities)
    if caps_seen.get(id(editor())) != offered:
        caps_seen[id(editor())] = offered
        # Hand over the manifest that triggered this rather than asking for it again: no
        # click happened, so there is no round trip anyone is waiting through, and re-asking
        # could answer differently from the change being reacted to.
        _connect(_editor_manifest())


@app.ui
def studio_ui(ctx):
    """Sliders and the editor: side by side when there is room, stacked when not."""
    wide = imgui.get_content_region_avail().x >= STACK_BELOW
    grid = WIDE if wide else NARROW
    editor_cell = grid[0:3, 1] if wide else grid[3, 0]

    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        panel_header("DRIVE THE MAP")
        if imgui.button("Connect / Reload"):
            _connect()
        if imgui.get_content_region_avail().x >= 160.0:
            imgui.same_line()
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(editor().label)
        imgui.pop_style_color()

        if failure:
            imgui.text_colored(DANGER, "Refused:")
            imgui.text_wrapped(failure)
        else:
            imgui.push_style_color(imgui.Col_.text, SUCCESS if bus is not None else muted())
            imgui.text_wrapped(status)
            imgui.pop_style_color()

        if bus is not None:
            _sliders_ui()
            _keyboard_ui()
        _waiting_ui()

    with editor_cell:
        _tabs_ui()
        # The editor writes the same file the sliders were built from, so a save is a
        # reason to rebuild them.
        if editor().ui():
            _connect()
        _rebuild_if_the_manifest_changed()


def _sliders_ui() -> None:
    """One slider per control in the file, sized to the column it is in.

    A slider is the one control here that must not be squeezed: a 60-pixel one cannot be
    dragged to a useful value. So the label goes *above* it on a narrow column rather
    than beside it, which buys back the label's width for the track itself.

    **Double-click a slider to type a value instead.** Dragging is right for hunting a
    threshold by feel and wrong for "exactly 0.6", which is the number you want when you
    are comparing a weight against a file. ImGui already offers Ctrl+Click for this on
    every slider; double-click is the gesture people reach for first, so it is wired to the
    same thing.
    """
    assert bus is not None
    avail = imgui.get_content_region_avail().x
    inline = avail >= 260.0
    changed = False
    for alias in levels:
        if not inline:
            imgui.text_unformatted(alias)
        label = alias if inline else f"##{alias}"
        width = avail - (imgui.calc_text_size(alias).x + 12.0 if inline else 0.0)
        imgui.set_next_item_width(width)
        if alias in typing:
            changed = _typed_value_ui(alias, width, alias if inline else None) or changed
            continue
        before = levels[alias]
        edited, levels[alias] = imgui.slider_float(label, levels[alias], -1.0, 1.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Drag, or double-click (or Ctrl+Click) to type a value")
        if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
            # A click on a slider track jumps the value to where it landed, so by the time
            # the second click registers the number has already moved. Put it back: someone
            # double-clicking wants to *type*, not to set a value by accident first.
            levels[alias] = before
            typing[alias] = before
            focus_pending.add(alias)
            edited = False
        changed = changed or edited
    if imgui.button("Rest"):
        levels.update(dict.fromkeys(levels, 0.0))
        changed = True
    if changed:
        bus.push(levels)
    _held_states_ui()


def _keyboard_ui() -> None:
    """The arm switch, shown only when the map actually names a key.

    Deliberately a checkbox rather than a button: an arm you have to hold is a different
    promise from one you can forget about, and this one you can forget about. What stops
    that being reckless is that it is off until you say so, it says loudly when it is on,
    and `KeyboardTarget.stop` lets go of everything on the way out.
    """
    global keyboard_error
    if not keys.claims:
        return
    imgui.separator()
    panel_header("KEYBOARD")
    # Asked before the click, not after it. Without this the switch is a trap: it flicks on,
    # `arm` refuses, it flicks back, and the reason went to `app.ctx.log` — a buffer this app
    # never renders. So the honest answer was written somewhere nobody could see it.
    refusal = keys.arm_refusal
    imgui.begin_disabled(bool(refusal) and not keys.armed)
    changed, armed = imgui.checkbox("Send keys to the system", keys.armed)
    imgui.end_disabled()
    if changed:
        try:
            keys.arm() if armed else keys.disarm()
            keyboard_error = ""
        except RuntimeError as exc:
            keyboard_error = str(exc)
    if refusal or keyboard_error:
        imgui.push_style_color(imgui.Col_.text, DANGER)
        imgui.text_wrapped("Cannot send keys yet:")
        imgui.pop_style_color()
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(refusal or keyboard_error)
        imgui.pop_style_color()
        if imgui.button("Grant access..."):
            # It cannot grant anything — only the user can, in System Settings, and there is
            # no API for it. What it does is register this binary in the Accessibility list
            # and open the pane, which removes the step people actually give up at: finding a
            # bare interpreter path in Finder and dragging it in.
            keyboard_error = keys.request_accessibility() or keyboard_error
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Asks macOS and opens the Accessibility list with this program in it.\n"
                "You still have to switch it on, then restart MyoGestic."
            )
        imgui.same_line()
        if imgui.button("Copy the path"):
            # Still worth having: if the prompt is dismissed or the list is being edited by
            # hand, the binary is the one thing that has to be exact and it is long.
            imgui.set_clipboard_text(os.path.realpath(sys.executable))
        return
    imgui.push_style_color(imgui.Col_.text, DANGER if keys.armed else muted())
    imgui.text_wrapped(
        f"ARMED — {len(keys.claims)} control(s) are typing into whatever window has focus."
        if keys.armed
        else f"Disarmed. {len(keys.claims)} key control(s) are mapped and will do nothing."
    )
    imgui.pop_style_color()


def _typed_value_ui(alias: str, width: float, label: str | None) -> bool:
    """The double-clicked slider, as a field. True when a value was committed.

    Enter commits, and so does clicking away having typed something; Escape abandons,
    because ImGui restores the value it opened with. The slider comes back either way — a
    field that stayed open would leave the control undraggable with no obvious way out.
    """
    if alias in focus_pending:
        imgui.set_keyboard_focus_here()
        focus_pending.discard(alias)
    # ImGui has no way to centre text inside an input — there is a style var for a button's
    # label and a selectable's, and none for this. So the *field* is centred instead: sized
    # to its number and placed in the middle of the span the slider filled, which keeps the
    # digits where the eye left them. Full width would put them hard against the left edge,
    # which is the jump this avoids.
    start_x = imgui.get_cursor_pos_x()
    style = imgui.get_style()
    field_w = min(
        width,
        imgui.calc_text_size(f"{typing[alias]:.3f}").x + style.frame_padding.x * 2.0 + 8.0,
    )
    imgui.set_cursor_pos_x(start_x + (width - field_w) * 0.5)
    imgui.set_next_item_width(field_w)
    # A **different ImGui id** from the slider it replaces, which is the whole reason this
    # works. An id identifies interaction state, and the mouse is still down from the
    # second click when this field first draws — handed the slider's id, ImGui sees the
    # active widget change type underneath itself and drops the field on the same frame it
    # appeared. Hidden here, and the label redrawn below where the slider put it, so it
    # does not ride along with the narrowed field.
    field_id = f"##{alias}_typed"
    # No `enter_returns_true`: `input_float` is `InputScalar` underneath, and ImGui
    # asserts that flag is *not* set on it — it is an `InputText` flag, and the scalar
    # wrappers handle Enter themselves. Passing it raised out of the render callback and
    # took the window down, on the one interaction the slider's tooltip advertises.
    # `is_item_deactivated_after_edit` is the supported way to ask "did this commit", and
    # it fires on Enter and on clicking away having changed the value.
    _, value = imgui.input_float(field_id, typing[alias], 0.0, 0.0, "%.3f")
    # Read **before** anything else is submitted. `is_item_*` answers about the last item,
    # so drawing the label first made both of these ask the label — which never
    # deactivates, so the field committed nothing and never closed, and the slider never
    # came back.
    committed = imgui.is_item_deactivated_after_edit()
    dismissed = imgui.is_item_deactivated()
    typing[alias] = value
    if label is not None:
        # Where `slider_float` would have drawn it: past the full span, not past the field.
        imgui.same_line(start_x + width + style.item_inner_spacing.x)
        imgui.text_unformatted(label)
    if committed:
        # Clamped to the same domain the slider offers. The bus clips anyway, so this is
        # about not *displaying* a value the hand will never render.
        levels[alias] = min(1.0, max(-1.0, value))
        typing.pop(alias, None)
        return True
    if dismissed:
        typing.pop(alias, None)
    return False


def _switch_to(index: int) -> None:
    """Make a document the active one, and therefore the running one.

    Disarms the keyboard on the way. A map you have just navigated away from must not keep
    sending keystrokes, and re-arming is one click — which is the right side to err on for
    something that types into whatever window has focus.
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

    An app with no document is a state with nothing to look at and no way back except a
    button that would have to appear from nowhere, so closing the last tab hands back a
    blank one instead.
    """
    global active
    # Before the document goes: `caps_seen` is keyed by `id`, and CPython reuses the id of a
    # collected object. A new document landing on a dead one's id, with the same number of
    # controls offered, would read as "nothing has changed" and skip its rebuild.
    caps_seen.pop(id(documents[index]), None)
    documents.pop(index)
    if not documents:
        documents.append(_new_document())
    active = min(active if index > active else max(0, active - 1), len(documents) - 1)
    keys.disarm()
    _connect()


def _tab_label(index: int, among: list[ControlMapEditor] | None = None) -> str:
    """What a tab says. Untitled maps are numbered in tab order.

    The widget calls them all "Untitled" because it only knows about itself; which one of
    several this is, is the app's question. `##doc{i}` keeps ImGui's ids apart either way —
    this is so the *reader* can tell them apart too.

    `among` is the list to number within, and passing the frame's own snapshot is not
    optional during a render: this indexed the live `documents` while the caller iterated a
    copy, so closing a tab shrank the list under the loop and the next label raised
    `IndexError` — which escaped past `end_tab_bar()` and took the whole app down with an
    ImGui assert.
    """
    within = documents if among is None else among
    document = within[index]
    if document.path is not None:
        return document.label
    nth = 1 + sum(1 for earlier in within[:index] if earlier.path is None)
    return "Untitled" if nth == 1 else f"Untitled {nth}"


def _tabs_ui() -> None:
    """One tab per open map, a `+` for a new one, and a way to open a file.

    A tab bar is the first in this repo — `segmented` is the house control for picking one
    of N — and it earns the exception because documents need a close button each and a row
    that scrolls when there are more than fit, neither of which `segmented` has.
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
    # Nothing structural happens inside the bar. Every click is recorded and applied after
    # `end_tab_bar`, because adding or removing a document mid-loop changes the very list
    # being walked — and an exception raised in there skips `end_tab_bar` entirely, which
    # ImGui answers with an assert that kills the process rather than a traceback.
    snapshot = list(documents)
    close_at: int | None = None
    switch_to: int | None = None
    add_blank = False
    for index, document in enumerate(snapshot):
        dirty = "*" if document._dirty() else ""
        # `##doc{index}` because two untitled maps share a visible label, and an ImGui id
        # *is* the widget's state — two tabs with one id would be one tab.
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
    # A caret rather than an "Open..." tab. A tab strip is for tabs, and a button shaped like
    # one reads as a document called "Open..." — which is why that felt wrong. Everything
    # that *makes* a tab lives behind this instead, where you already look for "another one".
    show_menu = imgui.tab_item_button("v", imgui.TabItemFlags_.trailing)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Open a file, an example, or something recent")
    imgui.end_tab_bar()
    if show_menu:
        # Opened after `end_tab_bar`, and drawn there too: a popup begun inside the bar
        # nests into it, and closing the bar first is what keeps the two stacks separate.
        imgui.open_popup("documents")
    _documents_menu()

    # Apply, now that the bar is closed. Close last: it is the one that can renumber
    # everything, so letting a switch or an add settle first keeps the indices meaningful.
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

    The examples matter more than they look. The studio starts on a blank map now, so
    `examples/controls/` went from "the file you opened into" to invisible — this is what
    keeps them discoverable without making one of them the default again.
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
    # This session only. Its use is reopening a tab you closed, which is exactly the thing a
    # session-scoped list is good for; persisting it would need a config store this app does
    # not have, and inventing one for a convenience is the wrong trade.
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
        f"{_tab_label(index) if document else 'That map'} has unsaved edits. "
        f"Closing it loses them."
    )
    imgui.separator()
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

    Deliberately *not* sliders. A slider for a control whose target has not answered would
    move and do nothing, which is the one failure this whole standard is arranged to
    prevent — so an undrivable control gets a sentence naming what is absent instead.
    """
    if not waiting:
        return
    imgui.separator()
    imgui.push_style_color(imgui.Col_.text, WARNING)
    imgui.text_wrapped(f"{len(waiting)} control(s) not driven:")
    imgui.pop_style_color()
    imgui.push_style_color(imgui.Col_.text, muted())
    for alias, why in waiting.items():
        imgui.bullet()
        imgui.text_wrapped(f"{alias}: {why}")
    imgui.pop_style_color()


def _held_states_ui() -> None:
    """A picker per held control: choose one of the states the target declared.

    `bus.select` rather than `bus.push`: a held state is delivered on change and rebases
    its own stability gate, so the next frame's push does not re-fire what was just
    chosen. And the states are the *target's* names — this app invents none of them.
    """
    assert bus is not None
    if not states:
        return
    imgui.separator()
    for alias, options in states.items():
        imgui.set_next_item_width(imgui.get_content_region_avail().x * 0.6)
        if imgui.begin_combo(alias, chosen.get(alias, options[0])):
            for state in options:
                selected, _ = imgui.selectable(state, chosen.get(alias) == state)
                if selected:
                    chosen[alias] = state
                    bus.select(alias, state)
            imgui.end_combo()


def main() -> None:
    """Run until the window closes, then rest the hand."""
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        # `bus.stop()` reaches the target, and the target owns the outlet it built, so
        # there is no separate outlet to stop here.
        if bus is not None:
            bus.stop()          # reaches both targets: rests the hand, lifts every key
        keys.stop()             # and again, in case the bus was never built
        vhi_control.stop()


if __name__ == "__main__":
    main()
