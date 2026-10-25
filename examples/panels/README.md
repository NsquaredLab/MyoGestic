# Panel examples — one widget at a time

The runnable counterpart to the [widget gallery](../../docs/widget-gallery.md):
one standalone script per public widget, each showing **that widget**
below the shared application header, with dummy data so you can interact at full
functionality — no hardware, no full app.

```bash
uv run python examples/panels/signal_viewer.py
```

Each script is self-contained: a module docstring, a minimal `App`, inline
dummy data, one `@app.ui` callback, `app.run()`. Every demo opens with an
`AppHeader` in a bare `Px(52)` Grid row, followed by its own body layout. The
header names the widget; recording, training and prediction demos keep the state
pill, while viewers and tools use `show_state=False`. The stream-backed ones feed on
`myogestic.sources.SyntheticSource` — a paced fake amplifier that ships with
the package, so an example is also a working recipe.

The widgets use the 2.0 kit directly: one header per card, state rows in words,
selection chips, and Settings popovers. Demo-only inputs sit in their own cards
when they accompany a widget. Pong's captioned inputs stack in narrow cells;
StepBar keeps its navigation in a full-width card beneath the app header, with
completion controls in the card below. The AppLogo demo still shows the fit-to-cell
wordmark in its body; the header uses the inline logo like every other demo.

| Script | Widget | Shows |
|--------|--------|-------|
| `signal_viewer.py` | [`signal_viewer`][sv] | Live decimated 8-ch scope, per-channel toggles, display filters |
| `raw_signal_viewer.py` | [`raw_signal_viewer`][rsv] | Every-sample 4-ch viewer (no decimation) |
| `stream_panel.py` | [`stream_panel`][sp] | Per-stream status + Scan → Connect flow (starts disconnected) |
| `device_picker.py` | [`DevicePicker`][dp] | Device dropdown + per-device options → Connect (two synthetic devices, then the real OTB list) |
| `stream_manager.py` | [`StreamManager`][sm2] | Add/remove streams at runtime, each row showing live rate, channels and sample age |
| `line_plot.py` | [`line_plot`][lp] | Static multi-channel line plot with legend and Auto / Shared amplitude range |
| `heatmap.py` | [`heatmap`][hm] | Labelled 2-D heatmap (mock confusion matrix) |
| `scatter2d.py` | [`scatter2d`][s2] | 2-D scatter, per-class colouring |
| `scatter3d.py` | [`scatter3d`][s3] | 3-D scatter with orbit camera |
| `recording_controls.py` | [`recording_controls`][rc] | Timed gesture takes with a warm-up, countdown and duration settings; manual capture is also available (records to a temp dir) |
| `record_button.py` | [`RecordButton`][rb] | Record → Stop → name-the-take dialog, no classes (records to a temp dir) |
| `session_manager.py` | [`session_manager`][sm] | Session picker over three mock sessions |
| `prediction_label.py` | [`prediction_label`][pl] | Predicted class + confidence read-out |
| `feature_selector.py` | [`FeatureSelector`][fs] | Feature chips + active count |
| `template_inspector.py` | [`template_inspector`][ti] | Accept/reject/select table of rows |
| `trial_preview.py` | [`trial_preview`][tp] | Stacked waveform + shaded band overlay |
| `pong.py` | [`PongTask`][pg] | Captioned command/opponent inputs, control segments and a cursor chip above the court (no model) |
| `tracking_task.py` | [`TrackingTask`][tt] | A captioned effort input above Zero/MVC capture and a trapezoid to follow, against a synthetic force channel |
| `participant_panel.py` | [`ParticipantPanel`][participant] | Participant selection and local name lookup, with a chip to simulate the recording lock |
| `step_bar.py` | [`StepBar`][steps] | Full-width workflow navigation with an independent completion chip and state row |
| `control_map_editor.py` | [`ControlMapEditor`][controls] | Control-map authoring against a fake target, with working save/reload |
| `post_processor.py` | [`PostProcessor`][pp2] | Live-tunable output smoother (extensible filter palette) |
| `process_launcher.py` | [`process_launcher`][pr] | Start/stop external subprocesses |
| `log_panel.py` | [`log_panel`][lg] | App-event log (seeded with dummy lines) |
| `image.py` | [`image`][im] | Generic fit-to-cell image widget (shipped app icon) |
| `app_logo.py` | [`app_logo`][al] | The MyoGestic wordmark, fit-to-cell (thin wrapper over `image`) |
| `pipeline_panel.py` | [`pipeline_panel`][pp] + `train_button` / `predict_button` / `training_log` / `save_model_button` / `load_model_button` | Working Train/Predict loop (NumPy nearest-centroid model) |
| `vhi_movements.py` | [`VhiMovementPanel`][vh] | VHI movement grid driven by a fake (offline) client |

## Adding a widget

**Every new public widget ships an example here.** If it needs data, use
dummy data that shows the widget at full functionality (non-empty,
interactive) — not an idle/empty state. Keep the file to the shape above and
add a row to the table.

Inline components such as `app_logo` and `StepBar` are shown in isolation too.

**Deliberately excluded** (building blocks, not standalone panels):
`panel_header` (a section header used inside panels), `popout_panel` (a
layout mechanism — see [`examples/synthetic/emg_popout_layout.py`](../synthetic/emg_popout_layout.py)),
and the non-widget helpers `TemplateInspectorRow`, `request_vhi_state_refresh`,
`VhiStateCache`, `VhiStateSnapshot`.

[sv]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.signal_viewer
[rsv]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.raw_signal_viewer
[sp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.stream_panel
[dp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.DevicePicker
[sm2]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.StreamManager
[lp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.line_plot
[hm]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.heatmap
[s2]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.scatter2d
[s3]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.scatter3d
[rc]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.recording_controls
[rb]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.RecordButton
[sm]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.session_manager
[pl]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.prediction_label
[fs]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.FeatureSelector
[ti]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.template_inspector
[tp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.trial_preview
[pg]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.PongTask
[tt]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.TrackingTask
[pp2]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.PostProcessor
[pr]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.process_launcher
[lg]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.log_panel
[im]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.image
[al]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.app_logo
[pp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.ml.widgets.pipeline_panel
[vh]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.VhiMovementPanel
[participant]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.ParticipantPanel
[steps]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.StepBar
[controls]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.ControlMapEditor
