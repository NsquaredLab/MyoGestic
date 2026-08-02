"""Drive a renderer — any separate application that displays or actuates control values.

A renderer is reached over **gRPC** for its manifest and discrete state, and over **LSL**
for continuous per-DOF values. Nothing here knows what the renderer renders: a hand, a
gripper, a cursor and a robot arm are all the same three objects.

- `InterfaceSpec` — where the renderer is: its process, its endpoint, how to build a
  stream for one of its controls.
- `RendererTarget` — the `myogestic.controls.Target`. Reads the manifest, publishes one
  stream per address it drives, forwards discrete edges over gRPC.
- `RendererClient` / `RecordingClient` — the gRPC clients for the control service and for
  the recording-session RPCs.

The contract itself is `_proto/renderer_control.proto`, authored in the
Virtual-Hand-Interface repo and vendored here byte-for-byte.

`myogestic.vhi` is one consumer of all this — the Virtual Hand's own numbers, install
gate and recorded pose layout, and nothing generic.
"""

from myogestic.renderer.interfaces import InterfaceSpec
from myogestic.renderer.target import PoseSink, RendererTarget

#: The two gRPC clients are listed here but resolved lazily by ``__getattr__`` below.
__all__ = [
    "InterfaceSpec",
    "PoseSink",
    "RecordingClient",
    "RendererClient",
    "RendererTarget",
]


def __getattr__(name: str):
    """Expose the gRPC clients without importing grpc on a plain install.

    A module-level import would pull in ``grpc`` for everyone, including installs with
    no ``[grpc]`` extra that only ever call `myogestic.vhi.virtual_hand().launcher()`.
    """
    if name == "RendererClient":
        from myogestic.renderer._control import RendererClient

        return RendererClient
    if name == "RecordingClient":
        from myogestic.renderer._recording import RecordingClient

        return RecordingClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
