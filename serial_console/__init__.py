"""Serial Command Console — an ENF project.

A professional desktop serial terminal built around user-definable command
buttons, designed to replace simple serial monitors for embedded development.

Author:  ENF
Licence: MIT
"""

from __future__ import annotations

__all__ = [
    "APP_NAME",
    "APP_SLUG",
    "AUTHOR",
    "COPYRIGHT",
    "ORG_NAME",
    "SIGNATURE",
    "WEBSITE",
    "__version__",
]

__version__ = "1.0.0"

APP_NAME = "ENF Serial Command Console"
APP_SLUG = "SerialCommandConsole"  # unchanged: it names the on-disk config folder
ORG_NAME = "ENF"

AUTHOR = "ENF"
COPYRIGHT = "© 2026 ENF"
WEBSITE = "https://github.com/hamid-enf/Serial_App"

#: Short mark shown in the status bar and the About box.
SIGNATURE = "ENF"
