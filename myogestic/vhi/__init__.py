"""Virtual Hand Interface (VHI) integration.

Groups the output-interface registry (`interfaces`), the canonical-control target
(`target`), the gRPC control client (`_client`), and the generated protobuf stubs
(`_proto`) for driving the VHI. `legacy` holds the wire mapping the target encodes
with, kept apart because its upgrade path is deletion.
"""

from myogestic.vhi.interfaces import InterfaceSpec, virtual_hand
from myogestic.vhi.target import PoseSink, VhiTarget

#: `VhiCanonicalClient` is listed here but resolved lazily by ``__getattr__`` below.
__all__ = ["InterfaceSpec", "PoseSink", "VhiCanonicalClient", "VhiTarget", "virtual_hand"]


def __getattr__(name: str):
    """Expose `VhiCanonicalClient` without importing grpc on a plain install.

    A module-level import would pull in ``grpc`` for everyone, including installs
    with no ``[grpc]`` extra that only ever call `virtual_hand().outlet()`.
    """
    if name == "VhiCanonicalClient":
        from myogestic.vhi._client_v2 import VhiCanonicalClient

        return VhiCanonicalClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
