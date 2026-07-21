# API cheatsheet

The most-used public symbols on one page, signatures only. This page is hand-maintained and not exhaustive. For prose, full Args/Returns, and source links, jump to the [API reference](../api/index.md).

<!--docs:skip-->
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

Stream(name, source, window_ms, buffer_ms=10000)
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
SerialSource(port, baud, n_channels, fs)  # extras:[serial]; from myogestic.sources.serial_source import SerialSource

# --- Outputs (myogestic.outputs) -------------------------------
LSLOutlet(name, n_channels, hz=50)
UDPOutput(host, port, hz=50)
SerialOutput(port, baud=115200, hz=10)  # extras:[serial]; from myogestic.outputs.serial_output import SerialOutput
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
iter_labeled_windows(paths, stream_name, window_ms, hop_ms,
                     classes=None)
  -> Iterator[(window, ts, class_index)]            # window: (n_ch, n_samp)
iter_aligned_windows(paths, primary_stream_name, aligned_stream_names,
                     window_ms, hop_ms, n_alignment_samples=1)
  -> Iterator[(primary_window, {name: vec}, ts)]

# --- Filters (myogestic.outputs.filters) -------------------------------
OneEuroFilter(hz=50.0, min_cutoff_hz=1.0, beta=0.02, derivative_cutoff_hz=1.0)
GaussianFilter(n_vectors=5, sigma=1.0)
IdentityFilter()
make_filter(name, hz=50.0, **kwargs) -> VectorFilter
  filter(x, timestamp=None) -> np.ndarray                  # __call__ all filters

# --- Widgets (myogestic.widgets) -------------------------------
# Construct once (setup scope), then call .ui(...) each frame in @app.ui.
SignalViewer(stream_name, selectable=False, scale_mode="auto",
             y_range=(-1, 1), show_diagnostics=False, show_markers=False)
  .ui(ctx)
RawSignalViewer(stream_name)                        # every-sample, zero-alloc
  .ui(ctx)
RecordingControls(class_names, *, on_record, on_stop, on_gesture=None)
  .ui(ctx)
SessionManager(base_path, title="Sessions", class_names=None)
  .ui() -> TrainingData(paths, class_names, classes)
ProcessLauncher(processes)
  .ui()
Scatter2D(label) / Scatter3D(label)
  .ui(points, labels=None, class_names=None)
Heatmap(label, label_fmt="%.1f") / LinePlot(label)
  .ui(data)                                         # LinePlot: .ui(data, channel_names=None)
panel_header(title, icon=None)
output_filter = FilterControl(hz=50, default="one_euro")
output_filter.ui()
popout_panel(title, gui_fn)
TemplateInspector(widget_id)
  .ui(rows)
TrialPreview(widget_id=widget_id)
  .ui(data, fs)

# --- ML widgets (myogestic.ml.widgets) -------------------------
TrainButton(pipeline)               .ui()
PredictButton(pipeline)             .ui()
TrainingLog(pipeline)               .ui()
SaveModelButton(pipeline, path)     .ui()
LoadModelButton(pipeline, path)     .ui()
PipelinePanel(pipeline)             .ui()
```
