"""yt-dlp helpers: module import, standalone binary, and download entry points.

Packaged (frozen) builds cannot reliably use system pip. We install the official
standalone binary into the app data bin folder (same pattern as FFmpeg).
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import requests

from .platform_utils import app_data_dir


def _component_bin() -> Path:
    path = app_data_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _hidden_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


LogFn = Callable[[str], None]


def ytdlp_asset_name() -> str:
    if sys.platform == "win32":
        return "yt-dlp.exe"
    if sys.platform == "darwin":
        return "yt-dlp_macos"
    return "yt-dlp_linux"


def ytdlp_binary_path() -> Path:
    return _component_bin() / ytdlp_asset_name()


def find_ytdlp_binary() -> str | None:
    """Return path to a usable yt-dlp executable, or None."""
    candidates = [
        ytdlp_binary_path(),
        _component_bin() / "yt-dlp.exe",
        _component_bin() / "yt-dlp",
    ]
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 50_000:
                return str(path)
        except OSError:
            continue
    which = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if which:
        try:
            if Path(which).stat().st_size > 50_000:
                return which
        except OSError:
            return which
    return None


def module_available() -> bool:
    try:
        return importlib.util.find_spec("yt_dlp") is not None
    except Exception:
        return False


def module_version() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return ""


def binary_version(binary: str | None = None) -> str:
    path = binary or find_ytdlp_binary()
    if not path:
        return ""
    try:
        result = subprocess.run(
            [path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **_hidden_kwargs(),
        )
        if result.returncode == 0:
            return (result.stdout or "").strip().splitlines()[0].strip()
    except Exception:
        pass
    return ""


def ytdlp_status() -> tuple[bool, str]:
    """(ok, detail) for component table."""
    if module_available():
        ver = module_version() or "已内置"
        return True, ver
    binary = find_ytdlp_binary()
    if binary:
        ver = binary_version(binary) or "独立程序"
        return True, f"{ver}  ({binary})"
    return False, "缺少：yt-dlp（模块或独立程序）"


def ytdlp_download_urls() -> list[str]:
    """Primary + fallbacks (GitHub may be slow in CN)."""
    asset = ytdlp_asset_name()
    return [
        f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{asset}",
        f"https://ghproxy.net/https://github.com/yt-dlp/yt-dlp/releases/latest/download/{asset}",
        f"https://mirror.ghproxy.com/https://github.com/yt-dlp/yt-dlp/releases/latest/download/{asset}",
    ]


def install_ytdlp_binary(
    log: LogFn | None = None,
    progress: Callable[[int], None] | None = None,
) -> str:
    """Download official standalone yt-dlp into app bin. Returns installed path."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    target = ytdlp_binary_path()
    urls = ytdlp_download_urls()
    last_error: Exception | None = None
    tmp = target.with_suffix(target.suffix + ".part")

    for url in urls:
        try:
            _log(f"正在下载 yt-dlp 独立程序…")
            _log(f"地址：{url}")
            with requests.get(url, stream=True, timeout=90) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0) or 0)
                if total:
                    _log(f"文件大小约 {total / (1024 * 1024):.1f} MB")
                received = 0
                last_pct = -1
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(256 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        received += len(chunk)
                        if total and progress:
                            pct = min(95, round(received / total * 95))
                            progress(pct)
                            if pct // 10 > last_pct // 10:
                                last_pct = pct
                                _log(
                                    f"  下载进度 {pct}%（"
                                    f"{received / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB）"
                                )
            size = tmp.stat().st_size
            if size < 50_000:
                raise RuntimeError(f"下载文件过小（{size} 字节），可能不是有效程序")
            # Replace existing
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    backup = target.with_suffix(target.suffix + ".old")
                    try:
                        if backup.exists():
                            backup.unlink()
                        target.rename(backup)
                    except OSError:
                        pass
            tmp.replace(target)
            if sys.platform != "win32":
                target.chmod(target.stat().st_mode | 0o111)
            ver = binary_version(str(target)) or "未知"
            _log(f"yt-dlp 独立程序已安装：版本 {ver}")
            _log(f"路径：{target}")
            if progress:
                progress(100)
            # Ensure bin on PATH for this process
            bin_text = str(_component_bin())
            path_env = os.environ.get("PATH", "")
            if bin_text not in path_env.split(os.pathsep):
                os.environ["PATH"] = bin_text + os.pathsep + path_env
            return str(target)
        except Exception as exc:
            last_error = exc
            _log(f"  此地址失败：{exc}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            continue

    raise RuntimeError(
        "下载 yt-dlp 独立程序失败（网络/代理/GitHub 访问）。"
        + (f" 最后错误：{last_error}" if last_error else "")
    )


def get_youtube_dl_class():
    """Import YoutubeDL or raise ImportError if only binary is available."""
    from yt_dlp import YoutubeDL  # type: ignore
    return YoutubeDL


def download_media(
    url: str,
    outtmpl: str,
    *,
    format_spec: str = "mp4/best",
    quiet: bool = True,
    no_warnings: bool = True,
    proxy: str | None = None,
    extra_opts: dict | None = None,
    progress_hooks: list | None = None,
    log: LogFn | None = None,
) -> tuple[str, dict | None]:
    """Download with Python module if available, else standalone binary.

    Returns (output_path, info_dict_or_None).
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    if module_available():
        from yt_dlp import YoutubeDL  # type: ignore

        options: dict = {
            "outtmpl": outtmpl,
            "format": format_spec,
            "quiet": quiet,
            "no_warnings": no_warnings,
            "nocheckcertificate": True,
            "noplaylist": True,
            "overwrites": True,
        }
        if proxy:
            options["proxy"] = proxy
        if progress_hooks:
            options["progress_hooks"] = progress_hooks
        if extra_opts:
            options.update(extra_opts)
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            return path, info

    binary = find_ytdlp_binary()
    if not binary:
        raise RuntimeError(
            "缺少网络视频解析组件 yt-dlp。请到「设置与组件」点击「一键更新 yt-dlp」。"
        )

    _log(f"使用独立 yt-dlp 程序：{binary}")
    # Resolve concrete path pattern (strip %(ext)s for probing later)
    out_dir = Path(outtmpl).parent if "%(" in outtmpl else Path(outtmpl).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        binary,
        "--no-playlist",
        "--force-overwrites",
        "-f", format_spec,
        "-o", outtmpl,
        "--no-check-certificates",
        "--newline",
    ]
    if quiet:
        cmd.append("--quiet")
    if no_warnings:
        cmd.append("--no-warnings")
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        **_hidden_kwargs(),
    )
    if result.returncode != 0:
        tail = (result.stdout or "")[-2000:]
        raise RuntimeError(f"yt-dlp 下载失败（退出码 {result.returncode}）。\n{tail}")

    # Find produced file
    # When outtmpl has %(ext)s, list matching stem
    import glob as _glob

    pattern = outtmpl
    if "%(" in pattern:
        # Replace common yt-dlp templates with wildcards
        import re as _re
        pattern = _re.sub(r"%\([^)]+\)s", "*", pattern)
        pattern = _re.sub(r"%\([^)]+\)\d*d", "*", pattern)
    matches = sorted(
        (Path(p) for p in _glob.glob(pattern) if Path(p).is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        # Fallback: newest file in directory
        files = [p for p in out_dir.iterdir() if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise RuntimeError("yt-dlp 已退出但未找到输出文件")
        return str(files[0]), None
    return str(matches[0]), None
