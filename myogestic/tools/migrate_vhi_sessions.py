"""Convert recorded ``vhi_control`` streams from VHI's old units to the control standard.

VHI's ground-truth outlet used to publish its own rig units, in which a fist read
``-1`` on the flexion channels — the opposite of the prediction stream it was meant to be
compared against. It publishes standard values now, so a recording made before that change
means something different from one made after, and nothing in the file said which.

This rewrites the old ones. It is a **migration, not a compatibility layer**: after it runs
there is one convention on disk, no reader has to ask which it is holding, and a session that
has already been converted is left alone.

Usage
-----
```
uv run python -m myogestic.tools.migrate_vhi_sessions sessions/
uv run python -m myogestic.tools.migrate_vhi_sessions sessions/ --dry-run
```

Each converted archive gets a ``.legacy.bak`` copy beside it. The conversion is exact and
self-inverse, so a mistake is recoverable from the backup or by running the same negation
again — but a recording cannot be re-made, so the backup is written unconditionally.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import zarr

#: Per-channel sign taking a legacy ``vhi_control`` frame to the control standard.
#:
#: Not a blanket negation. The five flexion channels ran the other way in VHI's rig
#: units, so they flip. Thumb abduction (channel 1) did not: the old readback divided by a
#: positive Z gain while a fist's thumb Z is negative, so a recorded fist already reads
#: ``-1`` there — adduction, which is what a fist does and what the standard calls ``-1``.
#: Channels 6-8 were never written by the old VHI build and are all zero, so their sign is
#: immaterial; they are left alone rather than flipped, because ``-0.0`` is noise in a diff.
TO_STANDARD = np.array([-1, 1, -1, -1, -1, -1, 1, 1, 1], dtype=np.float32)

#: Written into ``meta.json`` so a converted session says so about itself.
POSE_CONVENTION = "standard"

_STREAM = "vhi_control"


def _convention(meta: dict) -> str:
    """What convention a session's pose is in. Absent means it predates the question."""
    return meta.get("pose_convention", "legacy")


def migrate(path: Path, *, dry_run: bool = False) -> str:
    """Convert one ``.session.zip`` in place. Returns a one-line report."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if f"{_STREAM}.zarr/zarr.json" not in names:
            return f"skip   {path.name}: no {_STREAM} stream"
        meta = json.loads(zf.read("meta.json"))

    if _convention(meta) == POSE_CONVENTION:
        return f"skip   {path.name}: already standard"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "session"
        with zipfile.ZipFile(path) as zf:
            zf.extractall(root)

        array = zarr.open_array(store=str(root / f"{_STREAM}.zarr"), mode="r+")
        before = np.asarray(array[:])
        if before.shape[1] != TO_STANDARD.size:
            return f"SKIP   {path.name}: {before.shape[1]} channels, expected {TO_STANDARD.size}"
        after = (before * TO_STANDARD).astype(before.dtype)

        summary = (
            f"flexion {before[:, 2].min():+.2f}..{before[:, 2].max():+.2f} -> "
            f"{after[:, 2].min():+.2f}..{after[:, 2].max():+.2f}"
        )
        if dry_run:
            return f"would  {path.name}: {summary}"

        array[:] = after
        meta["pose_convention"] = POSE_CONVENTION
        (root / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Repack the way the recorder does — ZIP_STORED, because zarr chunks are already
        # compressed and an outer layer buys nothing.
        staged = Path(tmp) / "out.zip"
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_STORED) as zf:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(root)))

        # Prove the repack is readable before touching the original. A half-written
        # archive of a session that cannot be recorded again is the one unacceptable
        # outcome here.
        with zipfile.ZipFile(staged) as zf:
            assert "meta.json" in zf.namelist()
        check = zarr.open_array(store=zarr.storage.ZipStore(staged, mode="r"), path=f"{_STREAM}.zarr")
        assert np.array_equal(np.asarray(check[:]), after), "repacked data did not round-trip"

        shutil.copy2(path, path.with_suffix(path.suffix + ".legacy.bak"))
        shutil.move(str(staged), path)

    return f"ok     {path.name}: {summary}"


def main(argv: list[str] | None = None) -> int:
    """Convert every session under the given paths."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="session files or directories")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args(argv)

    targets: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            targets.extend(sorted(path.glob("*.session.zip")))
        elif path.is_file():
            targets.append(path)
        else:
            print(f"no such path: {path}", file=sys.stderr)
            return 2

    converted = 0
    for target in targets:
        line = migrate(target, dry_run=args.dry_run)
        if line.startswith(("ok", "would")):
            converted += 1
            print(line)
    print(f"\n{converted} of {len(targets)} session(s) {'would be ' if args.dry_run else ''}converted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
