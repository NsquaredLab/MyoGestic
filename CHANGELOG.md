# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.2] - 2026-06-03

### Fixed

- Recording no longer crashes the acquisition thread when Stop is clicked
  while data is still streaming. The acquire loop and session teardown are now
  synchronized through a dedicated per-stream lock, so an append already in
  flight cannot run after the session's Zarr stores have been cleared.
  Previously this raced and raised `KeyError: '<stream>'`, killing the acquire
  thread. The lock is separate from the buffer/window lock used by UI-facing
  reads, so disk writes never block the display path.
- Starting a new recording within the same wall-clock second as stopping the
  previous one no longer risks losing the new recording. Each session folder
  now gets a short unique suffix, so the previous session's background
  pack-and-zip step (which deletes its own folder) can no longer remove or
  collide with the new session's data.
- `Session.append()` now drops a late append for a finalized stream and logs it
  at debug level instead of raising, as defense in depth around the teardown
  path.

## [2.0.1] - 2026-05-17

### Changed

- Republished so PyPI picks up the README fix (absolute URLs for the image and
  for the docs and examples links). No code changes; the wheel content is
  identical apart from the metadata version and the embedded description.

## [2.0.0] - 2026-05-17

### Added

- Ground-up rewrite of the v2 line, replacing v1 with a redesign focused on
  small, composable API surfaces and live extensibility.
- New App, Stream, Pipeline, and Source/Output primitives. User code is plain
  decorated functions (`@app.ui`, `@pipeline.extract` / `train` / `predict`),
  with no base classes, registries, or config files.
- Real-time signal viewers backed by a dvg-ringbuffer with M4 display
  decimation. Recording lands as a Zarr session zip.
- ML pipeline lifecycle with train and predict on dedicated threads
  (asyncio-cooperative under Pyodide).
- Dear ImGui widgets via imgui-bundle, with a Px/Fr typed grid for layout.
- gRPC plus LSL dual-plane integration with the Virtual Hand Interface.

[2.0.2]: https://github.com/NsquaredLab/MyoGestic/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/NsquaredLab/MyoGestic/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/NsquaredLab/MyoGestic/releases/tag/v2.0.0
