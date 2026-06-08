"""
存档文件监听器。
监听两个存档文件，取最新修改时间的那个，文件变动时触发回调。
"""
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer


class _SaveFileHandler(FileSystemEventHandler):
    def __init__(self, file_a: Path, file_b: Path, callback: Callable[[Path], None]):
        self._file_a = file_a
        self._file_b = file_b
        self._callback = callback
        # watchdog 在 Windows 上 src_path 可能用反斜杠，统一转为字符串比较
        self._watched = {str(file_a), str(file_b)}

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if event.src_path not in self._watched:
            return
        newest = self._pick_newest()
        if newest is not None:
            self._callback(newest)

    def _pick_newest(self) -> Path | None:
        """返回两个文件中修改时间更新的那个；若文件不存在则跳过。"""
        candidates = []
        for f in (self._file_a, self._file_b):
            try:
                candidates.append((f.stat().st_mtime, f))
            except FileNotFoundError:
                pass
        if not candidates:
            return None
        return max(candidates)[1]


class SaveFileWatcher:
    """监听两个存档文件，任一变动时以最新文件路径触发 callback。"""

    def __init__(self, file_a: Path, file_b: Path, callback: Callable[[Path], None]):
        self._handler = _SaveFileHandler(file_a, file_b, callback)
        self._observer = Observer()
        # watchdog 以目录为粒度监听，不直接监听单个文件
        watch_dir = str(file_a.parent)
        self._observer.schedule(self._handler, watch_dir, recursive=False)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
