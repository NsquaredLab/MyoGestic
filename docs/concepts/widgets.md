# Widgets

A widget is a **plain function**. It takes `ctx` (and whatever else it needs) and calls Dear ImGui draw commands. No classes, no inheritance, no `Widget` base, no registration with the app.

```python
def emg_viewer(ctx: Context, stream: str = "emg") -> None:
    env_min, env_max = ctx.streams[stream].get_display(n_pixels=800)
    if implot.begin_plot("EMG", imgui.ImVec2(-1, 300)):
        for ch in range(env_min.shape[1]):
            implot.plot_line(f"##min{ch}", env_min[:, ch])
            implot.plot_line(f"##max{ch}", env_max[:, ch])
        implot.end_plot()
```

That's literally it. Drop it inside `@app.ui` and it draws every frame.

## The contract

1. **One file per widget.** ~100–200 LOC max. If a widget grows past 200 lines, split *its private state* into a `_<widget>_state.py` module - never split the public function across files.
2. **Stateless function.** The widget computes its UI from `ctx` (and arguments) every frame. There's no instance, no `self`.
3. **State, when needed, is keyed by widget identity.** A `signal_viewer(ctx, "emg")` and `signal_viewer(ctx, "imu")` need separate scroll positions and channel toggles. The widget keeps a `dict[key, _State]` indexed by something like `stream_name`. Two calls with the same key share state; two calls with different keys are independent.
4. **No work in the render path.** Widgets read precomputed values (`get_display`, `pipeline.predictions`, `ctx.session`). Heavy computation runs on acquisition or predict threads.

## ImGui immediate mode

Dear ImGui is *immediate mode*: the UI is described by code that runs every frame. There is no retained DOM. A button appears because you called `imgui.button(...)` this frame; it disappears next frame if you don't.

This is why widgets can be functions: there's no widget tree to maintain, no callbacks to register. The "register" step is just calling the function inside `@app.ui`.

```python
@app.ui
def ui(ctx):
    signal_viewer(ctx, "emg")  # draws this frame
    if imgui.button("Click me"):
        print("clicked")  # only true on the frame the click landed
```

## The `_<widget>_state.py` pattern

When a widget needs persistent per-instance state - selected channel set, scroll offsets, popup open/closed flags - it lives in a private module:

```text
myogestic/widgets/signals/
├── viewer.py                   # public: def signal_viewer(ctx, stream, ...)
├── raw.py                      # public: def raw_signal_viewer(ctx, stream)
├── _state.py                   # private: state dict keyed by stream
├── _controls.py                # private: control panel rendering
├── _plot.py                    # private: plot rendering
└── _scan.py                    # private: channel scan helper
```

The private modules are explicitly underscore-prefixed and not exported from `myogestic.widgets`. User code never imports them. The split is purely organisational - keep the public entry under ~200 lines and any single helper under ~350, with each helper focused on one concern (state, controls, plot).

Inside `signals/_state.py`:

```python
@dataclass
class ViewerState:
    visible_channels: set[int] = field(default_factory=set)
    gain: float = 1.0
    scale_mode: str = "auto"
    # ...


_states: dict[str, ViewerState] = {}


def get_state(key: str) -> ViewerState:
    return _states.setdefault(key, ViewerState())
```

The widget calls `get_state(stream_name)` to look up its state. Two `signal_viewer(ctx, "emg")` calls share the dict entry; `signal_viewer(ctx, "imu")` gets a separate one.

## Layout: `Grid`

[`Grid(rows, cols)`][myogestic.Grid] is a matplotlib-style helper for the common "panels in a grid" layout. It uses ImGui's `BeginChild` under the hood to allocate fixed-size cells.

```python
grid = Grid(8, 3)


@app.ui
def ui(ctx):
    with grid[0:8, 1:3]:  # right two columns
        signal_viewer(ctx, "emg")
    with grid[0, 0]:
        process_launcher(processes)
    with grid[1, 0]:
        recording_controls(ctx, classes, ...)
    with grid[2:6, 0]:  # rows 2–5, column 0
        session_manager("sessions")
    with grid[6, 0]:
        pipeline_panel(pipeline)
    with grid[7, 0]:
        save_model_button(pipeline, "model.pkl")
```

Slices accept Python conventions: `0:8` is rows 0–7 inclusive, `1:3` is cols 1–2 inclusive. There's no flex layout - sizes are even fractions of the window. If you want non-uniform sizing, drop down to `imgui.set_next_window_size` directly.

## Pop-out windows

Inside `App(docking=True)`, any panel can be torn off into its own native window:

```python
app = App("Demo", docking=True)
app.popout("Signal viewer", lambda: signal_viewer(app.ctx, "emg"))
app.popout("Recording", lambda: recording_controls(app.ctx, classes, ...))
app.run()
```

Drag the tab outside the main OS window and it floats. Layout state persists in `.imgui_state/<App>.ini` so the next launch restores your arrangement.

`popout_panel(title, gui_fn)` is the inline fallback - it renders `gui_fn` directly inside `@app.ui` if docking is off, or creates a docked window if docking is on. Useful for big secondary panels (a training-log dashboard, a per-class trial preview) that you may want to tear off on multi-monitor setups.

!!! warning "Pop-outs are experimental on macOS"
    Retina viewport sizing of detached windows can be wrong on initial draw. Native dialogs (`pfd.open_file`) plus detached viewports may stack badly. Treat it as experimental until verified for your specific use case.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Calling `signal_viewer(ctx)` outside `@app.ui`.** It'll throw because no ImGui context is bound. Widgets only work inside the render frame.
- **Putting computation in the widget.** If you find yourself doing `np.fft.rfft(stream.get_window()[0])` inside a widget, move that to a thread (acquisition or predict) and stash the result on `ctx` or your own object.
- **Sharing state across widget instances accidentally.** If you need per-key state, use the keyed dict pattern. If two widgets can be on screen at once with different keys, make sure their state dict doesn't collide.
- **Reading `pipeline.predictions` mid-write.** `predictions` is a dict; widgets get a reference. Read scalar fields and you're fine. If you need a coherent snapshot, copy-on-read.
