from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


_INSTANCE_ID: str | None = None
_INSTANCE_SLOT: int | None = None
_INSTANCE_REGISTERED = False


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


def instance_id() -> str:
    """Stable id for this process lifetime (used to isolate temps/logs)."""
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        override = os.environ.get("VIDEO_TOOLKIT_INSTANCE_ID", "").strip()
        if override:
            cleaned = re.sub(r"[^\w.\-]", "_", override)[:48]
            _INSTANCE_ID = cleaned or f"pid{os.getpid()}"
        else:
            _INSTANCE_ID = f"pid{os.getpid()}_{int(time.time()) % 100000:05d}"
    return _INSTANCE_ID


def instance_temp_dir(name: str = "") -> Path:
    """Per-process temp root so multi-open tasks do not clobber each other."""
    base = Path(tempfile.gettempdir()) / "VideoToolkit" / f"inst_{instance_id()}"
    if name:
        base = base / name
    base.mkdir(parents=True, exist_ok=True)
    return base


def _instances_dir() -> Path:
    path = app_data_dir() / "instances"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            # PROCESS_QUERY_LIMITED_INFORMATION
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, 0, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _cleanup_stale_instances() -> None:
    for path in _instances_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = int(data.get("pid", 0) or 0)
            if pid and not _pid_alive(pid):
                path.unlink(missing_ok=True)
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _unregister_instance() -> None:
    global _INSTANCE_REGISTERED
    if not _INSTANCE_REGISTERED:
        return
    try:
        path = _instances_dir() / f"{os.getpid()}.json"
        path.unlink(missing_ok=True)
    except OSError:
        pass
    _INSTANCE_REGISTERED = False


def register_instance() -> int:
    """Register this process for multi-open tracking; return 1-based slot."""
    global _INSTANCE_SLOT, _INSTANCE_REGISTERED
    if _INSTANCE_SLOT is not None:
        return _INSTANCE_SLOT
    _cleanup_stale_instances()
    pid = os.getpid()
    payload = {
        "pid": pid,
        "instance_id": instance_id(),
        "started": time.time(),
    }
    try:
        (_instances_dir() / f"{pid}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        _INSTANCE_REGISTERED = True
        atexit.register(_unregister_instance)
    except OSError:
        pass
    live = list_live_instances()
    slot = 1
    for index, item in enumerate(live, start=1):
        if int(item.get("pid", 0) or 0) == pid:
            slot = index
            break
    _INSTANCE_SLOT = slot
    return slot


def list_live_instances() -> list[dict]:
    """Return live multi-open instance records sorted by start time."""
    _cleanup_stale_instances()
    live: list[dict] = []
    for path in _instances_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = int(data.get("pid", 0) or 0)
            if pid and _pid_alive(pid):
                live.append(data)
        except Exception:
            continue
    live.sort(key=lambda item: (float(item.get("started", 0) or 0), int(item.get("pid", 0) or 0)))
    return live


def instance_slot() -> int:
    if _INSTANCE_SLOT is None:
        return register_instance()
    return _INSTANCE_SLOT


def live_instance_count() -> int:
    return max(1, len(list_live_instances()))


@contextmanager
def exclusive_file_lock(lock_path: Path | str, timeout: float = 12.0):
    """Cross-process exclusive lock (best-effort; continues after timeout)."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    locked = False
    try:
        deadline = time.time() + max(0.2, float(timeout))
        if sys.platform == "win32":
            import msvcrt
            while True:
                try:
                    handle.seek(0)
                    if handle.tell() == 0 and handle.read(1) == b"":
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.04)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.04)
        yield locked
    finally:
        if locked:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            handle.close()
        except OSError:
            pass


def media_tool_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def bundled_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def bundled_media_tool(name: str) -> Path:
    return bundled_root() / media_tool_name(name)


def validate_media_tool(path: str | os.PathLike[str], name: str) -> bool:
    """Reject a missing/corrupt tool or a frozen app executable copied as FFmpeg."""
    candidate=Path(path)
    if not candidate.is_file():
        return False
    try:
        if Path(sys.executable).is_file() and candidate.samefile(sys.executable):
            return False
    except OSError:
        pass
    environment=os.environ.copy()
    environment["VIDEO_TOOLKIT_MEDIA_PROBE"]="1"
    creation=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result=subprocess.run([str(candidate),"-version"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,encoding="utf-8",errors="replace",timeout=5,env=environment,
                              creationflags=creation)
    except Exception:
        return False
    output=(result.stdout or "").casefold()
    return result.returncode == 0 and f"{name.casefold()} version" in output


def open_local_path(path: str | os.PathLike[str]) -> None:
    """Open a file or directory with the platform's default application."""
    target = str(Path(path).expanduser().resolve())
    if sys.platform == "win32":
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])
