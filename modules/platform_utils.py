from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        path = base / "VideoToolkit"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "VideoToolkit"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = base / "VideoToolkit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_tool_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def bundled_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def bundled_media_tool(name: str) -> Path:
    return bundled_root() / media_tool_name(name)


def open_local_path(path: str | os.PathLike[str]) -> None:
    """Open a file or directory with the platform's default application."""
    target = str(Path(path).expanduser().resolve())
    if sys.platform == "win32":
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])
