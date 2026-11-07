---
title: "Docs screenshots"
slug: images
---
The docs site references PNGs from this folder. There are two capture
flows: **widgets** (automated, one script) and **examples** (manual, full
window).

## Widgets - automated via `tools/widget_screenshot.py`

For every entry in the script's registry, a minimal `App` is built with
the widget (or Hello EMG pair), the window settles for about 3 s
(7 s for the signal viewers), and the script
self-captures via Quartz + `screencapture`, saves the PNG, and exits
cleanly. This capture script requires macOS, screen-capture permission and
the `dev` extra for Quartz. Re-run any time the widget look changes (theme, fonts, ImGui
upgrade, new helper widget added).

```bash
uv run --extra dev python tools/widget_screenshot.py --all
# or one at a time
uv run --extra dev python tools/widget_screenshot.py signal_viewer
uv run --extra dev python tools/widget_screenshot.py hello_emg --out docs/images/hello-emg.png
```

The current registry covers:

| File                                       | Shows                               |
|--------------------------------------------|-------------------------------------|
| `widgets/hello_emg.png`                    | signal + recording controls (use `--out` above for the homepage) |
| `widgets/AppHeader.png`                    | Connect / Record / Train / Predict, Record selected |
| `widgets/StatusBar.png`                    | stream and participant status       |
| `widgets/SimulatorControls.png`            | persistent Rest / Fist preview       |
| `widgets/FollowRun.png`                    | guided recording controls            |
| `widgets/signal_viewer.png`                | 4-channel synthetic signal          |
| `widgets/recording_controls.png`           | 4-class button strip                |
| `widgets/session_manager.png`              | 3 mock sessions                     |
| `widgets/FilterControl.png`                | one-euro defaults                   |
| `widgets/process_launcher.png`             | 2 dummy `sleep 60` processes        |
| `widgets/TargetPanel.png`                  | connected, running and idle targets |
| `widgets/pipeline_panel.png`               | idle Pipeline                       |
| `widgets/FeatureSelector.png`              | RMS / MAV / WL / VAR / ZC           |
| `widgets/app_logo.png`                     | shipped wordmark, centred           |
| `widgets/prediction_label.png`             | "Fist" @ 82%                        |
| `widgets/VhiMovementPanel.png`             | 12 movements, "Fist" highlighted    |

## Examples - fullscreen, manual

For the classification tutorial screenshot (`gui-overview.png`) and any
future per-example shots, run the example **fullscreen** and capture the whole
window. `App.run(fullscreen=True)` opens the window maximised to the
monitor work area (keeps the menu bar / dock visible, fills the rest):

```python
# Add temporarily to the example's main() or pass through __main__:
app.run(fullscreen=True)
```

Then start the example, launch EMG Generator in **Connect**, connect
**TestEMG1**, and optionally connect the Virtual Hand. Run a
Record → Train → Predict cycle so the signal viewer and prediction card
show non-empty state, and capture:

```bash
# Interactive: click the window you want to capture
screencapture -i -W docs/images/gui-overview.png
```

For scripted macOS capture, obtain the Quartz window ID as
`_self_capture_after` does in `tools/widget_screenshot.py`; a process ID
is not a window ID.

Linux: `gnome-screenshot -w` (per-window) or `import` (ImageMagick).

## Style notes

- Crop tightly - the site renders images full-width on phones; whitespace is wasted.
- PNG, < 1 MB each. Use `pngquant` if needed: `pngquant --quality=70-90 *.png`.
- 16:10 is the safest aspect; the demo looks good at 1280×800. Fullscreen
  captures land at native monitor resolution - downsize before commit if
  you're on Retina (`sips -Z 1920 *.png`).
- Light or dark theme is fine - the docs support both. Pick whichever
  looks cleaner per screenshot; mixing is fine.

## Once captured

Run `cd website && npm run dev` after capturing to copy the images into the
Astro site. Reference paths in `docs/widget-gallery.md`, `docs/api/widgets.md`,
the homepage and the tutorials are already in place. The site's `npm run check:links` check fails if a referenced local image is missing.
