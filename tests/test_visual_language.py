"""Enforce the mechanically-decidable rules of `docs/concepts/visual-language.md`.

Only the parts a machine can decide honestly live here. Whether a cue *means*
the right thing, whether a label reads as plain language, whether a comparison
needs a shared range — those stay code review. A linter that guesses intent
produces noise and gets switched off.

Both rules below were written against real drift: `RawSignalViewer` rendered as
stock ImPlot for want of one `ensure_implot_style()` call, and 19 hardcoded
colours had accumulated across 8 widget files, several of which (a near-white
label, a dark pill) were invisible or wrong on the light theme.

The check is AST-based, not textual: a docstring in `_state.py` mentions
`begin_plot`, and a grep-based version flagged it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_WIDGETS = _ROOT / "myogestic" / "widgets"

#: The design layer itself — the one place colour literals belong. Everything
#: else must go through a token (`SUCCESS`, `PILL_BG`, …) or read a theme slot
#: (`muted()`, `primary()`, `hairline()`, `imgui.get_style().color_(...)`).
_DESIGN_LAYER = {"myogestic/_theme.py", "myogestic/widgets/common.py"}


def _py_files() -> list[pathlib.Path]:
    return sorted(p for p in (_ROOT / "myogestic").rglob("*.py"))


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _calls(tree: ast.Module) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _call_name(node: ast.Call) -> str:
    """``implot.begin_plot(...)`` -> ``"implot.begin_plot"``; ``muted()`` -> ``"muted"``."""
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


@pytest.mark.parametrize("path", _py_files(), ids=_rel)
def test_no_hardcoded_colours_outside_the_design_layer(path: pathlib.Path):
    """`ImVec4` built from bare numbers is a colour the theme cannot reach.

    A literal tuned on the dark theme goes invisible on the light one — that is
    exactly how `_MUTED = ImVec4(0.65, ...)` and a near-white session label got
    in. Colour components read from another colour (``off.x``, ``c[0]``,
    ``PALETTE[i]``) are fine: those already come from a token or a theme slot.
    """
    if _rel(path) in _DESIGN_LAYER:
        return
    offenders = [
        f"{_rel(path)}:{node.lineno}"
        for node in _calls(_tree(path))
        if _call_name(node) == "imgui.ImVec4"
        # All-constant numeric args == a colour typed by hand. A single scalar
        # (ImVec2-style sizes are a different call) still counts if it's ImVec4.
        and node.args
        and all(isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) for a in node.args)
    ]
    assert not offenders, (
        "Hardcoded colour literal(s) outside the design layer:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse a token from myogestic.widgets.common (SUCCESS / DANGER / PILL_BG / "
        "CONSOLE_BG …) or read the theme (muted(), primary(), hairline()). "
        "See docs/concepts/visual-language.md. If the colour is deliberately fixed in "
        "both themes, name it in common.py — do not inline it here."
    )


@pytest.mark.parametrize("path", _py_files(), ids=_rel)
def test_plot_widgets_apply_the_app_plot_style(path: pathlib.Path):
    """Any module that opens an ImPlot plot must also style it.

    Without `ensure_implot_style()` the plot keeps ImPlot's stock look — chart
    border, opaque background, heavy grid — and stops reading as part of the
    app. `RawSignalViewer` shipped that way until this test was written.
    """
    tree = _tree(path)
    names = {_call_name(n) for n in _calls(tree)}
    if "implot.begin_plot" not in names:
        return
    assert "ensure_implot_style" in names, (
        f"{_rel(path)} calls implot.begin_plot() without ensure_implot_style(). "
        "Call it at the top of the widget so the plot matches the app "
        "(see docs/concepts/visual-language.md)."
    )


#: Draw-list calls whose trailing parameters have swapped order between
#: imgui_bundle releases, mapped to how many arguments may safely be positional.
#: `add_polyline(points, col, flags, thickness)` on 1.92.601 became
#: `add_polyline(points, col, thickness, flags)` on 1.92.801 — same names, same
#: types on the wire for `flags=0, thickness=2.0`, so a positional call is silently
#: correct on one version and a TypeError on the other. `add_rect` moved the same
#: pair. Both are still fine by keyword. `add_line` is listed on the same habit rather
#: than on a break of its own: `thickness` is its last positional too, and one rule for
#: the three of them beats a reader having to remember which have already bitten.
_POSITIONAL_LIMIT = {"add_polyline": 2, "add_rect": 4, "add_line": 3}


@pytest.mark.parametrize("path", _py_files(), ids=_rel)
def test_drawlist_calls_pass_thickness_and_flags_by_keyword(path: pathlib.Path):
    """``imgui-bundle>=1.5.0`` is the floor, so users resolve versions we never ran.

    This shipped: the force-tracking sketch called ``add_polyline`` positionally, which
    was right on the version pinned here and a ``TypeError`` on the one a downstream
    project had resolved. Nothing in the suite could catch it — the code is correct
    against the installed bundle, and there is only ever one installed.
    """
    offenders = []
    for node in _calls(_tree(path)):
        name = _call_name(node).rsplit(".", 1)[-1]
        limit = _POSITIONAL_LIMIT.get(name)
        if limit is not None and len(node.args) > limit:
            offenders.append(f"{_rel(path)}:{node.lineno} ({name})")

    assert not offenders, (
        "Draw-list call(s) passing thickness/flags positionally:\n  "
        + "\n  ".join(offenders)
        + "\n\nThose two parameters swapped order between imgui_bundle releases. Pass "
        "them by keyword — `add_polyline(pts, col, thickness=2.0, flags=0)` — which is "
        "correct on every version."
    )
