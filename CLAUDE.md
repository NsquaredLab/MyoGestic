# MyoGestic — working notes for agents

A real-time biosignal app framework (imgui/implot). Read this before editing; it is short
because the real contracts live in two docs.

## The two contracts

- **[docs/concepts/design-principles.md](docs/concepts/design-principles.md)** — the *code*
  contract. No base classes, no inheritance, no registration, no config files. Every widget is a
  single public class/function with typed arguments. Widget state is keyed by **widget identity**,
  not by the data it happens to show.
- **[docs/concepts/visual-language.md](docs/concepts/visual-language.md)** — the *visual* contract.
  Read it before adding or restyling any control. The theme is deliberate; the most common way to
  break it is to reach for a literal instead of a token.

Two of its rules are enforced by `tests/test_visual_language.py`:

1. **Never hardcode a colour** outside `_theme.py` / `widgets/common.py`. Use a token
   (`SUCCESS`, `DANGER`, `PILL_BG`, `CONSOLE_BG`, …) or read the theme (`muted()`, `primary()`,
   `hairline()`). A literal tuned on the dark theme goes invisible on the light one. If a colour is
   deliberately fixed in *both* themes, name it in `common.py` — do not inline it.
2. **Call `ensure_implot_style()`** in any module that calls `implot.begin_plot`, or the plot
   renders as stock ImPlot instead of as part of the app.

The rest of the visual language is not machine-checkable and is on you: use `panel_header` for
panel titles (never a raw `imgui.text`), `push_selected`/`pop_selected` for any sticky on/off
control, `PALETTE` only for categorical series identity (never as a ramp), and a **shared range**
whenever several plots are meant to be compared — with per-instance autoscaling a quiet signal and
a loud one render identically.

## Conventions

- **Style**: 4-space indent, double quotes, NumPy-style docstrings. `pydocstyle` (ruff `D`) is
  CI-enforced. Run `uv run ruff check .`.
- **Tests**: `uv run --extra dev pytest -q`. `tests/test_stream_lsl.py::test_stream_reconnect_swaps_buffers_atomically`
  is flaky under full-suite load (LSL multicast contention) and passes in isolation — it is not
  your change.
- **Docs are tested.** `tests/test_docs.py` parses and *runs* Python blocks in `docs/`, so a code
  block in a doc page must actually work. New doc pages go in `properdocs.yml` and the relevant
  `index.md`.
- **Layout** is always `Grid` with `Px`/`Fr` tracks — widgets never position themselves.
- Prefer extending a token/helper in `widgets/common.py` over adding a one-off in a widget file.

## Commits

Do **not** add AI attribution — no `Co-Authored-By: Claude`, no "Generated with" footer, in commit
messages or PR bodies.
