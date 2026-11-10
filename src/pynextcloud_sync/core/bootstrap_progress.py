from __future__ import annotations

import os
import re
import stat
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from pynextcloud_sync.core.exclusions import ExclusionMatcher
from pynextcloud_sync.core.safety import is_sync_database_name


# Used only for the live estimate. The engine owns these files and the
# inventory used for the safety review keeps its existing exclusion rules.
_DOWNLOAD_TEMP = re.compile(r"\..+\.\~[0-9a-f]{1,8}\Z")


@dataclass(frozen=True)
class BootstrapProgress:
    message: str
    downloading: bool = False
    items: int = 0
    total_items: int | None = None
    bytes_done: int = 0
    partial_bytes: int = 0
    current: str = ""
    file_bytes: int = 0
    file_size: int = 0
    free_bytes: int | None = None
    counted: bool = False


class BootstrapProgressReporter:
    def __init__(
        self, publish: Callable[[BootstrapProgress], None], log: Callable[[str], None] | None = None,
    ) -> None:
        self.publish = publish
        self.log = log
        self.state = BootstrapProgress("")
        self.last_publish = 0.0

    def begin(self, message: str, **values: object) -> None:
        self.state = BootstrapProgress(message, **values)
        self.last_publish = time.monotonic()
        self.publish(self.state)
        if self.log:
            self.log(message)

    def update(self, *, force: bool = False, **values: object) -> None:
        now = time.monotonic()
        if force or now - self.last_publish >= 0.25:
            self.state = replace(self.state, **values)
            self.last_publish = now
            self.publish(self.state)


def measure_download(
    root: Path, matcher: ExclusionMatcher, stopped: threading.Event,
) -> tuple[int, int, int]:
    """Sample the logical size of the isolated tree while the engine writes it."""
    files = downloaded = partial = 0
    pending = [root]
    while pending and not stopped.is_set():
        try:
            with os.scandir(pending.pop()) as children:
                for child in children:
                    if stopped.is_set():
                        return files, downloaded, partial
                    if is_sync_database_name(child.name) or matcher.matches_name(child.name):
                        continue
                    try:
                        mode = child.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(mode.st_mode):
                        pending.append(child.path)
                    elif stat.S_ISREG(mode.st_mode):
                        if _DOWNLOAD_TEMP.fullmatch(child.name):
                            partial += mode.st_size
                        else:
                            files += 1
                            downloaded += mode.st_size
        except OSError:
            # The engine can remove or rename a directory while it is sampled.
            continue
    return files, downloaded, partial
