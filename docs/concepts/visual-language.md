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

`panel_header(title, icon)` renders the standard panel title: **uppercased, muted
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
log autoscroll, the expand↔collapse arrows on pop-out, `ANGLES_UP`↔`ANGLES_DOWN` on panel chrome. A button
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

`panel_header(title, icon, status=…)` puts a `CIRCLE` in one of them at the **right** end
of the header row, so a panel says how its subject is doing without spending a row on the
word — and stacked panels still line their titles up on the first glyph, which a leading
dot would break for whichever of them happen to carry state. **Colour is the only
thing a dot carries**, so the state has to live somewhere else as well — either a visible
read-out in the panel, or a tooltip on the header with the detail (a PID, an exit code) —
so the fact survives for a reader who cannot tell the hues apart. **One of the two, not
both.** A panel that already prints its state in words gains nothing from a tooltip
repeating it, and gains a second copy to keep in step.

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
- **Collapse chrome** (`SignalViewer(show_controls=…)` and its `ANGLES_UP`↔`ANGLES_DOWN` header
  toggle): controls, channel bar and footer fold away, leaving the plot and its title — a panel
  that loses its name is one you cannot identify at a glance, and the toggle has to stay
  somewhere. For a panel whose cell is *fixed*, a tile in a `Grid`, where the chrome costs more
  than it gives. Dropping the title too is `show_title=False`, which takes the whole header row.

Layout itself is always [`Grid`](grid-layout.md) with `Px`/`Fr` tracks. Widgets do not position
themselves.

### Four ways a row lies to you

Inside a widget, laying out one row is still immediate-mode arithmetic, and four of its rules
read backwards. Each of these has produced a shipped layout bug in this codebase more than once,
and none of them fails loudly — you get a plausible-looking row that is wrong.

**`same_line(offset)` measures from the window edge, not from the item**, and it ignores
`imgui.indent`. Inside an indented block or a popup it therefore lands the next item *on top of*
the one before it, or collapses the gutter you were trying to create. Set the column explicitly
instead:

```python
left = imgui.get_cursor_pos_x()
imgui.text(f"{n}.")
imgui.same_line()
imgui.set_cursor_pos_x(left + gutter)   # not same_line(gutter)
```

**Measure the space left *after* `same_line()`, never before.** Before the call the cursor has
already wrapped to the next line, so `get_content_region_avail().x` reports the whole row — and a
right-aligned control offset by it overshoots by the width of everything already on the row, which
puts it off the panel edge:

```python
imgui.same_line()                                # first
avail = imgui.get_content_region_avail().x       # then measure
if avail > button_w:
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail - button_w)
```

**`ItemSpacing.y` is charged when the item is placed, so it sets the gap *below* it.** To tighten
the space between two rows, push the smaller spacing around the **upper** one and pop after its
last item. Pushing it around the lower one shortens the gap under *that*, which pulls the next row
up instead — the same fault, inverted:

```python
imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(sp.x, 0.0))
name_row()          # the row whose *trailing* gap is being closed
imgui.pop_style_var()
detail_row()
```

**A push/pop pair is guarded on the value as it was at push time**, never on the live one. A
toggle button flips its own state *between* the two, so a pop guarded on the flag itself
disagrees with the push on the one frame the user clicks — popping a colour that was never
pushed, or leaking three into every widget after it. Read it into a local first:

```python
selected = v.enabled          # not `if v.enabled:` on both sides
if selected:
    push_selected()
if imgui.small_button("1:1"):
    v.enabled = not v.enabled
if selected:
    pop_selected()
```

A layout pass cannot catch this: with no mouse, `small_button` returns False, the flag never
flips and both branches agree. Simulate the click in the test.

A related one: plain `imgui.text` sits at the **top** of its line box. On a row made frame-height
by a button beside it, the text floats above a band of empty row — call
`imgui.align_text_to_frame_padding()` first.

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
