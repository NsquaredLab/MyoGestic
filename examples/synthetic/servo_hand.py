"""A prosthetic hand on a serial port: the shape most devices actually have.

Three methods and a write to a port. No gRPC, no LSL, no second process — those are for
a target that is *already its own program*. A device you can `import` and call is this.

Run it with no hardware at all:

    uv run python examples/synthetic/servo_hand.py

Two things are worth reading for rather than skimming past:

**Five addresses, six servos.** `hand.thumb` drives two of them, on different transfer
functions, because a real thumb opposes as it flexes. That coupling belongs *here* and not
in the control map: a fan-out sends one value to several addresses, so ganging two servos
through the map would force whoever writes it to know this hand's linkage — which is the
one thing an address exists to hide.

**Wire order is this file's, never the map's.** `send` builds its frame by iterating
`SERVOS`, so reordering a TOML for readability cannot reorder somebody's fingers.

What this file does *not* do, because the bus already did it: clamp NaN, fill a missing
control, hold the declared range, apply a dead zone, debounce a state, or deliver rest
before teardown. See `myogestic.controls.ControlBus`.
"""

from __future__ import annotations

from myogestic.controls import (
    Capability,
    ControlBus,
    ControlSet,
    load_control_map,
    resolve,
)

#: What this hand exports. One address per finger, because a finger is what a person drives.
#:
#: One-way: a servo hand flexes from open and cannot hyperextend, so `lo=0.0` rather than
#: the signed default. Declaring a direction the servos do not have would move the failure
#: from resolve time, where a human reads it, to a silent clamp on the predict thread.
ADDRESSES = ("hand.thumb", "hand.index", "hand.middle", "hand.ring", "hand.little")

#: The firmware's channel order, and each servo's travel in degrees, `(open, closed)`.
#: **This dict's order is the wire order.**
SERVOS = {
    "thumb_flex": (10, 96),
    "thumb_rot": (0, 110),
    "index": (5, 100),
    "middle": (5, 100),
    "ring": (5, 100),
    "little": (5, 100),
}

#: How far into the thumb's travel opposition completes; past this it only flexes. A fact
#: about the mechanism, which is why it lives here and not in anybody's control map.
OPPOSITION_SPAN = 0.6


class ServoHand:
    """Drive six servos over a serial port from a control map.

    Parameters
    ----------
    port
        Anything with ``write(bytes)`` and ``close()``. The real thing is one line::

            ServoHand(serial.Serial("/dev/ttyACM0", 115200))

        Left as ``None`` the hand computes its frames and sends nothing, which is what
        makes this file runnable with no hardware attached.
    """

    def __init__(self, port=None) -> None:
        self._port = port
        self._routed: tuple[tuple[str, str, float], ...] = ()

    def capabilities(self) -> tuple[Capability, ...]:
        """What a control map may name. Answerable immediately: nothing has to be running."""
        return tuple(
            Capability(
                address=address,
                kind="continuous",
                lo=0.0,
                hi=1.0,
                rest=0.0,
                description=f"{address.rsplit('.', 1)[-1]} curls from open (0) to closed (1)",
            )
            for address in ADDRESSES
        )

    def bind(self, controls: ControlSet) -> None:
        """Accept a configuration, or refuse it while a human is still reading.

        Raises
        ------
        ValueError
            Nothing in the map reaches this hand.
        """
        self._routed = tuple(
            (ref.address, alias, ref.weight)
            for alias, refs in controls.routes.items()
            for ref in refs
            if ref.address in ADDRESSES
        )
        if not self._routed:
            raise ValueError(
                f"nothing in this map reaches this hand. It drives {', '.join(ADDRESSES)} — "
                f"check the namespace on the right-hand side of your [dofs] table."
            )

    @property
    def claims(self) -> frozenset[str]:
        """Which aliases this hand drives, so the bus can spot one that nothing drives."""
        return frozenset(alias for _, alias, _ in self._routed)

    def send(self, values, changed) -> None:
        """Actuate one tick. Never raises: the bus guarantees finite, in-range values."""
        levels = {
            # Weight first, then this hand's own range. A gain may scale a value but must
            # not push one past what `capabilities` said this hand accepts.
            address: min(1.0, max(0.0, weight * float(values.get(alias, 0.0))))
            for address, alias, weight in self._routed
        }
        if self._port is not None:
            self._port.write(self.frame(levels))

    def stop(self) -> None:
        """Open the hand, then close the port. Idempotent.

        `ControlBus.stop` already delivered the neutral frame before calling this. Repeated
        anyway, because a target can be stopped directly too, and one extra open-hand frame
        costs a few bytes on a UART while a missed one leaves a hand clenched on somebody.
        """
        port, self._port = self._port, None
        if port is None:
            return
        try:
            port.write(self.frame({}))
        finally:
            port.close()

    @staticmethod
    def frame(levels) -> bytes:
        """The bytes for one pose. Pure, so it can be read without a port.

        An address nobody drives is held open rather than left floating: a servo has no
        third state. (A remote target is the opposite — there each address arrives on a
        stream of its own, so one that gets no sample keeps its last value.)
        """
        thumb = levels.get("hand.thumb", 0.0)
        fraction = {
            "thumb_flex": thumb,
            "thumb_rot": min(1.0, thumb / OPPOSITION_SPAN),
            "index": levels.get("hand.index", 0.0),
            "middle": levels.get("hand.middle", 0.0),
            "ring": levels.get("hand.ring", 0.0),
            "little": levels.get("hand.little", 0.0),
        }
        angles = (
            round(lo + fraction[servo] * (hi - lo)) for servo, (lo, hi) in SERVOS.items()
        )
        return (",".join(str(a) for a in angles) + "\n").encode()


if __name__ == "__main__":

    class _Log:
        """Stands in for `serial.Serial`, keeping what would have gone down the wire."""

        def __init__(self) -> None:
            self.lines: list[str] = []

        def write(self, payload: bytes) -> None:
            self.lines.append(payload.decode().strip())

        def close(self) -> None:
            self.lines.append("<closed>")

    port = _Log()
    hand = ServoHand(port)

    # The left side is yours; the right side is what the hand declared above.
    control_map = load_control_map(
        {
            "dofs": {
                "thumb": "hand.thumb",
                "index": "hand.index",
                "close": ["hand.middle", "hand.ring", "hand.little"],
            }
        }
    )
    bus = ControlBus(resolve(control_map, hand.capabilities()), targets=[hand], hz=32)

    bus.push({"thumb": 0.0, "index": 0.0, "close": 0.0})
    assert port.lines[-1] == "10,0,5,5,5,5", port.lines[-1]

    bus.push({"thumb": 1.0, "index": 1.0, "close": 1.0})
    assert port.lines[-1] == "96,110,100,100,100,100", port.lines[-1]

    # Half a thumb is *most* of the rotator's travel, not half of it. That is the coupling,
    # and it is why `hand.thumb` is one address rather than two.
    bus.push({"thumb": 0.5, "index": 0.0, "close": 0.0})
    assert port.lines[-1] == "53,92,5,5,5,5", port.lines[-1]

    # Out of range never reaches a servo: the bus clipped to the declared domain first.
    bus.push({"thumb": 5.0, "index": -3.0, "close": 0.0})
    assert port.lines[-1] == "96,110,5,5,5,5", port.lines[-1]

    bus.stop()  # rest, then teardown, in that order
    assert port.lines[-2] == "10,0,5,5,5,5", port.lines[-2]
    assert port.lines[-1] == "<closed>", "the port was left open"

    print("\n".join(port.lines))
