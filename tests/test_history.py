"""Send history semantics and memory bounds."""

from __future__ import annotations

from serial_console.core.history import CommandHistory


class TestBasics:
    def test_newest_first(self) -> None:
        history = CommandHistory()
        history.add("first")
        history.add("second")
        assert history.entries() == ["second", "first"]

    def test_blank_entries_are_ignored(self) -> None:
        history = CommandHistory()
        history.add("")
        history.add("   ")
        assert len(history) == 0

    def test_resending_moves_the_entry_to_the_top(self) -> None:
        history = CommandHistory()
        for command in ("a", "b", "c"):
            history.add(command)
        history.add("a")
        assert history.entries() == ["a", "c", "b"]
        assert len(history) == 3

    def test_clear(self) -> None:
        history = CommandHistory()
        history.add("a")
        history.clear()
        assert history.entries() == []


class TestBounds:
    def test_limit_is_enforced(self) -> None:
        history = CommandHistory(limit=3)
        for index in range(10):
            history.add(f"cmd{index}")
        assert len(history) == 3
        assert history.entries() == ["cmd9", "cmd8", "cmd7"]

    def test_zero_limit_disables_history(self) -> None:
        history = CommandHistory(limit=0)
        history.add("a")
        assert history.entries() == []

    def test_shrinking_the_limit_drops_the_oldest(self) -> None:
        history = CommandHistory(limit=10)
        for index in range(10):
            history.add(f"cmd{index}")
        history.set_limit(2)
        assert history.entries() == ["cmd9", "cmd8"]

    def test_growing_the_limit_keeps_existing_entries(self) -> None:
        history = CommandHistory(limit=2)
        history.add("a")
        history.add("b")
        history.set_limit(5)
        history.add("c")
        assert history.entries() == ["c", "b", "a"]

    def test_long_session_does_not_grow_without_bound(self) -> None:
        history = CommandHistory(limit=50)
        for index in range(100_000):
            history.add(f"cmd{index}")
        assert len(history) == 50


class TestNavigation:
    def test_arrow_up_walks_backwards(self) -> None:
        history = CommandHistory()
        for command in ("one", "two", "three"):
            history.add(command)
        assert history.previous() == "three"
        assert history.previous() == "two"
        assert history.previous() == "one"

    def test_arrow_up_stops_at_the_oldest_entry(self) -> None:
        history = CommandHistory()
        history.add("only")
        assert history.previous() == "only"
        assert history.previous() == "only"

    def test_arrow_down_returns_towards_an_empty_box(self) -> None:
        history = CommandHistory()
        history.add("one")
        history.add("two")
        history.previous()  # two
        history.previous()  # one
        assert history.next_entry() == "two"
        assert history.next_entry() == ""

    def test_navigation_on_empty_history_returns_none(self) -> None:
        history = CommandHistory()
        assert history.previous() is None
        assert history.next_entry() is None

    def test_adding_resets_the_cursor(self) -> None:
        history = CommandHistory()
        history.add("one")
        history.add("two")
        history.previous()
        history.add("three")
        assert history.previous() == "three"


class TestPersistence:
    def test_round_trip_preserves_order(self) -> None:
        history = CommandHistory()
        for command in ("a", "b", "c"):
            history.add(command)
        restored = CommandHistory.from_list(history.to_list())
        assert restored.entries() == history.entries()

    def test_from_list_applies_the_limit(self) -> None:
        restored = CommandHistory.from_list(["a", "b", "c", "d"], limit=2)
        assert restored.entries() == ["a", "b"]
