"""Virtual Hand Interface (VHI) integration.

Groups the output-interface registry (`interfaces`), the gRPC control client
(`_client`), and the generated protobuf stubs (`_proto`) for driving the VHI.
"""
from myogestic.vhi.interfaces import InterfaceSpec, virtual_hand

__all__ = ["InterfaceSpec", "virtual_hand"]
