# Network Monitor for macOS

A lightweight menu bar application that monitors network traffic, tracks daily usage per connection (WiFi/Ethernet), displays real-time speeds, discovers devices on your network, and logs connectivity issues.

## Features

### Core Monitoring
- **Menu Bar Display**: Shows latency, speeds, or device count with color-coded status icon
- **Traffic Breakdown by App**: See which applications are using your bandwidth
  - Real-time process-level traffic monitoring
  - Shows bytes in/out per application
  - Identifies apps by friendly names (Chrome, Slack, Spotify, etc.)
- **Network Device Discovery**: Discovers and tracks devices on your local network
  - Shows online/offline status with device type icons
  - Identifies device vendors (Apple, Samsung, Google, etc.)
  - Custom device naming with persistence
  - mDNS/Bonjour service discovery

### Statistics & History
- **Per-Connection Tracking**: Tracks usage separately for each WiFi network (by SSID) and Ethernet
- **Daily Statistics**: Persists daily totals across app restarts
- **Usage History**: Weekly, monthly, and per-connection breakdowns
- **Data Budgets**: Set data limits per connection with notifications

### Network Quality
- **Latency Monitor**: Real-time ping with color-coded status
- **Network Quality Score**: 0-100% score based on latency, jitter, and consistency
- **VPN Detection**: Automatically detects active VPN connections
- **Issue Detection**: Connection drops, high latency, speed drops, quality degradation

### Data Management (v1.2)
- **SQLite Storage**: Efficient storage for historical data queries
- **Automatic Cleanup**: Configurable data retention (default: 90 days)
- **Backup & Restore**: Create and restore database backups
- **Export**: Export data to CSV or JSON format

### System Integration
- **Launch at Login**: Toggle auto-start via LaunchAgent
- **Adaptive Updates**: Faster updates during high activity, slower when idle

## Requirements

- macOS (tested on macOS 14+)
- Python 3.9+

## Installation

1. **Clone or download this folder**

2. **Create virtual environment and install dependencies**:
   ```bash
   cd network-monitor
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python network_monitor.py
   ```

   Or use the convenience script:
   ```bash
   ./run.sh
   ```

### Device Identification

Devices are identified using multiple sources:

1. **Custom names** (highest priority) - Names you assign manually
2. **mDNS/Bonjour** - Discovers device names via network services (e.g., "Kitchen", "Johannes's MacBook")
3. **IEEE OUI Database** - 47,000+ vendor entries from MAC address prefixes
4. **Fingerprinting** - Device type inference from vendor + hostname patterns
5. **Hostname** - DNS name resolution
6. **IP address** (fallback)

**To name a device:**
- Click on any device in the **Devices** menu
- Enter a custom name (e.g., "Living Room TV", "Dad's iPhone")
- Names are saved to `~/.network-monitor/device_names.json`

**Device type icons:**
| Icon | Type | Examples |
|------|------|----------|
| 📱 | Phone | iPhone, Galaxy, Pixel |
| 💻 | Laptop | MacBook, Surface |
| 🖥️ | Desktop | iMac, Mac Mini, Intel PC |
| 📺 | TV | Roku, Chromecast, Apple TV |
| 🔊 | Speaker | Sonos, HomePod |
| 🔌 | IoT | ESP32, Tuya, smart plugs |
| 📡 | Router | Huawei, Netgear, TP-Link |
| 🖨️ | Printer | Epson, HP, Canon |
| 🎮 | Gaming | PlayStation, Xbox |
| 📷 | Camera | Ring, Wyze, Arlo |

### Optional: Install arp-scan for Better Vendor Database

The app uses the IEEE OUI database from `arp-scan` for vendor lookup:

```bash
brew install arp-scan
```

This provides 47,000+ vendor entries for accurate device identification. Without it, the app falls back to a smaller built-in database.

## Usage

Once running, the app appears in your menu bar showing current upload/download speeds and device count:

```
↑1.2 MB/s ↓5.4 MB/s | 📡5
```

The `📡5` indicates 5 devices are currently online on your network.

Click the menu bar item to see:
- Current connection (WiFi SSID or Ethernet)
- IP address
- Current, average, and peak speeds
- Session and daily totals
- **Traffic Breakdown**: See which apps are using your network:
  - Lists active processes with traffic data
  - Shows download/upload bytes per app
  - Identifies apps (Chrome, Slack, VS Code, etc.)
- Connection history (per-network usage)
- **Network Devices**: List of all discovered devices with:
  - Online/offline status (🟢/⚪)
  - Device name or IP
  - Vendor identification
  - MAC address, hostname, first/last seen times
- Rescan Network: Force an immediate network scan
- Issues log (connectivity problems)

### Settings

- **Launch at Login**: Toggle to start the app automatically when you log in
  - Shows ✓ when enabled, ○ when disabled
  - Uses macOS LaunchAgents (standard method)
- **Reset Session Stats**: Clears current session data (speeds, averages)
- **Reset Today's Stats**: Clears all data for today
- **Rescan Network**: Force a network device scan
- **Open Data Folder**: Opens the folder where statistics are stored

## Data Storage

Statistics are stored in SQLite format (v1.2+) at:
```
~/.network-monitor/network_monitor.db
```

The database includes:
- **traffic_stats**: Daily traffic data per connection
- **issues**: Network events and issues log
- **devices**: Known network devices with custom names

### Migration from JSON

When upgrading from v1.1, existing JSON data is automatically migrated to SQLite on first run. The old `stats.json` file is renamed to `stats.json.bak`.

### Backup & Restore

From the menu: **Actions → Backup & Restore**
- **Create Backup**: Save database to a file
- **Restore from Backup**: Restore from a previous backup
- **Database Info**: View statistics about stored data
- **Run Cleanup Now**: Manually remove data older than retention period

### Export Formats

Export data via **Actions → Export Data**:
- **CSV**: Daily totals for spreadsheet analysis
- **JSON**: Full data export including devices and issues

## Project Structure

```
network-monitor/
├── network_monitor.py      # Main application entry point
├── app/                    # Application architecture
│   ├── __init__.py
│   ├── events.py           # Event bus for pub/sub communication
│   ├── dependencies.py     # Dependency injection container
│   ├── controller.py       # Business logic orchestration
│   └── views/
│       ├── icons.py        # Icon and sparkline generation
│       └── menu_builder.py # Menu construction helpers
├── config/                 # Configuration module
│   ├── __init__.py
│   ├── constants.py        # Centralized configuration values
│   ├── exceptions.py       # Custom exception hierarchy
│   ├── logging_config.py   # Structured logging setup
│   └── subprocess_cache.py # Cached subprocess execution
├── monitor/                # Data collection modules
│   ├── __init__.py
│   ├── connection.py       # WiFi/Ethernet/VPN detection
│   ├── issues.py           # Issue detection and logging
│   ├── network.py          # Network stats collection
│   ├── scanner.py          # Network device discovery
│   ├── traffic.py          # Traffic breakdown by process
│   └── utils.py            # Shared utility functions
├── storage/                # Data persistence
│   ├── __init__.py
│   ├── sqlite_store.py     # SQLite storage (v1.2+)
│   ├── json_store.py       # Legacy JSON storage
│   └── settings.py         # Application settings
├── service/
│   ├── __init__.py
│   └── launch_agent.py     # macOS LaunchAgent management
├── tests/                  # Test suite
│   ├── __init__.py
│   ├── conftest.py         # Pytest fixtures
│   ├── mocks.py            # Mock implementations
│   └── test_*.py           # Test modules
├── pyproject.toml          # Project & tool configuration
├── .pre-commit-config.yaml # Pre-commit hooks
├── requirements.txt
├── requirements-dev.txt
├── README.md
└── run.sh
```

## Development

### Setup Development Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies including dev tools
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

### Code Quality Tools

The project uses modern Python tooling configured in `pyproject.toml`:

- **Black**: Code formatting (line length: 100)
- **Ruff**: Fast linting (replaces flake8, isort, pyupgrade)
- **MyPy**: Static type checking
- **Bandit**: Security scanning

```bash
# Format code
black .

# Run linter with auto-fix
ruff check --fix .

# Type check
mypy monitor storage service config app

# Run all pre-commit hooks
pre-commit run --all-files
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=monitor --cov=storage --cov=service --cov-report=html

# Run specific test file
pytest tests/test_network.py -v
```

### Verification Checklist

After making changes, verify:

1. Pre-commit hooks pass: `pre-commit run --all-files`
2. Application starts without errors: `python network_monitor.py`
3. All display modes work (latency, speed, session, devices, quality)
4. Device scanning works and shows vendors
5. Tests pass: `pytest`
6. No type errors: `mypy monitor storage`

## Troubleshooting

### App doesn't appear in menu bar
- Ensure you have Python 3.9+ installed
- Check that rumps installed correctly: `pip show rumps`
- Try running with: `python3 network_monitor.py`

### WiFi SSID shows "Private" or not detected
macOS 14+ (Sonoma/Sequoia) requires Location Services permission to access WiFi network names. To enable:

1. Open **System Settings** → **Privacy & Security** → **Location Services**
2. Enable Location Services (toggle at top)
3. Scroll down and enable for **Terminal** (or your terminal app)
4. Restart the Network Monitor app

Without Location Services, the app will show "WiFi (Private - enable Location)" instead of the actual network name. All other features work normally.

### Statistics not persisting
- Check that `~/.network-monitor/` is writable
- Look for error messages in the terminal

## License

MIT License - feel free to modify and use as needed.
