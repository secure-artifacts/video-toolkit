from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QListWidget, QTableWidget, QTextEdit


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def natural_key(value):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", str(value))]


def collect_files(paths, extensions=None, predicate=None):
    result = []
    extensions = {value.lower() for value in extensions} if extensions else None
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = []
            for root, directories, files in os.walk(path):
                directories.sort(key=natural_key)
                candidates.extend(Path(root) / name for name in sorted(files, key=natural_key))
        else:
            continue
        for candidate in candidates:
            if extensions is not None and candidate.suffix.lower() not in extensions:
                continue
            if predicate is not None and not predicate(candidate):
                continue
            result.append(str(candidate.resolve()))
    return sorted(dict.fromkeys(result), key=natural_key)


def load_subfolders(combo, parent):
    parent_path = Path(parent)
    children = sorted((path for path in parent_path.iterdir() if path.is_dir()),
                      key=lambda path: natural_key(path.name))
    combo.clear()
    combo.addItem(f"[父目录本身] {parent_path.name}", str(parent_path))
    for child in children:
        combo.addItem(child.name, str(child))
    combo.setEnabled(True)
    return len(children)


class _DropPathsMixin:
    paths_dropped = Signal(list)

    def _init_drop_paths(self):
        self.setAcceptDrops(True)
        if hasattr(self, "viewport"):
            self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class DropListWidget(_DropPathsMixin, QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self._init_drop_paths()
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)


class DropTextEdit(_DropPathsMixin, QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent); self._init_drop_paths()


class DropTableWidget(_DropPathsMixin, QTableWidget):
    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent); self._init_drop_paths()


class DropFolderLineEdit(QLineEdit):
    folder_dropped = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            folder = path if path.is_dir() else path.parent
            self.setText(str(folder)); self.folder_dropped.emit(str(folder)); event.acceptProposedAction(); return
        event.ignore()
