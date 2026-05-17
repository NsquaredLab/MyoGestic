# Add a custom widget

A widget is a function. The "register" step is calling it inside `@app.ui` - there's no list to add to, no class to subclass, no decorator.

## The simplest widget

```python
from imgui_bundle import imgui


def hello_widget(ctx) -> None:
    imgui.text("Hello, MyoGestic!")
    if imgui.button("Reset"):
        ctx.status_message = "reset clicked"
```

Use it:

```python
@app.ui
def ui(ctx):
    hello_widget(ctx)
    signal_viewer(ctx, "emg")
```

That's the whole pattern.

## A widget that reads streams

```python
import numpy as np
from imgui_bundle import imgui


def channel_rms_bar(ctx, stream: str = "emg") -> None:
    """Bar chart of per-channel RMS over the current window."""
    s = ctx.streams.get(stream)
    if s is None:
        imgui.text_disabled(f"stream '{stream}' not found")
        return
    data, _ = s.get_window()  # (n_channels, n_samples)
    if data.size == 0:
        imgui.text_disabled("buffer empty")
        return
    rms = np.sqrt(np.mean(data**2, axis=1))
    rms_norm = rms / (rms.max() + 1e-9)
    for ch, val in enumerate(rms_norm):
        imgui.text(f"ch {ch:2d}")
        imgui.same_line()
        imgui.progress_bar(float(val), imgui.ImVec2(120, 0), f"{rms[ch]:.3f}")
```

Drop it inside `@app.ui` and you have a live RMS bar chart.

## When you need state

Most widgets are stateless. When they aren't - selected channel set, scroll offset, popup open/closed - keep state in a **private module** keyed by widget identity:

```text
myogestic/widgets/
├── my_widget.py            # public - def my_widget(ctx, key, ...)
└── _my_widget_state.py     # private - state dict
```

`_my_widget_state.py`:

```python
from dataclasses import dataclass, field


@dataclass
class _State:
    visible: set[int] = field(default_factory=set)
    scroll: float = 0.0


_states: dict[str, _State] = {}


def get_state(key: str) -> _State:
    return _states.setdefault(key, _State())
```

`my_widget.py`:

```python
from imgui_bundle import imgui
from myogestic.widgets._my_widget_state import get_state


def my_widget(ctx, key: str = "default") -> None:
    s = get_state(key)
    # use s.visible, s.scroll, …
```

The keying matters: two `my_widget(ctx, key="emg")` calls share state; `my_widget(ctx, key="imu")` is independent.

!!! tip
    For widgets that always go with a stream, use `stream_name` as the key. The signal viewer does this - `signal_viewer(ctx, "emg")` and `signal_viewer(ctx, "imu")` get separate channel toggle sets automatically.

## Splitting a widget across files

If a widget grows past ~200 LOC, split it. Use the [`signal_viewer` layout](https://github.com/NsquaredLab/MyoGestic/tree/main/myogestic/widgets) as a template:

```text
myogestic/widgets/signal.py                   # public entry - calls into the privates
myogestic/widgets/_signal_viewer_state.py     # state dict, dataclass
myogestic/widgets/_signal_viewer_controls.py  # control panel rendering
myogestic/widgets/_signal_viewer_plot.py      # plot rendering
```

Public function lives in one file. Private modules are explicitly underscore-prefixed and *not* exported from `myogestic.widgets.__init__`. User code never imports them.

## Exporting your widget

Edit `myogestic/widgets/__init__.py`:

```python
from myogestic.widgets.my_widget import my_widget

__all__ = [..., "my_widget"]
```

Now `from myogestic.widgets import my_widget` works.

## Reading from `Pipeline` predictions

For widgets that visualise model output:

```python
def prediction_label(pipeline) -> None:
    if pipeline.model is None:
        imgui.text_disabled("not trained")
        return
    pred = pipeline.predictions  # dict[str, Any] - what predict() last returned
    if not pred:
        imgui.text_disabled("no prediction yet")
        return
    cls = pred.get("class")
    imgui.text(f"Class: {cls}")
```

Read scalar fields directly. If you need a coherent snapshot of multiple fields (rare), `dict(pipeline.predictions)` copies cheaply.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Computing in the widget.** Heavy compute (FFT, convolution, model evaluation) belongs on the predict thread. Cache results on `ctx` or your own object; the widget just reads the cached value.
- **Calling `imgui.set_next_window_size(...)` inside a `Grid` cell.** The grid manages sizes; per-window calls fight it. If you need a non-grid window, render outside the grid and use `popout_panel` or `imgui.begin/end` directly.
- **Sharing state between unrelated widgets via module globals.** The `_<widget>_state.py` pattern keys by widget identity. Don't reach into another widget's state from yours.
- **Using mutable defaults in widget args.** Standard Python pitfall: `def my_widget(ctx, names=[])` shares the default list across every call. Use `names: list[str] | None = None` and `if names is None: names = []` inside.
