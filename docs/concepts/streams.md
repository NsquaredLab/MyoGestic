# Streams

A [`Stream`][myogestic.Stream] wraps a `Source` plus a fixed-memory ring buffer. It owns one daemon acquisition thread, exposes one window-getter for predict code, and one decimated display getter for widgets.

## The data shape contract

There are two coordinate systems, and they're easy to mix up:

| Where | Shape | Why |
|-------|-------|-----|
| Source `read()` returns | `(n_samples, n_channels)` | sample-major matches LSL, BrainFlow, BDI, BLE - every transport in the wild |
| Recording (Zarr) stores | `(n_samples, n_channels)` | append-friendly: each chunk extends the time axis |
| `Stream.get_window()` returns | `(n_channels, n_samples)` | **channels-first** - what feature extractors and ML models expect |
| `extract()` receives | `dict[str, np.ndarray]` channels-first | matches `get_window` |

The transpose happens at one edge, in `Stream.get_window()`. New source adapters should keep the upstream sample-major orientation so recording and replay stay consistent.

## Construction

```python
Stream(name, source, window_ms, buffer_ms=10000)
```

- `name` keys the stream into `ctx.streams[name]`.
- `source` is anything implementing the `Source` protocol (`connect`, `read`, `disconnect`).
- `window_ms` is the duration of `get_window()`'s slice. There's no upper bound; values like 30 s are intentional for slow-moving signals.
- `buffer_ms` defaults to 10 s. The ring buffer stores this much past data so the predict thread always has a window to slice and `SignalViewer` can render the recent history.

## Reading the buffer

### `get_window()` - for prediction

```python
data, ts = stream.get_window()
# data.shape == (n_channels, n_samples)
# ts.shape   == (n_samples,)        # pylsl.local_clock() values
```

Returns the most recent `window_ms` of data, channels-first. `ts[-1]` is the timestamp of the newest sample - pass this into stateful models (e.g. `model.step(emg, last_ts=ts[-1])`) so they can detect stale ticks (predict thread firing faster than acquisition).

### `get_display(n_pixels)` - for widgets

```python
env_min, env_max = stream.get_display(n_pixels=800)
# both shape == (n_pixels, n_channels)
```

Returns an on-demand full-history M4 snapshot for compatibility. New widgets should request a bounded tail with `get_raw_snapshot_stable(duration_s)` and decimate it to their actual plot width, as `SignalViewer` does.

### `get_raw_snapshot()` - for diagnostics

```python
ts, data = stream.get_raw_snapshot()
# data.shape == (capacity, n_channels)
# ts.shape   == (capacity,)
```

An on-demand contiguous copy of the full ring-buffer contents in their native orientation. Most user code should prefer `get_window`, or `get_raw_snapshot_stable(duration_s)` when a stable recent tail is required. `RawSignalViewer` uses the latter so its work is bounded by the visible duration.

## Why dvg-ringbuffer

The ring buffer ([`dvg-ringbuffer`](https://github.com/Dennis-van-Gils/python-dvg-ringbuffer)) keeps memory bounded while acquisition runs indefinitely. That matters for two reasons:

1. **Constant acquisition cost.** Appending a chunk never unwraps or copies the accumulated history.
2. **Bounded consumer reads.** `get_window()` copies only the prediction window and `SignalViewer` only its visible tail, even when the ring holds much more history.

A `threading.Lock` guards reads and writes; overhead is ~1–5 microseconds per access - negligible compared to the actual work each thread does.

## Lifecycle

You don't usually call `start()` / `stop()` directly:

```python
app = App("Demo")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))
app.run()  # starts every stream, runs the GUI, stops every stream on exit
```

For dynamic device swaps:

```python
ctx.streams["emg"].reconnect(target=LSLSource("EMG_v2"))
```

`reconnect` stops the acquisition thread, swaps the source, and restarts cleanly. The ring buffer is preserved across the swap so `SignalViewer` doesn't blank.

## Channel naming

Sources may auto-discover channel names; if so, they appear in [`StreamInfo`][myogestic.StreamInfo]`.channel_names`:

```python
info = stream.info  # StreamInfo
info.n_channels  # 64
info.fs  # 2048.0
info.channel_names  # ["EMG_01", "EMG_02", ...] or None
```

`SignalViewer` uses these names in its channel toggle list. If a source returns `None`, names default to `"ch_0"`, `"ch_1"`, …

## Reading the waveform, not the envelope

`SignalViewer` MinMax-decimates: it keeps each bucket's **minimum and maximum**, so peak
height and burst timing are exact at any reduction — what coarsens is shape *within* a
bucket. At 2 kHz over a 5 s window on a 600 px plot that bucket is about 5 ms, which is
also roughly one pixel, so the trace is as faithful as the display can be.

Reading a feature shorter than that — a single motor-unit action potential — needs
decimation **off**, not turned up. **Detail** tops out at a few points per pixel by
design, because its ceiling is what stops a wide rig from stalling the frame rate. The
**1:1** toggle beside it removes the reduction entirely:

| Want | Use |
|---|---|
| Amplitude, bursts, envelope | Leave it alone — MinMax is exact for these |
| Waveform shape below ~5 ms | **1:1**, or shorten the window until the footer reads `(raw)` |
| Every sample, always, no toggle | [`RawSignalViewer`][myogestic.widgets.RawSignalViewer] |

The footer says which you are looking at: `MinMax 10,000→1,802 pts/ch` against
`10,000 pts/ch (raw)`. Shortening the window reaches `(raw)` on its own, because
decimation stops once the window fits the point budget — at 600 px and full Detail that
is a 0.9 s window at 2 kHz.

1:1 refuses, and turns itself back off, above 250,000 points per frame across the drawn
channels; 64 channels of 2 kHz over 10 s is 1.3 M points a frame for detail no display
can resolve. Hover the toggle for the count at your current settings.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Confusing window vs. buffer.** `window_ms` is what `get_window` returns; `buffer_ms` is how much history the buffer holds. The latter only matters if you want to look back further than a window (e.g. for a 30 s signal viewer with a 1 s prediction window).
- **Forgetting the transpose.** If you sub-class a Source and accidentally return `(n_channels, n_samples)`, the recording layer will write a Zarr array shaped wrong and replay won't match. Stay sample-major in the source.
- **Computing on the display path.** `get_display` is decimated. For features, always use `get_window`.
