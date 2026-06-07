# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Library reorganization + public-API standardization. These are **breaking**
changes; the migration is mostly mechanical (renames). Old → new below.

### Changed

- **Reorganized into responsibility subpackages** (`sources`, `outputs`, `ml`,
  `recipes`, `session`, `vhi`, `widgets`, `bridges`). Most public imports are
  unchanged — thin facades re-export the same names — but a few moved:
  - `myogestic.interfaces` (VHI) → `myogestic.vhi`
  - `myogestic.contrib.*` and `myogestic.models.*` → `myogestic.recipes`
    (feature recipes `myogestic.recipes.features`; estimator recipes
    `myogestic.recipes.estimators`)
  - model persistence (`save_pickle` / `load_pickle`) → `myogestic.ml`
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
  - filter `__call__(x, t=)` → `__call__(x, timestamp=)` (every filter and `FilterControl`)
  - `EdgeTrigger(stable_ticks=)` → `n_stable_ticks=`

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

### Changed (internal)

- CLI tools (`emg_generator`, `lsl_dummy`, `install_vhi`, `webcam`) migrated
  from `argparse` to Typer.

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
