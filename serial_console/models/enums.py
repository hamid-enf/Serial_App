"""Enumerations describing serial and terminal configuration.

These types are deliberately free of any dependency on ``pyserial`` or Qt so
that the model layer can be imported (and unit tested) in isolation.  The
mapping onto ``pyserial`` constants lives in :mod:`serial_console.transport`.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import TypeVar

#: Bound to the concrete subclass so ``LineEnding.coerce(...)`` is typed as
#: ``LineEnding`` rather than the private base class.
_E = TypeVar("_E", bound="_LabelledEnum")


class _LabelledEnum(Enum):
    """Enum with a human readable label and tolerant parsing.

    Deliberately **not** a ``str`` subclass: Qt converts ``str``-derived
    enum members to plain ``str`` when they are stored as item data, which
    silently turns ``combo.currentData()`` into a string and breaks every
    ``.value`` access downstream.  A plain ``Enum`` round-trips through
    ``QVariant`` as the identical Python object.
    """

    label: str

    def __new__(cls, value: str, label: str) -> _LabelledEnum:
        obj = object.__new__(cls)
        obj._value_ = value
        obj.label = label
        return obj

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def coerce(cls: type[_E], value: object, default: _E) -> _E:
        """Return a member for ``value``, falling back to ``default``.

        Parsing is case insensitive and also accepts the human readable label,
        which keeps hand-edited configuration files working.
        """
        if isinstance(value, cls):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        for member in cls:
            if text == member.value.lower() or text == member.label.lower():
                return member
        return default

    @classmethod
    def labels(cls) -> Iterable[str]:
        return [member.label for member in cls]


class LineEnding(_LabelledEnum):
    """Terminator appended to every transmitted command."""

    NONE = ("none", "None")
    LF = ("lf", "LF (\\n)")
    CR = ("cr", "CR (\\r)")
    CRLF = ("crlf", "CRLF (\\r\\n)")

    @property
    def suffix(self) -> bytes:
        """Bytes appended to the payload when sending."""
        return _LINE_ENDING_BYTES[self]


_LINE_ENDING_BYTES = {
    LineEnding.NONE: b"",
    LineEnding.LF: b"\n",
    LineEnding.CR: b"\r",
    LineEnding.CRLF: b"\r\n",
}


class Parity(_LabelledEnum):
    NONE = ("none", "None")
    EVEN = ("even", "Even")
    ODD = ("odd", "Odd")
    MARK = ("mark", "Mark")
    SPACE = ("space", "Space")


class StopBits(_LabelledEnum):
    ONE = ("1", "1")
    ONE_POINT_FIVE = ("1.5", "1.5")
    TWO = ("2", "2")

    @property
    def numeric(self) -> float:
        return float(self.value)


class DataBits(_LabelledEnum):
    FIVE = ("5", "5")
    SIX = ("6", "6")
    SEVEN = ("7", "7")
    EIGHT = ("8", "8")

    @property
    def numeric(self) -> int:
        return int(self.value)


class FlowControl(_LabelledEnum):
    NONE = ("none", "None")
    RTS_CTS = ("rtscts", "RTS/CTS (hardware)")
    XON_XOFF = ("xonxoff", "XON/XOFF (software)")
    DSR_DTR = ("dsrdtr", "DSR/DTR (hardware)")


class DisplayMode(_LabelledEnum):
    """How received bytes are rendered in the terminal."""

    ASCII = ("ascii", "ASCII / Text")
    HEX = ("hex", "Hex")
    BOTH = ("both", "Hex + ASCII")


class Direction(_LabelledEnum):
    """Origin of a terminal chunk."""

    RX = ("rx", "RX")
    TX = ("tx", "TX")
    INFO = ("info", "INFO")
    ERROR = ("error", "ERROR")


class Theme(_LabelledEnum):
    DARK = ("dark", "Dark")
    LIGHT = ("light", "Light")


#: Baud rates offered in the UI.  The combo box is editable so any other
#: value supported by the driver can be typed in by hand.
COMMON_BAUD_RATES: tuple[int, ...] = (
    300,
    1200,
    2400,
    4800,
    9600,
    14400,
    19200,
    38400,
    57600,
    115200,
    128000,
    230400,
    256000,
    460800,
    500000,
    576000,
    921600,
    1000000,
    1152000,
    1500000,
    2000000,
    2500000,
    3000000,
)

#: Terminal scrollback budgets offered in the settings dialog, in bytes.
BUFFER_PRESETS: tuple[tuple[str, int], ...] = (
    ("1 MB", 1 * 1024 * 1024),
    ("5 MB", 5 * 1024 * 1024),
    ("10 MB", 10 * 1024 * 1024),
    ("50 MB", 50 * 1024 * 1024),
)


def enum_value(candidate: object) -> object:
    """Return ``candidate.value`` for enum members, ``candidate`` otherwise.

    Defensive helper for serialisation paths: a hand-edited config or a future
    Qt quirk must not be able to turn ``to_dict()`` into an ``AttributeError``.
    """
    return getattr(candidate, "value", candidate)
