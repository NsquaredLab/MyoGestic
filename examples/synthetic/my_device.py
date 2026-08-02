"""Copy this file and drive your own device. Three lines to change, marked 1, 2, 3.

    uv run python examples/synthetic/my_device.py

It runs as-is, with no hardware: `send` prints what it would have sent. Replace that print
with your device's call and it is finished. Everything else here is the whole contract.

`examples/synthetic/servo_hand.py` is the same shape carrying a real mechanism - six servos,
a coupled thumb, a wire format - if you want to see where this goes.
"""

from __future__ import annotations

from myogestic.controls import Capability, ControlBus, ControlSet, load_control_map, resolve

# ── 1. Name your controls ─────────────────────────────────────────────────────────────
# Two or more dotted, lowercase segments. The first segment is your namespace, so these
# cannot collide with `vhi.*` or `keyboard.*` in the same map. Name a *direction*, so `+1`
# has a meaning: `grip.close`, not `grip.motor`.
ADDRESSES = ("mydevice.grip", "mydevice.wrist.pronation")


class MyDevice:
    """A target: three methods, and a list of what it can drive."""

    def __init__(self, port=None) -> None:
        self._port = port
        self._routed: tuple[tuple[str, str, float], ...] = ()

    def capabilities(self) -> tuple[Capability, ...]:
        """What a control map is allowed to name.

        Signed and normalised: `-1` to `+1`, resting at `0`, where `+1` means the direction
        the address name says. Use `lo=0.0` for a control that only moves one way.
        """
        return tuple(
            Capability(address=a, kind="continuous", lo=-1.0, hi=1.0, rest=0.0)
            for a in ADDRESSES
        )

    def bind(self, controls: ControlSet) -> None:
        """Accept a map, or refuse it here while a human is reading the traceback."""
        self._routed = tuple(
            (ref.address, alias, ref.weight)
            for alias, refs in controls.routes.items()
            for ref in refs
            if ref.address in ADDRESSES
        )
        if not self._routed:
            raise ValueError(f"this map reaches none of {ADDRESSES}")

    @property
    def claims(self) -> frozenset[str]:
        """Which aliases you drive, so the bus can spot one nothing drives."""
        return frozenset(alias for _, alias, _ in self._routed)

    def send(self, values, changed) -> None:
        """One tick. Must not raise: the bus already made every value finite and in range."""
        for address, alias, weight in self._routed:
            # Weight first, then your own range. The bus does not apply `weight` for you.
            value = min(1.0, max(-1.0, weight * float(values.get(alias, 0.0))))

            # ── 2. Drive your hardware ────────────────────────────────────────────────
            # self._port.write(...)   /   self._motors.set(address, value)   /   ...
            print(f"  {address:26} {value:+.2f}")

    def stop(self) -> None:
        """Rest the device and release it. Must be idempotent.

        The bus delivers a neutral frame before calling this, so by now every value is at
        rest. What is left is letting go of the hardware.
        """
        # ── 3. Release your hardware ──────────────────────────────────────────────────
        # self._port.close()
        print("  stopped")


if __name__ == "__main__":

    class _Recording(MyDevice):
        """Keeps what `send` produced, so the assertions below can check it."""

        sent: list[dict[str, float]] = []

        def send(self, values, changed) -> None:
            super().send(values, changed)
            self.sent.append(
                {
                    address: min(1.0, max(-1.0, weight * float(values.get(alias, 0.0))))
                    for address, alias, weight in self._routed
                }
            )

    device = _Recording()

    # Your model's output names on the left, your addresses on the right. In a real app
    # this is a TOML file read with `load_control_map(tomllib.load(f))`.
    control_map = load_control_map(
        {"dofs": {"close": "mydevice.grip", "twist": "mydevice.wrist.pronation"}}
    )
    bus = ControlBus(resolve(control_map, device.capabilities()), targets=[device], hz=32)

    print("a frame, as @pipeline.predict would push it:")
    bus.push({"close": 0.8, "twist": -0.4})
    assert device.sent[-1] == {"mydevice.grip": 0.8, "mydevice.wrist.pronation": -0.4}

    print("out of range and NaN, both handled before you see them:")
    bus.push({"close": 5.0, "twist": float("nan")})
    assert device.sent[-1] == {"mydevice.grip": 1.0, "mydevice.wrist.pronation": 0.0}

    print("teardown, which rests every control first:")
    bus.stop()
    assert device.sent[-1] == {"mydevice.grip": 0.0, "mydevice.wrist.pronation": 0.0}
