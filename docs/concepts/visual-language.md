# Visual language

[Design principles](design-principles.md) is the *code* contract: no base classes, one name one
meaning, a public API that fits on a page. This page is the *visual* one, the small set of tokens
and rules every widget already follows, so a new control looks like it belongs instead of like a
stock ImGui default.

Everything here exists in [`myogestic/_theme.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/myogestic/_theme.py)
and [`myogestic/widgets/common.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/myogestic/widgets/common.py).
Reach for the helper; don't re-derive the styling inline.

## Type

| Role | Face | Helper |
| --- | --- | --- |
| Hero / display text | Instrument Serif | `display_font()` |
| Console, logs, anything columnar | IBM Plex Mono | `mono_font()` |
| Everything else | the theme's UI face | — |

Size comes from the global scale, which resolves
`$MYOGESTIC_UI_SCALE` → `App(ui_scale=…)` → `1.0` (`set_ui_scale`). A control sized in
`imgui.get_frame_height()` units follows the user's display; one sized in raw pixels ignores it.

## Colour

- **`PALETTE`**: ten categorical colours, for *series identity* (channel 0 vs channel 1). Never
  use it as a ramp; adjacent entries carry no ordering.
- **Continuous data gets a perceptually uniform ramp.** Viridis is `Heatmap`'s default because
  ImPlot's stock "Deep" is categorical and misleads on a heatmap.
- **Semantic tone comes from the theme**, not literals: `Col_.text_disabled` for muted text,
  `Col_.child_bg` for cell surfaces. Reading the tone keeps light and dark themes honest.

## Panels

`panel_header(title, icon)` renders the one true panel title: **uppercased, muted
(`text_disabled`), optional Font-Awesome icon, ellipsis-truncated** when the panel is too narrow
(icon-only when there is no room at all). Pass `reserve=` to keep space for a right-aligned
control so the *title* collapses instead of pushing it off.

`panel_header_button(title, icon, button_icon)` is the same header with one right-aligned
icon-only action, dropping to its own line when the row is too tight.

Never `imgui.text()` a panel title directly: you lose the casing, the muting, the icon and the
truncation, and the panel stops matching its neighbours.

## State cues

| Cue | Helper | Means |
| --- | --- | --- |
| Translucent accent tint + 2 px accent underline | `push_selected()` / `pop_selected()` | "this is on" |
| Raised chip among flat segments | `segmented()` | one-of-N choice, all options visible |
| Colour flash decaying over ~0.18 s | `flash_color()` | "this value just updated" |

The selected cue is deliberately a *tint*, not a solid fill: it should read as selection, not as a
button caught mid-press. **Any control with a sticky on/off state uses it**: the channel grid's
`Edit…`, the Manual scale-mode button, and the panel chrome toggle all do.

Inline actions that sit in a row of pills (`All` / `None` / `Invert` / `Edit…`) use
`imgui.small_button`. A full-height `button` sits out of line with them.

## Icons

One glyph per meaning, and the glyph **shows what clicking will do**, not what the state currently
is. A toggle therefore swaps its icon: `PLAY`↔`PAUSE` on transport, `ANGLES_DOWN`↔`ARROW_DOWN` on
log autoscroll, the expand↔collapse arrows on pop-out, `ANGLES_UP`↔`BARS` on panel chrome. A button
whose icon never changes reads as a one-shot action.

Established meanings. Reuse them rather than picking a near-synonym:

| Glyph | Means |
| --- | --- |
| `ARROWS_ROTATE` | re-fetch live state: rescan, reconnect, refresh |
| `ROTATE_LEFT` | reset back to defaults |
| `BROOM` | clear accumulated content (a log) |
| `UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER` / its inverse | pop out to a window / dock back |
| `BARS` | reveal a hidden menu |
| `TERMINAL` | program output |
| `CIRCLE` | the live state of whatever this panel controls - see below |
| `PLUS` | append one more row to the list this button sits at the end of |
| `TRASH` | delete the thing this row *is* |
| `XMARK` | remove one row from a list |

Icon plus label is `f"{icon}  Label"`, two spaces, so the glyph doesn't crowd the text. Header
actions (`panel_header_button`) are icon-only.

### Adding and removing rows

An editable list follows one shape at every depth, so a nested one reads without instructions:

* **`PLUS` goes at the end of the list it appends to**, indented with its rows, never up beside
  the list's title. A button that says `+ Add target` while sitting a level above the targets is
  claiming to belong to the row it is on.
* **Removing is `destructive_button`**, red *on hover only*. `DANGER` means destructive and a
  delete has to read as one, but a permanently red button in every row turns the list into an
  alarm. Quiet at rest, red when the pointer is on it.
* **`TRASH` with a label for the whole row, a bare `XMARK` for one entry inside it.** The two
  sizes are the hierarchy: deleting a control is a bigger act than dropping one of its targets,
  so it gets the bigger control.

### State colours

Four tokens, and they mean the same thing everywhere:

| Token | Means |
| --- | --- |
| `SUCCESS` | running, connected, armed - working right now |
| `IDLE` | not running, and nothing is wrong with that |
| `WARNING` | works, but something about it is worth knowing |
| `DANGER` | failed, refused, or destructive |

`panel_header(title, icon, status=…)` puts a `CIRCLE` in one of them before the title, so a
panel says how its subject is doing without spending a row on the word. **Colour is the only
thing a dot carries**, so the state has to live somewhere else as well: give the header a
tooltip with the detail (a PID, an exit code) so the fact survives for a reader who cannot
tell the hues apart.

## Plots

Call `ensure_implot_style()` at the top of any plot widget. Plots then read as part of the app:
no chart border (the surface tone frames them), a transparent plot background so the card shows
through, and a faint grid.

**Comparison needs a shared range.** Any time several plots are meant to be read against each
other, they must share one scale: `Heatmap.ui(vrange=…)` for colour, a common manual `y_range`
for traces. With per-instance autoscaling a quiet electrode array and a loud one render
identically, which silently inverts the conclusion the operator draws.

## Units

Label a control in the unit the operator thinks in, not the one the code stores:

| Quantity | Format | Example |
| --- | --- | --- |
| Proportion of a maximum | `%.0f%%` | Detail `100%` |
| Multiplier | `%.2fx` | Gain `1.00x` |
| Physical quantity | its own unit | Window `1.0 s`, Artifact `< 20 ms` |

A label states what the control *does*, spelled out: `Artifact < 20 ms`, not `Reject <`.
Truncated or operator-symbol labels read as jargon to the clinician running the session.

## Space

Two different affordances, two different jobs; don't substitute one for the other:

- **Pop out** (`popout_panel`): the panel becomes its own dockable, tearable window. For a panel
  the user wants *bigger*, or on another monitor.
- **Collapse chrome** (`SignalViewer(show_controls=…)` and its `≡` header toggle): title,
  controls, channel bar and footer fold away, leaving the plot. For a panel whose cell is
  *fixed*, a tile in a `Grid`, where the chrome costs more than it gives.

Layout itself is always [`Grid`](grid-layout.md) with `Px`/`Fr` tracks. Widgets do not position
themselves.

## Identity

State is keyed by **widget identity**, never by the data it happens to show (rule 8 of the
[design principles](design-principles.md)). Widgets that can appear more than once take an explicit
`widget_id`, defaulting to the natural single-instance name:

```python
Heatmap("IN1", widget_id="grid:IN1")           # defaults to the label
SignalViewer("emg", widget_id="emg:grid:IN1")  # defaults to the stream name
```

Without it, two instances share one state and render identically. Prefer a stable, unique string;
user-facing labels can repeat.
