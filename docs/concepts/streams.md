---
title: "Streams"
---
A [`Stream`][myogestic.Stream] wraps a `Source` plus a fixed-memory ring buffer. It owns one daemon acquisition thread, exposes a window getter for predict code and bounded snapshot reads for widgets.

## The data shape contract

Sources and prediction use two array layouts.

| Where | Shape | Why |
|-------|-------|-----|
| Source `read()` returns | `(n_samples, n_channels)` | the common layout adapters return to `Stream` |
| Recording (Zarr) stores | `(n_samples, n_channels)` | append-friendly: each chunk extends the time axis |
| `Stream.get_window()` returns | `(n_channels, n_samples)` | channels-first - what feature extractors and ML models expect |
| `extract()` receives | `dict[str, np.ndarray]` channels-first | matches `get_window` |

The transpose happens at one edge, in `Stream.get_window()`. Source adapters should keep the upstream sample-major orientation so recording and replay stay consistent.

## Construction

```python
Stream(name, source, window_ms, buffer_ms=10000, notch_hz=0)
```

- `name` keys the stream into `ctx.streams[name]`.
- `source` is anything implementing the `Source` protocol (`connect`, `read`, `disconnect`).
- `window_ms` is the duration of `get_window()`'s slice. Values like 30 s are possible for slow-moving signals; set `buffer_ms` at least as large, or the read is limited to the buffered history.
- `buffer_ms` defaults to 10 s. The ring buffer stores this much past data so the predict thread always has a window to slice and `SignalViewer` can render the recent history.

`notch_hz=50` or `60` filters acquisition before both prediction and recording; `0` leaves it unchanged. This is separate from the viewer's display-only notch.

## Reading the buffer

### `get_window()` - for prediction

```python
data, ts = stream.get_window()
# data.shape == (n_channels, n_samples)
# ts.shape   == (n_samples,)        # pylsl.local_clock() values
```

Returns the most recent `window_ms` of data, channels-first and float32. Timestamps, and data for float32 streams, use reusable scratch storage; copy them to keep them past the next read. Pass the newest timestamp, `ts[-1]`, to stateful models with `model.step(emg, last_ts=ts[-1])` to detect stale ticks that repeat data when prediction runs faster than acquisition.

### `get_display(n_pixels)` - for widgets

```python
snapshot = stream.get_display(n_pixels=800)
if snapshot is not None:
    ts, data = snapshot
    # ts.shape == (n_points,)
    # data.shape == (n_points, n_channels)
```

Returns an on-demand full-history M4 snapshot, or `None` before two samples are available. The point count varies with the buffered data and the union of per-channel M4 selections. Widgets should request a bounded tail with `get_raw_snapshot_stable(duration_s)` and decimate it to their actual plot width, as `SignalViewer` does.

### `get_raw_snapshot()` - for diagnostics

```python
snapshot = stream.get_raw_snapshot()
if snapshot is not None:
    ts, data = snapshot
    # data.shape == (n_buffered, n_channels)
    # ts.shape   == (n_buffered,)
```

An on-demand contiguous snapshot of the buffered samples in their native orientation, or `None` before two samples are available. The returned arrays use reusable storage; copy them if they must survive another snapshot read. Most user code should prefer `get_window`, or `get_raw_snapshot_stable(duration_s)` when a stable recent tail is required. `RawSignalViewer` uses the latter so its work is bounded by the visible duration.

<a id="why-dvg-ringbuffer"></a>

## Ring buffer costs

[`dvg-ringbuffer`](https://github.com/Dennis-van-Gils/python-dvg-ringbuffer) bounds memory while acquisition runs indefinitely.

1. Constant acquisition cost. Appending a chunk never unwraps or copies the accumulated history.
2. Bounded consumer reads. `get_window()` copies only the prediction window and `SignalViewer` only its visible tail, even when the ring holds much more history.

A `threading.Lock` guards reads and writes; overhead is ~1–5 microseconds per access, negligible compared with each thread's workload.

## Lifecycle

You don't usually call `start()` / `stop()` directly:

```python
app = App("Demo")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))
app.run()  # starts every stream, runs the GUI, stops every stream on exit
```

Streams start detached. `start()` starts the acquisition loop, and `reconnect()` opens the source. Press Connect in the viewer or device picker, or call `stream.reconnect()` yourself. To retarget an LSL source:

```python
ctx.streams["emg"].reconnect(target="EMG_v2")
```

`reconnect` makes one connection attempt and reallocates the buffers for the returned geometry, clearing the previous history. The acquisition loop stays alive. It returns `False` if the attempt fails, another connection is in flight, or a session is attached. A `DevicePicker` can construct a different source when changing device types.

## Channel naming

Sources may auto-discover channel names; if so, they appear in [`StreamInfo`][myogestic.StreamInfo]`.channel_names`:

```python
info = stream.info  # StreamInfo
info.n_channels  # 64
info.fs  # 2048.0
info.channel_names  # ["EMG_01", "EMG_02", ...] or None
```

`SignalViewer` uses these names in its channel toggle list. If a source returns `None`, names default to `"ch0"`, `"ch1"`, …

## Reading the waveform, not the envelope

`SignalViewer` MinMax decimation keeps each bucket's minimum and maximum. Shape and onset timing *within* a bucket can still coarsen. At 2 kHz over a 5 s window on a 600 px plot that bucket is about 5 ms, which is
also roughly one pixel, so the trace is as faithful as the display can be.

To read a single motor-unit action potential shorter than that, turn decimation off. Increasing Detail is insufficient.
Detail is limited to a few points per pixel to bound rendering work. The
1:1 toggle beside it removes decimation.

| Want | Use |
|---|---|
| Amplitude, bursts, envelope | Use MinMax to preserve each bucket's extrema |
| Waveform shape below ~5 ms | 1:1, or shorten the window until the Display readout says `(raw)` |
| Every sample, always, no toggle | [`RawSignalViewer`][myogestic.widgets.RawSignalViewer] |

Open Display for the point-count readout. `MinMax 10,000→1,802 pts/ch` against
`10,000 pts/ch (raw)`. Shortening the window reaches `(raw)` on its own, because
decimation stops once the window fits the point budget. At 600 px and full Detail that
is a 0.9 s window at 2 kHz.

1:1 refuses to turn on, and turns itself off, above 250,000 points per frame across the drawn channels.
At 64 channels of 2 kHz over 10 s, the frame contains 1.3 M points, exceeding detail a display
can resolve. Hover the toggle for the count at your current settings.

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for symptoms and fixes.

- Confusing window vs. buffer. `window_ms` is what `get_window` returns; `buffer_ms` is how much history the buffer holds. Set `buffer_ms` to retain longer history, such as a 30 s signal viewer with a 1 s prediction window.
- Forgetting the transpose. If you write a Source adapter and accidentally return `(n_channels, n_samples)`, the recording layer will write a Zarr array shaped wrong and replay won't match. Stay sample-major in the source.
- Computing on the display path. `get_display` is decimated. For features, always use `get_window`.
