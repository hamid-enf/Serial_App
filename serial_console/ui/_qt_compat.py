"""Small typing shims over PySide6.

PySide6 ships stubs that describe ``Slot`` as returning ``Callable[[Any], Any]``.
Decorating a method with it therefore erases the method's signature, and every
decorated slot shows up as a type error while also losing the checking we
actually want inside the body. Wrapping it once, here, keeps the runtime
behaviour identical (it *is* ``QtCore.Slot``) and preserves the decorated
function's type everywhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from PySide6.QtCore import Slot as _QtSlot
from PySide6.QtWidgets import QMessageBox, QWidget

__all__ = ["slot", "warn"]

F = TypeVar("F", bound=Callable[..., Any])


def slot(*types: Any, **kwargs: Any) -> Callable[[F], F]:
    """Typing-friendly alias for :class:`PySide6.QtCore.Slot`.

    Usage is unchanged::

        @slot(str, bool)
        def _on_something(self, text: str, flag: bool) -> None: ...
    """
    return _QtSlot(*types, **kwargs)  # type: ignore[return-value]


def warn(parent: QWidget | None, title: str, text: str) -> None:
    """Show a warning box.

    ``QMessageBox.warning`` has defaulted its button arguments since Qt 5, but
    the bundled stubs still mark them as required; funnelling the call through
    here keeps the type checker honest everywhere else.
    """
    QMessageBox.warning(parent, title, text)  # type: ignore[call-arg,arg-type]
