# Changelog

All notable changes to PathSafe are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Auto-install icon and `.desktop` file on first Linux launch
- 6 bugs found by code audit: PHI masking and GUI improvements
- Mapping row layout: tighter Skip combo with centered text

## [1.1.0] - 2026-03-17

### Added
- File renaming and serialization: auto-sequential, CSV mapping, and custom template patterns
- Auto-worker detection (defaults to optimal thread count based on CPU cores)
- Update checker with toast notifications (opt-in, disabled by default, sends no file data)
- ARM64 Linux support (AppImage)
- Dynamic PDF report columns (adapts to findings)
- Type annotations across all modules
- DICOM lazy loading for faster startup

### Changed
- Removed `--verify` flag from CLI; users can re-scan output folder instead

### Fixed
- Mapping row layout alignment in GUI
- Hardened error handling across all format handlers

## [1.0.4] - 2026-03-01

### Added
- Phase-level progress reporting in GUI and CLI
- Optional SHA-256 checksum generation (`--checksum` flag)

### Changed
- I/O concurrency cap for stability on slower storage
- Performance improvements for large batch processing

### Fixed
- README: clarified that verify is CLI-only, not a GUI option

## [1.0.3] - 2026-02-28

### Added
- Detailed findings in de-identification certificates (specific PHI found per file and replacement values, matching scan report detail level)
- Independent verification script (`tools/independent_scanner.py`) for third-party validation
- Cross-platform uninstallation instructions

### Fixed
- Flaky PDF size comparison in test (`test_empty_institution_same_as_omitted`): replaced exact byte comparison with 5-byte tolerance

## [1.0.2] - 2026-02-22

### Added
- PyPI publish workflow with trusted publisher configuration
- Windows installer (`PathSafe-Setup.exe`) via build workflow
- Platform-specific icons for Windows, macOS, and Linux builds
- Release build workflow for native installers
- GitHub community standards templates (CODE_OF_CONDUCT, CONTRIBUTING, SECURITY)

### Changed
- Clarified CLI vs GUI dependency installation in README
- CLI version tests now use dynamic version detection

### Fixed
- macOS app bundle CLI/GUI executable collision
- Desktop file line endings and category for AppImage build
- Shell script line endings for macOS and Linux builds
- DICOM test failures on Python 3.9
- CI: installed optional deps, deduplicated Python 3.12 run, fixed stale tiff.py refs
- Converter tests skipped gracefully when tifffile is not installed
- Nested f-string syntax error on Python 3.11

## [1.0.1] - 2026-02-19

### Added
- EXIF, GPS, and ICC profile scanning and blanking across all TIFF-based formats
- PDF scan reports (`--report` flag)
- GUI improvements: convert tab with binary tile sizes, output validation, bundled deps
- Comprehensive test suite: 60 to 593 tests (unit, integration, adversarial, bypass, roundtrip, CLI, stress)
- Label/macro IFD unlinking from TIFF chain after blanking

### Fixed
- 5 critical PHI detection gaps (pre-production audit)
- 7 high-severity PHI detection gaps
- 6 medium-severity PHI detection issues
- 3 low-severity findings
- 9 fail-safety and error-handling bugs
- SCN false positive in test suite
- Convert tab: binary tile sizes and auto-reset timestamps

### Security
- Comprehensive PHI detection audit: fixed 18 issues across all formats
- Added EXIF sub-IFD, GPS sub-IFD, and ICC profile tag scanning to prevent metadata leakage

## [1.0.0] - 2026-02-15

### Added
- Initial release
- NDPI (Hamamatsu), SVS (Aperio), MRXS (3DHISTECH), BIF (Roche/Ventana), SCN (Leica), DICOM WSI, and generic TIFF support
- Label and macro image blanking
- Accession number pattern detection via regex
- Qt GUI with 5-step workflow panel
- CLI with `scan`, `deidentify`, `verify`, `convert`, `info`, and `gui` commands
- Compliance certificate generation (JSON + PDF)
- Copy mode (default) and in-place mode
- Light/dark theme toggle
- Standalone builds for Windows, macOS, and Linux
- Apache 2.0 license

[Unreleased]: https://github.com/DrSoma/PathSafe/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/DrSoma/PathSafe/compare/v1.0.4...v1.1.0
[1.0.4]: https://github.com/DrSoma/PathSafe/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/DrSoma/PathSafe/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/DrSoma/PathSafe/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/DrSoma/PathSafe/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/DrSoma/PathSafe/releases/tag/v1.0.0
