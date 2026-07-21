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

Returns a min/max envelope decimated to `n_pixels` columns - typical screen widths land at 300–1500. 64 channels at 2048 Hz with `window_ms=10000` is 64 × 2 × 800 = ~102K points, which ImPlot draws at 60 fps without breaking a sweat. The decimation uses [tsdownsample](https://github.com/predict-idlab/tsdownsample)'s M4 algorithm under the hood - preserves visual peaks without sub-sampling artefacts.

### `get_raw_snapshot()` - for diagnostics

```python
ts, data = stream.get_raw_snapshot()
# data.shape == (capacity, n_channels)
# ts.shape   == (capacity,)
```

The full ring-buffer contents in their native orientation. Used by `RawSignalViewer` for zero-allocation rendering of every sample. Most user code should prefer `get_window` or `get_display`.

## Why dvg-ringbuffer

The ring buffer ([`dvg-ringbuffer`](https://github.com/Dennis-van-Gils/python-dvg-ringbuffer)) keeps a fixed memory address once full. That matters for two reasons:

1. **Zero-copy reads when full.** No `np.copy` cost on every `get_window` call.
2. **JIT-friendly.** Numba compiles against a stable address, so any JIT-compiled feature extractor gets a fixed buffer to work against.

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

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Confusing window vs. buffer.** `window_ms` is what `get_window` returns; `buffer_ms` is how much history the buffer holds. The latter only matters if you want to look back further than a window (e.g. for a 30 s signal viewer with a 1 s prediction window).
- **Forgetting the transpose.** If you sub-class a Source and accidentally return `(n_channels, n_samples)`, the recording layer will write a Zarr array shaped wrong and replay won't match. Stay sample-major in the source.
- **Computing on the display path.** `get_display` is decimated. For features, always use `get_window`.
