"""Start the Virtual Hand and wait, so it can be a launch target of its own.

Every GUI example launches VHI from its own `ProcessLauncher` button, but two things
that need a running renderer have no UI to click: `tools/inspect_canonical_control.py`
and `tools/check_vhi_bridge.py`. This is the prerequisite for those — run it, leave it
running, and run the other in a second terminal or debug session.

    uv run python tools/launch_vhi.py

It resolves the same way the examples do, so it honours an installed release *and*
source-mode (`$VHI_PATH` + `$GODOT_BIN`) without knowing which it got. If VHI is not
installed it prints the install command rather than failing obscurely.

Ctrl-C stops the renderer. Nothing else is written or changed.
"""

from __future__ import annotations

import subprocess
import sys

from myogestic.vhi import virtual_hand


def main() -> int:
    """Launch VHI in the foreground; return its exit status."""
    try:
        # launcher() returns the [(name, argv)] the examples' ProcessLauncher takes, so
        # this starts exactly what clicking their button starts.
        (name, argv), *_ = virtual_hand().launcher()
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"launching {name}:\n  {' '.join(argv)}\n")
    print("Leave this running. Ctrl-C stops it.\n", flush=True)
    try:
        return subprocess.call(argv)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
