"""Every text file this package reads or writes must name its encoding.

`Path.read_text()` and `Path.write_text()` fall back to `locale.getpreferredencoding()`,
which is UTF-8 on macOS and Linux and **cp1252 on Windows**. A control map or a session
written on one and opened on the other then fails, and TOML and JSON are both *specified*
as UTF-8 — so the platform default is wrong for them everywhere, not only on Windows.

This shipped: CI collected `tests/test_docs_control_maps.py` on windows-latest and died with
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x90` reading a docs page.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = sorted((ROOT / "myogestic").rglob("*.py"))


def _implicit_encoding(path: pathlib.Path) -> list[str]:
    """`read_text`/`write_text` calls on `path` that do not pass `encoding`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("read_text", "write_text"):
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        bad.append(f"{path.relative_to(ROOT)}:{node.lineno}: .{node.func.attr}()")
    return bad


@pytest.mark.parametrize("path", PACKAGE, ids=lambda p: str(p.relative_to(ROOT)))
def test_text_io_names_its_encoding(path):
    offenders = _implicit_encoding(path)
    assert not offenders, (
        "text I/O without an explicit encoding, which is cp1252 on Windows:\n  "
        + "\n  ".join(offenders)
    )
