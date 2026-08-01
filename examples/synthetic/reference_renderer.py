"""The smallest thing MyoGestic can drive.

Serve one RPC, read your streams. That is the whole contract — everything else in
`myogestic_vhi.proto` is an extra a renderer may offer and a client may use.

Run it, then point any control map at `vhi.prediction.*`:

    uv run --extra grpc python examples/synthetic/reference_renderer.py
"""

from __future__ import annotations

import threading
from concurrent import futures
from contextlib import suppress

import grpc
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2
from myogestic.vhi._proto import myogestic_vhi_pb2_grpc as pb2_grpc

#: What this renderer exports. The address is yours to name; its first segment is the
#: namespace, so `vhi.*` here means a map written for a Virtual Hand drives this too.
#:
#: **One stream per address, named after the address, one channel wide.** That is what
#: the Virtual Hand publishes and it is the simplest thing to write: no width to declare,
#: no positional layout for the two ends to agree on, and each address is applied the
#: moment its sample arrives rather than when a whole pose does — one nobody drives just
#: keeps its last value. `ControlCapability.stream_name` is field 10 and `channel` field
#: 11; both are still required, `channel` is simply always 0 here.
#:
#: One stream carrying *several* addresses on distinct channels is equally legal and
#: sometimes what you want — see `_read`. MyoGestic needs telling neither way round: it
#: groups a map's addresses by whatever `stream_name` you report and builds one target
#: per group, so a shared stream gets one and nine separate ones get nine.
#:
#: `lo=-1.0, hi=1.0` is the range; the sign is a separate, settled convention this
#: project does not let a renderer redefine: `+1` is always the direction the address
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


class ReferenceRenderer(pb2_grpc.VhiControlServicer):
    """A renderer in eighty lines. Holds the last value it was sent, per address."""

    def __init__(self, port: int = 50051) -> None:
        #: The whole rendered state, by address rather than by channel. Nothing waits for
        #: a full pose here, because nothing on the wire delivers one.
        self.pose = dict.fromkeys(ADDRESSES, 0.0)
        self._port = port
        self._server: grpc.Server | None = None
        self._stop = threading.Event()

    # --- the one required RPC -------------------------------------------------

    def GetControlManifest(self, request, context):
        """What this renderer exports. The only thing a client must be able to ask.

        `stream_name` is load-bearing, not decoration: it names both the LSL stream
        `_read` reads and the stream a client publishes under, and a client resolves a
        manifest one stream at a time. Nothing has to be told to agree with it — this
        reply is the *only* place a stream name is decided. Report it empty and the
        client publishes an outlet it built itself, since there is then no name to build
        one from.
        """
        manifest = pb2.ControlManifest(target_name="reference", vocabulary_version="1")
        for address in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(
                    address=address,
                    kind=pb2.CONTINUOUS,
                    lo=-1.0,
                    hi=1.0,
                    rest=0.0,
                    channel=0,
                    stream_name=address,
                )
            )
        return manifest

    # --- lifecycle ------------------------------------------------------------

    def serve(self) -> None:
        """Start the gRPC server and the inlet reader."""
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        pb2_grpc.add_VhiControlServicer_to_server(self, self._server)
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

        One channel per stream, so there is nothing to unpack. Carrying several addresses
        on one stream instead means opening one inlet and reading `chunk[-1][channel]`
        per address off it — the same loop with a channel table beside it.
        """
        inlets: dict[str, StreamInlet] = {}
        while not self._stop.is_set():
            # Resolving is inside the try too: an outlet can vanish between the resolve
            # and the open, and `open_stream` raises when it does. Outside, that ordinary
            # race would kill this thread while the gRPC server kept answering the
            # manifest — a client would bind successfully against a renderer that never
            # reads another sample, which is the one failure this project refuses to ship.
            try:
                missing = [a for a in ADDRESSES if a not in inlets]
                if missing:
                    found = {s.name: s for s in resolve_streams(timeout=1.0)}
                    for address in missing:
                        info = found.get(address)
                        if info is not None:
                            inlets[address] = StreamInlet(info)
                            inlets[address].open_stream()
                for address, inlet in inlets.items():
                    chunk, _ = inlet.pull_chunk(timeout=0.0)
                    if chunk is not None and len(chunk):
                        self.pose[address] = float(chunk[-1][0])
                self._stop.wait(0.005)
            except Exception as exc:
                print(f"reference renderer: lost an inlet ({type(exc).__name__}: {exc}), re-resolving")
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
    renderer = ReferenceRenderer()
    renderer.serve()
    print("reference renderer on 127.0.0.1:50051 — Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        renderer.stop()
