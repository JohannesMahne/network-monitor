# Changelog

All notable changes to Network Monitor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI/CD pipeline for automated testing and builds
- CHANGELOG.md to track version history
- CONTRIBUTING.md with contributor guidelines
- Python 3.13 support

### Changed
- Updated pre-commit hook versions (black 24.10.0, ruff 0.9.2, mypy 1.14.1, bandit 1.9.0)
- Improved OUI database path detection (version-agnostic Homebrew Cellar search)
- Virtual environment detection now supports both `.venv/` and `venv/`

### Fixed
- Hardcoded arp-scan version in OUI database path

## [1.4.0] - 2026-01-15

### Added
- SQLite storage backend as default (replacing JSON)
- Subprocess caching for improved performance
- Lazy hostname resolution for better UI responsiveness
- mDNS/Bonjour service discovery for device identification

### Changed
- Migrated from JSON to SQLite for data persistence
- Improved device type inference from vendor and hostname patterns
- Better error handling in network scanning

### Fixed
- Memory leaks in long-running sessions
- Race conditions in concurrent device updates

## [1.3.0] - 2025-12-01

### Added
- Device scanner with MAC vendor lookup
- Custom device naming support
- Network issue detection (packet loss, latency spikes)

### Changed
- Improved traffic monitoring accuracy
- Better menu bar icon rendering

## [1.2.0] - 2025-10-15

### Added
- Traffic history graphs via matplotlib
- Settings persistence
- Launch at Login support via Launch Agent

### Changed
- Refactored code into modular packages

## [1.1.0] - 2025-09-01

### Added
- Network connection status monitoring
- Speed test integration
- Menu bar icon with status indicators

## [1.0.0] - 2025-08-01

### Added
- Initial release
- Basic network traffic monitoring
- macOS menu bar application
- Real-time upload/download speed display
