from __future__ import annotations

import datetime
import json
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QGroupBox, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)
from .path_picker import DropFolderLineEdit, load_subfolders


TITLE_MAX_CHARS = 20
MAX_FILENAME_CHARS = 230
MAX_SAFE_PATH_CHARS = 245
INVALID_FILENAME_CHARS = '<>:"/\\|?*'
INVALID_FILENAME_TRANS = str.maketrans("", "", INVALID_FILENAME_CHARS)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def clean_filename_part(value, fallback="未命名", max_chars=None):
    original = str(value)
    cleaned = original.translate(INVALID_FILENAME_TRANS)
    cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if max_chars is not None:
        cleaned = cleaned[:max_chars].rstrip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned += "_"
    return cleaned


def filename_part_changed(value, max_chars=None):
    raw = str(value).strip()
    return clean_filename_part(raw, fallback="", max_chars=max_chars) != raw


def safe_filename(filename, parent: Path):
    source = Path(filename)
    extension = source.suffix
    stem = clean_filename_part(source.stem)
    parent_text = str(parent.resolve())
    available = MAX_SAFE_PATH_CHARS - len(parent_text) - 1 - len(extension)
    maximum = min(MAX_FILENAME_CHARS - len(extension), available)
    if maximum < 12:
        raise ValueError(f"输出路径过长，请选择更短的输出目录：{parent}")
    truncated = len(stem) > maximum
    stem = stem[:maximum].rstrip(" .") or "未命名"
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem += "_"
    return stem + extension, truncated


class RenameTask:
    def __init__(self, input_dir, output_parent, task_name, prefix, titles, date_str,
                 suffix, start_index, padding, copy_files):
        self.input_dir = Path(input_dir)
        self.output_parent = Path(output_parent)
        raw_task_name = task_name.strip() or self.input_dir.name
        self.task_name = clean_filename_part(raw_task_name, max_chars=80)
        self.task_name_changed = filename_part_changed(raw_task_name, 80)
        self.prefix = clean_filename_part(prefix.strip(), fallback="", max_chars=60) if prefix.strip() else ""
        self.prefix_changed = filename_part_changed(prefix, 60) if prefix.strip() else False
        raw_titles = [x.strip() for x in titles.splitlines() if x.strip()]
        self.titles = [clean_filename_part(x, fallback="", max_chars=TITLE_MAX_CHARS) for x in raw_titles]
        self.title_changed = [filename_part_changed(x, TITLE_MAX_CHARS) for x in raw_titles]
        self.date_str = clean_filename_part(date_str.strip(), fallback="", max_chars=30) if date_str.strip() else ""
        self.date_changed = filename_part_changed(date_str, 30) if date_str.strip() else False
        self.suffix = clean_filename_part(suffix.strip(), fallback="", max_chars=60) if suffix.strip() else ""
        self.suffix_changed = filename_part_changed(suffix, 60) if suffix.strip() else False
        self.start_index = int(start_index)
        self.padding = int(padding)
        self.copy_files = copy_files

    def output_folder(self):
        return self.output_parent / "_".join(clean_filename_part(self.task_name).split())

    def render_name(self, original, index):
        return self.render_name_info(original, index)[0]

    def render_name_info(self, original, index):
        source = Path(original)
        title_index = index - self.start_index
        changed = self.task_name_changed or self.prefix_changed or self.date_changed or self.suffix_changed
        if self.titles:
            title = self.titles[title_index] if 0 <= title_index < len(self.titles) else ""
            if 0 <= title_index < len(self.title_changed):
                changed = changed or self.title_changed[title_index]
        else:
            title = clean_filename_part(source.stem, fallback="", max_chars=TITLE_MAX_CHARS)
            changed = changed or filename_part_changed(source.stem, TITLE_MAX_CHARS)
        parts = [str(index).zfill(self.padding)]
        for part in (self.prefix, title, self.date_str):
            if part: parts.append(part)
        base = "-".join(parts)
        if self.suffix: base += self.suffix if self.suffix.startswith("-") else "-" + self.suffix
        result, truncated = safe_filename(base + source.suffix, self.output_folder())
        return result, changed or truncated


class RenameWorker(QObject):
    log = Signal(str); progress = Signal(int); finished = Signal(bool, str)

    def __init__(self, tasks):
        super().__init__(); self.tasks = tasks

    def run(self):
        try:
            for task_no, task in enumerate(self.tasks):
                if not task.input_dir.is_dir():
                    raise FileNotFoundError(f"源文件夹已不存在：{task.input_dir}")
                if not task.output_parent.is_dir():
                    raise FileNotFoundError(f"输出父目录已不存在：{task.output_parent}")
                output = task.output_folder(); output.mkdir(parents=True, exist_ok=True)
                files = sorted((x for x in task.input_dir.iterdir() if x.is_file()), key=lambda x: natural_key(x.name))
                for offset, source in enumerate(files):
                    if not source.exists():
                        raise FileNotFoundError(f"源文件已不存在：{source}")
                    new_name, adjusted = task.render_name_info(source.name, task.start_index + offset)
                    destination = unique_destination(output / new_name)
                    (shutil.copy2 if task.copy_files else shutil.move)(str(source), str(destination))
                    note = "（已清洗/截断）" if adjusted else ""
                    self.log.emit(f"{source.name}  →  {destination.name}{note}")
                self.progress.emit(round((task_no + 1) / len(self.tasks) * 100))
            self.finished.emit(True, "全部重命名任务已完成")
        except Exception as exc:
            self.finished.emit(False, str(exc))


def natural_key(text):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", text)]


def unique_destination(path: Path):
    if not path.exists(): return path
    number = 1
    while True:
        tail = f"_{number}"
        available = min(
            MAX_FILENAME_CHARS - len(path.suffix) - len(tail),
            MAX_SAFE_PATH_CHARS - len(str(path.parent.resolve())) - 1 - len(path.suffix) - len(tail),
        )
        if available < 8:
            raise ValueError(f"输出路径过长，请选择更短的输出目录：{path.parent}")
        candidate = path.with_name(f"{path.stem[:available].rstrip(' .')}{tail}{path.suffix}")
        if not candidate.exists(): return candidate
        number += 1


class RenamePage(QWidget):
    def __init__(self):
        super().__init__(); self.tasks = []; self.thread = None; self.worker = None
        self.preset_path = Path(os.environ.get("APPDATA", Path.home())) / "VideoToolkit" / "rename_presets.json"
        self.presets = self.load_presets(); self.build_ui(); self.refresh_presets()

    def build_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(18, 12, 18, 12); layout.setSpacing(8)
        header = QHBoxLayout()
        title_box = QVBoxLayout(); title_box.setSpacing(1)
        title = QLabel("视频 / 文件批量重命名"); title.setStyleSheet("font-size:24px;font-weight:800;")
        title_box.addWidget(title); title_box.addWidget(QLabel("选文件夹、看预览、加入队列、统一执行"))
        header.addLayout(title_box); header.addStretch()
        top_preview = QPushButton("刷新预览"); top_preview.clicked.connect(self.update_preview)
        top_add = QPushButton("添加队列"); top_add.clicked.connect(self.add_task)
        self.run_btn = QPushButton("执行全部"); self.run_btn.setObjectName("primary"); self.run_btn.clicked.connect(self.run_tasks)
        header.addWidget(top_preview); header.addWidget(top_add); header.addWidget(self.run_btn)
        layout.addLayout(header)

        content = QSplitter(Qt.Orientation.Horizontal); content.setChildrenCollapsible(False)
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(10, 8, 10, 8); left_layout.setSpacing(7)
        form_group = QGroupBox("1. 文件夹与命名规则")
        form = QFormLayout(form_group); form.setContentsMargins(10, 10, 10, 10); form.setSpacing(6)
        self.input = DropFolderLineEdit(); self.input.setPlaceholderText("可把文件夹拖到这里")
        self.input.folder_dropped.connect(self.set_input_folder)
        form.addRow("源文件夹", self.path_row(self.input, self.choose_input))
        parent_row = QHBoxLayout()
        self.subfolders = QComboBox(); self.subfolders.setEnabled(False)
        choose_parent = QPushButton("选择父目录"); choose_parent.clicked.connect(self.choose_parent_folder)
        use_subfolder = QPushButton("使用所选目录"); use_subfolder.clicked.connect(self.use_selected_folder)
        parent_row.addWidget(self.subfolders, 1); parent_row.addWidget(choose_parent); parent_row.addWidget(use_subfolder)
        parent_widget = QWidget(); parent_widget.setLayout(parent_row); form.addRow("子文件夹", parent_widget)
        self.output = DropFolderLineEdit(); self.output.setPlaceholderText("可把输出文件夹拖到这里")
        form.addRow("输出父目录", self.path_row(self.output, self.choose_output))
        self.task_name = QLineEdit(); form.addRow("任务名称", self.task_name)
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox(); self.preset_combo.currentTextChanged.connect(self.apply_preset)
        save_preset = QPushButton("保存当前方案"); save_preset.clicked.connect(self.save_preset)
        delete_preset = QPushButton("删除方案"); delete_preset.clicked.connect(self.delete_preset)
        preset_row.addWidget(self.preset_combo, 1); preset_row.addWidget(save_preset); preset_row.addWidget(delete_preset)
        preset_widget = QWidget(); preset_widget.setLayout(preset_row); form.addRow("前后缀方案", preset_widget)
        self.prefix = QLineEdit(); form.addRow("前缀", self.prefix)
        line = QHBoxLayout()
        self.date = QLineEdit(datetime.date.today().strftime("%Y%m%d")); self.suffix = QLineEdit("FF-PT")
        self.start_index = QSpinBox(); self.start_index.setRange(0, 999999); self.start_index.setValue(1)
        self.padding = QSpinBox(); self.padding.setRange(1, 12); self.padding.setValue(3)
        line.addWidget(QLabel("日期")); line.addWidget(self.date); line.addWidget(QLabel("后缀")); line.addWidget(self.suffix)
        line.addWidget(QLabel("起始编号")); line.addWidget(self.start_index); line.addWidget(QLabel("位数")); line.addWidget(self.padding)
        line_widget = QWidget(); line_widget.setLayout(line); form.addRow("命名规则", line_widget)
        self.copy = QCheckBox("复制到输出目录，保留原文件"); self.copy.setChecked(True); form.addRow("处理方式", self.copy)
        left_layout.addWidget(form_group)

        title_group = QGroupBox("2. 标题列表（每行一个；留空使用原文件名）")
        title_layout = QVBoxLayout(title_group); title_layout.setContentsMargins(10, 10, 10, 10)
        self.titles = QPlainTextEdit(); self.titles.setMinimumHeight(150)
        title_layout.addWidget(self.titles)
        buttons = QHBoxLayout()
        preview = QPushButton("刷新预览"); preview.clicked.connect(self.update_preview)
        load = QPushButton("读取文件名为标题"); load.clicked.connect(self.load_titles)
        add = QPushButton("添加到队列"); add.clicked.connect(self.add_task)
        buttons.addWidget(load); buttons.addWidget(preview); buttons.addWidget(add); buttons.addStretch()
        title_layout.addLayout(buttons); left_layout.addWidget(title_group, 1)
        left_scroll.setWidget(left); content.addWidget(left_scroll)

        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(10, 8, 10, 8); right_layout.setSpacing(8)
        preview_group = QGroupBox("预览（先确认生成结果，再加入队列）")
        preview_layout = QVBoxLayout(preview_group); preview_layout.setContentsMargins(10, 10, 10, 10)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setMinimumHeight(190)
        preview_layout.addWidget(self.preview); right_layout.addWidget(preview_group, 1)
        queue_group = QGroupBox("任务队列")
        queue_layout = QVBoxLayout(queue_group); queue_layout.setContentsMargins(10, 10, 10, 10)
        self.queue = QTableWidget(0, 4); self.queue.setHorizontalHeaderLabels(["任务", "文件数", "输出目录", "状态"])
        self.queue.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); queue_layout.addWidget(self.queue)
        action = QHBoxLayout(); remove = QPushButton("移除选中"); remove.clicked.connect(self.remove_task)
        self.queue_run_btn = QPushButton("执行全部"); self.queue_run_btn.clicked.connect(self.run_tasks)
        action.addWidget(remove); action.addStretch(); action.addWidget(self.queue_run_btn)
        queue_layout.addLayout(action); right_layout.addWidget(queue_group, 1)
        content.addWidget(right); content.setSizes([610, 720]); content.setStretchFactor(0, 5); content.setStretchFactor(1, 6)
        layout.addWidget(content, 1)

        log_row = QHBoxLayout(); log_row.addWidget(QLabel("执行日志")); log_row.addStretch()
        layout.addLayout(log_row)
        self.progress = QProgressBar(); self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(90)
        layout.addWidget(self.progress); layout.addWidget(self.log)

    def load_presets(self):
        try:
            return json.loads(self.preset_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "常用-FF-PT": {"prefix": "", "suffix": "FF-PT"},
                "仅编号": {"prefix": "", "suffix": ""},
            }

    def persist_presets(self):
        self.preset_path.parent.mkdir(parents=True, exist_ok=True)
        self.preset_path.write_text(json.dumps(self.presets, ensure_ascii=False, indent=2), encoding="utf-8")

    def refresh_presets(self, selected=""):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear(); self.preset_combo.addItem("选择已保存方案…")
        self.preset_combo.addItems(self.presets.keys())
        if selected:
            self.preset_combo.setCurrentText(selected)
        self.preset_combo.blockSignals(False)

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "保存前后缀方案", "方案名称：")
        if not ok: return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "无法保存", "请输入方案名称。")
            return
        try:
            self.presets[name] = {"prefix": self.prefix.text(), "suffix": self.suffix.text()}
            self.persist_presets(); self.refresh_presets(name)
            QMessageBox.information(self, "保存成功", f"前后缀方案“{name}”已保存。")
        except Exception as exc:
            QMessageBox.critical(self, "保存方案失败", f"无法写入配置：\n{exc}")

    def apply_preset(self, name):
        data = self.presets.get(name)
        if data:
            self.prefix.setText(data.get("prefix", "")); self.suffix.setText(data.get("suffix", "")); self.update_preview()

    def delete_preset(self):
        name = self.preset_combo.currentText()
        if name in self.presets:
            try:
                del self.presets[name]; self.persist_presets(); self.refresh_presets()
                QMessageBox.information(self, "删除成功", f"前后缀方案“{name}”已删除。")
            except Exception as exc:
                QMessageBox.critical(self, "删除方案失败", f"无法写入配置：\n{exc}")

    def path_row(self, edit, callback):
        row = QHBoxLayout(); button = QPushButton("浏览…"); button.clicked.connect(callback); row.addWidget(edit); row.addWidget(button)
        widget = QWidget(); widget.setLayout(row); return widget

    def choose_input(self):
        path = QFileDialog.getExistingDirectory(self, "选择源文件夹")
        if path: self.set_input_folder(path)

    def set_input_folder(self, path):
        self.input.setText(path)
        if not self.output.text(): self.output.setText(str(Path(path).parent))
        if not self.task_name.text(): self.task_name.setText(Path(path).name)
        self.update_preview()

    def choose_parent_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择父目录")
        if path:
            try: load_subfolders(self.subfolders, path)
            except OSError as exc: QMessageBox.warning(self, "无法读取目录", str(exc))

    def use_selected_folder(self):
        path = self.subfolders.currentData()
        if path: self.set_input_folder(path)

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出父目录")
        if path: self.output.setText(path)

    def task_from_form(self):
        if not Path(self.input.text()).is_dir() or not Path(self.output.text()).is_dir():
            raise ValueError("请选择有效的源文件夹和输出父目录")
        return RenameTask(self.input.text(), self.output.text(), self.task_name.text(), self.prefix.text(),
                          self.titles.toPlainText(), self.date.text(), self.suffix.text(),
                          self.start_index.value(), self.padding.value(), self.copy.isChecked())

    def update_preview(self):
        try:
            task = self.task_from_form()
            files = sorted((x for x in task.input_dir.iterdir() if x.is_file()), key=lambda x: natural_key(x.name))
            lines = [f"共 {len(files)} 个文件，预览前 8 个：", ""]
            for offset, item in enumerate(files[:8]):
                name, adjusted = task.render_name_info(item.name, task.start_index + offset)
                note = "  ⚠ 已自动清洗/截断" if adjusted else ""
                lines.append(f"{item.name}  →  {name}{note}")
            self.preview.setPlainText("\n".join(lines))
        except Exception as exc: self.preview.setPlainText(str(exc))

    def load_titles(self):
        folder = Path(self.input.text())
        if folder.is_dir():
            self.titles.setPlainText("\n".join(x.stem for x in sorted(folder.iterdir(), key=lambda x: natural_key(x.name)) if x.is_file()))
            self.update_preview()

    def add_task(self):
        try:
            task = self.task_from_form(); count = sum(1 for x in task.input_dir.iterdir() if x.is_file())
            if not count: raise ValueError("源文件夹没有文件")
            self.tasks.append(task); row = self.queue.rowCount(); self.queue.insertRow(row)
            for col, value in enumerate((task.task_name, str(count), str(task.output_folder()), "就绪")):
                self.queue.setItem(row, col, QTableWidgetItem(value))
        except Exception as exc: QMessageBox.warning(self, "无法添加任务", str(exc))

    def remove_task(self):
        rows = sorted({x.row() for x in self.queue.selectedIndexes()}, reverse=True)
        for row in rows: self.queue.removeRow(row); self.tasks.pop(row)

    def run_tasks(self):
        if not self.tasks:
            QMessageBox.information(self, "无任务", "请先添加任务。")
            return
        self.thread = QThread(self); self.worker = RenameWorker(list(self.tasks)); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue); self.worker.finished.connect(self.done)
        self.worker.finished.connect(self.thread.quit); self.thread.finished.connect(self.thread.deleteLater)
        self.run_btn.setEnabled(False); self.queue_run_btn.setEnabled(False); self.thread.start()

    def done(self, ok, message):
        self.run_btn.setEnabled(True); self.queue_run_btn.setEnabled(True); self.log.appendPlainText(message)
        for row in range(self.queue.rowCount()): self.queue.setItem(row, 3, QTableWidgetItem("已完成" if ok else "失败"))
        (QMessageBox.information if ok else QMessageBox.critical)(self, "执行完成" if ok else "执行失败", message)
