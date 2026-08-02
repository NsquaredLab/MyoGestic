"""A prosthetic hand on a serial port: three methods and a write.

    uv run python examples/synthetic/servo_hand.py

Runs with no hardware. Two things to notice:

**Five addresses, six servos.** `hand.thumb` drives two of them on different transfer
functions, because a real thumb opposes as it flexes. The coupling lives here, not in the
control map: an address exists so the map need not know this hand's linkage.

**Wire order is this file's.** `frame` iterates `SERVOS` and looks each fraction up by name,
so reordering a TOML cannot reorder somebody's fingers.

The bus already clamped NaN, filled missing controls, held the declared range and delivered
rest before teardown - see `myogestic.controls.ControlBus`.
"""

from __future__ import annotations

from myogestic.controls import (
    Capability,
    ControlBus,
    ControlSet,
    load_control_map,
    resolve,
)

#: One address per finger. One-way (`lo=0.0`): a servo hand cannot hyperextend, and
#: declaring a direction it does not have would clamp silently on the predict thread.
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

#: How far into the thumb's travel opposition completes; past this it only flexes.
OPPOSITION_SPAN = 0.6


class ServoHand:
    """Drive six servos over a serial port from a control map.

    Parameters
    ----------
    port
        Anything with ``write(bytes)`` and ``close()``::

            ServoHand(serial.Serial("/dev/ttyACM0", 115200))

        ``None`` computes frames and sends nothing, so this file runs without hardware.
    """

    def __init__(self, port=None) -> None:
        self._port = port
        self._routed: tuple[tuple[str, str, float], ...] = ()

    def capabilities(self) -> tuple[Capability, ...]:
        """What a control map may name."""
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
        """Which aliases this hand drives."""
        return frozenset(alias for _, alias, _ in self._routed)

    def send(self, values, changed) -> None:
        """Actuate one tick. Never raises: the bus guarantees finite, in-range values."""
        levels = {
            # Weight first, then this hand's range: a gain must not exceed what we accept.
            address: min(1.0, max(0.0, weight * float(values.get(alias, 0.0))))
            for address, alias, weight in self._routed
        }
        if self._port is not None:
            self._port.write(self.frame(levels))

    def stop(self) -> None:
        """Open the hand, then close the port. Idempotent.

        The bus delivers rest before calling this; repeated because a target can also be
        stopped directly, and a missed open-hand frame leaves a hand closed.
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
        """The bytes for one pose. Pure, so a test can read it without a port.

        An address nobody drives is held open: a servo has no third state.
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

    # Half a thumb is *most* of the rotator's travel, not half of it: the coupling.
    bus.push({"thumb": 0.5, "index": 0.0, "close": 0.0})
    assert port.lines[-1] == "53,92,5,5,5,5", port.lines[-1]

    # Out of range never reaches a servo: the bus clipped to the declared domain first.
    bus.push({"thumb": 5.0, "index": -3.0, "close": 0.0})
    assert port.lines[-1] == "96,110,5,5,5,5", port.lines[-1]

    bus.stop()  # rest, then teardown, in that order
    assert port.lines[-2] == "10,0,5,5,5,5", port.lines[-2]
    assert port.lines[-1] == "<closed>", "the port was left open"

    print("\n".join(port.lines))
