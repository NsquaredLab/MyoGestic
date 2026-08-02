"""Virtual Hand Interface (VHI) — the parts that are genuinely about the Virtual Hand.

Everything generic lives in `myogestic.renderer`: the target, the gRPC clients, the
`~myogestic.renderer.InterfaceSpec` dataclass and the wire contract they all speak. VHI
is one renderer among however many, and imports that half like any other consumer.

What is left here is what a robot arm would have to answer differently:

- `virtual_hand` — VHI's own numbers: the Godot path or packaged binary, the install
  root, the nine-channel pose read-back, the gRPC endpoint. Plus the version gate that
  refuses a release too old to serve the v2 control contract.
- `pose` — the channel layout of VHI's *recorded* nine-float pose. A layout, not an
  interface: the live control path asks the renderer where its controls are and never
  consults a table.
"""

from myogestic.vhi.interfaces import virtual_hand

__all__ = ["virtual_hand"]
