# Docs screenshots

The docs site references PNGs from this folder. There are two capture
flows: **widgets** (automated, one script) and **examples** (manual, full
window).

## Widgets - automated via `tools/widget_screenshot.py`

For every widget in the script's registry, a minimal `App` is built with
that single widget rendered, the window settles for ~3 s, the script
self-captures via Quartz + `screencapture`, saves the PNG, and exits
cleanly. Re-run any time the widget look changes (theme, fonts, ImGui
upgrade, new helper widget added).

```bash
uv run python tools/widget_screenshot.py --all
# or one at a time
uv run python tools/widget_screenshot.py signal_viewer
```

The current registry covers:

| File                                       | Renderer                            |
|--------------------------------------------|-------------------------------------|
| `widgets/signal_viewer.png`                | 4-channel synthetic signal          |
| `widgets/recording_controls.png`           | 4-class button strip                |
| `widgets/session_manager.png`              | 3 mock sessions                     |
| `widgets/FilterControl.png`                | one-euro defaults                   |
| `widgets/process_launcher.png`             | 2 dummy `sleep 60` processes        |
| `widgets/pipeline_panel.png`               | idle Pipeline                       |
| `widgets/FeatureSelector.png`              | RMS / MAV / WL / VAR / ZC           |
| `widgets/app_logo.png`                     | shipped wordmark, centred           |
| `widgets/prediction_label.png`             | "Fist" @ 82%                        |
| `widgets/VhiMovementPanel.png`             | 12 movements, "Fist" highlighted    |

## Examples - fullscreen, manual

For the "live demo" hero screenshot (`gui-overview.png`) and any future
per-example shots, run the example **fullscreen** and capture the whole
window. `App.run(fullscreen=True)` opens the window maximised to the
monitor work area (keeps the menu bar / dock visible, fills the rest):

```python
# Add temporarily to the example's main() or pass through __main__:
app.run(fullscreen=True)
```

Then start the example, click Launch on EMG Generator + VHI Hand, run a
Record → Train → Predict cycle so the signal viewer + pipeline panel
show non-empty state, and capture:

```bash
# Interactive: click the window you want to capture
screencapture -i -W docs/images/gui-overview.png

# Or per-window by title (macOS)
WID=$(osascript -e 'tell app "System Events" to get id of (first process whose name is "EMG Classification")')
screencapture -l "$WID" -t png -x docs/images/gui-overview.png
```

Linux: `gnome-screenshot -w` (per-window) or `import` (ImageMagick).

## Style notes

- Crop tightly - Material renders images full-width on phones; whitespace is wasted.
- PNG, < 1 MB each. Use `pngquant` if needed: `pngquant --quality=70-90 *.png`.
- 16:10 is the safest aspect; the demo looks good at 1280×800. Fullscreen
  captures land at native monitor resolution - downsize before commit if
  you're on Retina (`sips -Z 1920 *.png`).
- Light or dark theme is fine - Material renders both. Pick whichever
  looks cleaner per screenshot; mixing is fine.

## Once captured

`properdocs serve` picks them up live - no config change. Reference
paths in `docs/widget-gallery.md`, `docs/api/widgets.md`, `docs/index.md`,
and the tutorials are already in place. Missing PNGs render as
broken-image placeholders so the gap is visible.
