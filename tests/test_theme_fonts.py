"""The app's body face travels with the wheel, including in Pyodide."""

import ast
import platform
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fontTools.ttLib import TTFont

from myogestic import _theme

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("system", ["Darwin", "Windows", "Linux", "Emscripten", "Unknown"])
def test_load_fonts_uses_bundled_plex_on_every_platform(monkeypatch, system):
    monkeypatch.setattr(platform, "system", lambda: system)
    for name in ("_FONT", "_DISPLAY_FONT", "_MONO_FONT"):
        monkeypatch.setattr(_theme, name, None)
    calls = []

    def load(path, size, params):
        font = object()
        calls.append((path, size, params, font))
        return font

    io = SimpleNamespace(font_default=None)
    monkeypatch.setattr(_theme.hello_imgui, "load_font", load)
    monkeypatch.setattr(_theme.imgui, "get_io", lambda: io)

    _theme.load_fonts()

    path, size, params, font = calls[0]
    assert Path(path).name == "IBMPlexSans-Regular.ttf"
    bundled = ROOT / "myogestic/assets/fonts/IBMPlexSans-Regular.ttf"
    assert bundled.is_file()
    if params.inside_assets:
        assert path == "fonts/IBMPlexSans-Regular.ttf"
    else:
        assert Path(path).resolve() == bundled
    assert size == 14.0
    assert not getattr(params, "adjust_size_to_dpi", False)  # gone in imgui-bundle 1.92.900
    assert not params.merge_to_last_font
    assert io.font_default is font
    icons = next(call for call in calls if "Font_Awesome_6" in call[0])
    assert icons[1] == 14.0
    assert icons[2].merge_to_last_font
    assert not getattr(icons[2], "adjust_size_to_dpi", False)
    # Re-entry must not append another font / duplicate the merged atlas.
    _theme.load_fonts()
    assert len(calls) == 4


def test_wheel_contains_plex_sans_and_its_licence(tmp_path):
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (wheel,) = tmp_path.glob("myogestic-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        font = archive.read("myogestic/assets/fonts/IBMPlexSans-Regular.ttf")
        licence = archive.read("myogestic/assets/fonts/IBMPlexSans-OFL.txt").decode()
    assert font == (ROOT / "myogestic/assets/fonts/IBMPlexSans-Regular.ttf").read_bytes()
    assert font[:4] == b"\x00\x01\x00\x00"  # TrueType sfnt header
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence


def test_plex_covers_ui_strings_and_scientific_symbols():
    # Include every non-docstring string, including f-string fragments, error
    # messages and CLI output: a superset of visible labels without prose/code
    # examples from docstrings. Font Awesome icons are merged separately.
    chars = set("±−µμ²°·äöüÄÖÜßéîαβγδΔθλσΣΩ")
    for directory in (ROOT / "myogestic", ROOT / "examples"):
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docs
                ):
                    chars.update(c for c in node.value if ord(c) > 127)
    with TTFont(ROOT / "myogestic/assets/fonts/IBMPlexSans-Regular.ttf") as font:
        cmap = font.getBestCmap()
        assert "fvar" not in font  # ImGui gets a static regular face.
        missing = sorted(f"U+{ord(c):04X} {c}" for c in chars if ord(c) not in cmap)
    assert not missing, f"Body glyphs need a bundled fallback: {', '.join(missing)}"
