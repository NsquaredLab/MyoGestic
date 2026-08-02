"""Drive a remote target — a separate application that displays or actuates control values.

A remote target is reached over **gRPC** for its manifest and discrete state, and over
**LSL** for continuous per-DOF values. Nothing here knows what it drives: a hand, a
gripper, a cursor and a robot arm are all the same three objects.

For a target whose code runs in this process — a serial prosthesis, a cursor, a library
you can import — none of this applies: write `myogestic.controls.Target`'s three methods
instead, and skip both wires.

- `InterfaceSpec` — where the target is: its process, its endpoint, how to build a
  stream for one of its controls.
- `RemoteTarget` — the `myogestic.controls.Target`. Reads the manifest, publishes one
  stream per address it drives, forwards discrete edges over gRPC.
- `RemoteClient` / `RecordingClient` — the gRPC clients for the control service and for
  the recording-session RPCs.

The contract itself is `_proto/remote_control.proto`, authored in the
Virtual-Hand-Interface repo and vendored here byte-for-byte.

`myogestic.vhi` is one consumer of all this — the Virtual Hand's own numbers, install
gate and recorded pose layout, and nothing generic.
"""

from myogestic.remote.interfaces import InterfaceSpec
from myogestic.remote.target import RemoteTarget

#: The two gRPC clients are listed here but resolved lazily by ``__getattr__`` below.
__all__ = [
    "InterfaceSpec",
    "RecordingClient",
    "RemoteClient",
    "RemoteTarget",
]


def __getattr__(name: str):
    """Expose the gRPC clients without importing grpc on a plain install.

    A module-level import would pull in ``grpc`` for everyone, including installs with
    no ``[grpc]`` extra that only ever call `myogestic.vhi.virtual_hand().launcher()`.
    """
    if name == "RemoteClient":
        from myogestic.remote._control import RemoteClient

        return RemoteClient
    if name == "RecordingClient":
        from myogestic.remote._recording import RecordingClient

        return RecordingClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
