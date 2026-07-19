from __future__ import annotations

import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)
from .path_picker import DropListWidget, VIDEO_EXTENSIONS, collect_files, load_subfolders


def hidden_kwargs():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def video_duration(ffmpeg: str, path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        candidate = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        ffprobe = str(candidate) if candidate.exists() else None
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    result = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", **hidden_kwargs())
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
    if not match:
        raise RuntimeError("无法获取视频时长")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


class SmartCutWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, files, output, mode, sequence, loop_length, threshold, ffmpeg):
        super().__init__()
        self.files = files
        self.output = Path(output)
        self.mode = mode
        self.sequence = sequence
        self.loop_length = loop_length
        self.threshold = threshold
        self.ffmpeg = ffmpeg
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            total = len(self.files)
            with ThreadPoolExecutor(max_workers=min(4, total)) as pool:
                futures = {pool.submit(self.process_one, path): Path(path).name for path in self.files}
                done = 0
                for future in as_completed(futures):
                    future.result()
                    done += 1
                    self.log.emit(f"完成：{futures[future]}")
                    self.progress.emit(round(done / total * 100))
                    if self.cancelled:
                        raise RuntimeError("用户已取消任务")
            self.finished.emit(True, "所有视频处理完成")
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def process_one(self, path):
        if self.cancelled:
            raise RuntimeError("用户已取消任务")
        target_dir = self.output / Path(path).stem
        target_dir.mkdir(parents=True, exist_ok=True)
        self.log.emit(f"处理中：{Path(path).name}")
        if self.mode == "智能画面识别":
            self.smart_split(path, target_dir)
        else:
            self.fixed_split(path, target_dir)

    def smart_split(self, path, target_dir):
        try:
            from scenedetect import ContentDetector, detect, split_video_ffmpeg
        except ImportError as exc:
            raise RuntimeError("缺少 scenedetect，无法进行智能画面识别") from exc
        scenes = detect(path, ContentDetector(threshold=self.threshold))
        if self.cancelled:
            raise RuntimeError("用户已取消任务")
        split_video_ffmpeg(path, scenes, output_file_template=str(target_dir / "$SCENE_NUMBER.mp4"))

    def fixed_split(self, path, target_dir):
        total = video_duration(self.ffmpeg, path)
        sequence = [float(x.strip()) for x in self.sequence.replace("，", ",").split(",") if x.strip()]
        if not sequence and self.loop_length <= 0:
            raise RuntimeError("请设置有效的切片时长")
        current, index = 0.0, 0
        while current < total - 0.1:
            if self.cancelled:
                raise RuntimeError("用户已取消任务")
            step = sequence[index] if index < len(sequence) else self.loop_length
            if step <= 0:
                raise RuntimeError("每段时长必须大于 0")
            duration = min(step, total - current)
            destination = target_dir / f"{index + 1:03d}.mp4"
            cmd = [self.ffmpeg, "-y", "-ss", str(current), "-t", str(duration), "-i", path,
                   "-c", "copy", "-avoid_negative_ts", "1", str(destination)]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_kwargs())
            if result.returncode != 0:
                raise RuntimeError(f"切片失败：{destination.name}")
            current += duration
            index += 1


class SmartCutPage(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("智能剪辑")
        title.setStyleSheet("font-size:26px;font-weight:800;")
        layout.addWidget(title)
        layout.addWidget(QLabel("支持自定义时长序列与智能场景识别，多文件并行处理。"))
        layout.addWidget(QLabel("视频队列（可拖入视频或整个文件夹）"))
        self.files = DropListWidget(); self.files.setMinimumHeight(115)
        self.files.paths_dropped.connect(self.add_paths)
        layout.addWidget(self.files)
        row = QHBoxLayout()
        add = QPushButton("选择视频"); add.clicked.connect(self.add_files)
        add_folder = QPushButton("选择文件夹"); add_folder.clicked.connect(self.add_folder)
        parent = QPushButton("选择父目录"); parent.clicked.connect(self.choose_parent_folder)
        clear = QPushButton("清空"); clear.clicked.connect(self.files.clear)
        row.addWidget(add); row.addWidget(add_folder); row.addWidget(parent); row.addWidget(clear); row.addStretch(); layout.addLayout(row)
        folder_row = QHBoxLayout(); folder_row.addWidget(QLabel("子文件夹"))
        self.subfolders = QComboBox(); self.subfolders.setEnabled(False)
        add_selected = QPushButton("添加所选目录"); add_selected.clicked.connect(self.add_selected_folder)
        folder_row.addWidget(self.subfolders, 1); folder_row.addWidget(add_selected); layout.addLayout(folder_row)
        form = QFormLayout()
        out_row = QHBoxLayout()
        self.output = QLineEdit(str(Path.cwd() / "智能剪辑输出"))
        choose = QPushButton("选择…"); choose.clicked.connect(self.choose_output)
        out_row.addWidget(self.output); out_row.addWidget(choose)
        out_widget = QWidget(); out_widget.setLayout(out_row); form.addRow("输出目录", out_widget)
        self.mode = QComboBox(); self.mode.addItems(["自定义时长序列", "智能画面识别"])
        self.mode.currentTextChanged.connect(self.mode_changed); form.addRow("剪辑模式", self.mode)
        self.sequence = QLineEdit("5,10,15"); form.addRow("时长序列（秒）", self.sequence)
        self.loop = QLineEdit("30"); form.addRow("序列用完后循环时长", self.loop)
        self.threshold = QLineEdit("27"); self.threshold.setEnabled(False); form.addRow("场景检测阈值", self.threshold)
        layout.addLayout(form)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log, 1)
        actions = QHBoxLayout(); actions.addStretch()
        self.stop = QPushButton("停止"); self.stop.setEnabled(False); self.stop.clicked.connect(self.cancel)
        self.start = QPushButton("开始处理"); self.start.setObjectName("primary"); self.start.clicked.connect(self.start_work)
        actions.addWidget(self.stop); actions.addWidget(self.start); layout.addLayout(actions)

    def mode_changed(self, mode):
        smart = mode == "智能画面识别"
        self.threshold.setEnabled(smart); self.sequence.setEnabled(not smart); self.loop.setEnabled(not smart)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择视频", "", "视频 (*.mp4 *.mov *.mkv *.avi *.wmv *.webm *.m4v);;所有文件 (*.*)")
        self.add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if folder: self.add_paths([folder])

    def add_paths(self, paths):
        files = collect_files(paths, VIDEO_EXTENSIONS)
        current = {self.files.item(i).text() for i in range(self.files.count())}
        for path in files:
            if path not in current: self.files.addItem(path); current.add(path)

    def choose_parent_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择父目录")
        if folder:
            try: load_subfolders(self.subfolders, folder)
            except OSError as exc: QMessageBox.warning(self, "无法读取目录", str(exc))

    def add_selected_folder(self):
        folder = self.subfolders.currentData()
        if folder: self.add_paths([folder])

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if path: self.output.setText(path)

    def start_work(self):
        files = [self.files.item(i).text() for i in range(self.files.count())]
        if not files:
            QMessageBox.information(self, "请选择文件", "请先选择视频文件。")
            return
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            QMessageBox.critical(self, "缺少 FFmpeg", "当前系统未找到 ffmpeg。")
            return
        try:
            loop = float(self.loop.text()); threshold = float(self.threshold.text())
        except ValueError:
            QMessageBox.warning(self, "参数错误", "时长和阈值必须是数字。")
            return
        self.thread = QThread(self)
        self.worker = SmartCutWorker(files, self.output.text(), self.mode.currentText(), self.sequence.text(), loop, threshold, ffmpeg)
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText); self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.done); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False); self.stop.setEnabled(True); self.thread.start()

    def cancel(self):
        if self.worker: self.worker.cancel()

    def done(self, ok, message):
        self.start.setEnabled(True); self.stop.setEnabled(False); self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(self, "处理完成" if ok else "处理失败", message)
