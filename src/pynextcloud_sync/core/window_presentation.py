from __future__ import annotations

from collections.abc import Callable
from typing import Any


class MappedWindowPresenter:
    """Present a child window only after its intended parent is mapped."""

    def __init__(
        self,
        *,
        idle_add: Callable[[Callable[[], Any]], Any],
        show: Callable[[Any, Any], None],
        source_remove: Any,
    ) -> None:
        self._idle_add = idle_add
        self._show = show
        self._source_remove = source_remove
        self._manifest: Any = None
        self._parent: Any = None
        self._map_handler: int | None = None

    def queue(self, manifest: Any, parent: Any) -> None:
        self.clear()
        self._manifest = manifest
        self._parent = parent
        if parent.get_mapped():
            self._idle_add(self._present)
            return
        self._map_handler = parent.connect("map", self._parent_mapped)

    def clear(self) -> None:
        parent = self._parent
        handler = self._map_handler
        if parent is not None and handler is not None:
            try:
                parent.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        self._manifest = None
        self._parent = None
        self._map_handler = None

    def _parent_mapped(self, _parent: Any) -> None:
        self._idle_add(self._present)

    def _present(self) -> Any:
        manifest = self._manifest
        parent = self._parent
        if manifest is None or parent is None:
            self.clear()
            return self._source_remove
        if not parent.get_mapped():
            return self._source_remove

        self.clear()
        self._show(manifest, parent)
        return self._source_remove
