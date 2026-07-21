# Add a custom widget

A widget is a class with a `.ui()` method. You construct it once, then call `.ui(...)` inside `@app.ui` each frame. There's no list to register with, no base class to subclass, no decorator.

## The simplest widget

```python
from imgui_bundle import imgui


class HelloWidget:
    def ui(self, ctx) -> None:
        imgui.text("Hello, MyoGestic!")
        if imgui.button("Reset"):
            ctx.status_message = "reset clicked"
```

Use it — build once, render each frame:

```python
hello = HelloWidget()
viewer = SignalViewer("emg")


@app.ui
def ui(ctx):
    hello.ui(ctx)
    viewer.ui(ctx)
```

That's the whole pattern.

## A widget that reads streams

Configuration (the stream name) goes to `__init__`; the live `ctx` is passed to `.ui()` each frame:

```python
import numpy as np
from imgui_bundle import imgui


class ChannelRmsBar:
    """Bar chart of per-channel RMS over the current window."""

    def __init__(self, stream: str = "emg") -> None:
        self._stream = stream

    def ui(self, ctx) -> None:
        s = ctx.streams.get(self._stream)
        if s is None:
            imgui.text_disabled(f"stream '{self._stream}' not found")
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

`bar = ChannelRmsBar("emg")` once, then `bar.ui(ctx)` inside `@app.ui`, and you have a live RMS bar chart.

## When you need state

Persistent UI state — selected channels, scroll offset, popup open/closed — lives as instance attributes. Because you construct the widget once and keep the instance, the state survives across frames for free:

```python
class ChannelPicker:
    def __init__(self, stream: str = "emg") -> None:
        self._stream = stream
        self._visible: set[int] = set()   # persists across frames

    def ui(self, ctx) -> None:
        s = ctx.streams.get(self._stream)
        if s is None or s.info is None:
            return
        for ch in range(s.info.n_channels):
            on = ch in self._visible
            changed, on = imgui.checkbox(f"ch {ch}", on)
            if changed:
                self._visible = self._visible | {ch} if on else self._visible - {ch}
```

Two independent `ChannelPicker("emg")` and `ChannelPicker("imu")` instances keep separate state automatically — they're separate objects.

!!! tip "Sharing state across widgets"
    A few caches are deliberately shared — e.g. the stream discovery/scan cache is shared by `SignalViewer`, `RawSignalViewer`, and `StreamPanel` so a scan started in one shows up in the others. Those stay in a module-level dict keyed by stream name. Reach for that only when widgets genuinely need to coordinate; instance attributes are the default.

## Splitting a widget across files

If a widget grows past ~200 LOC, split it. Use the [`SignalViewer` layout](https://github.com/NsquaredLab/MyoGestic/tree/main/myogestic/widgets) as a template:

```text
myogestic/widgets/signals/viewer.py           # public class SignalViewer - calls into the privates
myogestic/widgets/signals/_state.py           # per-stream state dataclass
myogestic/widgets/signals/_controls.py        # control panel rendering
myogestic/widgets/signals/_plot.py            # plot rendering
```

The public class lives in one file. Private modules are explicitly underscore-prefixed and *not* exported from `myogestic.widgets.__init__`. User code never imports them.

## Exporting your widget

Edit `myogestic/widgets/__init__.py`:

```python
from myogestic.widgets.my_widget import MyWidget

__all__ = [..., "MyWidget"]
```

Now `from myogestic.widgets import MyWidget` works.

## Reading from `Pipeline` predictions

For widgets that visualise model output, hold the `pipeline` in the constructor (it's a stable object) and read its live `predictions` in `.ui()`:

```python
class SimplePrediction:
    def __init__(self, pipeline) -> None:
        self._pipeline = pipeline

    def ui(self) -> None:
        if self._pipeline.model is None:
            imgui.text_disabled("not trained")
            return
        pred = self._pipeline.predictions  # dict[str, Any] - what predict() last returned
        if not pred:
            imgui.text_disabled("no prediction yet")
            return
        imgui.text(f"Class: {pred.get('class')}")
```

Read scalar fields directly. If you need a coherent snapshot of multiple fields (rare), `dict(self._pipeline.predictions)` copies cheaply.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Constructing the widget inside `@app.ui`.** `MyWidget().ui(ctx)` in the frame loop rebuilds it every frame and resets its state. Build it once, outside the render function.
- **Capturing `ctx` or a `Stream` in `__init__`.** `ctx.streams` is populated (and mutated on reconnect) after construction, so re-read `ctx.streams.get(name)` fresh each frame in `.ui(ctx)` instead of holding a `Stream`.
- **Computing in the widget.** Heavy compute (FFT, convolution, model evaluation) belongs on the predict thread. Cache results on `ctx` or your own object; `.ui()` just reads the cached value.
- **Calling `imgui.set_next_window_size(...)` inside a `Grid` cell.** The grid manages sizes; per-window calls fight it. If you need a non-grid window, render outside the grid and use `popout_panel` or `imgui.begin/end` directly.
- **Using mutable defaults in the constructor.** Standard Python pitfall: `def __init__(self, names=[])` shares the default list across instances. Use `names: list[str] | None = None` and `if names is None: names = []` inside.
