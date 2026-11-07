---
title: "Visual language"
---
Use these shared tokens and helpers to style widgets consistently.
[Design principles](design-principles.md) covers the public API.

Everything here exists in [`myogestic/_theme.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/myogestic/_theme.py)
and [`myogestic/widgets/common.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/myogestic/widgets/common.py).
Use the helpers to style widgets.

## The 2.0 kit

A widget is one card with one `panel_header`. Put its state dot in that header with
`status=…`, and keep header actions icon-only. Use `panel_header_button` for a header with one
action; when composing a status dot and actions, reserve their width with `panel_header(...,
reserve=…)`. Do not nest sub-headers, `separator_text` or `collapsing_header` sections inside
the card. A state row, a control row and the forward action give it its structure.

| Pattern | Draw it with | Contract |
| --- | --- | --- |
| State in words | `tinted_row(tone)` | Say what is happening, such as Running, Recording or Connection failed; put values and elapsed time in `mono_text`. Reserve room for the action beside the detail. `tinted_row()` without a tone uses the theme's surface for a neutral utility row. |
| Forward action | `primary_button` | One full-width forward action, such as Launch, Train or Start. Pass `size=(imgui.get_content_region_avail().x, 0)` to fill the available width; the default only fits the label. |
| State that is its own exit | `action_row(label, tone, height=…)` | When an action ends a state, such as Stop while recording or Cancel during warm-up, use the whole tinted row as its button. Place it where the starting action was. Name the action as text at the right edge; draw nothing interactive inside. |
| Pick one of a few found things | `carousel(id, items, index, can_look=…)` | Show one card at a time, starting on the expected choice. Name the card in the action beneath it, such as Connect Galvani. › past the last card and the refresh icon look for more; nothing looks on its own. For a long list the user knows by name, a combo reads faster. |
| Removal | `destructive_button` | Quiet at rest, red on hover or press. Never make a removal button permanently red. Use `TRASH` for the whole item and `XMARK` for an entry inside it, with a tooltip naming what will be removed. |
| Sticky on/off | `push_selected()` / `pop_selected()` around a chip button | Use chips instead of checkboxes or solid `PALETTE` fills. Capture the selected state before the button can change it, so the push and pop stay paired. Use `segmented()` for a visible one-of-N choice. |
| Lists | `mono_text`, `imgui.small_button`, and reserved action space | Compact one-line rows, approximately `ui_px(26)` high with room for the current font and padding. Keep values and times mono and right-aligned. Ellipsize names and details instead of wrapping; expose the full clipped text on hover. |
| Rare settings | An icon-only `imgui.small_button`, then `imgui.open_popup` / `imgui.begin_popup` / `imgui.end_popup` | Put rarely touched settings in a popover opened by a `SLIDERS` icon with a Settings tooltip. Keep the current setting or summary visible on the card. |
| Fields | `imgui.text_colored(muted(), caption)` above each control, arranged with `imgui.begin_table` | Use captions above controls in a two-column grid, with mono values beside slider captions. Fall back to one column when the controls no longer fit, including narrow cells around 320 px. Do not use `label_column` for this layout. |
| Empty state | Plain words with `imgui.text_wrapped` and `muted()` for supporting text | Centre a short explanation in an empty panel and give the next step, such as The hand is not running / Launch it, then refresh to load its movements. Avoid a bare (no data) when an action can help. |
| Locked state | `imgui.begin_disabled` / `imgui.end_disabled`, followed by a visible caption | Dim the unavailable controls and explain how to unlock them outside the disabled block, such as Stop the recording to add or remove streams. A tooltip alone is not enough. |

State colours have one meaning across the kit. `SUCCESS` indicates working state, `IDLE` is not running
and nothing is wrong, `WARNING` is something worth knowing, and `DANGER` is a failure. An
unattached stream is `IDLE`, not `DANGER`; a failed connection gets `DANGER` with the error
and Retry. Selection uses the accent tint; `PALETTE` is only for categorical identity, such
as a channel or gesture dot, never a state or a continuous ramp.

State selection can run without a window; drawing helpers require an ImGui frame
inside the app's GUI callback.

<!--docs:run-->
```python
from myogestic.widgets.common import IDLE, SUCCESS

connected = False
tone = SUCCESS if connected else IDLE
message = "Connected" if connected else "Not connected — choose a stream, then Connect."
assert tone is IDLE  # Being unattached is not a failure.
```

Use `ui_px` for every fixed pixel size and theme tokens for every colour. Check the whole card
at UI scale 2.0, in the light theme, and in a narrow cell. Check that captions stack, rows
ellipsize, actions stay reachable, and states remain readable in words. Keep any selection or popup state
under the widget's stable `widget_id`, so two cards never share it accidentally.

## Type

| Role | Face | Helper |
| --- | --- | --- |
| Hero / display text | Instrument Serif | `display_font()` |
| Console, logs, anything columnar | IBM Plex Mono | `mono_font()` |
| Everything else | the theme's UI face | — |

Size comes from the global scale, which resolves `$MYOGESTIC_UI_SCALE` →
`App(ui_scale=…)` → automatic OS display scale × window fit. See
[Grid layout](grid-layout.md#ui-scale). A control sized in `imgui.get_frame_height()` units
follows it; a size a widget fixes in pixels must go through `ui_px(n)` from
`widgets/common.py`, or its label overflows the box on a large screen.

## Colour

- `PALETTE` has ten categorical colours for series identity, such as channel 0 vs channel 1. Never
  use it as a ramp; adjacent entries carry no ordering.
- Continuous data gets a perceptually uniform ramp. Viridis is `Heatmap`'s default because
  ImPlot's stock "Deep" is categorical and misleads on a heatmap.
- Read semantic tones from the theme. Use `Col_.text_disabled` for muted text
  and `Col_.child_bg` for cell surfaces in light and dark themes.

## Panels

`panel_header(title, icon)` renders an uppercase title muted with `text_disabled` and an
optional Font-Awesome icon. Narrow panels truncate the title with an ellipsis or show only the icon. Pass `reserve=` to keep space for a right-aligned
control so the *title* collapses instead of pushing it off.

`panel_header_button(title, icon, button_icon)` is the same header with one right-aligned
icon-only action, dropping to its own line when the row is too tight.

Use one header per card. The helper provides consistent casing, muting, icons and truncation.

## State cues

| Cue | Helper | Means |
| --- | --- | --- |
| Translucent accent tint + 2 px accent underline | `push_selected()` / `pop_selected()` | "this is on" |
| Raised chip among flat segments | `segmented()` | one-of-N choice, all options visible |
| Blue fill with white text | `primary_button()` | the one forward action in a step |
| Quiet button, red on hover or press | `destructive_button()` | remove or discard |
| Theme surface with a semantic tint | `tinted_row()` | state in words, with detail and an action |
| Colour flash decaying over ~0.18 s | `flash_color()` | "value updated" |

`primary_button` uses `PRIMARY_FILL` set to `#0062CC` and white `ON_PRIMARY_TEXT`, fixed
in both themes for readable action labels. Hover and press gently lighten the fill.
Use it full-width for the forward action, such as Train, Start predicting or Start session.

Use the selected tint for sticky on/off controls, including the channel grid's `Edit…`,
the Manual scale-mode button and the panel chrome toggle.

Inline actions that sit in a row of pills, such as `All` / `None` / `Invert` / `Edit…`, use
`imgui.small_button`. A full-height `button` sits out of line with them.

## Icons

Use one glyph per action. Toggles swap icons to show what clicking will do. `PLAY`↔`PAUSE` on transport, `ANGLES_DOWN`↔`ARROW_DOWN` on
log autoscroll, the expand↔collapse arrows on pop-out, `ANGLES_UP`↔`ANGLES_DOWN` on panel chrome. A button
whose icon never changes reads as a one-shot action.

Reuse these established glyph meanings.

| Glyph | Means |
| --- | --- |
| `ARROWS_ROTATE` | re-fetch live state: rescan, reconnect, refresh |
| `ROTATE_LEFT` | reset back to defaults |
| `BROOM` | clear accumulated content (a log) |
| `UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER` / its inverse | pop out to a window / dock back |
| `BARS` | reveal a hidden menu |
| `TERMINAL` | program output |
| `CIRCLE` | the live state of the panel's control |
| `PLUS` | append one more row to the list this button sits at the end of |
| `TRASH` | delete the thing this row *is* |
| `XMARK` | remove one row from a list |

Icon plus label is `f"{icon}  Label"`, two spaces, so the glyph doesn't crowd the text. Header
actions (`panel_header_button`) are icon-only.

### Adding and removing rows

An editable list follows one shape at every depth, so a nested one reads without instructions:

* Place `PLUS` at the end of the list it appends to, indented with its rows.
* Use `destructive_button` for removal. It is quiet at rest and red on hover.
* `TRASH` for the whole row, a bare `XMARK` for one entry inside it. Deleting a control removes its targets too. A bare icon needs a tooltip that names
  what it removes; add a label when the surrounding row does not make that clear.

### Stream chips

A selectable `DevicePicker` shows sorted stream chips: a status-coloured `CIRCLE`
followed by the stream name in the mono face. The selected chip uses
`push_selected()` / `pop_selected()`. Chips wrap to another row when needed;
measure names in the same font used to draw them and scale padding with the UI.

The trailing `PLUS` opens an inline name field, Add, and a bare `XMARK` cancel.
Only the selected chip offers removal, through a bare `XMARK` and
`destructive_button`; the last offered stream cannot be removed. Adding and
removing are disabled during recording, with a visible caption:
*Stop the recording to add or remove streams.*

Connected device details share a single `tinted_row(SUCCESS)` with Reconnect and
Disconnect icons. `tinted_row()` without a tone uses the theme's surface for a
compact utility row such as Virtual Hand. The helper supplies the background and inner width;
the caller reserves room for actions, ellipsizes the detail and provides its full text in a
tooltip.

### State colours

Use these four state tokens consistently.

| Token | Means |
| --- | --- |
| `SUCCESS` | running, connected, armed - working |
| `IDLE` | not running or unattached, and nothing is wrong with that |
| `WARNING` | something is worth knowing or needs attention, such as missing calibration |
| `DANGER` | failed or refused; also the hover/press cue for a destructive action |

`panel_header(title, icon, status=…)` puts a `CIRCLE` in one of them at the right end
of the header row. Stacked panels line their titles up on the first glyph; a leading dot would
indent only the ones that carry state. Colour is the only thing a dot carries, so the kit
also puts the state in words in a `tinted_row`, readable without distinguishing the hues.
A header tooltip can add detail such as a PID or exit code; avoid repeating visible state text. An unattached stream uses `IDLE` and Not connected, with a
Connect action; reserve `DANGER` for a connection that actually failed.

## Plots

`SignalViewer` keeps transport, View and Scale on its title row; Channels and Display popups hold the detailed controls, leaving only sample rate and frame rate below the plot.

Call `ensure_implot_style()` at the top of any plot widget for a transparent background,
faint grid and no chart border. The card surface frames the plot.

For comparisons, plots must share a scale. Use `Heatmap.ui(vrange=…)` for colour, a common manual `y_range`
for traces. With per-instance autoscaling a quiet electrode array and a loud one render
identically, which silently inverts the conclusion the operator draws.

## Units

Label controls in the operator's units.

| Quantity | Format | Example |
| --- | --- | --- |
| Proportion of a maximum | `%.0f%%` | Detail `100%` |
| Multiplier | `%.2fx` | Gain `1.00x` |
| Physical quantity | its own unit | Window `1.0 s`, Artifact `< 20 ms` |

Spell out the action in a label, such as `Artifact < 20 ms`. Avoid `Reject <`.
Truncated or operator-symbol labels read as jargon to the clinician running the session.

## Space

Use pop-out windows for more space and collapse chrome within fixed cells.

- Pop out (`popout_panel`): the panel becomes its own dockable, tearable window. For a panel
  the user wants *bigger*, or on another monitor.
- Collapse chrome (`SignalViewer(show_controls=…)` and its `ANGLES_UP`↔`ANGLES_DOWN` header
  toggle): folds controls, channel bar and footer away, keeping the plot and title. Use it
  within a fixed `Grid` cell. Set `show_title=False` to hide the whole header row.

Panel placement is always [`Grid`](grid-layout.md) with `Px`/`Fr` tracks. Widgets lay out their
controls within the cell they receive; they do not position themselves in the app.

### Four ways a row lies to you

Check these four rules when laying out a widget row.

`same_line(offset)` measures from the window edge and ignores
`imgui.indent`. Inside an indented block or a popup it therefore lands the next item *on top of*
the one before it, or collapses the gutter you were trying to create. Set the column explicitly
instead:

```python
left = imgui.get_cursor_pos_x()
imgui.text(f"{n}.")
imgui.same_line()
imgui.set_cursor_pos_x(left + gutter)  # not same_line(gutter)
```

Measure the space left *after* `same_line()`, never before. Before the call the cursor has
already wrapped to the next line, so `get_content_region_avail().x` reports the whole row.
Using that width to right-align a control can push it off the panel edge.

```python
imgui.same_line()  # first
avail = imgui.get_content_region_avail().x  # then measure
if avail > button_w:
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail - button_w)
```

`ItemSpacing.y` is charged when the item is placed, so it sets the gap *below* it. To tighten
the space between two rows, push the smaller spacing around the upper one and pop after its
last item. Pushing it around the lower one shortens the gap under *that*, pulling the next row up.

```python
imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(sp.x, 0.0))
name_row()  # the row whose *trailing* gap is being closed
imgui.pop_style_var()
detail_row()
```

A push/pop pair is guarded on the value as it was at push time, never on the live one. A
toggle button flips its own state *between* the two, so a pop guarded on the flag itself
can pop a colour that was never pushed or leak three colours into later widgets. Read it into a local first:

```python
selected = v.enabled  # not `if v.enabled:` on both sides
if selected:
    push_selected()
if imgui.small_button("1:1"):
    v.enabled = not v.enabled
if selected:
    pop_selected()
```

Simulate a click in the test. Without it, `small_button` returns False and the flag stays
unchanged, so both branches agree.

Plain `imgui.text` sits at the top of its line box. Call `imgui.align_text_to_frame_padding()`
to align it with an adjacent frame-height button.

## Identity

Key state by widget identity, as in rule 8 of the
[design principles](design-principles.md). Widgets that can appear more than once take an explicit
`widget_id`, defaulting to the natural single-instance name:

```python
Heatmap("IN1", widget_id="grid:IN1")  # defaults to the label
SignalViewer("emg", widget_id="emg:grid:IN1")  # defaults to the stream name
```

Without distinct IDs, two viewers share their identity-keyed state; other widgets can collide in ImGui or in their shared helper caches. Prefer a stable, unique string;
user-facing labels can repeat.
