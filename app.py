from __future__ import annotations

import json
import hashlib
import asyncio
import base64
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def _startup_trace(message):
    path = os.environ.get("VIDEO_TOOLKIT_STARTUP_TRACE", "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    except Exception:
        pass


_startup_trace("standard imports ready")
import requests
_startup_trace("requests ready")
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QInputDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QScrollArea, QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
_startup_trace("PySide6 ready")

from modules.rename_page import RenamePage, RenameTask, natural_key as rename_natural_key
from modules.screenshot_page import VideoTool as ScreenshotPage
from modules.settings_page import SettingsPage, component_bin, hidden_kwargs
from modules.smartcut_page import SmartCutPage, video_duration
from modules.watermark_page import MainWindow as WatermarkPage
from modules.dynamic_caption_page import DynamicCaptionPage, group_word_srt, write_ass
from modules.metadata_page import MetadataPage
from modules.platform_utils import app_data_dir, bundled_media_tool, media_tool_name
_startup_trace("tool modules ready")


APP_NAME = "视频工具合集"
ALL_RESULTS_LABEL = "【全部结果】"
PROVIDERS = ["Groq", "Gemini", "ElevenLabs", "Gladia"]
LOCAL_PROVIDER = "本地 Whisper（无需密钥）"
AUTO_PROVIDER = "自动选择（按优先级）"
TRANSCRIPTION_PROVIDERS = [AUTO_PROVIDER, LOCAL_PROVIDER] + PROVIDERS
DEFAULT_MODELS = {
    LOCAL_PROVIDER: "small",
    "Groq": "whisper-large-v3-turbo",
    "Gemini": "gemini-3.5-flash",
    "ElevenLabs": "scribe_v2",
    "Gladia": "default",
}
DEFAULT_SHEET_MAPPINGS = [
    {"field": "日期", "column": "A", "source": "date", "value": ""},
    {"field": "文件名/链接", "column": "B", "source": "file", "value": ""},
    {"field": "中文字幕", "column": "K", "source": "chinese", "value": ""},
    {"field": "原文/葡语", "column": "L", "source": "original", "value": ""},
    {"field": "云端文件夹", "column": "W", "source": "folder", "value": ""},
]
DEFAULT_VARIABLE_FIELDS = [
    {"field": "组别", "column": "C", "options": [], "selected": ""},
    {"field": "分类", "column": "D", "options": [], "selected": ""},
    {"field": "难易程度", "column": "E", "options": [], "selected": ""},
    {"field": "素材来源", "column": "F", "options": [], "selected": ""},
    {"field": "使用软件", "column": "G", "options": [], "selected": ""},
    {"field": "制作人1", "column": "H", "options": [], "selected": ""},
    {"field": "字幕审核", "column": "I", "options": [], "selected": ""},
    {"field": "版权审核", "column": "J", "options": [], "selected": ""},
]


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", app_root()))
    return base / name


def config_dir() -> Path:
    return app_data_dir()


def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json_file(path: Path, default=None):
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except (OSError, ValueError, TypeError):
        return {} if default is None else default


def source_signature(source: str):
    if is_supported_video_url(source):
        return {"kind": "url", "value": source.strip()}
    path = Path(source).expanduser()
    try:
        resolved = path.resolve()
        stat = resolved.stat()
        return {"kind": "file", "path": str(resolved), "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns}
    except OSError:
        return {"kind": "file", "path": str(path.absolute()), "missing": True}


def stable_key(payload) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ConfigStore:
    def __init__(self):
        self.path = config_dir() / "config.json"
        self.lock = threading.RLock()
        self.data = self._load()

    def _default(self):
        return {
            "providers": {p: [] for p in PROVIDERS},
            "round_robin": {p: 0 for p in PROVIDERS},
            "models": dict(DEFAULT_MODELS),
            "provider_priority": PROVIDERS + [LOCAL_PROVIDER],
            "google_sync": {
                "enabled": False, "json_path": "", "parent_folder": "",
                "folder_mode": "视频名称", "custom_folder_name": "", "public_link": False,
                "write_sheet": False, "spreadsheet_id": "", "sheet_name": "",
                "available_sheet_names": [], "option_sheet_name": "", "option_start_row": 2,
                "insert_row": 4, "date_column": "A", "file_column": "B",
                "chinese_column": "K", "original_column": "L", "folder_column": "W",
                "static_columns": "C=\nD=\nE=\nF=\nG=\nH=\nI=\nJ=",
                "sheet_mappings": [dict(item) for item in DEFAULT_SHEET_MAPPINGS],
                "sheet_profiles": {}, "active_sheet_profile": "",
                "sync_profiles": {}, "active_sync_profile": "",
                "auth_ok": False, "auth_identity": "", "auth_checked": "",
                "variable_fields": [dict(item) for item in DEFAULT_VARIABLE_FIELDS],
                "mapping_ui_version": 3,
            },
        }

    def _load(self):
        default = self._default()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for key in default:
                if key not in loaded:
                    loaded[key] = default[key]
            for provider in PROVIDERS:
                loaded["providers"].setdefault(provider, [])
                loaded["round_robin"].setdefault(provider, 0)
                loaded["models"].setdefault(provider, DEFAULT_MODELS[provider])
            loaded["models"].setdefault(LOCAL_PROVIDER, DEFAULT_MODELS[LOCAL_PROVIDER])
            old_google = loaded.get("google_sync", {})
            had_mappings = bool(old_google.get("sheet_mappings"))
            old_mapping_version = int(old_google.get("mapping_ui_version", 1))
            loaded["google_sync"] = {**default["google_sync"], **old_google}
            if not had_mappings:
                legacy_values = {}
                for line in old_google.get("static_columns", "").splitlines():
                    if "=" in line:
                        column, value = line.split("=", 1); legacy_values[column.strip().upper()] = value.strip()
                mappings = [dict(item) for item in DEFAULT_SHEET_MAPPINGS]
                legacy_columns = {"date": "date_column", "file": "file_column", "chinese": "chinese_column",
                                  "original": "original_column", "folder": "folder_column"}
                for item in mappings:
                    if item["source"] in legacy_columns:
                        item["column"] = old_google.get(legacy_columns[item["source"]], item["column"])
                    elif item["source"] == "static":
                        item["value"] = legacy_values.get(item["column"], "")
                loaded["google_sync"]["sheet_mappings"] = mappings
            if old_mapping_version < 2:
                variable_columns = {item["column"] for item in DEFAULT_VARIABLE_FIELDS}
                old_mappings = loaded["google_sync"].get("sheet_mappings", [])
                loaded["google_sync"]["sheet_mappings"] = [item for item in old_mappings
                    if not (item.get("source") == "static" and item.get("column") in variable_columns
                            and not str(item.get("value", "")).strip())]
                loaded["google_sync"]["variable_fields"] = [dict(item) for item in DEFAULT_VARIABLE_FIELDS]
                loaded["google_sync"]["mapping_ui_version"] = 2
            priority = loaded.get("provider_priority", [])
            allowed = PROVIDERS + [LOCAL_PROVIDER]
            loaded["provider_priority"] = [p for p in priority if p in allowed]
            loaded["provider_priority"] += [p for p in allowed if p not in loaded["provider_priority"]]
            return loaded
        except Exception:
            return default

    def save(self):
        with self.lock:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)

    def add_key(self, provider: str, key: str):
        key = key.strip()
        if not key:
            raise ValueError("密钥不能为空")
        with self.lock:
            if any(item["key"] == key for item in self.data["providers"][provider]):
                raise ValueError("该密钥已存在")
            self.data["providers"][provider].append({
                "id": uuid.uuid4().hex,
                "key": key,
                "enabled": True,
                "status": "未检测",
                "last_checked": "",
                "last_error": "",
                "uses": 0,
            })
            self.save()

    def update_key(self, provider: str, key_id: str, **changes):
        with self.lock:
            for item in self.data["providers"][provider]:
                if item["id"] == key_id:
                    item.update(changes)
                    self.save()
                    return

    def remove_key(self, provider: str, key_id: str):
        with self.lock:
            self.data["providers"][provider] = [
                x for x in self.data["providers"][provider] if x["id"] != key_id
            ]
            self.save()

    def candidates(self, provider: str):
        with self.lock:
            keys = [x.copy() for x in self.data["providers"][provider]
                    if x.get("enabled", True) and x.get("status") not in ("失效", "格式错误")]
            if not keys:
                return []
            index = self.data["round_robin"].get(provider, 0) % len(keys)
            ordered = keys[index:] + keys[:index]
            self.data["round_robin"][provider] = (index + 1) % len(keys)
            self.save()
            return ordered

    def has_candidates(self, provider: str):
        if provider == LOCAL_PROVIDER:
            return True
        with self.lock:
            return any(x.get("enabled", True) and x.get("status") != "失效"
                       and x.get("status") != "格式错误"
                       for x in self.data["providers"].get(provider, []))

    def mark_use(self, provider: str, key_id: str, status="有效", error=""):
        with self.lock:
            for item in self.data["providers"][provider]:
                if item["id"] == key_id:
                    item["uses"] = item.get("uses", 0) + 1
                    item["status"] = status
                    item["last_error"] = error[:300]
                    item["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    break
            self.save()


def masked_key(key: str) -> str:
    if len(key) <= 9:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def response_error(resp: requests.Response) -> str:
    try:
        payload = resp.json()
        return json.dumps(payload, ensure_ascii=False)[:500]
    except Exception:
        return resp.text[:500] or f"HTTP {resp.status_code}"


def probe_audio_layout(ffmpeg_path: str, media_path: str):
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run([ffmpeg_path, "-hide_banner", "-i", str(media_path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=creation, text=True, encoding="utf-8", errors="replace")
    match = re.search(r"Audio:.*?,\s*(\d+)\s*Hz,\s*([^,\r\n]+)", result.stderr)
    return (int(match.group(1)), match.group(2).strip()) if match else None


def check_api_key(provider: str, key: str) -> tuple[bool, str]:
    # HTTP headers must be ASCII/Latin-1 encodable; APP_NAME contains Chinese.
    headers = {"User-Agent": "VideoToolkit/1.0"}
    try:
        if not key or any(ord(char) < 33 or ord(char) > 126 for char in key):
            return False, "密钥格式异常：含有空格、中文、全角字符或其他非法字符"
        if provider == "Groq":
            resp = requests.get("https://api.groq.com/openai/v1/models",
                                headers={**headers, "Authorization": f"Bearer {key}"}, timeout=20)
        elif provider == "Gemini":
            resp = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                headers={**headers, "x-goog-api-key": key}, timeout=20)
        elif provider == "ElevenLabs":
            resp = requests.get("https://api.elevenlabs.io/v1/user",
                                headers={**headers, "xi-api-key": key}, timeout=20)
        else:
            resp = requests.get("https://api.gladia.io/v2/pre-recorded?limit=1",
                                headers={**headers, "x-gladia-key": key}, timeout=20)
        if resp.status_code < 300:
            return True, "验证通过"
        return False, f"HTTP {resp.status_code}: {response_error(resp)}"
    except Exception as exc:
        return False, f"网络检测失败：{exc}"


class KeyCheckWorker(QObject):
    progress = Signal(str, str, bool, str)
    finished = Signal()

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    def run(self):
        for provider, item in self.jobs:
            ok, message = check_api_key(provider, item["key"])
            self.progress.emit(provider, item["id"], ok, message)
        self.finished.emit()


def timestamp_srt(seconds: float) -> str:
    millis = max(0, round(float(seconds) * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def segments_to_srt(segments) -> str:
    blocks = []
    for i, seg in enumerate(segments, 1):
        text = re.sub(r"\s+", " ", str(seg.get("text", ""))).strip()
        if not text:
            continue
        start = seg.get("start", 0)
        end = max(float(seg.get("end", start + 2)), float(start) + 0.2)
        blocks.append(f"{len(blocks)+1}\n{timestamp_srt(start)} --> {timestamp_srt(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def words_to_segments(words):
    segments, current, start, end = [], [], None, None
    for word in words or []:
        if word.get("type") not in (None, "word"):
            continue
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        w_start = float(word.get("start") or end or 0)
        w_end = float(word.get("end") or (w_start + 0.3))
        if start is None:
            start = w_start
        current.append(text)
        end = w_end
        joined = "".join(current) if any("\u4e00" <= c <= "\u9fff" for c in text) else " ".join(current)
        if end - start >= 6 or len(joined) >= 34 or re.search(r"[。！？.!?]$", text):
            segments.append({"start": start, "end": end, "text": joined})
            current, start, end = [], None, None
    if current:
        joined = "".join(current) if any(any("\u4e00" <= c <= "\u9fff" for c in x) for x in current) else " ".join(current)
        segments.append({"start": start or 0, "end": end or (start or 0) + 2, "text": joined})
    return segments


def clean_model_srt(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:srt)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("\r\n", "\n")
    if "-->" not in text:
        return f"1\n00:00:00,000 --> 99:59:59,000\n{text}\n"
    return text.strip() + "\n"


SUPPORTED_VIDEO_DOMAINS = (
    "youtube.com", "youtu.be", "facebook.com", "fb.watch",
    "instagram.com", "tiktok.com",
)
MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".ts",
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma",
}


def is_supported_video_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        return parsed.scheme in ("http", "https") and any(
            host == domain or host.endswith("." + domain) for domain in SUPPORTED_VIDEO_DOMAINS
        )
    except Exception:
        return False


def natural_path_key(value: str):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", value)]


class MediaDropList(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

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


class ApiFailure(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TranscribeWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    result_ready = Signal(str, str, str, str)
    finished = Signal(bool, str)

    def __init__(self, store: ConfigStore, provider: str, model: str, files: list[str],
                 output_dir: str, language: str, diarize: bool, ffmpeg_path: str,
                 resume_existing: bool = True):
        super().__init__()
        self.store = store
        self.provider = provider
        self.model = model
        self.files = files
        self.language = language.strip()
        self.diarize = diarize
        self.ffmpeg_path = ffmpeg_path
        self.cancelled = False
        self._local_model = None
        self._local_device = None
        self.resume_existing = resume_existing
        task_payload = {
            "version": 2, "provider": provider, "model": model,
            "language": self.language, "diarize": bool(diarize),
            "sources": [source_signature(source) for source in files],
        }
        self.task_id = stable_key(task_payload)
        self.output_dir = (Path(output_dir) if output_dir
                           else app_data_dir() / "subtitle_tasks" / self.task_id)
        self.checkpoint_path = self.output_dir / "checkpoint.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            if not self.resume_existing:
                shutil.rmtree(self.output_dir / ".work", ignore_errors=True)
            state = read_json_file(self.checkpoint_path, {}) if self.resume_existing else {}
            if state.get("task_id") != self.task_id:
                state = {}
            state.setdefault("task_id", self.task_id)
            state.setdefault("results", {})
            state["status"] = "running"
            atomic_write_json(self.checkpoint_path, state)
            for index, source in enumerate(self.files):
                if self.cancelled:
                    raise RuntimeError("任务已取消")
                source_key = stable_key(source_signature(source))
                cached = state["results"].get(source_key)
                if cached:
                    self.log.emit(f"断点续接：跳过已完成字幕 {index + 1}/{len(self.files)}：{cached['name']}")
                    self.result_ready.emit(cached["name"], cached.get("original", ""),
                                           cached.get("chinese", ""), cached.get("srt", ""))
                    self.progress.emit(round((index + 1) / len(self.files) * 100))
                    continue
                display = source if is_supported_video_url(source) else Path(source).name
                self.log.emit(f"正在处理 {index + 1}/{len(self.files)}：{display}")
                result = self._process_one(source)
                state["results"][source_key] = {
                    "source": source, "name": result["name"], "original": result["original"],
                    "chinese": result["chinese"], "srt": result["srt"],
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                }
                atomic_write_json(self.checkpoint_path, state)
                self._cleanup_source_work(source)
                self.progress.emit(round((index + 1) / len(self.files) * 100))
            state["status"] = "completed"
            atomic_write_json(self.checkpoint_path, state)
            self.finished.emit(True, "完成，字幕与中文对照已显示在当前窗口")
        except Exception as exc:
            try:
                state["status"] = "failed"
                state["last_error"] = str(exc)
                atomic_write_json(self.checkpoint_path, state)
            except Exception:
                pass
            self.finished.emit(False, str(exc))

    def _source_work_dir(self, source_value: str) -> Path:
        path = self.output_dir / ".work" / self._source_work_key(source_value)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _source_work_key(self, source_value: str) -> str:
        return stable_key({"source": source_signature(source_value), "provider": self.provider,
                           "model": self.model, "language": self.language})[:20]

    def _cleanup_source_work(self, source_value: str):
        work = self.output_dir / ".work" / self._source_work_key(source_value)
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)

    def _download_online_media(self, url: str, temp: Path):
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise RuntimeError("缺少网络视频解析组件 yt-dlp，请到“组件管理”点击一键安装。") from exc

        self.log.emit("正在解析并静默下载网络视频音轨 …")
        last_percent = {"value": ""}
        def download_hook(data):
            if self.cancelled:
                raise RuntimeError("任务已取消")
            if data.get("status") == "downloading":
                percent = re.sub(r"\x1b\[[0-9;]*m", "", data.get("_percent_str", "")).strip()
                if percent and percent != last_percent["value"]:
                    last_percent["value"] = percent
                    self.log.emit(f"网络视频下载中：{percent}")

        options = {
            "format": "bestaudio/best",
            "outtmpl": str(temp / "online_source.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "overwrites": True,
            "progress_hooks": [download_hook],
        }
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                prepared = Path(downloader.prepare_filename(info))
        except Exception as exc:
            raise RuntimeError(f"网络视频下载失败：{exc}") from exc
        candidates = [prepared] if prepared.exists() else []
        candidates += [p for p in temp.glob("online_source.*") if p.suffix not in (".part", ".ytdl")]
        source = next((p for p in candidates if p.exists() and p.is_file()), None)
        if not source:
            raise RuntimeError("网络视频下载完成，但没有找到可处理的媒体文件。")
        title = re.sub(r"[\\/:*?\"<>|]+", "_", str(info.get("title") or "网络视频")).strip()
        return source, (title[:100] or "网络视频")

    def _process_one(self, source_value: str):
        candidates = ([{"id": "local", "key": ""}] if self.provider == LOCAL_PROVIDER
                      else self.store.candidates(self.provider))
        if not candidates:
            raise RuntimeError(f"{self.provider} 没有可用密钥，请先到“密钥管理”添加并检测。")
        temp = self._source_work_dir(source_value)
        if is_supported_video_url(source_value):
            metadata_path = temp / "online_source.json"
            metadata = read_json_file(metadata_path, {})
            saved_path = Path(metadata.get("path", "")) if metadata.get("path") else None
            if saved_path and saved_path.exists():
                source = saved_path
                result_name = metadata.get("title") or source.name
                self.log.emit("断点续接：复用已下载的网络媒体。")
            else:
                source, result_name = self._download_online_media(source_value, temp)
                atomic_write_json(metadata_path, {"path": str(source), "title": result_name})
        else:
            source = Path(source_value)
            result_name = source.name

        if self.provider == LOCAL_PROVIDER:
            recognition_input = source
            self.log.emit("本地 Whisper 直接流式读取媒体，不创建整段 PCM 副本。")
        elif self.provider == "Groq":
            recognition_input = source
            self.log.emit("Groq 将直接从媒体生成 90 秒分段，不创建整段 PCM 副本。")
        else:
            audio = temp / "audio.wav"
            if not audio.exists() or audio.stat().st_size == 0:
                self.log.emit("创建临时 PCM 无损识别副本（保留原声道；不会修改视频音轨）…")
                cmd = [self.ffmpeg_path, "-y", "-i", str(source), "-map", "0:a:0", "-vn",
                       "-c:a", "pcm_s16le", str(audio)]
                creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      creationflags=creation, text=True, encoding="utf-8", errors="replace")
                if proc.returncode != 0 or not audio.exists():
                    raise RuntimeError("无法提取音频，请确认视频包含音轨。\n" + proc.stderr[-800:])
            else:
                self.log.emit("断点续接：复用已提取的识别音频。")
            recognition_input = audio

        last_error = ""
        for item in candidates:
            if self.cancelled:
                raise RuntimeError("任务已取消")
            if self.provider == LOCAL_PROVIDER:
                self.log.emit("使用本地 Whisper 模型，无需上传媒体或 API 密钥 …")
            else:
                self.log.emit(f"使用 {self.provider} 密钥 {masked_key(item['key'])} …")
            try:
                srt, plain, raw = self._call_provider(recognition_input, item["key"], temp)
                chinese = self._translate_chinese(plain)
                self.result_ready.emit(result_name, plain, chinese, srt)
                if self.provider != LOCAL_PROVIDER:
                    self.store.mark_use(self.provider, item["id"], "有效", "")
                self.log.emit(f"已在当前窗口生成中外文对照：{result_name}")
                return {"name": result_name, "original": plain, "chinese": chinese,
                        "srt": srt, "raw": raw}
            except ApiFailure as exc:
                last_error = str(exc)
                if exc.status in (401, 403):
                    status = "失效"
                elif exc.status == 429:
                    status = "额度受限"
                else:
                    status = "异常"
                self.store.mark_use(self.provider, item["id"], status, last_error)
                self.log.emit(f"密钥 {masked_key(item['key'])} 失败（{status}），自动轮换下一枚。")
            except requests.RequestException as exc:
                last_error = f"网络请求失败：{exc}"
                if self.provider != LOCAL_PROVIDER:
                    self.store.mark_use(self.provider, item["id"], "异常", last_error)
                    self.log.emit(f"密钥 {masked_key(item['key'])} 网络失败，保留分段进度并轮换下一枚。")
        raise RuntimeError(f"{self.provider} 的可用密钥均调用失败。最后错误：{last_error}")

    def _translate_chinese(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        visible = [c for c in text if c.isalpha() or "\u4e00" <= c <= "\u9fff"]
        chinese_count = sum("\u4e00" <= c <= "\u9fff" for c in visible)
        if visible and chinese_count / len(visible) > 0.45:
            return text
        self.log.emit("正在生成中文字幕对照 …")
        for item in self.store.candidates("Gemini"):
            try:
                prompt = ("把下面字幕准确翻译成简体中文。保留原有换行和段落顺序，只输出译文，"
                          "不要解释，不要 Markdown：\n\n" + text)
                model = self.store.data["models"].get("Gemini", DEFAULT_MODELS["Gemini"])
                response = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": item["key"], "Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}},
                    timeout=600)
                if response.status_code >= 300:
                    raise ApiFailure(response_error(response), response.status_code)
                payload = response.json()
                translated = "\n".join(part.get("text", "") for candidate in payload.get("candidates", [])
                                       for part in candidate.get("content", {}).get("parts", [])).strip()
                if translated:
                    self.store.mark_use("Gemini", item["id"], "有效", "")
                    return translated
            except Exception as exc:
                self.store.mark_use("Gemini", item["id"], "异常", str(exc))
        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source="auto", target="zh-CN")
            chunks, current = [], ""
            for line in text.splitlines() or [text]:
                if len(current) + len(line) + 1 > 3500 and current:
                    chunks.append(current); current = ""
                current += ("\n" if current else "") + line
            if current: chunks.append(current)
            return "\n".join(translator.translate(chunk) or "" for chunk in chunks).strip()
        except Exception as exc:
            self.log.emit(f"无密钥翻译暂不可用：{exc}")
            return "【自动翻译失败；可在密钥管理添加 Gemini 密钥后重试】\n" + text

    def _call_provider(self, audio: Path, key: str, temp: Path):
        if self.provider == LOCAL_PROVIDER:
            return self._local_whisper(audio)
        if self.provider == "Groq":
            return self._groq(audio, key, temp)
        if self.provider == "Gemini":
            return self._gemini(audio, key)
        if self.provider == "ElevenLabs":
            return self._elevenlabs(audio, key)
        return self._gladia(audio, key)

    def _local_whisper(self, audio: Path):
        try:
            from faster_whisper import WhisperModel
            import ctranslate2
        except ImportError as exc:
            raise RuntimeError("缺少本地字幕组件，请运行：pip install faster-whisper") from exc
        self.log.emit(f"正在加载本地 Whisper 模型：{self.model}（首次使用会下载模型）…")
        if self._local_model is None:
            has_cuda = ctranslate2.get_cuda_device_count() > 0
            try:
                self._local_model = WhisperModel(self.model or "small",
                                                 device="cuda" if has_cuda else "cpu",
                                                 compute_type="auto" if has_cuda else "int8",
                                                 cpu_threads=max(1, min(8, os.cpu_count() or 4)))
                self._local_device = "cuda" if has_cuda else "cpu"
            except (ValueError, RuntimeError) as exc:
                if not has_cuda:
                    raise
                self.log.emit(f"当前 GPU 模式不可用，自动切换 CPU INT8：{exc}")
                self._local_model = WhisperModel(self.model or "small", device="cpu", compute_type="int8",
                                                 cpu_threads=max(1, min(8, os.cpu_count() or 4)))
                self._local_device = "cpu"
        language = None if not self.language or self.language == "auto" else self.language
        def collect_segments(stream, info):
            segments = []
            for item in stream:
                if self.cancelled:
                    raise RuntimeError("任务已取消")
                words = [{"start": word.start, "end": word.end, "text": word.word.strip()}
                         for word in (getattr(item, "words", None) or []) if word.word.strip()]
                segments.append({"start": item.start, "end": item.end, "text": item.text.strip(), "words": words})
                if len(segments) % 10 == 0:
                    self.log.emit(f"本地识别中：已生成 {len(segments)} 条字幕 …")
            return segments, info

        def transcribe_with(model):
            try:
                import onnxruntime  # noqa: F401
                use_vad = True
            except ImportError:
                use_vad = False
                self.log.emit("未检测到 ONNX Runtime，已自动关闭 VAD 静音过滤并继续识别。")
            try:
                stream, info = model.transcribe(str(audio), language=language, beam_size=5,
                                                vad_filter=use_vad, word_timestamps=True)
                return collect_segments(stream, info)
            except RuntimeError as exc:
                if not use_vad or "onnxruntime" not in str(exc).lower():
                    raise
                self.log.emit("VAD 组件不可用，已关闭静音过滤并自动重试当前视频。")
                stream, info = model.transcribe(str(audio), language=language, beam_size=5,
                                                vad_filter=False, word_timestamps=True)
                return collect_segments(stream, info)
        try:
            segments, info = transcribe_with(self._local_model)
        except RuntimeError as exc:
            if self._local_device != "cuda" or self.cancelled:
                raise
            self.log.emit(f"GPU 长视频识别中断，自动改用 CPU INT8 从当前视频重试：{exc}")
            self._local_model = WhisperModel(self.model or "small", device="cpu", compute_type="int8",
                                             cpu_threads=max(1, min(8, os.cpu_count() or 4)))
            self._local_device = "cpu"
            segments, info = transcribe_with(self._local_model)
        plain = "\n".join(x["text"] for x in segments)
        raw = {"provider": "Local Whisper", "model": self.model,
               "language": getattr(info, "language", language), "segments": segments,
               "words": [word for segment in segments for word in segment.get("words", [])]}
        return segments_to_srt(segments), plain, raw

    def _groq(self, audio: Path, key: str, temp: Path):
        chunks_dir = temp / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        pattern = chunks_dir / "chunk_%03d.wav"
        creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        segment_seconds = 90
        chunks = sorted(chunks_dir.glob("chunk_*.wav"), key=lambda path: rename_natural_key(path.name))
        if not chunks:
            self.log.emit("正在把长音频切成 90 秒无损识别分段 …")
            cmd = [self.ffmpeg_path, "-y", "-i", str(audio), "-map", "0:a:0", "-vn", "-f", "segment",
                   "-segment_time", str(segment_seconds), "-reset_timestamps", "1",
                   "-c:a", "pcm_s16le", str(pattern)]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    creationflags=creation, text=True, encoding="utf-8", errors="replace")
            chunks = sorted(chunks_dir.glob("chunk_*.wav"), key=lambda path: rename_natural_key(path.name))
            if result.returncode != 0 or not chunks:
                raise RuntimeError("Groq 长音频分段失败。\n" + result.stderr[-800:])
        else:
            self.log.emit(f"断点续接：复用 {len(chunks)} 个长音频分段。")
        cache_path = temp / "groq_chunk_results.json"
        cache = read_json_file(cache_path, {})
        all_segments, all_words, texts, raw_items, offset = [], [], [], [], 0.0
        for number, chunk in enumerate(chunks, 1):
            payload = cache.get(chunk.name)
            if payload:
                self.log.emit(f"Groq 断点续接：跳过已完成分段 {number}/{len(chunks)}")
            else:
                self.log.emit(f"Groq 转写分段 {number}/{len(chunks)} …")
                data = {"model": self.model, "response_format": "verbose_json",
                        "timestamp_granularities[]": ["word", "segment"], "temperature": "0"}
                if self.language and self.language != "auto":
                    data["language"] = self.language
                with chunk.open("rb") as handle:
                    resp = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                         headers={"Authorization": f"Bearer {key}"}, data=data,
                                         files={"file": (chunk.name, handle, "audio/wav")}, timeout=900)
                if resp.status_code >= 300:
                    raise ApiFailure(response_error(resp), resp.status_code)
                payload = resp.json()
                cache[chunk.name] = payload
                atomic_write_json(cache_path, cache)
            raw_items.append(payload)
            text = payload.get("text", "").strip()
            texts.append(text)
            local = payload.get("segments") or []
            for seg in local:
                all_segments.append({"start": float(seg.get("start", 0)) + offset,
                                     "end": float(seg.get("end", 0)) + offset,
                                     "text": seg.get("text", "")})
            for word in payload.get("words") or []:
                word_text = str(word.get("word") or word.get("text") or "").strip()
                if word_text:
                    all_words.append({"start": float(word.get("start", 0)) + offset,
                                      "end": float(word.get("end", 0)) + offset, "text": word_text})
            try:
                offset += video_duration(self.ffmpeg_path, str(chunk))
            except Exception:
                offset += segment_seconds
        if not all_segments:
            all_segments = [{"start": 0, "end": max(2, offset), "text": "\n".join(texts)}]
        return segments_to_srt(all_segments), "\n".join(texts), {"provider": "Groq", "chunks": raw_items,
                                                                 "words": all_words}

    def _gemini(self, audio: Path, key: str):
        size = audio.stat().st_size
        mime = "audio/wav"
        headers = {
            "x-goog-api-key": key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        }
        start = requests.post("https://generativelanguage.googleapis.com/upload/v1beta/files",
                              headers=headers, json={"file": {"display_name": audio.name}}, timeout=60)
        if start.status_code >= 300:
            raise ApiFailure(response_error(start), start.status_code)
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise ApiFailure("Gemini 未返回上传地址")
        self.log.emit("上传音频到 Gemini Files API …")
        with audio.open("rb") as handle:
            uploaded = requests.post(upload_url, headers={
                "Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            }, data=handle, timeout=900)
        if uploaded.status_code >= 300:
            raise ApiFailure(response_error(uploaded), uploaded.status_code)
        file_info = uploaded.json().get("file", {})
        file_uri = file_info.get("uri")
        file_name = file_info.get("name")
        if not file_uri:
            raise ApiFailure("Gemini 文件上传响应缺少 URI")
        prompt = (
            "请准确转写这段音频，并只输出标准 SRT 字幕。要求：保留原语言；每条字幕包含序号、"
            "HH:MM:SS,mmm 时间码和正文；合理断句；不要 Markdown 代码框，不要解释。"
        )
        if self.language and self.language != "auto":
            prompt += f" 音频语言代码提示：{self.language}。"
        body = {"contents": [{"parts": [{"text": prompt}, {"file_data": {
            "mime_type": mime, "file_uri": file_uri}}]}],
                "generationConfig": {"temperature": 0.1}}
        try:
            self.log.emit("Gemini 正在生成带时间码字幕 …")
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=1200)
            if resp.status_code >= 300:
                raise ApiFailure(response_error(resp), resp.status_code)
            payload = resp.json()
            text = "\n".join(part.get("text", "") for cand in payload.get("candidates", [])
                              for part in cand.get("content", {}).get("parts", []))
            srt = clean_model_srt(text)
            plain = re.sub(r"(?m)^\d+\s*$|^\d{2}:\d{2}:\d{2},\d{3} --> .*?$", "", srt)
            plain = re.sub(r"\n{2,}", "\n", plain).strip()
            return srt, plain, {"provider": "Gemini", "response": payload}
        finally:
            if file_name:
                try:
                    requests.delete(f"https://generativelanguage.googleapis.com/v1beta/{file_name}",
                                    headers={"x-goog-api-key": key}, timeout=20)
                except Exception:
                    pass

    def _elevenlabs(self, audio: Path, key: str):
        data = {"model_id": self.model, "tag_audio_events": "true",
                "diarize": "true" if self.diarize else "false"}
        if self.language and self.language != "auto":
            data["language_code"] = self.language
        self.log.emit("ElevenLabs Scribe 正在转写 …")
        with audio.open("rb") as handle:
            resp = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                                 headers={"xi-api-key": key}, data=data,
                                 files={"file": (audio.name, handle, "audio/wav")}, timeout=1800)
        if resp.status_code >= 300:
            raise ApiFailure(response_error(resp), resp.status_code)
        payload = resp.json()
        segments = words_to_segments(payload.get("words", []))
        text = payload.get("text", "").strip()
        if not segments:
            segments = [{"start": 0, "end": 5, "text": text}]
        return segments_to_srt(segments), text, {"provider": "ElevenLabs", "response": payload}

    def _gladia(self, audio: Path, key: str):
        headers = {"x-gladia-key": key}
        self.log.emit("上传音频到 Gladia …")
        with audio.open("rb") as handle:
            uploaded = requests.post("https://api.gladia.io/v2/upload", headers=headers,
                                     files={"audio": (audio.name, handle, "audio/wav")}, timeout=1800)
        if uploaded.status_code >= 300:
            raise ApiFailure(response_error(uploaded), uploaded.status_code)
        audio_url = uploaded.json().get("audio_url")
        body = {"audio_url": audio_url, "subtitles": True,
                "subtitles_config": {"formats": ["srt"]}, "diarization": self.diarize}
        if self.language and self.language != "auto":
            body["language_config"] = {"languages": [self.language], "code_switching": False}
        init = requests.post("https://api.gladia.io/v2/pre-recorded",
                             headers={**headers, "Content-Type": "application/json"}, json=body, timeout=60)
        if init.status_code >= 300:
            raise ApiFailure(response_error(init), init.status_code)
        job = init.json()
        job_id = job.get("id")
        self.log.emit(f"Gladia 任务已提交：{job_id}")
        for _ in range(720):
            if self.cancelled:
                raise RuntimeError("任务已取消")
            result = requests.get(f"https://api.gladia.io/v2/pre-recorded/{job_id}",
                                  headers=headers, timeout=30)
            if result.status_code >= 300:
                raise ApiFailure(response_error(result), result.status_code)
            payload = result.json()
            status = payload.get("status")
            if status == "done":
                data = payload.get("result") or {}
                transcription = data.get("transcription") or {}
                plain = transcription.get("full_transcript", "") if isinstance(transcription, dict) else str(transcription)
                subtitles = data.get("subtitles") or []
                srt = ""
                if isinstance(subtitles, list):
                    for sub in subtitles:
                        if isinstance(sub, dict) and sub.get("format") == "srt":
                            srt = sub.get("subtitles") or sub.get("content") or ""
                            break
                        if isinstance(sub, str) and "-->" in sub:
                            srt = sub
                            break
                elif isinstance(subtitles, dict):
                    srt = subtitles.get("srt", "")
                if not srt:
                    utterances = transcription.get("utterances", []) if isinstance(transcription, dict) else []
                    srt = segments_to_srt(utterances) if utterances else clean_model_srt(plain)
                return clean_model_srt(srt), plain, {"provider": "Gladia", "response": payload}
            if status == "error":
                raise ApiFailure(json.dumps(payload, ensure_ascii=False)[:800])
            time.sleep(5)
        raise ApiFailure("Gladia 任务等待超时")


def extract_google_id(value: str) -> str:
    match = re.search(r"[-\w]{20,}", (value or "").strip())
    return match.group(0) if match else ""


def column_to_index(column: str) -> int:
    column = (column or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", column):
        raise ValueError(f"无效的表格列：{column or '空'}")
    result = 0
    for char in column: result = result * 26 + ord(char) - 64
    return result - 1


def index_to_column(index: int) -> str:
    value = index + 1; result = ""
    while value:
        value, remainder = divmod(value - 1, 26); result = chr(65 + remainder) + result
    return result


GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]


def load_google_credentials(config, interactive=False):
    json_path = Path(config.get("json_path", ""))
    if not json_path.is_file(): raise RuntimeError("Google 授权 JSON 文件不存在。")
    try: payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except Exception as exc: raise RuntimeError(f"Google JSON 无法读取：{exc}") from exc
    if payload.get("type") == "service_account":
        required = [name for name in ("client_email", "token_uri", "private_key") if not payload.get(name)]
        if required:
            raise RuntimeError("服务账号 JSON 不完整，缺少：" + "、".join(required))
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(payload, scopes=GOOGLE_SCOPES)
        return credentials, f"服务账号：{payload.get('client_email', '')}"
    client = payload.get("installed") or payload.get("web")
    if not client:
        raise RuntimeError("无法识别该 JSON。请选择服务账号密钥，或 OAuth 桌面客户端 JSON。")
    if not client.get("client_id") or not client.get("client_secret") or not client.get("token_uri"):
        raise RuntimeError("OAuth 客户端 JSON 不完整，缺少 client_id、client_secret 或 token_uri。")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("缺少 Google OAuth 授权组件，请到“设置与组件”一键安装。") from exc
    token_path = config_dir() / "google_oauth_token.json"
    credentials = None
    if token_path.is_file():
        try: credentials = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)
        except Exception: credentials = None
    if credentials and credentials.expired and credentials.refresh_token:
        try: credentials.refresh(Request())
        except Exception: credentials = None
    if not credentials or not credentials.valid:
        if not interactive:
            raise RuntimeError("OAuth 尚未授权，请打开 Google 配置并点击“授权/检查权限”。")
        flow = InstalledAppFlow.from_client_config(payload, GOOGLE_SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True,
                                            success_message="视频工具合集 Google 授权成功，可以关闭此页面。")
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials, "OAuth 用户授权"


def test_google_authorization(config, interactive=True):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("缺少 Google API 组件，请到“设置与组件”一键安装。") from exc
    credentials, identity = load_google_credentials(config, interactive=interactive)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    drive.about().get(fields="user").execute()
    parent_id = extract_google_id(config.get("parent_folder", ""))
    if parent_id:
        drive.files().get(fileId=parent_id, fields="id,name", supportsAllDrives=True).execute()
    return identity


class SheetWritePendingError(RuntimeError):
    def __init__(self, folder_url, uploaded, cause):
        super().__init__(f"视频已上传成功，但写入表格失败：{cause}")
        self.folder_url=folder_url
        self.uploaded=[{**dict(item),"path":str(item.get("path",""))} for item in uploaded]


class GoogleCloudSync:
    def __init__(self, config, log_callback=None, cancel_callback=None):
        self.config = config
        self.log = log_callback or (lambda text: None)
        self.cancelled = cancel_callback or (lambda: False)

    def _services(self):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("缺少 Google 云同步组件，请到“设置与组件”一键安装。") from exc
        credentials, identity = load_google_credentials(self.config, interactive=False)
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return drive, sheets, getattr(credentials, "service_account_email", "") or identity

    def _find_or_create_folder(self, drive, name, parent_id):
        escaped = name.replace("'", "\\'")
        query = (f"name = '{escaped}' and mimeType = 'application/vnd.google-apps.folder' "
                 f"and '{parent_id}' in parents and trashed = false")
        response = drive.files().list(q=query, spaces="drive", fields="files(id,name)",
                                      pageSize=10, supportsAllDrives=True,
                                      includeItemsFromAllDrives=True).execute()
        items = response.get("files", [])
        if items: return items[0]["id"]
        body = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
        return drive.files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"]

    def _upload_file(self, drive, path, parent_id):
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(path), mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                chunksize=8 * 1024 * 1024, resumable=True)
        escaped = path.name.replace("'", "\\'")
        query = f"name = '{escaped}' and '{parent_id}' in parents and trashed = false"
        found = drive.files().list(q=query, spaces="drive", fields="files(id,name,webViewLink)", pageSize=10,
                                   supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
        if found:
            request = drive.files().update(fileId=found[0]["id"], media_body=media,
                                           fields="id,name,webViewLink", supportsAllDrives=True)
        else:
            request = drive.files().create(body={"name": path.name, "parents": [parent_id]}, media_body=media,
                                           fields="id,name,webViewLink", supportsAllDrives=True)
        response = None
        while response is None:
            if self.cancelled(): raise RuntimeError("云端上传已停止；已上传的文件会保留，可稍后继续上传。")
            status, response = request.next_chunk()
            if status: self.log(f"上传 {path.name}：{round(status.progress() * 100)}%")
        return response

    def _parse_static_columns(self):
        mappings = {}
        for line in self.config.get("static_columns", "").splitlines():
            if "=" not in line: continue
            column, value = line.split("=", 1); column = column.strip().upper()
            if column: mappings[column] = value.strip()
        return mappings

    def _write_sheet(self, sheets, uploaded, folder_url):
        spreadsheet_id = extract_google_id(self.config.get("spreadsheet_id", ""))
        sheet_name = self.config.get("sheet_name", "").strip()
        if not spreadsheet_id or not sheet_name:
            raise RuntimeError("已开启表格写入，但表格 ID 或 Sheet 名称为空。")
        insert_row = max(1, int(self.config.get("insert_row", 4)))
        mappings = [dict(item) for item in self.config.get("sheet_mappings", DEFAULT_SHEET_MAPPINGS)
                    if str(item.get("column", "")).strip()]
        mappings += [{"field": item.get("field", "下拉字段"), "column": item.get("column", ""),
                      "source": "static", "value": item.get("selected", "")}
                     for item in self.config.get("variable_fields", []) if str(item.get("column", "")).strip()]
        if not mappings: raise RuntimeError("表格列映射为空。")
        for item in mappings: item["column"] = item["column"].strip().upper()
        max_index = max(column_to_index(item["column"]) for item in mappings)
        file_mapping = next((item for item in mappings if item.get("source") == "file"), None)
        if not file_mapping: raise RuntimeError("列映射中必须保留“文件名/链接”自动字段。")
        file_col = file_mapping["column"]
        folder_mapping = next((item for item in mappings if item.get("source") == "folder"), None)
        quoted_sheet = "'" + sheet_name.replace("'", "''") + "'"
        existing_response = sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"{quoted_sheet}!{file_col}{insert_row}:{file_col}",
            valueRenderOption="FORMULA").execute()
        # 文件链接是唯一值；同名文件可以存在，但同一个云端链接不会重复写入。
        existing = {}
        for offset, values in enumerate(existing_response.get("values", [])):
            value = str(values[0]) if values else ""
            match = re.search(r'HYPERLINK\(\s*"([^"]+)"\s*[,;]\s*"[^"]*"', value, re.I)
            link = match.group(1) if match else (value if value.lower().startswith(("http://","https://")) else "")
            if link: existing[link.strip().casefold()] = insert_row + offset

        new_rows, update_data = [], []
        for item in uploaded:
            path, url = item["path"], item["url"]
            values = [""] * (max_index + 1)
            context = {"date": datetime.now().strftime("%Y-%m-%d"), "folder_url": folder_url,
                       "file_name": path.name, "file_url": url, "zh": item.get("chinese", ""),
                       "original": item.get("original", "")}
            for mapping in mappings:
                column_index = column_to_index(mapping["column"]); source = mapping.get("source", "static")
                if source == "date": cell_value = context["date"]
                elif source == "file": cell_value = f'=HYPERLINK("{url}","{path.name.replace(chr(34), chr(34)*2)}")'
                elif source == "chinese": cell_value = context["zh"]
                elif source == "original": cell_value = context["original"]
                elif source == "folder": cell_value = folder_url
                else:
                    template = str(mapping.get("value", ""))
                    try: cell_value = template.format(**context)
                    except (KeyError, ValueError): cell_value = template
                values[column_index] = cell_value
            key = url.strip().casefold()
            if key in existing:
                self.log(f"表格已存在该文件链接，跳过：{path.name}")
            else:
                new_rows.append(values)
        if update_data:
            sheets.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": update_data}).execute()
        if new_rows:
            metadata = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
            target = next((item["properties"] for item in metadata.get("sheets", [])
                           if item["properties"]["title"] == sheet_name), None)
            if not target: raise RuntimeError(f"表格中没有找到 Sheet：{sheet_name}")
            sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [{
                "insertDimension": {"range": {"sheetId": target["sheetId"], "dimension": "ROWS",
                                                "startIndex": insert_row - 1,
                                                "endIndex": insert_row - 1 + len(new_rows)},
                                    "inheritFromBefore": False}}]}).execute()
            end_col = index_to_column(max_index)
            sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{quoted_sheet}!A{insert_row}:{end_col}{insert_row + len(new_rows) - 1}",
                valueInputOption="USER_ENTERED", body={"values": new_rows}).execute()
        return len(new_rows), len(uploaded) - len(new_rows)

    def run(self, final_dir: Path, records, source_paths, selected_files=None):
        drive, sheets, email = self._services()
        parent_id = extract_google_id(self.config.get("parent_folder", ""))
        if not parent_id: raise RuntimeError("Google Drive 父文件夹 ID 或链接无效。")
        self.log(f"Google JSON 授权成功：{email}")
        date_folder = self._find_or_create_folder(drive, datetime.now().strftime("%Y-%m-%d"), parent_id)
        if self.config.get("folder_mode") == "自定义名称":
            task_name = self.config.get("custom_folder_name", "").strip()
        else:
            first = Path(source_paths[0]).stem if source_paths else final_dir.name
            task_name = first if len(source_paths) <= 1 else f"{first}_等{len(source_paths)}个视频"
        task_name = re.sub(r'[\\/:*?"<>|]+', "_", task_name).strip() or final_dir.name
        task_folder = self._find_or_create_folder(drive, task_name, date_folder)
        if self.config.get("public_link"):
            drive.permissions().create(fileId=task_folder, body={"type": "anyone", "role": "reader"},
                                       supportsAllDrives=True).execute()
        folder_url = f"https://drive.google.com/drive/folders/{task_folder}"
        record_map = {Path(item["path"]).name: item for item in records}
        uploaded = []
        final_files = sorted((Path(path) for path in selected_files), key=lambda path: rename_natural_key(path.name)) if selected_files else sorted((path for path in final_dir.iterdir() if path.is_file()),
                             key=lambda path: rename_natural_key(path.name))
        self.log(f"只上传重命名成品：共 {len(final_files)} 个文件")
        for number, path in enumerate(final_files, 1):
            if self.cancelled(): raise RuntimeError("云端上传已停止；可以稍后点击继续上传。")
            response = self._upload_file(drive, path, task_folder)
            source_record = record_map.get(path.name, {})
            uploaded.append({"path": path, "url": response.get("webViewLink") or
                             f"https://drive.google.com/file/d/{response['id']}/view",
                             "chinese": source_record.get("chinese", ""),
                             "original": source_record.get("original", "")})
            self.log(f"云端上传完成 {number}/{len(final_files)}：{path.name}")
        sheet_note = "未开启表格写入"
        if self.config.get("write_sheet"):
            try:
                added, updated = self._write_sheet(sheets, uploaded, folder_url)
                sheet_note = f"表格新增 {added} 行，跳过已存在链接 {updated} 行"
            except Exception as exc:
                raise SheetWritePendingError(folder_url, uploaded, exc) from exc
        return folder_url, f"上传 {len(uploaded)} 个重命名成品；{sheet_note}"

    def write_sheet_only(self, uploaded, folder_url):
        _drive, sheets, email = self._services()
        self.log(f"复用已上传文件，不重新上传视频（{email}）")
        normalized=[]
        for item in uploaded:
            value=dict(item); value["path"]=Path(value.get("path","")); normalized.append(value)
        added, skipped=self._write_sheet(sheets,normalized,folder_url)
        return f"继续填表完成：新增 {added} 行，跳过已存在链接 {skipped} 行"


class PipelineWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    result_ready = Signal(str, str, str, str)
    titles_ready = Signal(str, list)
    cloud_ready = Signal(str, str)
    cloud_failed = Signal(str, str)
    cloud_sheet_pending = Signal(str, object, str)
    finished = Signal(bool, str)

    def __init__(self, store, sources, output, threshold, provider, model, language,
                 ffmpeg, prefix, date_text, suffix, start_index, padding, cloud_config=None,
                 resume_existing=True):
        super().__init__()
        self.store = store; self.sources = sources; self.output = Path(output)
        self.threshold = threshold; self.provider = provider; self.model = model
        self.language = language; self.ffmpeg = ffmpeg; self.prefix = prefix
        self.date_text = date_text; self.suffix = suffix
        self.start_index = start_index; self.padding = padding; self.cancelled = False
        self.cloud_config = cloud_config or {}
        self.resume_existing = resume_existing
        self.state = {}
        self.checkpoint_path = None

    def cancel(self):
        self.cancelled = True

    def _pipeline_key(self):
        return stable_key({
            "version": 2,
            "sources": [source_signature(source) for source in self.sources],
            "threshold": self.threshold,
            "rename": {"prefix": self.prefix, "date": self.date_text, "suffix": self.suffix,
                       "start": self.start_index, "padding": self.padding},
        })

    def _open_run(self):
        pipeline_key = self._pipeline_key()
        if self.resume_existing and self.output.exists():
            candidates = sorted((path for path in self.output.glob("流水线_*") if path.is_dir()),
                                key=lambda path: path.stat().st_mtime, reverse=True)
            for candidate in candidates:
                checkpoint = candidate / "pipeline_checkpoint.json"
                state = read_json_file(checkpoint, {})
                if state.get("pipeline_key") == pipeline_key and state.get("status") != "completed":
                    self.state = state
                    self.checkpoint_path = checkpoint
                    self.log.emit(f"发现未完成任务，自动断点续接：{candidate.name}")
                    return candidate
        run_root = self.output / f"流水线_{datetime.now():%Y%m%d_%H%M%S}"
        suffix = 1
        while run_root.exists():
            run_root = self.output / f"流水线_{datetime.now():%Y%m%d_%H%M%S}_{suffix}"
            suffix += 1
        run_root.mkdir(parents=True, exist_ok=False)
        self.checkpoint_path = run_root / "pipeline_checkpoint.json"
        self.state = {
            "version": 2, "pipeline_key": pipeline_key, "status": "running",
            "sources": self.sources, "clips": [], "transcripts": {}, "renamed": {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_checkpoint()
        return run_root

    def _save_checkpoint(self):
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(self.checkpoint_path, self.state)

    def _cut_sources(self, clips_dir):
        try:
            from scenedetect import ContentDetector, detect
        except ImportError as exc:
            raise RuntimeError("缺少智能场景检测组件 scenedetect，请到“设置与组件”一键安装。") from exc
        clips = []
        creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for source_number, source_text in enumerate(self.sources, 1):
            source = Path(source_text)
            if self.cancelled: raise RuntimeError("任务已取消")
            source_key = stable_key(source_signature(source_text))
            completed_names = self.state.setdefault("cut_completed", {}).get(source_key, [])
            completed_paths = [clips_dir / name for name in completed_names]
            if completed_paths and all(path.exists() for path in completed_paths):
                clips.extend(completed_paths)
                self.log.emit(f"断点续接：跳过已完成剪辑 {source_number}/{len(self.sources)}：{source.name}")
                self.progress.emit(round(source_number / max(1, len(self.sources)) * 30))
                continue
            for partial in clips_dir.glob(f"{source_number:03d}_*.mp4"):
                try:
                    partial.unlink()
                except OSError:
                    pass
            self.log.emit(f"分析画面切换：{source.name}")
            source_audio = probe_audio_layout(self.ffmpeg, str(source))
            scenes = detect(str(source), ContentDetector(threshold=self.threshold), show_progress=False)
            if not scenes:
                duration = video_duration(self.ffmpeg, str(source))
                scenes = [(0.0, duration)]
            for scene_number, (start, end) in enumerate(scenes, 1):
                start_seconds = start.get_seconds() if hasattr(start, "get_seconds") else float(start)
                end_seconds = end.get_seconds() if hasattr(end, "get_seconds") else float(end)
                duration = max(0.1, end_seconds - start_seconds)
                destination = clips_dir / f"{source_number:03d}_{scene_number:03d}.mp4"
                cmd = [self.ffmpeg, "-y", "-ss", f"{start_seconds:.3f}", "-t", f"{duration:.3f}",
                       "-i", str(source), "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", str(destination)]
                result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        creationflags=creation, text=True, encoding="utf-8", errors="replace")
                if result.returncode != 0:
                    raise RuntimeError(f"智能剪辑失败：{source.name}\n{result.stderr[-500:]}")
                output_audio = probe_audio_layout(self.ffmpeg, str(destination))
                if source_audio and output_audio != source_audio:
                    raise RuntimeError(
                        f"音轨校验失败：{source.name} 为 {source_audio[1]}，"
                        f"但片段 {destination.name} 为 {output_audio[1]}。已停止以避免改变声道。")
                clips.append(destination)
                audio_note = f"；音轨保持 {output_audio[1]} / {output_audio[0]}Hz" if output_audio else ""
                self.log.emit(f"已生成片段：{destination.name}{audio_note}")
            source_clips = [path.name for path in clips if path.name.startswith(f"{source_number:03d}_")]
            self.state["cut_completed"][source_key] = source_clips
            self._save_checkpoint()
            self.progress.emit(round(source_number / max(1, len(self.sources)) * 30))
        return clips

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            run_root = self._open_run()
            clips_dir = run_root / "01_智能剪辑片段"; clips_dir.mkdir(exist_ok=True)
            subtitles_dir = run_root / "02_字幕"; subtitles_dir.mkdir(exist_ok=True)
            saved_clips = [clips_dir / name for name in self.state.get("clips", [])]
            if saved_clips and all(path.exists() for path in saved_clips):
                clips = saved_clips
                self.log.emit(f"断点续接：剪辑阶段已完成，直接使用 {len(clips)} 个片段。")
                self.progress.emit(30)
            else:
                clips = self._cut_sources(clips_dir)
                self.state["clips"] = [path.name for path in clips]
                self.state["stage"] = "subtitles"
                self._save_checkpoint()
            if not clips: raise RuntimeError("没有生成任何视频片段。")
            transcriber = TranscribeWorker(self.store, self.provider, self.model, [],
                                           str(run_root / ".transcription_work"),
                                           self.language, False, self.ffmpeg, True)
            transcriber.log.connect(self.log.emit)
            captured = {}
            def capture(name, original, chinese, srt):
                captured.clear(); captured.update(name=name, original=original, chinese=chinese, srt=srt)
            transcriber.result_ready.connect(capture)
            titles, transcript_records = [], []
            for index, clip in enumerate(clips, 1):
                if self.cancelled: raise RuntimeError("任务已取消")
                cached = self.state.setdefault("transcripts", {}).get(clip.name)
                if cached:
                    captured.clear(); captured.update(name=clip.name, original=cached.get("original", ""),
                                                      chinese=cached.get("chinese", ""), srt=cached.get("srt", ""))
                    self.log.emit(f"断点续接：跳过已完成字幕 {index}/{len(clips)}：{clip.name}")
                else:
                    captured.clear(); self.log.emit(f"提取字幕 {index}/{len(clips)}：{clip.name}")
                    result = transcriber._process_one(str(clip))
                    if result and not captured:
                        captured.update(name=result["name"], original=result["original"],
                                        chinese=result["chinese"], srt=result["srt"])
                    if not captured: raise RuntimeError(f"未收到字幕结果：{clip.name}")
                    self.state["transcripts"][clip.name] = {
                        "original": captured["original"], "chinese": captured["chinese"],
                        "srt": captured["srt"], "provider": self.provider,
                    }
                    self._save_checkpoint()
                    transcriber._cleanup_source_work(str(clip))
                title = re.sub(r"\s+", " ", captured.get("chinese") or captured.get("original") or clip.stem).strip()
                titles.append(title)
                transcript_records.append({"clip_name": clip.name, "original": captured["original"],
                                           "chinese": captured["chinese"], "srt": captured["srt"]})
                (subtitles_dir / f"{clip.stem}.srt").write_text(captured["srt"], encoding="utf-8-sig")
                bilingual = f"【原文】\n{captured['original']}\n\n【简体中文】\n{captured['chinese']}"
                (subtitles_dir / f"{clip.stem}_中外文对照.txt").write_text(bilingual, encoding="utf-8-sig")
                self.result_ready.emit(clip.name, captured["original"], captured["chinese"], captured["srt"])
                self.progress.emit(30 + round(index / len(clips) * 60))

            self.state["stage"] = "rename"
            self._save_checkpoint()

            task = RenameTask(str(clips_dir), str(run_root), "03_重命名成品", self.prefix,
                              "\n".join(titles), self.date_text, self.suffix,
                              self.start_index, self.padding, True)
            final_dir = task.output_folder(); final_dir.mkdir(parents=True, exist_ok=True)
            ordered = sorted((path for path in clips_dir.iterdir() if path.is_file()),
                             key=lambda path: rename_natural_key(path.name))
            final_records = []
            for offset, source in enumerate(ordered):
                destination = final_dir / task.render_name(source.name, self.start_index + offset)
                saved_destination = self.state.setdefault("renamed", {}).get(source.name)
                if saved_destination and (final_dir / saved_destination).exists():
                    destination = final_dir / saved_destination
                    self.log.emit(f"断点续接：跳过已完成重命名 {offset + 1}/{len(ordered)}：{destination.name}")
                elif destination.exists():
                    self.log.emit(f"断点续接：检测到已复制成品，登记并跳过：{destination.name}")
                    self.state["renamed"][source.name] = destination.name
                    self._save_checkpoint()
                else:
                    shutil.copy2(source, destination)
                    self.state["renamed"][source.name] = destination.name
                    self._save_checkpoint()
                transcript = self.state["transcripts"].get(source.name, {})
                final_records.append({"path": str(destination), "original": transcript.get("original", ""),
                                      "chinese": transcript.get("chinese", "")})
            self.state["stage"] = "cloud" if self.cloud_config.get("enabled") else "completed"
            self._save_checkpoint()
            self.titles_ready.emit(str(clips_dir), titles)
            if self.cloud_config.get("enabled"):
                self.progress.emit(92); self.log.emit("开始 Google 云端同步（仅重命名成品）…")
                try:
                    folder_url, cloud_summary = GoogleCloudSync(
                        self.cloud_config, self.log.emit, lambda: self.cancelled).run(
                        final_dir, final_records, self.sources)
                    self.cloud_ready.emit(folder_url, cloud_summary)
                    self.state["status"] = "completed"
                    self.state["cloud_url"] = folder_url
                    self._save_checkpoint()
                except SheetWritePendingError as cloud_exc:
                    folder_url = cloud_exc.folder_url
                    cloud_summary = str(cloud_exc)
                    self.log.emit(cloud_summary); self.cloud_sheet_pending.emit(folder_url, cloud_exc.uploaded, str(cloud_exc))
                    self.state["status"] = "sheet_pending"; self.state["cloud_url"] = folder_url
                    self.state["pending_sheet_uploads"] = cloud_exc.uploaded; self.state["last_error"] = str(cloud_exc)
                    self._save_checkpoint()
                except Exception as cloud_exc:
                    folder_url = ""
                    cloud_summary = f"本地视频已全部处理；云同步失败：{cloud_exc}"
                    self.log.emit(cloud_summary); self.cloud_failed.emit(str(final_dir), str(cloud_exc))
                    self.state["status"] = "cloud_failed"
                    self.state["last_error"] = str(cloud_exc)
                    self._save_checkpoint()
            else:
                folder_url = ""; cloud_summary = "云端同步已关闭"
                self.state["status"] = "completed"
                self._save_checkpoint()
            self.progress.emit(100)
            message = f"流水线完成：生成 {len(clips)} 个片段和成品\n{final_dir}\n{cloud_summary}"
            if folder_url: message += f"\n{folder_url}"
            self.finished.emit(True, message)
        except Exception as exc:
            if self.checkpoint_path:
                try:
                    self.state["status"] = "failed"
                    self.state["last_error"] = str(exc)
                    self._save_checkpoint()
                except Exception:
                    pass
            self.finished.emit(False, str(exc))


class CloudUploadWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str, str)
    sheet_pending = Signal(str, object, str)

    def __init__(self, config, files, records=None, source_paths=None):
        super().__init__(); self.config = config; self.files = [Path(path) for path in files]
        self.records = records or []; self.source_paths = source_paths or [str(self.files[0])] if self.files else []
        self.cancelled = False

    def cancel(self): self.cancelled = True

    def run(self):
        try:
            if not self.files: raise RuntimeError("没有选择需要上传的成品文件。")
            folder_url, summary = GoogleCloudSync(
                self.config, self.log.emit, lambda: self.cancelled).run(
                self.files[0].parent, self.records, self.source_paths, self.files)
            self.finished.emit(True, folder_url, summary)
        except SheetWritePendingError as exc:
            self.sheet_pending.emit(exc.folder_url,exc.uploaded,str(exc))
            self.finished.emit(False,exc.folder_url,str(exc))
        except Exception as exc:
            self.finished.emit(False, "", str(exc))


class SheetFillWorker(QObject):
    log=Signal(str); finished=Signal(bool,str,str)

    def __init__(self,config,uploaded,folder_url):
        super().__init__(); self.config=config; self.uploaded=uploaded; self.folder_url=folder_url

    def run(self):
        try:
            summary=GoogleCloudSync(self.config,self.log.emit).write_sheet_only(self.uploaded,self.folder_url)
            self.finished.emit(True,self.folder_url,summary)
        except Exception as exc:
            self.finished.emit(False,self.folder_url,str(exc))


class ToolCard(QFrame):
    clicked = Signal(str)

    def __init__(self, icon_text, title, description, accent, path):
        super().__init__()
        self.path = path
        self.setObjectName("toolCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(10)
        icon = QLabel(icon_text)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(38, 38)
        icon.setStyleSheet(
            f"background:{accent}22;border:1px solid {accent}66;border-radius:9px;"
            f"color:{accent};font-size:20px;font-weight:800;")
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size:18px;font-weight:800;color:{accent};")
        header.addWidget(icon)
        header.addWidget(title_label, 1)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#a9b8cb;line-height:1.45;")
        button = QPushButton("进入  →")
        button.clicked.connect(lambda: self.clicked.emit(self.path))
        layout.addLayout(header)
        layout.addWidget(desc)
        layout.addStretch()
        layout.addWidget(button)


class GoogleAuthWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, config, interactive=True):
        super().__init__(); self.config = config; self.interactive = interactive

    def run(self):
        try:
            self.finished.emit(True, test_google_authorization(self.config, interactive=self.interactive))
        except Exception as exc:
            self.finished.emit(False, str(exc))


class GoogleSheetReadWorker(QObject):
    """读取工作表名称，或按配置表列读取去重后的下拉选项。"""
    finished = Signal(bool, object, str)

    def __init__(self, config, mode):
        super().__init__(); self.config = config; self.mode = mode

    def run(self):
        try:
            from googleapiclient.discovery import build
            credentials, identity = load_google_credentials(self.config, interactive=False)
            service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
            spreadsheet_id = extract_google_id(self.config.get("spreadsheet_id", ""))
            if not spreadsheet_id: raise RuntimeError("请先填写有效的 Google 表格 ID 或链接。")
            metadata = service.spreadsheets().get(
                spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
            sheet_names = [item.get("properties", {}).get("title", "") for item in metadata.get("sheets", [])]
            sheet_names = [name for name in sheet_names if name]
            if self.mode == "sheets":
                self.finished.emit(True, sheet_names, f"已读取 {len(sheet_names)} 个 Sheet（{identity}）")
                return
            source_sheet = self.config.get("option_sheet_name", "").strip()
            if not source_sheet: raise RuntimeError("请选择用于读取下拉选项的配置 Sheet。")
            if source_sheet not in sheet_names: raise RuntimeError(f"表格中没有找到配置 Sheet：{source_sheet}")
            start_row = max(1, int(self.config.get("option_start_row", 2)))
            quoted = "'" + source_sheet.replace("'", "''") + "'"
            result = {}
            for item in self.config.get("variable_fields", []):
                source_column = str(item.get("source_column", "")).strip().upper()
                if not source_column: continue
                column_to_index(source_column)
                response = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"{quoted}!{source_column}{start_row}:{source_column}").execute()
                values=[]; seen=set()
                for row in response.get("values", []):
                    value=str(row[0]).strip() if row else ""
                    key=value.casefold()
                    if value and key not in seen: values.append(value); seen.add(key)
                result[item.get("field", source_column)] = values
            self.finished.emit(True, result, f"已从“{source_sheet}”读取 {sum(len(v) for v in result.values())} 个去重选项")
        except Exception as exc:
            self.finished.emit(False, {}, str(exc))


class PasteOptionsTable(QTableWidget):
    """支持把 Excel/Google Sheets 的多行、多列内容直接粘贴进选项网格。"""
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            text=QApplication.clipboard().text().replace("\r\n","\n").replace("\r","\n")
            rows=[line.split("\t") for line in text.split("\n") if line or "\t" in line]
            if not rows: return
            start_row=max(0,self.currentRow()); start_col=max(0,self.currentColumn())
            needed_rows=start_row+len(rows)
            if needed_rows>self.rowCount(): self.setRowCount(needed_rows)
            for row_offset,values in enumerate(rows):
                for col_offset,value in enumerate(values):
                    column=start_col+col_offset
                    if column>=self.columnCount(): break
                    self.setItem(start_row+row_offset,column,QTableWidgetItem(value.strip()))
            return
        super().keyPressEvent(event)


class NoWheelComboBox(QComboBox):
    """下拉框仍可点击和键盘选择，但页面滚动时不会误切换值。"""
    def wheelEvent(self, event):
        event.ignore()


class VariableOptionsDialog(QDialog):
    """以“字段为列、选项为行”的方式批量维护本地上传选项。"""
    def __init__(self, fields, parent=None):
        super().__init__(parent); self.fields=[dict(item) for item in fields]
        self.setWindowTitle("配置下拉字段和选项"); self.resize(1040,620)
        root=QVBoxLayout(self); root.setContentsMargins(12,12,12,10); root.setSpacing(8)
        hint=QLabel("每一列对应一个上传字段。选中列下方的第一个空格后，可直接粘贴多行数据；也支持一次粘贴多列。保存时会自动删除空白和重复项。")
        hint.setWordWrap(True); hint.setStyleSheet("color:#7dd3fc;"); root.addWidget(hint)
        max_rows=max([len(item.get("options",[])) for item in self.fields]+[8])
        self.table=PasteOptionsTable(max_rows+3,len(self.fields))
        self.table.setHorizontalHeaderLabels([f"{item.get('field','字段')}\n（写入 {item.get('column','')} 列）" for item in self.fields])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setAlternatingRowColors(False); self.table.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.table.setStyleSheet("""
            QTableWidget { background:#0b1424; color:#f1f5f9; gridline-color:#334155; border:1px solid #334155; }
            QTableWidget::item { background:#0b1424; color:#f1f5f9; padding:4px; }
            QTableWidget::item:selected { background:#2563eb; color:#ffffff; }
            QHeaderView::section { background:#1b2a41; color:#e2e8f0; border:1px solid #334155; padding:5px; font-weight:700; }
        """)
        for column,item in enumerate(self.fields):
            for row,value in enumerate(item.get("options",[])):
                self.table.setItem(row,column,QTableWidgetItem(str(value)))
        root.addWidget(self.table,1)
        actions=QHBoxLayout(); add_rows=QPushButton("增加 10 行"); add_rows.clicked.connect(lambda:self.table.setRowCount(self.table.rowCount()+10))
        clear_column=QPushButton("清空选中列"); clear_column.clicked.connect(self._clear_selected_columns)
        actions.addWidget(add_rows); actions.addWidget(clear_column); actions.addStretch(); root.addLayout(actions)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存选项")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def _clear_selected_columns(self):
        columns={index.column() for index in self.table.selectedIndexes()}
        for column in columns:
            for row in range(self.table.rowCount()): self.table.takeItem(row,column)

    def result_fields(self):
        result=[]
        for column,item in enumerate(self.fields):
            values=[]; seen=set()
            for row in range(self.table.rowCount()):
                cell=self.table.item(row,column); value=cell.text().strip() if cell else ""; key=value.casefold()
                if value and key not in seen: values.append(value); seen.add(key)
            updated=dict(item); updated["options"]=values
            if updated.get("selected") not in values: updated["selected"]=""
            result.append(updated)
        return result


class GoogleSettingsPanel(QWidget):
    """常驻的 Google Drive / Sheets 多方案编辑器。"""
    profiles_changed = Signal()

    def __init__(self, store):
        super().__init__(); self.store = store; self.auth_thread = None; self.auth_worker = None
        self.sheet_thread = None; self.sheet_worker = None; self._loaded_options = {}; self._variable_selected = {}; self._available_sheet_names = []
        self._build(); self.load_current()
        # 授权成功后直接复用本地 OAuth token / 服务账号，不要求每次启动重新点击检查。

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(14, 12, 14, 12); root.setSpacing(7)
        top = QHBoxLayout(); title = QLabel("Google Drive / Sheets 授权与同步方案"); title.setObjectName("heading")
        top.addWidget(title); top.addStretch(); self.profile = QComboBox(); self.profile.setEditable(True); self.profile.setMinimumWidth(210)
        self.profile.currentTextChanged.connect(self.load_profile)
        save = QPushButton("保存为当前方案"); save.setObjectName("primary"); save.clicked.connect(self.save_profile)
        delete = QPushButton("删除方案"); delete.clicked.connect(self.delete_profile)
        top.addWidget(QLabel("方案")); top.addWidget(self.profile); top.addWidget(save); top.addWidget(delete); root.addLayout(top)
        hint = QLabel("把授权、Drive 文件夹、表格、Sheet、固定列和上传时选择项保存在同一方案。流水线开始前只需选择方案。")
        hint.setWordWrap(True); hint.setStyleSheet("color:#7dd3fc;"); root.addWidget(hint)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop)
        body = QWidget(); body.setMaximumWidth(1180); body_layout = QVBoxLayout(body)
        auth = QGroupBox("授权与 Drive"); auth_form = QFormLayout(auth)
        json_row = QHBoxLayout(); self.json_path = QLineEdit(); json_row.addWidget(self.json_path); browse = QPushButton("选择 JSON…")
        browse.clicked.connect(self.choose_json); json_row.addWidget(browse); auth_form.addRow("服务账号 / OAuth JSON", json_row)
        self.parent_folder = QLineEdit(); self.parent_folder.setPlaceholderText("Drive 父文件夹 ID 或链接"); auth_form.addRow("父文件夹", self.parent_folder)
        self.folder_mode = QComboBox(); self.folder_mode.addItems(["视频名称", "自定义名称"]); self.custom_folder = QLineEdit()
        mode_row = QHBoxLayout(); mode_row.addWidget(self.folder_mode); mode_row.addWidget(self.custom_folder, 1); auth_form.addRow("云端目录命名", mode_row)
        auth_row = QHBoxLayout(); self.auth_status = QLabel("尚未检查"); self.auth_status.setWordWrap(True); self.auth_button = QPushButton("授权 / 重新检查")
        self.auth_button.clicked.connect(lambda: self.check_auth(True)); auth_row.addWidget(self.auth_status, 1); auth_row.addWidget(self.auth_button); auth_form.addRow("权限状态", auth_row)
        self.public_link = QCheckBox("允许知道链接的用户查看任务文件夹"); auth_form.addRow("共享", self.public_link); body_layout.addWidget(auth)
        sheet = QGroupBox("Google Sheets 写入"); sheet_form = QFormLayout(sheet)
        self.write_sheet = QCheckBox("上传完成后写入表格"); sheet_form.addRow("启用", self.write_sheet)
        self.spreadsheet = QLineEdit(); self.spreadsheet.setPlaceholderText("表格 ID 或完整链接")
        spreadsheet_row = QHBoxLayout(); spreadsheet_row.addWidget(self.spreadsheet, 1)
        self.read_sheets_button = QPushButton("读取 Sheet 名称"); self.read_sheets_button.clicked.connect(self.read_sheet_names); spreadsheet_row.addWidget(self.read_sheets_button)
        self.sheet_name = QComboBox(); self.sheet_name.setEditable(True); self.sheet_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sheet_name.lineEdit().setPlaceholderText("选择或直接输入写入目标 Sheet")
        self.insert_row = QSpinBox(); self.insert_row.setRange(1,100000); self.insert_row.setValue(4)
        sheet_form.addRow("表格 ID", spreadsheet_row); sheet_form.addRow("写入 Sheet", self.sheet_name); sheet_form.addRow("数据起始行", self.insert_row)
        body_layout.addWidget(sheet)
        mapping_group = QGroupBox("固定字段与列映射"); mapping_layout = QVBoxLayout(mapping_group)
        self.mapping_table = QTableWidget(0, 4); self.mapping_table.setHorizontalHeaderLabels(["字段名称", "写入列", "类型", "固定内容"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch); self.mapping_table.setMinimumHeight(210)
        mapping_layout.addWidget(self.mapping_table); mbuttons = QHBoxLayout(); madd = QPushButton("新增固定字段"); madd.clicked.connect(self.add_mapping)
        mdel = QPushButton("删除选中"); mdel.clicked.connect(lambda: self.remove_rows(self.mapping_table)); mbuttons.addWidget(madd); mbuttons.addWidget(mdel); mbuttons.addStretch(); mapping_layout.addLayout(mbuttons)
        body_layout.addWidget(mapping_group)
        variable_group = QGroupBox("本次上传可选择字段"); variable_layout = QVBoxLayout(variable_group)
        variable_hint=QLabel("字段名称和写入列在下表维护；具体选项在独立窗口中按列批量粘贴。")
        variable_hint.setStyleSheet("color:#7dd3fc;"); variable_layout.addWidget(variable_hint)
        self.variable_table = QTableWidget(0, 3); self.variable_table.setHorizontalHeaderLabels(["字段名称", "写入列", "可选项数量"])
        self.variable_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.variable_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        self.variable_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents); self.variable_table.setMinimumHeight(180)
        variable_layout.addWidget(self.variable_table); vbuttons = QHBoxLayout(); configure=QPushButton("配置下拉字段和选项"); configure.setObjectName("primary"); configure.clicked.connect(self.configure_variable_options)
        vadd = QPushButton("新增字段"); vadd.clicked.connect(self.add_variable)
        vdel = QPushButton("删除选中"); vdel.clicked.connect(lambda: self.remove_rows(self.variable_table)); vbuttons.addWidget(configure); vbuttons.addWidget(vadd); vbuttons.addWidget(vdel); vbuttons.addStretch(); variable_layout.addLayout(vbuttons)
        body_layout.addWidget(variable_group); body_layout.addStretch(); scroll.setWidget(body); root.addWidget(scroll, 1)
        bottom = QHBoxLayout(); self.enabled = QCheckBox("允许流水线使用此方案"); bottom.addWidget(self.enabled); bottom.addStretch()
        apply = QPushButton("保存当前修改"); apply.clicked.connect(self.save_current); bottom.addWidget(apply); root.addLayout(bottom)

    def choose_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Google 授权 JSON", "", "JSON (*.json)")
        if path: self.json_path.setText(path); self.auth_status.setText("授权文件已变更，等待检查")

    def read_sheet_names(self):
        self._start_sheet_read("sheets")

    def _start_sheet_read(self, mode="sheets", config=None):
        if self.sheet_thread and self.sheet_thread.isRunning(): return
        config=config or self.read_ui(); self._sheet_read_mode=mode
        self.read_sheets_button.setEnabled(False); self.read_sheets_button.setText("正在读取…")
        self.sheet_thread=QThread(self); self.sheet_worker=GoogleSheetReadWorker(config,mode); self.sheet_worker.moveToThread(self.sheet_thread)
        self.sheet_thread.started.connect(self.sheet_worker.run); self.sheet_worker.finished.connect(self._sheet_read_done); self.sheet_worker.finished.connect(self.sheet_thread.quit)
        self.sheet_thread.finished.connect(self._sheet_read_ended); self.sheet_thread.finished.connect(self.sheet_thread.deleteLater); self.sheet_thread.start()

    def _sheet_read_done(self, ok, data, message):
        self.read_sheets_button.setEnabled(True); self.read_sheets_button.setText("读取 Sheet 名称")
        if not ok:
            QMessageBox.warning(self,"读取 Google 表格失败",message); return
        target=self.sheet_name.currentText(); self.sheet_name.blockSignals(True); self.sheet_name.clear(); self.sheet_name.addItems(data)
        self.sheet_name.setCurrentText(target or (data[0] if data else "")); self.sheet_name.blockSignals(False)
        self._available_sheet_names=list(data); self.save_current(silent=True)
        QMessageBox.information(self,"读取完成",message)

    def _sheet_read_ended(self):
        self.sheet_worker=None; self.sheet_thread=None

    def add_mapping(self, item=None):
        item = item or {"field":"自定义字段","column":"","source":"static","value":""}; row = self.mapping_table.rowCount(); self.mapping_table.insertRow(row)
        for col, value in enumerate((item.get("field",""), item.get("column",""), item.get("source","static"), item.get("value",""))): self.mapping_table.setItem(row,col,QTableWidgetItem(str(value)))

    def add_variable(self, item=None):
        item = item or {"field":"选择项","column":"","options":[],"selected":""}; row = self.variable_table.rowCount(); self.variable_table.insertRow(row)
        field=item.get("field",""); options=list(item.get("options",[])); self._loaded_options[field]=options; self._variable_selected[field]=item.get("selected","")
        self.variable_table.setItem(row,0,QTableWidgetItem(str(field))); self.variable_table.setItem(row,1,QTableWidgetItem(str(item.get("column",""))))
        count=QTableWidgetItem(str(len(options))); count.setFlags(count.flags()&~Qt.ItemFlag.ItemIsEditable); self.variable_table.setItem(row,2,count)

    def configure_variable_options(self):
        fields=[]
        for row in range(self.variable_table.rowCount()):
            field=self.variable_table.item(row,0).text().strip() if self.variable_table.item(row,0) else ""
            column=self.variable_table.item(row,1).text().strip().upper() if self.variable_table.item(row,1) else ""
            if field and column:
                fields.append({"field":field,"column":column,"options":list(self._loaded_options.get(field,[])),"selected":self._variable_selected.get(field,"")})
        if not fields:
            QMessageBox.information(self,"没有字段","请先添加字段名称和写入列。")
            return
        dialog=VariableOptionsDialog(fields,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        updated=dialog.result_fields(); self.variable_table.setRowCount(0); self._loaded_options={}; self._variable_selected={}
        for item in updated: self.add_variable(item)
        self.save_current(silent=True)

    def remove_rows(self, table):
        for row in sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True): table.removeRow(row)

    def read_ui(self):
        mappings=[]
        for row in range(self.mapping_table.rowCount()):
            values=[self.mapping_table.item(row,c).text().strip() if self.mapping_table.item(row,c) else "" for c in range(4)]
            if values[1]: mappings.append({"field":values[0] or "自定义字段","column":values[1].upper(),"source":values[2] or "static","value":values[3]})
        variables=[]
        for row in range(self.variable_table.rowCount()):
            values=[self.variable_table.item(row,c).text().strip() if self.variable_table.item(row,c) else "" for c in range(2)]
            if values[0] and values[1]: variables.append({"field":values[0],"column":values[1].upper(),"options":list(self._loaded_options.get(values[0],[])),"selected":self._variable_selected.get(values[0],"")})
        base = dict(self.store.data.get("google_sync", {}))
        base.update({"enabled":self.enabled.isChecked(),"json_path":self.json_path.text().strip(),"parent_folder":self.parent_folder.text().strip(),
                     "folder_mode":self.folder_mode.currentText(),"custom_folder_name":self.custom_folder.text().strip(),"public_link":self.public_link.isChecked(),
                     "write_sheet":self.write_sheet.isChecked(),"spreadsheet_id":self.spreadsheet.text().strip(),"sheet_name":self.sheet_name.currentText().strip(),
                     "available_sheet_names":list(self._available_sheet_names),"insert_row":self.insert_row.value(),"sheet_mappings":mappings,"variable_fields":variables,"mapping_ui_version":3})
        return base

    def apply(self, config):
        self.json_path.setText(config.get("json_path","")); self.parent_folder.setText(config.get("parent_folder","")); self.folder_mode.setCurrentText(config.get("folder_mode","视频名称"))
        self.custom_folder.setText(config.get("custom_folder_name","")); self.public_link.setChecked(config.get("public_link",False)); self.write_sheet.setChecked(config.get("write_sheet",False))
        self.spreadsheet.setText(config.get("spreadsheet_id","")); self._available_sheet_names=list(config.get("available_sheet_names",[]))
        current_sheet=config.get("sheet_name",""); self.sheet_name.blockSignals(True); self.sheet_name.clear(); self.sheet_name.addItems(self._available_sheet_names); self.sheet_name.setCurrentText(current_sheet); self.sheet_name.blockSignals(False)
        self.insert_row.setValue(int(config.get("insert_row",4))); self.enabled.setChecked(config.get("enabled",False))
        self.mapping_table.setRowCount(0)
        for item in config.get("sheet_mappings",DEFAULT_SHEET_MAPPINGS): self.add_mapping(item)
        self.variable_table.setRowCount(0); self._loaded_options={}; self._variable_selected={}
        for item in config.get("variable_fields",DEFAULT_VARIABLE_FIELDS): self.add_variable(item)
        if config.get("auth_ok"):
            self.auth_status.setText(f"已授权：{config.get('auth_identity','Google 账号')}（启动后自动复用）"); self.auth_status.setStyleSheet("color:#86efac;")
        else: self.auth_status.setText("尚未授权或需要重新检查"); self.auth_status.setStyleSheet("color:#fbbf24;")

    def load_current(self):
        config = self.store.data["google_sync"]; profiles = config.get("sync_profiles",{})
        self.profile.blockSignals(True); self.profile.clear(); self.profile.addItems(profiles.keys()); self.profile.blockSignals(False)
        active = config.get("active_sync_profile","")
        if active in profiles: self.profile.setCurrentText(active); self.apply(profiles[active])
        else: self.apply(config)

    def load_profile(self, name):
        profile = self.store.data["google_sync"].get("sync_profiles",{}).get(name)
        if profile: self.apply(profile)

    def save_current(self, silent=False):
        config = self.read_ui(); profiles = dict(self.store.data["google_sync"].get("sync_profiles",{}))
        profile_name=self.profile.currentText().strip()
        if profile_name in profiles:
            profile_data=dict(config); profile_data.pop("sync_profiles",None); profile_data.pop("active_sync_profile",None); profiles[profile_name]=profile_data
        config["sync_profiles"] = profiles; config["active_sync_profile"] = profile_name if profile_name in profiles else ""
        self.store.data["google_sync"] = config; self.store.save(); self.profiles_changed.emit()
        if not silent: QMessageBox.information(self,"配置已保存","Google 同步配置已保存。")

    def save_profile(self):
        name = self.profile.currentText().strip()
        if not name:
            name, ok = QInputDialog.getText(self,"保存同步方案","方案名称（例如：方案1）：")
            if not ok or not name.strip(): return
            name = name.strip()
        config = self.read_ui(); profiles = dict(self.store.data["google_sync"].get("sync_profiles",{})); config.pop("sync_profiles",None)
        profiles[name] = config; current = dict(config); current["sync_profiles"] = profiles; current["active_sync_profile"] = name
        self.store.data["google_sync"] = current; self.store.save(); self.load_current(); self.profile.setCurrentText(name); self.profiles_changed.emit()
        QMessageBox.information(self,"方案已保存",f"同步方案“{name}”已保存并设为当前方案。")

    def delete_profile(self):
        name=self.profile.currentText().strip(); profiles=dict(self.store.data["google_sync"].get("sync_profiles",{}))
        if name not in profiles: return
        del profiles[name]; self.store.data["google_sync"]["sync_profiles"]=profiles; self.store.data["google_sync"]["active_sync_profile"]=""; self.store.save(); self.load_current(); self.profiles_changed.emit()

    def check_auth(self, interactive=True):
        if self.auth_thread and self.auth_thread.isRunning(): return
        config=self.read_ui(); self.auth_status.setText("正在检查 Google 权限…"); self.auth_button.setEnabled(False)
        self.auth_thread=QThread(self); self.auth_worker=GoogleAuthWorker(config, interactive); self.auth_worker.moveToThread(self.auth_thread)
        self.auth_thread.started.connect(self.auth_worker.run); self.auth_worker.finished.connect(self.auth_done); self.auth_worker.finished.connect(self.auth_thread.quit)
        self.auth_thread.finished.connect(self.auth_ended); self.auth_thread.finished.connect(self.auth_thread.deleteLater); self.auth_thread.start()

    def auth_done(self, ok, message):
        self.auth_button.setEnabled(True); config=self.read_ui(); config["auth_ok"]=ok; config["auth_identity"]=message if ok else ""; config["auth_checked"]=datetime.now().isoformat(timespec="seconds")
        profiles=dict(self.store.data["google_sync"].get("sync_profiles",{})); profile_name=self.profile.currentText().strip()
        if profile_name in profiles:
            profile_data=dict(config); profile_data.pop("sync_profiles",None); profile_data.pop("active_sync_profile",None); profiles[profile_name]=profile_data
        config["sync_profiles"]=profiles; config["active_sync_profile"]=profile_name if profile_name in profiles else ""
        self.store.data["google_sync"]=config; self.store.save(); self.profiles_changed.emit()
        self.auth_status.setText(("授权成功：" if ok else "授权失败：")+message); self.auth_status.setStyleSheet("color:#86efac;" if ok else "color:#fca5a5;")
        if not ok: QMessageBox.warning(self,"Google 授权失败",message)

    def auth_ended(self): self.auth_worker=None; self.auth_thread=None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        _startup_trace("MainWindow init")
        # 打包版的 FFmpeg / FFprobe 位于 PyInstaller 解包目录；将它与用户组件目录
        # 一并加入 PATH，确保截图、剪辑、水印、字幕和组件检测使用同一套工具。
        media_paths = [str(component_bin())]
        bundled_media = str(bundled_media_tool("ffmpeg").parent)
        if bundled_media_tool("ffmpeg").exists():
            media_paths.insert(0, bundled_media)
        current_path = os.environ.get("PATH", "")
        current_parts = current_path.split(os.pathsep)
        prepend = [path for path in media_paths if path not in current_parts]
        if prepend:
            os.environ["PATH"] = os.pathsep.join(prepend + [current_path])
        self.store = ConfigStore()
        self.thread = None
        self.worker = None
        self.cloud_thread = None
        self.cloud_worker = None
        self.pending_upload_files = []
        self.pending_sheet_uploads = []; self.pending_sheet_folder_url = ""
        self.setWindowTitle(APP_NAME)
        self.resize(1380, 820)
        self.setMinimumSize(1080, 680)
        icon = resource_path("logo.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        _startup_trace("building UI")
        self._build_ui()
        _startup_trace("UI built")
        self._refresh_keys()
        _startup_trace("keys refreshed")

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav = QFrame()
        nav.setObjectName("nav")
        nav.setFixedHeight(62)
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(18, 10, 18, 10)
        nav_layout.setSpacing(5)
        brand = QLabel("▶  视频工具合集")
        brand.setObjectName("brand")
        nav_layout.addWidget(brand)
        nav_layout.addSpacing(16)
        self.nav_buttons = []
        nav_items = (("首页", 0), ("批量截图", 1), ("智能剪辑", 2), ("动态文案/水印", 3),
                     ("批量重命名", 4), ("清除元数据", 10), ("字幕提取", 5), ("自动流水线", 8),
                     ("密钥管理", 6), ("设置与组件", 7), ("帮助", 9))
        for text, page_index in nav_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("navButton")
            btn.setProperty("pageIndex", page_index)
            btn.clicked.connect(lambda checked=False, idx=page_index: self._show_page(idx))
            nav_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        nav_layout.addStretch()
        privacy = QLabel("密钥仅存本机")
        privacy.setStyleSheet("color:#64748b;font-size:11px;")
        nav_layout.addWidget(privacy)
        outer.addWidget(nav)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._home_page())
        _startup_trace("home page ready")
        self.screenshot_page = ScreenshotPage()
        _startup_trace("screenshot page ready")
        self.smartcut_page = SmartCutPage()
        _startup_trace("smartcut page ready")
        self.watermark_tabs = QTabWidget()
        self.watermark_page = WatermarkPage()
        self.dynamic_caption_page = DynamicCaptionPage(
            self._caption_transcribe, self._text_to_speech, self._find_ffmpeg,
            TRANSCRIPTION_PROVIDERS, AUTO_PROVIDER)
        reels_tab_index = self.watermark_tabs.addTab(self.dynamic_caption_page, "动态 Reels 流水线")
        # 开发/预览版默认开放 Reels；稳定发布时仍可设置
        # VIDEO_TOOLKIT_SHOW_REELS=0 单独隐藏，不影响其他水印功能。
        show_reels_preview = os.environ.get("VIDEO_TOOLKIT_SHOW_REELS", "1").strip() != "0"
        self.watermark_tabs.setTabVisible(reels_tab_index, show_reels_preview)
        watermark_tab_index = self.watermark_tabs.addTab(self.watermark_page, "视频 / 图片水印")
        self.watermark_tabs.addTab(MetadataPage(), "素材元数据清理")
        self.watermark_tabs.setCurrentIndex(reels_tab_index if show_reels_preview else watermark_tab_index)
        _startup_trace("watermark page ready")
        self.rename_page = RenamePage()
        _startup_trace("rename page ready")
        self.pages.addWidget(self.screenshot_page)
        self.pages.addWidget(self.smartcut_page)
        self.pages.addWidget(self.watermark_tabs)
        self.pages.addWidget(self.rename_page)
        self.pages.addWidget(self._subtitle_page())
        _startup_trace("subtitle page ready")
        self.pages.addWidget(self._keys_page())
        _startup_trace("keys page ready")
        self.settings_page = QTabWidget()
        self.component_settings_page = SettingsPage()
        self.google_settings_page = GoogleSettingsPanel(self.store)
        self.settings_page.addTab(self.component_settings_page, "组件检测与安装")
        self.settings_page.addTab(self.google_settings_page, "Google 授权与同步方案")
        _startup_trace("settings page ready")
        self.pages.addWidget(self.settings_page)
        self.pages.addWidget(self._pipeline_page())
        self.google_settings_page.profiles_changed.connect(self._refresh_pipeline_profiles)
        _startup_trace("pipeline page ready")
        self.pages.addWidget(self._help_page())
        _startup_trace("help page ready")
        self.metadata_page = MetadataPage()
        self.pages.addWidget(self.metadata_page)
        _startup_trace("metadata page ready")
        outer.addWidget(self.pages, 1)
        self._show_page(0)

    def _page_shell(self, title, subtitle):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("heading")
        sub = QLabel(subtitle)
        sub.setStyleSheet("color:#94a3b8;")
        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addSpacing(6)
        return page, layout

    def _home_page(self):
        page, layout = self._page_shell("一站式视频工作台", "选择需要的业务功能；文件、文件夹和网络链接均可按模块批量处理。")
        tools = [
            ("▣", "视频批量截图",
             "• YouTube / FB / IG / TikTok 网络链接取帧\n• 本地视频、文件夹拖拽与父子目录选择\n• 自定义截图间隔、数量、画质和命名\n• 保存任务记录并自动进行历史查重",
             "#38bdf8", "page:1"),
            ("✂", "智能剪辑",
             "• 根据画面变化自动检测视频场景\n• 支持自定义片段时长和批量切分\n• 多视频、文件夹拖拽和任务队列\n• 输出成品并保留视频原有立体声音频",
             "#a78bfa", "page:2"),
            ("◉", "视频 / 图片水印",
             "• 批量添加文字水印与图片水印\n• 支持多层水印、模板保存和快速复用\n• 可调整位置、透明度、边距与预览比例\n• 视频和图片素材均可批量处理",
             "#34d399", "page:3"),
            ("A↔", "视频 / 文件重命名",
             "• 文件自然排序及 Windows 安全名称处理\n• 标题、日期、前后缀和连续编号组合\n• 执行前完整预览新旧文件名\n• 多套前缀与后缀方案保存和快速切换",
             "#fbbf24", "page:4"),
            ("CC", "智能字幕提取",
             "• 本地 Whisper 无需密钥即可识别\n• 在线服务支持多密钥检测与轮询\n• 批量处理网络链接、本地视频或音频\n• 中外文对照、全部复制及批量导出字幕",
             "#fb7185", "page:5"),
            ("⇢", "自动流水线",
             "• 智能剪辑 → 字幕提取 → 标题生成 → 批量重命名\n• 批量上传重命名成品并填写 Google Sheets\n• 上传成功、填表失败时可单独继续填表\n• 支持断点续接、方案保存和重复链接跳过",
             "#22d3ee", "page:8"),
            ("⌫", "批量清除素材元数据",
             "• 无损清除视频/音频的标题、作者、设备和章节信息\n• 清除图片 EXIF、XMP、拍摄时间和位置数据\n• 文件与文件夹拖拽、父目录和子目录批量选择\n• 可作为自动流水线的素材预处理步骤",
             "#60a5fa", "page:10"),
        ]
        rows = [QHBoxLayout() for _ in range((len(tools) + 1) // 2)]
        for idx, item in enumerate(tools):
            card = ToolCard(*item)
            card.clicked.connect(self._launch_tool)
            rows[idx // 2].addWidget(card)
        for row in rows:
            layout.addLayout(row, 1)
        return page

    def _help_page(self):
        page, layout = self._page_shell("帮助与使用说明", "从添加素材到导出成品的常用操作说明；遇到组件问题也可以在这里快速定位。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(2, 2, 8, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        sections = [
            ("快速开始", "1. 在顶部选择需要的工具。\n2. 拖入视频、音频、文件夹，或点击按钮选择素材。\n3. 检查输出目录和处理参数。\n4. 先预览，再开始批量执行。\n5. 完成后从日志或结果区查看输出位置。"),
            ("素材添加与拖拽", "需要选择素材的页面均支持拖入文件或文件夹。选择父目录后，可以从子文件夹列表继续添加指定目录。批量截图和字幕提取还支持 YouTube、Facebook、Instagram、TikTok 链接，每行填写一个。"),
            ("字幕提取", "可以使用“本地 Whisper（无需密钥）”，也可以配置 Groq、Gemini、ElevenLabs、Gladia。批量结果可查看当前项目或全部项目，并支持复制全部原文、复制全部中外文对照及批量导出字幕。"),
            ("视频 / 图片水印", "保留原有静态水印功能，并开放动态 Reels 流水线：视频、音频、独立文案、字幕样式、蒙版和批量导出。"),
            ("素材元数据清理", "可从顶部“清除元数据”直接进入，也可在“视频 / 图片水印”中打开对应子页。程序会显示清理前后的元数据信息；视频和音频使用无损流复制且保留原声道，图片重新保存干净副本以移除 EXIF/XMP，原文件不会修改。"),
            ("自动流水线", "流水线按“智能剪辑 → 提取字幕 → 字幕生成标题 → 批量重命名成品 → 批量上传 → 批量填表”执行。只上传重命名成品；支持断点续接、保存同步方案、继续上传和继续填表，并按云端文件链接唯一值跳过已经填写的记录。"),
            ("密钥与云端授权", "密钥管理支持一次粘贴多枚密钥、自动检测、状态诊断及轮询调用。Google 云端同步需要在流水线配置中选择正确的授权 JSON；授权或上传失败不会删除已经处理好的本地成品，可稍后继续上传。"),
            ("组件检查与常见问题", "FFmpeg、FFprobe 或 Python 组件异常时，进入“设置与组件”统一检测并一键恢复。网络链接无法解析时可更新 yt-dlp。macOS 首次打开若被系统拦截，请在 Finder 中右键应用并选择“打开”。"),
            ("长视频与断点续接", "字幕提取和自动流水线默认开启“自动续接”。同一批素材再次执行时，程序会跳过已成功的视频；流水线还会跳过已经完成的剪辑和重命名。请保留流水线输出目录及其中的 pipeline_checkpoint.json。需要全部重做时，取消勾选自动续接。"),
            ("提高本地识别效率", "本地 Whisper 会直接流式读取媒体，避免先生成整段超大 WAV。建议普通电脑使用 small 模型；GPU 不适合 FP16 时会自动选择可用计算模式或回退 CPU INT8。ONNX Runtime 用于 VAD 静音过滤，缺失时程序会自动关闭 VAD 继续运行。Groq 长视频会自动拆成 90 秒分段并逐段保存进度。"),
        ]
        for index, (title, body) in enumerate(sections):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(14, 14, 14, 12)
            text = QLabel(body)
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setStyleSheet("color:#b7c5d8;line-height:1.55;")
            group_layout.addWidget(text)
            grid.addWidget(group, index // 2, index % 2)
        for row in range(5):
            grid.setRowStretch(row, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        actions = QHBoxLayout()
        keys = QPushButton("打开密钥管理")
        keys.clicked.connect(lambda: self._show_page(6))
        components = QPushButton("检查设置与组件")
        components.setObjectName("primary")
        components.clicked.connect(lambda: self._show_page(7))
        actions.addStretch()
        actions.addWidget(keys)
        actions.addWidget(components)
        layout.addLayout(actions)
        return page

    def _subtitle_page(self):
        page, layout = self._page_shell("智能提取视频字幕", "结果直接显示在当前窗口；支持原文与简体中文对照、一键复制。")
        self.subtitle_results = {}

        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setChildrenCollapsible(False)
        control_panel = QFrame(); control_panel.setObjectName("panel")
        control_panel.setMinimumWidth(480)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(12, 10, 12, 10); control_layout.setSpacing(8)

        local_header = QHBoxLayout(); local_header.addWidget(QLabel("本地媒体（可拖入文件或文件夹）")); local_header.addStretch()
        self.media_source_hint = QLabel("尚未添加")
        self.media_source_hint.setStyleSheet("color:#7dd3fc;")
        local_header.addWidget(self.media_source_hint); control_layout.addLayout(local_header)
        self.file_list = MediaDropList()
        self.file_list.paths_dropped.connect(self._add_media_paths)
        self.file_list.setMinimumHeight(120); self.file_list.setMaximumHeight(185)
        file_buttons = QHBoxLayout()
        add = QPushButton("添加视频 / 音频")
        add.clicked.connect(self._add_media)
        add_folder = QPushButton("添加文件夹"); add_folder.clicked.connect(self._add_media_folder)
        choose_parent = QPushButton("选择父目录"); choose_parent.clicked.connect(self._choose_parent_folder)
        remove = QPushButton("移除选中")
        remove.clicked.connect(self._remove_selected_media)
        file_buttons.addWidget(add)
        file_buttons.addWidget(add_folder)
        file_buttons.addWidget(choose_parent)
        file_buttons.addWidget(remove)
        control_layout.addWidget(self.file_list)
        control_layout.addLayout(file_buttons)

        folder_row = QHBoxLayout(); folder_row.addWidget(QLabel("子文件夹"))
        self.subfolder_combo = QComboBox(); self.subfolder_combo.setEnabled(False)
        self.subfolder_combo.setPlaceholderText("先选择父目录")
        add_subfolder = QPushButton("添加所选目录"); add_subfolder.clicked.connect(self._add_selected_subfolder)
        folder_row.addWidget(self.subfolder_combo, 1); folder_row.addWidget(add_subfolder)
        control_layout.addLayout(folder_row)

        url_header = QHBoxLayout(); url_header.addWidget(QLabel("网络视频链接（每行一个）")); url_header.addStretch()
        paste_urls = QPushButton("粘贴"); paste_urls.clicked.connect(
            lambda: self.url_input.setPlainText(QApplication.clipboard().text()))
        clear_urls = QPushButton("清空"); clear_urls.clicked.connect(lambda: self.url_input.clear())
        url_header.addWidget(paste_urls); url_header.addWidget(clear_urls)
        control_layout.addLayout(url_header)
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "支持 YouTube、Facebook、Instagram、TikTok；可一次粘贴多个链接，每行一个")
        self.url_input.setMinimumHeight(64); self.url_input.setMaximumHeight(88)
        control_layout.addWidget(self.url_input)

        settings_group = QGroupBox("识别设置")
        settings_group.setMinimumHeight(190)
        form = QFormLayout(settings_group)
        form.setContentsMargins(10, 10, 10, 8); form.setSpacing(6)
        self.provider_combo = QComboBox(); self.provider_combo.addItems(TRANSCRIPTION_PROVIDERS)
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        form.addRow("识别服务", self.provider_combo)
        self.model_edit = QLineEdit("按优先级自动匹配")
        form.addRow("模型", self.model_edit)
        self.language_edit = QLineEdit("auto")
        self.language_edit.setPlaceholderText("auto / zh / en / pt …")
        form.addRow("语言代码", self.language_edit)
        self.diarize_check = QCheckBox("区分说话人（服务支持时启用）")
        form.addRow("说话人", self.diarize_check)
        priority_widget = QWidget(); priority_row = QHBoxLayout(priority_widget)
        priority_row.setContentsMargins(0, 0, 0, 0); priority_row.setSpacing(5)
        self.priority_label = QLabel(); self.priority_label.setWordWrap(True)
        priority_btn = QPushButton("调整顺序"); priority_btn.clicked.connect(self._open_priority_dialog)
        priority_row.addWidget(self.priority_label, 1); priority_row.addWidget(priority_btn)
        form.addRow("自动优先级", priority_widget)
        control_layout.addWidget(settings_group)

        self.transcribe_progress = QProgressBar(); self.transcribe_progress.setValue(0)
        control_layout.addWidget(self.transcribe_progress)
        actions = QHBoxLayout()
        self.subtitle_resume_check = QCheckBox("自动续接上次进度")
        self.subtitle_resume_check.setChecked(True)
        self.subtitle_resume_check.setToolTip("同一批素材和识别设置再次执行时，自动跳过已成功的视频")
        self.start_btn = QPushButton("开始提取字幕"); self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start_transcription)
        self.cancel_btn = QPushButton("取消"); self.cancel_btn.setEnabled(False); self.cancel_btn.clicked.connect(self._cancel_transcription)
        actions.addWidget(self.subtitle_resume_check); actions.addStretch()
        actions.addWidget(self.cancel_btn); actions.addWidget(self.start_btn)
        control_layout.addLayout(actions)
        control_layout.addWidget(QLabel("运行日志"))
        self.log_box = QPlainTextEdit(); self.log_box.setReadOnly(True)
        control_layout.addWidget(self.log_box, 1)

        result_panel = QFrame(); result_panel.setObjectName("panel")
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(12, 10, 12, 10); result_layout.setSpacing(7)

        result_bar = QHBoxLayout(); result_bar.addWidget(QLabel("查看结果"))
        self.result_combo = QComboBox(); self.result_combo.addItem(ALL_RESULTS_LABEL)
        self.result_combo.currentTextChanged.connect(self._show_subtitle_result)
        copy_original = QPushButton("复制当前原文"); copy_original.clicked.connect(lambda: QApplication.clipboard().setText(self.original_result.toPlainText()))
        copy_bilingual = QPushButton("复制当前对照"); copy_bilingual.clicked.connect(self._copy_bilingual)
        copy_all_original = QPushButton("复制全部原文"); copy_all_original.clicked.connect(self._copy_all_original)
        copy_all_bilingual = QPushButton("复制全部对照"); copy_all_bilingual.clicked.connect(self._copy_all_bilingual)
        export_all = QPushButton("批量导出字幕"); export_all.setObjectName("primary"); export_all.clicked.connect(self._export_all_subtitles)
        result_bar.addWidget(self.result_combo, 1); result_bar.addWidget(copy_original); result_bar.addWidget(copy_bilingual)
        result_bar.addWidget(copy_all_original); result_bar.addWidget(copy_all_bilingual); result_bar.addWidget(export_all)
        result_layout.addLayout(result_bar)
        result_split = QSplitter(Qt.Orientation.Vertical); result_split.setChildrenCollapsible(False)
        original_group = QGroupBox("识别原文"); original_layout = QVBoxLayout(original_group)
        self.original_result = QPlainTextEdit(); self.original_result.setReadOnly(True); original_layout.addWidget(self.original_result)
        chinese_group = QGroupBox("简体中文对照"); chinese_layout = QVBoxLayout(chinese_group)
        self.chinese_result = QPlainTextEdit(); self.chinese_result.setReadOnly(True); chinese_layout.addWidget(self.chinese_result)
        result_split.addWidget(original_group); result_split.addWidget(chinese_group); result_split.setSizes([360, 360])
        result_layout.addWidget(result_split, 1)

        control_scroll = QScrollArea(); control_scroll.setWidgetResizable(True); control_scroll.setWidget(control_panel)
        main_split.addWidget(control_scroll); main_split.addWidget(result_panel)
        main_split.setStretchFactor(0, 0); main_split.setStretchFactor(1, 1)
        main_split.setSizes([520, 1000])
        layout.addWidget(main_split, 1)
        self._refresh_priority_label()
        self._provider_changed(AUTO_PROVIDER)
        return page

    def _pipeline_page(self):
        page, layout = self._page_shell(
            "批量自动流水线",
            "一次完成：智能画面剪辑 → 批量字幕 → 字幕作为标题 → 按规则重命名；中间结果全部保留。")
        split = QSplitter(Qt.Orientation.Horizontal); split.setChildrenCollapsible(False)
        left = QFrame(); left.setObjectName("panel"); left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 10, 12, 10); left_layout.setSpacing(7)
        left_layout.addWidget(QLabel("1. 原始视频（可拖入多个视频或文件夹）"))
        self.pipeline_files = MediaDropList(); self.pipeline_files.setMinimumHeight(145)
        self.pipeline_files.paths_dropped.connect(self._pipeline_add_paths); left_layout.addWidget(self.pipeline_files)
        source_buttons = QHBoxLayout()
        add_files = QPushButton("添加视频"); add_files.clicked.connect(self._pipeline_choose_files)
        add_folder = QPushButton("添加文件夹"); add_folder.clicked.connect(self._pipeline_choose_folder)
        parent_folder = QPushButton("选择父目录"); parent_folder.clicked.connect(self._pipeline_choose_parent)
        clear = QPushButton("清空"); clear.clicked.connect(self.pipeline_files.clear)
        for button in (add_files, add_folder, parent_folder, clear): source_buttons.addWidget(button)
        left_layout.addLayout(source_buttons)
        child_row = QHBoxLayout(); child_row.addWidget(QLabel("子文件夹"))
        self.pipeline_subfolders = QComboBox(); self.pipeline_subfolders.setEnabled(False)
        add_child = QPushButton("添加所选目录"); add_child.clicked.connect(self._pipeline_add_selected_folder)
        child_row.addWidget(self.pipeline_subfolders, 1); child_row.addWidget(add_child); left_layout.addLayout(child_row)

        settings = QGroupBox("2. 流程设置"); form = QFormLayout(settings)
        output_row = QHBoxLayout(); self.pipeline_output = QLineEdit(str(Path.cwd() / "流水线输出"))
        choose_output = QPushButton("选择…"); choose_output.clicked.connect(self._pipeline_choose_output)
        output_row.addWidget(self.pipeline_output); output_row.addWidget(choose_output)
        output_widget = QWidget(); output_widget.setLayout(output_row); form.addRow("输出目录", output_widget)
        self.pipeline_threshold = QSpinBox(); self.pipeline_threshold.setRange(1, 100); self.pipeline_threshold.setValue(27)
        form.addRow("画面阈值", self.pipeline_threshold)
        self.pipeline_provider = QComboBox(); self.pipeline_provider.addItems(TRANSCRIPTION_PROVIDERS)
        form.addRow("字幕服务", self.pipeline_provider)
        self.pipeline_language = QLineEdit("auto"); form.addRow("语言", self.pipeline_language)
        rename_line = QHBoxLayout()
        self.pipeline_prefix = QLineEdit(); self.pipeline_prefix.setPlaceholderText("前缀")
        self.pipeline_date = QLineEdit(datetime.now().strftime("%Y%m%d"))
        self.pipeline_suffix = QLineEdit("FF-PT")
        rename_line.addWidget(self.pipeline_prefix); rename_line.addWidget(self.pipeline_date); rename_line.addWidget(self.pipeline_suffix)
        rename_widget = QWidget(); rename_widget.setLayout(rename_line); form.addRow("前缀/日期/后缀", rename_widget)
        number_line = QHBoxLayout(); self.pipeline_start = QSpinBox(); self.pipeline_start.setRange(0, 999999); self.pipeline_start.setValue(1)
        self.pipeline_padding = QSpinBox(); self.pipeline_padding.setRange(1, 12); self.pipeline_padding.setValue(3)
        number_line.addWidget(QLabel("起始编号")); number_line.addWidget(self.pipeline_start)
        number_line.addWidget(QLabel("位数")); number_line.addWidget(self.pipeline_padding); number_line.addStretch()
        number_widget = QWidget(); number_widget.setLayout(number_line); form.addRow("编号", number_widget)
        left_layout.addWidget(settings)
        cloud_group = QGroupBox("3. Google 云端同步（只上传重命名成品）")
        cloud_layout = QVBoxLayout(cloud_group); cloud_layout.setContentsMargins(10, 9, 10, 9)
        cloud_top = QHBoxLayout()
        self.pipeline_cloud_check = QCheckBox("流水线完成后自动上传并写入表格")
        self.pipeline_cloud_check.setChecked(self.store.data["google_sync"].get("enabled", False))
        self.pipeline_cloud_check.toggled.connect(self._pipeline_cloud_toggled)
        cloud_config = QPushButton("打开设置与组件")
        cloud_config.clicked.connect(self._open_google_settings)
        cloud_top.addWidget(self.pipeline_cloud_check); cloud_top.addStretch(); cloud_top.addWidget(cloud_config); cloud_layout.addLayout(cloud_top)
        profile_row = QHBoxLayout(); profile_row.addWidget(QLabel("同步方案")); self.pipeline_sync_profile = NoWheelComboBox()
        self.pipeline_sync_profile.currentTextChanged.connect(self._pipeline_profile_changed)
        self.pipeline_save_profile=QPushButton("保存方案"); self.pipeline_save_profile.clicked.connect(self._save_pipeline_sync_profile)
        profile_row.addWidget(self.pipeline_sync_profile, 1); profile_row.addWidget(self.pipeline_save_profile); cloud_layout.addLayout(profile_row)
        self.pipeline_profile_hint = QLabel("未选择同步方案"); self.pipeline_profile_hint.setWordWrap(True); self.pipeline_profile_hint.setStyleSheet("color:#94a3b8;")
        self.pipeline_profile_hint.setVisible(False)
        self.pipeline_variable_group = QGroupBox("本次上传选择（每次可重新选择）")
        self.pipeline_variable_form = QFormLayout(self.pipeline_variable_group); self.pipeline_variable_form.setVerticalSpacing(6)
        self.pipeline_runtime_values = {}; self.pipeline_runtime_sheet = ""; self._pipeline_runtime_profile = None
        cloud_layout.addWidget(self.pipeline_variable_group)
        left_layout.addWidget(cloud_group)
        self.pipeline_resume_check = QCheckBox("自动续接未完成任务（跳过已完成的剪辑、字幕和重命名）")
        self.pipeline_resume_check.setChecked(True)
        self.pipeline_resume_check.setToolTip("取消勾选后会创建一个全新的流水线任务")
        left_layout.addWidget(self.pipeline_resume_check)
        self.pipeline_progress = QProgressBar(); left_layout.addWidget(self.pipeline_progress)
        actions = QHBoxLayout(); actions.addStretch()
        self.pipeline_stop = QPushButton("停止"); self.pipeline_stop.setEnabled(False); self.pipeline_stop.clicked.connect(self._pipeline_cancel)
        self.pipeline_start_btn = QPushButton("开始自动流水线"); self.pipeline_start_btn.setObjectName("primary")
        self.pipeline_start_btn.clicked.connect(self._pipeline_start)
        actions.addWidget(self.pipeline_stop); actions.addWidget(self.pipeline_start_btn); left_layout.addLayout(actions)

        right = QFrame(); right.setObjectName("panel"); right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 10, 12, 10); right_layout.setSpacing(7)
        step_text = QLabel("① 智能剪辑   →   ② 提取字幕   →   ③ 字幕生成标题   →   ④ 批量重命名成品   →   ⑤ 批量上传   →   ⑥ 批量填表")
        step_text.setWordWrap(True)
        step_text.setStyleSheet("color:#7dd3fc;font-size:14px;font-weight:700;padding:8px;")
        right_layout.addWidget(step_text)
        self.pipeline_cloud_result = QLabel("云端同步：等待执行")
        self.pipeline_cloud_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.pipeline_cloud_result.setOpenExternalLinks(True); self.pipeline_cloud_result.setWordWrap(True)
        self.pipeline_cloud_result.setStyleSheet("color:#86efac;padding:4px;")
        right_layout.addWidget(self.pipeline_cloud_result)
        right_layout.addWidget(QLabel("自动引用到批量重命名的标题列表"))
        self.pipeline_titles = QPlainTextEdit(); self.pipeline_titles.setReadOnly(True); self.pipeline_titles.setMinimumHeight(170)
        right_layout.addWidget(self.pipeline_titles, 1)
        right_layout.addWidget(QLabel("运行日志"))
        self.pipeline_log = QPlainTextEdit(); self.pipeline_log.setReadOnly(True)
        right_layout.addWidget(self.pipeline_log, 2)
        upload_actions = QHBoxLayout()
        upload_files = QPushButton("选择成品文件上传"); upload_files.clicked.connect(self._manual_upload_files)
        upload_folder = QPushButton("选择成品目录上传"); upload_folder.clicked.connect(self._manual_upload_folder)
        self.pipeline_retry_upload = QPushButton("继续上传"); self.pipeline_retry_upload.setEnabled(False)
        self.pipeline_retry_upload.clicked.connect(self._retry_cloud_upload)
        self.pipeline_continue_sheet = QPushButton("继续填表"); self.pipeline_continue_sheet.setEnabled(False)
        self.pipeline_continue_sheet.clicked.connect(self._continue_sheet_write)
        self.pipeline_stop_upload = QPushButton("停止上传"); self.pipeline_stop_upload.setEnabled(False)
        self.pipeline_stop_upload.clicked.connect(self._stop_cloud_upload)
        upload_actions.addWidget(upload_files); upload_actions.addWidget(upload_folder)
        upload_actions.addWidget(self.pipeline_retry_upload); upload_actions.addWidget(self.pipeline_continue_sheet); upload_actions.addWidget(self.pipeline_stop_upload)
        upload_actions.addStretch(); right_layout.addLayout(upload_actions)
        handoff = QHBoxLayout(); handoff.addStretch()
        to_subtitle = QPushButton("查看全部字幕"); to_subtitle.clicked.connect(lambda: self._show_page(5))
        to_rename = QPushButton("到批量重命名继续调整"); to_rename.clicked.connect(lambda: self._show_page(4))
        handoff.addWidget(to_subtitle); handoff.addWidget(to_rename); right_layout.addLayout(handoff)
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True); left_scroll.setWidget(left)
        split.addWidget(left_scroll); split.addWidget(right); split.setSizes([620, 850])
        layout.addWidget(split, 1)
        self._refresh_pipeline_profiles()
        QTimer.singleShot(0,self._restore_pending_sheet_checkpoint)
        return page

    def _restore_pending_sheet_checkpoint(self):
        try:
            root=Path(self.pipeline_output.text())
            checkpoints=sorted(root.rglob("pipeline_checkpoint.json"),key=lambda path:path.stat().st_mtime,reverse=True) if root.is_dir() else []
            for checkpoint in checkpoints:
                state=read_json_file(checkpoint,{})
                uploads=state.get("pending_sheet_uploads",[]); folder_url=state.get("cloud_url","")
                if state.get("status")=="sheet_pending" and uploads and folder_url:
                    self.pending_sheet_uploads=list(uploads); self.pending_sheet_folder_url=folder_url; self.pipeline_continue_sheet.setEnabled(True)
                    self.pipeline_cloud_result.setStyleSheet("color:#fbbf24;padding:4px;")
                    self.pipeline_cloud_result.setText("检测到上次视频已上传但表格未完成，可直接点击“继续填表”。")
                    break
        except Exception:
            pass

    def _keys_page(self):
        page, layout = self._page_shell("API 密钥管理", "每个服务可添加多枚密钥；调用时轮询，失效或额度受限会自动切换。")
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setMaximumHeight(250)
        key_container = QWidget(); key_grid = QGridLayout(key_container)
        key_grid.setContentsMargins(0, 0, 0, 0); key_grid.setSpacing(8)
        self.provider_inputs = {}
        provider_notes = {
            "Groq": "高速 Whisper 转写",
            "Gemini": "长音频理解与字幕",
            "ElevenLabs": "Scribe 高精度识别",
            "Gladia": "字幕与说话人识别",
        }
        for index, provider in enumerate(PROVIDERS):
            group = QGroupBox(f"{provider} · {provider_notes[provider]}")
            group.setCheckable(True); group.setChecked(True)
            group_layout = QVBoxLayout(group); group_layout.setContentsMargins(10, 8, 10, 8); group_layout.setSpacing(5)
            edit = QPlainTextEdit(); edit.setPlaceholderText("可一次粘贴多个密钥，每行一个")
            edit.setMaximumHeight(68); self.provider_inputs[provider] = edit
            add_btn = QPushButton(f"批量添加 {provider} 密钥")
            add_btn.clicked.connect(lambda checked=False, p=provider: self._add_keys_for_provider(p))
            group_layout.addWidget(edit); group_layout.addWidget(add_btn)
            group.toggled.connect(lambda checked, box=edit, button=add_btn: (box.setVisible(checked), button.setVisible(checked)))
            key_grid.addWidget(group, index // 2, index % 2)
        scroll.setWidget(key_container); layout.addWidget(scroll)
        panel = QFrame(); panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel); panel_layout.setContentsMargins(10, 10, 10, 10)
        self.key_table = QTableWidget(0, 7)
        self.key_table.setHorizontalHeaderLabels(["服务", "密钥", "状态", "上次检测", "使用次数", "异常原因", "ID"])
        header = self.key_table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.key_table.setColumnHidden(6, True)
        self.key_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.key_table.cellDoubleClicked.connect(lambda row, column: self._show_key_error(row))
        panel_layout.addWidget(self.key_table)
        buttons = QHBoxLayout()
        check_selected = QPushButton("检测选中"); check_selected.clicked.connect(self._check_selected_keys)
        check_all = QPushButton("检测全部"); check_all.clicked.connect(self._check_all_keys)
        details = QPushButton("查看异常详情"); details.clicked.connect(self._show_selected_key_error)
        toggle = QPushButton("启用 / 停用"); toggle.clicked.connect(self._toggle_key)
        remove = QPushButton("删除选中"); remove.clicked.connect(self._remove_key)
        buttons.addWidget(check_selected); buttons.addWidget(check_all); buttons.addWidget(details); buttons.addWidget(toggle); buttons.addStretch(); buttons.addWidget(remove)
        panel_layout.addLayout(buttons)
        layout.addWidget(panel, 1)
        note = QLabel("安全提示：配置文件为本机明文保存，请勿共享该文件或整个用户配置目录。")
        note.setStyleSheet("color:#f59e0b;")
        layout.addWidget(note)
        return page

    def _show_page(self, index):
        self.pages.setCurrentIndex(index)
        for btn in self.nav_buttons:
            btn.setChecked(int(btn.property("pageIndex")) == index)

    def _launch_tool(self, relative):
        if relative.startswith("page:"):
            self._show_page(int(relative.split(":", 1)[1]))

    def _add_media(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择视频或音频", "",
            "媒体文件 (*.mp4 *.mov *.mkv *.avi *.wmv *.webm *.m4v *.mp3 *.wav *.m4a *.flac *.aac *.ogg);;所有文件 (*.*)")
        self._add_media_paths(files)

    def _add_media_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含媒体的文件夹")
        if folder:
            self._add_media_paths([folder])

    def _media_files_in_folder(self, folder: Path):
        found = []
        try:
            for root, directories, files in os.walk(folder):
                directories.sort(key=natural_path_key)
                for name in sorted(files, key=natural_path_key):
                    path = Path(root) / name
                    if path.suffix.lower() in MEDIA_EXTENSIONS:
                        found.append(str(path.resolve()))
        except (OSError, PermissionError) as exc:
            self.media_source_hint.setText(f"部分路径无法读取：{exc}")
        return found

    def _add_media_paths(self, paths):
        candidates = []
        folder_count = 0
        for raw_path in paths:
            path = Path(raw_path)
            if path.is_dir():
                folder_count += 1
                candidates.extend(self._media_files_in_folder(path))
            elif path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                candidates.append(str(path.resolve()))
        candidates.sort(key=natural_path_key)
        existing = {self.file_list.item(i).text() for i in range(self.file_list.count())}
        added = 0
        for path in candidates:
            if path not in existing:
                self.file_list.addItem(path); existing.add(path); added += 1
        if added:
            source = f"，来自 {folder_count} 个文件夹" if folder_count else ""
            self.media_source_hint.setText(f"新增 {added} 个{source}；共 {self.file_list.count()} 个")
        elif paths:
            self.media_source_hint.setText("没有发现新媒体（可能重复或格式不支持）")

    def _remove_selected_media(self):
        for index in self.file_list.selectedIndexes()[::-1]:
            self.file_list.takeItem(index.row())
        self.media_source_hint.setText(f"共 {self.file_list.count()} 个")

    def _choose_parent_folder(self):
        parent = QFileDialog.getExistingDirectory(self, "选择父目录")
        if not parent:
            return
        parent_path = Path(parent)
        try:
            children = sorted((path for path in parent_path.iterdir() if path.is_dir()),
                              key=lambda path: natural_path_key(path.name))
        except (OSError, PermissionError) as exc:
            QMessageBox.warning(self, "无法读取目录", str(exc)); return
        self.subfolder_combo.clear()
        self.subfolder_combo.addItem(f"[父目录本身] {parent_path.name}", str(parent_path))
        for child in children:
            self.subfolder_combo.addItem(child.name, str(child))
        self.subfolder_combo.setEnabled(True)
        self.media_source_hint.setText(f"已加载 {len(children)} 个子文件夹")

    def _add_selected_subfolder(self):
        folder = self.subfolder_combo.currentData()
        if folder:
            self._add_media_paths([folder])

    def _pipeline_choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择原始视频", "", "视频 (*.mp4 *.mov *.mkv *.avi *.wmv *.webm *.m4v *.flv *.ts)")
        self._pipeline_add_paths(files)

    def _pipeline_choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择原始视频文件夹")
        if folder: self._pipeline_add_paths([folder])

    def _pipeline_add_paths(self, paths):
        video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".ts"}
        candidates = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                candidates.extend(str(item.resolve()) for item in path.rglob("*")
                                  if item.is_file() and item.suffix.lower() in video_extensions)
            elif path.is_file() and path.suffix.lower() in video_extensions:
                candidates.append(str(path.resolve()))
        candidates.sort(key=natural_path_key)
        existing = {self.pipeline_files.item(i).text() for i in range(self.pipeline_files.count())}
        for path in candidates:
            if path not in existing: self.pipeline_files.addItem(path); existing.add(path)

    def _pipeline_choose_parent(self):
        folder = QFileDialog.getExistingDirectory(self, "选择父目录")
        if not folder: return
        parent = Path(folder)
        try:
            children = sorted((path for path in parent.iterdir() if path.is_dir()),
                              key=lambda path: natural_path_key(path.name))
        except OSError as exc:
            QMessageBox.warning(self, "无法读取目录", str(exc)); return
        self.pipeline_subfolders.clear(); self.pipeline_subfolders.addItem(f"[父目录本身] {parent.name}", str(parent))
        for child in children: self.pipeline_subfolders.addItem(child.name, str(child))
        self.pipeline_subfolders.setEnabled(True)

    def _pipeline_add_selected_folder(self):
        folder = self.pipeline_subfolders.currentData()
        if folder: self._pipeline_add_paths([folder])

    def _pipeline_choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择流水线输出目录", self.pipeline_output.text())
        if folder: self.pipeline_output.setText(folder)

    def _pipeline_cloud_toggled(self, checked):
        self.store.data["google_sync"]["enabled"] = bool(checked)
        self.store.save()
        self.pipeline_cloud_result.setText("云端同步：已开启" if checked else "云端同步：已关闭")

    def _save_pipeline_sync_profile(self):
        current_name=self.pipeline_sync_profile.currentData()
        if current_name:
            name=current_name
        else:
            name,ok=QInputDialog.getText(self,"保存同步方案","方案名称：",text="方案1")
            if not ok or not name.strip(): return
            name=name.strip()
        config=self._selected_sync_config(); config["enabled"]=self.pipeline_cloud_check.isChecked()
        config.pop("sync_profiles",None); config.pop("active_sync_profile",None)
        root=self.store.data.setdefault("google_sync",{}); profiles=dict(root.get("sync_profiles",{})); profiles[name]=config
        root["sync_profiles"]=profiles; root["active_sync_profile"]=name; self.store.save()
        if hasattr(self,"google_settings_page"): self.google_settings_page.load_current()
        self._refresh_pipeline_profiles(); index=self.pipeline_sync_profile.findData(name)
        if index>=0: self.pipeline_sync_profile.setCurrentIndex(index)
        QMessageBox.information(self,"方案已保存",f"当前写入 Sheet 和本次选择已同步保存到方案“{name}”。")

    def _open_google_settings(self):
        self._show_page(7)
        self.settings_page.setCurrentWidget(self.google_settings_page)

    def _refresh_pipeline_profiles(self):
        if not hasattr(self, "pipeline_sync_profile"): return
        config = self.store.data.get("google_sync", {}); profiles = config.get("sync_profiles", {})
        current = self.pipeline_sync_profile.currentText() or config.get("active_sync_profile", "")
        self.pipeline_sync_profile.blockSignals(True); self.pipeline_sync_profile.clear()
        self.pipeline_sync_profile.addItem("使用当前设置", "")
        for name in profiles: self.pipeline_sync_profile.addItem(name, name)
        index = self.pipeline_sync_profile.findData(current)
        if index < 0: index = self.pipeline_sync_profile.findData(config.get("active_sync_profile", ""))
        self.pipeline_sync_profile.setCurrentIndex(max(0, index)); self.pipeline_sync_profile.blockSignals(False)
        self._pipeline_profile_changed(self.pipeline_sync_profile.currentText())

    def _selected_sync_config(self):
        base = dict(self.store.data.get("google_sync", {})); name = self.pipeline_sync_profile.currentData() if hasattr(self, "pipeline_sync_profile") else ""
        profile = base.get("sync_profiles", {}).get(name)
        if profile:
            preserved_profiles = base.get("sync_profiles", {}); base.update(dict(profile)); base["sync_profiles"] = preserved_profiles; base["active_sync_profile"] = name
        profile_key=name or "__current__"
        if getattr(self,"_pipeline_runtime_profile",None)==profile_key:
            if getattr(self,"pipeline_runtime_sheet",""): base["sheet_name"]=self.pipeline_runtime_sheet
            fields=[]
            for item in base.get("variable_fields",[]):
                updated=dict(item); updated["selected"]=self.pipeline_runtime_values.get(item.get("field",""),item.get("selected","")); fields.append(updated)
            base["variable_fields"]=fields
        return base

    def _pipeline_profile_changed(self, _text):
        if not hasattr(self, "pipeline_profile_hint"): return
        name=self.pipeline_sync_profile.currentData(); profile_key=name or "__current__"
        base=dict(self.store.data.get("google_sync",{})); profile_config=base.get("sync_profiles",{}).get(name)
        if profile_config: base.update(dict(profile_config))
        self._pipeline_runtime_profile=profile_key
        self.pipeline_runtime_sheet=base.get("sheet_name","")
        self.pipeline_runtime_values={item.get("field",""):item.get("selected","") for item in base.get("variable_fields",[])}
        while self.pipeline_variable_form.count():
            item=self.pipeline_variable_form.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.pipeline_target_sheet=NoWheelComboBox(); self.pipeline_target_sheet.setEditable(True); self.pipeline_target_sheet.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        sheet_names=[str(value) for value in base.get("available_sheet_names",[]) if str(value).strip()]
        current_sheet=base.get("sheet_name","")
        if current_sheet and current_sheet not in sheet_names: sheet_names.insert(0,current_sheet)
        self.pipeline_target_sheet.addItems(sheet_names); self.pipeline_target_sheet.setCurrentText(current_sheet)
        self.pipeline_target_sheet.lineEdit().setPlaceholderText("选择或输入写入 Sheet 名称")
        self.pipeline_target_sheet.currentTextChanged.connect(self._pipeline_sheet_changed)
        self.pipeline_variable_form.addRow("写入 Sheet",self.pipeline_target_sheet)
        for item in base.get("variable_fields",[]):
            field=item.get("field","选择项"); options=[str(v) for v in item.get("options",[]) if str(v).strip()]
            combo=NoWheelComboBox(); combo.setEditable(False); combo.addItem("请选择…",""); combo.addItems(options)
            selected=item.get("selected",""); index=combo.findText(selected); combo.setCurrentIndex(index if index>=0 else 0)
            combo.currentTextChanged.connect(lambda value,f=field:self._pipeline_variable_changed(f,value))
            combo.setEnabled(bool(options)); combo.setToolTip("选项来自 Google 配置 Sheet" if options else "请先在设置与组件中从配置 Sheet 刷新选项")
            self.pipeline_variable_form.addRow(f"{field}（{item.get('column','')}列）",combo)
        self.pipeline_variable_group.setVisible(bool(base.get("write_sheet") or base.get("variable_fields",[])))
        self._update_pipeline_profile_hint()

    def _pipeline_variable_changed(self, field, value):
        self.pipeline_runtime_values[field]="" if value=="请选择…" else value
        self._update_pipeline_profile_hint()

    def _pipeline_sheet_changed(self, value):
        self.pipeline_runtime_sheet=value.strip()
        self._update_pipeline_profile_hint()

    def _update_pipeline_profile_hint(self):
        config = self._selected_sync_config(); profile = self.pipeline_sync_profile.currentData() or "当前设置"
        sheet = config.get("sheet_name", "") or "未填写 Sheet"
        table_id = extract_google_id(config.get("spreadsheet_id", "")) or "未填写表格"
        selected = [f"{item.get('field')}={item.get('selected')}" for item in config.get("variable_fields", []) if item.get("selected")]
        extra = "；" + "，".join(selected) if selected else ""
        self.pipeline_profile_hint.setText(f"{profile} → 表格 {table_id} / Sheet：{sheet}{extra}")

    def _open_google_sync_dialog(self):
        config = dict(self.store.data["google_sync"])
        dialog = QDialog(self); dialog.setWindowTitle("Google 云端同步配置"); dialog.resize(680, 760)
        root = QVBoxLayout(dialog)
        note = QLabel("使用服务账号 JSON。请先把 Drive 父文件夹和 Google 表格共享给 JSON 中的 client_email。\n"
                      "流水线只上传“03_重命名成品”中的最终视频，中间片段和字幕不会上传。")
        note.setWordWrap(True); note.setStyleSheet("color:#7dd3fc;"); root.addWidget(note)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); container = QWidget(); form = QFormLayout(container)
        json_edit = QLineEdit(config.get("json_path", "")); json_row = QHBoxLayout(); json_row.addWidget(json_edit)
        browse_json = QPushButton("选择 JSON…")
        browse_json.clicked.connect(lambda: json_edit.setText(QFileDialog.getOpenFileName(
            dialog, "选择 Google 服务账号 JSON", "", "JSON (*.json)")[0] or json_edit.text()))
        json_row.addWidget(browse_json); json_widget = QWidget(); json_widget.setLayout(json_row)
        form.addRow("服务账号 JSON", json_widget)
        parent_edit = QLineEdit(config.get("parent_folder", "")); parent_edit.setPlaceholderText("Drive 父文件夹 ID 或链接")
        form.addRow("云端父文件夹", parent_edit)
        auth_row = QHBoxLayout(); auth_status = QLabel("尚未检查授权"); auth_status.setWordWrap(True)
        authorize = QPushButton("授权 / 检查权限"); auth_row.addWidget(auth_status, 1); auth_row.addWidget(authorize)
        auth_widget = QWidget(); auth_widget.setLayout(auth_row); form.addRow("Google 权限", auth_widget)
        def authorize_google():
            temporary = dict(config); temporary.update({"json_path": json_edit.text().strip(),
                                                         "parent_folder": parent_edit.text().strip()})
            authorize.setEnabled(False); auth_status.setText("正在授权并检查权限…")
            QApplication.processEvents()
            try:
                identity = test_google_authorization(temporary, interactive=True)
                auth_status.setText(f"授权成功：{identity}"); auth_status.setStyleSheet("color:#86efac;")
            except Exception as exc:
                auth_status.setText(f"授权失败：{exc}"); auth_status.setStyleSheet("color:#fca5a5;")
                QMessageBox.warning(dialog, "Google 授权失败", str(exc))
            finally: authorize.setEnabled(True)
        authorize.clicked.connect(authorize_google)
        mode_combo = QComboBox(); mode_combo.addItems(["视频名称", "自定义名称"])
        mode_combo.setCurrentText(config.get("folder_mode", "视频名称")); form.addRow("任务文件夹命名", mode_combo)
        custom_name = QLineEdit(config.get("custom_folder_name", "")); custom_name.setPlaceholderText("选择自定义名称时使用")
        form.addRow("自定义名称", custom_name)
        public_check = QCheckBox("允许知道链接的用户查看云端任务文件夹")
        public_check.setChecked(config.get("public_link", False)); form.addRow("共享权限", public_check)
        sheet_check = QCheckBox("上传完成后写入 Google Sheets")
        sheet_check.setChecked(config.get("write_sheet", False)); form.addRow("表格同步", sheet_check)
        profiles = {name: dict(value) for name, value in config.get("sheet_profiles", {}).items()}
        profile_row = QHBoxLayout(); profile_combo = QComboBox(); profile_combo.addItem("选择已保存表格方案…")
        profile_combo.addItems(profiles.keys())
        save_profile = QPushButton("保存当前方案"); delete_profile = QPushButton("删除方案")
        profile_row.addWidget(profile_combo, 1); profile_row.addWidget(save_profile); profile_row.addWidget(delete_profile)
        profile_widget = QWidget(); profile_widget.setLayout(profile_row); form.addRow("表格方案", profile_widget)
        spreadsheet = QLineEdit(config.get("spreadsheet_id", "")); spreadsheet.setPlaceholderText("表格 ID 或完整链接")
        sheet_name = QLineEdit(config.get("sheet_name", "")); sheet_name.setPlaceholderText("例如：AS-批量视频版权表")
        insert_row = QSpinBox(); insert_row.setRange(1, 100000); insert_row.setValue(int(config.get("insert_row", 4)))
        form.addRow("表格 ID", spreadsheet); form.addRow("Sheet 名称", sheet_name); form.addRow("数据插入行", insert_row)

        variable_fields = [dict(item) for item in config.get("variable_fields", [])]
        variable_group = QGroupBox("本次上传选择（每次上传可重新选择）")
        variable_layout = QVBoxLayout(variable_group); variable_rows = QFormLayout(); variable_layout.addLayout(variable_rows)
        variable_combos = []
        def clear_form_layout(layout_to_clear):
            while layout_to_clear.rowCount(): layout_to_clear.removeRow(0)
        def read_variable_fields():
            result = []
            for index, item in enumerate(variable_fields):
                updated_item = dict(item)
                if index < len(variable_combos): updated_item["selected"] = variable_combos[index].currentText()
                result.append(updated_item)
            return result
        def rebuild_variable_rows():
            clear_form_layout(variable_rows); variable_combos.clear()
            for item in variable_fields:
                combo = QComboBox(); options = [str(value) for value in item.get("options", []) if str(value).strip()]
                combo.addItems(options); combo.setEditable(True)
                combo.setCurrentText(str(item.get("selected", options[0] if options else "")))
                variable_combos.append(combo)
                variable_rows.addRow(f"{item.get('field', '选择项')}（{item.get('column', '')}列）", combo)
            if not variable_fields:
                variable_rows.addRow(QLabel("尚未配置非固定字段；点击右侧按钮添加。"))
        configure_variables = QPushButton("配置下拉字段和选项")
        variable_layout.addWidget(configure_variables, 0, Qt.AlignmentFlag.AlignRight)
        form.addRow(variable_group)
        def configure_variable_fields():
            nonlocal variable_fields
            editor = QDialog(dialog); editor.setWindowTitle("配置每次上传需要选择的字段"); editor.resize(650, 460)
            editor_layout = QVBoxLayout(editor)
            hint = QLabel("这些字段不会固定在表格方案中；每次上传前从下拉框选择。选项用 | 分隔。")
            hint.setWordWrap(True); editor_layout.addWidget(hint)
            table = QTableWidget(0, 3); table.setHorizontalHeaderLabels(["字段名称", "写入列", "下拉选项（用 | 分隔）"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            for item in read_variable_fields():
                row = table.rowCount(); table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(str(item.get("field", "选择项"))))
                table.setItem(row, 1, QTableWidgetItem(str(item.get("column", ""))))
                table.setItem(row, 2, QTableWidgetItem(" | ".join(item.get("options", []))))
            editor_layout.addWidget(table, 1)
            edit_buttons = QHBoxLayout(); add_row = QPushButton("新增字段"); remove_row = QPushButton("删除选中")
            add_row.clicked.connect(lambda: (table.insertRow(table.rowCount()),
                                              table.setItem(table.rowCount()-1, 0, QTableWidgetItem("选择项")),
                                              table.setItem(table.rowCount()-1, 1, QTableWidgetItem("")),
                                              table.setItem(table.rowCount()-1, 2, QTableWidgetItem(""))))
            def remove_rows():
                for row in sorted({index.row() for index in table.selectedIndexes()}, reverse=True): table.removeRow(row)
            remove_row.clicked.connect(remove_rows); edit_buttons.addWidget(add_row); edit_buttons.addWidget(remove_row); edit_buttons.addStretch()
            editor_layout.addLayout(edit_buttons)
            editor_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            editor_buttons.accepted.connect(editor.accept); editor_buttons.rejected.connect(editor.reject)
            editor_layout.addWidget(editor_buttons)
            if editor.exec() != QDialog.DialogCode.Accepted: return
            updated_fields = []
            for row in range(table.rowCount()):
                field = table.item(row, 0).text().strip() if table.item(row, 0) else ""
                column = table.item(row, 1).text().strip().upper() if table.item(row, 1) else ""
                options_text = table.item(row, 2).text() if table.item(row, 2) else ""
                options = [value.strip() for value in options_text.split("|") if value.strip()]
                if field and column: updated_fields.append({"field": field, "column": column,
                                                             "options": options, "selected": options[0] if options else ""})
            variable_fields = updated_fields; rebuild_variable_rows()
        configure_variables.clicked.connect(configure_variable_fields); rebuild_variable_rows()

        columns_group = QGroupBox("字段与列映射（名称、列、填写内容合并配置）")
        columns_layout = QVBoxLayout(columns_group)
        mapping_table = QTableWidget(0, 3)
        mapping_table.setHorizontalHeaderLabels(["字段名称", "写入列", "固定内容 / 自动来源"])
        mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        mapping_table.setMinimumHeight(330); mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        source_labels = {"date": "自动：当天日期", "file": "自动：文件名与云端链接",
                         "chinese": "自动：中文字幕", "original": "自动：识别原文/葡语",
                         "folder": "自动：云端任务文件夹链接"}
        def load_mapping_table(mappings):
            mapping_table.setRowCount(0)
            for mapping in mappings:
                row = mapping_table.rowCount(); mapping_table.insertRow(row)
                field_item = QTableWidgetItem(str(mapping.get("field", "自定义字段")))
                source = mapping.get("source", "static"); field_item.setData(Qt.ItemDataRole.UserRole, source)
                column_item = QTableWidgetItem(str(mapping.get("column", "")))
                value_item = QTableWidgetItem(source_labels.get(source, str(mapping.get("value", ""))))
                if source != "static":
                    value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    value_item.setForeground(QColor("#7dd3fc"))
                mapping_table.setItem(row, 0, field_item); mapping_table.setItem(row, 1, column_item)
                mapping_table.setItem(row, 2, value_item)
        def read_mapping_table():
            mappings = []
            for row in range(mapping_table.rowCount()):
                field_item = mapping_table.item(row, 0); column_item = mapping_table.item(row, 1)
                value_item = mapping_table.item(row, 2); source = field_item.data(Qt.ItemDataRole.UserRole) or "static"
                column = column_item.text().strip().upper() if column_item else ""
                if not column: continue
                mappings.append({"field": field_item.text().strip() or "自定义字段", "column": column,
                                 "source": source, "value": value_item.text() if source == "static" and value_item else ""})
            return mappings
        load_mapping_table(config.get("sheet_mappings", DEFAULT_SHEET_MAPPINGS))
        mapping_buttons = QHBoxLayout()
        add_mapping = QPushButton("新增固定字段"); delete_mapping = QPushButton("删除选中字段")
        reset_mapping = QPushButton("恢复默认映射")
        def add_mapping_row():
            row = mapping_table.rowCount(); mapping_table.insertRow(row)
            field = QTableWidgetItem("自定义字段"); field.setData(Qt.ItemDataRole.UserRole, "static")
            mapping_table.setItem(row, 0, field); mapping_table.setItem(row, 1, QTableWidgetItem(""))
            mapping_table.setItem(row, 2, QTableWidgetItem("")); mapping_table.setCurrentCell(row, 0)
        def delete_mapping_rows():
            for row in sorted({index.row() for index in mapping_table.selectedIndexes()}, reverse=True):
                mapping_table.removeRow(row)
        add_mapping.clicked.connect(add_mapping_row); delete_mapping.clicked.connect(delete_mapping_rows)
        reset_mapping.clicked.connect(lambda: load_mapping_table(DEFAULT_SHEET_MAPPINGS))
        mapping_buttons.addWidget(add_mapping); mapping_buttons.addWidget(delete_mapping); mapping_buttons.addStretch()
        mapping_buttons.addWidget(reset_mapping); columns_layout.addWidget(mapping_table); columns_layout.addLayout(mapping_buttons)
        form.addRow(columns_group)

        def current_sheet_profile():
            return {"spreadsheet_id": spreadsheet.text().strip(), "sheet_name": sheet_name.text().strip(),
                    "insert_row": insert_row.value(), "sheet_mappings": read_mapping_table(),
                    "variable_fields": read_variable_fields()}
        def apply_sheet_profile(name):
            nonlocal variable_fields
            profile = profiles.get(name)
            if not profile: return
            spreadsheet.setText(profile.get("spreadsheet_id", "")); sheet_name.setText(profile.get("sheet_name", ""))
            insert_row.setValue(int(profile.get("insert_row", 4)))
            load_mapping_table(profile.get("sheet_mappings", DEFAULT_SHEET_MAPPINGS))
            variable_fields = [dict(item) for item in profile.get("variable_fields", [])]
            rebuild_variable_rows()
        def save_current_profile():
            default_name = sheet_name.text().strip() or "表格方案"
            name, ok = QInputDialog.getText(dialog, "保存表格方案", "方案名称：", text=default_name)
            if not ok: return
            name = name.strip()
            if not name:
                QMessageBox.information(dialog, "无法保存", "请输入方案名称。")
                return
            try:
                profiles[name] = current_sheet_profile()
                # “保存当前方案”应立即持久化，不要求用户再点击弹窗底部的 Save。
                google_config = self.store.data.setdefault("google_sync", {})
                google_config["sheet_profiles"] = {key: dict(value) for key, value in profiles.items()}
                google_config["active_sheet_profile"] = name
                self.store.save()
                if profile_combo.findText(name) < 0: profile_combo.addItem(name)
                profile_combo.setCurrentText(name)
                QMessageBox.information(dialog, "保存成功", f"表格方案“{name}”已保存。")
            except Exception as exc:
                QMessageBox.critical(dialog, "保存方案失败", f"无法写入配置：\n{exc}")
        def delete_current_profile():
            name = profile_combo.currentText()
            if name in profiles:
                try:
                    del profiles[name]
                    google_config = self.store.data.setdefault("google_sync", {})
                    google_config["sheet_profiles"] = {key: dict(value) for key, value in profiles.items()}
                    if google_config.get("active_sheet_profile") == name:
                        google_config["active_sheet_profile"] = ""
                    self.store.save()
                    profile_combo.removeItem(profile_combo.currentIndex())
                    QMessageBox.information(dialog, "删除成功", f"表格方案“{name}”已删除。")
                except Exception as exc:
                    QMessageBox.critical(dialog, "删除方案失败", f"无法写入配置：\n{exc}")
        profile_combo.currentTextChanged.connect(apply_sheet_profile)
        save_profile.clicked.connect(save_current_profile); delete_profile.clicked.connect(delete_current_profile)
        active_profile = config.get("active_sheet_profile", "")
        if active_profile in profiles: profile_combo.setCurrentText(active_profile)
        scroll.setWidget(container); root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); root.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return False
        updated = {
            "enabled": self.pipeline_cloud_check.isChecked(), "json_path": json_edit.text().strip(),
            "parent_folder": parent_edit.text().strip(), "folder_mode": mode_combo.currentText(),
            "custom_folder_name": custom_name.text().strip(), "public_link": public_check.isChecked(),
            "write_sheet": sheet_check.isChecked(), "spreadsheet_id": spreadsheet.text().strip(),
            "sheet_name": sheet_name.text().strip(), "insert_row": insert_row.value(),
            "sheet_mappings": read_mapping_table(), "sheet_profiles": profiles,
            "variable_fields": read_variable_fields(),
            "active_sheet_profile": profile_combo.currentText() if profile_combo.currentText() in profiles else "",
            "mapping_ui_version": 2,
        }
        self.store.data["google_sync"] = updated; self.store.save()
        return True

    def _pipeline_start(self):
        sources = [self.pipeline_files.item(i).text() for i in range(self.pipeline_files.count())]
        if not sources:
            QMessageBox.information(self, "没有视频", "请先添加 Canva、HeyGen 或其他来源的视频。")
            return
        if self.thread:
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前任务结束。")
                    return
            except RuntimeError:
                self.thread = None
        selected = self.pipeline_provider.currentText()
        provider = self._resolve_provider() if selected == AUTO_PROVIDER else selected
        if provider != LOCAL_PROVIDER and not self.store.has_candidates(provider):
            QMessageBox.information(self, "缺少密钥", f"{provider} 没有可用密钥，请先添加并检测。")
            self._show_page(6); return
        try: ffmpeg = self._find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self, "缺少组件", str(exc)); return
        cloud_config = self._selected_sync_config()
        cloud_config["enabled"] = self.pipeline_cloud_check.isChecked()
        if cloud_config["enabled"]:
            if not Path(cloud_config.get("json_path", "")).is_file() or not extract_google_id(cloud_config.get("parent_folder", "")):
                QMessageBox.warning(self, "Google 同步配置不完整",
                                    "请配置有效的服务账号 JSON 和 Drive 父文件夹 ID/链接。")
                self._open_google_settings(); return
            if cloud_config.get("write_sheet") and (not extract_google_id(cloud_config.get("spreadsheet_id", ""))
                                                     or not cloud_config.get("sheet_name", "").strip()):
                QMessageBox.warning(self, "表格配置不完整", "请填写 Google 表格 ID 和 Sheet 名称。")
                self._open_google_settings(); return
        model = self.store.data["models"].get(provider, DEFAULT_MODELS[provider])
        self.subtitle_results.clear(); self.result_combo.clear(); self.result_combo.addItem(ALL_RESULTS_LABEL)
        self.pipeline_titles.clear(); self.pipeline_log.clear(); self.pipeline_progress.setValue(0)
        self.thread = QThread(self)
        self.worker = PipelineWorker(
            self.store, sources, self.pipeline_output.text(), self.pipeline_threshold.value(),
            provider, model, self.pipeline_language.text(), ffmpeg,
            self.pipeline_prefix.text(), self.pipeline_date.text(), self.pipeline_suffix.text(),
            self.pipeline_start.value(), self.pipeline_padding.value(), cloud_config,
            self.pipeline_resume_check.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.pipeline_log.appendPlainText)
        self.worker.progress.connect(self.pipeline_progress.setValue)
        self.worker.result_ready.connect(self._subtitle_result_ready)
        self.worker.titles_ready.connect(self._pipeline_titles_ready)
        self.worker.cloud_ready.connect(self._pipeline_cloud_ready)
        self.worker.cloud_failed.connect(self._pipeline_cloud_failed)
        self.worker.cloud_sheet_pending.connect(self._pipeline_sheet_pending)
        self.worker.finished.connect(self._pipeline_done); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_ended); self.thread.finished.connect(self.thread.deleteLater)
        self.pipeline_start_btn.setEnabled(False); self.pipeline_stop.setEnabled(True); self.thread.start()

    def _pipeline_cancel(self):
        if self.worker and hasattr(self.worker, "cancel"): self.worker.cancel()

    def _pipeline_titles_ready(self, clips_dir, titles):
        self.pipeline_titles.setPlainText("\n".join(titles))
        self.rename_page.input.setText(clips_dir)
        self.rename_page.output.setText(str(Path(clips_dir).parent))
        self.rename_page.task_name.setText("04_手动调整成品")
        self.rename_page.titles.setPlainText("\n".join(titles))
        self.rename_page.update_preview()

    def _pipeline_cloud_ready(self, folder_url, summary):
        self.pending_upload_files = []; self.pipeline_retry_upload.setEnabled(False)
        self.pending_sheet_uploads=[]; self.pending_sheet_folder_url=""; self.pipeline_continue_sheet.setEnabled(False)
        self.pipeline_cloud_result.setText(
            f'云端同步完成：{summary}<br><a href="{folder_url}">打开 Google Drive 文件夹</a>')

    def _pipeline_sheet_pending(self, folder_url, uploaded, error):
        self.pending_upload_files=[]; self.pipeline_retry_upload.setEnabled(False)
        self.pending_sheet_uploads=list(uploaded); self.pending_sheet_folder_url=folder_url
        self.pipeline_continue_sheet.setEnabled(bool(self.pending_sheet_uploads))
        self.pipeline_cloud_result.setStyleSheet("color:#fbbf24;padding:4px;")
        self.pipeline_cloud_result.setText(
            f'视频已上传成功，但写入表格失败：{error}<br><a href="{folder_url}">打开 Google Drive 文件夹</a><br>修正配置后点击“继续填表”，不会重新上传视频。')

    def _pipeline_cloud_failed(self, final_dir, error):
        self.pending_sheet_uploads=[]; self.pending_sheet_folder_url=""; self.pipeline_continue_sheet.setEnabled(False)
        video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".ts"}
        self.pending_upload_files = [str(path) for path in sorted(Path(final_dir).iterdir(),
                                      key=lambda path: natural_path_key(path.name))
                                     if path.is_file() and path.suffix.lower() in video_extensions]
        self.pipeline_retry_upload.setEnabled(bool(self.pending_upload_files))
        self.pipeline_cloud_result.setText(f"云端同步失败，但本地视频已处理完成：{error}<br>可点击“继续上传”。")
        self.pipeline_cloud_result.setStyleSheet("color:#fca5a5;padding:4px;")

    def _manual_upload_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择需要上传的重命名成品", "",
                                                 "视频 (*.mp4 *.mov *.mkv *.avi *.wmv *.webm *.m4v *.flv *.ts)")
        if files: self._start_cloud_upload(files)

    def _manual_upload_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择重命名成品目录")
        if not folder: return
        selected_folder = Path(folder)
        if selected_folder.name != "03_重命名成品":
            product_folders = sorted((path for path in selected_folder.rglob("03_重命名成品") if path.is_dir()),
                                     key=lambda path: path.stat().st_mtime, reverse=True)
            if product_folders:
                selected_folder = product_folders[0]
                self.pipeline_log.appendPlainText(f"已自动限定为重命名成品目录：{selected_folder}")
        extensions = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".ts"}
        files = [str(path) for path in sorted(selected_folder.rglob("*"), key=lambda path: natural_path_key(path.name))
                 if path.is_file() and path.suffix.lower() in extensions]
        if not files: QMessageBox.information(self, "没有成品", "所选目录中没有找到视频文件。")
        else: self._start_cloud_upload(files)

    def _retry_cloud_upload(self):
        if self.pending_upload_files: self._start_cloud_upload(self.pending_upload_files)

    def _continue_sheet_write(self):
        if not self.pending_sheet_uploads or not self.pending_sheet_folder_url: return
        if self.cloud_thread:
            try:
                if self.cloud_thread.isRunning():
                    QMessageBox.information(self,"任务进行中","请等待当前云端任务结束。")
                    return
            except RuntimeError: self.cloud_thread=None
        config=self._selected_sync_config(); config["enabled"]=True; config["write_sheet"]=True
        if not extract_google_id(config.get("spreadsheet_id","")) or not config.get("sheet_name","").strip():
            QMessageBox.warning(self,"表格配置不完整","请选择写入 Sheet 并确认表格 ID。")
            return
        self.cloud_thread=QThread(self); self.cloud_worker=SheetFillWorker(config,list(self.pending_sheet_uploads),self.pending_sheet_folder_url)
        self.cloud_worker.moveToThread(self.cloud_thread); self.cloud_thread.started.connect(self.cloud_worker.run)
        self.cloud_worker.log.connect(self.pipeline_log.appendPlainText); self.cloud_worker.finished.connect(self._sheet_fill_done)
        self.cloud_worker.finished.connect(self.cloud_thread.quit); self.cloud_thread.finished.connect(self._cloud_thread_ended); self.cloud_thread.finished.connect(self.cloud_thread.deleteLater)
        self.pipeline_continue_sheet.setEnabled(False); self.pipeline_stop_upload.setEnabled(False)
        self.pipeline_cloud_result.setStyleSheet("color:#7dd3fc;padding:4px;"); self.pipeline_cloud_result.setText("正在继续填写 Google Sheets，不会重新上传视频…")
        self.cloud_thread.start()

    def _sheet_fill_done(self, ok, folder_url, message):
        if ok:
            self._mark_pending_sheet_complete(folder_url)
            self.pending_sheet_uploads=[]; self.pending_sheet_folder_url=""; self.pipeline_continue_sheet.setEnabled(False)
            self.pipeline_cloud_result.setStyleSheet("color:#86efac;padding:4px;")
            self.pipeline_cloud_result.setText(f'{message}<br><a href="{folder_url}">打开 Google Drive 文件夹</a>')
        else:
            self.pipeline_continue_sheet.setEnabled(bool(self.pending_sheet_uploads))
            self.pipeline_cloud_result.setStyleSheet("color:#fca5a5;padding:4px;")
            self.pipeline_cloud_result.setText(f"继续填表失败：{message}<br>修正配置后可以再次点击继续填表。")

    def _mark_pending_sheet_complete(self, folder_url):
        try:
            root=Path(self.pipeline_output.text())
            for checkpoint in root.rglob("pipeline_checkpoint.json") if root.is_dir() else []:
                state=read_json_file(checkpoint,{})
                if state.get("status")=="sheet_pending" and state.get("cloud_url")==folder_url:
                    state["status"]="completed"; state.pop("pending_sheet_uploads",None); state.pop("last_error",None); atomic_write_json(checkpoint,state)
        except Exception:
            pass

    def _start_cloud_upload(self, files):
        if self.cloud_thread:
            try:
                if self.cloud_thread.isRunning():
                    QMessageBox.information(self, "正在上传", "请等待当前上传结束，或点击停止上传。")
                    return
            except RuntimeError: self.cloud_thread = None
        config = self._selected_sync_config(); config["enabled"] = True
        if not Path(config.get("json_path", "")).is_file() or not extract_google_id(config.get("parent_folder", "")):
            QMessageBox.warning(self, "Google 配置不完整", "请先配置授权 JSON 和 Drive 父文件夹。")
            self._open_google_settings(); return
        results = list(self.subtitle_results.values())
        records = []
        for index, path in enumerate(files):
            result = results[index] if index < len(results) else {}
            records.append({"path": path, "original": result.get("original", ""),
                            "chinese": result.get("chinese", "")})
        self.pending_upload_files = list(files)
        self.cloud_thread = QThread(self); self.cloud_worker = CloudUploadWorker(config, files, records, files)
        self.cloud_worker.moveToThread(self.cloud_thread); self.cloud_thread.started.connect(self.cloud_worker.run)
        self.cloud_worker.log.connect(self.pipeline_log.appendPlainText)
        self.cloud_worker.sheet_pending.connect(self._pipeline_sheet_pending)
        self.cloud_worker.finished.connect(self._cloud_upload_done); self.cloud_worker.finished.connect(self.cloud_thread.quit)
        self.cloud_thread.finished.connect(self._cloud_thread_ended); self.cloud_thread.finished.connect(self.cloud_thread.deleteLater)
        self.pipeline_stop_upload.setEnabled(True); self.pipeline_retry_upload.setEnabled(False)
        self.pipeline_cloud_result.setStyleSheet("color:#7dd3fc;padding:4px;")
        self.pipeline_cloud_result.setText(f"正在上传 {len(files)} 个重命名成品…")
        self.cloud_thread.start()

    def _stop_cloud_upload(self):
        if self.cloud_worker: self.cloud_worker.cancel()

    def _cloud_upload_done(self, ok, folder_url, message):
        self.pipeline_stop_upload.setEnabled(False)
        if ok:
            self.pending_upload_files = []; self.pipeline_retry_upload.setEnabled(False)
            self._pipeline_cloud_ready(folder_url, message)
        elif self.pending_sheet_uploads:
            self.pipeline_retry_upload.setEnabled(False)
        else:
            self.pipeline_retry_upload.setEnabled(bool(self.pending_upload_files))
            self.pipeline_cloud_result.setStyleSheet("color:#fca5a5;padding:4px;")
            self.pipeline_cloud_result.setText(f"上传失败/已停止：{message}<br>可以修复授权后继续上传。")

    def _cloud_thread_ended(self):
        self.cloud_worker = None; self.cloud_thread = None

    def _pipeline_done(self, ok, message):
        self.pipeline_start_btn.setEnabled(True); self.pipeline_stop.setEnabled(False)
        self.pipeline_log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(
            self, "流水线完成" if ok else "流水线失败", message)

    def _choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择字幕输出目录", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _provider_changed(self, provider):
        automatic = provider == AUTO_PROVIDER
        self.model_edit.setReadOnly(automatic)
        if automatic:
            self.model_edit.setText("按优先级自动匹配")
            self.diarize_check.setEnabled(True)
        else:
            self.model_edit.setText(self.store.data["models"].get(provider, DEFAULT_MODELS[provider]))
            self.diarize_check.setEnabled(provider in ("ElevenLabs", "Gladia"))

    def _refresh_priority_label(self):
        if hasattr(self, "priority_label"):
            self.priority_label.setText("  ›  ".join(self.store.data["provider_priority"]))

    def _open_priority_dialog(self):
        dialog = QDialog(self); dialog.setWindowTitle("调整字幕服务优先级"); dialog.resize(470, 390)
        box = QVBoxLayout(dialog)
        note = QLabel("自动模式会从上到下查找可用服务；拖动项目，或用右侧按钮调整。")
        note.setWordWrap(True); box.addWidget(note)
        row = QHBoxLayout(); priority_list = QListWidget()
        priority_list.addItems(self.store.data["provider_priority"])
        priority_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        priority_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        moves = QVBoxLayout()
        up = QPushButton("上移"); down = QPushButton("下移")
        def move_item(delta):
            current = priority_list.currentRow()
            target = current + delta
            if current < 0 or target < 0 or target >= priority_list.count():
                return
            item = priority_list.takeItem(current); priority_list.insertItem(target, item); priority_list.setCurrentRow(target)
        up.clicked.connect(lambda: move_item(-1)); down.clicked.connect(lambda: move_item(1))
        moves.addWidget(up); moves.addWidget(down); moves.addStretch()
        row.addWidget(priority_list, 1); row.addLayout(moves); box.addLayout(row, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); box.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.store.data["provider_priority"] = [priority_list.item(i).text() for i in range(priority_list.count())]
            self.store.save(); self._refresh_priority_label()

    def _resolve_provider(self):
        for provider in self.store.data["provider_priority"]:
            if provider == LOCAL_PROVIDER:
                return provider
            keys = self.store.data["providers"].get(provider, [])
            if any(x.get("enabled", True) and x.get("status", "未检测") in ("未检测", "有效") for x in keys):
                return provider
        return LOCAL_PROVIDER

    def _caption_transcribe(self, media_path, selected_provider):
        """在动态文案工作线程中复用同一套识别、翻译和密钥轮询逻辑。"""
        provider = self._resolve_provider() if selected_provider == AUTO_PROVIDER else selected_provider
        if provider != LOCAL_PROVIDER and not self.store.has_candidates(provider):
            raise RuntimeError(f"{provider} 没有可用密钥，请先到“密钥管理”添加并检测。")
        model = self.store.data["models"].get(provider, DEFAULT_MODELS[provider])
        worker = TranscribeWorker(self.store, provider, model, [media_path], "", "auto", False,
                                  self._find_ffmpeg(), True)
        result = worker._process_one(media_path)
        raw = result.get("raw") or {}; words = raw.get("words") or (raw.get("response") or {}).get("words") or []
        timed_words = []
        for word in words:
            text = str(word.get("text") or word.get("word") or "").strip()
            if text and word.get("start") is not None:
                timed_words.append({"start": float(word.get("start", 0)),
                                    "end": float(word.get("end", word.get("start", 0) + .25)), "text": text})
        precise_srt = segments_to_srt(timed_words) if timed_words else result["srt"]
        return result["original"], result["chinese"], precise_srt

    def _text_to_speech(self, text, service, voice, destination):
        """生成配音；ElevenLabs 失败时自动轮换下一枚可用密钥。"""
        target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
        if service == "微软文字转语音":
            try:
                import edge_tts
            except ImportError as exc:
                raise RuntimeError("缺少微软语音组件 edge-tts，请到“设置与组件”点击一键安装。") from exc
            clean_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", str(text)).strip()
            if not clean_text:
                raise RuntimeError("文案为空，无法生成语音。")

            selected_voice = voice or "zh-CN-XiaoxiaoNeural"
            locale = selected_voice[:5]
            voice_fallbacks = {
                "pt-PT": ["pt-PT-RaquelNeural", "pt-PT-DuarteNeural"],
                "pt-BR": ["pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"],
                "zh-CN": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
                "en-US": ["en-US-JennyNeural", "en-US-GuyNeural"],
            }
            voices = list(dict.fromkeys([selected_voice] + voice_fallbacks.get(locale, [])))

            # Edge 的免费接口在长段落或网络短暂波动时偶尔只返回元数据、不返回音频。
            # 按句拆成适中的请求，并对当前音色及同语种备用音色自动重试。
            pieces = []
            pending = ""
            for sentence in re.split(r"(?<=[。！？.!?；;：:\n])\s*", clean_text):
                sentence = sentence.strip()
                if not sentence:
                    continue
                if pending and len(pending) + len(sentence) + 1 > 1400:
                    pieces.append(pending); pending = sentence
                else:
                    pending = f"{pending} {sentence}".strip()
            if pending:
                pieces.append(pending)
            if not pieces:
                pieces = [clean_text]

            async def generate_part(part_text, part_path, part_voice):
                boundaries = []
                with part_path.open("wb") as audio_handle:
                    async for chunk in edge_tts.Communicate(part_text, part_voice).stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            audio_handle.write(chunk["data"])
                        elif chunk.get("type") == "WordBoundary":
                            start = float(chunk.get("offset", 0)) / 10_000_000
                            duration = float(chunk.get("duration", 0)) / 10_000_000
                            boundaries.append({"start": start, "end": start + max(.08, duration),
                                               "text": str(chunk.get("text", "")).strip()})
                return boundaries

            last_error = "服务没有返回音频"
            with tempfile.TemporaryDirectory(prefix="video_toolkit_tts_") as temp_name:
                temp_dir = Path(temp_name)
                for selected in voices:
                    for attempt in range(1, 3):
                        part_paths = []; all_boundaries = []; time_offset = 0.0
                        try:
                            for index, piece in enumerate(pieces):
                                part_path = temp_dir / f"part_{index:03d}.mp3"
                                if part_path.exists(): part_path.unlink()
                                boundaries = asyncio.run(generate_part(piece, part_path, selected))
                                if not part_path.exists() or part_path.stat().st_size < 256:
                                    raise RuntimeError(f"第 {index + 1} 段没有收到音频")
                                part_paths.append(part_path)
                                for entry in boundaries:
                                    all_boundaries.append({**entry,
                                                           "start": entry["start"] + time_offset,
                                                           "end": entry["end"] + time_offset})
                                if boundaries:
                                    time_offset += max(item["end"] for item in boundaries) + .08

                            if target.exists(): target.unlink()
                            if len(part_paths) == 1:
                                shutil.copyfile(part_paths[0], target)
                            else:
                                concat_file = temp_dir / "concat.txt"
                                concat_file.write_text("".join(
                                    f"file '{str(path).replace(chr(39), chr(39) + '\\\'' + chr(39))}'\n"
                                    for path in part_paths), encoding="utf-8")
                                result = subprocess.run(
                                    [self._find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                                     "-f", "concat", "-safe", "0", "-i", str(concat_file),
                                     "-c", "copy", str(target)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    **hidden_kwargs())
                                if result.returncode:
                                    raise RuntimeError(result.stderr.strip() or "分段音频合并失败")
                            if not target.exists() or target.stat().st_size < 256:
                                raise RuntimeError("合并后音频为空")
                            if all_boundaries:
                                target.with_suffix(".srt").write_text(
                                    segments_to_srt(all_boundaries), encoding="utf-8-sig")
                            return target
                        except Exception as exc:
                            last_error = f"{selected}（第 {attempt} 次）：{exc}"
                            for part_path in part_paths:
                                try: part_path.unlink()
                                except OSError: pass
            raise RuntimeError(
                "微软文字转语音连续重试后仍未收到音频。"
                f"\n最后错误：{last_error}"
                "\n请检查网络，或切换同语种音色；追求自然度可改用 ElevenLabs。")

        if service == "Gemini 自然语音":
            candidates = self.store.candidates("Gemini")
            if not candidates:
                raise RuntimeError("没有可用的 Gemini 密钥，请先到密钥管理添加并检测。")
            voice_name = (voice.split("｜", 1)[0].strip() if voice else "Kore") or "Kore"
            last_error = ""
            for item in candidates:
                try:
                    response = requests.post(
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        "gemini-2.5-flash-preview-tts:generateContent",
                        params={"key": item["key"]},
                        headers={"Content-Type": "application/json"},
                        json={
                            "contents": [{"parts": [{"text": str(text).strip()}]}],
                            "generationConfig": {
                                "responseModalities": ["AUDIO"],
                                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                                    "voiceName": voice_name}}},
                            },
                        }, timeout=240)
                    if response.status_code >= 400:
                        last_error = response_error(response)
                        self.store.mark_use("Gemini", item["id"],
                                            "失效" if response.status_code in (401, 403) else
                                            "额度受限" if response.status_code == 429 else "异常", last_error)
                        continue
                    payload = response.json()
                    parts = (((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
                    inline = next((part.get("inlineData") or part.get("inline_data")
                                   for part in parts if part.get("inlineData") or part.get("inline_data")), None)
                    if not inline or not inline.get("data"):
                        last_error = "Gemini 没有返回音频数据，请重试或更换音色。"
                        self.store.mark_use("Gemini", item["id"], "异常", last_error)
                        continue
                    audio = base64.b64decode(inline["data"])
                    mime = str(inline.get("mimeType") or inline.get("mime_type") or "audio/L16;rate=24000").lower()
                    with tempfile.TemporaryDirectory(prefix="video_toolkit_gemini_tts_") as temp_name:
                        temp_dir = Path(temp_name)
                        if "wav" in mime:
                            source = temp_dir / "voice.wav"; source.write_bytes(audio)
                        else:
                            rate_match = re.search(r"rate=(\d+)", mime)
                            rate = int(rate_match.group(1)) if rate_match else 24000
                            source = temp_dir / "voice.wav"
                            with wave.open(str(source), "wb") as wav_file:
                                wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(rate)
                                wav_file.writeframes(audio)
                        result = subprocess.run(
                            [self._find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                             "-i", str(source), "-c:a", "libmp3lame", "-b:a", "192k", str(target)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **hidden_kwargs())
                        if result.returncode or not target.exists() or target.stat().st_size < 256:
                            last_error = result.stderr.strip() or "Gemini 音频转换失败"
                            self.store.mark_use("Gemini", item["id"], "异常", last_error)
                            continue
                    self.store.mark_use("Gemini", item["id"], "有效", "")
                    return target
                except (requests.RequestException, ValueError, KeyError) as exc:
                    last_error = f"Gemini 语音请求失败：{exc}"
                    self.store.mark_use("Gemini", item["id"], "异常", last_error)
            raise RuntimeError(f"Gemini 可用密钥均生成失败。最后错误：{last_error}")

        voice_id = voice.strip()
        if not voice_id or voice_id.endswith("Neural"):
            raise RuntimeError("使用 ElevenLabs 时，请在音色框输入 ElevenLabs Voice ID。")
        candidates = self.store.candidates("ElevenLabs")
        if not candidates:
            raise RuntimeError("没有可用的 ElevenLabs 密钥，请先到密钥管理添加并检测。")
        last_error = ""
        for item in candidates:
            try:
                response = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={"xi-api-key": item["key"], "Content-Type": "application/json",
                             "Accept": "audio/mpeg"},
                    json={"text": text, "model_id": "eleven_multilingual_v2",
                          "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}, timeout=180)
                if response.status_code >= 400:
                    last_error = response_error(response)
                    self.store.mark_use("ElevenLabs", item["id"],
                                        "失效" if response.status_code in (401, 403) else
                                        "额度受限" if response.status_code == 429 else "异常", last_error)
                    continue
                content_type = response.headers.get("Content-Type", "").lower()
                if len(response.content) < 256 or (content_type and "audio" not in content_type):
                    last_error = ("接口没有返回有效音频"
                                  f"（Content-Type: {content_type or '未知'}，{len(response.content)} 字节）")
                    self.store.mark_use("ElevenLabs", item["id"], "异常", last_error)
                    continue
                target.write_bytes(response.content)
                self.store.mark_use("ElevenLabs", item["id"], "有效", "")
                return target
            except requests.RequestException as exc:
                last_error = f"网络请求失败：{exc}"
                self.store.mark_use("ElevenLabs", item["id"], "异常", last_error)
        raise RuntimeError(f"ElevenLabs 可用密钥均生成失败。最后错误：{last_error}")

    def _find_ffmpeg(self):
        executable = media_tool_name("ffmpeg")
        candidates = [bundled_media_tool("ffmpeg"), app_root() / executable, component_bin() / executable]
        for path in candidates:
            if path.exists():
                return str(path)
        found = shutil.which("ffmpeg")
        if found:
            return found
        raise RuntimeError(f"未找到 {executable}")

    def _start_transcription(self):
        local_files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        urls = [line.strip() for line in self.url_input.toPlainText().splitlines() if line.strip()]
        invalid_urls = [url for url in urls if not is_supported_video_url(url)]
        if invalid_urls:
            QMessageBox.warning(self, "链接格式不支持",
                                "以下内容不是受支持的视频链接：\n" + "\n".join(invalid_urls[:5]))
            return
        files = local_files + urls
        if not files:
            QMessageBox.information(self, "请选择来源", "请添加本地视频/音频，或粘贴网络视频链接。")
            return
        selected_provider = self.provider_combo.currentText()
        provider = self._resolve_provider() if selected_provider == AUTO_PROVIDER else selected_provider
        if provider != LOCAL_PROVIDER and not self.store.has_candidates(provider):
            QMessageBox.information(self, "缺少密钥", f"请先在“API 密钥管理”中添加 {provider} 密钥。")
            self._show_page(6)
            return
        try:
            ffmpeg = self._find_ffmpeg()
        except Exception as exc:
            QMessageBox.critical(self, "缺少组件", str(exc)); return
        model = (self.store.data["models"].get(provider, DEFAULT_MODELS[provider])
                 if selected_provider == AUTO_PROVIDER
                 else self.model_edit.text().strip() or DEFAULT_MODELS[provider])
        self.store.data["models"][provider] = model; self.store.save()
        self.log_box.clear(); self.transcribe_progress.setValue(0)
        if selected_provider == AUTO_PROVIDER:
            self._append_log(f"自动选择：{provider}（模型：{model}）")
        self.subtitle_results.clear(); self.result_combo.clear(); self.result_combo.addItem(ALL_RESULTS_LABEL)
        self.original_result.clear(); self.chinese_result.clear()
        self.thread = QThread(self)
        self.worker = TranscribeWorker(self.store, provider, model, files, "",
                                       self.language_edit.text(), self.diarize_check.isChecked(), ffmpeg,
                                       self.subtitle_resume_check.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self.transcribe_progress.setValue)
        self.worker.result_ready.connect(self._subtitle_result_ready)
        self.worker.finished.connect(self._transcription_done)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_ended)
        self.thread.finished.connect(self.thread.deleteLater)
        self.start_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        self.thread.start()

    def _cancel_transcription(self):
        if self.worker:
            self.worker.cancel(); self._append_log("正在取消（当前网络请求结束后生效）…")

    def _append_log(self, text):
        self.log_box.appendPlainText(f"[{datetime.now():%H:%M:%S}] {text}")

    def _transcription_done(self, ok, message):
        self.start_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self._append_log(message); self._refresh_keys()
        (QMessageBox.information if ok else QMessageBox.critical)(self, "任务完成" if ok else "任务失败", message)

    def _subtitle_result_ready(self, name, original, chinese, srt):
        self.subtitle_results[name] = {"original": original, "chinese": chinese, "srt": srt}
        if self.result_combo.findText(name) < 0:
            self.result_combo.addItem(name)
        self.result_combo.setCurrentText(ALL_RESULTS_LABEL)
        self._show_subtitle_result(ALL_RESULTS_LABEL)

    def _show_subtitle_result(self, name):
        if name == ALL_RESULTS_LABEL:
            originals, translations = [], []
            for result_name, result in self.subtitle_results.items():
                originals.append(f"【{result_name}】\n{result.get('original', '')}")
                translations.append(f"【{result_name}】\n{result.get('chinese', '')}")
            self.original_result.setPlainText("\n\n".join(originals))
            self.chinese_result.setPlainText("\n\n".join(translations))
            return
        result = self.subtitle_results.get(name, {})
        self.original_result.setPlainText(result.get("original", ""))
        self.chinese_result.setPlainText(result.get("chinese", ""))

    def _copy_bilingual(self):
        name = self.result_combo.currentText()
        if name == ALL_RESULTS_LABEL:
            self._copy_all_bilingual()
            return
        result = self.subtitle_results.get(name)
        if not result:
            return
        text = f"【原文】\n{result['original']}\n\n【简体中文】\n{result['chinese']}"
        QApplication.clipboard().setText(text)

    def _copy_all_original(self):
        text = "\n\n".join(f"【{name}】\n{result['original']}"
                            for name, result in self.subtitle_results.items())
        QApplication.clipboard().setText(text)

    def _copy_all_bilingual(self):
        parts = []
        for name, result in self.subtitle_results.items():
            parts.append(f"【{name}】\n【原文】\n{result['original']}\n\n【简体中文】\n{result['chinese']}")
        QApplication.clipboard().setText("\n\n".join(parts))

    def _export_all_subtitles(self):
        if not self.subtitle_results:
            QMessageBox.information(self, "没有结果", "请先完成字幕提取。")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择字幕导出目录")
        if not folder:
            return
        output = Path(folder)
        for number, (name, result) in enumerate(self.subtitle_results.items(), 1):
            base = re.sub(r'[\\/:*?"<>|]+', "_", Path(name).stem).strip(" .") or f"字幕_{number:03d}"
            (output / f"{base}.srt").write_text(result.get("srt", ""), encoding="utf-8-sig")
            (output / f"{base}_原文.txt").write_text(result.get("original", ""), encoding="utf-8-sig")
            bilingual = f"【原文】\n{result.get('original', '')}\n\n【简体中文】\n{result.get('chinese', '')}"
            (output / f"{base}_中外文对照.txt").write_text(bilingual, encoding="utf-8-sig")
        QMessageBox.information(self, "导出完成", f"已导出 {len(self.subtitle_results)} 组字幕到：\n{output}")

    def _add_keys_for_provider(self, provider):
        edit = self.provider_inputs[provider]
        keys = [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]
        if not keys:
            QMessageBox.information(self, "没有密钥", "请粘贴至少一枚密钥，每行一个。")
            return
        added, skipped = 0, []
        for key in keys:
            try:
                self.store.add_key(provider, key)
                added += 1
            except Exception:
                skipped.append(masked_key(key))
        edit.clear(); self._refresh_keys()
        message = f"已添加 {added} 枚 {provider} 密钥。"
        if skipped:
            message += f"\n跳过 {len(skipped)} 枚重复或无效内容。"
        QMessageBox.information(self, "批量添加完成", message)

    def _refresh_keys(self):
        if not hasattr(self, "key_table"):
            return
        self.key_table.setRowCount(0)
        status_colors = {"有效": "#22c55e", "失效": "#ef4444", "格式错误": "#ef4444",
                         "额度受限": "#f59e0b", "异常": "#f97316"}
        for provider in PROVIDERS:
            for item in self.store.data["providers"][provider]:
                row = self.key_table.rowCount(); self.key_table.insertRow(row)
                reason = item.get("last_error", "") or "—"
                compact_reason = " ".join(reason.split())
                values = [provider, masked_key(item["key"]), item.get("status", "未检测"),
                          item.get("last_checked", ""), str(item.get("uses", 0)), compact_reason, item["id"]]
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 5:
                        cell.setToolTip(reason)
                    if not item.get("enabled", True):
                        cell.setForeground(QColor("#64748b"))
                    elif col == 2 and value in status_colors:
                        cell.setForeground(QColor(status_colors[value]))
                    self.key_table.setItem(row, col, cell)

    def _selected_key_jobs(self):
        jobs = []
        for index in self.key_table.selectionModel().selectedRows():
            provider = self.key_table.item(index.row(), 0).text()
            key_id = self.key_table.item(index.row(), 6).text()
            item = next((x for x in self.store.data["providers"][provider] if x["id"] == key_id), None)
            if item: jobs.append((provider, item.copy()))
        return jobs

    def _check_selected_keys(self):
        jobs = self._selected_key_jobs()
        if not jobs:
            QMessageBox.information(self, "未选择", "请选择要检测的密钥行。")
            return
        self._run_key_check(jobs)

    def _check_all_keys(self):
        jobs = [(p, x.copy()) for p in PROVIDERS for x in self.store.data["providers"][p]]
        if jobs: self._run_key_check(jobs)

    def _run_key_check(self, jobs):
        if self.thread:
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前任务结束。")
                    return
            except RuntimeError:
                self.thread = None
        self.thread = QThread(self); self.worker = KeyCheckWorker(jobs); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._key_check_result)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(lambda: QMessageBox.information(self, "检测完成", "密钥检测已完成。"))
        self.thread.finished.connect(self._thread_ended)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def _key_check_result(self, provider, key_id, ok, message):
        if ok:
            status = "有效"
        elif "HTTP 429" in message:
            status = "额度受限"
        elif message.startswith("密钥格式异常"):
            status = "格式错误"
        elif "HTTP 401" in message or "HTTP 403" in message:
            status = "失效"
        else:
            status = "异常"
        self.store.update_key(provider, key_id, status=status,
                              last_checked=datetime.now().strftime("%Y-%m-%d %H:%M"), last_error="" if ok else message)
        self._refresh_keys()

    def _show_selected_key_error(self):
        rows = self.key_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未选择", "请先选择一行密钥。")
            return
        self._show_key_error(rows[0].row())

    def _show_key_error(self, row):
        provider_item = self.key_table.item(row, 0)
        key_id_item = self.key_table.item(row, 6)
        if not provider_item or not key_id_item:
            return
        provider = provider_item.text(); key_id = key_id_item.text()
        item = next((x for x in self.store.data["providers"][provider] if x["id"] == key_id), None)
        if not item:
            return
        reason = item.get("last_error") or "没有错误记录。该密钥尚未检测，或最近一次检测通过。"
        detail = (f"服务：{provider}\n密钥：{masked_key(item['key'])}\n"
                  f"状态：{item.get('status', '未检测')}\n"
                  f"检测时间：{item.get('last_checked') or '尚未检测'}\n\n"
                  f"检测详情：\n{reason}")
        box = QMessageBox(self); box.setWindowTitle("密钥检测详情"); box.setIcon(QMessageBox.Icon.Information)
        box.setText("密钥状态诊断"); box.setDetailedText(detail); box.setInformativeText(reason)
        box.exec()

    def _thread_ended(self):
        self.worker = None
        self.thread = None

    def _toggle_key(self):
        jobs = self._selected_key_jobs()
        for provider, item in jobs:
            self.store.update_key(provider, item["id"], enabled=not item.get("enabled", True))
        self._refresh_keys()

    def _remove_key(self):
        jobs = self._selected_key_jobs()
        if not jobs: return
        if QMessageBox.question(self, "确认删除", f"确定删除选中的 {len(jobs)} 枚密钥？") != QMessageBox.StandardButton.Yes:
            return
        for provider, item in jobs:
            self.store.remove_key(provider, item["id"])
        self._refresh_keys()


STYLE = """
QWidget { background:#080d19; color:#e5edf9; font-family:'Microsoft YaHei UI'; font-size:12px; }
#nav { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #101a35,stop:.55 #111b2e,stop:1 #0b1325); border-bottom:1px solid #263655; }
#brand { font-size:18px; font-weight:800; color:#f8fbff; padding-right:8px; }
#navButton { padding:8px 10px; border:1px solid transparent; border-radius:7px; color:#9cacbf; }
#navButton:hover { background:#192844; color:#f3f7ff; border-color:#2b4268; }
#navButton:checked { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #2563eb,stop:1 #7c3aed); color:white; font-weight:700; }
#heading { font-size:24px; font-weight:800; color:#f8fbff; }
#toolCard, #panel { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #121d31,stop:1 #0d1627); border:1px solid #263957; border-radius:12px; }
#toolCard:hover { border-color:#3b82f6; }
QPushButton { background:#17243a; border:1px solid #30445f; border-radius:6px; padding:6px 11px; min-height:18px; }
QPushButton:hover { background:#223654; border-color:#4d6d97; }
QPushButton:disabled { color:#64748b; background:#172033; }
#primary { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0ea5e9,stop:1 #6366f1); border-color:#60a5fa; color:white; font-weight:700; padding:7px 15px; }
#primary:hover { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #38bdf8,stop:1 #818cf8); }
QLineEdit, QComboBox, QSpinBox, QListWidget, QPlainTextEdit, QTextEdit, QTableWidget { background:#0c1424; border:1px solid #2b3d58; border-radius:5px; padding:4px; selection-background-color:#2563eb; }
QGroupBox { background:#101a2b; border:1px solid #293d5c; border-radius:8px; margin-top:8px; padding-top:7px; font-weight:700; }
QGroupBox::title { subcontrol-origin:margin; left:9px; padding:0 4px; color:#b8c8dc; }
QHeaderView::section { background:#17243a; color:#cbd5e1; border:none; padding:6px; }
QProgressBar { background:#17243a; border:none; border-radius:5px; text-align:center; min-height:16px; }
QProgressBar::chunk { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #06b6d4,stop:1 #6366f1); border-radius:5px; }
QScrollArea { border:none; }
QTabWidget::pane { border:1px solid #2b3d58; background:#0b1322; top:-1px; }
QTabBar::tab { background:#17243a; color:#cbd5e1; border:1px solid #30445f; padding:8px 16px; min-width:90px; }
QTabBar::tab:hover { background:#223654; color:white; }
QTabBar::tab:selected { background:#2563eb; color:white; border-color:#60a5fa; font-weight:700; }
QToolBar { background:#0d1627; border-bottom:1px solid #263957; spacing:6px; padding:4px; }
QScrollBar:vertical { background:#091221; width:14px; margin:2px; border-radius:7px; }
QScrollBar::handle:vertical { background:#46658d; min-height:34px; margin:1px; border-radius:6px; }
QScrollBar::handle:vertical:hover { background:#60a5fa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:#091221; height:14px; margin:2px; border-radius:7px; }
QScrollBar::handle:horizontal { background:#46658d; min-width:34px; margin:1px; border-radius:6px; }
QScrollBar::handle:horizontal:hover { background:#60a5fa; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }
QSlider::groove:horizontal { height:8px; background:#1c2d45; border-radius:4px; }
QSlider::sub-page:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #06b6d4,stop:1 #6366f1); border-radius:4px; }
QSlider::handle:horizontal { background:#e0f2fe; border:2px solid #38bdf8; width:18px; margin:-6px 0; border-radius:9px; }
QSlider::handle:horizontal:hover { background:white; border-color:#818cf8; }
QSplitter::handle { background:#263957; }
QSplitter::handle:hover { background:#3b82f6; }
"""


def main():
    _startup_trace("main entered")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = QApplication(sys.argv)
    _startup_trace("QApplication ready")
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    icon = resource_path("logo.ico")
    if icon.exists(): app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    _startup_trace(
        f"window shown platform={app.platformName()} visible={window.isVisible()} "
        f"winId={int(window.winId())} geometry={window.geometry().getRect()}"
    )
    QTimer.singleShot(350, lambda: (window.raise_(), window.activateWindow()))
    # 打包后自动化启动检查使用；普通用户启动时不会触发。
    if os.environ.get("VIDEO_TOOLKIT_SMOKE_TEST", "").strip() == "1":
        QTimer.singleShot(1800, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
