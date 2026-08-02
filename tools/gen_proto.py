#!/usr/bin/env python3
"""Regenerate the renderer-control gRPC Python stubs from the vendored .proto.

The contract lives in the Virtual-Hand-Interface repo (``proto/renderer_control.proto``);
``myogestic/renderer/_proto/renderer_control.proto`` is a byte-identical vendored copy.
After updating the vendored copy, run:

    uv run --extra grpc python tools/gen_proto.py

This writes ``myogestic/renderer/_proto/renderer_control_pb2.py``, ``..._pb2.pyi`` (type
stubs so checkers see the generated message classes), and ``..._pb2_grpc.py`` —
all committed so a plain install needs only grpcio at runtime (not grpcio-tools).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = REPO_ROOT / "myogestic" / "renderer" / "_proto"


def main() -> int:
    protos = sorted(PROTO_DIR.glob("*.proto"))
    if not protos:
        print(f"no .proto files in {PROTO_DIR}", file=sys.stderr)
        return 1

    # Globbed rather than named, so adding or removing a contract needs no edit here.
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={PROTO_DIR}",
        f"--python_out={PROTO_DIR}",
        f"--pyi_out={PROTO_DIR}",
        f"--grpc_python_out={PROTO_DIR}",
        *[str(p) for p in protos],
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("protoc failed", file=sys.stderr)
        return result.returncode

    # grpc_tools emits a flat `import <stem>_pb2` in each _pb2_grpc file; rewrite it to a
    # package-relative import so the stubs work as `myogestic.renderer._proto.*`.
    for proto in protos:
        stem = proto.stem
        grpc_file = PROTO_DIR / f"{stem}_pb2_grpc.py"
        if not grpc_file.exists():
            print(f"WARNING: {grpc_file.name} was not generated", file=sys.stderr)
            continue
        alias = stem.replace("_", "__")
        text = grpc_file.read_text()
        patched = text.replace(
            f"import {stem}_pb2 as {alias}__pb2",
            f"from . import {stem}_pb2 as {alias}__pb2",
        )
        if patched != text:
            grpc_file.write_text(patched)
            print(f"patched relative import in {grpc_file.name}")
        else:
            print(f"WARNING: expected import line not found in {grpc_file.name}", file=sys.stderr)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
