"""
Setup script for building Network Monitor as a macOS application.

Usage:
    python setup.py py2app

The resulting app will be in the 'dist' folder.
"""
from setuptools import setup

APP = ['network_monitor.py']
DATA_FILES = []

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'assets/NetworkMonitor.icns',
    'plist': {
        'CFBundleName': 'Network Monitor',
        'CFBundleDisplayName': 'Network Monitor',
        'CFBundleIdentifier': 'com.networkmonitor.app',
        'CFBundleVersion': '1.4.0',
        'CFBundleShortVersionString': '1.4.0',
        'LSMinimumSystemVersion': '10.14.0',
        'LSUIElement': True,  # Hide dock icon (menu bar app)
        'NSHighResolutionCapable': True,
        'NSLocationWhenInUseUsageDescription': 'Network Monitor needs location access to detect WiFi network names on macOS 14+.',
        'NSLocationUsageDescription': 'Network Monitor needs location access to detect WiFi network names on macOS 14+.',
    },
    'packages': [
        # Our packages
        'monitor',
        'storage',
        'service',
        'config',
        'app',
    ],
    'includes': [
        'rumps',
        'psutil',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'matplotlib',
        'matplotlib.pyplot',
        'numpy',
        'dateutil',
        'pyparsing',
        'objc',
        'Foundation',
        'AppKit',
        'Cocoa',
    ],
    'excludes': [
        'tkinter',
        'pytest',
        'hypothesis',
        'coverage',
        'pip',
        'PyObjCTools',
    ],
    'site_packages': True,
}

setup(
    app=APP,
    name='Network Monitor',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
