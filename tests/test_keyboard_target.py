"""`KeyboardTarget` — what actually reaches the keyboard, without touching a keyboard.

Every test here drives a recording backend. That is not only for speed: a test suite that
pressed real keys would type into whatever window happened to be focused on the machine
running it, which is the same hazard the target's arm guard exists for.

The property that matters most: **a key that goes down comes back up.** A stuck modifier
outlives the process that set it, and no teardown runs on a hard kill — so `disarm`, `stop`
and a failing backend all have to let go of everything.
"""

from __future__ import annotations

import pytest

from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.keyboard import KeyboardTarget, keyboard_capabilities

CAPS = keyboard_capabilities()


class Recorder:
    """A backend that writes down what it was asked to do."""

    def __init__(self, fail: bool = False) -> None:
        self.events: list[tuple[str, str]] = []
        self.fail = fail

    def press(self, spec) -> None:
        if self.fail:
            raise RuntimeError("no permission")
        self.events.append(("press", spec[1]))

    def release(self, spec) -> None:
        if self.fail:
            raise RuntimeError("no permission")
        self.events.append(("release", spec[1]))


@pytest.fixture(autouse=True)
def _permission_granted(monkeypatch):
    """Pretend the OS allows key events, unless a test says otherwise.

    Without this the suite would pass or fail depending on whether the machine running it
    has granted Accessibility to the test runner — which is exactly the kind of "works on
    mine" the target's own check exists to eliminate.

    Patched at `_trusted`, the OS question, rather than at `_accessibility_refusal`, the
    answer. Stubbing the answer also stubbed out the *message*, so a test about what the
    refusal actually says could not get at it however it patched underneath — this fixture
    always won. Tests about the refusal patch `_trusted` and read the real message.
    """
    monkeypatch.setattr("myogestic.keyboard._trusted", lambda: True)


def _target(dofs, *, armed=True, backend=None):
    """A bound target for `dofs`, armed by default because most tests are about sending."""
    backend = backend if backend is not None else Recorder()
    target = KeyboardTarget(backend=backend, armed=armed)
    target.bind(resolve(load_control_map({"dofs": dofs}), CAPS))
    return target, backend


# --- the manifest ---------------------------------------------------------------


class TestWhatItAdvertises:
    def test_every_address_has_four_segments(self):
        """The picker's tree is built by splitting on dots, so the shape is the contract."""
        assert all(len(cap.address.split(".")) == 4 for cap in CAPS)

    def test_every_key_is_offered_in_both_modes(self):
        holds = {c.address.replace("keyboard.hold.", "") for c in CAPS if ".hold." in c.address}
        taps = {c.address.replace("keyboard.tap.", "") for c in CAPS if ".tap." in c.address}
        assert holds == taps
        assert len(holds) > 100

    def test_a_key_is_a_two_state_discrete_control(self):
        """Not a new kind. This is what makes the existing threshold machinery apply."""
        cap = next(c for c in CAPS if c.address == "keyboard.hold.letter.a")
        assert cap.kind == "discrete"
        assert cap.states == ("up", "down")
        assert cap.rest_state == "up"

    def test_no_key_is_a_number(self):
        """A key is a held state, and a held state drives no stream.

        Kind is the whole of what keeps a key off a wire now. There used to be a second
        signal — `channel = -1` and an empty `stream_name` — but a manifest no longer
        describes transport at all: a streamed control's stream is named for its address,
        so a control that is not a number has nothing to name.
        """
        assert all(cap.kind == "discrete" for cap in CAPS)
        assert not hasattr(CAPS[0], "channel"), "a capability carries no transport"
        assert not hasattr(CAPS[0], "stream_name")

    def test_a_scalar_activates_at_the_declared_threshold(self):
        """Wiring, not arithmetic: the rule lives in the core and is tested there.

        What this pins is that a keyboard capability resolves into a DOF the core will
        drive from a number at all — `activates` is only set for a two-state control.
        """
        controls = resolve(load_control_map({"dofs": {"go": "keyboard.hold.letter.w"}}), CAPS)
        dof = controls.dofs["go"]
        assert dof.activates == "down"
        assert dof.threshold_fraction == pytest.approx(0.5)


# --- pressing -------------------------------------------------------------------


class TestHoldAndTap:
    def test_hold_presses_on_the_way_up_and_releases_on_the_way_down(self):
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"go": "down"})
        assert rec.events == [("press", "w")]
        target.send({}, {"go": "up"})
        assert rec.events == [("press", "w"), ("release", "w")]

    def test_tap_presses_and_releases_at_once_and_ignores_the_way_down(self):
        """One gesture is one keystroke, however long it is held."""
        target, rec = _target({"fire": "keyboard.tap.edit.space"})
        target.send({}, {"fire": "down"})
        assert rec.events == [("press", "space"), ("release", "space")]
        target.send({}, {"fire": "up"})
        assert rec.events == [("press", "space"), ("release", "space")]

    def test_a_held_key_is_not_re_pressed_every_tick(self):
        """`send` reads edges, never the level — the difference between held and repeated."""
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"go": "down"})
        for _ in range(5):
            target.send({"go": "down"}, {})     # values, no edges
        assert rec.events == [("press", "w")]

    def test_two_controls_press_two_keys(self):
        target, rec = _target(
            {"go": "keyboard.hold.letter.w", "fire": "keyboard.tap.edit.space"}
        )
        target.send({}, {"go": "down", "fire": "down"})
        assert ("press", "w") in rec.events
        assert ("press", "space") in rec.events

    def test_an_alias_this_target_does_not_own_is_ignored(self):
        """A map shared with another target reaches this one too; it must not guess."""
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"someone_elses": "down"})
        assert rec.events == []


# --- the guard ------------------------------------------------------------------


class TestArming:
    def test_disarmed_is_the_default(self):
        """A resolved map is live the instant it binds. Not this one."""
        assert KeyboardTarget(backend=Recorder()).armed is False

    def test_disarmed_sends_nothing(self):
        target, rec = _target({"go": "keyboard.hold.letter.w"}, armed=False)
        target.send({}, {"go": "down"})
        assert rec.events == []

    def test_arming_does_not_replay_what_was_missed(self):
        """Arming means "from now on", not "catch up" — a burst of stale presses on arm
        would be the surprise the guard exists to prevent."""
        target, rec = _target({"go": "keyboard.hold.letter.w"}, armed=False)
        target.send({}, {"go": "down"})
        target.arm()
        assert rec.events == []

    def test_arming_is_refused_when_the_os_would_drop_the_keys(self, monkeypatch):
        """The worst state this module can be in is "armed and silently doing nothing".

        macOS discards every event from a process without Accessibility permission, and
        `pynput` cannot tell — it reports success either way. Observed live: the target
        armed, the map was correct, and nothing was pressed. So the permission is checked
        and arming *fails* rather than lying.
        """
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb, "_accessibility_refusal", lambda: "no permission here")
        target = KeyboardTarget(backend=Recorder())
        with pytest.raises(RuntimeError, match="no permission here"):
            target.arm()
        assert target.armed is False

    def test_a_refused_arm_sends_nothing(self, monkeypatch):
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb, "_accessibility_refusal", lambda: "nope")
        target, rec = _target({"go": "keyboard.hold.letter.w"}, armed=False)
        with pytest.raises(RuntimeError):
            target.arm()
        target.send({}, {"go": "down"})
        assert rec.events == []

    def test_the_check_passes_off_darwin(self, monkeypatch):
        """A platform with no such permission must not be blocked by a check for it."""
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "linux")
        assert kb._accessibility_refusal() == ""

    def test_disarming_releases_what_is_held(self):
        """Otherwise disarming mid-gesture leaves a key down with nothing left to lift it."""
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"go": "down"})
        target.disarm()
        assert rec.events == [("press", "w"), ("release", "w")]
        assert target.armed is False

    def test_stop_releases_what_is_held(self):
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"go": "down"})
        target.stop()
        assert ("release", "w") in rec.events

    def test_stop_is_idempotent(self):
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"go": "down"})
        target.stop()
        target.stop()
        assert rec.events.count(("release", "w")) == 1

    def test_rebinding_releases_the_previous_map(self):
        """A hot reload rebinds; a key held under the old map would never be lifted."""
        target, rec = _target({"go": "keyboard.hold.letter.w"})
        target.send({}, {"go": "down"})
        target.bind(resolve(load_control_map({"dofs": {"go": "keyboard.hold.letter.a"}}), CAPS))
        assert ("release", "w") in rec.events


# --- refusing -------------------------------------------------------------------


class TestRefusals:
    def test_a_key_that_does_not_exist_is_refused_at_bind(self):
        """On the main thread, with a traceback — not as a key that never fires."""
        target = KeyboardTarget(backend=Recorder())
        controls = resolve(load_control_map({"dofs": {"go": "keyboard.hold.letter.w"}}), CAPS)
        # Rewrite the route to something the manifest never advertised.
        from myogestic.controls import TargetRef

        object.__setattr__(
            controls, "routes", {"go": (TargetRef("keyboard.hold.letter.nope"),)}
        )
        with pytest.raises(ValueError, match="not a key this target presses"):
            target.bind(controls)

    def test_a_backend_failure_disarms_instead_of_raising(self):
        """`send` runs on the predict thread. Raising there takes the whole loop down."""
        target, _ = _target({"go": "keyboard.hold.letter.w"}, backend=Recorder(fail=True))
        target.send({}, {"go": "down"})          # must not raise
        assert target.armed is False

    def test_claims_reports_exactly_the_keyboard_aliases(self):
        """`ControlBus` refuses a map where some alias renders nowhere, and with two
        targets sharing one map that check is the only thing that catches a typo."""
        target, _ = _target(
            {"go": "keyboard.hold.letter.w", "fire": "keyboard.tap.edit.space"}
        )
        assert target.claims == frozenset({"go", "fire"})

    def test_a_bus_accepts_a_keyboard_only_map(self):
        """End to end through the real bus, which is what an app actually builds."""
        rec = Recorder()
        target = KeyboardTarget(backend=rec, armed=True)
        controls = resolve(load_control_map({"dofs": {"go": "keyboard.hold.letter.w"}}), CAPS)
        bus = ControlBus(controls, targets=[target], hz=32)
        bus.select("go", "down")
        bus.stop()
        assert ("press", "w") in rec.events


class TestItSaysWhyItCannotArm:
    """The switch must not be a trap.

    Without a reason asked for *before* the click, arming looks broken: the toggle flicks
    on, `arm` refuses, it flicks back, and the explanation went to a log panel the studio
    does not render. `arm_refusal` is the question the UI can ask first.
    """

    def test_a_working_backend_has_no_refusal(self, monkeypatch):
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb, "_accessibility_refusal", lambda: "")
        assert KeyboardTarget(backend=Recorder()).arm_refusal == ""

    def test_a_refusal_stops_arm_and_says_so(self, monkeypatch):
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb, "_accessibility_refusal", lambda: "no permission here")
        target = KeyboardTarget(backend=Recorder())
        assert target.arm_refusal == "no permission here"
        with pytest.raises(RuntimeError, match="no permission here"):
            target.arm()
        assert target.armed is False

    def test_an_untrusted_mac_is_refused_and_told_which_binary(self, monkeypatch):
        """"The program running MyoGestic" is the classic macOS ambiguity: the permission
        attaches to a binary, and for a virtualenv it is not the symlink you launched."""
        import os
        import sys

        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "darwin")
        monkeypatch.setattr(kb, "_trusted", lambda: False)
        refusal = kb._accessibility_refusal()
        assert "Accessibility" in refusal
        assert os.path.realpath(sys.executable) in refusal

    def test_a_trusted_mac_refuses_nothing(self, monkeypatch):
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "darwin")
        monkeypatch.setattr(kb, "_trusted", lambda: True)
        assert kb._accessibility_refusal() == ""

    def test_a_platform_without_the_permission_is_never_refused(self, monkeypatch):
        """A false refusal would be worse than no check — it would block Linux and Windows,
        which have no such permission at all."""
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "linux")
        monkeypatch.setattr(kb, "_trusted", lambda: False)
        assert kb._accessibility_refusal() == ""

    def test_missing_pyobjc_does_not_block(self, monkeypatch):
        """No way to ask means assume yes: refusing on an unanswerable question is worse."""
        import builtins

        import myogestic.keyboard as kb

        real_import = builtins.__import__

        def no_appservices(name, *args, **kwargs):
            if name == "ApplicationServices":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_appservices)
        assert kb._trusted() is True


class TestAKeyThisPlatformLacks:
    """The manifest is the same everywhere; the keys are not.

    `insert` exists on Windows and Linux and simply is not a macOS key. Advertising it keeps
    a control map portable — a manifest that varied by machine would make a map resolve here
    and fail there — so the per-platform truth is a `bind`-time refusal instead. Without it
    the `getattr(Key, "insert")` happened inside `send`, on the predict thread, where it must
    not raise and would therefore be swallowed into a control that silently never fires.
    """

    def test_every_advertised_key_is_pressable_or_refused_at_bind(self):
        """No advertised key may fail at press time. Either it resolves, or `bind` says so."""
        from myogestic.controls import load_control_map, resolve
        from myogestic.keyboard import _spec_for, _unpressable

        caps = keyboard_capabilities()
        for cap in caps:
            spec = _spec_for(cap.address)
            assert spec is not None, cap.address
            if not _unpressable(spec):
                continue
            controls = resolve(load_control_map({"dofs": {"k": cap.address}}), caps)
            with pytest.raises(ValueError, match="no key for"):
                KeyboardTarget(backend=Recorder()).bind(controls)

    def test_a_pressable_key_still_binds(self):
        from myogestic.controls import load_control_map, resolve

        caps = keyboard_capabilities()
        controls = resolve(
            load_control_map({"dofs": {"k": "keyboard.hold.function.f1"}}), caps
        )
        target = KeyboardTarget(backend=Recorder())
        target.bind(controls)
        assert target.claims == frozenset({"k"})

    def test_without_pynput_nothing_is_called_unpressable(self, monkeypatch):
        """Unknowable is allowed — the same rule the rest of this library follows."""
        import builtins

        from myogestic.keyboard import _unpressable

        real_import = builtins.__import__

        def no_pynput(name, *args, **kwargs):
            if name == "pynput" or name.startswith("pynput."):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_pynput)
        assert _unpressable(("key", "definitely_not_a_key")) == ""


class TestAskingForThePermission:
    """A button can ask; it cannot grant.

    Only the user can turn on Accessibility, in System Settings, and no API exists to do it
    for them — that is what the TCC boundary is. What can be automated is the step people give
    up at: getting a bare interpreter path *into* the list, which otherwise means finding it in
    Finder with Cmd+Shift+G and dragging it in.
    """

    def test_it_says_nothing_when_already_granted(self, monkeypatch):
        """No prompt, no settings pane, no message — there is nothing to fix."""
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "darwin")
        monkeypatch.setattr(kb, "_trusted", lambda: True)
        called = []
        monkeypatch.setattr(kb.subprocess, "run", lambda *a, **k: called.append(a))
        assert kb.request_accessibility() == ""
        assert called == []

    def test_it_opens_the_pane_and_names_the_binary(self, monkeypatch):
        import os
        import sys

        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "darwin")
        monkeypatch.setattr(kb, "_trusted", lambda: False)
        opened = []
        monkeypatch.setattr(
            kb.subprocess, "run", lambda cmd, **k: opened.append(cmd)
        )
        message = kb.request_accessibility()
        assert opened and opened[0][0] == "open"
        assert "Privacy_Accessibility" in opened[0][1]
        assert os.path.realpath(sys.executable) in message
        assert "restart" in message.lower()

    def test_a_failing_prompt_is_reported_not_raised(self, monkeypatch):
        """It runs from a click. An exception here would take the window down."""
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "darwin")
        monkeypatch.setattr(kb, "_trusted", lambda: False)

        def boom(*_args, **_kwargs):
            raise OSError("no `open` here")

        monkeypatch.setattr(kb.subprocess, "run", boom)
        assert kb.request_accessibility()          # a message, not an exception

    def test_it_does_nothing_off_macos(self, monkeypatch):
        import myogestic.keyboard as kb

        monkeypatch.setattr(kb.sys, "platform", "linux")
        called = []
        monkeypatch.setattr(kb.subprocess, "run", lambda *a, **k: called.append(a))
        assert kb.request_accessibility() == ""
        assert called == []

    def test_the_target_offers_it_too(self):
        """"Why can I not arm" and "help me fix it" belong next to each other."""
        assert callable(KeyboardTarget(backend=Recorder()).request_accessibility)
