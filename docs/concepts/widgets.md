---
title: "Widgets"
---
A widget is a class. You construct it once with its configuration, then call `.ui(...)` each frame with the live per-frame inputs. Use a plain class with a `.ui()` method. No `Widget` base class or registration with the app is required.

```python
class EmgViewer:
    def __init__(self, stream: str = "emg") -> None:
        self._stream = stream  # config held on the instance

    def ui(self, ctx: Context) -> None:  # per-frame: takes ctx
        snapshot = ctx.streams[self._stream].get_display(n_pixels=800)
        if snapshot is None:
            return
        ts, data = snapshot
        if implot.begin_plot("EMG", imgui.ImVec2(-1, 300)):
            for ch in range(data.shape[1]):
                implot.plot_line(f"##ch{ch}", ts, data[:, ch])
            implot.end_plot()
```

Construct it once, then drop `.ui(ctx)` inside `@app.ui`:

```python
viewer = EmgViewer("emg")  # once, at module/app scope


@app.ui
def ui(ctx):
    viewer.ui(ctx)  # every frame
```

Public widget calls include `SignalViewer("emg").ui(ctx)`, `Heatmap("Confusion").ui(cm)`, `PipelinePanel(pipeline).ui()`. Functional helpers such as `panel_header` and `popout_panel` are called directly.

`ProcessLauncher(processes)` shows a full-width process selector and Launch.
While running, its tinted state row gives the PID, elapsed time and Stop;
failures show the exit code, Show output and Launch again. The header's
pop-out icon opens the selected process's log, which stays open when another
process is selected. Each launcher gets its own identity by default; set
`widget_id` explicitly to keep that identity across reconstruction.

`TargetPanel(targets, connectors=...)` is the card for the processes an app *drives*,
with one row each showing state in words, PID and elapsed time in mono, one action and the
process output. A target with a `ControlLinkConnector` gets Connect, which binds to
one already running and launches only when none answers; one without gets Launch.
Stop appears only for a process the card started.

`PostProcessor(hz=50)` defaults to a compact Smoothing row with a filter combo,
mono delay and a settings popover for the description, captioned sliders and
Reset. Pass `compact=False` for the full panel; `FilterProcessor` provides the
same full-panel controls for a custom filter palette.

## The contract

1. Construct once; render every frame. The instance holds state, so build it at module/app scope and only call `.ui(...)` inside the frame. Constructing a widget *inside* `@app.ui` rebuilds it every frame and can reset its instance state, such as filter tuning. Identity-keyed caches, such as viewer channel selection, may outlive the instance.
2. Config in `__init__`, per-frame in `.ui(...)`. Stable configuration such as stream name, pipeline or plot options goes to the constructor. Pass only inputs that cannot be held ahead of time to `.ui(...)`, such as `ctx` for stream/recording/log widgets or `data` arrays for plots. Widgets holding `pipeline.predictions`, a filter or the feature map need no per-frame arguments.
3. One file per widget. ~100–200 LOC. If a widget grows past that, split its private helpers into underscore-prefixed modules (`_state.py`, `_controls.py`, `_plot.py`). Keep the public class in one file.
4. Bound render work. Widgets read recent snapshots and prediction state. Signal display filtering and decimation run on the render thread, bounded by the visible window. Model training and other heavy work belong outside the render path.

<a id="why-ctx-is-a-ui-argument-not-constructor-state"></a>

## Passing `ctx` to `.ui()`

`app.streams(...)` can populate `ctx.streams` after widget construction. A reconnect replaces
stream buffers and changes status, so widgets read `ctx.streams.get(name)` each frame.
Do not capture a `Stream` at construction.
`SignalViewer("emg")` stores configuration; `.ui(ctx)` reads live state. A `Pipeline` is stable,
so `PipelinePanel(pipeline)` holds it and takes no per-frame arguments in `.ui()`.

## ImGui immediate mode

Dear ImGui is *immediate mode*: the UI is described by code that runs every frame. There is no retained DOM. A button appears because you called `imgui.button(...)` this frame; it disappears next frame if you don't.

```python
@app.ui
def ui(ctx):
    viewer.ui(ctx)  # draws this frame
    if imgui.button("Click me"):
        print("clicked")  # only true on the frame the click landed
```

The class holds state between frames. Rendering remains immediate-mode. `.ui()` issues
fresh draw calls each frame.

## State and the `_<widget>_state.py` pattern

Persistent state, such as selected channels, scroll offsets or popup flags, lives with the widget. Small widgets keep it as instance attributes. Larger widgets such as the signal viewer keep a private state module so the public class stays short:

```text
myogestic/widgets/signals/
├── viewer.py     # public: class SignalViewer
├── raw.py        # public: class RawSignalViewer
├── _state.py     # private: per-stream ViewerState
├── _controls.py  # private: control panel rendering
├── _plot.py      # private: plot rendering
└── _scan.py      # private: shared scan/discovery cache
```

Some module-level caches are shared across widgets and keyed by identity. The stream
discovery cache in `_scan.py` is keyed by stream name and shared by `SignalViewer`,
`RawSignalViewer` and `StreamPanel`, so a scan started from one appears in the others.

<a id="layout-grid"></a>

## Grid layout

[`Grid(rows, cols)`][myogestic.Grid] is a matplotlib-style helper for the common "panels in a grid" layout. It uses ImGui's `BeginChild` under the hood to allocate fixed-size cells.

```python
grid = Grid(8, 3)

# Widgets constructed once, up here:
viewer = SignalViewer("emg")
launcher = ProcessLauncher(processes)
recording = RecordingControls(classes, on_record=..., on_stop=..., on_gesture=...)
sessions = SessionManager("data")
panel = PipelinePanel(pipeline)
save = SaveModelButton(pipeline, "model.pkl")


@app.ui
def ui(ctx):
    with grid[0:8, 1:3]:  # right two columns
        viewer.ui(ctx)
    with grid[0, 0]:
        launcher.ui()
    with grid[1, 0]:
        recording.ui(ctx)
    with grid[2:6, 0]:  # rows 2–5, column 0
        pipeline.training_data = sessions.ui()
    with grid[6, 0]:
        panel.ui()
    with grid[7, 0]:
        save.ui()
```

Slices accept Python conventions: `0:8` is rows 0–7 inclusive, `1:3` is cols 1–2 inclusive. With no track lists, sizes are even fractions of the window. Use `Px` and `Fr` for non-uniform tracks, or named areas and `Layout` for responsive arrangements; see [Grid layout](grid-layout.md).

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

`popout_panel(title, gui_fn)` is the inline fallback. It renders `gui_fn` directly inside `@app.ui` if docking is off, or creates a docked window if docking is on. Useful for big secondary panels you may want to tear off on multi-monitor setups.

!!! warning "Pop-outs are experimental on macOS"
    Retina viewport sizing of detached windows can be wrong on initial draw. Native dialogs (`pfd.open_file`) plus detached viewports may stack badly. Treat it as experimental until verified for your specific use case.

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for symptoms and fixes.

- Constructing a widget inside `@app.ui`. `SignalViewer("emg").ui(ctx)` in the frame loop rebuilds the widget every frame and can reset instance state. Build it once, outside.
- Calling `.ui(...)` outside `@app.ui`. It'll throw because no ImGui context is bound. Widgets only render inside the frame.
- Putting computation in the widget. If you find yourself doing `np.fft.rfft(stream.get_window()[0])` inside `.ui()`, move it to the acquisition or predict thread and store the result on `ctx` or your own object.
- Reading `pipeline.predictions` mid-write. `predictions` is a dict; widgets get a reference. Read scalar fields and you're fine. The pipeline replaces the whole dict after a successful prediction. Hold one local reference for a coherent result; avoid mutating the published dict in place.
