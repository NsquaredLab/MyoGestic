"""Keep the website's rendered colours aligned with the native app."""

import ast
import re
from pathlib import Path

import pytest

from myogestic.widgets import common

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def css_tokens():
    path = ROOT / "website/src/styles/tokens.css"
    assert path.is_file(), "The website token stylesheet has not been created"
    source = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    return {
        selector.strip(): dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", source)
    }


def _css_rgba(value):
    value = value.strip()
    if re.fullmatch(r"#[\da-fA-F]{6}(?:[\da-fA-F]{2})?", value):
        channels = [int(value[i : i + 2], 16) for i in range(1, len(value), 2)]
        return tuple(channels if len(channels) == 4 else [*channels, 255])
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    assert match, f"Unsupported colour: {value}"
    channels = [float(part.strip()) for part in match[1].split(",")]
    return (*channels[:3], channels[3] * 255 if len(channels) == 4 else 255)


def _assert_colour(value, expected):
    assert _css_rgba(value) == pytest.approx(expected, abs=1)


def _native_rgba(colour):
    return tuple(channel * 255 for channel in (colour.x, colour.y, colour.z, colour.w))


def test_semantic_tokens_match_common(css_tokens):
    names = {
        "SUCCESS": "success",
        "WARNING": "warning",
        "DANGER": "danger",
        "INFO": "info",
        "IDLE": "idle",
        "PRIMARY_FILL": "primary-fill",
        "ON_PRIMARY_TEXT": "on-primary",
        "RECORD_FILL": "record-fill",
        "CONSOLE_BG": "console-bg",
        "CONSOLE_TEXT": "console-text",
        "PILL_BG": "pill-bg",
        "ON_PILL_TEXT": "on-pill",
    }
    for native, css in names.items():
        _assert_colour(css_tokens[":root"][f"--mg-{css}"], _native_rgba(getattr(common, native)))


def test_palette_tokens_match_common(css_tokens):
    for index, colour in enumerate(common.PALETTE):
        _assert_colour(css_tokens[":root"][f"--mg-palette-{index}"], (*colour * 255, 255))


def test_theme_ladders_match_theme_py(css_tokens):
    module = ast.parse((ROOT / "myogestic/_theme.py").read_text(encoding="utf-8"))
    apply_theme = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "apply_theme")
    branch = next(node for node in apply_theme.body if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "dark")
    names = {
        "window_bg": "canvas",
        "child_bg": "card",
        "raised": "raised",
        "control_bg": "control",
        "control_hi": "control-hi",
        "border": "border",
        "text": "text",
        "text_dim": "text-dim",
        "link": "link",
        "accent": "accent",
    }
    for theme, nodes in (("dark", branch.body), ("light", branch.orelse)):
        found = set()
        for node in nodes:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            name = node.targets[0].id
            if name not in names:
                continue
            assert isinstance(node.value.func, ast.Name) and node.value.func.id == "_rgba"
            values = [ast.literal_eval(arg) for arg in node.value.args]
            expected = tuple(values if len(values) == 4 else [*values, 255])
            _assert_colour(css_tokens[f"[data-theme='{theme}']"][f"--mg-{names[name]}"], expected)
            found.add(name)
        assert found == names.keys(), "A theme source token was not checked"


def test_selected_tint_matches_common(css_tokens):
    for native, css in (("_SELECTED_FILL", "selected"), ("_ACCENT", "selected-line")):
        _assert_colour(css_tokens[":root"][f"--mg-{css}"], _native_rgba(getattr(common, native)))
