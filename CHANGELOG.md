# Changelog

All notable changes to Network Monitor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.7.1] - 2026-01-23

### Changed
- WiFi signal strength indicator now uses diamond prefix (◆●●●) for consistent visual style

## [1.7.0] - 2026-01-23

### Added
- BandwidthMonitor for per-app bandwidth throttling detection and alerts
- DNSMonitor for DNS performance monitoring and slow DNS alerts
- GeolocationService for IP country lookups with caching
- ConnectionTracker for tracking external connections per app
- Comprehensive test suites for all new monitoring components
- New constants: DNS_CHECK_INTERVAL, DNS_SLOW_THRESHOLD_MS in NetworkConfig

### Changed
- AppDependencies now includes bandwidth_monitor, dns_monitor, geolocation_service, and connection_tracker
- Improved test coverage for new modules (97%, 100%, 94%, 93% respectively)
- Updated test fixtures to include new dependency fields

### Fixed
- Test failures due to missing dependency fields in AppDependencies constructor

## [1.6.0] - 2026-01-22

### Added
- Python 3.13 compatibility improvements

### Changed
- Minor code quality improvements

## [1.5.0] - 2026-01-22

### Added
- AppController for business logic orchestration with dependency injection
- EventBus for decoupled component communication (pub/sub pattern)
- MenuAwareTimer extracted to `app/timer.py` for better modularity
- SingletonLock extracted to `config/singleton.py` for reusability
- Comprehensive test fixtures in `tests/conftest.py` for common mocking patterns
- Integration test suite with pytest markers (unit, integration, slow)
- New tests for ConnectionDetector, MenuBuilder, NetworkScanner, and dependencies
- GitHub Actions CI now fails on coverage regression below 65%

### Changed
- Wired AppController into main NetworkMonitorApp for cleaner architecture
- Test coverage improved from 65% to 69%
- `menu_builder.py` coverage: 30% → 92%
- `dependencies.py` coverage: 41% → 96%
- `connection.py` coverage: 49% → 69%
- `network.py` coverage: 59% → 94%
- Added pytest warning filters for matplotlib deprecation warnings
- Improved documentation and consistency (British English, clarified install/dev instructions)

### Fixed
- Event subscription pattern now properly connects controller events to UI updates

## [1.4.0] - 2026-01-15

### Added
- SQLite storage backend as default (replacing JSON)
- Subprocess caching for improved performance
- Lazy hostname resolution for better UI responsiveness
- mDNS/Bonjour service discovery for device identification
- Python 3.13 support

### Changed
- Migrated from JSON to SQLite for data persistence
- Improved device type inference from vendor and hostname patterns
- Better error handling in network scanning
- Improved OUI database path detection (version-agnostic Homebrew Cellar search)
- Virtual environment detection now supports both `.venv/` and `venv/`
- Updated pre-commit hook versions (black 24.10.0, ruff 0.9.2, mypy 1.14.1, bandit 1.9.0)

### Fixed
- Memory leaks in long-running sessions
- Race conditions in concurrent device updates
- Hardcoded arp-scan version in OUI database path

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
