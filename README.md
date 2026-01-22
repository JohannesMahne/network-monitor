# Network Monitor for macOS

A menu bar application that monitors network traffic, tracks daily usage per connection (WiFi/Ethernet), displays real-time speeds, discovers devices on your network (like Fing), and logs connectivity issues.

## Features

- **Menu Bar Display**: Shows current upload/download speeds and device count in the macOS menu bar
- **Traffic Breakdown by App**: See which applications are using your bandwidth
  - Real-time process-level traffic monitoring
  - Shows bytes in/out per application
  - Identifies apps by friendly names (Chrome, Slack, Spotify, etc.)
  - Manual refresh option for instant updates
- **Network Device Discovery** (Fing-like): Discovers and tracks devices on your local network
  - Shows online/offline status
  - Identifies device vendors (Apple, Samsung, Google, etc.)
  - Resolves hostnames when available
  - Tracks when devices were first/last seen
- **Per-Connection Tracking**: Tracks usage separately for each WiFi network (by SSID) and Ethernet
- **Daily Statistics**: Persists daily totals across app restarts
- **Speed Metrics**:
  - Current speed (real-time)
  - Today's total usage
- **Latency Monitor**:
  - Real-time ping to 8.8.8.8 (Google DNS)
  - Color-coded status: 🟢 Good (<50ms), 🟡 OK (50-100ms), 🔴 Poor (>100ms)
  - Running average displayed
- **Usage History**:
  - Weekly totals
  - Monthly totals (30 days)
  - Daily breakdown (last 7 days)
  - Per-connection history with daily stats
- **Issue Detection**:
  - Connection drops
  - High latency alerts
  - Speed drop detection
- **Connection History**: View usage per network connection
- **Launch at Login**: Toggle auto-start in Settings menu (like other macOS apps)

## Requirements

- macOS (tested on macOS 14+)
- Python 3.9+
- **Optional**: [Fing CLI](https://www.fing.com/desktop/) for enhanced device recognition

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

Statistics are stored in JSON format at:
```
~/.network-monitor/stats.json
```

Data is organized by date and connection:
```json
{
  "2026-01-21": {
    "WiFi:HomeNetwork": {
      "bytes_sent": 1234567890,
      "bytes_recv": 9876543210,
      "peak_upload": 5242880,
      "peak_download": 52428800,
      "issues": []
    }
  }
}
```

## Project Structure

```
network-monitor/
├── network_monitor.py    # Main application
├── monitor/
│   ├── __init__.py
│   ├── network.py        # Network stats collection
│   ├── connection.py     # WiFi/Ethernet detection
│   ├── issues.py         # Issue detection
│   ├── scanner.py        # Network device discovery (Fing-like)
│   └── traffic.py        # Traffic breakdown by process
├── storage/
│   ├── __init__.py
│   └── json_store.py     # JSON persistence with history
├── service/
│   ├── __init__.py
│   └── launch_agent.py   # macOS Launch Agent for auto-start
├── requirements.txt
├── README.md
└── run.sh
```

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
