# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/NsquaredLab/MyoGestic/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/NsquaredLab/MyoGestic/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/NsquaredLab/MyoGestic/compare/v0.1.0...v0.4.0
