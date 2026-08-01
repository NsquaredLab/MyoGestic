"""The smallest thing MyoGestic can drive.

Serve one RPC, read one stream. That is the whole contract — everything else in
`myogestic_vhi.proto` is an extra a renderer may offer and a client may use.

Run it, then point any control map at `vhi.prediction.*`:

    uv run --extra grpc python examples/synthetic/reference_renderer.py
"""

from __future__ import annotations

import threading
from concurrent import futures

import grpc
import numpy as np
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2
from myogestic.vhi._proto import myogestic_vhi_pb2_grpc as pb2_grpc

#: What this renderer exports. The address is yours to name; its first segment is the
#: namespace, so `vhi.*` here means a map written for a Virtual Hand drives this too.
#: `channel` is the position on the wire — a channel *is* an address, and this table is
#: the only place that says so. `ControlCapability.channel` is field 11 and
#: `stream_name` field 10; both are required for a client to place a value.
#:
#: `lo=-1.0, hi=1.0` is the range; the sign is a separate, settled convention this
#: project does not let a renderer redefine: `+1` is always the direction the address
#: name denotes, so `vhi.prediction.index` at `+1` is a flexed index, and a fist across
#: this table is `[1, -1, 1, 1, 1, 1, 0, 0, 0]` (the last three channels are never
#: claimed below, so they stay at rest). `POSE_WIDTH` is the *stream's* channel count —
#: at least one more than the highest channel claimed here, not the number of
#: addresses; this renderer copies VHI's own 9-channel layout so `virtual_hand()` can
#: point straight at it, unmodified, the way `tests/test_reference_renderer.py` does.
ADDRESSES = [
    ("vhi.prediction.thumb.flexion", 0),
    ("vhi.prediction.thumb.abduction", 1),
    ("vhi.prediction.index", 2),
    ("vhi.prediction.middle", 3),
    ("vhi.prediction.ring", 4),
    ("vhi.prediction.little", 5),
]

POSE_WIDTH = 9


class ReferenceRenderer(pb2_grpc.VhiControlServicer):
    """A renderer in eighty lines. Holds the last pose it was sent."""

    #: `stream` is load-bearing, not decoration: a client resolves a manifest against one
    #: stream at a time and looks for `MyoGestic_Output` (or `MyoGestic_ControlPose` for a
    #: control hand). A capability naming anything else is dropped from the negotiation and
    #: the client refuses the map without saying why. Name yours one of those two, or leave
    #: `stream_name` empty.
    def __init__(self, port: int = 50051, stream: str = "MyoGestic_Output") -> None:
        self.pose = np.zeros(POSE_WIDTH, dtype=np.float32)
        self._port = port
        self._stream = stream
        self._server: grpc.Server | None = None
        self._stop = threading.Event()

    # --- the one required RPC -------------------------------------------------

    def GetControlManifest(self, request, context):
        """What this renderer exports. The only thing a client must be able to ask."""
        manifest = pb2.ControlManifest(target_name="reference", vocabulary_version="1")
        for address, channel in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(
                    address=address,
                    kind=pb2.CONTINUOUS,
                    lo=-1.0,
                    hi=1.0,
                    rest=0.0,
                    channel=channel,
                    stream_name=self._stream,
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
        """Read the pose stream. Positional: a channel is an address."""
        inlet = None
        while not self._stop.is_set():
            # Resolving is inside the try too: the outlet can vanish between the resolve
            # and the open, and `open_stream` raises when it does. Outside, that ordinary
            # race would kill this thread while the gRPC server kept answering the
            # manifest — a client would bind successfully against a renderer that never
            # reads another sample, which is the one failure this project refuses to ship.
            try:
                if inlet is None:
                    found = [s for s in resolve_streams(timeout=1.0) if s.name == self._stream]
                    if not found:
                        continue
                    inlet = StreamInlet(found[0])
                    inlet.open_stream()
                    continue
                chunk, _ = inlet.pull_chunk(timeout=0.5)
                if chunk is not None and len(chunk):
                    self.pose = np.asarray(chunk[-1], dtype=np.float32)
            except Exception as exc:
                print(f"reference renderer: lost the inlet ({type(exc).__name__}: {exc}), re-resolving")
                if inlet is not None:
                    inlet.close_stream()
                inlet = None


if __name__ == "__main__":
    renderer = ReferenceRenderer()
    renderer.serve()
    print("reference renderer on 127.0.0.1:50051 — Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        renderer.stop()
