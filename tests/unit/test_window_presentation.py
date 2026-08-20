from __future__ import annotations

import unittest

from pynextcloud_sync.core.window_presentation import MappedWindowPresenter


class _Parent:
    def __init__(self, *, mapped: bool) -> None:
        self.mapped = mapped
        self.callbacks: dict[int, object] = {}
        self.disconnected: list[int] = []

    def get_mapped(self) -> bool:
        return self.mapped

    def connect(self, signal: str, callback: object) -> int:
        if signal != "map":
            raise AssertionError(signal)
        self.callbacks[7] = callback
        return 7

    def disconnect(self, handler: int) -> None:
        self.disconnected.append(handler)
        self.callbacks.pop(handler, None)

    def map(self) -> None:
        self.mapped = True
        for callback in tuple(self.callbacks.values()):
            callback(self)


class MappedWindowPresenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.idle: list[object] = []
        self.shown: list[tuple[object, object]] = []
        self.presenter = MappedWindowPresenter(
            idle_add=self.idle.append,
            show=lambda manifest, parent: self.shown.append((manifest, parent)),
            source_remove=False,
        )

    def run_idle(self) -> None:
        while self.idle:
            callback = self.idle.pop(0)
            callback()

    def test_unmapped_parent_delays_child_until_the_map_cycle_finishes(self) -> None:
        parent = _Parent(mapped=False)
        self.presenter.queue("release", parent)

        self.assertEqual(self.shown, [])
        self.assertEqual(self.idle, [])
        parent.map()
        self.assertEqual(self.shown, [])

        self.run_idle()
        self.assertEqual(self.shown, [("release", parent)])
        self.assertEqual(parent.disconnected, [7])

    def test_already_mapped_parent_still_uses_the_next_ui_cycle(self) -> None:
        parent = _Parent(mapped=True)
        self.presenter.queue("release", parent)

        self.assertEqual(self.shown, [])
        self.run_idle()
        self.assertEqual(self.shown, [("release", parent)])

    def test_replaced_request_disconnects_the_old_parent(self) -> None:
        old_parent = _Parent(mapped=False)
        new_parent = _Parent(mapped=True)
        self.presenter.queue("old", old_parent)
        self.presenter.queue("new", new_parent)

        self.assertEqual(old_parent.disconnected, [7])
        old_parent.map()
        self.run_idle()
        self.assertEqual(self.shown, [("new", new_parent)])

    def test_parent_unmapped_before_idle_waits_for_its_next_map(self) -> None:
        parent = _Parent(mapped=False)
        self.presenter.queue("release", parent)
        parent.map()
        parent.mapped = False
        self.run_idle()
        self.assertEqual(self.shown, [])

        parent.map()
        self.run_idle()
        self.assertEqual(self.shown, [("release", parent)])


if __name__ == "__main__":
    unittest.main()
