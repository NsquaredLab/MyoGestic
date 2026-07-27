"""Virtual Hand Interface (VHI) integration.

Groups the output-interface registry (`interfaces`), the canonical-control target
(`target`), the gRPC control client (`_client`), and the generated protobuf stubs
(`_proto`) for driving the VHI. `legacy` holds the wire mapping the target encodes
with, kept apart because its upgrade path is deletion.
"""

from myogestic.vhi.interfaces import InterfaceSpec, virtual_hand
from myogestic.vhi.target import PoseSink, VhiTarget

__all__ = ["InterfaceSpec", "PoseSink", "VhiTarget", "virtual_hand"]
