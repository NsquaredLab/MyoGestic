# Bridges

A `Bridge` is a subprocess MyoGestic spawns alongside the app for **heavy-data acquisition that doesn't fit the LSL pull model** - typically a webcam decoder that writes frames straight to Zarr and publishes an LSL clock outlet so the rest of the app can align timestamps.

Bridges are registered via `app.bridges(...)`, started before the GUI loop, and terminated as part of `App.run()`'s cleanup hook chain.

::: myogestic.bridges.Bridge

::: myogestic.bridges.WebCamBridge

::: myogestic.bridges.CustomBridge

## The webcam runner

`WebCamBridge` invokes `python -m myogestic.bridges.webcam` as a subprocess. The same runner can be launched directly for testing:

```bash
uv run python -m myogestic.bridges.webcam --device 0 --zarr session/cam.zarr --lsl-name webcam_clock
```

Flags:

- `--device N` - OpenCV device index (default `0`).
- `--zarr PATH` - where to write the Zarr array. Frames are appended one chunk per capture.
- `--lsl-name NAME` - LSL outlet name for the per-frame timestamp clock; the app subscribes to this to align webcam frames with EMG.
