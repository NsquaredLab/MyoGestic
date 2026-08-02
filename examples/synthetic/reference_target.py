"""The smallest thing MyoGestic can drive.

Serve one RPC, read your streams. That is the whole contract — everything else in
`remote_control.proto` is an extra a target may offer and a client may use.

Run it, then point any control map at `vhi.prediction.*`:

    uv run --extra grpc python examples/synthetic/reference_target.py
"""

from __future__ import annotations

import threading
from concurrent import futures
from contextlib import suppress

import grpc
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.remote._proto import remote_control_pb2 as pb2
from myogestic.remote._proto import remote_control_pb2_grpc as pb2_grpc

#: What this target exports. The address is yours to name; its first segment is the
#: namespace, so `vhi.*` here means a map written for a Virtual Hand drives this too.
#:
#: **One stream per address, named after the address, one channel wide.** That is the
#: whole transport, and it is not one option among several: there is no width to declare,
#: no positional layout for the two ends to agree on, and nothing in the manifest that
#: describes a wire. Each address is applied the moment its sample arrives rather than
#: when a whole pose does — one nobody drives just keeps its last value. A client reads
#: the address and publishes under exactly that name.
#:
#: `lo=-1.0, hi=1.0` is the range; the sign is a separate, settled convention this
#: project does not let a target redefine: `+1` is always the direction the address
#: name denotes, so `vhi.prediction.index` at `+1` is a flexed index, and a fist across
#: the nine addresses of a VHI-shaped hand is `[1, -1, 1, 1, 1, 1, 0, 0, 0]`.
ADDRESSES = [
    "vhi.prediction.thumb.flexion",
    "vhi.prediction.thumb.abduction",
    "vhi.prediction.index",
    "vhi.prediction.middle",
    "vhi.prediction.ring",
    "vhi.prediction.little",
]


class ReferenceTarget(pb2_grpc.RemoteControlServicer):
    """A remote target in eighty lines. Holds the last value it was sent, per address."""

    def __init__(self, port: int = 50051) -> None:
        #: The whole driven state, by address rather than by channel. Nothing waits for
        #: a full pose here, because nothing on the wire delivers one.
        self.pose = dict.fromkeys(ADDRESSES, 0.0)
        self._port = port
        self._server: grpc.Server | None = None
        self._stop = threading.Event()

    # --- the one required RPC -------------------------------------------------

    def GetControlManifest(self, request, context):
        """What this target exports. The only thing a client must be able to ask.

        The address is load-bearing twice over: it is what a map points at, and it is
        the name of the one-channel LSL stream both `_read` and the client use. There is
        no separate transport field to keep in step with it, which is the point — there
        is nothing here that can disagree with anything.

        `vocabulary_version` is the compatibility gate, and it is not decoration either:
        a client refuses a target reporting less than the vocabulary it speaks, by
        name, at bind. Report ``"2"`` — one stream per DOF — or a current MyoGestic
        refuses this target instead of driving it.
        """
        manifest = pb2.ControlManifest(target_name="reference", vocabulary_version="2")
        for address in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(
                    address=address,
                    kind=pb2.CONTINUOUS,
                    lo=-1.0,
                    hi=1.0,
                    rest=0.0,
                )
            )
        return manifest

    # --- lifecycle ------------------------------------------------------------

    def serve(self) -> None:
        """Start the gRPC server and the inlet reader."""
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        pb2_grpc.add_RemoteControlServicer_to_server(self, self._server)
        self._server.add_insecure_port(f"127.0.0.1:{self._port}")
        self._server.start()
        threading.Thread(target=self._read, name="reference-inlet", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.stop(grace=None)

    def _read(self) -> None:
        """Read every stream and apply each value as it arrives.

        **One thread, not one per stream.** `resolve_streams` is a multicast sweep of the
        whole network; several running at once cost far more than they buy, and one sweep
        already answers for every stream still missing an inlet.

        One channel per stream, so there is nothing to unpack: `chunk[-1][0]` is the
        whole sample. A stream that turns up wider than that is not this contract and a
        target should say so rather than read element zero of something unexpected.
        """
        inlets: dict[str, StreamInlet] = {}
        while not self._stop.is_set():
            # Resolving is inside the try too: an outlet can vanish between the resolve
            # and the open, and `open_stream` raises when it does. Outside, that ordinary
            # race would kill this thread while the gRPC server kept answering the
            # manifest — a client would bind successfully against a target that never
            # reads another sample, which is the one failure this project refuses to ship.
            try:
                missing = [a for a in ADDRESSES if a not in inlets]
                if missing:
                    found = {s.name: s for s in resolve_streams(timeout=1.0)}
                    for address in missing:
                        info = found.get(address)
                        if info is None:
                            continue
                        if info.n_channels != 1:
                            # Refused, not tolerated. An inlet is found by its address's
                            # *stream name*, so a wide stream can only ever reach the one
                            # address it is named for — it cannot corrupt the others. What
                            # reading element zero of it would do is quieter and no better:
                            # element zero of somebody's nine-channel pose frame is a
                            # different DOF's value entirely, and this address would track
                            # it all session — plausible, in range, and completely wrong.
                            print(
                                f"reference target: {address} is published "
                                f"{info.n_channels} channels wide, and this contract is "
                                f"one address per stream, one channel. Not opening it."
                            )
                            continue
                        inlets[address] = StreamInlet(info)
                        inlets[address].open_stream()
                for address, inlet in inlets.items():
                    chunk, _ = inlet.pull_chunk(timeout=0.0)
                    if chunk is not None and len(chunk):
                        self.pose[address] = float(chunk[-1][0])
                self._stop.wait(0.005)
            except Exception as exc:
                print(f"reference target: lost an inlet ({type(exc).__name__}: {exc}), re-resolving")
                for inlet in inlets.values():
                    # Suppressed: closing a *broken* inlet is exactly the case that raises,
                    # and a raise here would kill the thread this handler exists to keep
                    # alive. There is nothing left to do about it either way.
                    with suppress(Exception):
                        inlet.close_stream()
                # All of them, not just the one that failed: re-resolving a healthy stream
                # costs one sweep, and telling which inlet raised costs a try per inlet
                # per tick.
                inlets.clear()
                # `resolve_streams` can raise too, and with no inlet to lose that is a
                # tight loop printing once per iteration. Back off before retrying.
                self._stop.wait(1.0)


if __name__ == "__main__":
    target = ReferenceTarget()
    target.serve()
    print("reference target on 127.0.0.1:50051 — Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        target.stop()
