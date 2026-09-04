#!/usr/bin/env python3
"""Entry point for running Serial Command Console from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python main.py`` from anywhere without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from serial_console.app import main

if __name__ == "__main__":
    raise SystemExit(main())
