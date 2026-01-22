# Network Monitor for macOS

A lightweight macOS menu bar app that monitors network traffic, tracks daily usage per connection (Wi‑Fi/Ethernet), shows real‑time speeds with sparklines, discovers devices on your network, and logs connectivity issues.

![Network Monitor icon preview](assets/icon_preview.png)

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [Privacy, permissions, and security notes](#privacy-permissions-and-security-notes)
- [Data storage](#data-storage)
- [Optional: install arp-scan for richer vendor lookups](#optional-install-arp-scan-for-richer-vendor-lookups)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Changelog](#changelog)
- [Licence](#licence)

## Features

### Monitoring

- **Live sparklines**: compact graphs for:
  - network quality (purple) — 0–100 score
  - upload speed (green)
  - download speed (blue)
  - total traffic (pink)
  - latency (orange)
- **Menu bar status**: latency/speeds/device count with a colour‑coded status icon
- **Traffic breakdown by app**: per‑process traffic (bytes in/out) with friendly application names
- **Device discovery**: scans your local network and tracks devices over time (including vendor lookups and mDNS/Bonjour names)

### History & budgets

- **Per‑connection tracking**: separate usage for each Wi‑Fi SSID and Ethernet
- **Daily totals**: persisted across app restarts
- **History views**: weekly/monthly breakdowns (where supported in the UI)
- **Data budgets**: set limits per connection and get notified

### Network quality

- **Latency monitor**: continuous ping with colour‑coded status
- **Quality score**: 0–100 score based on latency/jitter/consistency
- **VPN detection**: detects active VPN interfaces
- **Issue detection**: connection drops, sustained high latency, notable speed drops, quality degradation

### System integration

- **Launch at login**: toggle auto‑start via a LaunchAgent
- **Adaptive updates**: updates more frequently during high activity and less when idle

## Requirements

- **macOS**: tested on **macOS 14+**. Older versions may work but are not currently verified.
- **Python**: **3.9+**

## Install

### Option 1: Build a standalone macOS app (recommended)

Build an `.app` bundle you can place in `/Applications`:

```bash
cd network-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

python setup.py py2app
cp -R "dist/Network Monitor.app" /Applications/
```

Launch **Network Monitor** from **Applications** or Spotlight.

### Option 2: Run from source

```bash
cd network-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python network_monitor.py
```

Or use the convenience script (creates `venv/` automatically if needed):

```bash
./run.sh
```

## Usage

Once running, the app appears in the menu bar. A typical display looks like:

```
↑1.2 MB/s ↓5.4 MB/s | 📡5
```

The `📡5` indicates five devices currently appear online on your network.

Click the menu bar item to see details such as:

- current connection (Wi‑Fi SSID or Ethernet) and IP address
- current/average/peak speeds, session totals, and today’s totals
- **traffic breakdown**: active processes and their upload/download usage
- **devices**: online/offline status (🟢/⚪), name/IP, vendor, MAC, hostname, first/last seen
- actions such as **Rescan Network** and viewing the **Issues** log

### Device identification and naming

Device names are resolved from multiple sources (highest priority first):

1. **Custom names** you set
2. **mDNS/Bonjour** service names (where available)
3. **Vendor/OUI look‑ups** from MAC prefixes
4. **Device type inference** from vendor/hostname patterns
5. **Hostname** via DNS resolution
6. **IP address** as a fallback

To name a device:

- open **Devices**
- select a device
- enter a custom name

Names are stored at `~/.network-monitor/device_names.json`.

## Privacy, permissions, and security notes

- **Location Services (Wi‑Fi SSID)**: on macOS 14+, your terminal (or the built `.app`) may need Location Services permission to read the current Wi‑Fi network name (SSID). Without it, the app will show a “Private” placeholder for the SSID.
- **Local network scanning**: device discovery relies on standard local tools and protocols (e.g. ARP and mDNS). It does **not** require port forwarding or inbound firewall rules.
- **Data stays local**: stats, device names, and logs are written under `~/.network-monitor/`.

## Data storage

Data is stored under `~/.network-monitor/`. Historical statistics use SQLite:

```
~/.network-monitor/network_monitor.db
```

Common tables include:

- `traffic_stats`: daily traffic per connection
- `issues`: events and issue log
- `devices`: known devices (including custom names)

### Backup, restore, and export

From the menu:

- **Actions → Backup & Restore** (create/restore backups, view database info, run retention clean‑up)
- **Actions → Export Data** (CSV or JSON)

### Migration from JSON

If you are upgrading from older releases that used `stats.json`, existing data is migrated on first run. The old file is renamed to `stats.json.bak`.

## Optional: install arp-scan for richer vendor lookups

If you have `arp-scan` installed, the app can use its IEEE OUI database for vendor identification:

```bash
brew install arp-scan
```

Without it, the app falls back to a smaller built‑in vendor list.

## Development

### Set up a development environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
```

### Quality checks

```bash
black .
ruff check --fix .
mypy monitor storage service config app
pre-commit run --all-files
```

### Tests

```bash
pytest
pytest -v
pytest --cov=monitor --cov=storage --cov=service --cov=config --cov=app --cov-report=html
```

## Troubleshooting

### The app doesn’t appear in the menu bar

- Ensure you’re running on macOS and using Python 3.9+
- Check dependencies installed correctly: `pip show rumps`
- Try running from a terminal first: `python network_monitor.py`

### Wi‑Fi SSID shows “Private” (or is not detected)

On macOS 14+, Location Services permission is required to access Wi‑Fi network names. Enable it for your terminal:

1. **System Settings** → **Privacy & Security** → **Location Services**
2. Turn on Location Services (top toggle)
3. Enable it for **Terminal** (or your terminal app)
4. Restart Network Monitor

### Statistics don’t persist

- Check `~/.network-monitor/` is writable
- Check `~/.network-monitor/network_monitor.log` for errors

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Licence

This project is released under the MIT License.
