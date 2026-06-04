# API cheatsheet

Every public symbol on one page, signatures only. For prose, full Args/Returns, and source links, jump to the [API reference](../api/index.md).

```python
# --- Core (myogestic) ------------------------------------------
App(name, theme=True, docking=False)
  .streams(*streams)
  .ui(fn)                                          # decorator
  .popout(title, gui_fn)                           # App(docking=True)
  .start_recording(base_path="sessions")
  .stop_recording()
  .run(mode="gui" | "headless")
  .ctx                                             # Context

Stream(name, source, window_seconds, buffer_seconds=10)
  .start() / .stop() / .reconnect(target=None)
  .get_window() -> (data, ts)                      # data is channels-first
  .get_display(n_pixels) -> (env_min, env_max)
  .get_raw_snapshot() -> (ts, data)

Context                                            # flat dataclass
  .streams: dict[str, Stream]
  .state: str                                      # "idle" / "recording" / ...
  .session: Session | None                         # active recording
  .class_names: list[str]
  .status_message: str

Grid(rows, cols)                                   # @app.ui layout helper
StreamInfo(n_channels, fs, dtype=float32, channel_names=None)
TrainingData(paths=[], class_names=[], classes=set())
  .is_empty

# --- Sources (myogestic.sources) -------------------------------
LSLSource(stream_name)
ReplaySource(session_path, stream_name, speed=1.0) # accepts .session.zip
SerialSource(port, baud, n_channels, fs)           # extras: [serial]

# --- Outputs (myogestic.outputs) -------------------------------
LSLOutlet(name, n_channels, hz=50)
UDPOutput(host, port, hz=50)
SerialOutput(port, baud=115200, hz=10)             # extras: [serial]
  .push(data) -> None                              # all outputs

# --- ML pipeline (myogestic.ml) --------------------------------
Pipeline(app, predict_hz=50)
  @pipeline.extract(windows: dict[str, np.ndarray])  # channels-first
  @pipeline.train(data: TrainingData)
  @pipeline.predict(model, features) -> dict
  .training_data: TrainingData | None
  .start_training() / .start_predicting() / .stop_predicting()
  .save_model / .load_model                          # set to enable buttons
  .model / .predictions / .train_log

save_pickle(model, path) / load_pickle(path)

# --- Session (myogestic.session) -------------------------------
open_session_store(path) -> Session                # folder OR .session.zip
iter_labeled_windows(paths, stream_name, win_seconds, hop_seconds,
                     classes=None)
  -> Iterator[(window, ts, class_index)]            # window: (n_ch, n_samp)
iter_aligned_windows(paths, primary_stream, aligned_streams,
                     win_seconds, hop_seconds, align_window_samples=1)
  -> Iterator[(primary_window, {name: vec}, ts)]

# --- Filters (myogestic.outputs.filters) -------------------------------
OneEuroFilter(freq=50.0, min_cutoff=1.0, beta=0.02, d_cutoff=1.0)
GaussianFilter(window=5, sigma=1.0)
IdentityFilter()
make_filter(name, hz=50.0, **kwargs) -> VectorFilter
  filter(x, t=None) -> np.ndarray                  # __call__ all filters

# --- Widgets (myogestic.widgets) -------------------------------
signal_viewer(ctx, stream_name, selectable=False,
              scale_mode="auto", y_range=(-1, 1),
              show_diagnostics=False, show_markers=False)
raw_signal_viewer(ctx, stream_name)                # every-sample, zero-alloc
recording_controls(ctx, class_names, *, on_record, on_stop,
                   on_gesture=None)
session_manager(base_path, label="Sessions", class_names=None)
  -> TrainingData(paths, class_names, classes)
process_launcher(processes)
scatter2d(label, points) / scatter3d(label, points)
heatmap(label, matrix) / line_plot(label, ys, xs=None)
panel_header(title, icon=None)
FilterControl(hz=50, default="one_euro").ui()
popout_panel(title, gui_fn)
template_inspector(uid, rows)
trial_preview(uid, row, fs)

# --- ML widgets (myogestic.ml.widgets) -------------------------
train_button(pipeline)
predict_button(pipeline)
training_log(pipeline)
save_model_button(pipeline, path)
load_model_button(pipeline, path)
pipeline_panel(pipeline)
```
