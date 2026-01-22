# Contributing to Network Monitor

Thank you for your interest in contributing to Network Monitor! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions. We welcome contributors of all experience levels.

## Getting Started

### Prerequisites

- macOS 10.14 or later
- Python 3.9 or later
- Git

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/JohannesMahne/network-monitor.git
   cd network-monitor
   ```

2. **Create a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

4. **Install pre-commit hooks**
   ```bash
   pre-commit install
   ```

5. **Run the application**
   ```bash
   python network_monitor.py
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=monitor --cov=storage --cov=service --cov=config --cov=app

# Run specific test file
pytest tests/test_scanner.py

# Run with verbose output
pytest -v
```

### Code Quality

We use several tools to maintain code quality:

- **Black** - Code formatting
- **Ruff** - Linting (replaces flake8, isort, etc.)
- **MyPy** - Type checking
- **Bandit** - Security scanning

Run all checks manually:
```bash
# Format code
black .

# Lint
ruff check . --fix

# Type check
mypy monitor storage service config app

# Security scan
bandit -r monitor storage service config app -c pyproject.toml
```

Or let pre-commit run them automatically on commit:
```bash
pre-commit run --all-files
```

### Project Structure

```
network-monitor/
├── app/                    # UI components (menu bar, views)
│   └── views/              # Menu builders and icons
├── config/                 # Configuration and constants
├── monitor/                # Core monitoring logic
│   ├── connection.py       # Network connection tracking
│   ├── issues.py           # Issue detection
│   ├── network.py          # Network interface utilities
│   ├── scanner.py          # Device discovery
│   └── traffic.py          # Traffic monitoring
├── service/                # System services
│   └── launch_agent.py     # Launch at Login
├── storage/                # Data persistence
│   ├── json_store.py       # JSON storage backend
│   ├── settings.py         # User settings
│   └── sqlite_store.py     # SQLite storage backend
├── tests/                  # Test suite
└── network_monitor.py      # Main entry point
```

## Making Changes

### Branch Naming

Use descriptive branch names:
- `feature/device-scanner-improvements`
- `fix/memory-leak-in-traffic-monitor`
- `docs/update-readme`

### Commit Messages

Write clear, concise commit messages:
- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Fix bug" not "Fixes bug")
- Reference issues when applicable ("Fix #123: Resolve crash on startup")

Example:
```
Add lazy hostname resolution for device scanner

- Resolve hostnames in background thread
- Prioritize visible devices for resolution
- Add request_hostname_resolution() API for on-demand lookup
```

### Pull Requests

1. **Create a feature branch** from `main`
2. **Make your changes** with appropriate tests
3. **Ensure all tests pass** (`pytest`)
4. **Ensure code quality checks pass** (`pre-commit run --all-files`)
5. **Push your branch** and open a Pull Request
6. **Fill out the PR template** with:
   - Summary of changes
   - Related issues
   - Test plan

### Code Style Guidelines

- Follow PEP 8 (enforced by Black and Ruff)
- Use type hints for function signatures
- Write docstrings for public functions and classes
- Keep functions focused and under 50 lines when possible
- Prefer composition over inheritance

### Testing Guidelines

- Write tests for new features
- Maintain or improve code coverage
- Use meaningful test names that describe the behavior
- Use fixtures for common test setup
- Mock external dependencies (subprocess, network, filesystem)

## Reporting Issues

When reporting bugs, please include:
- macOS version
- Python version
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output (from `~/.network-monitor/`)

## Questions?

Feel free to open an issue for questions or discussions about potential contributions.
