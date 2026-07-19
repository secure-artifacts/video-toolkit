from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


PYTHON_COMPONENTS = [
    ("PySide6", "PySide6", "PySide6"),
    ("Pillow", "PIL", "Pillow"),
    ("OpenCV", "cv2", "opencv-python"),
    ("yt-dlp", "yt_dlp", "yt-dlp"),
    ("SceneDetect", "scenedetect", "scenedetect[opencv]"),
    ("MoviePy", "moviepy", "moviepy"),
    ("Requests", "requests", "requests"),
    ("本地 Whisper", "faster_whisper", "faster-whisper"),
    ("无密钥翻译", "deep_translator", "deep-translator"),
    ("Google Drive / Sheets", "googleapiclient", "google-api-python-client google-auth"),
    ("Google OAuth 授权", "google_auth_oauthlib", "google-auth-oauthlib"),
]


def toolkit_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", os.environ.get("APPDATA", Path.home())))
    path = base / "VideoToolkit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def component_bin() -> Path:
    path = toolkit_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hidden_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def find_media_tool(name: str):
    suffix = ".exe" if os.name == "nt" else ""
    local = component_bin() / f"{name}{suffix}"
    return str(local) if local.exists() else shutil.which(name)


def component_rows():
    rows = []
    for label, module, package in PYTHON_COMPONENTS:
        ok = importlib.util.find_spec(module) is not None
        version = ""
        if ok:
            try:
                version = importlib.metadata.version(package.split("[")[0])
            except Exception:
                version = "已安装"
        rows.append({"name": label, "type": "Python 依赖", "ok": ok,
                     "detail": version or f"缺少：{package}", "package": package})
    for name in ("ffmpeg", "ffprobe"):
        path = find_media_tool(name)
        rows.append({"name": name.upper(), "type": "媒体组件", "ok": bool(path),
                     "detail": path or "未找到", "package": ""})
    return rows


class InstallWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, packages, install_media=False):
        super().__init__()
        self.packages = packages
        self.install_media = install_media

    def run(self):
        try:
            steps = len(self.packages) + (1 if self.install_media else 0)
            if not steps:
                self.finished.emit(True, "所有组件均已齐全")
                return
            completed = 0
            if self.packages:
                python_cmd = sys.executable if not getattr(sys, "frozen", False) else (shutil.which("python") or "python")
                self.log.emit("正在静默安装缺少的 Python 依赖 …")
                command = [python_cmd, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", *self.packages]
                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
                self.log.emit(result.stdout[-5000:])
                if result.returncode != 0:
                    raise RuntimeError("Python 依赖安装失败，请查看日志")
                completed += len(self.packages)
                self.progress.emit(round(completed / steps * 100))
            if self.install_media:
                self._install_ffmpeg()
                completed += 1
                self.progress.emit(round(completed / steps * 100))
            self.finished.emit(True, "组件安装完成，请重新检测")
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _install_ffmpeg(self):
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        self.log.emit("正在下载 FFmpeg Essentials（包含 FFmpeg 与 FFprobe）…")
        with tempfile.TemporaryDirectory(prefix="video_toolkit_ffmpeg_") as temp_name:
            archive = Path(temp_name) / "ffmpeg.zip"
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                received = 0
                with archive.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk); received += len(chunk)
                            if total:
                                self.progress.emit(min(95, round(received / total * 95)))
            self.log.emit("正在解压媒体组件 …")
            with zipfile.ZipFile(archive) as package:
                members = package.namelist()
                for executable in ("ffmpeg.exe", "ffprobe.exe"):
                    member = next((x for x in members if x.lower().endswith("/bin/" + executable)), None)
                    if not member:
                        raise RuntimeError(f"安装包中未找到 {executable}")
                    with package.open(member) as source, (component_bin() / executable).open("wb") as target:
                        shutil.copyfileobj(source, target)
        bin_text = str(component_bin())
        if bin_text not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = bin_text + os.pathsep + os.environ.get("PATH", "")


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.rows = []
        self.build_ui()
        self.refresh()

    def build_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 16, 24, 16); layout.setSpacing(8)
        title = QLabel("设置与组件管理"); title.setObjectName("heading")
        layout.addWidget(title)
        layout.addWidget(QLabel("集中检查整个软件需要的组件；安装过程静默执行，不弹出命令窗口。"))
        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("重新检测全部"); self.refresh_btn.clicked.connect(self.refresh)
        self.install_btn = QPushButton("一键安装缺少组件"); self.install_btn.setObjectName("primary"); self.install_btn.clicked.connect(self.install_missing)
        self.media_btn = QPushButton("重新安装 FFmpeg / FFprobe"); self.media_btn.clicked.connect(lambda: self.start_install([], True))
        actions.addWidget(self.refresh_btn); actions.addWidget(self.install_btn); actions.addWidget(self.media_btn); actions.addStretch()
        layout.addLayout(actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["组件", "类型", "状态", "版本或位置"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(170)
        layout.addWidget(self.log)

    def refresh(self):
        self.rows = component_rows(); self.table.setRowCount(0)
        for data in self.rows:
            row = self.table.rowCount(); self.table.insertRow(row)
            values = (data["name"], data["type"], "✓ 正常" if data["ok"] else "✕ 缺少", data["detail"])
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 2:
                    item.setForeground(QColor("#22c55e" if data["ok"] else "#ef4444"))
                self.table.setItem(row, col, item)
        missing = sum(not x["ok"] for x in self.rows)
        self.install_btn.setText(f"一键安装缺少组件（{missing}）")

    def install_missing(self):
        packages = [x["package"] for x in self.rows if not x["ok"] and x["type"] == "Python 依赖"]
        media = any(not x["ok"] and x["type"] == "媒体组件" for x in self.rows)
        self.start_install(packages, media)

    def start_install(self, packages, media):
        if self.thread:
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "安装进行中", "请等待当前安装结束。")
                    return
            except RuntimeError:
                self.thread = None
        self.log.clear(); self.progress.setValue(0)
        self.thread = QThread(self); self.worker = InstallWorker(packages, media); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue); self.worker.finished.connect(self.done)
        self.worker.finished.connect(self.thread.quit); self.thread.finished.connect(self._thread_ended)
        self.thread.finished.connect(self.thread.deleteLater)
        self.install_btn.setEnabled(False); self.media_btn.setEnabled(False); self.thread.start()

    def done(self, ok, message):
        self.install_btn.setEnabled(True); self.media_btn.setEnabled(True); self.log.appendPlainText(message); self.refresh()
        (QMessageBox.information if ok else QMessageBox.critical)(self, "组件管理", message)

    def _thread_ended(self):
        self.worker = None
        self.thread = None
