"""Press keys when a control is active — a `myogestic.controls.Target` for the keyboard.

A key is a **two-state discrete control**; nothing here extends the standard.

    [dofs]
    walk  = "keyboard.hold.letter.w"          # held while the control is above 0.5
    fire  = "keyboard.tap.edit.space"         # one press per crossing

A model output crossing the threshold selects the non-rest state, `ControlBus` delivers
that as an **edge**, and this presses or releases. The threshold is
`myogestic.controls.Capability.activation_threshold` (0.5 here); a binding overrides it
with `threshold_fraction`, and chatter is handled by `debounce_s`.

Addresses are `keyboard.<mode>.<category>.<key>`, mode first.

.. danger::
    **This types into whatever window has focus.** A twitchy signal bound to
    ``keyboard.tap.edit.enter`` acts on your terminal. So a `KeyboardTarget` starts
    **disarmed** and sends nothing until `KeyboardTarget.arm` is called, and it disarms
    itself on `KeyboardTarget.stop`, on a backend failure, and when the process exits.
    Prefer a ``tap`` for anything destructive: a held key outlives a crash, and no
    teardown runs on ``SIGKILL``.

.. note::
    Needs the ``keyboard`` extra (``pynput``), imported lazily so this module loads
    without it. On macOS the process also needs **Accessibility** permission —
    System Settings › Privacy & Security › Accessibility. Without it `pynput` reports
    success and nothing happens, so `KeyboardTarget.arm` refuses and says why.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from myogestic.controls import Capability

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic.controls import ControlSet

log = logging.getLogger("myogestic.keyboard")

#: The first address segment, which keeps this target's controls distinct from any other's.
NAMESPACE = "keyboard"

#: How a key follows its control. ``hold`` presses on the way up and releases on the way
#: down, so the key is down exactly while the control is active. ``tap`` presses *and*
#: releases the moment the control goes active and ignores its release, so one gesture is
#: one keystroke however long it is held.
MODES = ("hold", "tap")

#: The two states every key control declares. A scalar picks `_DOWN` at the threshold.
_UP, _DOWN = "up", "down"

#: Every key, by category, mapped to how the backend should name it: ``("char", c)`` for
#: something that types a character, ``("key", n)`` for a named key. Keeping the backend's
#: vocabulary out of the addresses means `keyboard_capabilities` needs no `pynput`, so a
#: map can be written, validated and inspected on a machine that cannot press anything.
_KEYS: dict[str, dict[str, tuple[str, str]]] = {
    "letter": {c: ("char", c) for c in "abcdefghijklmnopqrstuvwxyz"},
    "digit": {d: ("char", d) for d in "0123456789"},
    "nav": {
        name: ("key", name)
        for name in ("left", "right", "up", "down", "home", "end", "page_up", "page_down")
    },
    "edit": {
        "enter": ("key", "enter"),
        "tab": ("key", "tab"),
        "space": ("key", "space"),
        "escape": ("key", "esc"),
        "backspace": ("key", "backspace"),
        "delete": ("key", "delete"),
        "insert": ("key", "insert"),
    },
    "modifier": {name: ("key", name) for name in ("shift", "ctrl", "alt", "cmd")},
    "function": {f"f{n}": ("key", f"f{n}") for n in range(1, 21)},
    "numpad": {
        **{f"n{d}": ("char", d) for d in "0123456789"},
        "add": ("char", "+"),
        "subtract": ("char", "-"),
        "multiply": ("char", "*"),
        "divide": ("char", "/"),
        "decimal": ("char", "."),
    },
    "punctuation": {
        "minus": ("char", "-"),
        "equal": ("char", "="),
        "bracket_left": ("char", "["),
        "bracket_right": ("char", "]"),
        "backslash": ("char", "\\"),
        "semicolon": ("char", ";"),
        "quote": ("char", "'"),
        "comma": ("char", ","),
        "period": ("char", "."),
        "slash": ("char", "/"),
        "grave": ("char", "`"),
    },
    "media": {
        "volume_up": ("key", "media_volume_up"),
        "volume_down": ("key", "media_volume_down"),
        "volume_mute": ("key", "media_volume_mute"),
        "play_pause": ("key", "media_play_pause"),
        "next": ("key", "media_next"),
        "previous": ("key", "media_previous"),
    },
}

#: What a scalar has to reach before the key goes down. A binding overrides it per control
#: with `threshold_fraction`.
ACTIVATION_THRESHOLD = 0.5


def _spec_for(address: str) -> tuple[str, str] | None:
    """The backend spec an address names, or None if it names no key here."""
    parts = address.split(".")
    if len(parts) != 4 or parts[0] != NAMESPACE or parts[1] not in MODES:
        return None
    return _KEYS.get(parts[2], {}).get(parts[3])


def keyboard_capabilities() -> tuple[Capability, ...]:
    """Every key this target can press, in both modes.

    The manifest a `myogestic.controls.resolve` call validates a map against, exactly like
    a renderer's. Around 220 entries — every key twice.

    Returns
    -------
    tuple[myogestic.controls.Capability, ...]
        Discrete and two-state. A held state travels over its target's own command
        channel, never on a stream, so nothing may try to route one onto a wire.

    Examples
    --------
    >>> from myogestic.keyboard import keyboard_capabilities
    >>> caps = {c.address: c for c in keyboard_capabilities()}
    >>> caps["keyboard.hold.letter.a"].states
    ('up', 'down')
    >>> caps["keyboard.tap.edit.space"].activation_threshold
    0.5
    """
    caps: list[Capability] = []
    for mode in MODES:
        held = "held down while active" if mode == "hold" else "pressed once when activated"
        for category, keys in _KEYS.items():
            for key in keys:
                caps.append(
                    Capability(
                        address=f"{NAMESPACE}.{mode}.{category}.{key}",
                        kind="discrete",
                        states=(_UP, _DOWN),
                        rest_state=_UP,
                        activation_threshold=ACTIVATION_THRESHOLD,
                        description=f"{category} key {key!r}, {held}",
                    )
                )
    return tuple(caps)


def _trusted() -> bool:
    """Whether macOS trusts this process to post key events.

    A separate function so a test can say "trusted" or "not" without injecting a pyobjc
    module — `from ApplicationServices import ...` goes through pyobjc's lazy loader, which
    does not read `sys.modules`, so patching that way silently does nothing.
    """
    try:
        from ApplicationServices import AXIsProcessTrusted  # noqa: PLC0415 - darwin only
    except ImportError:
        return True  # No pyobjc: assume fine rather than refuse on a guess.
    return bool(AXIsProcessTrusted())


def _unpressable(spec: tuple[str, str]) -> str:
    """Why this platform cannot press `spec`, or "" when it can.

    The manifest does not vary by platform, so that a map stays portable; the per-platform
    truth is checked here instead, and `bind` turns it into a refusal.

    Without `pynput` installed this cannot know, and returns ``""`` rather than refuse on a
    guess.
    """
    try:
        from pynput import keyboard as backend  # noqa: PLC0415 - optional extra
    except ImportError:
        return ""
    kind, name = spec
    try:
        backend.KeyCode.from_char(name) if kind == "char" else getattr(backend.Key, name)
    except Exception as exc:  # noqa: BLE001 - reported as a reason, not raised
        return f"{type(exc).__name__}: {exc}"
    return ""


#: The exact System Settings pane.
_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"


def request_accessibility() -> str:
    """Ask macOS for Accessibility permission, and report what happened.

    **This cannot grant the permission.** Only the user can, in System Settings.
    `AXIsProcessTrustedWithOptions` with the prompt option shows the system dialog *and
    registers this binary in the Accessibility list*, so it appears there ready to be
    switched on rather than having to be dragged in from Finder. The pane is also opened
    directly, since that is where the switch is.

    Returns
    -------
    str
        What to tell the user. Empty when the permission is already granted.

    Notes
    -----
    Take effect needs a **restart** of the process: the trust is read once at launch, so a
    switch flicked while this is running does not reach the already-loaded event tap.
    """
    if sys.platform != "darwin":
        return ""
    if _trusted():
        return ""
    prompted = False
    try:
        from ApplicationServices import (  # noqa: PLC0415 - darwin only
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        prompted = True
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        log.info("could not raise the Accessibility prompt: %s", exc)
    try:
        subprocess.run(["open", _SETTINGS_URL], check=False, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("could not open the Accessibility pane: %s", exc)
    listed = (
        "macOS has been asked, so this program is now listed under Accessibility"
        if prompted
        else "Open the Accessibility list"
    )
    return (
        f"{listed} — switch it on, then **restart MyoGestic**. The permission is read once "
        f"at launch, so flicking it while this is running will not reach the event tap.\n"
        f"    {os.path.realpath(sys.executable)}"
    )


def _accessibility_refusal() -> str:
    """Why macOS will drop every key event, or an empty string when it will not.

    Without the permission `pynput` accepts every press and the system discards it, so an
    armed target with a correct map does nothing and says nothing.

    Not macOS, or the check is unavailable: assume fine, rather than refuse on a platform
    that has no such permission at all.
    """
    if sys.platform != "darwin" or _trusted():
        return ""
    # The *resolved* interpreter path: the permission attaches to a binary, and for a
    # virtualenv that binary is not the venv symlink but what it points at.
    binary = os.path.realpath(sys.executable)
    return (
        "macOS has not granted Accessibility permission, so every key event would be "
        "accepted and then discarded. Add this binary under System Settings > Privacy & "
        f"Security > Accessibility:\n    {binary}\n"
        "Then restart MyoGestic — the permission is read once at launch. If you launched "
        "from a terminal or an IDE, granting it to that app works too."
    )


class _PynputBackend:
    """Presses keys for real. The default, and the only part that needs `pynput`."""

    def __init__(self) -> None:
        from pynput.keyboard import Controller, Key, KeyCode  # noqa: PLC0415 - see module doc

        self._controller = Controller()
        self._key, self._code = Key, KeyCode

    def _resolve(self, spec: tuple[str, str]) -> Any:
        kind, name = spec
        return self._code.from_char(name) if kind == "char" else getattr(self._key, name)

    def press(self, spec: tuple[str, str]) -> None:
        """Send a key-down."""
        self._controller.press(self._resolve(spec))

    def release(self, spec: tuple[str, str]) -> None:
        """Send a key-up."""
        self._controller.release(self._resolve(spec))


class KeyboardTarget:
    """Press keys from control values.

    A `myogestic.controls.Target`: construct it, hand it to a
    `myogestic.controls.ControlBus`, and register `stop` with ``app.cleanup_hooks``.

    Parameters
    ----------
    backend
        Anything with ``press(spec)`` and ``release(spec)``. Defaults to a `pynput` one,
        constructed on the first `arm` rather than here, so importing this module, listing
        its capabilities and resolving a map all work without the extra installed.
    armed
        Start armed. Defaults to **False**: a resolved map is live the moment it binds,
        into whatever window has focus.

    Notes
    -----
    `send` acts only on the **edges** `ControlBus` reports, never on the level.

    Examples
    --------
    >>> from myogestic.controls import ControlBus, load_control_map, resolve
    >>> from myogestic.keyboard import KeyboardTarget, keyboard_capabilities
    >>>
    >>> control_map = load_control_map({"dofs": {"go": "keyboard.hold.letter.w"}})
    >>> controls = resolve(control_map, keyboard_capabilities())
    >>> keys = KeyboardTarget()
    >>> bus = ControlBus(controls, targets=[keys])
    >>> keys.armed                       # nothing is sent until it is armed
    False
    """

    __slots__ = ("_armed", "_backend", "_bound", "_down", "_factory")

    def __init__(self, backend: Any = None, *, armed: bool = False) -> None:
        self._backend = backend
        self._factory = _PynputBackend if backend is None else None
        self._armed = bool(armed)
        #: alias -> (mode, spec), for the aliases routed to this target.
        self._bound: dict[str, tuple[str, tuple[str, str]]] = {}
        #: Which aliases are holding a key down, so they can all be let go at once.
        self._down: set[str] = set()

    # --- what this target can do -------------------------------------------------

    def capabilities(self) -> tuple[Capability, ...]:
        """The manifest, so this can be handed to an editor like a renderer's client."""
        return keyboard_capabilities()

    @property
    def claims(self) -> frozenset[str]:
        """Which aliases this target drives, for `ControlBus`'s coverage check."""
        return frozenset(self._bound)

    @property
    def armed(self) -> bool:
        """Whether key events actually leave this process."""
        return self._armed

    @staticmethod
    def request_accessibility() -> str:
        """Ask macOS for the permission this target needs. See `request_accessibility`."""
        return request_accessibility()

    @property
    def arm_refusal(self) -> str:
        """Why `arm` would refuse right now, or "" when it would work.

        Asked *before* the click, so the switch is not a trap. Cheap enough to read every
        frame — one `AXIsProcessTrusted` and one module lookup.
        """
        refusal = _accessibility_refusal()
        if refusal:
            return refusal
        if self._backend is None and importlib.util.find_spec("pynput") is None:
            return "cannot press keys: install the 'keyboard' extra (`uv sync --extra keyboard`)."
        return ""

    def arm(self) -> None:
        """Start sending key events, building the backend if it does not exist yet.

        Raises
        ------
        RuntimeError
            When the backend cannot be built (normally `pynput` not installed), or when
            macOS has not granted Accessibility permission. Raised rather than logged, so
            no target reports itself armed and then presses nothing.
        """
        refusal = _accessibility_refusal()
        if refusal:
            raise RuntimeError(refusal)
        if self._backend is None and self._factory is not None:
            try:
                self._backend = self._factory()
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                raise RuntimeError(
                    "cannot press keys: install the 'keyboard' extra "
                    "(`uv sync --extra keyboard`). On macOS this process also needs "
                    "Accessibility permission — System Settings > Privacy & Security > "
                    "Accessibility — without which key events are accepted and do nothing."
                ) from exc
        self._armed = True
        log.warning("keyboard target ARMED — controls now type into the focused window")

    def disarm(self) -> None:
        """Stop sending, letting go of anything still held. Idempotent.

        Releases first: disarming mid-gesture would otherwise leave a key down with nothing
        left to lift it.
        """
        self._release_all()
        if self._armed:
            log.info("keyboard target disarmed")
        self._armed = False

    # --- the Target protocol ------------------------------------------------------

    def bind(self, controls: ControlSet) -> None:
        """Accept the keyboard aliases in `controls`, and refuse a key that is not real.

        Raises
        ------
        ValueError
            When an alias routes to a `keyboard.` address this target does not export.
            Refused here, on the main thread, rather than discovered as a key that never
            fires.
        """
        self._release_all()
        self._bound = {}
        for alias, refs in getattr(controls, "routes", {}).items():
            for ref in refs:
                address = getattr(ref, "address", "")
                if not address.startswith(f"{NAMESPACE}."):
                    continue  # another target's control; not this one's business
                spec = _spec_for(address)
                if spec is None:
                    raise ValueError(
                        f"{alias!r} points at {address!r}, which is not a key this target "
                        f"presses. The shape is "
                        f"'{NAMESPACE}.<{'|'.join(MODES)}>.<category>.<key>', for example "
                        f"'{NAMESPACE}.hold.letter.a'."
                    )
                if alias in self._bound:
                    raise ValueError(
                        f"{alias!r} is routed to more than one key. One control drives one "
                        f"key — map a second alias, or fan out to two keys from two."
                    )
                unpressable = _unpressable(spec)
                if unpressable:
                    # The manifest is the same everywhere so a map stays portable, but the
                    # *keys* are not: `insert` exists on Windows and Linux and is not a
                    # macOS key. Refused here rather than on the predict thread.
                    raise ValueError(
                        f"{alias!r} points at {address!r}, which this platform has no key "
                        f"for ({unpressable}). It is advertised because the manifest is the "
                        f"same everywhere; pick a key that exists here."
                    )
                self._bound[alias] = (address.split(".")[1], spec)
        log.info("keyboard target bound %d control(s)", len(self._bound))

    def send(self, values: Mapping[str, float | str], changed: Mapping[str, str]) -> None:
        """Act on the state changes this tick. Never raises.

        Only `changed` is read: a level would re-press a held key every tick. `ControlBus`
        already computes the edge, including the debounce.
        """
        if not self._armed:
            return
        for alias, state in changed.items():
            bound = self._bound.get(alias)
            if bound is None:
                continue
            mode, spec = bound
            try:
                if state == _DOWN:
                    self._backend.press(spec)
                    if mode == "tap":
                        self._backend.release(spec)
                    else:
                        self._down.add(alias)
                elif alias in self._down:
                    self._backend.release(spec)
                    self._down.discard(alias)
            except Exception as exc:  # noqa: BLE001 - the predict thread must survive
                log.error("keyboard %r failed, disarming: %s", alias, exc)
                self._armed = False
                self._down.discard(alias)

    def stop(self) -> None:
        """Let go of every held key and disarm. Idempotent."""
        self.disarm()

    # --- internals ----------------------------------------------------------------

    def _release_all(self) -> None:
        """Lift every key this target is holding, whatever else is going on."""
        if self._backend is None:
            self._down.clear()
            return
        for alias in list(self._down):
            spec = self._bound.get(alias)
            if spec is not None:
                try:
                    self._backend.release(spec[1])
                except Exception as exc:  # noqa: BLE001 - teardown reports, never raises
                    log.error("could not release the key for %r: %s", alias, exc)
        self._down.clear()


__all__ = ["ACTIVATION_THRESHOLD", "MODES", "NAMESPACE", "KeyboardTarget", "keyboard_capabilities"]
