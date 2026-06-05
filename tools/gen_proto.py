#!/usr/bin/env python3
"""Regenerate the VHI gRPC Python stubs from the vendored .proto.

The canonical contract lives in the Virtual-Hand-Interface repo
(``proto/myogestic_vhi.proto``); ``myogestic/vhi/_proto/myogestic_vhi.proto`` is a
vendored copy. After updating the vendored copy, run:

    uv run --extra grpc python tools/gen_proto.py

This writes ``myogestic/vhi/_proto/myogestic_vhi_pb2.py``, ``..._pb2.pyi`` (type
stubs so checkers see the generated message classes), and ``..._pb2_grpc.py`` —
all committed so a plain install needs only grpcio at runtime (not grpcio-tools).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = REPO_ROOT / "myogestic" / "vhi" / "_proto"
PROTO_FILE = PROTO_DIR / "myogestic_vhi.proto"


def main() -> int:
    if not PROTO_FILE.exists():
        print(f"proto not found: {PROTO_FILE}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={PROTO_DIR}",
        f"--python_out={PROTO_DIR}",
        f"--pyi_out={PROTO_DIR}",
        f"--grpc_python_out={PROTO_DIR}",
        str(PROTO_FILE),
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("protoc failed", file=sys.stderr)
        return result.returncode

    # grpc_tools emits a flat `import myogestic_vhi_pb2` in the _pb2_grpc file;
    # rewrite it to a package-relative import so the stubs work as
    # `myogestic.vhi._proto.*`.
    grpc_file = PROTO_DIR / "myogestic_vhi_pb2_grpc.py"
    text = grpc_file.read_text()
    patched = text.replace(
        "import myogestic_vhi_pb2 as myogestic__vhi__pb2",
        "from . import myogestic_vhi_pb2 as myogestic__vhi__pb2",
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
