# Panel examples — one widget at a time

The runnable counterpart to the [widget gallery](../../docs/widget-gallery.md):
one standalone script per public widget, each standing up **that widget
alone** with dummy data so you can see and interact with it at full
functionality — no hardware, no full app.

```bash
uv run python examples/panels/signal_viewer.py
```

Each script is self-contained: a module docstring, a minimal `App`, inline
dummy data, one `@app.ui` panel, `app.run()`. The only shared piece is
[`_fixtures.py`](_fixtures.py) — a paced synthetic `Stream` source reused by
the stream-backed examples.

| Script | Widget | Shows |
|--------|--------|-------|
| `signal_viewer.py` | [`signal_viewer`][sv] | Live decimated 8-ch scope, per-channel toggles, display filters |
| `raw_signal_viewer.py` | [`raw_signal_viewer`][rsv] | Every-sample 4-ch viewer (no decimation) |
| `stream_panel.py` | [`stream_panel`][sp] | Per-stream status + Scan → Connect flow (starts disconnected) |
| `line_plot.py` | [`line_plot`][lp] | Static multi-channel line plot with legend |
| `heatmap.py` | [`heatmap`][hm] | Labelled 2-D heatmap (mock confusion matrix) |
| `scatter2d.py` | [`scatter2d`][s2] | 2-D scatter, per-class colouring |
| `scatter3d.py` | [`scatter3d`][s3] | 3-D scatter with orbit camera |
| `recording_controls.py` | [`recording_controls`][rc] | Record toggle + per-class buttons + state pill (records to a temp dir) |
| `session_manager.py` | [`session_manager`][sm] | Session picker over three mock sessions |
| `prediction_label.py` | [`prediction_label`][pl] | Predicted class + confidence read-out |
| `feature_selector.py` | [`FeatureSelector`][fs] | Feature tick-list + active count |
| `template_inspector.py` | [`template_inspector`][ti] | Accept/reject/select table of rows |
| `trial_preview.py` | [`trial_preview`][tp] | Stacked waveform + shaded band overlay |
| `filter_control.py` | [`FilterControl`][fc] | Live-tunable output smoother |
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

Not every file is a titled "panel": the plots, `app_logo`,
`template_inspector`, and `trial_preview` are inline components rather than
self-contained panels — shown in isolation here all the same.

**Deliberately excluded** (building blocks, not standalone panels):
`panel_header` (a section header used inside panels), `popout_panel` (a
layout mechanism — see [`examples/synthetic/emg_popout_layout.py`](../synthetic/emg_popout_layout.py)),
and the non-widget helpers `TemplateInspectorRow`, `request_vhi_state_refresh`,
`VhiStateCache`, `VhiStateSnapshot`.

[sv]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.signal_viewer
[rsv]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.raw_signal_viewer
[sp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.stream_panel
[lp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.line_plot
[hm]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.heatmap
[s2]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.scatter2d
[s3]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.scatter3d
[rc]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.recording_controls
[sm]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.session_manager
[pl]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.prediction_label
[fs]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.FeatureSelector
[ti]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.template_inspector
[tp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.trial_preview
[fc]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.FilterControl
[pr]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.process_launcher
[lg]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.log_panel
[im]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.image
[al]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.app_logo
[pp]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.ml.widgets.pipeline_panel
[vh]: https://nsquaredlab.github.io/MyoGestic/api/widgets/#myogestic.widgets.VhiMovementPanel
