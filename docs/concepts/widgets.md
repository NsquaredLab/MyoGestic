# Widgets

A widget is a **class**. You construct it once with its configuration, then call `.ui(...)` each frame with the live per-frame inputs. No inheritance, no `Widget` base, no registration with the app — just a plain class with a `.ui()` method.

```python
class EmgViewer:
    def __init__(self, stream: str = "emg") -> None:
        self._stream = stream                       # config held on the instance

    def ui(self, ctx: Context) -> None:             # per-frame: takes ctx
        env_min, env_max = ctx.streams[self._stream].get_display(n_pixels=800)
        if implot.begin_plot("EMG", imgui.ImVec2(-1, 300)):
            for ch in range(env_min.shape[1]):
                implot.plot_line(f"##min{ch}", env_min[:, ch])
                implot.plot_line(f"##max{ch}", env_max[:, ch])
            implot.end_plot()
```

Construct it once, then drop `.ui(ctx)` inside `@app.ui`:

```python
viewer = EmgViewer("emg")           # once, at module/app scope

@app.ui
def ui(ctx):
    viewer.ui(ctx)                   # every frame
```

Every widget follows this shape — `SignalViewer("emg").ui(ctx)`, `Heatmap("Confusion").ui(cm)`, `PipelinePanel(pipeline).ui()`. One convention, no exceptions.

## The contract

1. **Construct once; render every frame.** The instance holds state, so build it at module/app scope and only call `.ui(...)` inside the frame. Constructing a widget *inside* `@app.ui` rebuilds it every frame and silently resets its state (channel selection, scroll, filter tuning).
2. **Config in `__init__`, per-frame in `.ui(...)`.** Stable configuration (stream name, pipeline, plot options) goes to the constructor. `.ui(...)` receives only what can't be held ahead of time: `ctx` for stream/recording/log widgets, live `data` arrays for plots, or nothing for widgets that read from held references (`pipeline.predictions`, a filter, the feature map).
3. **One file per widget.** ~100–200 LOC. If a widget grows past that, split its private helpers into underscore-prefixed modules (`_state.py`, `_controls.py`, `_plot.py`) — never split the public class across files.
4. **No work in the render path.** Widgets read precomputed values (`get_display`, `pipeline.predictions`, `ctx.session`). Heavy computation runs on the acquisition or predict threads.

## Why `ctx` is a `.ui()` argument, not constructor state

`ctx.streams` is populated by `app.streams(...)` — possibly *after* the widget is constructed — and its contents mutate across frames (a reconnect replaces a stream's buffers and flips its status). So a widget re-reads `ctx.streams.get(name)` fresh every frame rather than capturing a `Stream` at construction. That's why the split is `SignalViewer("emg")` (stable config) + `.ui(ctx)` (live, per-frame). Widgets that render a `Pipeline` hold it in the constructor (it's a stable object) and take nothing per-frame: `PipelinePanel(pipeline).ui()`.

## ImGui immediate mode

Dear ImGui is *immediate mode*: the UI is described by code that runs every frame. There is no retained DOM. A button appears because you called `imgui.button(...)` this frame; it disappears next frame if you don't.

```python
@app.ui
def ui(ctx):
    viewer.ui(ctx)                 # draws this frame
    if imgui.button("Click me"):
        print("clicked")           # only true on the frame the click landed
```

The widget is a class only so it has somewhere to keep state between frames — the *rendering* is still immediate-mode draw calls issued fresh each frame from `.ui()`.

## State and the `_<widget>_state.py` pattern

Persistent per-widget state — selected channels, scroll offsets, popup flags — lives with the widget. Small widgets keep it as instance attributes. Larger ones (the signal viewer) keep a private state module so the public class stays short:

```text
myogestic/widgets/signals/
├── viewer.py     # public: class SignalViewer
├── raw.py        # public: class RawSignalViewer
├── _state.py     # private: per-stream ViewerState
├── _controls.py  # private: control panel rendering
├── _plot.py      # private: plot rendering
└── _scan.py      # private: shared scan/discovery cache
```

A few caches are deliberately **shared across widgets**, keyed by identity rather than owned by one instance — e.g. the stream discovery/scan cache in `_scan.py` is shared by `SignalViewer`, `RawSignalViewer`, and `StreamPanel` so a scan started from one appears in the others. Those stay module-level, keyed by stream name.

## Layout: `Grid`

[`Grid(rows, cols)`][myogestic.Grid] is a matplotlib-style helper for the common "panels in a grid" layout. It uses ImGui's `BeginChild` under the hood to allocate fixed-size cells.

```python
grid = Grid(8, 3)

# Widgets constructed once, up here:
viewer = SignalViewer("emg")
launcher = ProcessLauncher(processes)
recording = RecordingControls(classes, on_record=..., on_stop=..., on_gesture=...)
sessions = SessionManager("sessions")
panel = PipelinePanel(pipeline)
save = SaveModelButton(pipeline, "model.pkl")


@app.ui
def ui(ctx):
    with grid[0:8, 1:3]:      # right two columns
        viewer.ui(ctx)
    with grid[0, 0]:
        launcher.ui()
    with grid[1, 0]:
        recording.ui(ctx)
    with grid[2:6, 0]:        # rows 2–5, column 0
        pipeline.training_data = sessions.ui()
    with grid[6, 0]:
        panel.ui()
    with grid[7, 0]:
        save.ui()
```

Slices accept Python conventions: `0:8` is rows 0–7 inclusive, `1:3` is cols 1–2 inclusive. There's no flex layout — sizes are even fractions of the window. If you want non-uniform sizing, drop down to `imgui.set_next_window_size` directly.

## Pop-out windows

Inside `App(docking=True)`, any panel can be torn off into its own native window. The render callback runs every frame, so construct the widget once and reference it from the callback:

```python
app = App("Demo", docking=True)
viewer = SignalViewer("emg")
recording = RecordingControls(classes, on_record=..., on_stop=..., on_gesture=...)

app.popout("Signal viewer", lambda: viewer.ui(app.ctx))
app.popout("Recording", lambda: recording.ui(app.ctx))
app.run()
```

Drag the tab outside the main OS window and it floats. Layout state persists in `.imgui_state/<App>.ini` so the next launch restores your arrangement.

`popout_panel(title, gui_fn)` is the inline fallback — it renders `gui_fn` directly inside `@app.ui` if docking is off, or creates a docked window if docking is on. Useful for big secondary panels you may want to tear off on multi-monitor setups.

!!! warning "Pop-outs are experimental on macOS"
    Retina viewport sizing of detached windows can be wrong on initial draw. Native dialogs (`pfd.open_file`) plus detached viewports may stack badly. Treat it as experimental until verified for your specific use case.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Constructing a widget inside `@app.ui`.** `SignalViewer("emg").ui(ctx)` in the frame loop rebuilds the widget every frame and resets its state. Build it once, outside.
- **Calling `.ui(...)` outside `@app.ui`.** It'll throw because no ImGui context is bound. Widgets only render inside the frame.
- **Putting computation in the widget.** If you find yourself doing `np.fft.rfft(stream.get_window()[0])` inside `.ui()`, move it to a thread (acquisition or predict) and stash the result on `ctx` or your own object.
- **Reading `pipeline.predictions` mid-write.** `predictions` is a dict; widgets get a reference. Read scalar fields and you're fine. If you need a coherent snapshot, copy-on-read.
