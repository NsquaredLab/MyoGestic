---
title: "Docs screenshots"
slug: images
---
The docs site uses PNGs from this folder. Capture widgets automatically
with one script and examples manually as full windows.

## Widgets - automated via `tools/widget_screenshot.py`

For each registry entry, the script builds a minimal `App` with the widget
or Hello EMG pair. It waits about 3 s, or 7 s for signal viewers, then captures
the window via Quartz + `screencapture`, saves the PNG and exits. This capture script requires macOS, screen-capture permission and
the `dev` extra for Quartz. Re-run after changes to widget styling, themes, fonts or ImGui, and when adding widgets.

```bash
uv run --extra dev python tools/widget_screenshot.py --all
# or one at a time
uv run --extra dev python tools/widget_screenshot.py signal_viewer
uv run --extra dev python tools/widget_screenshot.py hello_emg --out docs/images/hello-emg.png
```

The registry covers

| File                                       | Shows                               |
|--------------------------------------------|-------------------------------------|
| `widgets/hello_emg.png`                    | signal + recording controls (use `--out` above for the homepage) |
| `widgets/AppHeader.png`                    | Connect / Record / Train / Predict, Record selected |
| `widgets/StatusBar.png`                    | stream, participant and `data/P-014` folder |
| `widgets/SimulatorControls.png`            | persistent Rest / Fist preview       |
| `widgets/FollowRun.png`                    | guided recording controls            |
| `widgets/signal_viewer.png`                | 4-channel synthetic signal          |
| `widgets/recording_controls.png`           | 4-class button strip                |
| `widgets/session_manager.png`              | 3 selected mock takes for `P-014`, with Rest / Fist durations |
| `widgets/FilterControl.png`                | one-euro defaults                   |
| `widgets/process_launcher.png`             | 2 dummy `sleep 60` processes        |
| `widgets/TargetPanel.png`                  | connected, running and idle targets |
| `widgets/pipeline_panel.png`               | idle Pipeline                       |
| `widgets/FeatureSelector.png`              | RMS / MAV / WL / VAR / ZC           |
| `widgets/app_logo.png`                     | shipped wordmark, centred           |
| `widgets/prediction_label.png`             | "Fist" @ 82%                        |
| `widgets/VhiMovementPanel.png`             | 12 movements, "Fist" highlighted    |

The session fixture creates three takes in `P-014/recordings/`, calls
`SessionManager.select_all("P-014")`, then renders that participant. No Rescan click is
needed. The newest day opens with all three takes visible.

## Examples - fullscreen, manual

For the classification tutorial screenshot (`gui-overview.png`) and any
future per-example shots, run the example fullscreen and capture the whole
window. `App.run(fullscreen=True)` maximizes to the monitor work area,
keeping the menu bar / dock visible.

```python
# Add temporarily to the example's main() or pass through __main__:
app.run(fullscreen=True)
```

Then start the example, launch EMG Generator in Connect, connect
TestEMG1, and optionally connect the Virtual Hand. Run a
Record → Train → Predict cycle so the signal viewer and prediction card
show non-empty state, and capture:

```bash
# Interactive: click the window you want to capture
screencapture -i -W docs/images/gui-overview.png
```

For scripted macOS capture, obtain the Quartz window ID as
`_self_capture_after` does in `tools/widget_screenshot.py`; a process ID
is not a window ID.

On Linux, capture one window with `gnome-screenshot -w` or use ImageMagick
`import`.

## Style notes

- Crop tightly for full-width display on phones.
- PNG, < 1 MB each. Compress with `pngquant --quality=70-90 *.png`.
- 16:10 is the safest aspect; the demo looks good at 1280×800. Fullscreen
  captures use native monitor resolution. Downsize Retina captures with
  `sips -Z 1920 *.png` before committing.
- Use light or dark themes, whichever looks clearer in each screenshot.
  The docs support both. Mixing themes across screenshots is fine.

## Once captured

Run `cd website && npm run dev` after capturing to copy the images into the
Astro site. Reference paths in `docs/widget-gallery.md`, `docs/api/widgets.md`,
the homepage and the tutorials are already in place. The site's `npm run check:links` check fails if a referenced local image is missing.
