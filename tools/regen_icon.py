#!/usr/bin/env python3
"""Regenerate the MyoGestic shipped icon + in-app wordmark from the source PNG.

Reads ``docs/images/myogestic_logo.png`` (canonical source, 2339×1579 RGBA)
and writes two assets that ship inside the package wheel:

* ``myogestic/assets/app_settings/icon.png`` — 512×512 square padded with
  transparent space. HelloImGui's asset convention picks this up as the
  window icon (Linux/Windows); ``core.py`` also feeds it to PyObjC's
  ``NSApplication.setApplicationIconImage_`` for the macOS dock.
* ``myogestic/assets/myogestic_logo.png`` — 800×540 wordmark (original
  1.5:1 aspect), used by the ``app_logo`` in-app branding widget.

Run after editing the source:

    uv run python tools/regen_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docs" / "images" / "myogestic_logo.png"
ICON_OUT = REPO_ROOT / "myogestic" / "assets" / "app_settings" / "icon.png"
WORDMARK_OUT = REPO_ROOT / "myogestic" / "assets" / "myogestic_logo.png"

ICON_SIZE = 512
WORDMARK_WIDTH = 800


def main() -> int:
    if not SOURCE.exists():
        print(f"source not found: {SOURCE}", file=sys.stderr)
        return 1

    src = Image.open(SOURCE).convert("RGBA")
    w, h = src.size
    print(f"source: {SOURCE.name}  {w}×{h}")

    # Square padded icon.
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(src, ((side - w) // 2, (side - h) // 2), src)
    icon = square.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    ICON_OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(ICON_OUT, optimize=True)
    print(f"  → {ICON_OUT.relative_to(REPO_ROOT)}  {icon.size}  "
          f"{ICON_OUT.stat().st_size:,} bytes")

    # Wordmark for in-app display — preserve aspect.
    wordmark_h = round(WORDMARK_WIDTH * h / w)
    wordmark = src.resize((WORDMARK_WIDTH, wordmark_h), Image.LANCZOS)
    WORDMARK_OUT.parent.mkdir(parents=True, exist_ok=True)
    wordmark.save(WORDMARK_OUT, optimize=True)
    print(f"  → {WORDMARK_OUT.relative_to(REPO_ROOT)}  {wordmark.size}  "
          f"{WORDMARK_OUT.stat().st_size:,} bytes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
