from __future__ import annotations

import ast
import unittest
from pathlib import Path


ENTRYPOINT = (
    Path(__file__).parents[2]
    / "src"
    / "pynextcloud_sync"
    / "__main__.py"
)


class MainEntryTests(unittest.TestCase):
    def test_keyboard_interrupt_is_handled_without_a_traceback(self) -> None:
        tree = ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))
        handlers = [
            handler
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            for handler in node.handlers
        ]
        self.assertTrue(
            any(
                isinstance(handler.type, ast.Name)
                and handler.type.id == "KeyboardInterrupt"
                for handler in handlers
            )
        )


if __name__ == "__main__":
    unittest.main()
