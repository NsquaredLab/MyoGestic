"""Point liblsl at a fallback config unless something already configures it.

Imported for its side effect, first thing in `myogestic/__init__.py`: liblsl reads its
configuration once when the shared library initialises and ignores anything set afterwards.

At liblsl's default level, building one outlet logs a line per network interface plus a
multicast bind warning per interface it cannot use — 65 lines on a laptop with a dozen
adapters. MyoGestic publishes one outlet per control it drives, so a six-control map buries
its own log before printing anything.

liblsl looks for its config in `$LSLAPICFG`, then `./lsl_api.cfg`, then `~/lsl_api.cfg`. If
any of those exists it is somebody's deliberate choice and this module does nothing — which
matters: this repo's own `lsl_api.cfg` disables IPv6 to avoid a driver deadlock, and shadowing
it would put that back.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Ships in the wheel — `pyproject.toml` already includes `myogestic/assets/**/*`.
_FALLBACK = Path(__file__).parent / "assets" / "lsl_api.cfg"


def quiet_liblsl() -> bool:
    """Set `LSLAPICFG` to the shipped config if liblsl is otherwise unconfigured.

    Returns
    -------
    bool
        Whether this call set the variable. `False` means liblsl was already configured and
        was left alone.
    """
    if os.environ.get("LSLAPICFG"):
        return False
    for existing in (Path("lsl_api.cfg"), Path.home() / "lsl_api.cfg"):
        try:
            if existing.is_file():
                return False
        except OSError:
            # An unreadable cwd or home (locked-down account, some containers) is not a
            # reason to leave the console noisy.
            pass
    if not _FALLBACK.is_file():
        return False  # a tree without assets: noise beats raising on import
    os.environ["LSLAPICFG"] = str(_FALLBACK)
    return True


quiet_liblsl()
