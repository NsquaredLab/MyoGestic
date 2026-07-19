# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.2.0] - 2026-07-19

Signal-viewer overhaul for high-channel HD-EMG: a spatial channel selector, an
RMS-envelope display mode, and the performance work to make hundreds of channels
usable. Backward-compatible — old sessions still load.

### Added

- **Spatial channel-grid selector.** A compact bar opens a floating grid of
  cells laid out by electrode grid (showing the channel index); click to toggle,
  drag to rubber-band a rectangle, shift-click for a linear range. Replaces the
  one-button-per-channel wall.
- **Configurable RMS-envelope display** (`display = rms_env`) with adjustable
  **RMS window** and **RMS shift** — a sparse, scroll-stable trailing-RMS trace
  computed on the incoming signal. Visual-only (recording/model input unaffected).
- **`StreamInfo.channel_grids`** channel topology, persisted across session
  save/load so a replayed recording keeps its layout.
- **`signal_viewer(..., initial_channels=...)`** to bound the initially-enabled
  channel set so a 256-channel stream doesn't open as 256 lines.

### Changed

- **M4 display decimation now runs lazily on the render thread**, not on the
  acquire loop — where computing it for every channel ~60×/s starved
  high-channel-count acquisition and pinned the viewer's frame rate.
- **Viewer decimation rebuilt** as one vectorized shared-x MinMax over only the
  enabled channels, anchored to an absolute-time bucket grid (scroll-stable).
- **Per-channel viewer stats throttled** (~10 Hz) and computed without an
  all-column copy.

### Fixed

- **Windows:** retry zarr's chunk-rename on transient file locks (antivirus /
  search-indexer handles), fixing intermittent `PermissionError` crashes
  mid-recording.
- Guard the MinMax decimator against an out-of-memory blow-up on degenerate
  flat-timestamp runs (a device clock stall or a monotonic-clamped session).
- Size the M4 output scratch to the sample count instead of
  `n_out * n_channels` (~2 GiB → ~21 MB at 256 ch).

## [2.1.0] - 2026-06-07

Library reorganization, public-API standardization, and Windows session-save
reliability. The API changes are **breaking** but mostly mechanical renames —
old → new below.

### Changed

- **Reorganized into responsibility subpackages** (`sources`, `outputs`, `ml`,
  `recipes`, `session`, `vhi`, `widgets`, `bridges`). Most public imports are
  unchanged — thin facades re-export the same names — but a few moved:
  - `myogestic.interfaces` (VHI) → `myogestic.vhi`
  - `myogestic.contrib.*` and `myogestic.models.*` → `myogestic.recipes`
    (feature recipes `myogestic.recipes.features`; estimator recipes
    `myogestic.recipes.estimators`)
  - model persistence: `myogestic.models.save_model` / `load_model` →
    `myogestic.ml.save_pickle` / `load_pickle`
  - output-smoothing filters → `myogestic.outputs.filters` (also re-exported
    from `myogestic.outputs`); `EdgeTrigger` → `myogestic.outputs` (and still
    top-level `myogestic.EdgeTrigger`)

- **BREAKING — public parameters renamed** for a self-descriptive surface:
  durations now carry unit suffixes (`_ms` / `_s`), rates use `hz` / `*_hz`,
  counts use `n_`, and cryptic/abbreviated names are spelled out.

  *Streams & window extraction*
  - `Stream(window_seconds=, buffer_seconds=)` → `Stream(window_ms=, buffer_ms=)`
  - `iter_labeled_windows(win_seconds=, hop_seconds=)` → `(window_ms=, hop_ms=)`
  - `iter_aligned_windows(primary_stream=, aligned_streams=, win_seconds=, hop_seconds=, align_window_samples=)`
    → `(primary_stream_name=, aligned_stream_names=, window_ms=, hop_ms=, n_alignment_samples=)`
  - `signal_viewer(window_seconds=)` → `signal_viewer(window_s=)`

  *Session*
  - `Session.init_stream(name=)`, `Session.append(name=)` → `stream_name=`
  - `Session.get_trials(pre=, post=)` → `pre_s=, post_s=`

  *Filters & outputs*
  - `OneEuroFilter(freq=, min_cutoff=, d_cutoff=)` → `(hz=, min_cutoff_hz=, derivative_cutoff_hz=)`
  - `GaussianFilter(window=)` → `n_vectors=`
  - `make_filter(...)` forwards these kwargs, so `make_filter("one_euro", min_cutoff=, d_cutoff=)`
    → `min_cutoff_hz=, derivative_cutoff_hz=` and `make_filter("gaussian", window=)` → `n_vectors=`
  - filter `__call__(x, t=)` → `__call__(x, timestamp=)` (every filter and `FilterControl`)

  *Recipes & VHI*
  - `constant_classifier(class_idx=)` → `class_index=`
  - `InterfaceSpec`: `output_stream=/control_stream=/control_pose_stream=` →
    `*_stream_name=`; `output_channels=/control_channels=/control_pose_channels=` →
    `n_output_channels=/n_control_channels=/n_control_pose_channels=`
  - `virtual_hand(mode=)` → `launch_mode=`
  - `VhiMovementPanel(refresh_min_interval_s=)` → `min_interval_s=`

  *Widgets*
  - `template_inspector(uid=)`, `trial_preview(uid=)` → `widget_id=`
  - `trial_preview(window=)` → `as_window=`
  - `process_launcher(label=)`, `FilterControl.ui(label=)` → `widget_id=`
  - panel-heading `label=` → `title=` (`prediction_label`, `session_manager`,
    `vhi_movement_palette`, `VhiMovementPanel`)
  - `prediction_label(key=, proba_key=)` → `class_key=, probability_key=`
  - `FeatureSelector.set_active(on=)` → `active=`

  *CLI tools* (flag names unchanged — `--channels`, `--classes`, `--chunk`,
  `--control`): the Python params of `emg_generator` / `lsl_dummy` `main()`
  were renamed `channels`/`classes`/`chunk`/`control` →
  `n_channels`/`n_classes`/`chunk_size`/`control_stream_name`.

### Added

- Streams accept integer and float dtypes (`StreamInfo(dtype=...)`, default
  `float32`).
- `EdgeTrigger(n_stable_ticks=N)` debounce — fire only after a value holds for
  N consecutive ticks (swallows classifier flicker).
- Docstring coverage is enforced (ruff pydocstyle, NumPy convention): every
  public module, class, and function is documented.

### Fixed

- **Windows session saving**: finalizing a recording (`Session.pack_to_zip`)
  assumed POSIX file semantics and failed on Windows with
  `PermissionError: [WinError 32]` — open zarr / `ZipStore` handles can't be
  deleted or renamed there. Packing now releases handles, retries the folder
  cleanup, and uses `os.replace`, so saving a recording works on Windows.
- **Leaked session file handles**: reading a session (`open_session_store`,
  `ReplaySource`, `iter_labeled_windows` / `iter_aligned_windows`) left the
  `.session.zip` open, which locks the file on Windows. `Session` is now
  closeable (and usable as a context manager) and every reader releases the
  handle when it is done.
- **VHI connection robustness**: while the Virtual Hand is disconnected, the
  gRPC state poll backs off and uses a short probe deadline, and repeated
  failures are deduped/quieted — a closed or absent VHI no longer floods the log
  or stutters the render loop.

### Changed (internal)

- CLI tools (`emg_generator`, `lsl_dummy`, `install_vhi`, `webcam`) migrated
  from `argparse` to Typer.
- Tests + CI: documentation code blocks are parse-checked (and the tagged ones
  executed) and the example scripts are smoke-run, with the full test suite now
  running on Linux **and Windows** (previously CI only built the docs).

## [2.0.2] - 2026-06-03

### Fixed
- **Recording crash on Stop**: clicking Stop while data was still streaming could kill the per-stream acquisition thread with `KeyError: '<stream>'`. The acquire loop checked and used `Stream._session` outside any lock while `App.stop_recording()` nulled it and a daemon thread cleared the session's Zarr stores, so an append already in flight ran after the stores were gone. A new per-stream `Stream._session_lock` now makes attach/detach atomic with the acquire loop: `detach_session()` waits for any in-flight append before returning, so the subsequent pack-and-clear can no longer race. The lock is deliberately separate from the buffer/window lock used by UI-facing reads (`get_window()`, `last_timestamp()`), so disk writes never block the display path
- **Same-second session folder collision**: starting a new recording within the same wall-clock second as stopping the previous one could destroy the new recording. `Session.__init__` named the folder with a second-resolution timestamp and created it with `mkdir(exist_ok=True)`, so two sessions shared one folder and the first session's background `pack_to_zip()` (which deletes its own folder and writes `<name>.session.zip`) could remove or collide with the new session's data. Each session folder now gets a short `uuid4` suffix, so rapid same-second sessions no longer share a folder. The folder name is only used to derive the zip name and for display and logging, so the format change is safe
- **Silent loss masking**: `Session.append()` now drops a late append for a finalized stream and logs it at debug level instead of raising, as defense in depth around the teardown path

## [2.0.1] - 2026-05-17

### Changed
- **PyPI metadata republish**: re-released so PyPI picks up the README fix (absolute URLs for the image and for the docs and examples links). No code changes; the wheel content is identical apart from the metadata version and the embedded description

## [2.0.0] - 2026-05-17

### Added
- **v2 rewrite**: ground-up redesign of the framework, replacing v1 with a focus on small, composable API surfaces and live extensibility
- **Core primitives**: new App, Stream, Pipeline, and Source/Output building blocks. User code is plain decorated functions (`@app.ui`, `@pipeline.extract` / `train` / `predict`) with no base classes, registries, or config files
- **Real-time viewers**: signal viewers backed by a dvg-ringbuffer with M4 display decimation. Recording lands as a Zarr session zip
- **ML lifecycle**: train and predict run on dedicated threads (asyncio-cooperative under Pyodide)
- **UI toolkit**: Dear ImGui widgets via imgui-bundle, with a Px/Fr typed grid for layout
- **VHI integration**: gRPC plus LSL dual-plane integration with the Virtual Hand Interface

---

## Types of Changes
- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes
