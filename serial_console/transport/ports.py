"""COM port enumeration."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PortInfo:
    """A serial port as offered in the port selector."""

    device: str
    description: str = ""
    hwid: str = ""
    manufacturer: str = ""

    def display_name(self) -> str:
        """``COM5 — Silicon Labs CP210x`` style label."""
        detail = self.description or self.manufacturer
        if detail and detail.lower() not in {"n/a", "unknown"}:
            return f"{self.device} — {detail}"
        return self.device


def list_ports() -> list[PortInfo]:
    """Return the available serial ports, sorted naturally.

    Enumeration is defensive: a flaky USB driver can make ``comports()`` raise,
    and that must degrade to an empty list rather than break the UI.
    """
    try:
        from serial.tools import list_ports as pyserial_list_ports
    except ImportError:  # pragma: no cover - pyserial is a hard dependency
        _log.error("pyserial is not installed; port enumeration unavailable")
        return []

    try:
        raw = list(pyserial_list_ports.comports())
    except Exception:
        _log.exception("Failed to enumerate serial ports")
        return []

    ports = [
        PortInfo(
            device=item.device,
            description=(item.description or "").strip(),
            hwid=(item.hwid or "").strip(),
            manufacturer=(getattr(item, "manufacturer", "") or "").strip(),
        )
        for item in raw
        if getattr(item, "device", None)
    ]
    return sorted(ports, key=_natural_key)


def _natural_key(port: PortInfo) -> tuple[str, int, str]:
    """Sort ``COM2`` before ``COM10`` and group by prefix."""
    device = port.device
    digits = ""
    index = len(device)
    while index > 0 and device[index - 1].isdigit():
        index -= 1
        digits = device[index] + digits
    prefix = device[:index]
    return (prefix, int(digits) if digits else 0, device)
