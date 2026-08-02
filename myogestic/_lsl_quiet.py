"""Point liblsl at a fallback config unless something already configures it.

Imported for its side effect, first thing in `myogestic/__init__.py`: liblsl reads its
configuration once when the shared library initialises and ignores anything set afterwards.

At liblsl's default level, building one outlet logs a line per network interface plus a
multicast bind warning per interface it cannot use — 65 lines on a laptop with a dozen
adapters. MyoGestic publishes one outlet per control it drives, so a six-control map emits
several hundred lines before the application logs anything.

liblsl looks for its config in `$LSLAPICFG`, then `./lsl_api.cfg`, then `~/lsl_api.cfg`. If
any of those exists it is somebody's deliberate choice and this module does nothing — which
matters: this repo's own `lsl_api.cfg` disables IPv6 to avoid a driver deadlock, and shadowing
it would put that back.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Pyodide has no liblsl and no home directory. Probing for one there is pointless at best,
#: and `Path.home()` raises `RuntimeError` when it cannot resolve `~` — from a function this
#: module calls at import, which would take `import myogestic` down with it in the browser.
_IS_BROWSER = sys.platform == "emscripten"

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
    if _IS_BROWSER or os.environ.get("LSLAPICFG"):
        return False
    for candidate in (lambda: Path("lsl_api.cfg"), lambda: Path.home() / "lsl_api.cfg"):
        try:
            if candidate().is_file():
                return False
        except (OSError, RuntimeError):
            # An unreadable cwd, or a home directory that cannot be resolved at all
            # (locked-down account, some containers). Neither is a reason to leave the
            # console noisy — and `Path.home()` is called lazily, inside the guard, because
            # it is the call that raises.
            pass
    if not _FALLBACK.is_file():
        return False  # a tree without assets: noise beats raising on import
    os.environ["LSLAPICFG"] = str(_FALLBACK)
    return True


quiet_liblsl()
