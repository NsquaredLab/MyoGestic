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
                    description=f"{address}, signed and normalised",
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
            if inlet is None:
                found = [s for s in resolve_streams(timeout=1.0) if s.name == self._stream]
                if not found:
                    continue
                inlet = StreamInlet(found[0])
                inlet.open_stream()
                continue
            try:
                chunk, _ = inlet.pull_chunk(timeout=0.5)
                if chunk is not None and len(chunk):
                    self.pose = np.asarray(chunk[-1], dtype=np.float32)
            except Exception:
                inlet = None


if __name__ == "__main__":
    renderer = ReferenceRenderer()
    renderer.serve()
    print("reference renderer on 127.0.0.1:50051 — Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        renderer.stop()
