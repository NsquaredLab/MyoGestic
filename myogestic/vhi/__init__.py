"""Virtual Hand Interface (VHI) integration.

Groups the output-interface registry (`interfaces`), the control target (`target`),
the gRPC clients (`_control`, `_recording`), and the generated protobuf stubs
(`_proto`) for driving the VHI. `legacy` is separate: it reads VHI's own recorded
pose format for old sessions, and never touches the live control path.
"""

from myogestic.vhi.interfaces import InterfaceSpec, virtual_hand
from myogestic.vhi.target import PoseSink, VhiTarget

#: The two gRPC clients are listed here but resolved lazily by ``__getattr__`` below.
__all__ = [
    "InterfaceSpec",
    "PoseSink",
    "VhiControlClient",
    "VhiRecordingClient",
    "VhiTarget",
    "virtual_hand",
]


def __getattr__(name: str):
    """Expose the gRPC clients without importing grpc on a plain install.

    A module-level import would pull in ``grpc`` for everyone, including installs with
    no ``[grpc]`` extra that only ever call `virtual_hand().outlet()`.
    """
    if name == "VhiControlClient":
        from myogestic.vhi._control import VhiControlClient

        return VhiControlClient
    if name == "VhiRecordingClient":
        from myogestic.vhi._recording import VhiRecordingClient

        return VhiRecordingClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
