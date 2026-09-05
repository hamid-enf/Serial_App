"""Bounded, de-duplicating send history with shell-style navigation."""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Iterable, Sequence

DEFAULT_LIMIT = 200


class CommandHistory:
    """Most-recent-first history of transmitted commands.

    Semantics chosen to match what engineers expect from a shell:

    * re-sending an existing entry moves it to the top instead of duplicating,
    * the size is hard-capped so a week-long session cannot grow RAM,
    * :meth:`previous` / :meth:`next_entry` walk a cursor that resets whenever
      a new command is recorded.
    """

    def __init__(self, limit: int = DEFAULT_LIMIT, entries: Iterable[str] | None = None) -> None:
        self._limit = max(0, int(limit))
        self._entries: deque[str] = deque(maxlen=self._limit or 1)
        self._cursor = -1
        if entries:
            # ``entries`` is stored most-recent-first; append in reverse so the
            # newest ends up at index 0 after the per-item add.
            for entry in reversed(list(entries)):
                self.add(entry)
        self.reset_cursor()

    # ------------------------------------------------------------------
    @property
    def limit(self) -> int:
        return self._limit

    def set_limit(self, limit: int) -> None:
        """Resize the history, discarding the oldest entries if needed."""
        self._limit = max(0, int(limit))
        kept = list(self._entries)[: self._limit]
        self._entries = deque(kept, maxlen=self._limit or 1)
        if self._limit == 0:
            self._entries.clear()
        self.reset_cursor()

    def entries(self) -> list[str]:
        """Return entries most-recent-first."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, item: object) -> bool:
        return item in self._entries

    # ------------------------------------------------------------------
    def add(self, command: str) -> None:
        """Record ``command`` as the most recent entry."""
        if self._limit == 0:
            self.reset_cursor()
            return
        if command is None:
            return
        text = str(command)
        if not text.strip():
            return
        with contextlib.suppress(ValueError):
            self._entries.remove(text)
        self._entries.appendleft(text)
        while len(self._entries) > self._limit:
            self._entries.pop()
        self.reset_cursor()

    def clear(self) -> None:
        self._entries.clear()
        self.reset_cursor()

    # ------------------------------------------------------------------
    def reset_cursor(self) -> None:
        self._cursor = -1

    @property
    def cursor(self) -> int:
        return self._cursor

    def previous(self) -> str | None:
        """Step towards older entries (Arrow Up)."""
        if not self._entries:
            return None
        if self._cursor + 1 < len(self._entries):
            self._cursor += 1
        return self._entries[self._cursor]

    def next_entry(self) -> str | None:
        """Step towards newer entries (Arrow Down).

        Returns ``""`` when stepping past the newest entry, which clears the
        input box exactly like a shell does.
        """
        if not self._entries:
            return None
        if self._cursor <= 0:
            self._cursor = -1
            return ""
        self._cursor -= 1
        return self._entries[self._cursor]

    # ------------------------------------------------------------------
    def to_list(self) -> list[str]:
        return self.entries()

    @classmethod
    def from_list(cls, entries: Sequence[str], limit: int = DEFAULT_LIMIT) -> CommandHistory:
        return cls(limit=limit, entries=entries)
