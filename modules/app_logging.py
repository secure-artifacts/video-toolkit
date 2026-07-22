from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path


_LOCK = threading.Lock()


def app_log_path() -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home()) / "VideoToolkit"
    return root / "video_toolkit.log"


def write_app_log(message: object, level: str = "INFO", source: str = "应用") -> None:
    text = str(message or "").strip()
    if not text:
        return
    try:
        path = app_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] [{source}] {text}\n")
    except OSError:
        pass


def read_app_log() -> str:
    path = app_log_path()
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else "当前还没有软件运行日志。"
    except OSError as exc:
        return f"无法读取软件日志：{exc}"
