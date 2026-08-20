from __future__ import annotations

import unittest

from pynextcloud_sync.core.triggers import CoalescingQueue, Trigger, manual_only


class TriggerTests(unittest.TestCase):
    def test_queue_coalesces_duplicate_reasons(self) -> None:
        queue = CoalescingQueue()
        queue.add(Trigger.LOCAL_INOTIFY)
        queue.add(Trigger.LOCAL_INOTIFY)
        queue.add(Trigger.MANUAL)
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue.take(), {Trigger.LOCAL_INOTIFY, Trigger.MANUAL})
        self.assertFalse(queue)

    def test_discard_removes_only_the_selected_reason(self) -> None:
        queue = CoalescingQueue()
        queue.add(Trigger.LOCAL_INOTIFY)
        queue.add(Trigger.REMOTE_PUSH)
        queue.discard(Trigger.LOCAL_INOTIFY)
        self.assertEqual(queue.take(), {Trigger.REMOTE_PUSH})

    def test_manual_only_requires_all_four_triggers_off(self) -> None:
        settings = {
            "local_inotify_enabled": False,
            "local_interval_enabled": False,
            "remote_push_enabled": False,
            "remote_interval_enabled": False,
        }
        self.assertTrue(manual_only(settings))
        for key in settings:
            changed = dict(settings)
            changed[key] = True
            self.assertFalse(manual_only(changed), key)


if __name__ == "__main__":
    unittest.main()
