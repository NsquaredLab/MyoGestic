# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0]
Documentation overhaul, Sphinx compatibility, and multi-VI support.

### Added
- **Multiple active Visual Interfaces** — Run several VIs simultaneously with shared task selector and unified recording controls.
- Ground truth source selector for multi-VI dataset creation.
- Sphinx-Gallery tutorial suite covering models, features, filters, output systems, and visual interface integration.
- Full API reference pages with autosummary for Config, Models, and Visual Interface modules.
- Default method stubs in `RecordingInterfaceTemplate` for easier VI development.

### Changed
- Refactored visual interface system architecture to support multiple active VIs.
- Re-enabled `autosummary_generate` by fixing PySide6 mock metaclass compatibility.
- Wrapped `catboost.get_gpu_device_count` to handle mocked imports during docs build.
- Rewrote all example files with Sphinx `:class:`, `:meth:`, and `:attr:` cross-references.

## [0.8.0]
Improved stability, UI enhancements, and new recording capabilities.

### Added
- Ctrl+C signal handling for graceful application shutdown.
- Default Recording Interface for recording without visual interface.

### Changed
- Improved main window UI layout and sizing.
- Updated visual interface UIs.
- Minor GUI improvements and fixes.
- Updated dependencies.
- Migrated biosignal-device-interface from git submodule to PyPI (>=0.2.4).

## [0.7.0]
Improved UI/UX and macOS compatibility.

### Added
- Logging moved to separate tab for better vertical space management.
- Tooltips throughout the UI explaining button functions and workflow steps.
- Status bar feedback messages for device connection and streaming actions.
- Visual hierarchy with color-coded buttons (Connect, Stream, active states).
- Placeholder widget in EMG plot area when device is not connected.
- macOS support for Virtual Hand Interface (automatic permissions and quarantine handling).

### Changed
- Platform-specific dependency overrides for torch and vispy on macOS.

## [0.6.0]
### Added
- Add a virtual cursor interface for foot movement control.

## [0.5.2]
### Changed
- Made it possible to train without having a visual interface open.

## [0.5.1]
### Changed
- Updated dependencies and sources in lockfile and config
- Replaced `myoverse` Git source with versioned PyPI source (`>=1.1.2`)
- Simplified `torch` and `torchvision` specifications by removing platform-specific markers and redundant configurations

## [0.5.0]
Enhanced Virtual Hand Interface integration and improved user experience.

### Added
- Updated UI and task options for Virtual Hand Interface.

### Changed
- Renamed gesture labels for clarity and consistency.
- Updated task labels for clarity in recording UI.

## [0.4.0]
Enhanced user interface and improved cross-platform compatibility.

### Added
- Changelog file to track project changes.
- Virtual Hand Interface integration with updated UI and task options.

### Changed
- Renamed gesture labels for clarity and consistency.
- Updated task labels for clarity in recording UI.
- Adjusted dataloader parameters for cross-platform compatibility.
- Adjusted multiprocessing settings for cross-platform compatibility.
- Updated MyoVerse to latest version with fixes.
- Fixed import paths for CONFIG_REGISTRY (@Mario200212)

### Removed
- Redundant parameters and dead code in dataset module.

[Unreleased]: https://github.com/NsquaredLab/MyoGestic/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/NsquaredLab/MyoGestic/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.1.0...v0.4.0
