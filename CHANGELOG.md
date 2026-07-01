# Changelog

All notable changes to PathSafe are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.4] - 2026-07-01

### Fixed
- `WinError 87` (The parameter is incorrect) crash on Windows when
  de-identifying slides on network shares, OneDrive, or cloud-synced
  folders. The `os.fsync()` calls added in v2.0.3 for blanking confirmation
  are now guarded; the `is_ifd_image_blanked()` re-read remains the
  authoritative safety check.
- `os.utime(path, (0, 0))` timestamp reset crash on FAT32/exFAT drives
  (common hospital USB media) where epoch-zero is not representable. Now
  warns instead of aborting.
- Staging file `os.open()` missing `O_BINARY` flag on Windows.

## [2.0.3] - 2026-06-08

### Fixed
- In-place de-identification false-clean on Windows: blanking write could
  fail to persist (OneDrive/network/locked handle) while the IFD-unlink
  succeeded, leaving the scanner reporting clean despite PHI still visible.
  Staging-copy + atomic replace prevents the original from ever being
  written directly.
- `is_ifd_image_blanked` now verifies every strip/tile (was first-strip-only),
  closing a multi-strip false-clean path. MRXS blanking streams the whole
  region.
- Label/macro IFD unlink is now gated on fsync + re-read confirmation of
  the blank; an unconfirmed blank raises instead of silently becoming a
  false-clean.
- Post-deidentification verify is authoritative: residual content PHI
  blocks staging promotion and exits non-zero. `DeidentificationResult.verified`
  is tri-state (`None`/`True`/`False`). CLI gains `--verify`/`--no-verify`
  (default on).

### Added
- Regression tests: `test_blank_all_strips`, `test_inplace_staging`,
  `test_verify_before_unlink`, `test_authoritative_verify`.
- On-demand `build-standalone` workflow producing a no-install Windows
  `.exe` artifact for pre-merge testing.

### Changed
- Bumped pinned third-party GitHub Actions to Node 24-compatible
  versions ahead of the 2026-06-02 forced upgrade:
  `softprops/action-gh-release` v2 -> v3.0.0 (runtime-only major bump
  per upstream release notes, no API changes) and
  `Minionguyjpro/Inno-Setup-Action` v1.2.4 -> v1.2.8.

## [2.0.2] - 2026-05-20

### Added
- Bisson Level IV conformance suite: 26 tests in
  `tests/test_bisson_conformance.py` mapped 1:1 to the criteria in Bisson
  et al. (2023), plus a per-criterion paper-to-code-to-test matrix in
  `docs/BISSON_CONFORMANCE.md`. Covers Levels I-IV for SVS, NDPI, MRXS,
  and BIF; Philips iSyntax is documented as a known gap; Level V is
  out of scope per the paper. Total test suite: 950 passing (was 924).
- MRXS PHI field coverage: `SCANNER_HARDWARE_ID`,
  `SLIDE_UTC_CREATIONDATETIME`, and `ProfileName` added to
  `GENERAL_PHI_FIELDS` to match Bisson Appendix A.
- BIF (Ventana) PHI attribute coverage for the older XML schema:
  `JP2FileName`, `UnitNumber`, `UserName`, `Barcode1D`, `Barcode2D`,
  `BaseName`, and `BuildDate` added to `XMP_PHI_ATTRIBUTES` alongside the
  existing modern iScan attribute set.

### Changed
- README Bisson conformance claim upgraded from soft "design intent"
  wording to a verified Level IV claim backed by the new conformance
  suite. A regression that breaks Level IV will now surface as a test
  failure.
- SECURITY.md updated to list the 2.0.x line as supported (was 1.1.0).

### Fixed
- GUI: the four Deidentify Options inputs (Institution plus three Filter
  files fields) clipped the descenders of the 14 px theme font because
  they used 28 px or Qt's compact default height. Minimum height set to
  32 px on all four so they match the surrounding combo boxes and
  buttons.
- Stale `master` branch references replaced with `main` in `SECURITY.md`,
  `CONTRIBUTING.md`, and `.github/workflows/test.yml` (the workflow
  previously triggered on `[master, main]` but `master` no longer
  exists).

## [2.0.1] - 2026-05-05

### Fixed
- PyInstaller spec referenced the pre-split `pathsafe/cli.py` path, breaking
  v2.0.0 installer builds on all platforms. Spec now points at
  `pathsafe/cli/__main__.py` and includes the new `pathsafe.cli.*` and
  `pathsafe.gui.*` submodules in `hiddenimports`.
- Conversion timing used `time.monotonic()` whose ~16 ms resolution on
  Windows could record 0.0 ms for fast operations and trip the
  `conversion_time_ms > 0` test. Switched to `time.perf_counter()`.

### Changed
- Bumped pinned GitHub Actions to Node 24-compatible versions ahead of the
  2026-06-02 forced upgrade (`actions/checkout` v6, `actions/setup-python`
  v6, `actions/upload-artifact` v7, `actions/download-artifact` v8).

## [2.0.0] - 2026-05-05

### Changed (BREAKING)
- Renamed every "anonymizer" / "anonymize" / "anonymization" identifier to
  the medically and regulatorially correct "de-identifier" / "deidentify"
  / "deidentification". HIPAA, DICOM PS3.15, and the medical literature
  all use de-identification; "anonymization" implies a mathematical
  irreversibility that this tool does not provide.
  - `pathsafe.anonymizer` -> `pathsafe.deidentifier`
  - `anonymize_file()` -> `deidentify_file()`
  - `anonymize_batch()` -> `deidentify_batch()`
  - `AnonymizationResult` -> `DeidentificationResult`
  - `pathsafe anonymize PATH` -> `pathsafe deidentify PATH`
  - Compliance-certificate JSON keys renamed accordingly.
  No compatibility shims; update scripts before upgrading.
- Markdown prose uses the hyphenated form (`de-identify`,
  `de-identifier`, `de-identification`); Python identifiers and the CLI
  subcommand use the unhyphenated form because Python identifiers cannot
  contain hyphens.
- Dropped "Production-tested" from the package description, CLI banner,
  and GUI About dialog.

### Added
- README now carries an explicit institution-pattern validation warning.
  The built-in regex patterns for accession-number detection were derived
  from one institution's formats; users must validate against their own
  accession schemes (and supply custom patterns via
  `--patterns custom_patterns.json` if needed).

### Fixed
- Auto-install icon and `.desktop` file on first Linux launch.
- 6 bugs found by code audit: PHI masking and GUI improvements.
- Mapping-row layout: tighter Skip combo with centered text.

### Internal
- Split `gui/window.py` (2047 lines) into a main shell plus
  `menus.py`, `dialogs.py`, `panels/deidentify_panel.py`, and
  `panels/convert_panel.py` mixins.
- Split `cli.py` (1334 lines) into a `pathsafe.cli` package with one
  module per subcommand.

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

[Unreleased]: https://github.com/DrSoma/PathSafe/compare/v2.0.3...HEAD
[2.0.3]: https://github.com/DrSoma/PathSafe/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/DrSoma/PathSafe/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/DrSoma/PathSafe/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/DrSoma/PathSafe/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/DrSoma/PathSafe/compare/v1.0.4...v1.1.0
[1.0.4]: https://github.com/DrSoma/PathSafe/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/DrSoma/PathSafe/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/DrSoma/PathSafe/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/DrSoma/PathSafe/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/DrSoma/PathSafe/releases/tag/v1.0.0
