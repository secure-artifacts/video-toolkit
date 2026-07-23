from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2
import requests

def translate_to_chinese_free(text):
    text = text.strip()
    if not text:
        return ""
    visible = [c for c in text if c.isalpha() or "\u4e00" <= c <= "\u9fff"]
    chinese_count = sum("\u4e00" <= c <= "\u9fff" for c in visible)
    if visible and chinese_count / len(visible) > 0.45:
        return text
    import urllib.parse
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&dt=t&sl=auto&tl=zh-CN&q={urllib.parse.quote(text)}"
        res = requests.get(url, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if data and len(data) > 0 and data[0]:
                translated = "".join(sentence[0] for sentence in data[0] if sentence and len(sentence) > 0 and sentence[0])
                if translated.strip():
                    return translated.strip()
    except Exception:
        pass
    return ""

from PySide6.QtCore import QObject, QRectF, QSettings, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontInfo, QFontMetricsF, QImage, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QTabWidget,
    QStackedWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QVBoxLayout, QWidget,
)

from .path_picker import (
    AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, DropFolderLineEdit, DropListWidget, collect_files, default_output_path, natural_key,
)
from .group_merge import GroupMergeWorker, discover_groups, split_group_script
from .settings_page import hidden_kwargs
from .text_rules import normalize_required_capitalization
from .video_encoding import ENCODER_LABELS, encoder_args, resolve_encoder
from .app_logging import write_app_log
from .platform_utils import app_data_dir
from .rename_page import clean_filename_part, safe_filename


PRESETS = {
    "Descript 经典黄": {"text": "#F8FAFC", "outline": "#111111", "highlight": "#FACC15", "outline_width": 5,
                         "effect": "word_color", "font": "Arial", "font_size": 90, "line_length": 26,
                         "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                         "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 暖橙": {"text": "#FFFFFF", "outline": "#171717", "highlight": "#FB923C", "outline_width": 5,
                       "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                       "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 青柠": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#A3E635", "outline_width": 5,
                       "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                       "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 天蓝": {"text": "#FFFFFF", "outline": "#0F172A", "highlight": "#38BDF8", "outline_width": 5,
                       "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                       "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 紫色块": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#7C3AED", "outline_width": 4,
                         "effect": "descript", "font": "Arial", "font_size": 78, "line_length": 28,
                         "margin_v": 330, "max_words": 7, "highlight_padding": 18, "animation_speed": 150},
    "HeyGen 跟读": {"text": "#FFFFFF", "outline": "#050505", "highlight": "#F43F5E", "outline_width": 6, "effect": "heygen", "font": "Arial", "font_size": 86, "line_length": 18, "margin_v": 350},
    "逐字弹出": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#8B5CF6", "outline_width": 3, "effect": "pop"},
    "精选高亮": {"text": "#FFFFFF", "outline": "#172554", "highlight": "#7C3AED", "outline_width": 2, "effect": "highlight"},
    "小范下划线": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#FACC15", "outline_width": 2, "effect": "underline"},
    "外框字幕": {"text": "#FFFFFF", "outline": "#8B5CF6", "highlight": "#8B5CF6", "outline_width": 5, "effect": "outline"},
    "背景跟读": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#2563EB", "outline_width": 2, "effect": "highlight"},
    "光晕字幕": {"text": "#F5F3FF", "outline": "#7C3AED", "highlight": "#A855F7", "outline_width": 6, "effect": "glow"},
}

OPEN_SOURCE_FONTS = {
    # Final subtitles are bold.  Static Bold files are intentional: some
    # libass/DirectWrite combinations select the Regular face from a variable
    # font even when ASS asks for weight 700, while Qt correctly selects Bold.
    # That silent mismatch was the main cause of preview/export size drift.
    "Open Sans（清晰现代/多语言）": ("OpenSans-Bold.ttf", "https://raw.githubusercontent.com/googlefonts/opensans/main/fonts/ttf/OpenSans-Bold.ttf", "SIL OFL 1.1"),
    "Noto Sans（多语言/希腊语）": ("NotoSans-Bold.ttf", "https://raw.githubusercontent.com/notofonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf", "SIL OFL 1.1"),
    "Noto Sans SC（简体中文）": ("NotoSansCJKsc-Bold.otf", "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf", "SIL OFL 1.1"),
    "Poppins（现代拉丁字形）": ("Poppins-Bold.ttf", "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf", "SIL OFL 1.1"),
    "Libre Baskerville（衬线）": ("LibreBaskerville-Bold.ttf", "https://raw.githubusercontent.com/google/fonts/main/ofl/librebaskerville/static/LibreBaskerville-Bold.ttf", "SIL OFL 1.1"),
}

STATIC_BOLD_FONT_FILES = {
    "Open Sans": "OpenSans-Bold.ttf",
    "Noto Sans": "NotoSans-Bold.ttf",
    "Noto Sans SC": "NotoSansCJKsc-Bold.otf",
    "Noto Sans CJK SC": "NotoSansCJKsc-Bold.otf",
    "Poppins": "Poppins-Bold.ttf",
    "Libre Baskerville": "LibreBaskerville-Bold.ttf",
}

CAPTION_RENDERER_VERSION = 9


def custom_font_dir():
    folder=app_data_dir()/"fonts"
    folder.mkdir(parents=True,exist_ok=True)
    # Migrate fonts installed by early macOS builds from ~/VideoToolkit/fonts.
    if sys.platform == "darwin":
        legacy=Path.home()/"VideoToolkit"/"fonts"
        if legacy.is_dir():
            for source in legacy.iterdir():
                target=folder/source.name
                if source.is_file() and not target.exists():
                    try: shutil.copy2(source,target)
                    except OSError: pass
    return folder


def bundled_font_dir():
    return Path(__file__).resolve().parents[1]/"resources"/"fonts"


def render_font_dir():
    """Return one short directory containing user and bundled font assets."""
    destination=Path(tempfile.gettempdir())/"video_toolkit_fonts"
    destination.mkdir(parents=True,exist_ok=True)
    for source_dir in (custom_font_dir(),bundled_font_dir()):
        if not source_dir.is_dir(): continue
        for source in source_dir.iterdir():
            if not source.is_file() or source.suffix.casefold() not in (".ttf",".otf",".ttc"): continue
            target=destination/source.name
            try:
                if not target.exists() or source.stat().st_size != target.stat().st_size:
                    shutil.copy2(source,target)
            except OSError:
                pass
    return destination


class FontDownloadWorker(QObject):
    finished=Signal(bool,str,list)

    def __init__(self,names):
        super().__init__(); self.names=list(names)

    def run(self):
        installed=[]; failures=[]; folder=custom_font_dir(); folder.mkdir(parents=True,exist_ok=True)
        for name in self.names:
            filename,url,_license=OPEN_SOURCE_FONTS[name]; target=folder/filename
            try:
                if not target.exists() or target.stat().st_size<1024:
                    response=requests.get(url,timeout=60); response.raise_for_status()
                    temporary=target.with_suffix(target.suffix+".download"); temporary.write_bytes(response.content); temporary.replace(target)
                installed.append(str(target))
            except Exception as exc:
                failures.append(f"{name}：{exc}")
        message=f"已安装 {len(installed)} 个开源字体"+(f"；失败 {len(failures)} 个："+"｜".join(failures) if failures else "")
        self.finished.emit(bool(installed),message,installed)


class ScriptTaskTable(QTableWidget):
    """One editable row per batch TTS job, with paste-friendly helpers."""

    textChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["序号", "需要转成音频的文案（每行一个任务）"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(0, 46)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(False)
        self.setWordWrap(True)
        self.setStyleSheet(
            "QTableWidget{background:#0b1424;alternate-background-color:#0b1424;}"
            "QTableWidget::item{background:#0b1424;color:#e5edf8;padding:4px;}"
            "QTableWidget::item:selected{background:#2563eb;color:#ffffff;}"
        )
        self.itemChanged.connect(lambda _item: self.textChanged.emit())

    def add_script(self, text=""):
        row = self.rowCount()
        self.insertRow(row)
        number = QTableWidgetItem(f"{row + 1:02d}")
        number.setFlags(number.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, 0, number)
        self.setItem(row, 1, QTableWidgetItem(str(text)))
        self.setRowHeight(row, 38)
        return row

    def setPlainText(self, text):
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            lines = [line.strip() for line in str(text or "").splitlines() if line.strip() and line.strip() != "---"]
            for line in lines:
                self.add_script(line)
        finally:
            self.blockSignals(False)
        self.textChanged.emit()

    def toPlainText(self):
        return "\n".join(
            self.item(row, 1).text().strip()
            for row in range(self.rowCount())
            if self.item(row, 1) and self.item(row, 1).text().strip()
        )

    def paste_rows(self):
        self.setPlainText(QApplication.clipboard().text())

    def remove_selected_rows(self):
        rows = sorted({index.row() for index in self.selectedIndexes()}, reverse=True)
        for row in rows:
            self.removeRow(row)
        for row in range(self.rowCount()):
            self.item(row, 0).setText(f"{row + 1:02d}")
        self.textChanged.emit()

    def appendPlainText(self, text):
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip() and line.strip() != "---"]
        for line in lines:
            self.add_script(line)
        if lines:
            self.textChanged.emit()


class ScriptTaskDialog(QDialog):
    """Batch-friendly editor; the compact table on the main page remains a task overview."""

    def __init__(self, text="", parent=None, add_empty=False, clipboard_text=""):
        super().__init__(parent)
        self.setWindowTitle("批量文案任务编辑")
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        hint = QLabel("每一行对应一个视频/音频任务。可从表格或文本中复制多行后一次粘贴。")
        hint.setStyleSheet("color:#7dd3fc;")
        layout.addWidget(hint)
        self.table = ScriptTaskTable()
        self.table.setPlainText(text)
        if clipboard_text:
            self.table.appendPlainText(clipboard_text)
        if add_empty:
            row = self.table.add_script("")
            self.table.setCurrentCell(row, 1)
            self.table.editItem(self.table.item(row, 1))
        layout.addWidget(self.table, 1)
        tools = QHBoxLayout()
        add_row = QPushButton("＋ 新增一行")
        add_row.clicked.connect(lambda: self.table.add_script(""))
        paste = QPushButton("从剪贴板追加多行")
        paste.clicked.connect(lambda: self.table.appendPlainText(QApplication.clipboard().text()))
        remove = QPushButton("删除选中")
        remove.clicked.connect(self.table.remove_selected_rows)
        tools.addWidget(add_row); tools.addWidget(paste); tools.addWidget(remove); tools.addStretch()
        layout.addLayout(tools)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Save).setText("保存任务")
        actions.accepted.connect(self.accept); actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def text(self):
        return self.table.toPlainText()


class ProgressSlider(QSlider):
    """Compact, non-interactive progress indicator styled as a slider."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setFixedHeight(18)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            "QSlider::groove:horizontal{height:6px;background:#17243a;border-radius:3px;}"
            "QSlider::sub-page:horizontal{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #06b6d4,stop:1 #6366f1);border-radius:3px;}"
            "QSlider::handle:horizontal{width:12px;margin:-4px 0;background:#e0f2fe;border:2px solid #38bdf8;border-radius:6px;}"
        )


class DragHandleWidget(QWidget):
    def __init__(self, list_widget, parent=None):
        super().__init__(parent)
        self.list_widget = list_widget
        self.setFixedWidth(16)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("用鼠标拖拽此处可上下调整顺序")

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QColor
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#4b5563"), 2))
        x = self.width() // 2
        for y in (16, 22, 28, 34, 40):
            painter.drawPoint(x - 2, y)
            painter.drawPoint(x + 2, y)

    def mousePressEvent(self, event):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QMouseEvent
        viewport = self.list_widget.viewport()
        pos_in_viewport = viewport.mapFromGlobal(event.globalPosition().toPoint())
        fake_event = QMouseEvent(
            event.type(),
            pos_in_viewport,
            event.globalPosition().toPoint(),
            event.button(),
            event.buttons(),
            event.modifiers()
        )
        QCoreApplication.sendEvent(viewport, fake_event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QMouseEvent
        viewport = self.list_widget.viewport()
        pos_in_viewport = viewport.mapFromGlobal(event.globalPosition().toPoint())
        fake_event = QMouseEvent(
            event.type(),
            pos_in_viewport,
            event.globalPosition().toPoint(),
            event.button(),
            event.buttons(),
            event.modifiers()
        )
        QCoreApplication.sendEvent(viewport, fake_event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QMouseEvent
        viewport = self.list_widget.viewport()
        pos_in_viewport = viewport.mapFromGlobal(event.globalPosition().toPoint())
        fake_event = QMouseEvent(
            event.type(),
            pos_in_viewport,
            event.globalPosition().toPoint(),
            event.button(),
            event.buttons(),
            event.modifiers()
        )
        QCoreApplication.sendEvent(viewport, fake_event)
        super().mouseReleaseEvent(event)


class PresetPreviewButton(QPushButton):
    """Compact preset card that previews the actual caption treatment."""

    def __init__(self, name, preset, parent=None):
        super().__init__(name,parent); self.name = name; self.preset = preset
        self.setCheckable(True); self.setMinimumHeight(58); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name}｜文字 {preset['text']}｜强调 {preset['highlight']}")

    def paintEvent(self, _event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background = QColor("#1E293B" if self.underMouse() else "#111827")
        if self.isChecked(): background = QColor("#172554")
        painter.setPen(QPen(QColor("#38BDF8" if self.isChecked() else "#334155"), 2 if self.isChecked() else 1))
        painter.setBrush(background); painter.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),6,6)
        painter.fillRect(2,7,6,max(10,self.height()-14),QColor(self.preset["highlight"]))
        name_font = QFont(self.font()); name_font.setPixelSize(11); name_font.setBold(False); painter.setFont(name_font)
        painter.setPen(QColor("#CBD5E1")); painter.drawText(QRectF(14,4,self.width()-20,18),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,self.name)
        sample = "字幕样式"; font = QFont(self.preset.get("font","Arial")); font.setPixelSize(17); font.setBold(True)
        painter.setFont(font); metrics=QFontMetricsF(font); width=metrics.horizontalAdvance(sample); x=14; baseline=48
        effect=self.preset.get("effect","word_color"); text_color=QColor(self.preset["text"]); highlight=QColor(self.preset["highlight"]); outline=QColor(self.preset["outline"])
        if effect in ("descript","heygen","highlight"):
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(highlight); painter.drawRoundedRect(QRectF(x-3,27,width+8,24),5,5)
            painter.setPen(text_color); painter.drawText(x,baseline,sample)
        elif effect == "underline":
            painter.setPen(text_color); painter.drawText(x,baseline,sample); painter.setPen(QPen(highlight,3)); painter.drawLine(int(x),52,int(x+width),52)
        elif effect in ("outline","glow"):
            path=QPainterPath(); path.addText(x,baseline,font,sample)
            if effect == "glow": painter.setPen(QPen(highlight,7)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
            painter.setPen(QPen(outline,max(2,int(self.preset.get("outline_width",3))))); painter.setBrush(text_color); painter.drawPath(path)
        elif effect == "word_color":
            painter.setPen(text_color); painter.drawText(x,baseline,"字幕"); x2=x+metrics.horizontalAdvance("字幕")
            painter.setPen(highlight); painter.drawText(x2,baseline,"样式")
        else:
            painter.setPen(highlight); painter.drawText(x,baseline,sample)
        painter.end()


def ass_color(hex_color, alpha="00"):
    value = QColor(hex_color)
    return f"&H{alpha}{value.blue():02X}{value.green():02X}{value.red():02X}"


def ass_time(seconds):
    seconds = max(0.0, float(seconds)); hours = int(seconds // 3600); seconds -= hours * 3600
    minutes = int(seconds // 60); seconds -= minutes * 60
    return f"{hours}:{minutes:02d}:{seconds:05.2f}"


def parse_srt(srt):
    blocks = re.split(r"\r?\n\s*\r?\n", srt.strip())
    result = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0: continue
        match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[timing_index])
        if not match: continue
        raw_values = match.groups(); values = [int(value) for value in raw_values]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / (10 ** len(raw_values[3]))
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / (10 ** len(raw_values[7]))
        # 保留用户手动换行；自由整段字幕需要按输入排版显示全部行。
        text = normalize_required_capitalization("\n".join(lines[timing_index + 1:]).strip())
        if text: result.append((start, max(start + .1, end), text))
    return result


def fix_srt_overlaps(srt, gap_ms=20, min_duration_ms=80):
    """Fix adjacent SRT overlaps without touching caption text or word timing caches."""
    entries=parse_srt(srt)
    if len(entries) < 2: return srt,0
    entries=[list(item) for item in sorted(entries,key=lambda item:(item[0],item[1]))]
    gap=max(0,int(gap_ms))/1000; minimum=max(20,int(min_duration_ms))/1000
    fixed=0
    for index in range(1,len(entries)):
        previous=entries[index-1]; current=entries[index]
        if current[0] >= previous[1]: continue
        # Subtitle Edit style: normally shorten the previous cue to just before
        # the next cue.  Only move the next start when the previous cue would
        # otherwise become too short to display.
        candidate=current[0]-gap
        if candidate >= previous[0]+minimum:
            previous[1]=candidate
        else:
            previous[1]=previous[0]+minimum
            current[0]=previous[1]+gap
            current[1]=max(current[1],current[0]+minimum)
        fixed+=1
    if not fixed: return srt,0

    def stamp(value):
        milliseconds=max(0,round(float(value)*1000)); hours,remainder=divmod(milliseconds,3600000)
        minutes,remainder=divmod(remainder,60000); seconds,millis=divmod(remainder,1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    blocks=[f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}"
            for index,(start,end,text) in enumerate(entries,1)]
    return "\n\n".join(blocks)+"\n",fixed


def group_word_srt(srt, max_chars=36, max_duration=4.6, max_words=8, return_fix_count=False):
    """把词级时间轴合并成便于阅读/编辑的逐句 SRT，保留首尾真实时间。"""
    words = parse_srt(srt)
    if not words: return (srt,0) if return_fix_count else srt
    # 已经是正常句级字幕时不重复合并。
    if len(words) <= 2 or sum(len(tokens_for(text)) for _,_,text in words) > len(words) * 2:
        fixed,count=fix_srt_overlaps(srt)
        return (fixed,count) if return_fix_count else fixed
    phrases=[]; current=[]; start=None; end=None

    def flush():
        nonlocal current, start, end
        if current:
            phrases.append((start or 0, end or (start or 0) + .4, " ".join(current)))
        current=[]; start=end=None

    for w_start,w_end,text in words:
        pause = 0 if end is None else max(0, w_start - end)
        candidate=(" ".join(current+[text])).strip()
        # 长停顿、过长句子和行宽溢出时，在当前词之前切句；避免只显示单个词。
        if current and ((pause >= .52 and len(current) >= 2) or len(candidate) > max_chars
                        or len(current) >= max_words or (w_end - (start or w_start)) > max_duration):
            flush()
        if start is None: start=w_start
        current.append(text); end=w_end
        sentence_end=bool(re.search(r"[.!?。！？…][\"'”’)]?$",text))
        if sentence_end and len(current) >= 2:
            flush()
    flush()
    blocks=[]
    for index,(start,end,text) in enumerate(phrases,1):
        def stamp(value):
            ms=max(0,round(value*1000)); h,rem=divmod(ms,3600000); m,rem=divmod(rem,60000); sec,milli=divmod(rem,1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{milli:03d}"
        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}")
    fixed,count=fix_srt_overlaps("\n\n".join(blocks)+"\n")
    return (fixed,count) if return_fix_count else fixed


def media_duration(ffmpeg, path, fallback=8.0):
    """读取媒体时长；失败时返回用于预览的安全默认值。"""
    ffmpeg_path = Path(ffmpeg)
    ffprobe = ffmpeg_path.with_name("ffprobe" + ffmpeg_path.suffix)
    try:
        result = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            **hidden_kwargs())
        value = float(result.stdout.strip())
        return value if value > .05 else fallback
    except Exception:
        return fallback


def media_has_audio(ffmpeg, path):
    """Return whether the first audio stream exists without decoding the media."""
    ffmpeg_path = Path(ffmpeg)
    ffprobe = ffmpeg_path.with_name("ffprobe" + ffmpeg_path.suffix)
    try:
        result = subprocess.run(
            [str(ffprobe), "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **hidden_kwargs())
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def added_audio_fade_filters(mode="直接加入（无淡入淡出）", fade_in_ms=500,
                             fade_out_ms=500, duration=0):
    """Return FFmpeg filters for the matched external track only."""
    filters=[]; duration=max(0.0,float(duration or 0))
    fade_in=max(0.0,int(fade_in_ms or 0)/1000)
    fade_out=max(0.0,int(fade_out_ms or 0)/1000)
    if mode in ("仅淡入","淡入＋淡出") and fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={min(fade_in,duration or fade_in):.3f}")
    if mode in ("仅淡出","淡入＋淡出") and fade_out > 0 and duration > 0:
        actual=min(fade_out,duration)
        filters.append(f"afade=t=out:st={max(0.0,duration-actual):.3f}:d={actual:.3f}")
    return filters


def mixed_audio_filter(original_volume=100, background_volume=25,
                       fade_mode="直接加入（无淡入淡出）", fade_in_ms=500,
                       fade_out_ms=500, duration=0):
    """Shared FFmpeg graph used by exact preview and final export."""
    original = max(0, min(200, int(original_volume))) / 100
    background = max(0, min(200, int(background_volume))) / 100
    background_filters=["aresample=48000","aformat=channel_layouts=stereo",f"volume={background:.3f}"]
    background_filters.extend(added_audio_fade_filters(
        fade_mode,fade_in_ms,fade_out_ms,duration))
    return (
        f"[0:a:0]aresample=48000,aformat=channel_layouts=stereo,volume={original:.3f}[original_audio];"
        f"[1:a:0]{','.join(background_filters)}[background_audio];"
        "[original_audio][background_audio]amix=inputs=2:duration=longest:"
        "dropout_transition=2:normalize=0[aout]"
    )


def replacement_audio_filter(fade_mode="直接加入（无淡入淡出）", fade_in_ms=500,
                             fade_out_ms=500, duration=0):
    """Pad a replacement track with silence; -shortest then keeps video length."""
    filters=["aresample=48000","aformat=channel_layouts=stereo"]
    filters.extend(added_audio_fade_filters(fade_mode,fade_in_ms,fade_out_ms,duration))
    filters.append("apad=pad_dur=86400")
    return f"[1:a:0]{','.join(filters)}[aout]"


def media_video_size(ffmpeg, path, fallback=(1080,1920)):
    ffmpeg_path=Path(ffmpeg); ffprobe=ffmpeg_path.with_name("ffprobe"+ffmpeg_path.suffix)
    try:
        result=subprocess.run([str(ffprobe),"-v","error","-select_streams","v:0","-show_entries",
                               "stream=width,height:stream_side_data=rotation","-of","json",str(path)],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",**hidden_kwargs())
        stream=(json.loads(result.stdout or "{}").get("streams") or [{}])[0]
        width=int(stream.get("width") or fallback[0]); height=int(stream.get("height") or fallback[1])
        side_data=stream.get("side_data_list") or []
        rotation=next((int(item.get("rotation",0)) for item in side_data if "rotation" in item),0)
        if abs(rotation)%180==90: width,height=height,width
        return max(2,width),max(2,height)
    except Exception:
        return fallback


def prepared_fullframe_watermark(ffmpeg, video, watermark, cache_dir, opacity=90):
    """Pre-scale and apply opacity once so FFmpeg only overlays a static exact-size frame."""
    source=Path(watermark); width,height=media_video_size(ffmpeg,video)
    stat=source.stat(); fingerprint=hashlib.sha256(
        f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{width}x{height}|{opacity}".encode("utf-8")
    ).hexdigest()[:18]
    cache=Path(cache_dir)/".watermark_cache"; cache.mkdir(parents=True,exist_ok=True)
    destination=cache/f"wm_{fingerprint}_{width}x{height}.png"
    if destination.exists() and destination.stat().st_size>256: return destination
    image=QImage(str(source))
    if image.isNull(): raise RuntimeError(f"无法读取公司水印：{source}")
    scaled=image.scaled(width,height,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    canvas=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); canvas.fill(Qt.GlobalColor.transparent)
    painter=QPainter(canvas); painter.setOpacity(max(5,min(100,int(opacity)))/100); painter.drawImage(0,0,scaled); painter.end()
    if not canvas.save(str(destination),"PNG"): raise RuntimeError("无法生成公司水印加速缓存")
    return destination


def prepared_watermark_stack(paths, cache_dir):
    """Combine several transparent images into one reusable overlay."""
    sources=[Path(path) for path in paths if Path(path).is_file()]
    if not sources: return Path("")
    if len(sources)==1: return sources[0]
    images=[]; signatures=[]
    for source in sources:
        image=QImage(str(source))
        if image.isNull(): continue
        stat=source.stat(); signatures.append(f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"); images.append(image)
    if not images: return Path("")
    cache=Path(cache_dir)/".watermark_cache"; cache.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256("\n".join(signatures).encode("utf-8")).hexdigest()[:18]
    destination=cache/f"wm_stack_{fingerprint}.png"
    if destination.exists() and destination.stat().st_size>256: return destination
    width=max(image.width() for image in images); height=max(image.height() for image in images)
    canvas=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); canvas.fill(Qt.GlobalColor.transparent)
    painter=QPainter(canvas)
    for image in images: painter.drawImage((width-image.width())//2,(height-image.height())//2,image)
    painter.end()
    if not canvas.save(str(destination),"PNG"): raise RuntimeError("无法生成多图片水印缓存")
    return destination


def prepared_watermark_composite(ffmpeg,video,watermarks,cache_dir):
    """Render independently positioned watermark layers into one exact-size transparent frame."""
    entries=[dict(item) for item in watermarks if Path(str(item.get("path",""))).is_file()]
    if not entries: return Path("")
    width,height=media_video_size(ffmpeg,video); signatures=[]
    for item in entries:
        source=Path(item["path"]); stat=source.stat()
        signatures.append({"path":str(source.resolve()),"size":stat.st_size,"mtime":stat.st_mtime_ns,
                           "mode":item.get("mode"),"position":item.get("position"),"width":item.get("width"),
                           "opacity":item.get("opacity"),"margin":item.get("margin")})
    fingerprint=hashlib.sha256(json.dumps(signatures,ensure_ascii=False,sort_keys=True).encode("utf-8")).hexdigest()[:18]
    cache=Path(cache_dir)/".watermark_cache"; cache.mkdir(parents=True,exist_ok=True)
    destination=cache/f"wm_layers_{fingerprint}_{width}x{height}.png"
    if destination.exists() and destination.stat().st_size>256: return destination
    canvas=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); canvas.fill(Qt.GlobalColor.transparent)
    painter=QPainter(canvas); painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
    for item in entries:
        source=QImage(str(item["path"]))
        if source.isNull(): continue
        painter.save(); painter.setOpacity(max(5,min(100,int(item.get("opacity",100))))/100)
        if item.get("mode","9:16 全屏覆盖")=="9:16 全屏覆盖":
            image=source.scaled(width,height,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation); x=y=0
        else:
            target_width=max(1,round(width*max(3,min(100,int(item.get("width",18))))/100))
            image=source.scaledToWidth(target_width,Qt.TransformationMode.SmoothTransformation)
            margin=max(0,int(item.get("margin",28))); target_height=image.height(); position=item.get("position","右上角")
            positions={"左上角":(margin,margin),"右上角":(width-target_width-margin,margin),
                       "左下角":(margin,height-target_height-margin),"右下角":(width-target_width-margin,height-target_height-margin),
                       "画面中间":((width-target_width)//2,(height-target_height)//2)}
            x,y=positions.get(position,positions["右上角"])
        painter.drawImage(int(x),int(y),image); painter.restore()
    painter.end()
    if not canvas.save(str(destination),"PNG"): raise RuntimeError("无法生成多图层水印缓存")
    return destination


def watermark_config_fingerprint(watermarks):
    """Stable identity for the exact watermark files and per-layer geometry."""
    payload=[]
    for item in watermarks or []:
        candidate=Path(str(item.get("path","")))
        if not candidate.is_file(): continue
        stat=candidate.stat()
        payload.append({"path":str(candidate.resolve()),"size":stat.st_size,"mtime":stat.st_mtime_ns,
                        "mode":item.get("mode"),"position":item.get("position"),"width":item.get("width"),
                        "opacity":item.get("opacity"),"margin":item.get("margin")})
    if not payload: return ""
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode("utf-8")).hexdigest()


def short_media_id(path):
    """Short, stable name for FFmpeg/libass intermediate files on Windows."""
    return hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:16]


def bounded_output_path(directory, stem, suffix, max_path=230):
    """Preserve descriptive output names while staying below legacy media-library limits."""
    directory = Path(directory)
    candidate = directory / f"{stem}{suffix}"
    if len(str(candidate.resolve())) <= max_path:
        return candidate
    digest = hashlib.sha256(str(stem).encode("utf-8")).hexdigest()[:10]
    available = max(24, max_path - len(str(directory.resolve())) - len(suffix) - len(digest) - 3)
    return directory / f"{str(stem)[:available]}_{digest}{suffix}"


def _media_signature(path):
    path = Path(path); stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime": stat.st_mtime_ns}


def _timeline_cache_path(output, source):
    key = hashlib.sha256(json.dumps(_media_signature(source), sort_keys=True).encode("utf-8")).hexdigest()[:20]
    return Path(output) / ".reels_timeline_cache" / f"{key}.srt"


def _load_timeline_cache(output, source):
    try:
        path = _timeline_cache_path(output, source)
        return path.read_text(encoding="utf-8-sig") if path.exists() and path.stat().st_size else ""
    except Exception:
        return ""


def _save_timeline_cache(output, source, srt):
    path = _timeline_cache_path(output, source); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp"); temporary.write_text(str(srt or ""), encoding="utf-8-sig"); temporary.replace(path)
    return path


def _render_fingerprint(video, audio, settings):
    watermark_files=[]
    for item in settings.get("watermarks", []) or []:
        candidate=Path(str(item.get("path", "")))
        if candidate.is_file(): watermark_files.append(_media_signature(candidate))
    font_assets=[]
    for candidate in sorted(render_font_dir().glob("*"),key=lambda path:path.name.casefold()):
        if candidate.is_file() and candidate.suffix.casefold() in (".ttf",".otf",".ttc"):
            stat=candidate.stat()
            font_assets.append({"name":candidate.name,"size":stat.st_size,"mtime":stat.st_mtime_ns})
    payload={"video":_media_signature(video),"audio":_media_signature(audio),"settings":settings,
             "watermarks":watermark_files,"font_assets":font_assets,
             "caption_renderer_version":CAPTION_RENDERER_VERSION}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode("utf-8")).hexdigest()


def _read_reels_checkpoint(output):
    path=Path(output)/"reels_checkpoint.json"
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception: return {}


def _write_reels_checkpoint(output,state):
    path=Path(output)/"reels_checkpoint.json"; path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(".tmp"); temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2,default=str),encoding="utf-8"); temporary.replace(path)


def free_caption_srt(text, duration, settings):
    """把不需要对口型的自由文案按两行一屏生成时间轴。"""
    value = normalize_required_capitalization(str(text or "").strip())
    if not value:
        return ""
    if "-->" in value:
        return value
    if settings.get("free_animation") == "整段固定":
        available = max(.5, float(duration))
        milliseconds = round(available * 1000)
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        return (f"1\n00:00:00,000 --> {hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}\n"
                f"{value}\n")
    max_chars = max(6, int(settings.get("line_length", 18)))
    tokens = tokens_for(re.sub(r"\s+", " ", value))
    separator = "" if re.search(r"[\u3400-\u9fff]", value) else " "
    lines = []; current = []
    for token in tokens:
        candidate = separator.join(current + [token])
        if current and len(candidate) > max_chars:
            lines.append(separator.join(current)); current = [token]
        else:
            current.append(token)
    if current:
        lines.append(separator.join(current))
    pages = ["\n".join(lines[index:index + 2]) for index in range(0, len(lines), 2)]
    if not pages:
        return ""
    requested = max(.5, float(settings.get("free_page_seconds", 3.0)))
    available = max(.5, float(duration))
    page_seconds = min(requested, available / len(pages)) if requested * len(pages) > available else requested
    segments = []
    for index, page in enumerate(pages):
        start = index * page_seconds
        if start >= available:
            break
        end = min(available, start + page_seconds)
        segments.append({"start": start, "end": max(start + .2, end), "text": page})
    blocks=[]
    for index,item in enumerate(segments,1):
        def stamp(value):
            ms=max(0,round(value*1000)); h,rem=divmod(ms,3600000); m,rem=divmod(rem,60000); sec,milli=divmod(rem,1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{milli:03d}"
        blocks.append(f"{index}\n{stamp(item['start'])} --> {stamp(item['end'])}\n{item['text']}")
    return "\n\n".join(blocks) + "\n"


def tokens_for(text):
    if re.search(r"[\u3400-\u9fff]", text):
        return [char for char in text if not char.isspace()]
    return re.findall(r"\S+", text)


def replace_srt_copy(srt, copy_text):
    events = parse_srt(srt)
    if not events or not copy_text.strip(): return srt
    chunks = [value.strip() for value in re.split(r"(?<=[。！？.!?])\s*|\r?\n+", copy_text) if value.strip()]
    if not chunks: chunks = [copy_text.strip()]
    if len(chunks) != len(events):
        units = tokens_for(copy_text)
        if units:
            per = max(1, (len(units) + len(events) - 1) // len(events))
            separator = "" if re.search(r"[\u3400-\u9fff]", copy_text) else " "
            chunks = [separator.join(units[i:i + per]) for i in range(0, len(units), per)]
    result = []
    for index, (start, end, old_text) in enumerate(events, 1):
        text = chunks[index - 1] if index - 1 < len(chunks) else old_text
        def stamp(value):
            h=int(value//3600); value-=h*3600; m=int(value//60); value-=m*60
            return f"{h:02d}:{m:02d}:{int(value):02d},{int((value-int(value))*1000):03d}"
        result.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    return "\n".join(result)


def wrap_caption(text, limit):
    if re.search(r"[\u3400-\u9fff]", text):
        chars = [char for char in text if not char.isspace()]
        return r"\N".join("".join(chars[i:i + limit]) for i in range(0, len(chars), limit))
    words = text.split(); lines, current = [], []
    for word in words:
        if current and len(" ".join(current + [word])) > limit:
            lines.append(" ".join(current)); current = [word]
        else: current.append(word)
    if current: lines.append(" ".join(current))
    return r"\N".join(lines)


def rounded_rect_path(width, height, radius):
    """生成 libass 可直接填充的圆角矩形矢量路径。"""
    width=max(2,int(round(width))); height=max(2,int(round(height)))
    radius=max(0,min(int(round(radius)),width//2,height//2))
    if radius == 0: return f"m 0 0 l {width} 0 {width} {height} 0 {height}"
    # 三次贝塞尔控制点使用 0.552 的圆弧近似。
    k=max(1,int(round(radius*.552))); w=width; h=height; r=radius
    return (f"m {r} 0 l {w-r} 0 b {w-r+k} 0 {w} {r-k} {w} {r} "
            f"l {w} {h-r} b {w} {h-r+k} {w-r+k} {h} {w-r} {h} "
            f"l {r} {h} b {r-k} {h} 0 {h-r+k} 0 {h-r} "
            f"l 0 {r} b 0 {r-k} {r-k} 0 {r} 0")


def watermark_filter_graph(ass_filter, settings, watermark_input_index):
    """Build one filter graph so preview and final export use the same watermark geometry."""
    ass_expression=ass_filter_expression(ass_filter,settings)
    opacity = max(5, min(100, int(settings.get("watermark_opacity", 90)))) / 100
    mode = settings.get("watermark_mode", "9:16 全屏覆盖")
    if mode == "9:16 全屏覆盖" and settings.get("watermark_prepared"):
        return (f"[0:v]{ass_expression}[captioned];"
                f"[{watermark_input_index}:v]format=rgba[wm];"
                "[captioned][wm]overlay=0:0:eof_action=repeat[outv]")
    prefix = (
        f"[0:v]{ass_expression}[captioned];"
        f"[{watermark_input_index}:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[wm_alpha];"
    )
    if mode == "9:16 全屏覆盖":
        return (
            prefix + "[wm_alpha][captioned]scale2ref=w=main_w:h=main_h[wm][base];"
            "[base][wm]overlay=0:0:eof_action=repeat[outv]"
        )
    width = max(3, min(60, int(settings.get("watermark_width", 18)))) / 100
    margin = max(0, min(300, int(settings.get("watermark_margin", 28))))
    position = settings.get("watermark_position", "右上角")
    positions = {
        "左上角": (str(margin), str(margin)),
        "右上角": (f"W-w-{margin}", str(margin)),
        "左下角": (str(margin), f"H-h-{margin}"),
        "右下角": (f"W-w-{margin}", f"H-h-{margin}"),
        "画面中间": ("(W-w)/2", "(H-h)/2"),
    }
    x, y = positions.get(position, positions["右上角"])
    return (
        prefix +
        f"[wm_alpha][captioned]scale2ref=w=main_w*{width:.4f}:h=ow/mdar[wm][base];"
        f"[base][wm]overlay={x}:{y}:eof_action=repeat[outv]"
    )


def ass_filter_expression(ass_filter,settings):
    expression=f"ass=filename='{escape_ffmpeg_filter_path(ass_filter)}'"
    folder=render_font_dir()
    if folder.is_dir():
        expression+=f":fontsdir='{escape_ffmpeg_filter_path(folder)}'"
    return expression


def escape_ffmpeg_filter_path(path):
    """Escape a filename embedded in an FFmpeg filter option.

    ASS paths are filter syntax, not normal command-line arguments.  Commas,
    brackets and colons in a user folder can otherwise be parsed as filters.
    """
    value=str(path).replace("\\","/")
    for source,target in (("\\",r"\\"),("'",r"\'"),(":",r"\:"),
                          (",",r"\,"),(";",r"\;"),("[",r"\["),("]",r"\]")):
        value=value.replace(source,target)
    return value


def temporary_ass_path(prefix="caption"):
    """Create a short ASCII-only ASS path outside user-selected directories."""
    folder=Path(tempfile.gettempdir())/"video_toolkit_ass"
    folder.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix=f"{prefix}_",suffix=".ass",dir=folder)
    os.close(descriptor)
    return Path(name)


def caption_layout_context(settings):
    """Canonical 1080x1920 caption metrics shared by live preview and ASS."""
    font=QFont(str(settings.get("font","Arial")))
    font.setPixelSize(max(1,int(settings.get("font_size",76))))
    font.setBold(caption_uses_bold_face(settings))
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,float(settings.get("letter_spacing",0)))
    metrics=QFontMetricsF(font)
    font_size=max(1,int(settings.get("font_size",76)))
    # Word spacing is independent from glyph/letter spacing.  Negative values
    # intentionally remain negative so the control still changes the final
    # geometry after the natural space has reached zero.
    gap=max(-font_size*1.25,metrics.horizontalAdvance(" ")+float(settings.get("word_spacing",0)))
    line_gap=max(font_size,metrics.height())*max(70,min(180,int(settings.get("line_spacing",116))))/100
    max_width=1080*max(40,min(96,int(settings.get("line_width",86))))/100
    return font,metrics,gap,line_gap,max_width


def caption_uses_bold_face(settings):
    # Caption presets are designed as bold treatments. Qt and libass both use
    # weight 700 here; static Bold files are preferred, while variable fonts
    # can still provide/synthesise the same weight until upgraded.
    family=str(settings.get("font",""))
    static_name=STATIC_BOLD_FONT_FILES.get(family)
    if static_name:
        # Old releases downloaded variable/regular files.  On Windows libass
        # resolves those as Regular even when ASS requests weight 700.  Until a
        # static Bold face is present, use Regular in both Qt and libass rather
        # than previewing one face and exporting another.
        return any((folder/static_name).is_file() for folder in (custom_font_dir(),bundled_font_dir()))
    return True


def caption_wrapped_lines(text,settings,fixed_all=False,context=None):
    context=context or caption_layout_context(settings); _font,metrics,gap,_line_gap,max_width=context
    if fixed_all and "\n" in text:
        return [tokens_for(line) for line in text.splitlines() if tokens_for(line)]
    lines=[]; current=[]
    for token in tokens_for(text):
        candidate=" ".join(current+[token])
        width=sum(metrics.horizontalAdvance(value) for value in current+[token])+gap*len(current)
        if current and (len(candidate)>int(settings.get("line_length",18)) or width>max_width):
            lines.append(current); current=[token]
        else:
            current.append(token)
    if current: lines.append(current)
    return lines


def caption_page_geometry(lines,settings,context=None):
    """Return stable token centers/baselines in the common 1080x1920 canvas."""
    context=context or caption_layout_context(settings); _font,metrics,gap,line_gap,_max_width=context
    position=settings.get("position","底部")
    if position=="顶部": center_y=float(settings.get("margin_v",250))+line_gap*(len(lines)-1)/2
    elif position=="画面中间": center_y=960.0
    else: center_y=1920-float(settings.get("margin_v",250))-line_gap*(len(lines)-1)/2
    result=[]
    for line_index,tokens in enumerate(lines):
        widths=[max(float(settings.get("font_size",76))*.55,metrics.horizontalAdvance(token)) for token in tokens]
        total=sum(widths)+gap*max(0,len(widths)-1); cursor=(1080-total)/2
        y=center_y+(line_index-(len(lines)-1)/2)*line_gap
        baseline=y+metrics.ascent()/2-metrics.descent()/2
        items=[]
        for token,width in zip(tokens,widths):
            items.append({"token":token,"left":cursor,"width":width,"x":cursor+width/2,
                          "y":y,"baseline":baseline})
            cursor+=width+gap
        result.append(items)
    return result


def write_ass(path, srt, settings, word_srt=""):
    preset = PRESETS[settings["preset"]]
    text_color = ass_color(settings["text_color"])
    outline_color = ass_color(settings["outline_color"])
    highlight = ass_color(settings["highlight_color"])
    # Use the face Qt actually selected for live preview.  If a requested font
    # is missing or has a different internal family name, libass now receives
    # the same resolved family instead of choosing an unrelated fallback.
    metric_font=caption_layout_context(settings)[0]
    font = QFontInfo(metric_font).family().replace(",", "")
    alignment = {"底部": 2, "画面中间": 5, "顶部": 8}.get(settings.get("position", "底部"), 2)
    bold_flag=-1 if caption_uses_bold_face(settings) else 0
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{font},{settings['font_size']},{text_color},{text_color},{outline_color},&H90000000,{bold_flag},0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,{settings['outline_width']},2,{alignment},40,40,{settings['margin_v']},1
Style: Active,{font},{settings['font_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{bold_flag},0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,0,0,{alignment},40,40,{settings['margin_v']},1
Style: ActiveColor,{font},{settings['font_size']},{highlight},{highlight},{outline_color},&H90000000,{bold_flag},0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,{settings['outline_width']},2,{alignment},40,40,{settings['margin_v']},1
Style: HighlightBox,{font},{settings['font_size']},{highlight},{highlight},{highlight},{highlight},{bold_flag},0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    # UI 中图层由上到下排列；ASS 的 Layer 数字越大越靠上。
    ui_layers = settings.get("layers") or [{"type": "caption", "name": "字幕层"}]
    render_layers = list(reversed(ui_layers))
    caption_layer = next((index * 10 for index, layer in enumerate(render_layers)
                          if layer.get("type") == "caption"), 0)
    for index, layer in enumerate(render_layers):
        if not layer.get("enabled", True):
            continue
        if layer.get("type") == "mask":
            x = 1080 * float(layer.get("x", 10)) / 100
            y = 1920 * float(layer.get("y", 66)) / 100
            width = 1080 * float(layer.get("w", 80)) / 100
            height = 1920 * float(layer.get("h", 15)) / 100
            opacity = max(0, min(100, int(layer.get("opacity", 55))))
            alpha = f"{round(255 * (1 - opacity / 100)):02X}"
            color = ass_color(layer.get("color", "#000000"))
            radius_percent = max(0, min(100, int(layer.get("radius", 35))))
            mask_path = rounded_rect_path(width, height, min(width, height) * .5 * radius_percent / 100)
            mask_override = fr"{{\an7\pos({x:.1f},{y:.1f})\p1\1c{color}\1a&H{alpha}&\bord0\shad0}}"
            events.append(
                f"Dialogue: {index * 10},0:00:00.00,9:59:59.00,HighlightBox,,0,0,0,,"
                f"{mask_override}{mask_path}"
            )
        elif layer.get("type") == "text" and str(layer.get("text", "")).strip():
            x = 1080 * float(layer.get("x", 50)) / 100; y = 1920 * float(layer.get("y", 18)) / 100
            opacity = max(0, min(100, int(layer.get("opacity", 100))))
            alpha = f"{round(255 * (1 - opacity / 100)):02X}"
            layer_font = str(layer.get("font", font)).replace(",", "")
            layer_size = max(12, min(220, int(layer.get("size", 58))))
            color = ass_color(layer.get("color", "#FFFFFF")); outline = ass_color(layer.get("outline", "#111111"))
            outline_width = max(0, min(12, int(layer.get("outline_width", 2))))
            safe_text = str(layer.get("text", "")).replace("{", "（").replace("}", "）").replace("\n", r"\N")
            override = (fr"{{\an5\pos({x:.1f},{y:.1f})\fn{layer_font}\fs{layer_size}"
                        fr"\1c{color}\3c{outline}\bord{outline_width}\shad0\alpha&H{alpha}&}}")
            events.append(f"Dialogue: {index * 10},0:00:00.00,9:59:59.00,Base,,0,0,0,,{override}{safe_text}")
    precise_words = parse_srt(word_srt)
    font_size = settings["font_size"]
    layout_context=caption_layout_context(settings)
    _metric_font,metrics,word_gap,line_gap,max_line_width=layout_context
    padding_x = int(settings.get("highlight_padding", max(12, font_size * .2)))
    padding_y = max(0, int(settings.get("highlight_padding_y", max(7, font_size * .11))))
    animation_ms = int(settings.get("animation_speed", 150))
    position = settings.get("position", "底部")
    free_mode = settings.get("caption_mode") == "自由文案动画（不对口型）"
    free_animation = settings.get("free_animation", "淡入淡出")
    for start, end, text in parse_srt(srt):
        safe = text.replace("{", "（").replace("}", "）")
        tokens = tokens_for(safe)
        if not tokens: continue
        effect = preset["effect"]
        fixed_all = free_mode and free_animation == "整段固定"
        # 整段固定保留手动换行，且允许任意行数；其他模式继续自动排版分页。
        lines=caption_wrapped_lines(safe,settings,fixed_all,layout_context)

        # Use the word midpoint to assign it to exactly one phrase.  Overlap
        # tolerances made boundary words appear in two adjacent phrases and
        # could produce two highlighted words at the same time.
        phrase_words=[item for item in precise_words
                      if start-.01 <= (item[0]+item[1])/2 <= end+.01]
        if len(phrase_words) >= len(tokens):
            timings=[(phrase_words[i][0],phrase_words[i][1]) for i in range(len(tokens))]
        else:
            duration=max(.08,(end-start)/len(tokens)); timings=[(start+duration*i,min(end,start+duration*(i+1))) for i in range(len(tokens))]

        # 一个画面最多两行。若排版宽度产生第三行，从该行第一个完整单词的
        # 真实时间戳开始切换到下一画面，任何情况下都不拆开单词。
        line_pages=[lines] if fixed_all else [lines[index:index+2] for index in range(0,len(lines),2)]
        token_index=0
        for page_lines in line_pages:
            page_token_count=sum(len(line) for line in page_lines)
            page_start=start if token_index == 0 else timings[token_index][0]
            next_index=token_index+page_token_count
            page_end=timings[next_index][0] if next_index < len(timings) else end
            page_end=max(page_start+.08,page_end)
            geometry=caption_page_geometry(page_lines,settings,layout_context)
            for line_index,(line_tokens,line_geometry) in enumerate(zip(page_lines,geometry)):
                for local_index,(token,item) in enumerate(zip(line_tokens,line_geometry)):
                    width=item["width"]; x=item["x"]; y=item["y"]
                    token_start,token_end=timings[token_index]; token_index+=1
                    if free_mode:
                        visible_start = page_start
                        override = fr"{{\an5\pos({x:.1f},{y:.1f})}}"
                        if free_animation == "逐字出现":
                            visible_start = token_start
                            override = (fr"{{\an5\pos({x:.1f},{y:.1f})\fscx70\fscy70"
                                        fr"\t(0,{animation_ms},\fscx100\fscy100)\fad(80,80)}}")
                        elif free_animation == "逐行出现":
                            visible_start = page_start + (page_end-page_start) * line_index / max(3,len(page_lines)+1)
                            override = fr"{{\an5\pos({x:.1f},{y:.1f})\fad(180,100)}}"
                        elif free_animation == "由下向上":
                            override = fr"{{\an5\move({x:.1f},{y+70:.1f},{x:.1f},{y:.1f},0,{max(220,animation_ms*2)})\fad(160,120)}}"
                        elif free_animation == "淡入淡出":
                            override = fr"{{\an5\pos({x:.1f},{y:.1f})\fad(320,320)}}"
                        events.append(
                            f"Dialogue: {caption_layer},{ass_time(visible_start)},{ass_time(page_end)},"
                            f"Base,,0,0,0,,{override}{token}")
                        continue
                    intro=fr"{{\an5\pos({x:.1f},{y:.1f})\fad(70,70)}}"
                    if effect == "glow": intro=fr"{{\an5\pos({x:.1f},{y:.1f})\blur3\fad(70,70)}}"
                    events.append(f"Dialogue: {caption_layer},{ass_time(page_start)},{ass_time(page_end)},Base,,0,0,0,,{intro}{token}")
                    if effect in ("outline","glow"): continue

                    active_style="Active"
                    if effect == "word_color":
                        active_style="ActiveColor"
                        active_override=fr"{{\an5\pos({x:.1f},{y:.1f})\fad(30,30)}}"
                    elif effect in ("descript","heygen","highlight"):
                        box_width=width+padding_x*2; box_height=max(font_size*1.12,metrics.height())+padding_y*2
                        box_x=x-box_width/2; box_y=y-box_height/2
                        box=rounded_rect_path(box_width,box_height,min(18,box_height*.24))
                        box_override=(fr"{{\an7\pos({box_x:.1f},{box_y:.1f})\p1\fscx92\fscy92"
                                      fr"\t(0,{animation_ms},\fscx100\fscy100)}}")
                        events.append(f"Dialogue: {caption_layer + 1},{ass_time(token_start)},{ass_time(token_end)},HighlightBox,,0,0,0,,{box_override}{box}")
                        active_override=(fr"{{\an5\pos({x:.1f},{y:.1f})\fscx92\fscy92"
                                         fr"\t(0,{animation_ms},\fscx100\fscy100)}}")
                    elif effect == "pop":
                        active_override=(fr"{{\an5\pos({x:.1f},{y:.1f})\fscx75\fscy75"
                                         fr"\t(0,{animation_ms},\fscx108\fscy108)"
                                         fr"\t({animation_ms},{animation_ms+90},\fscx100\fscy100)}}")
                    elif effect == "underline": active_override=fr"{{\an5\pos({x:.1f},{y:.1f})\u1}}"
                    else: active_override=fr"{{\an5\pos({x:.1f},{y:.1f})}}"
                    events.append(f"Dialogue: {caption_layer + 2},{ass_time(token_start)},{ass_time(token_end)},{active_style},,0,0,0,,{active_override}{token}")
    path.write_text(header + "\n".join(events), encoding="utf-8-sig")


class CaptionWorker(QObject):
    log = Signal(str); progress = Signal(int); result = Signal(str, str, str)
    timeline_ready = Signal(str, str, str); finished = Signal(bool, str)

    def __init__(self, videos, audios, output, ffmpeg, transcribe, settings):
        super().__init__(); self.videos = [Path(p) for p in videos]; self.audios = [Path(p) for p in audios]
        self.output = Path(output); self.ffmpeg = ffmpeg; self.transcribe = transcribe; self.settings = settings; self.cancelled = False
        self._current_child = None

    def cancel(self):
        self.cancelled = True
        if self._current_child: self._current_child.cancel()

    def _run_render(self, command, duration, index, total):
        """Run FFmpeg with live time-based progress instead of a frozen percentage."""
        destination = command[-1]
        command = command[:-1] + ["-progress", "pipe:1", "-nostats", destination]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1, **hidden_kwargs(),
        )
        tail = []
        for raw in process.stdout or []:
            line = raw.strip()
            if line:
                tail.append(line)
                tail = tail[-40:]
            if line.startswith("out_time_ms="):
                try:
                    rendered = int(line.split("=", 1)[1]) / 1_000_000
                    fraction = min(.98, rendered / max(.1, duration))
                    self.progress.emit(round((index + fraction) / max(1, total) * 100))
                except (TypeError, ValueError):
                    pass
            if self.cancelled and process.poll() is None:
                process.terminate()
        return process.wait(), "\n".join(tail)

    @staticmethod
    def _match_stem(path):
        value = Path(path).stem.casefold()
        # 允许“视频名_配音.mp3 / 视频名-音频.wav / 视频名_动态文案.mp4”等常见命名。
        value = re.sub(r"(?:[_\-\s]*(?:动态文案|配音|音频|audio|voice|tts|成品))+$", "", value)
        return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value)

    def _audio_selection(self, video, index):
        mode = self.settings.get("audio_match_mode", "自动匹配（同名优先，其次按队列）")
        if not self.audios or mode == "每个视频使用自身音频":
            return video, "视频自身音频"
        if mode == "随机分配并随机截取时间段":
            import random
            rnd = random.Random(hash(str(video.resolve())) + index)
            selected = rnd.choice(self.audios)
            return selected, "随机匹配背景音"
        if mode == "严格按队列一一对应":
            if index < len(self.audios):
                return self.audios[index], "队列一一对应"
            return video, "该视频没有对应的添加音频"
        video_key = self._match_stem(video)
        same = next((audio for audio in self.audios if self._match_stem(audio) == video_key), None)
        if same is not None:
            return same, "同名自动匹配"
        # Each added track may be used by only one video.  Never reuse the last
        # (or the only) audio item for the remaining batch entries.
        if index < len(self.audios):
            return self.audios[index], "队列一一对应"
        return video, "该视频没有对应的添加音频"

    def _audio_for(self, video, index):
        return self._audio_selection(video, index)[0]

    def run(self):
        """Keep a batch alive when one media item fails; only stop on explicit cancellation."""
        failures=[]; completed=0; total=len(self.videos)
        for index,video in enumerate(self.videos):
            if self.cancelled:
                self.finished.emit(False,f"任务已停止；已完成 {completed} 个，成品仍保留。")
                return
            audio,_reason=self._audio_selection(video,index)
            child_audios=[] if audio.resolve()==video.resolve() else [audio]
            child=CaptionWorker([video],child_audios,self.output,self.ffmpeg,self.transcribe,dict(self.settings))
            self._current_child=child; outcome=[]
            child.log.connect(lambda message,n=index+1,t=total:self.log.emit(f"[{n}/{t}] {message}"))
            child.progress.connect(lambda value,n=index,t=total:self.progress.emit(round((n+value/100)/max(1,t)*100)))
            child.result.connect(self.result.emit); child.timeline_ready.connect(self.timeline_ready.emit)
            child.finished.connect(lambda ok,message:outcome.append((ok,message)))
            child._run_all_failfast()
            ok,message=outcome[-1] if outcome else (False,"任务未返回结果")
            if ok: completed+=1
            else:
                failures.append(f"{video.name}：{message}")
                self.log.emit(f"[{index+1}/{total}] 当前视频失败，已记录并继续下一项：{message}")
            self.progress.emit(round((index+1)/max(1,total)*100))
        self._current_child=None
        if failures and not completed:
            self.finished.emit(False,"全部视频处理失败。"+"｜".join(failures[:5]))
        elif failures:
            self.finished.emit(True,f"批处理完成：成功 {completed} 个，失败 {len(failures)} 个；失败项已写入软件日志。\n{self.output}")
        else:
            self.finished.emit(True,f"批处理完成，共生成 {completed} 个 Reels 视频。\n{self.output}")

    def _run_all_failfast(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            checkpoint = _read_reels_checkpoint(self.output)
            completed = checkpoint.setdefault("rendered", {})
            encoder = resolve_encoder(self.ffmpeg, self.settings.get("encoder_backend", "auto"))
            self.log.emit(f"视频编码：{ENCODER_LABELS[encoder]}（自动检测，硬件不可用时使用 CPU）")
            for index, video in enumerate(self.videos):
                if self.cancelled: raise RuntimeError("任务已停止；已完成的动态文案视频仍保留。")
                self.progress.emit(round(index / max(1,len(self.videos)) * 100))
                self.log.emit(f"[{index + 1}/{len(self.videos)}] 开始处理：{video.name}")
                audio, match_reason = self._audio_selection(video, index)
                # Background music is part of the render mix, not the spoken
                # caption source.  Only replacement audio owns the dialogue;
                # keep-original and mix modes must transcribe the video's voice.
                audio_mode = self.settings.get("audio_mode", "保留视频原音")
                caption_audio = audio if audio_mode == "替换为添加的音频" else video
                self.log.emit(
                    f"[{index + 1}/{len(self.videos)}] 素材匹配：{video.name}  ←  {audio.name}（{match_reason}）"
                )
                destination = None
                fingerprint = _render_fingerprint(video, audio, self.settings)
                saved = completed.get(str(video.resolve()), {})
                if saved.get("fingerprint") == fingerprint:
                    saved_dest = saved.get("destination")
                    if saved_dest and Path(saved_dest).exists() and Path(saved_dest).stat().st_size > 1024:
                        destination = Path(saved_dest)
                        word_srt=str(saved.get("word_srt","")); phrase_srt=str(saved.get("phrase_srt",""))
                        original=str(saved.get("original","")); chinese=str(saved.get("chinese",""))
                        self.timeline_ready.emit(str(caption_audio.resolve()),word_srt,phrase_srt)
                        self.result.emit(str(destination),original,chinese)
                        self.progress.emit(round((index+1)/len(self.videos)*100))
                        self.log.emit(f"续接：素材和样式未变化，复用已完成成品 {destination.name}")
                        continue
                # 元数据在最终成品的同一条 FFmpeg 命令中清除。不再先生成
                # `00_无元数据素材` 副本，避免额外占用空间和一次完整读写。
                render_video = video
                source_key = str(caption_audio.resolve())
                if self.settings.get("caption_mode") == "自由文案动画（不对口型）":
                    video_key = str(video.resolve())
                    copy_text = str(self.settings.get("free_texts", {}).get(video_key, "")).strip()
                    if not copy_text:
                        raise RuntimeError(f"自由文案模式下，视频尚未填写字幕：{video.name}")
                    phrase_srt = free_caption_srt(copy_text, media_duration(self.ffmpeg, render_video), self.settings)
                    word_srt = ""; original = copy_text; chinese = ""
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 使用自由文案动画，不执行语音识别：{video.name}")
                else:
                    saved_word_srt = str(self.settings.get("word_timelines", {}).get(source_key, "")).strip()
                    sidecar = caption_audio.with_suffix(".srt")
                    if saved_word_srt:
                        srt = saved_word_srt
                        original = " ".join(text for _,_,text in parse_srt(srt))
                        chinese = str(self.settings.get("timeline_chinese", {}).get(source_key, "")).strip()
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 复用已提取的词级时间轴：{caption_audio.name}")
                    elif sidecar.exists() and sidecar.stat().st_size:
                        srt = sidecar.read_text(encoding="utf-8-sig")
                        original = " ".join(text for _, _, text in parse_srt(srt))
                        chinese = str(self.settings.get("timeline_chinese", {}).get(source_key, "")).strip()
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 使用配音的真实词级时间轴：{sidecar.name}")
                    elif _load_timeline_cache(self.output,caption_audio):
                        srt=_load_timeline_cache(self.output,caption_audio)
                        original=" ".join(text for _,_,text in parse_srt(srt))
                        chinese = str(self.settings.get("timeline_chinese", {}).get(source_key, "")).strip()
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 断点续接：复用已提取字幕 {caption_audio.name}")
                    else:
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 从对白音轨提取词级时间轴：{caption_audio.name}")
                        original, chinese, srt = self.transcribe(str(caption_audio))
                        if str(srt or "").strip(): _save_timeline_cache(self.output,caption_audio,srt)
                    if not srt.strip(): raise RuntimeError(f"未识别到有效字幕：{caption_audio.name}")
                    word_srt = srt
                    phrase_srt = group_word_srt(word_srt, self.settings["line_length"] * 2,
                                                max_words=self.settings.get("max_words", 8))
                    override = str(self.settings.get("timeline_overrides", {}).get(str(caption_audio.resolve()), "")).strip()
                    if override:
                        if "-->" in override:
                            phrase_srt = override
                            self.log.emit("已应用人工修订后的逐句 SRT，逐词时间轴继续驱动高亮。")
                        else:
                            phrase_srt = replace_srt_copy(phrase_srt, override)
                            self.log.emit("已应用人工修订文案，并保留词级时间轴。")
                phrase_srt,overlap_fixes=fix_srt_overlaps(phrase_srt)
                if overlap_fixes:
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 渲染前自动修正 {overlap_fixes} 处逐句字幕时间重叠。")
                self.timeline_ready.emit(source_key, word_srt, phrase_srt)
                if self.settings.get("rename_enabled"):
                    rename_prefix = self.settings.get("rename_prefix", "").strip()
                    rename_suffix_enabled = self.settings.get("rename_suffix_enabled", True)
                    rename_suffix = self.settings.get("rename_suffix", "").strip() if rename_suffix_enabled else ""
                    rename_date_enabled = self.settings.get("rename_date_enabled", True)
                    rename_date = self.settings.get("rename_date", "").strip() if rename_date_enabled else ""
                    rename_start_index = int(self.settings.get("rename_start_index", 1))
                    rename_padding = int(self.settings.get("rename_padding", 3))

                    prefix_part = clean_filename_part(rename_prefix) if rename_prefix else ""
                    suffix_part = clean_filename_part(rename_suffix) if rename_suffix else ""
                    date_part = clean_filename_part(rename_date) if rename_date else ""

                    title_text = chinese
                    if not title_text or title_text.strip().startswith("【"):
                        short_orig = original[:200] if original else ""
                        translated = translate_to_chinese_free(short_orig)
                        if translated:
                            title_text = translated
                        else:
                            title_text = original or video.stem
                    title_part = clean_filename_part(title_text)

                    seq_str = str(rename_start_index + index).zfill(rename_padding)

                    parts = [seq_str]
                    for part in (prefix_part, title_part, date_part):
                        if part:
                            parts.append(part)
                    base = "-".join(parts)
                    if suffix_part:
                        base += suffix_part if suffix_part.startswith("-") else "-" + suffix_part
                    
                    safe_name, _truncated = safe_filename(base + video.suffix, self.output)
                    destination = self.output / safe_name
                else:
                    destination = bounded_output_path(self.output, video.stem, "_动态文案.mp4")
                # Keep libass intermediate paths short. Long source titles can exceed
                # the Windows/libass path limit even when the source video opens fine.
                ass = temporary_ass_path(f"caption_{short_media_id(video)}")
                write_ass(ass, phrase_srt, self.settings, word_srt)
                baked_watermarks={str(Path(path).resolve()) for path in self.settings.get("watermark_baked_videos",[]) }
                watermark_already_baked=str(video.resolve()) in baked_watermarks
                stages=[]
                if self.settings.get("watermark_path") and not watermark_already_baked: stages.append("公司水印")
                if any(layer.get("type") in ("mask","text") for layer in self.settings.get("layers",[])): stages.append("图层/蒙版")
                stage_text="、".join(["字幕",*stages])
                if watermark_already_baked:
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 当前水印已在分组合成阶段烧录，本次跳过重复水印。")
                self.log.emit(f"[{index + 1}/{len(self.videos)}] 正在烧录{stage_text}并编码视频，请等待…")
                self.progress.emit(round((index + .55) / max(1,len(self.videos)) * 100))
                ass_filter = ass
                command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(render_video)]
                external = audio.resolve() != video.resolve()
                audio_mode = self.settings.get("audio_mode", "保留视频原音")
                mix_audio = external and audio_mode == "原声＋背景音混合"
                replace_audio = external and audio_mode == "替换为添加的音频"
                source_has_audio = media_has_audio(self.ffmpeg, render_video)
                if audio_mode == "原声＋背景音混合" and not external:
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 未匹配到独立背景音，已保留视频原声继续处理。")
                if external and self.settings.get("audio_match_mode") == "随机分配并随机截取时间段":
                    import random
                    audio_duration = media_duration(self.ffmpeg, audio)
                    video_duration = media_duration(self.ffmpeg, render_video)
                    if audio_duration > video_duration:
                        max_start = audio_duration - video_duration
                        rnd = random.Random(hash(str(video.resolve())) + index + 777)
                        random_start = rnd.uniform(0.0, max_start)
                        audio_offset_ms = int(random_start * 1000)
                    else:
                        if audio_duration > 1.0:
                            rnd = random.Random(hash(str(video.resolve())) + index + 777)
                            random_start = rnd.uniform(0.0, min(5.0, audio_duration - 0.5))
                            audio_offset_ms = int(random_start * 1000)
                        else:
                            audio_offset_ms = 0
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 随机匹配背景音：选用 {audio.name}，随机起始裁剪点为 {audio_offset_ms / 1000:.2f} 秒。")
                else:
                    audio_offset_ms = (int(self.settings.get("audio_offsets", {}).get(str(audio.resolve()), 0))
                                       if external else 0)
                if external:
                    if mix_audio: command += ["-stream_loop", "-1"]
                    if audio_offset_ms > 0: command += ["-ss", f"{audio_offset_ms / 1000:.3f}"]
                    command += ["-i", str(audio)]
                watermark_entries=[] if watermark_already_baked else (self.settings.get("watermarks") or [])
                watermark_paths=[] if watermark_already_baked else (self.settings.get("watermark_paths") or [self.settings.get("watermark_path","")])
                watermark = (prepared_watermark_composite(self.ffmpeg,render_video,watermark_entries,self.output)
                             if watermark_entries else prepared_watermark_stack(watermark_paths,self.output))
                watermark_enabled = watermark.is_file()
                render_settings=self.settings
                if watermark_enabled and watermark_entries:
                    render_settings=dict(self.settings); render_settings.update({"watermark_prepared":True,"watermark_mode":"9:16 全屏覆盖"})
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 已合成 {len(watermark_entries)} 个独立水印图层缓存。")
                elif watermark_enabled and self.settings.get("watermark_mode","9:16 全屏覆盖")=="9:16 全屏覆盖":
                    watermark=prepared_fullframe_watermark(
                        self.ffmpeg,render_video,watermark,self.output,self.settings.get("watermark_opacity",90))
                    render_settings=dict(self.settings); render_settings["watermark_prepared"]=True
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 已使用预缩放公司水印缓存，跳过逐帧缩放。")
                watermark_input = 2 if external else 1
                video_duration = media_duration(self.ffmpeg, render_video)
                audio_graph = (mixed_audio_filter(self.settings.get("original_volume", 100),
                                                  self.settings.get("background_volume", 25),
                                                  self.settings.get("audio_fade_mode"),
                                                  self.settings.get("audio_fade_in_ms",500),
                                                  self.settings.get("audio_fade_out_ms",500),video_duration)
                               if mix_audio and source_has_audio else
                               (replacement_audio_filter(self.settings.get("audio_fade_mode"),
                                                        self.settings.get("audio_fade_in_ms",500),
                                                        self.settings.get("audio_fade_out_ms",500),video_duration)
                                if replace_audio else ""))
                if watermark_enabled:
                    # Decode the static PNG once; overlay=eof_action=repeat keeps that frame
                    # for the whole video without decoding/scaling the same image every frame.
                    command += ["-i", str(watermark)]
                    graph = watermark_filter_graph(ass_filter, render_settings, watermark_input)
                    if audio_graph: graph += ";" + audio_graph
                    command += ["-filter_complex", graph,
                                "-map", "[outv]"]
                else:
                    command += ["-vf", ass_filter_expression(ass_filter,self.settings), "-map", "0:v:0"]
                    if audio_graph: command += ["-filter_complex", audio_graph]
                if audio_graph:
                    command += ["-map", "[aout]", "-shortest"]
                    if mix_audio:
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 正在混合原声与背景音："
                                      f"原声 {self.settings.get('original_volume',100)}%，"
                                      f"背景音 {self.settings.get('background_volume',25)}%，"
                                      f"起点 {audio_offset_ms / 1000:.2f} 秒。")
                    else:
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 替换音频从 {audio_offset_ms / 1000:.2f} 秒开始，"
                                      "并已按当前视频时长自动裁剪或补静音。")
                elif mix_audio and not source_has_audio:
                    command += ["-map", "1:a:0", "-shortest"]
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 当前视频没有原声音轨，已自动仅使用背景音。")
                else:
                    command += ["-map", "0:a?"]
                # 不指定 -ac，保留源音频声道；字幕烧录只重编码画面。
                command += encoder_args(encoder, self.settings["encode_preset"])
                command += ["-c:a", "aac", "-b:a", "192k"]
                if external and audio_mode in ("替换为添加的音频", "原声＋背景音混合"):
                    command += ["-ac", "2"]
                if self.settings.get("clean_metadata", True):
                    command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                "-map_chapters", "-1"]
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 将在成品输出时直接清除元数据（不生成副本）。")
                command += ["-movflags", "+faststart", str(destination)]
                returncode, render_log = self._run_render(command, video_duration, index, len(self.videos))
                try: ass.unlink()
                except OSError: pass
                if returncode: raise RuntimeError(render_log.strip() or "动态文案渲染失败")
                completed[str(video.resolve())]={"fingerprint":fingerprint,"destination":str(destination),
                    "original":original,"chinese":chinese,"word_srt":word_srt,"phrase_srt":phrase_srt}
                checkpoint["status"]="rendering"; _write_reels_checkpoint(self.output,checkpoint)
                self.result.emit(str(destination), original, chinese)
                self.progress.emit(round((index + 1) / len(self.videos) * 100))
                self.log.emit(f"成品：{destination}")
            checkpoint["status"]="render_completed"; _write_reels_checkpoint(self.output,checkpoint)
            self.finished.emit(True, f"批处理完成，共生成 {len(self.videos)} 个动态文案视频。\n{self.output}")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class TtsWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, callback, text, service, voice, destination):
        super().__init__(); self.callback = callback; self.text = text; self.service = service
        self.voice = voice; self.destination = destination

    def run(self):
        try:
            result = self.callback(self.text, self.service, self.voice, self.destination)
            self.finished.emit(True, str(result))
        except Exception as exc:
            self.finished.emit(False, str(exc))


class BatchTtsWorker(QObject):
    item_done = Signal(bool, str, str, int, int)
    finished = Signal(bool, str)

    def __init__(self, callback, jobs, service, voice):
        super().__init__(); self.callback = callback; self.jobs = jobs
        self.service = service; self.voice = voice; self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        failures = []
        for index, (text, destination) in enumerate(self.jobs, 1):
            if self.cancelled:
                self.finished.emit(False, "配音队列已停止；已经生成的音频仍然保留。")
                return
            target = Path(destination); state = target.with_suffix(target.suffix + ".tts.json")
            fingerprint = hashlib.sha256(
                f"{self.service}\n{self.voice}\n{text}".encode("utf-8")).hexdigest()
            try:
                saved = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
            except Exception:
                saved = {}
            if target.exists() and target.stat().st_size > 256 and saved.get("fingerprint") == fingerprint:
                self.item_done.emit(True, str(target), "续接：复用已成功生成的配音", index, len(self.jobs))
                continue
            try:
                result = Path(self.callback(text, self.service, self.voice, str(target)))
                state.write_text(json.dumps({"fingerprint": fingerprint, "service": self.service,
                                             "voice": self.voice}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
                self.item_done.emit(True, str(result), "生成成功", index, len(self.jobs))
            except Exception as exc:
                failures.append(f"第 {index} 条：{exc}")
                self.item_done.emit(False, str(target), str(exc), index, len(self.jobs))
        if failures:
            self.finished.emit(False, f"配音队列完成：成功 {len(self.jobs)-len(failures)} 条，失败 {len(failures)} 条。\n" +
                               "\n".join(failures[:5]))
        else:
            self.finished.emit(True, f"批量配音完成，共 {len(self.jobs)} 条。")


class PreviewWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, ffmpeg, source, destination, text, settings):
        super().__init__(); self.ffmpeg = ffmpeg; self.source = Path(source)
        self.destination = Path(destination); self.text = text; self.settings = settings

    def run(self):
        ass = temporary_ass_path("preview")
        try:
            if self.settings.get("caption_mode") == "自由文案动画（不对口型）":
                sample = free_caption_srt(self.text, 8.0, self.settings)
            else:
                sample = self.text if "-->" in self.text else f"1\n00:00:00,000 --> 00:00:08,000\n{self.text}\n"
            write_ass(ass, sample, self.settings, self.settings.get("preview_word_srt", ""))
            ass_filter = ass
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.source)]
            preview_audio = Path(str(self.settings.get("preview_audio", "")))
            external = preview_audio.is_file() and preview_audio.resolve() != self.source.resolve()
            audio_mode = self.settings.get("audio_mode", "保留视频原音")
            mix_audio = external and audio_mode == "原声＋背景音混合"
            replace_audio = external and audio_mode == "替换为添加的音频"
            source_has_audio = media_has_audio(self.ffmpeg, self.source)
            if external:
                if mix_audio: command += ["-stream_loop", "-1"]
                preview_offset=max(0,int(self.settings.get("preview_audio_offset_ms",0)))
                if preview_offset: command += ["-ss",f"{preview_offset/1000:.3f}"]
                command += ["-i", str(preview_audio)]
            baked_watermarks={str(Path(path).resolve()) for path in self.settings.get("watermark_baked_videos",[]) }
            watermark_already_baked=str(self.source.resolve()) in baked_watermarks
            watermark_entries=[] if watermark_already_baked else (self.settings.get("watermarks") or [])
            watermark_paths=[] if watermark_already_baked else (self.settings.get("watermark_paths") or [self.settings.get("watermark_path","")])
            watermark = (prepared_watermark_composite(self.ffmpeg,self.source,watermark_entries,self.destination.parent)
                         if watermark_entries else prepared_watermark_stack(watermark_paths,self.destination.parent))
            watermark_enabled = watermark.is_file()
            render_settings=self.settings
            if watermark_enabled and watermark_entries:
                render_settings=dict(self.settings); render_settings.update({"watermark_prepared":True,"watermark_mode":"9:16 全屏覆盖"})
            elif watermark_enabled and self.settings.get("watermark_mode","9:16 全屏覆盖")=="9:16 全屏覆盖":
                watermark=prepared_fullframe_watermark(
                    self.ffmpeg,self.source,watermark,self.destination.parent,self.settings.get("watermark_opacity",90))
                render_settings=dict(self.settings); render_settings["watermark_prepared"]=True
            watermark_input = 2 if external else 1
            preview_duration=min(8.0,media_duration(self.ffmpeg,self.source))
            audio_graph = (mixed_audio_filter(self.settings.get("original_volume", 100),
                                              self.settings.get("background_volume", 25),
                                              self.settings.get("audio_fade_mode"),
                                              self.settings.get("audio_fade_in_ms",500),
                                              self.settings.get("audio_fade_out_ms",500),preview_duration)
                           if mix_audio and source_has_audio else
                           (replacement_audio_filter(self.settings.get("audio_fade_mode"),
                                                    self.settings.get("audio_fade_in_ms",500),
                                                    self.settings.get("audio_fade_out_ms",500),preview_duration)
                            if replace_audio else ""))
            if watermark_enabled:
                graph = watermark_filter_graph(ass_filter, render_settings, watermark_input)
                if audio_graph: graph += ";" + audio_graph
                command += ["-i", str(watermark), "-t", "8", "-filter_complex",
                            graph, "-map", "[outv]"]
            else:
                command += ["-t", "8", "-vf", ass_filter_expression(ass_filter,self.settings), "-map", "0:v:0"]
                if audio_graph: command += ["-filter_complex", audio_graph]
            if audio_graph:
                command += ["-map", "[aout]"]
            elif mix_audio and not source_has_audio:
                command += ["-map", "1:a:0"]
            else:
                command += ["-map", "0:a?"]
            encoder = resolve_encoder(self.ffmpeg, self.settings.get("encoder_backend", "auto"))
            command += encoder_args(encoder, preview=True)
            command += ["-c:a", "aac", "-b:a", "160k"]
            if external and audio_mode in ("替换为添加的音频", "原声＋背景音混合"):
                command += ["-ac", "2", "-shortest"]
            command += ["-movflags", "+faststart", str(self.destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
            if result.returncode: raise RuntimeError(result.stderr.strip() or "效果预览生成失败")
            self.finished.emit(True, str(self.destination))
        except Exception as exc:
            self.finished.emit(False, str(exc))
        finally:
            try: ass.unlink()
            except OSError: pass


class TimelineWorker(QObject):
    started = Signal(str)
    finished = Signal(bool, str, str)

    def __init__(self, callback, path, cache_dir=None, force_refresh=False):
        super().__init__(); self.callback = callback; self.path = path; self.cache_dir=cache_dir
        self.force_refresh = bool(force_refresh)

    def run(self):
        try:
            self.started.emit(str(self.path))
            # A manual "extract selected" action must really call the selected
            # recognition service again.  Cache reuse is reserved for batch
            # processing/checkpoint resume; otherwise a bad ASR result can never
            # be corrected from the editor.
            srt=("" if self.force_refresh else
                 (_load_timeline_cache(self.cache_dir,self.path) if self.cache_dir else ""))
            chinese = ""
            if not srt:
                _original, chinese, srt = self.callback(self.path)
                if self.cache_dir and str(srt or "").strip(): _save_timeline_cache(self.cache_dir,self.path,srt)
            self.finished.emit(True, srt, chinese)
        except Exception as exc:
            self.finished.emit(False, str(exc), "")


class BatchTimelineWorker(QObject):
    item_started = Signal(str, int, int)
    item_done = Signal(str, str, str, int, int)
    item_failed = Signal(str, str, int, int)
    finished = Signal(bool, str)

    def __init__(self, callback, paths, cache_dir=None):
        super().__init__(); self.callback = callback; self.paths = list(paths); self.cache_dir=cache_dir

    def run(self):
        total = len(self.paths)
        failures = []
        for index, path in enumerate(self.paths, 1):
            try:
                self.item_started.emit(str(path), index, total)
                sidecar = Path(path).with_suffix(".srt")
                chinese = ""
                if sidecar.exists() and sidecar.stat().st_size:
                    srt = sidecar.read_text(encoding="utf-8-sig")
                elif self.cache_dir and _load_timeline_cache(self.cache_dir,path):
                    srt=_load_timeline_cache(self.cache_dir,path)
                else:
                    _original, chinese, srt = self.callback(path)
                    if self.cache_dir and str(srt or "").strip(): _save_timeline_cache(self.cache_dir,path,srt)
                if not srt.strip():
                    raise RuntimeError(f"没有识别到字幕：{Path(path).name}")
                self.item_done.emit(str(path), srt, chinese, index, total)
            except Exception as exc:
                message = str(exc)
                failures.append(f"{Path(path).name}：{message}")
                self.item_failed.emit(str(path), message, index, total)
        if failures:
            self.finished.emit(
                len(failures) < total,
                f"批量时间轴处理结束：成功 {total-len(failures)} 个，失败 {len(failures)} 个；失败项已写入软件日志。",
            )
        else:
            self.finished.emit(True, f"已按队列完成 {total} 个素材的时间轴提取。")


class GroupCaptionDialog(QDialog):
    """Folder-level mapping table: one pasted line maps to one naturally sorted clip."""

    def __init__(self, groups, saved_scripts, parent=None):
        super().__init__(parent); self.groups=list(groups); self.saved_scripts=dict(saved_scripts)
        self.setWindowTitle("分组文件与字幕对应表"); self.resize(1120,650)
        layout=QVBoxLayout(self)
        tip=QLabel("每行代表一个文件夹组。文案列中每一行对应该文件夹内一个视频；文件按自然顺序 1、2、3…排列。也可复制全部文案后点击“一键按片段数分配”。")
        tip.setWordWrap(True); tip.setStyleSheet("color:#7dd3fc;background:#0b1830;padding:8px;border-radius:5px;"); layout.addWidget(tip)
        self.table=QTableWidget(len(self.groups),6)
        self.table.setHorizontalHeaderLabels(["序号","文件夹","片段数","片段文件（自然排序）","逐段文案（每行一个）","状态"])
        self.table.verticalHeader().setVisible(False); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.editors=[]
        for row,(folder,clips) in enumerate(self.groups):
            clips=sorted(clips,key=lambda p:natural_key(Path(p).name))
            values=(f"{row+1:02d}",folder.name,str(len(clips)),"\n".join(f"{i+1:02d}. {Path(p).name}" for i,p in enumerate(clips)))
            for column,value in enumerate(values):
                item=QTableWidgetItem(value); item.setToolTip(value); self.table.setItem(row,column,item)
            editor=QPlainTextEdit(); editor.setPlaceholderText(f"粘贴 {len(clips)} 行文案")
            existing=str(self.saved_scripts.get(str(folder.resolve()),""))
            editor.setPlainText("\n".join(split_group_script(existing)))
            editor.textChanged.connect(lambda r=row:self._update_status(r)); self.table.setCellWidget(row,4,editor); self.editors.append(editor)
            self.table.setRowHeight(row,122); self._update_status(row)
        header=self.table.horizontalHeader(); header.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); header.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch); header.setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5,QHeaderView.ResizeMode.ResizeToContents); layout.addWidget(self.table,1)
        actions=QHBoxLayout(); paste_all=QPushButton("从剪贴板一键按片段数分配"); paste_all.clicked.connect(self._paste_all)
        actions.addWidget(paste_all); actions.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存对应关系")
        buttons.accepted.connect(self._validate_accept); buttons.rejected.connect(self.reject); actions.addWidget(buttons); layout.addLayout(actions)

    @staticmethod
    def _lines(editor):
        return [line.strip() for line in editor.toPlainText().splitlines() if line.strip() and line.strip()!="---"]

    def _update_status(self,row):
        expected=len(self.groups[row][1]); actual=len(self._lines(self.editors[row])) if row < len(self.editors) else 0
        text="未填写" if actual==0 else ("✓ 已对应" if actual==expected else f"{actual}/{expected}")
        item=self.table.item(row,5) or QTableWidgetItem(); item.setText(text)
        item.setForeground(QColor("#4ade80" if actual==expected else "#facc15")); self.table.setItem(row,5,item)

    def _paste_all(self):
        lines=[line.strip() for line in QApplication.clipboard().text().splitlines() if line.strip() and line.strip()!="---"]
        expected=sum(len(clips) for _folder,clips in self.groups)
        if len(lines)!=expected:
            QMessageBox.information(self,"数量不一致",f"剪贴板有 {len(lines)} 行有效文案，但全部文件夹共有 {expected} 个视频。\n请保证一行对应一个视频后重试。")
            return
        offset=0
        for editor,(_folder,clips) in zip(self.editors,self.groups):
            count=len(clips); editor.setPlainText("\n".join(lines[offset:offset+count])); offset+=count

    def _validate_accept(self):
        errors=[]
        for editor,(folder,clips) in zip(self.editors,self.groups):
            count=len(self._lines(editor))
            if count and count!=len(clips): errors.append(f"{folder.name}：文案 {count} 行，视频 {len(clips)} 个")
        if errors:
            QMessageBox.warning(self,"对应数量不一致","请调整以下文件夹：\n"+"\n".join(errors[:10])); return
        self.accept()

    def scripts(self):
        return {str(folder.resolve()):"\n\n".join(self._lines(editor)) for editor,(folder,_clips) in zip(self.editors,self.groups)}


class DynamicCaptionPage(QWidget):
    rename_folder_requested = Signal(str)

    def __init__(self, transcribe_callable, tts_callable, find_ffmpeg, providers, default_provider,
                 sync_profiles_callable=None, cloud_sync_callable=None, open_sync_settings_callable=None):
        super().__init__(); self.transcribe_callable = transcribe_callable; self.find_ffmpeg = find_ffmpeg
        self.tts_callable = tts_callable; self.providers = providers; self.thread = None; self.worker = None
        self.sync_profiles_callable = sync_profiles_callable; self.cloud_sync_callable = cloud_sync_callable
        self.open_sync_settings_callable = open_sync_settings_callable; self.generated_records = []
        self.tts_thread = None; self.tts_worker = None; self.timeline_overrides = {}; self.timeline_words = {}; self.timeline_chinese = {}; self._loading_timeline = False
        self.group_merge_thread = None; self.group_merge_worker = None; self.group_merge_groups = []
        self._group_auto_extract_requested = False; self._group_auto_extract_pending = False
        self.group_scripts = {}; self._loading_group_script = False; self.group_merge_outputs = []
        self._pending_group_cleanup_dir=None; self._batch_expected_count=0
        self._watermark_image = QImage(); self._watermark_images=[]; self._watermark_paths=[]; self._watermark_entries=[]
        self._active_group_watermark_fingerprint=""
        try: self._baked_watermarks=json.loads(QSettings("VideoToolkit","DynamicReels").value("baked_watermarks","{}"))
        except Exception: self._baked_watermarks={}
        self._precise_preview_active = False; self._precise_preview_files = set()
        self._live_caption_style_cache=None
        self._live_timeline_cache_key=None; self._live_timeline_cache=([],[])
        self._live_watermark_cache=None
        self.free_texts = {}
        self.audio_offsets = {}; self._audio_edit_source = ""; self._preview_audio_offset_ms = 0
        self._active_timeline_source = ""; self._syncing_media_selection = False; self._timeline_pending_source = ""
        self._timeline_activity_started=0.0; self._timeline_activity_label=""
        self._timeline_activity_base=0; self._timeline_activity_cap=90
        self._timeline_activity_timer=QTimer(self); self._timeline_activity_timer.setInterval(800)
        self._timeline_activity_timer.timeout.connect(self._timeline_activity_tick)
        self._restoring_style = False
        # 图层列表按“上层在前”保存；渲染时反向绘制，便于用户理解上移/下移。
        self.layers = [{"type": "caption", "name": "字幕层"}]
        self._mask_counter = 0
        self._text_counter = 0; self._layer_schemes = {}
        self._build_ui(default_provider)

    def _make_collapsible(self, group, key, default_expanded=True):
        """Turn a settings group into a remembered compact disclosure section."""
        store=QSettings("VideoToolkit","DynamicReels")
        saved=store.value(f"section_expanded/{key}",default_expanded)
        expanded=(str(saved).casefold() not in ("false","0","no"))
        group.setCheckable(True)
        group.setChecked(expanded)
        group.setToolTip("点击标题可展开或折叠此设置区")
        original_title = group.title()
        def apply(opened):
            group.setMaximumHeight(16777215 if opened else 32)
            store.setValue(f"section_expanded/{key}",bool(opened))
            arrow = "▼ " if opened else "▶ "
            group.setTitle(arrow + original_title)
            if opened:
                group.setStyleSheet("QGroupBox { border: 2px solid #2563eb; background-color: #111e36; margin-top:8px; padding-top:7px; font-weight:700; } QGroupBox::title { subcontrol-origin:margin; left:9px; padding:0 4px; color:#60a5fa; } QGroupBox::indicator { width:0px; height:0px; }")
            else:
                group.setStyleSheet("QGroupBox { border: 1px solid #1e293b; background-color: #0b0f19; margin-top:8px; padding-top:7px; font-weight:normal; } QGroupBox::title { subcontrol-origin:margin; left:9px; padding:0 4px; color:#64748b; } QGroupBox::indicator { width:0px; height:0px; }")
            group.updateGeometry()
        group.toggled.connect(apply)
        apply(expanded)

    def _build_ui(self, default_provider):
        self._restoring_style=True
        root = QVBoxLayout(self); root.setContentsMargins(12, 8, 12, 10); root.setSpacing(6)
        
        # Create run-related controls early so they can be added to header layout
        self.cloud_sync_check=QCheckBox("生成后上传/填表")
        self.cloud_sync_check.setToolTip("使用自动流水线相同的 Google Drive 与 Google Sheets 配置；不勾选则只生成本地成品")
        self.cloud_sync_profile=QComboBox()
        self.cloud_sync_profile.setMinimumWidth(80)
        self.cloud_sync_profile.setMaximumWidth(120)
        
        configure_sync=QPushButton("上传/填表配置")
        configure_sync.setObjectName("syncConfigButton")
        configure_sync.setStyleSheet("background:#1d4ed8;color:white;font-weight:700;border-color:#60a5fa;padding:3px 8px;min-height:18px;")
        configure_sync.clicked.connect(self._open_sync_settings)
        configure_sync.setMaximumWidth(100)
        
        self.stop=QPushButton("停止")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        self.stop.setStyleSheet("background:#991b1b;color:white;border-color:#fca5a5;padding:3px 8px;min-height:18px;")
        
        self.start=QPushButton("开始批量导出")
        self.start.setObjectName("primary")
        self.start.setStyleSheet("padding:3px 12px;min-height:18px;")
        self.start.clicked.connect(self.run)

        header = QHBoxLayout()
        heading = QLabel("Reels 视频编辑器")
        heading.setObjectName("heading")
        
        flow_label = QLabel(" 合成 → 批量字幕 → 批量配音 → 字幕样式 → 添加水印 → 批量重命名 → 批量导出 → 批量上传与填表")
        flow_label.setStyleSheet("font-size:11px;color:#94a3b8;margin-left:8px;")
        
        header.addWidget(heading)
        header.addWidget(flow_label)
        header.addStretch()
        header.addWidget(self.cloud_sync_check)
        header.addWidget(QLabel("方案"))
        header.addWidget(self.cloud_sync_profile)
        header.addWidget(configure_sync)
        header.addWidget(self.stop)
        header.addWidget(self.start)
        root.addLayout(header)

        workspace = QSplitter(Qt.Orientation.Horizontal); workspace.setChildrenCollapsible(False)

        # 左栏内部拆成“内容 + 竖向图标”两列；中间预览和最右设置保持独立。
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0,0,4,0); left_layout.setSpacing(6)
        left.setMinimumWidth(360)
        source_group = QGroupBox("素材项目"); source_group_layout = QHBoxLayout(source_group); source_group_layout.setContentsMargins(8,10,8,8)
        source_group.setMinimumHeight(350)
        source_stack = QStackedWidget(); self.source_stack = source_stack

        video_tab = QWidget(); vg = QVBoxLayout(video_tab); vg.setContentsMargins(4,4,4,4)
        self.videos = DropListWidget(); self.videos.setMinimumHeight(110)
        self.videos.paths_dropped.connect(lambda p: self._add(self.videos, p, VIDEO_EXTENSIONS))
        self.videos.currentTextChanged.connect(self._video_selection_changed); vg.addWidget(self.videos, 1)
        vrow = QHBoxLayout(); vb = QPushButton("添加视频"); vb.clicked.connect(self._choose_videos)
        vf = QPushButton("添加文件夹"); vf.clicked.connect(lambda: self._choose_folder(self.videos, VIDEO_EXTENSIONS))
        vc = QPushButton("清空"); vc.clicked.connect(lambda: self._clear_media_queue(self.videos))
        for button in (vb,vf,vc): vrow.addWidget(button)
        vg.addLayout(vrow)

        audio_tab = QWidget(); audio_tab_layout = QVBoxLayout(audio_tab); audio_tab_layout.setContentsMargins(4,4,4,4)
        self.audios = DropListWidget(); self.audios.setMinimumHeight(95); self.audios.paths_dropped.connect(lambda p: self._add(self.audios, p, AUDIO_EXTENSIONS))
        self.audios.currentTextChanged.connect(self._audio_selection_changed)
        arow = QHBoxLayout(); ab = QPushButton("添加音频"); ab.clicked.connect(self._choose_audio)
        af = QPushButton("添加文件夹"); af.clicked.connect(lambda: self._choose_folder(self.audios, AUDIO_EXTENSIONS))
        ac = QPushButton("清空"); ac.clicked.connect(lambda: self._clear_media_queue(self.audios))
        for button in (ab,af,ac): arow.addWidget(button)
        audio_tab_layout.addWidget(self.audios,1); audio_tab_layout.addLayout(arow)
        text_tab = QWidget(); text_tab_layout = QVBoxLayout(text_tab); text_tab_layout.setContentsMargins(4,4,4,4)
        self.tts_text = ScriptTaskTable(); self.tts_text.setMinimumHeight(130)
        self.tts_text.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        text_tab_layout.addWidget(self.tts_text,1)
        script_actions=QHBoxLayout()
        add_script=QPushButton("＋ 新增任务"); add_script.clicked.connect(lambda:self._edit_script_tasks(add_empty=True))
        paste_scripts=QPushButton("粘贴多行"); paste_scripts.clicked.connect(lambda:self._edit_script_tasks(clipboard_text=QApplication.clipboard().text()))
        remove_scripts=QPushButton("删除选中"); remove_scripts.clicked.connect(self.tts_text.remove_selected_rows)
        script_actions.addWidget(add_script); script_actions.addWidget(paste_scripts); script_actions.addWidget(remove_scripts)
        text_tab_layout.addLayout(script_actions)
        self.tts_service = QComboBox(); self.tts_service.addItems(
            ["Gemini 自然语音", "ElevenLabs API", "微软文字转语音"])
        self.tts_voice = QComboBox(); self.tts_voice.setEditable(True); self._load_gemini_voices()
        self.tts_service.currentTextChanged.connect(self.tts_service_changed)
        self.tts_generate = QPushButton("批量生成并加入音频队列"); self.tts_generate.setObjectName("primary"); self.tts_generate.clicked.connect(self.generate_tts)
        tts_line1 = QHBoxLayout(); tts_line1.addWidget(self.tts_service); tts_line1.addWidget(self.tts_voice,1)
        text_tab_layout.addLayout(tts_line1); text_tab_layout.addWidget(self.tts_generate)

        group_tab = QScrollArea(); group_tab.setWidgetResizable(True)
        group_tab.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        group_tab.setFrameShape(QFrame.Shape.NoFrame)
        group_body = QWidget(); group_layout = QVBoxLayout(group_body); group_layout.setContentsMargins(4,4,4,4); group_layout.setSpacing(4)
        group_tab.setWidget(group_body)
        group_path_row = QHBoxLayout()
        self.group_parent = DropFolderLineEdit(); self.group_parent.setPlaceholderText("拖入父文件夹：每个直接子文件夹为一组合成任务")
        self.group_parent.folder_dropped.connect(self._scan_group_parent)
        choose_group_parent = QPushButton("选择…"); choose_group_parent.clicked.connect(self._choose_group_parent)
        clear_group_tasks = QPushButton("清空"); clear_group_tasks.clicked.connect(self._clear_group_tasks)
        scan_groups = QPushButton("扫描"); scan_groups.clicked.connect(lambda: self._scan_group_parent(self.group_parent.text()))
        map_captions = QPushButton("字幕对应表…"); map_captions.clicked.connect(self._open_group_caption_dialog)
        group_path_row.addWidget(self.group_parent,1); group_path_row.addWidget(choose_group_parent); group_path_row.addWidget(clear_group_tasks)
        group_layout.addLayout(group_path_row)
        group_tools_row=QHBoxLayout(); group_tools_row.addWidget(scan_groups); group_tools_row.addWidget(map_captions,1); group_layout.addLayout(group_tools_row)
        self.group_table = QTableWidget(0,4); self.group_table.setHorizontalHeaderLabels(["序号","文件夹","片段","文件列表"])
        self.group_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.group_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.group_table.setMaximumHeight(150); self.group_table.verticalHeader().setVisible(False)
        self.group_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed)
        self.group_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.group_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Fixed)
        self.group_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        self.group_table.setColumnWidth(0,42); self.group_table.setColumnWidth(2,46)
        self.group_table.currentCellChanged.connect(self._group_selection_changed)
        group_layout.addWidget(self.group_table)
        sort_row = QHBoxLayout(); sort_row.addWidget(QLabel("排序"))
        self.group_sort_mode = QComboBox(); self.group_sort_mode.addItems(["文件名自然排序（推荐）","按分段文案自动匹配"])
        self.group_sort_mode.currentTextChanged.connect(self._group_sort_mode_changed)
        self.group_trim_mode = QComboBox(); self.group_trim_mode.addItems([
            "智能混合边界（推荐）", "仅按文案边界", "快速声音边界",
        ])
        self.group_trim_mode.setToolTip(
            "智能混合模式会用文案首词/末词时间定位正文，再用声音检测修正首尾；"
            "识别失败会自动退回本地声音检测，不会中断整批任务。"
        )
        self.group_head_padding = QSpinBox(); self.group_head_padding.setRange(0,1000); self.group_head_padding.setValue(80); self.group_head_padding.setSuffix(" ms")
        self.group_tail_padding = QSpinBox(); self.group_tail_padding.setRange(0,1000); self.group_tail_padding.setValue(120); self.group_tail_padding.setSuffix(" ms")
        sort_row.addWidget(self.group_sort_mode,1); group_layout.addLayout(sort_row)
        trim_mode_row=QHBoxLayout(); trim_mode_row.addWidget(QLabel("裁剪")); trim_mode_row.addWidget(self.group_trim_mode,1)
        group_layout.addLayout(trim_mode_row)
        self.group_head_padding.setMinimumWidth(78); self.group_tail_padding.setMinimumWidth(78)
        self.group_head_padding.setToolTip("第一词前最多保留的保护时间，防止吞掉词首发音")
        self.group_tail_padding.setToolTip("最后一词后最多保留的保护时间，防止吞掉词尾发音")
        trim_row=QHBoxLayout(); trim_row.addWidget(QLabel("首保护")); trim_row.addWidget(self.group_head_padding,1)
        trim_row.addWidget(QLabel("尾保护")); trim_row.addWidget(self.group_tail_padding,1); group_layout.addLayout(trim_row)
        self.group_silence_threshold = QSpinBox(); self.group_silence_threshold.setRange(-60,-20)
        self.group_silence_threshold.setValue(-35); self.group_silence_threshold.setSuffix(" dB")
        self.group_silence_min = QSpinBox(); self.group_silence_min.setRange(60,1000)
        self.group_silence_min.setValue(180); self.group_silence_min.setSuffix(" ms")
        self.group_silence_threshold.setMinimumWidth(78); self.group_silence_min.setMinimumWidth(78)
        self.group_silence_threshold.setToolTip("低于该音量时视为静音；数值越大，裁剪越积极")
        self.group_silence_min.setToolTip("持续达到该时长才视为有效静音，避免误切很短的停顿")
        silence_row=QHBoxLayout(); silence_row.addWidget(QLabel("静音阈值")); silence_row.addWidget(self.group_silence_threshold,1)
        silence_row.addWidget(QLabel("最短静音")); silence_row.addWidget(self.group_silence_min,1); group_layout.addLayout(silence_row)
        group_layout.addStretch(1)
        self.group_burn_watermark=QCheckBox("水印")
        self.group_burn_watermark.setChecked(False)
        self.group_burn_watermark.setToolTip("合成时烧录当前公司水印；后续导出会自动跳过重复烧录")

        # 对应关系改在表格弹窗中集中编辑；保留隐藏编辑器兼容现有断点和选择逻辑。
        self.group_script = QPlainTextEdit(); self.group_script.hide()
        self.group_script.textChanged.connect(self._save_current_group_script)
        group_action_panel=QWidget(); self.group_action_panel=group_action_panel
        group_action_layout=QVBoxLayout(group_action_panel); group_action_layout.setContentsMargins(2,4,2,2); group_action_layout.setSpacing(5)
        self.group_auto_timeline = QCheckBox("合成并转文字"); self.group_auto_timeline.setChecked(True)
        self.group_merge_start = QPushButton("合成"); self.group_merge_start.setObjectName("primary"); self.group_merge_start.setFixedSize(66,42); self.group_merge_start.clicked.connect(self.start_group_merge)
        self.group_merge_stop = QPushButton("停止"); self.group_merge_stop.setFixedSize(66,42); self.group_merge_stop.setEnabled(False); self.group_merge_stop.clicked.connect(self.stop_group_merge)
        group_action_layout.addWidget(self.group_auto_timeline)
        compact_options=QHBoxLayout(); compact_options.setSpacing(3)
        compact_options.addWidget(self.group_burn_watermark)
        group_action_layout.addLayout(compact_options)
        group_action_layout.addWidget(self.group_merge_start); group_action_layout.addWidget(self.group_merge_stop)
        group_action_layout.addStretch()
        group_action_panel.setFixedWidth(126)

        for page in (group_tab,video_tab,audio_tab,text_tab): source_stack.addWidget(page)
        source_tools=QVBoxLayout(); source_tools.setContentsMargins(4,0,0,0); source_tools.setSpacing(5)
        self.source_tool_buttons=[]
        for index,label in enumerate(("合成","视频","音频","文转音")):
            button=QPushButton(label); button.setCheckable(True); button.setFixedSize(66,42)
            button.setToolTip({0:"分组去口气音并合成",1:"视频素材队列",2:"音频素材队列",3:"文案配音"}[index])
            button.clicked.connect(lambda checked=False,i=index:self._show_source_tool(i))
            source_tools.addWidget(button); self.source_tool_buttons.append(button)
        source_tools.addStretch()
        source_rail=QWidget(); source_rail_layout=QVBoxLayout(source_rail); source_rail_layout.setContentsMargins(0,0,0,0); source_rail_layout.setSpacing(5)
        source_rail_layout.addLayout(source_tools); source_rail_layout.addWidget(group_action_panel,1)
        source_rail.setFixedWidth(126)
        source_group_layout.addWidget(source_rail); source_group_layout.addWidget(source_stack,1)
        source_group.setStyleSheet("QPushButton:checked{background:#2563eb;color:white;border-color:#60a5fa;font-weight:700;}")
        self.audio_player=QMediaPlayer(self); self.audio_preview_output=QAudioOutput(self); self.audio_preview_output.setVolume(.8); self.audio_player.setAudioOutput(self.audio_preview_output)
        self._preview_external_audio = False
        self.audio_player.positionChanged.connect(self._audio_position_changed); self.audio_player.durationChanged.connect(self._audio_duration_changed)
        audio_controls=QHBoxLayout(); self.audio_play_btn=QPushButton("试听配音"); self.audio_play_btn.clicked.connect(self.toggle_audio_preview)
        self.audio_seek=QSlider(Qt.Orientation.Horizontal); self.audio_seek.setRange(0,0); self.audio_seek.sliderMoved.connect(self.audio_player.setPosition)
        self.audio_time=QLabel("00:00 / 00:00"); audio_controls.addWidget(self.audio_play_btn); audio_controls.addWidget(self.audio_seek,1); audio_controls.addWidget(self.audio_time); audio_tab_layout.addLayout(audio_controls)
        audio_start_controls=QHBoxLayout(); audio_start_controls.addWidget(QLabel("背景音起点"))
        self.audio_start_seek=QSlider(Qt.Orientation.Horizontal); self.audio_start_seek.setRange(0,0)
        self.audio_start_seek.setToolTip("拖动选择当前音频用于对应视频时的开始节点；每条音频单独记忆")
        self.audio_start_seek.sliderMoved.connect(self._audio_start_changed)
        self.audio_start_time=QLabel("00:00"); self.audio_start_time.setFixedWidth(42)
        self.audio_start_preview=QPushButton("试听起点"); self.audio_start_preview.clicked.connect(self._preview_audio_start)
        audio_start_controls.addWidget(self.audio_start_seek,1); audio_start_controls.addWidget(self.audio_start_time); audio_start_controls.addWidget(self.audio_start_preview)
        audio_tab_layout.addLayout(audio_start_controls)
        self._show_source_tool(0)
        left_layout.addWidget(source_group,3)

        # 右侧工作区中的视频播放器、时间轴和快速效果预览。
        center = QWidget(); center_layout = QVBoxLayout(center); center_layout.setContentsMargins(4,0,4,0); center_layout.setSpacing(6)
        preview_group = QGroupBox("视频预览与定位"); preview_layout = QVBoxLayout(preview_group); preview_layout.setContentsMargins(9,10,9,8)
        # Windows 上 QVideoWidget 在部分显卡/解码器组合下只有声音没有画面。
        # 画面统一交给 OpenCV 解码并显示，QMediaPlayer 只负责音频和播放时钟。
        self.video_widget = QLabel("添加或选择视频后在这里预览")
        self.video_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_widget.setMinimumSize(300,330)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.video_widget.setStyleSheet("background:#02050b;color:#64748b;border:1px solid #334155;border-radius:7px;")
        self.audio_output = QAudioOutput(self); self.audio_output.setVolume(.65)
        self.player = QMediaPlayer(self); self.player.setAudioOutput(self.audio_output)
        # 直接接收播放器已经解码好的画面，不再让 OpenCV 在 UI 线程重复解码整段视频。
        self.video_sink = QVideoSink(self); self.player.setVideoOutput(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._video_frame_changed)
        self.player.positionChanged.connect(self._preview_position_changed); self.player.durationChanged.connect(self._preview_duration_changed)
        self.player.errorOccurred.connect(lambda _error,message:self.log.appendPlainText(f"播放器错误：{message}") if hasattr(self,"log") else None)
        self.preview_capture = None
        self.preview_base_image = QImage()
        self.preview_frame_timer = QTimer(self); self.preview_frame_timer.setInterval(80); self.preview_frame_timer.timeout.connect(self._render_preview_frame)
        self.live_refresh_timer = QTimer(self); self.live_refresh_timer.setSingleShot(True); self.live_refresh_timer.setInterval(34)
        self.live_refresh_timer.timeout.connect(self._display_cached_preview)
        preview_layout.addWidget(self.video_widget,1)
        timeline = QHBoxLayout(); self.play_btn = QPushButton("播放"); self.play_btn.clicked.connect(self.toggle_preview)
        self.seek = QSlider(Qt.Orientation.Horizontal); self.seek.setRange(0,0); self.seek.sliderMoved.connect(self._seek_preview)
        self.time_label = QLabel("00:00 / 00:00"); timeline.addWidget(self.play_btn); timeline.addWidget(self.seek,1); timeline.addWidget(self.time_label); preview_layout.addLayout(timeline)
        position_preview = QHBoxLayout()
        position_preview.addWidget(QLabel("字幕上下位置"))
        self.preview_position_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_position_slider.setRange(20, 900)
        self.preview_position_slider.setValue(350)
        self.preview_position_slider.setToolTip("向右移动会把字幕向上抬高；实时预览立即生效")
        self.preview_position_value = QLabel("距底部 350")
        self.preview_position_slider.valueChanged.connect(self._preview_margin_changed)
        position_preview.addWidget(QLabel("低")); position_preview.addWidget(self.preview_position_slider, 1)
        position_preview.addWidget(QLabel("高")); position_preview.addWidget(self.preview_position_value)
        preview_layout.addLayout(position_preview)
        live_row = QHBoxLayout()
        self.live_preview = QCheckBox("实时显示字幕、颜色、位置与图层")
        self.live_preview.setChecked(True)
        self.live_preview.toggled.connect(self._refresh_live_preview)
        live_hint = QLabel("调整后立即更新；8 秒渲染仅用于最终核对")
        live_hint.setStyleSheet("color:#7dd3fc;")
        live_row.addWidget(self.live_preview); live_row.addStretch(); live_row.addWidget(live_hint)
        preview_layout.addLayout(live_row)
        self.render_preview_btn = QPushButton("渲染 8 秒精确预览"); self.render_preview_btn.setObjectName("primary"); self.render_preview_btn.clicked.connect(self.render_effect_preview)
        self.render_preview_btn.setMaximumWidth(230)
        self.clear_preview_btn=QPushButton("清除精确预览"); self.clear_preview_btn.clicked.connect(self._clear_precise_preview)
        render_row=QHBoxLayout(); render_row.addStretch(); render_row.addWidget(self.clear_preview_btn); render_row.addWidget(self.render_preview_btn)
        preview_layout.addLayout(render_row); center_layout.addWidget(preview_group,1)
        self.style_preview = QLabel(); self.style_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.style_preview.setMinimumHeight(76)
        self.style_preview.setVisible(False)

        # 右栏：设置独立滚动，任何窗口高度都不会把控件压扁。
        settings_scroll = QScrollArea(); settings_scroll.setWidgetResizable(True); settings_scroll.setMinimumWidth(500)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_body = QWidget(); settings_body.setMinimumWidth(0); settings_body.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        settings_layout = QVBoxLayout(settings_body); settings_layout.setContentsMargins(4,0,8,4); settings_layout.setSpacing(7)


        preset_group = QGroupBox("🎨 4. 字幕样式与动画"); preset_group.setMinimumWidth(0); preset_group.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        pg = QHBoxLayout(preset_group); pg.setContentsMargins(10,12,10,10); pg.setSpacing(10)
        self.preset_buttons=[]
        form = QFormLayout(); form.setVerticalSpacing(9); form.setHorizontalSpacing(8)
        self.provider=QComboBox(); self.provider.addItems(self.providers); self.provider.setCurrentText(default_provider)
        self.caption_mode=QComboBox(); self.caption_mode.addItems(["语音同步字幕", "自由文案动画（不对口型）"])
        self.caption_mode.setToolTip("语音同步会提取词级时间轴；自由文案按固定时长分页，不要求与人物口型一致。")
        self.caption_mode.currentTextChanged.connect(self._caption_mode_changed)
        self.free_animation=QComboBox(); self.free_animation.addItems(["逐字出现", "逐行出现", "由下向上", "淡入淡出", "整段固定"])
        self.free_animation.currentTextChanged.connect(self._free_animation_changed)
        self.free_page_seconds=QSpinBox(); self.free_page_seconds.setRange(1,20); self.free_page_seconds.setValue(3); self.free_page_seconds.setSuffix(" 秒/屏")
        free_line=QHBoxLayout(); free_line.addWidget(self.free_animation,1); free_line.addWidget(self.free_page_seconds)
        self._load_saved_font_files()
        self.font=QComboBox(); self.font.addItems(QFontDatabase.families())
        if self.font.findText("Arial") < 0: self.font.insertItem(0,"Arial")
        self.font.setCurrentText("Arial")
        self.font_size=QSpinBox(); self.font_size.setRange(20,160); self.font_size.setValue(58)
        font_line=QHBoxLayout(); font_line.addWidget(self.font,1)
        font_line.addWidget(QLabel("字号")); font_line.addWidget(self.font_size)
        self.line_length=QSpinBox(); self.line_length.setRange(6,60); self.line_length.setValue(18)
        self.line_width=QSpinBox(); self.line_width.setRange(40,96); self.line_width.setValue(86); self.line_width.setSuffix(" %")
        self.line_width.setToolTip("字幕一行最多占画面宽度的百分比；超过后自动换行")
        self.letter_spacing=QSpinBox(); self.letter_spacing.setRange(-100,300); self.letter_spacing.setValue(0); self.letter_spacing.setSuffix(" px")
        self.letter_spacing.setToolTip("调整同一个单词或文字内部的字与字间距")
        self.word_spacing=QSpinBox(); self.word_spacing.setRange(-100,300); self.word_spacing.setValue(0); self.word_spacing.setSuffix(" px")
        self.word_spacing.setToolTip("调整单词与单词之间的距离；可设为负数，不会强制保留额外空白")
        self.line_spacing=QSpinBox(); self.line_spacing.setRange(70,180); self.line_spacing.setValue(116); self.line_spacing.setSuffix(" %")
        self.line_spacing.setToolTip("调整两排字幕基线之间的距离，100% 约等于一行文字高度")
        self.max_words=QSpinBox(); self.max_words.setRange(3,12); self.max_words.setValue(7)
        self.highlight_padding=QSpinBox(); self.highlight_padding.setRange(0,120); self.highlight_padding.setValue(18); self.highlight_padding.setSuffix(" px")
        self.highlight_padding.setToolTip("跟读色块左右留白")
        self.highlight_padding_y=QSpinBox(); self.highlight_padding_y.setRange(0,120); self.highlight_padding_y.setValue(10); self.highlight_padding_y.setSuffix(" px")
        self.highlight_padding_y.setToolTip("跟读色块上下留白")
        self.animation_speed=QSpinBox(); self.animation_speed.setRange(60,360); self.animation_speed.setValue(150); self.animation_speed.setSuffix(" ms")
        self.outline_width=QSpinBox(); self.outline_width.setRange(0,12); self.outline_width.setValue(3)
        self.position=QComboBox(); self.position.addItems(["底部","画面中间","顶部"])
        self.margin_v=QSpinBox(); self.margin_v.setRange(20,900); self.margin_v.setValue(250)
        self.margin_v.valueChanged.connect(self._sync_preview_margin)
        position_line=QHBoxLayout(); position_line.addWidget(self.position); position_line.addWidget(QLabel("边距")); position_line.addWidget(self.margin_v)
        self.audio_mode=QComboBox(); self.audio_mode.addItems(["保留视频原音","替换为添加的音频","原声＋背景音混合"])
        self.audio_mode.currentTextChanged.connect(self._rematch_current_video)
        self.audio_mode.currentTextChanged.connect(self._audio_mode_changed)
        self.original_volume=QSpinBox(); self.original_volume.setRange(0,200); self.original_volume.setValue(100); self.original_volume.setSuffix(" %")
        self.background_volume=QSpinBox(); self.background_volume.setRange(0,200); self.background_volume.setValue(25); self.background_volume.setSuffix(" %")
        self.original_volume.setEnabled(False); self.background_volume.setEnabled(False)
        self.original_volume.valueChanged.connect(self._update_preview_audio_levels)
        self.background_volume.valueChanged.connect(self._update_preview_audio_levels)
        audio_volume_line=QHBoxLayout(); audio_volume_line.addWidget(QLabel("原声")); audio_volume_line.addWidget(self.original_volume)
        audio_volume_line.addWidget(QLabel("背景音")); audio_volume_line.addWidget(self.background_volume)
        self.audio_fade_mode=QComboBox(); self.audio_fade_mode.addItems([
            "直接加入（无淡入淡出）","仅淡入","仅淡出","淡入＋淡出",
        ])
        self.audio_fade_in=QSpinBox(); self.audio_fade_in.setRange(0,10000); self.audio_fade_in.setValue(500); self.audio_fade_in.setSuffix(" ms")
        self.audio_fade_out=QSpinBox(); self.audio_fade_out.setRange(0,10000); self.audio_fade_out.setValue(500); self.audio_fade_out.setSuffix(" ms")
        self.audio_fade_mode.setToolTip("只处理当前视频匹配的外部音频；直接加入不改变音量曲线。")
        self.audio_fade_in.setToolTip("外部音频从静音到设定音量的时间")
        self.audio_fade_out.setToolTip("外部音频在视频结尾逐渐变为静音的时间")
        self.audio_fade_mode.setEnabled(False); self.audio_fade_in.setEnabled(False); self.audio_fade_out.setEnabled(False)
        self.audio_fade_mode.currentTextChanged.connect(self._audio_fade_mode_changed)
        fade_time_line=QHBoxLayout(); fade_time_line.addWidget(QLabel("淡入")); fade_time_line.addWidget(self.audio_fade_in)
        fade_time_line.addWidget(QLabel("淡出")); fade_time_line.addWidget(self.audio_fade_out)
        self.audio_match_mode=QComboBox(); self.audio_match_mode.addItems([
            "自动匹配（同名优先，其次按队列）", "严格按队列一一对应", "每个视频使用自身音频", "随机分配并随机截取时间段",
        ])
        self.audio_match_mode.setToolTip(
            "添加的音频按同名或队列序号与视频一一对应；一条音频不会重复套用到其他视频")
        self.audio_match_mode.currentTextChanged.connect(self._rematch_current_video)
        self.audio_match_mode.currentTextChanged.connect(self._refresh_task_queue)
        self.clean_metadata=QCheckBox("成品直接清除元数据"); self.clean_metadata.setChecked(True)
        self.clean_metadata.setToolTip("与字幕、水印和音轨一起在最终输出命令中处理，不会另外生成无元数据副本。")
        self.encoder_backend=QComboBox(); self.encoder_backend.addItems(list(ENCODER_LABELS.values()))
        self.encoder_backend.setToolTip("自动模式会实际测试显卡编码器；不可用时自动使用 CPU。")
        self.encode_preset=QComboBox(); self.encode_preset.addItems(["veryfast","faster","fast","medium"])
        for combo in (self.caption_mode,self.free_animation,self.font,self.position,self.audio_match_mode,self.audio_mode,
                      self.audio_fade_mode,self.encoder_backend,self.encode_preset):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8); combo.setMinimumWidth(0)
        phrase_line=QHBoxLayout(); phrase_line.addWidget(QLabel("每句词数")); phrase_line.addWidget(self.max_words); phrase_line.addWidget(QLabel("每行字符")); phrase_line.addWidget(self.line_length)
        width_line=QHBoxLayout(); width_line.addWidget(QLabel("字幕行宽")); width_line.addWidget(self.line_width)
        spacing_line=QHBoxLayout(); spacing_line.addWidget(QLabel("字间距")); spacing_line.addWidget(self.letter_spacing); spacing_line.addWidget(QLabel("词间距")); spacing_line.addWidget(self.word_spacing)
        line_spacing_line=QHBoxLayout(); line_spacing_line.addWidget(QLabel("行距")); line_spacing_line.addWidget(self.line_spacing); line_spacing_line.addStretch(1)
        effect_line=QHBoxLayout(); effect_line.addWidget(QLabel("左右")); effect_line.addWidget(self.highlight_padding); effect_line.addWidget(QLabel("上下")); effect_line.addWidget(self.highlight_padding_y)
        form.addRow("字幕模式",self.caption_mode); form.addRow("自由动画",free_line)
        form.addRow("字体",font_line); form.addRow("自然分句",phrase_line); form.addRow("排版宽度",width_line); form.addRow("字幕间距",spacing_line)
        form.addRow("行间距",line_spacing_line); form.addRow("色块留白",effect_line); form.addRow("跟读动画",self.animation_speed)
        form.addRow("字幕位置",position_line); form.addRow("描边宽度",self.outline_width)
        batch_style_hint=QLabel("✓ 每个视频、匹配音频和文案组成独立任务；这里只批量套用字幕样式、蒙版 and 动画，最后统一批量导出。")
        batch_style_hint.setWordWrap(True); batch_style_hint.setStyleSheet("color:#67e8f9;background:#0b1830;padding:6px;border-radius:5px;")
        colors=QGridLayout(); self.text_color=QPushButton("文字 #FFFFFF"); self.outline_color=QPushButton("描边 #111827"); self.highlight_color=QPushButton("跟读背景 #8B5CF6")
        for index,button in enumerate((self.text_color,self.outline_color,self.highlight_color)):
            button.setMinimumHeight(32); button.clicked.connect(lambda checked=False,b=button:self.pick_color(b)); colors.addWidget(button,index//2,index%2)
        style_controls=QWidget(); style_controls.setMinimumWidth(0); style_controls.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        style_controls_layout=QVBoxLayout(style_controls); style_controls_layout.setContentsMargins(0,0,0,0); style_controls_layout.setSpacing(7)
        style_controls_layout.addLayout(form); style_controls_layout.addWidget(batch_style_hint); style_controls_layout.addLayout(colors); style_controls_layout.addStretch()
        preset_panel=QWidget(); preset_panel.setMinimumWidth(170); preset_panel.setMaximumWidth(195)
        preset_list=QVBoxLayout(preset_panel); preset_list.setContentsMargins(0,0,0,0); preset_list.setSpacing(5)
        preset_title=QLabel("动画与配色预设"); preset_title.setAlignment(Qt.AlignmentFlag.AlignCenter); preset_title.setStyleSheet("color:#7dd3fc;font-weight:700;")
        preset_list.addWidget(preset_title)
        
        # Preset save / import / export actions
        preset_actions = QHBoxLayout(); preset_actions.setSpacing(3)
        self.preset_save = QPushButton("＋保存"); self.preset_save.setToolTip("保存当前字幕参数为自定义预设")
        self.preset_save.setStyleSheet("font-size: 11px; padding: 2px;")
        self.preset_save.clicked.connect(self._save_current_preset)
        
        self.preset_import = QPushButton("导入"); self.preset_import.setToolTip("从外部文件导入预设")
        self.preset_import.setStyleSheet("font-size: 11px; padding: 2px;")
        self.preset_import.clicked.connect(self._import_preset)
        
        self.preset_export = QPushButton("导出"); self.preset_export.setToolTip("将选中的预设导出到文件")
        self.preset_export.setStyleSheet("font-size: 11px; padding: 2px;")
        self.preset_export.clicked.connect(self._export_selected_preset)
        
        preset_actions.addWidget(self.preset_save)
        preset_actions.addWidget(self.preset_import)
        preset_actions.addWidget(self.preset_export)
        preset_list.addLayout(preset_actions)
        
        self.preset_list_widget = QListWidget()
        self.preset_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.preset_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.preset_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preset_list_widget.customContextMenuRequested.connect(self._show_preset_context_menu)
        self.preset_list_widget.setStyleSheet("QListWidget { background: transparent; border: none; } QListWidget::item { background: transparent; padding: 0px; border: none; }")
        self.preset_list_widget.model().rowsMoved.connect(
            lambda parent, start, end, dest, row: QTimer.singleShot(50, self._preset_order_changed)
        )
        preset_list.addWidget(self.preset_list_widget, 1)
        pg.addWidget(style_controls,1); pg.addWidget(preset_panel)
        settings_layout.addWidget(preset_group)

        # 🎵 5. 音频与背景音乐
        audio_group = QGroupBox("🎵 5. 音频与背景音乐")
        audio_layout = QVBoxLayout(audio_group); audio_layout.setContentsMargins(10,12,10,10); audio_layout.setSpacing(7)
        audio_form = QFormLayout(); audio_form.setVerticalSpacing(9); audio_form.setHorizontalSpacing(8)
        audio_form.addRow("音频匹配", self.audio_match_mode)
        audio_form.addRow("音频处理", self.audio_mode)
        audio_form.addRow("音轨音量", audio_volume_line)
        audio_form.addRow("音频淡化", self.audio_fade_mode)
        audio_form.addRow("淡化时长", fade_time_line)
        audio_layout.addLayout(audio_form)
        settings_layout.addWidget(audio_group)
        self.audio_group = audio_group

        # ⚙️ 8. 运行与编码加速
        hardware_group = QGroupBox("⚙️ 8. 运行与编码加速")
        hardware_layout = QVBoxLayout(hardware_group); hardware_layout.setContentsMargins(10,12,10,10); hardware_layout.setSpacing(7)
        hardware_form = QFormLayout(); hardware_form.setVerticalSpacing(9); hardware_form.setHorizontalSpacing(8)
        hardware_form.addRow("编码加速", self.encoder_backend)
        hardware_form.addRow("CPU 质量", self.encode_preset)
        hardware_form.addRow("素材清理", self.clean_metadata)
        hardware_layout.addLayout(hardware_form)
        self.hardware_group = hardware_group

        layer_group = QGroupBox("🛡️ 6. 蒙版、防伪水印与图层顺序")
        layer_layout = QVBoxLayout(layer_group); layer_layout.setContentsMargins(9,11,9,8); layer_layout.setSpacing(6)
        layer_tip = QLabel("列表上方会覆盖下方；字幕、文字和蒙版都可调整层级，并保存为常用方案。")
        layer_tip.setStyleSheet("color:#7dd3fc;"); layer_tip.setWordWrap(True); layer_layout.addWidget(layer_tip)
        scheme_row=QHBoxLayout(); self.layer_scheme_combo=QComboBox(); self.layer_scheme_combo.setEditable(True); self.layer_scheme_combo.setPlaceholderText("输入或选择图层方案")
        apply_scheme=QPushButton("应用"); apply_scheme.clicked.connect(self._apply_layer_scheme)
        save_scheme=QPushButton("保存方案"); save_scheme.clicked.connect(self._save_layer_scheme)
        delete_scheme=QPushButton("删除"); delete_scheme.clicked.connect(self._delete_layer_scheme)
        scheme_row.addWidget(QLabel("图层方案")); scheme_row.addWidget(self.layer_scheme_combo,1)
        for button in (apply_scheme,save_scheme,delete_scheme): scheme_row.addWidget(button)
        layer_layout.addLayout(scheme_row)
        self.layer_list = QListWidget(); self.layer_list.setMinimumHeight(92); self.layer_list.setMaximumHeight(130)
        self.layer_list.currentRowChanged.connect(self._layer_selected); layer_layout.addWidget(self.layer_list)
        layer_actions = QHBoxLayout()
        add_mask = QPushButton("＋ 添加蒙版"); add_mask.clicked.connect(self._add_mask_layer)
        add_text = QPushButton("＋ 添加文字"); add_text.clicked.connect(self._add_text_layer)
        delete_layer = QPushButton("删除"); delete_layer.clicked.connect(self._delete_layer)
        move_up = QPushButton("上移"); move_up.clicked.connect(lambda:self._move_layer(-1))
        move_down = QPushButton("下移"); move_down.clicked.connect(lambda:self._move_layer(1))
        for button in (add_mask, add_text, delete_layer, move_up, move_down): layer_actions.addWidget(button)
        layer_layout.addLayout(layer_actions)
        mask_form = QGridLayout(); mask_form.setHorizontalSpacing(6); mask_form.setVerticalSpacing(5)
        self.mask_color = QPushButton("蒙版颜色 #000000"); self.mask_color.clicked.connect(self._pick_mask_color)
        self.mask_opacity = QSlider(Qt.Orientation.Horizontal); self.mask_opacity.setRange(0,100); self.mask_opacity.setValue(55)
        self.mask_opacity_value = QLabel("55%")
        self.mask_x = QSpinBox(); self.mask_y = QSpinBox(); self.mask_w = QSpinBox(); self.mask_h = QSpinBox()
        for control in (self.mask_x,self.mask_y,self.mask_w,self.mask_h): control.setRange(0,100); control.valueChanged.connect(self._mask_control_changed)
        self.mask_radius = QSpinBox(); self.mask_radius.setRange(0,100); self.mask_radius.setValue(35); self.mask_radius.setSuffix(" %")
        self.mask_radius.setToolTip("0% 为直角；100% 为该蒙版尺寸允许的最大圆角")
        self.mask_radius.valueChanged.connect(self._mask_control_changed)
        self.mask_opacity.valueChanged.connect(self._mask_control_changed)
        mask_form.addWidget(self.mask_color,0,0,1,2); mask_form.addWidget(QLabel("透明度"),0,2); mask_form.addWidget(self.mask_opacity,0,3,1,2); mask_form.addWidget(self.mask_opacity_value,0,5)
        for column,(label,control) in enumerate((("左",self.mask_x),("上",self.mask_y),("宽",self.mask_w),("高",self.mask_h))):
            mask_form.addWidget(QLabel(label),1,column*2); mask_form.addWidget(control,1,column*2+1)
        mask_form.addWidget(QLabel("圆角"),2,0); mask_form.addWidget(self.mask_radius,2,1,1,3)
        layer_layout.addLayout(mask_form)
        quick_positions=QHBoxLayout(); quick_positions.addWidget(QLabel("快速定位")); self.mask_quick_buttons=[]
        for label,mode in (("上下居中","vertical"),("左右居中","horizontal"),("顶部居中","top"),("底部居中","bottom")):
            button=QPushButton(label); button.setMinimumHeight(26); button.clicked.connect(lambda checked=False,m=mode:self._quick_mask_position(m)); quick_positions.addWidget(button); self.mask_quick_buttons.append(button)
        layer_layout.addLayout(quick_positions)
        text_form=QGridLayout(); text_form.setHorizontalSpacing(6); text_form.setVerticalSpacing(5)
        self.layer_text=QLineEdit(); self.layer_text.setPlaceholderText("选中文字层后输入内容")
        self.layer_text_font=QComboBox(); self.layer_text_font.addItems(QFontDatabase.families()); self.layer_text_font.setCurrentText("Microsoft YaHei")
        self.layer_text_size=QSpinBox(); self.layer_text_size.setRange(12,220); self.layer_text_size.setValue(58)
        self.layer_text_color=QPushButton("文字颜色 #FFFFFF"); self.layer_text_color.clicked.connect(self._pick_layer_text_color)
        self.layer_text_outline=QSpinBox(); self.layer_text_outline.setRange(0,12); self.layer_text_outline.setValue(2)
        self.layer_text_opacity=QSpinBox(); self.layer_text_opacity.setRange(5,100); self.layer_text_opacity.setValue(100); self.layer_text_opacity.setSuffix(" %")
        self.layer_text_x=QSpinBox(); self.layer_text_y=QSpinBox()
        for control in (self.layer_text_x,self.layer_text_y): control.setRange(0,100); control.setSuffix(" %")
        text_form.addWidget(QLabel("文字层"),0,0); text_form.addWidget(self.layer_text,0,1,1,5)
        text_form.addWidget(QLabel("字体"),1,0); text_form.addWidget(self.layer_text_font,1,1,1,2); text_form.addWidget(QLabel("字号"),1,3); text_form.addWidget(self.layer_text_size,1,4)
        text_form.addWidget(self.layer_text_color,2,0,1,2); text_form.addWidget(QLabel("描边"),2,2); text_form.addWidget(self.layer_text_outline,2,3); text_form.addWidget(QLabel("透明度"),2,4); text_form.addWidget(self.layer_text_opacity,2,5)
        text_form.addWidget(QLabel("横向位置"),3,0); text_form.addWidget(self.layer_text_x,3,1); text_form.addWidget(QLabel("纵向位置"),3,2); text_form.addWidget(self.layer_text_y,3,3)
        text_quick=QHBoxLayout(); text_quick.addWidget(QLabel("文字快速定位")); self.text_quick_buttons=[]
        for label,mode in (("顶部居中","top"),("画面中心","center"),("底部居中","bottom")):
            button=QPushButton(label); button.clicked.connect(lambda checked=False,m=mode:self._quick_text_position(m)); text_quick.addWidget(button); self.text_quick_buttons.append(button)
        layer_layout.addLayout(text_form); layer_layout.addLayout(text_quick)
        self.layer_text.textChanged.connect(self._text_layer_changed); self.layer_text_font.currentTextChanged.connect(self._text_layer_changed)
        for control in (self.layer_text_size,self.layer_text_outline,self.layer_text_opacity,self.layer_text_x,self.layer_text_y): control.valueChanged.connect(self._text_layer_changed)

        watermark_title=QLabel("公司水印烧录（实时预览，并应用到全部批量成品）")
        watermark_title.setStyleSheet("color:#7dd3fc;font-weight:700;"); layer_layout.addWidget(watermark_title)
        watermark_path_row=QHBoxLayout(); self.company_watermark=QLineEdit(); self.company_watermark.setReadOnly(True); self.company_watermark.setPlaceholderText("支持添加多张透明 PNG、WebP、JPG")
        choose_watermark=QPushButton("添加图片…"); choose_watermark.setObjectName("primary"); choose_watermark.clicked.connect(self._choose_company_watermark)
        clear_watermark=QPushButton("删除选中"); clear_watermark.clicked.connect(self._remove_selected_watermarks)
        clear_all_watermarks=QPushButton("清空"); clear_all_watermarks.clicked.connect(self._clear_company_watermark)
        watermark_path_row.addWidget(self.company_watermark,1); watermark_path_row.addWidget(choose_watermark); watermark_path_row.addWidget(clear_watermark); watermark_path_row.addWidget(clear_all_watermarks); layer_layout.addLayout(watermark_path_row)
        self.watermark_table=QTableWidget(0,4); self.watermark_table.setHorizontalHeaderLabels(["图片图层","位置","大小","透明度"])
        self.watermark_table.verticalHeader().setVisible(False); self.watermark_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.watermark_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.watermark_table.setMaximumHeight(105)
        self.watermark_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for column in (1,2,3): self.watermark_table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.ResizeToContents)
        self.watermark_table.currentCellChanged.connect(self._watermark_selection_changed); layer_layout.addWidget(self.watermark_table)
        watermark_mode_row=QHBoxLayout(); self.watermark_mode=QComboBox(); self.watermark_mode.addItems(["9:16 全屏覆盖","小 Logo 自定义位置"])
        watermark_mode_row.addWidget(QLabel("覆盖方式")); watermark_mode_row.addWidget(self.watermark_mode,1); layer_layout.addLayout(watermark_mode_row)
        watermark_controls=QHBoxLayout(); self.watermark_position=QComboBox(); self.watermark_position.addItems(["右上角","左上角","右下角","左下角","画面中间"])
        self.watermark_width=QSpinBox(); self.watermark_width.setRange(3,60); self.watermark_width.setValue(18); self.watermark_width.setSuffix(" %")
        self.watermark_opacity=QSpinBox(); self.watermark_opacity.setRange(5,100); self.watermark_opacity.setValue(100); self.watermark_opacity.setSuffix(" %")
        self.watermark_margin=QSpinBox(); self.watermark_margin.setRange(0,300); self.watermark_margin.setValue(28); self.watermark_margin.setSuffix(" px")
        watermark_controls.addWidget(QLabel("位置")); watermark_controls.addWidget(self.watermark_position,1)
        watermark_controls.addWidget(QLabel("宽度")); watermark_controls.addWidget(self.watermark_width)
        watermark_controls.addWidget(QLabel("透明度")); watermark_controls.addWidget(self.watermark_opacity)
        watermark_controls.addWidget(QLabel("边距")); watermark_controls.addWidget(self.watermark_margin); layer_layout.addLayout(watermark_controls)
        self.watermark_mode.currentTextChanged.connect(self._watermark_mode_changed)
        self.watermark_position.currentTextChanged.connect(self._watermark_control_changed)
        for control in (self.watermark_width,self.watermark_opacity,self.watermark_margin): control.valueChanged.connect(self._watermark_control_changed)
        settings_layout.addWidget(layer_group)
        revise_group=QGroupBox("📝 3. 字幕提取与文字编辑"); revise_layout=QVBoxLayout(revise_group); revise_layout.setContentsMargins(9,11,9,8)
        provider_row=QHBoxLayout(); provider_row.addWidget(QLabel("字幕识别服务")); provider_row.addWidget(self.provider,1); revise_layout.addLayout(provider_row)
        self.combination_label=QLabel("当前任务组合：尚未选择视频")
        self.combination_label.setWordWrap(True); self.combination_label.setStyleSheet("color:#67e8f9;background:#0b1830;padding:5px 7px;border-radius:4px;")
        revise_layout.addWidget(self.combination_label)
        queue_title=QLabel("批处理对应队列（序号相同即为同一组任务）")
        queue_title.setStyleSheet("color:#cbd5e1;")
        self.task_queue=QTableWidget(0,4)
        self.task_queue.setHorizontalHeaderLabels(["序号","视频","匹配音频","文案"])
        self.task_queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_queue.setAlternatingRowColors(False); self.task_queue.setMinimumHeight(120)
        self.task_queue.verticalHeader().setVisible(False)
        self.task_queue.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.task_queue.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.task_queue.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.task_queue.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.task_queue.cellClicked.connect(lambda row,_column:self.videos.setCurrentRow(row))
        self.timeline_source_label=QLabel("当前字幕：尚未选择视频")
        self.timeline_source_label.setStyleSheet("color:#facc15;background:#111827;padding:5px 7px;border-radius:4px;")
        self.timeline_source_label.setWordWrap(True); revise_layout.addWidget(self.timeline_source_label)
        timeline_actions=QHBoxLayout(); self.extract_timeline_btn=QPushButton("重新提取选中素材"); self.extract_timeline_btn.setObjectName("primary"); self.extract_timeline_btn.clicked.connect(self.extract_timeline)
        self.extract_all_btn=QPushButton("批量提取全部"); self.extract_all_btn.setStyleSheet("QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669); border-color: #34d399; color: white; font-weight: 700; } QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399, stop:1 #10b981); }"); self.extract_all_btn.clicked.connect(self.extract_all_timelines)
        self.fix_overlap_btn=QPushButton("修正重叠"); self.fix_overlap_btn.setToolTip("批量修正当前 SRT 中后一句提前开始造成的时间重叠")
        self.fix_overlap_btn.clicked.connect(self._fix_current_overlaps)
        load_sidecar=QPushButton("载入 SRT…"); load_sidecar.clicked.connect(self.load_srt_file); timeline_actions.addWidget(self.extract_timeline_btn); timeline_actions.addWidget(self.extract_all_btn); timeline_actions.addWidget(self.fix_overlap_btn); timeline_actions.addWidget(load_sidecar)
        revise_layout.addLayout(timeline_actions)
        timeline_hint=QLabel("语音同步：按时间轴对齐朗读。自由动画：每个视频保存自己的文案；整段固定保留全部手动换行，不限制行数和每屏秒数。")
        timeline_hint.setWordWrap(True); timeline_hint.setStyleSheet("color:#7dd3fc;"); revise_layout.addWidget(timeline_hint)
        self.override_text=QPlainTextEdit(); self.override_text.setMinimumHeight(170); self.override_text.setPlaceholderText("1\n00:00:00,250 --> 00:00:00,780\nPrimeira\n\n2\n00:00:00,790 --> 00:00:01,240\npalavra")
        self.override_text.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;")
        self.override_text.textChanged.connect(self._timeline_text_changed)
        caption_edit_tabs=QTabWidget(); caption_edit_tabs.addTab(self.override_text,"时间轴与字幕")
        proofread_page=QWidget(); proofread_layout=QVBoxLayout(proofread_page); proofread_layout.setContentsMargins(4,4,4,4)
        proofread_hint=QLabel("粘贴正确的源文案，只校对文字内容；识别得到的时间戳与对口型节奏保持不变。")
        proofread_hint.setWordWrap(True); proofread_hint.setStyleSheet("color:#7dd3fc;")
        self.source_proofread=QPlainTextEdit(); self.source_proofread.setPlaceholderText("粘贴完整源文案，不需要时间戳…")
        apply_proofread=QPushButton("按源文案校对字幕（保留时间）"); apply_proofread.setObjectName("primary"); apply_proofread.clicked.connect(self._apply_source_proofread)
        proofread_layout.addWidget(proofread_hint); proofread_layout.addWidget(self.source_proofread,1); proofread_layout.addWidget(apply_proofread)
        caption_edit_tabs.addTab(proofread_page,"源文案校对")
        revise_layout.addWidget(caption_edit_tabs)
        # 视频素材列表和任务对应队列本来就是同一组数据。把任务表移动到左侧“视频”页，
        # 点击一行会同时切换预览、匹配音频和右侧字幕，避免在两个区域重复展示。
        rename_group = QGroupBox("🏷️ 7. 自动重命名（使用文案标题）")
        rename_layout = QVBoxLayout(rename_group); rename_layout.setContentsMargins(9,11,9,8); rename_layout.setSpacing(6)
        self.rename_enabled = QCheckBox("启用自动重命名最终成品")
        self.rename_enabled.setChecked(False)
        rename_layout.addWidget(self.rename_enabled)
        
        rename_form = QFormLayout()
        
        # Prefix presets combo row
        prefix_preset_row = QHBoxLayout()
        self.rename_preset_combo = QComboBox()
        self.rename_preset_combo.setMinimumWidth(100)
        self.rename_preset_combo.currentTextChanged.connect(self._apply_rename_prefix_preset)
        self.rename_preset_save = QPushButton("保存")
        self.rename_preset_save.clicked.connect(self._save_rename_prefix_preset)
        self.rename_preset_delete = QPushButton("删除")
        self.rename_preset_delete.clicked.connect(self._delete_rename_prefix_preset)
        prefix_preset_row.addWidget(self.rename_preset_combo, 1)
        prefix_preset_row.addWidget(self.rename_preset_save)
        prefix_preset_row.addWidget(self.rename_preset_delete)
        rename_form.addRow("前缀方案", prefix_preset_row)

        self.rename_prefix = QLineEdit()
        self.rename_prefix.setPlaceholderText("例如: prefix-")
        rename_form.addRow("前缀", self.rename_prefix)
        
        rename_rule_row = QHBoxLayout()
        import datetime
        self.rename_date_enabled = QCheckBox("日期")
        self.rename_date_enabled.setChecked(True)
        self.rename_date = QLineEdit(datetime.date.today().strftime("%Y%m%d"))
        self.rename_suffix_enabled = QCheckBox("后缀")
        self.rename_suffix_enabled.setChecked(True)
        self.rename_suffix = QLineEdit("FF-PT")
        rename_rule_row.addWidget(self.rename_date_enabled)
        rename_rule_row.addWidget(self.rename_date)
        rename_rule_row.addWidget(self.rename_suffix_enabled)
        rename_rule_row.addWidget(self.rename_suffix)
        rename_form.addRow("命名附加项", rename_rule_row)
        
        rename_num_row = QHBoxLayout()
        self.rename_start_index = QSpinBox()
        self.rename_start_index.setRange(0, 999999)
        self.rename_start_index.setValue(1)
        self.rename_padding = QSpinBox()
        self.rename_padding.setRange(1, 12)
        self.rename_padding.setValue(3)
        rename_num_row.addWidget(QLabel("起始编号"))
        rename_num_row.addWidget(self.rename_start_index)
        rename_num_row.addWidget(QLabel("位数"))
        rename_num_row.addWidget(self.rename_padding)
        rename_num_row.addStretch()
        rename_form.addRow("序列号配置", rename_num_row)
        
        rename_layout.addLayout(rename_form)
        settings_layout.addWidget(rename_group)
        settings_layout.addWidget(hardware_group)

        queue_title.hide(); self.videos.hide()
        vg.insertWidget(0,self.task_queue,1)
        settings_layout.insertWidget(0,revise_group); settings_layout.addStretch(); settings_scroll.setWidget(settings_body)
        self._make_collapsible(revise_group,"captions",True)
        self._make_collapsible(preset_group,"style",True)
        self._make_collapsible(audio_group,"audio_settings",True)
        self._make_collapsible(layer_group,"layers_watermarks",False)
        self._make_collapsible(rename_group,"automatic_rename",False)
        self._make_collapsible(hardware_group,"hardware_acceleration",False)


        # Disable wheel events for all QComboBoxes and QSpinBoxes to prevent accidental scroll changes
        for combo in self.findChildren(QComboBox):
            combo.wheelEvent = lambda event: event.ignore()
        for spin in self.findChildren(QSpinBox):
            spin.wheelEvent = lambda event: event.ignore()

        # 左下角的输出与日志保持窄而完整，不再横跨整个窗口挤压预览。
        output_group=QGroupBox("2. 输出与运行"); og=QVBoxLayout(output_group); og.setContentsMargins(8,10,8,8); og.setSpacing(6)
        outrow=QHBoxLayout(); self.output=QLineEdit(str(default_output_path("dynamic_caption_outputs"))); self.output.setToolTip(self.output.text()); outrow.addWidget(QLabel("输出")); outrow.addWidget(self.output,1)
        choose=QPushButton("选择…"); choose.clicked.connect(self.choose_output); outrow.addWidget(choose); og.addLayout(outrow)
        self.run_status=QLabel("等待任务")
        self.run_status.setWordWrap(False); self.run_status.setMaximumHeight(26)
        self.run_status.setStyleSheet("color:#67e8f9;background:#0b1830;padding:3px 7px;border-radius:4px;font-weight:700;")
        progress_row=QHBoxLayout(); progress_row.addWidget(self.run_status,1)
        self.progress=ProgressSlider(); self.progress.setMinimumWidth(105); self.progress.setMaximumWidth(155)
        self.progress_value=QLabel("0%"); self.progress_value.setFixedWidth(38); self.progress_value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.progress.valueChanged.connect(lambda value:self.progress_value.setText(f"{value}%"))
        progress_row.addWidget(self.progress); progress_row.addWidget(self.progress_value); og.addLayout(progress_row)
        self.cloud_sync_hint=QLabel("未开启：本次只批量生成本地 Reels 成品")
        self.cloud_sync_hint.setWordWrap(False); self.cloud_sync_hint.setStyleSheet("color:#7dd3fc;font-size:11px;")
        self.cloud_sync_check.toggled.connect(self._update_cloud_sync_hint)
        self.cloud_sync_profile.currentTextChanged.connect(self._update_cloud_sync_hint)
        og.addWidget(self.cloud_sync_hint)
        self.output_to_rename=QPushButton("加入批量重命名")
        self.output_to_rename.hide()
        self.log_status=QLabel(); self.log_status.hide()
        self.log=QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMinimumHeight(92); self.log.setMaximumHeight(145)
        self.log.setPlaceholderText("本板块执行日志会显示在这里…")
        self.log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;line-height:1.35;")
        og.addWidget(self.log,1)
        left_layout.addWidget(output_group,0)

        # Proportional sizes based on screen resolution
        screen = QApplication.primaryScreen()
        screen_width = screen.geometry().width() if screen else 1920
        left_w = int(screen_width * 0.23)
        right_w = screen_width - left_w
        preview_w = int(right_w * 0.55)
        settings_w = right_w - preview_w

        # 右侧工作设置区：预览与全部设置等高延伸到底部。
        work_group=QGroupBox("工作设置区 · 实时预览与字幕设计")
        work_group_layout=QVBoxLayout(work_group); work_group_layout.setContentsMargins(7,10,7,7)
        work_splitter=QSplitter(Qt.Orientation.Horizontal); work_splitter.setChildrenCollapsible(False)
        center.setMinimumWidth(380); settings_scroll.setMinimumWidth(400)
        work_splitter.addWidget(center); work_splitter.addWidget(settings_scroll); work_splitter.setSizes([preview_w,settings_w])
        work_splitter.setStretchFactor(0, 3)
        work_splitter.setStretchFactor(1, 2)
        work_group_layout.addWidget(work_splitter)
        workspace.addWidget(left); workspace.addWidget(work_group); workspace.setSizes([left_w,right_w])
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 3); root.addWidget(workspace,1)

        self.preview_thread=None; self.preview_worker=None; self.timeline_thread=None; self.timeline_worker=None
        self._refresh_layer_list(0)
        self._load_layer_schemes(); self._load_all_presets(); self._watermark_mode_changed(self.watermark_mode.currentText())
        self._refresh_task_queue()
        self._caption_mode_changed(self.caption_mode.currentText())
        self._group_sort_mode_changed(self.group_sort_mode.currentText())
        self._restoring_style=True
        try:
            self.apply_preset("Descript 经典黄")
            self._load_style_preferences()
            self._load_rename_prefix_presets()
        finally:
            self._restoring_style=False
        self._connect_live_preview_signals()
        self.refresh_sync_profiles()

    def _show_source_tool(self, index):
        if hasattr(self,"source_stack"):
            self.source_stack.setCurrentIndex(index)
        if hasattr(self,"group_action_panel"):
            self.group_action_panel.setVisible(index == 0)
        for button_index,button in enumerate(getattr(self,"source_tool_buttons",[])):
            button.setChecked(button_index == index)

    def _edit_script_tasks(self, add_empty=False, clipboard_text=""):
        dialog = ScriptTaskDialog(
            self.tts_text.toPlainText(), self,
            add_empty=add_empty, clipboard_text=clipboard_text,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.tts_text.setPlainText(dialog.text())

    def _append_run_log(self,message):
        text=str(message or "").strip()
        if not text: return
        self.log.appendPlainText(text)
        scroll = self.log.verticalScrollBar()
        scroll.setValue(scroll.maximum())
        write_app_log(text, "INFO", "Reels")
        if hasattr(self,"run_status"):
            current=text.splitlines()[0]
            self.run_status.setText(current)
        error_markers=("失败","错误","异常","报错","[WinError","Traceback","Invalid argument","Error ")
        if any(marker.casefold() in text.casefold() for marker in error_markers):
            self._record_error(text)
            if hasattr(self,"log_status"):
                self.log_status.setText("检测到错误，已写入软件日志和 reels_error.log")
                self.log_status.setStyleSheet("color:#fca5a5;font-size:11px;font-weight:700;")
        elif hasattr(self,"log_status"):
            self.log_status.setText(current)

    def _start_timeline_activity(self,label,base=2,cap=90):
        self._timeline_activity_label=str(label)
        self._timeline_activity_started=time.monotonic()
        self._timeline_activity_base=max(0,min(99,int(base)))
        self._timeline_activity_cap=max(self._timeline_activity_base,min(99,int(cap)))
        self.progress.setValue(self._timeline_activity_base)
        self._timeline_activity_timer.start()
        self._timeline_activity_tick()

    def _timeline_activity_tick(self):
        if not self._timeline_activity_label: return
        elapsed=max(0,int(time.monotonic()-self._timeline_activity_started))
        span=max(1,self._timeline_activity_cap-self._timeline_activity_base)
        pulse=min(span-1,elapsed//2)
        self.progress.setValue(self._timeline_activity_base+pulse)
        self.run_status.setText(f"当前状态：正在识别 {self._timeline_activity_label} · 已运行 {elapsed} 秒")

    def _stop_timeline_activity(self,progress=None):
        self._timeline_activity_timer.stop(); self._timeline_activity_label=""
        if progress is not None: self.progress.setValue(max(0,min(100,int(progress))))

    def _error_log_path(self):
        output=Path(self.output.text()).expanduser()
        return output / "reels_error.log"

    def _record_error(self,message):
        write_app_log(message, "ERROR", "Reels")
        try:
            path=self._error_log_path(); path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("a",encoding="utf-8") as handle:
                handle.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{str(message).strip()}\n")
        except OSError:
            pass

    def _show_logs(self):
        dialog=QDialog(self); dialog.setWindowTitle("Reels 运行与错误日志"); dialog.resize(860,560)
        layout=QVBoxLayout(dialog); tabs=QTabWidget()
        runtime=QPlainTextEdit(); runtime.setReadOnly(True); runtime.setPlainText(self.log.toPlainText() or "当前还没有运行日志。")
        runtime.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;")
        errors=QPlainTextEdit(); errors.setReadOnly(True); error_path=self._error_log_path()
        try: error_text=error_path.read_text(encoding="utf-8") if error_path.is_file() else "当前没有错误日志。"
        except OSError as exc: error_text=f"无法读取错误日志：{exc}"
        errors.setPlainText(error_text); errors.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;color:#fca5a5;")
        tabs.addTab(runtime,"运行日志"); tabs.addTab(errors,"错误日志")
        layout.addWidget(tabs,1)
        path_label=QLabel(f"错误日志位置：{error_path}"); path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setStyleSheet("color:#7dd3fc;"); layout.addWidget(path_label)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        dialog.exec()

    def _choose_group_parent(self):
        folder = QFileDialog.getExistingDirectory(self, "选择分组合成父文件夹", self.group_parent.text())
        if folder:
            self.group_parent.setText(folder)
            self._scan_group_parent(folder)
            if self.group_merge_groups: self._open_group_caption_dialog()

    def _clear_group_tasks(self):
        if self.group_merge_thread and self.group_merge_thread.isRunning():
            QMessageBox.information(self,"任务正在运行","请先停止当前分组合成，任务释放后再清空。")
            return
        self.group_parent.clear(); self.group_merge_groups=[]; self.group_scripts={}; self.group_merge_outputs=[]
        self.group_table.setRowCount(0)
        self._loading_group_script=True
        try: self.group_script.clear()
        finally: self._loading_group_script=False
        self.progress.setValue(0); self.run_status.setText("当前状态：等待任务")
        self._append_run_log("已清空分组合成路径、任务列表和分组文案。")

    def _open_group_caption_dialog(self):
        self._save_current_group_script()
        if not self.group_merge_groups:
            self._scan_group_parent(self.group_parent.text())
        if not self.group_merge_groups:
            QMessageBox.information(self,"没有视频组","请先选择或拖入父文件夹。")
            return
        dialog=GroupCaptionDialog(self.group_merge_groups,self.group_scripts,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.group_scripts.update(dialog.scripts())
            current=self.group_table.currentRow()
            if 0<=current<len(self.group_merge_groups):
                folder=self.group_merge_groups[current][0]
                self._loading_group_script=True
                try: self.group_script.setPlainText(self.group_scripts.get(str(folder.resolve()),""))
                finally: self._loading_group_script=False
            self.group_sort_mode.setCurrentText("按分段文案自动匹配")
            self._append_run_log("已保存分组字幕对应表；每行文案将按文件自然顺序对应一个视频片段。")

    def _scan_group_parent(self, folder):
        folder = str(folder or "").strip()
        self._save_current_group_script()
        self.group_merge_groups = discover_groups(folder)
        self.group_table.setRowCount(len(self.group_merge_groups))
        for row, (group_folder, clips) in enumerate(self.group_merge_groups):
            file_names="；".join(Path(clip).name for clip in sorted(clips,key=lambda p:natural_key(Path(p).name)))
            for column, value in enumerate((f"{row + 1:02d}", group_folder.name, str(len(clips)),file_names)):
                item = QTableWidgetItem(value); item.setToolTip(str(group_folder)); self.group_table.setItem(row, column, item)
        if self.group_merge_groups:
            self.group_table.selectRow(0); self.group_table.setCurrentCell(0, 0)
            self.log.appendPlainText(
                f"已扫描 {len(self.group_merge_groups)} 组文件夹，共 {sum(len(clips) for _folder, clips in self.group_merge_groups)} 个视频片段。"
            )
        else:
            self._loading_group_script = True
            try: self.group_script.clear()
            finally: self._loading_group_script = False
            if folder: self.log.appendPlainText("所选目录中没有找到可处理的视频组。")

    def _group_selection_changed(self, current_row, _current_column, previous_row, _previous_column):
        if 0 <= previous_row < len(self.group_merge_groups):
            folder = self.group_merge_groups[previous_row][0]
            self.group_scripts[str(folder.resolve())] = self.group_script.toPlainText()
        self._loading_group_script = True
        try:
            if 0 <= current_row < len(self.group_merge_groups):
                folder = self.group_merge_groups[current_row][0]
                self.group_script.setPlainText(self.group_scripts.get(str(folder.resolve()), ""))
            else:
                self.group_script.clear()
        finally:
            self._loading_group_script = False

    def _save_current_group_script(self):
        if self._loading_group_script or not hasattr(self, "group_table"):
            return
        row = self.group_table.currentRow()
        if 0 <= row < len(self.group_merge_groups):
            folder = self.group_merge_groups[row][0]
            self.group_scripts[str(folder.resolve())] = self.group_script.toPlainText()

    def _group_sort_mode_changed(self, text):
        script_mode = "文案" in str(text)
        self.group_script.setEnabled(script_mode)
        self.group_script.setToolTip(
            "选择一个组后粘贴它的分段文案；段数必须与视频数一致。" if script_mode
            else "文件名自然排序会正确处理 1、2、3…10；裁剪方式可选择智能混合、仅文案或快速声音边界。"
        )

    def start_group_merge(self):
        if self.group_merge_thread and self.group_merge_thread.isRunning():
            return
        self._save_current_group_script()
        if not self.group_merge_groups:
            self._scan_group_parent(self.group_parent.text())
        if not self.group_merge_groups:
            QMessageBox.information(self, "没有视频组", "请选择父文件夹。每个直接子文件夹会作为一组合成任务。")
            return
        if "文案" in self.group_sort_mode.currentText():
            missing = [folder.name for folder, _clips in self.group_merge_groups
                       if not self.group_scripts.get(str(folder.resolve()), "").strip()]
            if missing:
                QMessageBox.information(
                    self, "缺少分段文案", "以下组尚未填写分段文案：\n" + "、".join(missing[:8]) +
                    "\n\n可以补充文案，或切换为“文件名自然排序”。",
                )
                return
        try:
            ffmpeg = self.find_ffmpeg()
        except Exception as exc:
            QMessageBox.critical(self, "缺少组件", str(exc)); return
        output = Path(self.output.text()) / "00_分组合成"
        provider = self.provider.currentText()
        callback = lambda path: self.transcribe_callable(path, provider)
        settings = {
            "sort_mode": "script" if "文案" in self.group_sort_mode.currentText() else "natural",
            "trim_mode": ("hybrid" if "混合" in self.group_trim_mode.currentText()
                          else "text" if "文案" in self.group_trim_mode.currentText() else "fast"),
            "scripts": dict(self.group_scripts),
            "head_padding_ms": self.group_head_padding.value(),
            "tail_padding_ms": self.group_tail_padding.value(),
            "silence_threshold_db": self.group_silence_threshold.value(),
            "silence_min_ms": self.group_silence_min.value(),
            "resume": True,
            "encoder_backend": self.encoder_backend.currentText(),
            "encode_preset": self.encode_preset.currentText(),
            "clean_metadata": self.clean_metadata.isChecked(),
        }
        watermark_fingerprint=watermark_config_fingerprint(self._watermark_entries)
        burn_watermark=bool(self.group_burn_watermark.isChecked() and watermark_fingerprint)
        if self.group_burn_watermark.isChecked() and not watermark_fingerprint:
            self._append_run_log("已勾选合成时烧录水印，但当前没有有效水印图片；本次按无水印合成，最终导出仍可添加水印。")
        settings["burn_watermark"]=burn_watermark
        if burn_watermark:
            watermark_entries=[dict(item) for item in self._watermark_entries]
            settings["watermark_prepare"]=(
                lambda video,cache,entries=watermark_entries:
                str(prepared_watermark_composite(ffmpeg,video,entries,cache))
            )
        self._active_group_watermark_fingerprint=watermark_fingerprint if burn_watermark else ""
        # Lock the user's choice at task start.  Changing the checkbox while a long
        # merge is running must not unexpectedly start or suppress transcription.
        self._group_auto_extract_requested=bool(self.group_auto_timeline.isChecked())
        self._group_auto_extract_pending=False
        self.group_merge_outputs = []
        self.group_merge_thread = QThread(self)
        self.group_merge_worker = GroupMergeWorker(self.group_merge_groups, output, ffmpeg, callback, settings)
        self.group_merge_worker.moveToThread(self.group_merge_thread)
        self.group_merge_thread.started.connect(self.group_merge_worker.run)
        self.group_merge_worker.log.connect(self._append_run_log)
        self.group_merge_worker.progress.connect(self.progress.setValue)
        self.group_merge_worker.item_done.connect(self._group_merge_item_done)
        self.group_merge_worker.finished.connect(self._group_merge_finished)
        self.group_merge_worker.finished.connect(self.group_merge_thread.quit)
        self.group_merge_thread.finished.connect(self._group_merge_ended)
        self.group_merge_thread.finished.connect(self.group_merge_thread.deleteLater)
        self.group_merge_start.setEnabled(False); self.group_merge_stop.setEnabled(True); self.progress.setValue(0)
        if settings["sort_mode"] == "natural":
            if settings["trim_mode"] == "hybrid":
                self._append_run_log("开始智能混合分组合成：文件名自然排序 → 文案首尾定位 → 声音边界修正 → 自动去口气音 → 无缝合成；不核对字幕内容。")
            elif settings["trim_mode"] == "text":
                self._append_run_log("开始文案边界分组合成：文件名自然排序 → 识别每段首词/末词时间 → 自动去口气音 → 无缝合成。")
            else:
                self._append_run_log("开始快速分组合成：文件名自然排序 → 本地检测首尾声音 → 去口气音 → 无缝合成。")
        else:
            self._append_run_log("开始文案匹配合成：识别片段文字 → 按文案排序 → 去口气音 → 无缝合成。")
        self.group_merge_thread.start()

    def stop_group_merge(self):
        if self.group_merge_worker:
            self.group_merge_worker.cancel()
            self.group_merge_stop.setEnabled(False)
            self.run_status.setText("当前状态：正在停止分组合成…")
            self.log.appendPlainText("正在停止当前处理；已完成内容会保留，下次可直接断点续接。")

    def _group_merge_item_done(self, output, group_name, index, total):
        if output not in self.group_merge_outputs:
            self.group_merge_outputs.append(output)
        if self._active_group_watermark_fingerprint and Path(output).is_file():
            key=str(Path(output).resolve())
            self._baked_watermarks[key]={"source":_media_signature(output),
                                         "watermark":self._active_group_watermark_fingerprint}
            QSettings("VideoToolkit","DynamicReels").setValue(
                "baked_watermarks",json.dumps(self._baked_watermarks,ensure_ascii=False))
        self.log.appendPlainText(f"[{index}/{total}] {group_name} 已加入合成结果队列。")

    def _load_group_merge_outputs(self, auto_extract=False):
        outputs = [path for path in self.group_merge_outputs if Path(path).is_file()]
        if not outputs:
            return
        self.videos.clear()
        self._add(self.videos, outputs, VIDEO_EXTENSIONS)

        self._refresh_task_queue()
        # Automatic extraction is deliberately started by _group_merge_ended(),
        # after the merge worker thread is fully released.  This method only loads
        # finished files into the normal video/task queue.

    def _group_merge_finished(self, ok, message):
        if ok:
            try:
                for path in json.loads(message).get("outputs", []):
                    if path not in self.group_merge_outputs: self.group_merge_outputs.append(path)
            except Exception:
                pass
            self.progress.setValue(100); self._load_group_merge_outputs(auto_extract=False)
            self._group_auto_extract_pending=bool(self._group_auto_extract_requested and self.group_merge_outputs)
            self.log.appendPlainText(
                f"分组合成完成：共 {len(self.group_merge_outputs)} 个完整视频。已进入视频队列，"
                + ("线程释放后将继续批量提取字幕。" if self._group_auto_extract_pending else "未启用自动转文字，可稍后手动提取。")
            )
            self.run_status.setText("当前状态：分组合成完成" + ("，等待批量提取字幕" if self._group_auto_extract_pending else ""))
        else:
            self._group_auto_extract_pending=False
            if self.group_merge_outputs:
                # 停止或失败时只保留已完成的视频，不要在后台又启动字幕提取，
                # 否则用户会误以为停止失效，也无法立即开始下一次分组合成。
                self._load_group_merge_outputs(auto_extract=False)
                message += f"\n\n已完成的 {len(self.group_merge_outputs)} 组仍已加入视频队列，可修复后断点续接。"
            if "已停止" in message:
                self._append_run_log(message)
                self.run_status.setText("当前状态：已停止，可直接再次开始并断点续接")
            else:
                QMessageBox.critical(self, "分组合成失败", message)
                self.run_status.setText("当前状态：分组合成失败，请查看日志")

    def _group_merge_ended(self):
        should_extract=bool(self._group_auto_extract_pending)
        self.group_merge_start.setEnabled(True); self.group_merge_stop.setEnabled(False)
        self.group_merge_worker = None; self.group_merge_thread = None
        self._active_group_watermark_fingerprint=""
        self._group_auto_extract_pending=False
        self._append_run_log("分组合成任务已释放，可以直接开始下一次任务。")
        if should_extract:
            self.run_status.setText("当前状态：合成完成，正在批量提取字幕")
            self._append_run_log("已启用“合成并转文字”：现在开始对全部合成成品提取字幕。")
            QTimer.singleShot(0,self.extract_all_timelines)

    def _add(self, widget, paths, extensions):
        existing = {widget.item(i).text() for i in range(widget.count())}
        for path in collect_files(paths, extensions):
            if path not in existing: widget.addItem(path); existing.add(path)
        if widget.count() and widget.currentRow() < 0: widget.setCurrentRow(0)
        if hasattr(self,"audios") and widget is self.audios and self.videos.currentItem():
            QTimer.singleShot(0,self._rematch_current_video)
        if hasattr(self,"task_queue"): QTimer.singleShot(0,self._refresh_task_queue)

    def _clear_media_queue(self, widget):
        widget.clear()
        self._refresh_task_queue()

    def _refresh_task_queue(self):
        if not hasattr(self,"task_queue") or not hasattr(self,"videos"): return
        videos=[self.videos.item(i).text() for i in range(self.videos.count())]
        audios=[self.audios.item(i).text() for i in range(self.audios.count())] if hasattr(self,"audios") else []
        mode=self.audio_match_mode.currentText() if hasattr(self,"audio_match_mode") else "自动匹配（同名优先，其次按队列）"
        matcher=CaptionWorker(videos,audios,Path("."),"",None,{"audio_match_mode":mode})
        self.task_queue.setRowCount(len(videos))
        for row,video in enumerate(matcher.videos):
            audio,reason=matcher._audio_selection(video,row)
            offset_ms=int(self.audio_offsets.get(self._timeline_key(str(audio)),0)) if hasattr(self,"audio_offsets") else 0
            if audio.resolve()!=video.resolve() and offset_ms:
                reason+=f"，起点 {self._clock(offset_ms)}"
            video_key=self._timeline_key(str(video))
            if hasattr(self,"caption_mode") and self.caption_mode.currentText()=="自由文案动画（不对口型）":
                text_state="已填写" if self.free_texts.get(video_key,"").strip() else "待填写"
            else:
                audio_key=self._timeline_key(str(audio))
                text_state="已提取" if (self.timeline_overrides.get(audio_key,"").strip() or self.timeline_words.get(audio_key,"")) else "待提取"
            values=(f"{row+1:02d}",video.name,f"{audio.name}（{reason}）",text_state)
            for column,value in enumerate(values):
                item=QTableWidgetItem(value); item.setToolTip(value); self.task_queue.setItem(row,column,item)

    def _load_microsoft_voices(self):
        self.tts_voice.clear()
        self.tts_voice.addItems([
            "pt-PT-RaquelNeural", "pt-PT-DuarteNeural",
            "pt-BR-FranciscaNeural", "pt-BR-AntonioNeural",
            "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "en-US-JennyNeural",
        ])
        self.tts_voice.setToolTip("pt-PT 是欧洲葡萄牙语；pt-BR 是巴西葡萄牙语。")

    def _load_gemini_voices(self):
        self.tts_voice.clear()
        self.tts_voice.addItems([
            "Kore｜温暖沉稳女声", "Aoede｜自然明亮女声", "Leda｜年轻清晰女声",
            "Callirrhoe｜轻柔女声", "Sulafat｜温暖叙事女声", "Puck｜活泼男声",
            "Charon｜沉稳男声", "Fenrir｜有力男声", "Orus｜成熟男声",
            "Enceladus｜轻柔气声", "Achernar｜柔和自然", "Gacrux｜成熟稳重",
        ])
        self.tts_voice.setToolTip("Gemini 官方预置音色；可使用现有 Gemini 密钥轮询生成。")

    def load_video_preview(self, path, external_audio="", precise=False, mix_audio=False, audio_offset_ms=0):
        if not path or not Path(path).is_file(): return
        self._precise_preview_active = bool(precise)
        if self.preview_capture is not None:
            self.preview_capture.release()
        self.preview_capture = None
        self.preview_base_image = QImage(); self.seek.setRange(0,0)
        self._preview_external_audio = bool(external_audio and Path(external_audio).is_file())
        self._preview_audio_offset_ms = max(0,int(audio_offset_ms)) if self._preview_external_audio else 0
        self.audio_output.setVolume(
            self.original_volume.value()/100 if self._preview_external_audio and mix_audio else
            (0 if self._preview_external_audio else .65))
        self.player.setSource(QUrl.fromLocalFile(path)); self.player.play()
        if self._preview_external_audio:
            self.audio_player.setSource(QUrl.fromLocalFile(external_audio))
            self.audio_preview_output.setVolume(
                self.background_volume.value()/100 if mix_audio else .8)
            self.audio_player.setPosition(self._preview_audio_offset_ms); self.audio_player.play(); self.audio_play_btn.setText("暂停配音")
        else:
            self.audio_player.pause()
        self.preview_frame_timer.stop(); self._seek_preview(0); self.play_btn.setText("暂停")

    def toggle_preview(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            if self._preview_external_audio: self.audio_player.pause()
            self.play_btn.setText("播放")
        else:
            if self._preview_external_audio:
                self.audio_player.setPosition(self.player.position()+self._preview_audio_offset_ms); self.audio_player.play()
            self.player.play(); self.play_btn.setText("暂停")

    def _seek_preview(self, milliseconds):
        self.player.setPosition(int(milliseconds))
        if self._preview_external_audio:
            self.audio_player.setPosition(int(milliseconds)+self._preview_audio_offset_ms)
        # QVideoSink 会在跳转完成后送来对应帧；短暂等待期间保留上一帧，不阻塞界面。

    def _video_frame_changed(self, frame):
        if not frame or not frame.isValid(): return
        image = frame.toImage()
        if image.isNull(): return
        self.preview_base_image = image.copy()
        # Drop obsolete decoded frames instead of queueing a full subtitle paint
        # for every callback. The newest frame is displayed at about 30 FPS.
        if not self.live_refresh_timer.isActive():
            self.live_refresh_timer.start()

    def _display_cached_preview(self):
        if self.preview_base_image.isNull():
            return
        # 先缩到预览控件尺寸再绘制字幕，避免每帧在 1080x1920 原图上做昂贵的路径绘制。
        image = self.preview_base_image.scaled(
            self.video_widget.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation)
        if getattr(self, "live_preview", None) and self.live_preview.isChecked() and not self._precise_preview_active:
            self._paint_live_layers(image, self.player.position() / 1000)
        self.video_widget.setPixmap(QPixmap.fromImage(image))

    def _render_preview_frame(self, force=False, target_override=None):
        capture = self.preview_capture
        if capture is None or not capture.isOpened(): return
        target = int(target_override) if target_override is not None else self.player.position()
        current = capture.get(cv2.CAP_PROP_POS_MSEC)
        if force or abs(current - target) > 220:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, target))
        ok, frame = capture.read()
        if not ok:
            self.preview_frame_timer.stop(); return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
        if getattr(self, "live_preview", None) and self.live_preview.isChecked() and not self._precise_preview_active:
            self._paint_live_layers(image, target / 1000)
        pixmap = QPixmap.fromImage(image).scaled(
            self.video_widget.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.video_widget.setPixmap(pixmap)

    def _connect_live_preview_signals(self):
        for control in (self.font, self.position, self.free_animation, self.caption_mode,
                        self.audio_match_mode, self.audio_mode, self.audio_fade_mode,
                        self.encoder_backend, self.encode_preset,
                        self.watermark_mode, self.watermark_position):
            control.currentTextChanged.connect(self._refresh_live_preview)
            control.currentTextChanged.connect(self._save_style_preferences)
        for control in (self.font_size, self.line_length, self.line_width, self.letter_spacing, self.word_spacing,
                        self.line_spacing, self.max_words, self.highlight_padding, self.highlight_padding_y,
                        self.animation_speed, self.outline_width, self.margin_v, self.free_page_seconds,
                        self.original_volume, self.background_volume,self.audio_fade_in,self.audio_fade_out,
                        self.watermark_width, self.watermark_opacity, self.watermark_margin):
            control.valueChanged.connect(self._refresh_live_preview)
            control.valueChanged.connect(self._save_style_preferences)
        self.clean_metadata.toggled.connect(self._save_style_preferences)
        self.rename_enabled.toggled.connect(self._save_style_preferences)
        self.rename_prefix.textChanged.connect(self._save_style_preferences)
        self.rename_date_enabled.toggled.connect(self._save_style_preferences)
        self.rename_date.textChanged.connect(self._save_style_preferences)
        self.rename_suffix_enabled.toggled.connect(self._save_style_preferences)
        self.rename_suffix.textChanged.connect(self._save_style_preferences)
        self.rename_start_index.valueChanged.connect(self._save_style_preferences)
        self.rename_padding.valueChanged.connect(self._save_style_preferences)
        self.group_burn_watermark.toggled.connect(self._save_style_preferences)
        self.output.textChanged.connect(self._save_style_preferences)
        self.override_text.textChanged.connect(self._refresh_live_preview)

    def _style_settings_store(self):
        return QSettings("VideoToolkit","DynamicReels")

    def _load_all_presets(self):
        from PySide6.QtWidgets import QListWidgetItem
        store = QSettings("VideoToolkit", "DynamicReels")
        saved_presets_json = store.value("presets_list_json", "")
        
        self.preset_list_widget.clear()
        self.preset_buttons = []
        
        self.all_presets = []
        if saved_presets_json:
            try:
                self.all_presets = json.loads(saved_presets_json)
            except Exception:
                pass
                
        if not self.all_presets:
            for name, preset_dict in PRESETS.items():
                self.all_presets.append({
                    "name": name,
                    "is_custom": False,
                    "data": preset_dict
                })
            store.setValue("presets_list_json", json.dumps(self.all_presets, ensure_ascii=False))
            
        for index, item in enumerate(self.all_presets):
            name = item["name"]
            is_custom = item["is_custom"]
            data = item["data"]
            
            if is_custom:
                repr_preset = {
                    "text": data.get("text_color", "#FFFFFF"),
                    "outline": data.get("outline_color", "#111827"),
                    "highlight": data.get("highlight_color", "#8B5CF6"),
                    "outline_width": data.get("outline_width", 3),
                    "effect": data.get("free_animation", "word_color"),
                    "font": data.get("font", "Arial"),
                    "font_size": data.get("font_size", 58)
                }
                anim = repr_preset["effect"]
                if anim == "卡点单行":
                    repr_preset["effect"] = "descript"
                elif anim == "逐字弹出":
                    repr_preset["effect"] = "pop"
                elif anim == "逐字渐出":
                    repr_preset["effect"] = "glow"
                elif anim == "智能卡点":
                    repr_preset["effect"] = "highlight"
                else:
                    repr_preset["effect"] = "word_color"
            else:
                repr_preset = data
                
            button = PresetPreviewButton(name, repr_preset)
            button.clicked.connect(lambda checked=False, idx=index: self._apply_preset_by_index(idx))
            self.preset_buttons.append(button)
            
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(1, 1, 1, 1)
            item_layout.setSpacing(4)
            
            # Drag handle on the left
            handle = DragHandleWidget(self.preset_list_widget)
            item_layout.addWidget(handle)
            
            # Preview button fills the rest
            item_layout.addWidget(button, 1)
            
            list_item = QListWidgetItem(self.preset_list_widget)
            list_item.setSizeHint(item_widget.sizeHint())
            self.preset_list_widget.addItem(list_item)
            self.preset_list_widget.setItemWidget(list_item, item_widget)

    def _preset_order_changed(self):
        new_presets = []
        for i in range(self.preset_list_widget.count()):
            list_item = self.preset_list_widget.item(i)
            item_widget = self.preset_list_widget.itemWidget(list_item)
            if not item_widget:
                continue
            button = item_widget.findChild(PresetPreviewButton)
            if button:
                for item in self.all_presets:
                    if item["name"] == button.name:
                        new_presets.append(item)
                        break
        self.all_presets = new_presets
        store = QSettings("VideoToolkit", "DynamicReels")
        store.setValue("presets_list_json", json.dumps(self.all_presets, ensure_ascii=False))
        self._load_all_presets()

    def _show_preset_context_menu(self, pos):
        item = self.preset_list_widget.itemAt(pos)
        if not item:
            return
        item_widget = self.preset_list_widget.itemWidget(item)
        if not item_widget:
            return
        button = item_widget.findChild(PresetPreviewButton)
        if not button:
            return
        name = button.name
        
        preset_item = next((x for x in self.all_presets if x["name"] == name), None)
        if not preset_item:
            return
            
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        
        apply_action = menu.addAction("应用该预设")
        export_action = menu.addAction("导出为 JSON 文件")
        delete_action = menu.addAction("删除预设")
            
        action = menu.exec(self.preset_list_widget.mapToGlobal(pos))
        if action == apply_action:
            idx = next((i for i, x in enumerate(self.all_presets) if x["name"] == name), -1)
            if idx != -1:
                self._apply_preset_by_index(idx)
        elif action == export_action:
            for btn in self.preset_buttons:
                btn.setChecked(btn.name == name)
            self._export_selected_preset()
        elif action == delete_action:
            idx = next((i for i, x in enumerate(self.all_presets) if x["name"] == name), -1)
            if idx != -1:
                self._delete_preset_by_index(idx)

    def _apply_preset_by_index(self, idx):
        if idx < 0 or idx >= len(self.all_presets):
            return
        item = self.all_presets[idx]
        name = item["name"]
        for btn in self.preset_buttons:
            btn.setChecked(btn.name == name)
        if item["is_custom"]:
            self._apply_style_template_data(item["data"])
            self._append_run_log(f"已应用自定义预设：{name}")
        else:
            self.apply_preset(name)

    def _delete_preset_by_index(self, idx):
        if idx < 0 or idx >= len(self.all_presets):
            return
        name = self.all_presets[idx]["name"]
        if QMessageBox.question(self, "删除预设", f"确定要删除预设“{name}”吗？") != QMessageBox.StandardButton.Yes:
            return
        self.all_presets.pop(idx)
        store = QSettings("VideoToolkit", "DynamicReels")
        store.setValue("presets_list_json", json.dumps(self.all_presets, ensure_ascii=False))
        self._load_all_presets()
        self._append_run_log(f"已删除预设：{name}")

    def _save_current_preset(self):
        name, ok = QInputDialog.getText(self, "保存预设", "请输入预设名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        for item in self.all_presets:
            if item["name"] == name:
                if QMessageBox.question(self, "覆盖预设", f"已存在名为“{name}”的预设，是否覆盖？") != QMessageBox.StandardButton.Yes:
                    return
                self.all_presets.remove(item)
                break
        snapshot = self._style_template_snapshot()
        self.all_presets.insert(0, {
            "name": name,
            "is_custom": True,
            "data": snapshot
        })
        store = QSettings("VideoToolkit", "DynamicReels")
        store.setValue("presets_list_json", json.dumps(self.all_presets, ensure_ascii=False))
        self._load_all_presets()
        self._append_run_log(f"已保存自定义预设：{name}")

    def _import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入字幕样式预设", "", "样式预设 (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            name = data.get("preset_name", Path(path).stem)
            if "preset_name" not in data and "style" in data:
                data = data["style"]
            for item in self.all_presets:
                if item["name"] == name:
                    if QMessageBox.question(self, "覆盖预设", f"已存在名为“{name}”的预设，是否覆盖？") != QMessageBox.StandardButton.Yes:
                        return
                    self.all_presets.remove(item)
                    break
            self.all_presets.insert(0, {
                "name": name,
                "is_custom": True,
                "data": data
            })
            store = QSettings("VideoToolkit", "DynamicReels")
            store.setValue("presets_list_json", json.dumps(self.all_presets, ensure_ascii=False))
            self._load_all_presets()
            self._append_run_log(f"已成功导入预设：{name}")
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", f"无法解析预设文件：{exc}")

    def _export_selected_preset(self):
        selected_name = next((btn.name for btn in self.preset_buttons if btn.isChecked()), None)
        if not selected_name:
            QMessageBox.information(self, "未选择预设", "请先在右侧预设列表中点击选中一个要导出的预设。")
            return
        preset_item = next((item for item in self.all_presets if item["name"] == selected_name), None)
        if not preset_item:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出字幕样式预设", f"{selected_name}.json", "样式预设 (*.json)")
        if not path:
            return
        try:
            if preset_item["is_custom"]:
                export_data = dict(preset_item["data"])
            else:
                export_data = self._style_template_snapshot()
                export_data["preset"] = selected_name
            export_data["preset_name"] = selected_name
            Path(path).write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._append_run_log(f"已成功导出预设到：{Path(path).name}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"无法保存预设文件：{exc}")

    def _style_template_snapshot(self):
        """Return portable visual settings only; media/timelines never enter a template."""
        values=self._style_preferences()
        allowed={
            "preset","font","font_size","caption_mode","free_animation","free_page_seconds",
            "line_length","line_width","letter_spacing","word_spacing","line_spacing","max_words",
            "highlight_padding","highlight_padding_y","animation_speed","outline_width","position","margin_v",
            "text_color","outline_color","highlight_color","watermark_mode",
            "watermark_position","watermark_width","watermark_opacity","watermark_margin",
        }
        result={key:value for key,value in values.items() if key in allowed}
        result["layers"]=json.loads(json.dumps(self.layers,ensure_ascii=False))
        result["watermarks"]=json.loads(json.dumps(self._watermark_entries,ensure_ascii=False))
        return result

    def _apply_style_template_data(self,saved):
        if not isinstance(saved,dict): raise ValueError("模板内容不是有效对象")
        previous=self._restoring_style; self._restoring_style=True
        try:
            preset=saved.get("preset")
            if preset in PRESETS: self.apply_preset(preset)
            combos={"font":self.font,"caption_mode":self.caption_mode,"free_animation":self.free_animation,
                    "position":self.position,"watermark_mode":self.watermark_mode,
                    "watermark_position":self.watermark_position}
            spins={"font_size":self.font_size,"free_page_seconds":self.free_page_seconds,
                   "line_length":self.line_length,"line_width":self.line_width,
                   "letter_spacing":self.letter_spacing,"word_spacing":self.word_spacing,
                   "line_spacing":self.line_spacing,"max_words":self.max_words,
                   "highlight_padding":self.highlight_padding,"highlight_padding_y":self.highlight_padding_y,
                   "animation_speed":self.animation_speed,"outline_width":self.outline_width,
                   "margin_v":self.margin_v,"watermark_width":self.watermark_width,
                   "watermark_opacity":self.watermark_opacity,"watermark_margin":self.watermark_margin}
            for key,control in combos.items():
                if key in saved: control.setCurrentText(str(saved[key]))
            for key,control in spins.items():
                if key in saved:
                    try: control.setValue(int(saved[key]))
                    except (TypeError,ValueError): pass
            for button,label,key in ((self.text_color,"文字","text_color"),(self.outline_color,"描边","outline_color"),
                                     (self.highlight_color,"跟读","highlight_color")):
                color=str(saved.get(key,""))
                if re.fullmatch(r"#[0-9A-Fa-f]{6}",color): button.setText(f"{label} {color.upper()}")
            if isinstance(saved.get("layers"),list):
                self.layers=json.loads(json.dumps(saved["layers"],ensure_ascii=False))
                if not any(item.get("type")=="caption" for item in self.layers if isinstance(item,dict)):
                    self.layers.append({"type":"caption","name":"字幕层"})
                self._mask_counter=sum(1 for item in self.layers if item.get("type")=="mask")
                self._text_counter=sum(1 for item in self.layers if item.get("type")=="text")
                self._refresh_layer_list(0)
            if isinstance(saved.get("watermarks"),list):
                entries=[]; images=[]; missing=[]
                for item in saved["watermarks"]:
                    path=str(item.get("path", "")) if isinstance(item,dict) else ""
                    image=QImage(path) if path and Path(path).is_file() else QImage()
                    if image.isNull():
                        if path: missing.append(path)
                        continue
                    entries.append(dict(item)); images.append(image)
                self._watermark_entries=entries; self._watermark_paths=[item["path"] for item in entries]
                self._watermark_images=images; self._watermark_image=images[0] if images else QImage()
                summary="；".join(Path(path).name for path in self._watermark_paths)
                self.company_watermark.setText(f"已添加 {len(entries)} 张：{summary}" if summary else "")
                self.company_watermark.setToolTip("\n".join(self._watermark_paths)); self._refresh_watermark_table(0)
                if missing: self._append_run_log("模板中的水印文件在本机不存在，已跳过："+"；".join(missing))
        finally:
            self._restoring_style=previous
        self._sync_preview_margin(self.margin_v.value()); self.update_style_preview(); self._refresh_live_preview()
        self._save_style_preferences()


    def _load_rename_prefix_presets(self):
        try:
            presets = json.loads(self._style_settings_store().value("rename_prefix_presets", "{}") or "{}")
        except Exception:
            presets = {}
        if not isinstance(presets, dict): presets = {}
        self._rename_prefix_presets = presets
        self.rename_preset_combo.blockSignals(True)
        self.rename_preset_combo.clear()
        self.rename_preset_combo.addItems(sorted(self._rename_prefix_presets.keys()))
        self.rename_preset_combo.setCurrentText("")
        self.rename_preset_combo.blockSignals(False)

    def _save_rename_prefix_preset(self):
        name, ok = QInputDialog.getText(self, "保存前缀方案", "请输入方案名称:")
        if not ok or not name.strip(): return
        name = name.strip()
        prefix = self.rename_prefix.text()
        self._rename_prefix_presets[name] = prefix
        self._style_settings_store().setValue("rename_prefix_presets", json.dumps(self._rename_prefix_presets, ensure_ascii=False))
        self._load_rename_prefix_presets()
        self.rename_preset_combo.setCurrentText(name)

    def _delete_rename_prefix_preset(self):
        name = self.rename_preset_combo.currentText()
        if not name or name not in self._rename_prefix_presets: return
        self._rename_prefix_presets.pop(name)
        self._style_settings_store().setValue("rename_prefix_presets", json.dumps(self._rename_prefix_presets, ensure_ascii=False))
        self._load_rename_prefix_presets()

    def _apply_rename_prefix_preset(self, name):
        if name in self._rename_prefix_presets:
            self.rename_prefix.setText(self._rename_prefix_presets[name])









    def _load_saved_font_files(self):
        folder=render_font_dir()
        if not folder.is_dir(): return
        for path in folder.iterdir():
            if path.suffix.casefold() in (".ttf",".otf",".ttc"):
                QFontDatabase.addApplicationFont(str(path))

    def _refresh_font_families(self,preferred=""):
        if not hasattr(self,"font"): return
        current=preferred or self.font.currentText(); self.font.blockSignals(True)
        self.font.clear(); self.font.addItems(QFontDatabase.families())
        if current and self.font.findText(current)>=0: self.font.setCurrentText(current)
        elif self.font.findText("Arial")>=0: self.font.setCurrentText("Arial")
        self.font.blockSignals(False); self._refresh_live_preview()

    def _register_font_files(self,paths):
        families=[]
        for path in paths:
            font_id=QFontDatabase.addApplicationFont(str(path))
            if font_id>=0: families.extend(QFontDatabase.applicationFontFamilies(font_id))
        self._refresh_font_families(families[0] if families else "")
        return families

    def _import_local_fonts(self):
        paths,_=QFileDialog.getOpenFileNames(self,"导入本地字体","","字体 (*.ttf *.otf *.ttc)")
        if not paths: return
        folder=custom_font_dir(); folder.mkdir(parents=True,exist_ok=True); copied=[]; failures=[]
        for source in map(Path,paths):
            try:
                target=folder/source.name
                if source.resolve()!=target.resolve(): shutil.copy2(source,target)
                copied.append(str(target))
            except Exception as exc: failures.append(f"{source.name}：{exc}")
        families=self._register_font_files(copied)
        write_app_log(f"已导入本地字体：{'、'.join(families) if families else len(copied)}", "INFO", "字体管理")
        if failures: write_app_log("字体导入失败："+"｜".join(failures), "ERROR", "字体管理")

    def _open_source_font_library(self):
        dialog=QDialog(self); dialog.setWindowTitle("开源字体库（首次下载，之后离线使用）"); dialog.resize(620,420)
        layout=QVBoxLayout(dialog)
        note=QLabel("字体来自 Google Fonts 官方仓库。全部列出许可证；下载后保存在软件字体目录，可用于实时预览和 FFmpeg 字幕烧录。")
        note.setWordWrap(True); note.setStyleSheet("color:#7dd3fc;"); layout.addWidget(note)
        choices=QListWidget(); choices.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for name,(_filename,_url,license_name) in OPEN_SOURCE_FONTS.items(): choices.addItem(f"{name}　｜　{license_name}")
        layout.addWidget(choices,1)
        actions=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("下载并安装选中字体")
        actions.accepted.connect(dialog.accept); actions.rejected.connect(dialog.reject); layout.addWidget(actions)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        rows=[index.row() for index in choices.selectedIndexes()]
        names=list(OPEN_SOURCE_FONTS)
        selected=[names[row] for row in rows if 0<=row<len(names)]
        if not selected:
            write_app_log("未选择开源字体，已取消下载。", "INFO", "字体管理")
            return
        self.font_download_thread=QThread(self); self.font_download_worker=FontDownloadWorker(selected)
        self.font_download_worker.moveToThread(self.font_download_thread)
        self.font_download_thread.started.connect(self.font_download_worker.run)
        self.font_download_worker.finished.connect(self._font_download_done)
        self.font_download_worker.finished.connect(self.font_download_thread.quit)
        self.font_download_thread.finished.connect(self.font_download_thread.deleteLater)
        write_app_log(f"开始下载 {len(selected)} 个开源字体。", "INFO", "字体管理")
        self.font_download_thread.start()

    def _font_download_done(self,ok,message,paths):
        families=self._register_font_files(paths) if paths else []
        write_app_log(message+(f"｜可用字体：{'、'.join(families)}" if families else ""), "INFO" if ok else "ERROR", "字体管理")

    def _style_preferences(self):
        preset=next((button.text() for button in self.preset_buttons if button.isChecked()),"Descript 经典黄")
        return {
            "preset":preset,"font":self.font.currentText(),"font_size":self.font_size.value(),
            "caption_mode":self.caption_mode.currentText(),"free_animation":self.free_animation.currentText(),
            "free_page_seconds":self.free_page_seconds.value(),"line_length":self.line_length.value(),
            "line_width":self.line_width.value(),"letter_spacing":self.letter_spacing.value(),
            "word_spacing":self.word_spacing.value(),
            "line_spacing":self.line_spacing.value(),"max_words":self.max_words.value(),
            "highlight_padding":self.highlight_padding.value(),"highlight_padding_y":self.highlight_padding_y.value(),
            "animation_speed":self.animation_speed.value(),
            "outline_width":self.outline_width.value(),"position":self.position.currentText(),
            "margin_v":self.margin_v.value(),"audio_match_mode":self.audio_match_mode.currentText(),
            "audio_mode":self.audio_mode.currentText(),"encoder_backend":self.encoder_backend.currentText(),
            "original_volume":self.original_volume.value(),"background_volume":self.background_volume.value(),
            "audio_fade_mode":self.audio_fade_mode.currentText(),
            "audio_fade_in_ms":self.audio_fade_in.value(),"audio_fade_out_ms":self.audio_fade_out.value(),
            "encode_preset":self.encode_preset.currentText(),"clean_metadata":self.clean_metadata.isChecked(),
            "watermark_mode":self.watermark_mode.currentText(),"watermark_position":self.watermark_position.currentText(),
            "watermark_width":self.watermark_width.value(),"watermark_opacity":self.watermark_opacity.value(),
            "watermark_margin":self.watermark_margin.value(),"text_color":self._hex(self.text_color),
            "outline_color":self._hex(self.outline_color),"highlight_color":self._hex(self.highlight_color),
            "audio_offsets":dict(self.audio_offsets),
            "rename_enabled": self.rename_enabled.isChecked(),
            "rename_prefix": self.rename_prefix.text(),
            "rename_date_enabled": self.rename_date_enabled.isChecked(),
            "rename_date": self.rename_date.text(),
            "rename_suffix_enabled": self.rename_suffix_enabled.isChecked(),
            "rename_suffix": self.rename_suffix.text(),
            "rename_start_index": self.rename_start_index.value(),
            "rename_padding": self.rename_padding.value(),
            "group_burn_watermark": self.group_burn_watermark.isChecked(),
            "watermark_paths": list(self._watermark_paths),
            "watermarks": [dict(item) for item in self._watermark_entries],
            "timeline_chinese": dict(self.timeline_chinese),
            "output_dir": self.output.text(),
        }

    def _save_style_preferences(self,*_args):
        if self._restoring_style or os.environ.get("VIDEO_TOOLKIT_DISABLE_STYLE_MEMORY")=="1": return
        self._style_settings_store().setValue("style_preferences",json.dumps(self._style_preferences(),ensure_ascii=False))

    def _load_style_preferences(self):
        if os.environ.get("VIDEO_TOOLKIT_DISABLE_STYLE_MEMORY")=="1": return
        raw=self._style_settings_store().value("style_preferences","")
        if not raw: return
        try: saved=json.loads(raw)
        except Exception: return
        # Early preview builds briefly wrote constructor defaults before the preset was applied.
        # Treat that exact combination as "no user preference" so the intended product defaults remain intact.
        if (saved.get("preset")=="Descript 经典黄" and saved.get("font_size")==58 and
                saved.get("letter_spacing")==0 and saved.get("line_spacing")==116 and saved.get("margin_v")==250):
            return
        preset=saved.get("preset")
        if preset in PRESETS: self.apply_preset(preset)
        combos={"font":self.font,"caption_mode":self.caption_mode,"free_animation":self.free_animation,
                "position":self.position,"audio_match_mode":self.audio_match_mode,"audio_mode":self.audio_mode,
                "audio_fade_mode":self.audio_fade_mode,
                "encoder_backend":self.encoder_backend,"encode_preset":self.encode_preset,
                "watermark_mode":self.watermark_mode,"watermark_position":self.watermark_position}
        spins={"font_size":self.font_size,"free_page_seconds":self.free_page_seconds,"line_length":self.line_length,
               "line_width":self.line_width,"letter_spacing":self.letter_spacing,"word_spacing":self.word_spacing,
               "line_spacing":self.line_spacing,"max_words":self.max_words,"highlight_padding":self.highlight_padding,
               "highlight_padding_y":self.highlight_padding_y,"animation_speed":self.animation_speed,
               "outline_width":self.outline_width,"margin_v":self.margin_v,"watermark_width":self.watermark_width,
               "original_volume":self.original_volume,"background_volume":self.background_volume,
               "audio_fade_in_ms":self.audio_fade_in,"audio_fade_out_ms":self.audio_fade_out,
               "watermark_opacity":self.watermark_opacity,"watermark_margin":self.watermark_margin}
        for key,control in combos.items():
            if key in saved: control.setCurrentText(str(saved[key]))
        for key,control in spins.items():
            if key in saved:
                try: control.setValue(float(saved[key]) if isinstance(control.value(),float) else int(saved[key]))
                except (TypeError,ValueError): pass
        self.clean_metadata.setChecked(bool(saved.get("clean_metadata",self.clean_metadata.isChecked())))
        offsets=saved.get("audio_offsets",{})
        if isinstance(offsets,dict):
            self.audio_offsets={str(key):max(0,int(value)) for key,value in offsets.items()
                                if str(value).lstrip("-").isdigit()}
        colors=((self.text_color,"文字",saved.get("text_color")),(self.outline_color,"描边",saved.get("outline_color")),
                (self.highlight_color,"跟读",saved.get("highlight_color")))
        for button,label,color in colors:
            if color and re.fullmatch(r"#[0-9A-Fa-f]{6}",str(color)): button.setText(f"{label} {str(color).upper()}")
        if "rename_enabled" in saved:
            self.rename_enabled.setChecked(bool(saved["rename_enabled"]))
        if "rename_prefix" in saved:
            self.rename_prefix.setText(str(saved["rename_prefix"]))
        if "rename_date_enabled" in saved:
            self.rename_date_enabled.setChecked(bool(saved["rename_date_enabled"]))
        if "rename_date" in saved:
            self.rename_date.setText(str(saved["rename_date"]))
        if "rename_suffix_enabled" in saved:
            self.rename_suffix_enabled.setChecked(bool(saved["rename_suffix_enabled"]))
        if "rename_suffix" in saved:
            self.rename_suffix.setText(str(saved["rename_suffix"]))
        if "rename_start_index" in saved:
            self.rename_start_index.setValue(int(saved["rename_start_index"]))
        if "rename_padding" in saved:
            self.rename_padding.setValue(int(saved["rename_padding"]))
        if "group_burn_watermark" in saved:
            self.group_burn_watermark.setChecked(bool(saved["group_burn_watermark"]))
            
        if "output_dir" in saved and saved["output_dir"]:
            self.output.setText(str(saved["output_dir"]))
            self.output.setToolTip(str(saved["output_dir"]))
            
        watermark_paths = saved.get("watermark_paths", [])
        watermark_entries = saved.get("watermarks", [])
        if isinstance(watermark_paths, list) and isinstance(watermark_entries, list):
            valid_paths = []
            valid_images = []
            valid_entries = []
            for path, entry in zip(watermark_paths, watermark_entries):
                if Path(path).is_file():
                    img = QImage(path)
                    if not img.isNull():
                        valid_paths.append(path)
                        valid_images.append(img)
                        valid_entries.append(entry)
            self._watermark_paths = valid_paths
            self._watermark_images = valid_images
            self._watermark_entries = valid_entries
            self._watermark_image = self._watermark_images[0] if self._watermark_images else QImage()
            summary = "；".join(Path(path).name for path in self._watermark_paths)
            self.company_watermark.setText(f"已添加 {len(self._watermark_paths)} 张：{summary}" if summary else "")
            self.company_watermark.setToolTip("\n".join(self._watermark_paths))
            self._refresh_watermark_table()
            
        timeline_chinese = saved.get("timeline_chinese", {})
        if isinstance(timeline_chinese, dict):
            self.timeline_chinese = {str(k): str(v) for k, v in timeline_chinese.items()}

        self._sync_preview_margin(self.margin_v.value()); self.update_style_preview(); self._refresh_live_preview()

    def _refresh_live_preview(self, *_args):
        # 预览只重绘缓存画面，不重新解码视频；参数变化后立即同步。
        self._live_caption_style_cache=None
        self._live_timeline_cache_key=None
        self._live_watermark_cache=None
        if hasattr(self,"preview_base_image") and not self.preview_base_image.isNull():
            self._display_cached_preview()

    def _live_caption_data(self, seconds):
        phrase_srt = self.override_text.toPlainText().strip() if hasattr(self, "override_text") else ""
        source = self._timeline_source() if hasattr(self, "audios") else ""
        word_srt = self.timeline_words.get(self._timeline_key(source), "") if source else ""
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            duration=max(8.0,(self.player.duration() or 0)/1000)
            settings=(self._live_caption_style_cache or {}).get("settings") or self._current_settings()
            phrase_srt=free_caption_srt(phrase_srt,duration,settings)
            word_srt=""
        if phrase_srt and "-->" not in phrase_srt:
            phrase_srt = ""
        if not phrase_srt and word_srt:
            phrase_srt = group_word_srt(word_srt, max_chars=max(18, self.line_length.value() * 2),
                                        max_words=self.max_words.value())
        cache_key=(phrase_srt,word_srt)
        if cache_key != self._live_timeline_cache_key:
            self._live_timeline_cache_key=cache_key
            self._live_timeline_cache=(parse_srt(phrase_srt) if phrase_srt else [],
                                       parse_srt(word_srt) if word_srt else [])
        phrase_events,word_events_all=self._live_timeline_cache
        event = next((item for item in phrase_events if item[0] <= seconds <= item[1]), None)
        if event is None and phrase_events:
            event = min(phrase_events, key=lambda item: abs(item[0] - seconds))
        if event:
            text = event[2]
            word_events = [item for item in word_events_all
                           if event[0] - .02 <= (item[0] + item[1]) / 2 <= event[1] + .02]
            active = next((item[2] for item in word_events if item[0] <= seconds <= item[1]), "")
            return text, active
        # 没有真实时间轴时保持画面干净，不显示任何语言的演示占位字幕。
        return "", ""

    def _paint_live_layers(self, image, seconds):
        if not self.layers: return
        painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 最终 ASS 始终在 1080x1920 上排版。实时预览也使用同一虚拟画布，
        # 最后整体缩放到播放器画面，避免小预览窗口重新计算字体和换行。
        painter.scale(image.width()/1080.0,image.height()/1920.0)
        try:
            for layer in reversed(self.layers):
                if not layer.get("enabled", True): continue
                if layer.get("type") == "mask":
                    color = QColor(layer.get("color", "#000000")); color.setAlphaF(max(0,min(1,float(layer.get("opacity",55))/100)))
                    x=1080*float(layer.get("x",10))/100; y=1920*float(layer.get("y",66))/100
                    width=1080*float(layer.get("w",80))/100; height=1920*float(layer.get("h",15))/100
                    radius_percent=max(0,min(100,int(layer.get("radius",35))))
                    radius=min(width,height)*.5*radius_percent/100
                    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QBrush(color)); painter.drawRoundedRect(int(x),int(y),int(width),int(height),radius,radius)
                elif layer.get("type") == "text":
                    self._paint_live_text_layer(painter,layer)
                elif layer.get("type") == "caption":
                    self._paint_live_caption(painter,image,seconds)
            if not self._current_video_has_baked_watermark():
                self._paint_live_watermark(painter)
        finally:
            painter.end()

    def _paint_live_watermark(self, painter):
        images=list(getattr(self,"_watermark_images",[])) or ([self._watermark_image] if not self._watermark_image.isNull() else [])
        if not images or not hasattr(self,"watermark_width"):
            return
        if self._live_watermark_cache is None:
            prepared=[]; entries=list(getattr(self,"_watermark_entries",[]))
            for index,source in enumerate(images):
                item=entries[index] if index<len(entries) else {"mode":self.watermark_mode.currentText(),"position":self.watermark_position.currentText(),
                                                                 "width":self.watermark_width.value(),"opacity":self.watermark_opacity.value(),"margin":self.watermark_margin.value()}
                if item.get("mode")=="9:16 全屏覆盖":
                    image=source.scaled(1080,1920,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation); x=y=0
                else:
                    width=max(1,round(1080*int(item.get("width",18))/100)); image=source.scaledToWidth(width,Qt.TransformationMode.SmoothTransformation)
                    margin=int(item.get("margin",28)); position=item.get("position","右上角"); height=image.height()
                    positions={"左上角":(margin,margin),"右上角":(1080-width-margin,margin),"左下角":(margin,1920-height-margin),
                               "右下角":(1080-width-margin,1920-height-margin),"画面中间":((1080-width)//2,(1920-height)//2)}
                    x,y=positions.get(position,positions["右上角"])
                prepared.append((image,int(x),int(y),max(5,min(100,int(item.get("opacity",100))))/100))
            self._live_watermark_cache=prepared
        for image,x,y,opacity in self._live_watermark_cache:
            painter.save(); painter.setOpacity(opacity)
            painter.drawImage(x,y,image)
            painter.restore()

    def _baked_watermark_matches(self,path,fingerprint=None):
        if not path: return False
        fingerprint=fingerprint if fingerprint is not None else watermark_config_fingerprint(self._watermark_entries)
        if not fingerprint: return False
        try:
            record=self._baked_watermarks.get(str(Path(path).resolve()),{})
            return record.get("watermark")==fingerprint and record.get("source")==_media_signature(path)
        except Exception:
            return False

    def _current_video_has_baked_watermark(self):
        item=self.videos.currentItem() if hasattr(self,"videos") else None
        return bool(item and self._baked_watermark_matches(item.text()))

    def _paint_live_text_layer(self,painter,layer):
        text=str(layer.get("text","")).strip()
        if not text: return
        font=QFont(str(layer.get("font","Microsoft YaHei"))); font.setPixelSize(max(12,int(layer.get("size",58)))); font.setBold(True)
        metrics=QFontMetricsF(font); lines=text.splitlines() or [text]; line_height=metrics.height()*1.1
        center_x=1080*float(layer.get("x",50))/100; center_y=1920*float(layer.get("y",18))/100
        painter.save(); painter.setOpacity(max(0,min(100,int(layer.get("opacity",100))))/100)
        for index,line in enumerate(lines):
            width=metrics.horizontalAdvance(line); baseline=center_y+(index-(len(lines)-1)/2)*line_height+metrics.ascent()/2-metrics.descent()/2
            path=QPainterPath(); path.addText(center_x-width/2,baseline,font,line)
            outline=max(0,int(layer.get("outline_width",2)))
            if outline:
                painter.setPen(QPen(QColor(layer.get("outline","#111111")),outline*2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(layer.get("color","#FFFFFF"))); painter.drawPath(path)
        painter.restore()

    def _paint_live_caption(self, painter, image, seconds):
        if self._live_caption_style_cache is None:
            settings=self._current_settings(); context=caption_layout_context(settings)
            self._live_caption_style_cache={"settings":settings,"preset":PRESETS[settings["preset"]],"context":context}
        settings=self._live_caption_style_cache["settings"]; preset=self._live_caption_style_cache["preset"]
        text, active_word = self._live_caption_data(seconds); tokens = tokens_for(text)
        if not tokens: return
        fixed_all = (settings.get("caption_mode") == "自由文案动画（不对口型）" and
                     settings.get("free_animation") == "整段固定")
        context=self._live_caption_style_cache["context"]; font,metrics,_gap,_line_gap,_max_line_width=context
        lines=caption_wrapped_lines(text,settings,fixed_all,context)
        # 与最终导出一致：一个画面最多两排。根据当前朗读词切换到对应分页。
        pages=([lines] if fixed_all else [lines[index:index+2] for index in range(0,len(lines),2)]) or [[]]
        active_page=0
        if active_word:
            for page_index,page in enumerate(pages):
                if any(active_word == token for line in page for token in line):
                    active_page=page_index; break
        lines=pages[active_page]; geometry=caption_page_geometry(lines,settings,context)
        base_color=QColor(settings["text_color"]); outline=QColor(settings["outline_color"]); highlight=QColor(settings["highlight_color"])
        effect=preset["effect"]; active_used=False
        for line,line_geometry in zip(lines,geometry):
            for token,item in zip(line,line_geometry):
                width=item["width"]; cursor=item["left"]; baseline=item["baseline"]
                is_active=not active_used and token==active_word
                if is_active: active_used=True
                if is_active and effect in ("descript","heygen","highlight"):
                    pad_x=max(0,int(settings.get("highlight_padding",0)))
                    pad_y=max(0,int(settings.get("highlight_padding_y",0)))
                    box_width=width+pad_x*2
                    box_height=max(float(settings["font_size"])*1.12,metrics.height())+pad_y*2
                    radius=max(0,min(18.0,box_height*.24))
                    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(highlight))
                    painter.drawRoundedRect(QRectF(item["x"]-box_width/2,item["y"]-box_height/2,
                                                   box_width,box_height),radius,radius)
                path_cache=self._live_caption_style_cache.setdefault("paths",{})
                path=path_cache.get(token)
                if path is None:
                    path=QPainterPath(); path.addText(0,0,font,token); path_cache[token]=path
                painter.save(); painter.translate(cursor,baseline)
                pen_width=max(1.0,settings["outline_width"])
                painter.setPen(QPen(outline,pen_width*2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
                fill=highlight if is_active and effect in ("word_color","pop","underline") else base_color
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(fill); painter.drawPath(path)
                painter.restore()
                if is_active and effect=="underline":
                    painter.setPen(QPen(highlight,max(2,pen_width))); painter.drawLine(int(cursor),int(baseline+metrics.descent()+3),int(cursor+width),int(baseline+metrics.descent()+3))

    def _refresh_layer_list(self, selected=0):
        if not hasattr(self,"layer_list"): return
        self.layer_list.blockSignals(True); self.layer_list.clear()
        for index,layer in enumerate(self.layers):
            prefix={"caption":"字幕","mask":"蒙版","text":"文字"}.get(layer.get("type"),"图层")
            self.layer_list.addItem(f"{index+1}. {prefix} · {layer.get('name',prefix)}")
        self.layer_list.setCurrentRow(max(0,min(selected,len(self.layers)-1)))
        self.layer_list.blockSignals(False); self._layer_selected(self.layer_list.currentRow())

    def _add_mask_layer(self):
        self._mask_counter+=1; caption_index=next((i for i,l in enumerate(self.layers) if l.get("type")=="caption"),0)
        layer={"type":"mask","name":f"蒙版 {self._mask_counter}","enabled":True,"x":10,"y":66,"w":80,"h":15,"color":"#000000","opacity":55,"radius":35}
        self.layers.insert(caption_index+1,layer); self._refresh_layer_list(caption_index+1); self._refresh_live_preview()

    def _add_text_layer(self):
        self._text_counter+=1; caption_index=next((i for i,l in enumerate(self.layers) if l.get("type")=="caption"),0)
        layer={"type":"text","name":f"文字 {self._text_counter}","enabled":True,"text":"公司名称或提示文字",
               "font":"Microsoft YaHei","size":58,"color":"#FFFFFF","outline":"#111111","outline_width":2,
               "opacity":100,"x":50,"y":18}
        self.layers.insert(caption_index,layer); self._refresh_layer_list(caption_index); self._refresh_live_preview()

    def _delete_layer(self):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")=="caption": return
        self.layers.pop(row); self._refresh_layer_list(max(0,row-1)); self._refresh_live_preview()

    def _move_layer(self, delta):
        row=self.layer_list.currentRow(); target=row+delta
        if row<0 or target<0 or target>=len(self.layers): return
        self.layers[row],self.layers[target]=self.layers[target],self.layers[row]
        self._refresh_layer_list(target); self._refresh_live_preview()

    def _layer_selected(self, row):
        layer=self.layers[row] if 0<=row<len(self.layers) else None; mask_enabled=bool(layer and layer.get("type")=="mask"); text_enabled=bool(layer and layer.get("type")=="text")
        for control in (self.mask_color,self.mask_opacity,self.mask_x,self.mask_y,self.mask_w,self.mask_h,self.mask_radius,*self.mask_quick_buttons): control.setEnabled(mask_enabled)
        text_controls=(self.layer_text,self.layer_text_font,self.layer_text_size,self.layer_text_color,self.layer_text_outline,
                       self.layer_text_opacity,self.layer_text_x,self.layer_text_y,*self.text_quick_buttons)
        for control in text_controls: control.setEnabled(text_enabled)
        if mask_enabled:
            controls=((self.mask_x,"x"),(self.mask_y,"y"),(self.mask_w,"w"),(self.mask_h,"h"),(self.mask_opacity,"opacity"),(self.mask_radius,"radius"))
            for control,key in controls: control.blockSignals(True); control.setValue(int(layer.get(key,0))); control.blockSignals(False)
            self.mask_color.setText(f"蒙版颜色 {layer.get('color','#000000')}"); self.mask_opacity_value.setText(f"{layer.get('opacity',55)}%")
        if text_enabled:
            controls=((self.layer_text,"text"),(self.layer_text_font,"font"),(self.layer_text_size,"size"),(self.layer_text_outline,"outline_width"),
                      (self.layer_text_opacity,"opacity"),(self.layer_text_x,"x"),(self.layer_text_y,"y"))
            for control,key in controls:
                control.blockSignals(True)
                if isinstance(control,(QLineEdit,QComboBox)): control.setText(str(layer.get(key,""))) if isinstance(control,QLineEdit) else control.setCurrentText(str(layer.get(key,"")))
                else: control.setValue(int(layer.get(key,0)))
                control.blockSignals(False)
            self.layer_text_color.setText(f"文字颜色 {layer.get('color','#FFFFFF')}")

    def _mask_control_changed(self, *_args):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="mask": return
        self.layers[row].update({"x":self.mask_x.value(),"y":self.mask_y.value(),"w":self.mask_w.value(),"h":self.mask_h.value(),"opacity":self.mask_opacity.value(),"radius":self.mask_radius.value()})
        self.mask_opacity_value.setText(f"{self.mask_opacity.value()}%"); self._refresh_live_preview()

    def _quick_mask_position(self, mode):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="mask": return
        width=self.mask_w.value(); height=self.mask_h.value()
        if mode in ("horizontal","top","bottom"):
            self.mask_x.setValue(max(0,(100-width)//2))
        if mode=="vertical": self.mask_y.setValue(max(0,(100-height)//2))
        elif mode=="top": self.mask_y.setValue(5)
        elif mode=="bottom": self.mask_y.setValue(max(0,95-height))
        self._mask_control_changed()

    def _text_layer_changed(self,*_args):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="text": return
        self.layers[row].update({"text":self.layer_text.text(),"font":self.layer_text_font.currentText(),"size":self.layer_text_size.value(),
                                 "outline_width":self.layer_text_outline.value(),"opacity":self.layer_text_opacity.value(),
                                 "x":self.layer_text_x.value(),"y":self.layer_text_y.value()})
        self._refresh_live_preview()

    def _quick_text_position(self,mode):
        self.layer_text_x.setValue(50)
        self.layer_text_y.setValue({"top":12,"center":50,"bottom":88}.get(mode,18)); self._text_layer_changed()

    def _pick_layer_text_color(self):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="text": return
        color=QColorDialog.getColor(QColor(self.layers[row].get("color","#FFFFFF")),self)
        if color.isValid():
            self.layers[row]["color"]=color.name().upper(); self.layer_text_color.setText(f"文字颜色 {color.name().upper()}"); self._refresh_live_preview()

    def _layer_settings_store(self):
        return QSettings("VideoToolkit","DynamicReels")

    def _load_layer_schemes(self):
        try: self._layer_schemes=json.loads(self._layer_settings_store().value("layer_schemes","{}"))
        except Exception: self._layer_schemes={}
        self.layer_scheme_combo.clear(); self.layer_scheme_combo.addItems(sorted(self._layer_schemes))

    def _save_layer_scheme(self):
        name=self.layer_scheme_combo.currentText().strip()
        if not name:
            name=f"方案 {len(self._layer_schemes)+1}"
        self._layer_schemes[name]=json.loads(json.dumps(self.layers,ensure_ascii=False))
        self._layer_settings_store().setValue("layer_schemes",json.dumps(self._layer_schemes,ensure_ascii=False))
        self._load_layer_schemes(); self.layer_scheme_combo.setCurrentText(name); self.log.appendPlainText(f"已保存图层方案：{name}")

    def _apply_layer_scheme(self):
        name=self.layer_scheme_combo.currentText().strip(); saved=self._layer_schemes.get(name)
        if not saved:
            QMessageBox.information(self,"没有方案","请选择已保存的图层方案，或输入名称后点击“保存方案”。"); return
        self.layers=json.loads(json.dumps(saved,ensure_ascii=False))
        if not any(layer.get("type")=="caption" for layer in self.layers): self.layers.append({"type":"caption","name":"字幕层"})
        self._mask_counter=sum(1 for layer in self.layers if layer.get("type")=="mask")
        self._text_counter=sum(1 for layer in self.layers if layer.get("type")=="text")
        self._refresh_layer_list(0); self._refresh_live_preview(); self.log.appendPlainText(f"已应用图层方案：{name}")

    def _delete_layer_scheme(self):
        name=self.layer_scheme_combo.currentText().strip()
        if name in self._layer_schemes:
            self._layer_schemes.pop(name); self._layer_settings_store().setValue("layer_schemes",json.dumps(self._layer_schemes,ensure_ascii=False)); self._load_layer_schemes()

    def _watermark_mode_changed(self,*_args):
        custom=self.watermark_mode.currentText()=="小 Logo 自定义位置"
        for control in (self.watermark_position,self.watermark_width,self.watermark_margin): control.setEnabled(custom)
        self._watermark_control_changed()
        self._refresh_live_preview()

    def _refresh_watermark_table(self,selected=None):
        if not hasattr(self,"watermark_table"): return
        current=self.watermark_table.currentRow() if selected is None else selected
        self.watermark_table.blockSignals(True); self.watermark_table.setRowCount(len(self._watermark_entries))
        for row,item in enumerate(self._watermark_entries):
            values=(Path(item["path"]).name,item.get("position","右上角"),
                    "全屏" if item.get("mode")=="9:16 全屏覆盖" else f"{item.get('width',18)}%",f"{item.get('opacity',100)}%")
            for column,value in enumerate(values):
                cell=QTableWidgetItem(str(value)); cell.setToolTip(item["path"]); self.watermark_table.setItem(row,column,cell)
        self.watermark_table.blockSignals(False)
        if self._watermark_entries:
            self.watermark_table.setCurrentCell(max(0,min(current,len(self._watermark_entries)-1)),0)

    def _watermark_selection_changed(self,current_row,*_args):
        if not (0<=current_row<len(self._watermark_entries)): return
        item=self._watermark_entries[current_row]
        controls=((self.watermark_mode,"mode"),(self.watermark_position,"position"),(self.watermark_width,"width"),
                  (self.watermark_opacity,"opacity"),(self.watermark_margin,"margin"))
        for control,key in controls: control.blockSignals(True)
        try:
            self.watermark_mode.setCurrentText(item.get("mode","9:16 全屏覆盖")); self.watermark_position.setCurrentText(item.get("position","右上角"))
            self.watermark_width.setValue(int(item.get("width",18))); self.watermark_opacity.setValue(int(item.get("opacity",100))); self.watermark_margin.setValue(int(item.get("margin",28)))
        finally:
            for control,key in controls: control.blockSignals(False)
        custom=self.watermark_mode.currentText()=="小 Logo 自定义位置"
        for control in (self.watermark_position,self.watermark_width,self.watermark_margin): control.setEnabled(custom)

    def _watermark_control_changed(self,*_args):
        if not hasattr(self,"watermark_table"): return
        row=self.watermark_table.currentRow()
        if 0<=row<len(self._watermark_entries):
            self._watermark_entries[row].update({"mode":self.watermark_mode.currentText(),"position":self.watermark_position.currentText(),
                                                  "width":self.watermark_width.value(),"opacity":self.watermark_opacity.value(),
                                                  "margin":self.watermark_margin.value()})
            self._refresh_watermark_table(row)
        self._refresh_live_preview(); self._save_style_preferences()

    def _pick_mask_color(self):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="mask": return
        color=QColorDialog.getColor(QColor(self.layers[row].get("color","#000000")),self)
        if color.isValid():
            self.layers[row]["color"]=color.name().upper(); self.mask_color.setText(f"蒙版颜色 {color.name().upper()}"); self._refresh_live_preview()

    def _choose_company_watermark(self):
        paths,_=QFileDialog.getOpenFileNames(self,"添加公司水印图片","","图片 (*.png *.webp *.jpg *.jpeg *.bmp)")
        if not paths: return
        invalid=[]
        for path in paths:
            if path in self._watermark_paths: continue
            image=QImage(path)
            if image.isNull(): invalid.append(path); continue
            self._watermark_paths.append(path); self._watermark_images.append(image)
            self._watermark_entries.append({"path":path,"mode":self.watermark_mode.currentText(),
                                             "position":self.watermark_position.currentText(),"width":self.watermark_width.value(),
                                             "opacity":100,"margin":self.watermark_margin.value()})
        self._watermark_image=self._watermark_images[0] if self._watermark_images else QImage()
        summary="；".join(Path(path).name for path in self._watermark_paths)
        self.company_watermark.setText(f"已添加 {len(self._watermark_paths)} 张：{summary}")
        self.company_watermark.setToolTip("\n".join(self._watermark_paths))
        self._refresh_watermark_table(len(self._watermark_entries)-1)
        self._refresh_live_preview(); self._save_style_preferences(); self._append_run_log(f"已加载 {len(self._watermark_paths)} 张公司水印")
        if invalid: self._append_run_log("以下水印图片无法读取，已跳过："+"；".join(invalid))

    def _clear_company_watermark(self):
        self.company_watermark.clear(); self.company_watermark.setToolTip(""); self._watermark_image=QImage()
        self._watermark_images=[]; self._watermark_paths=[]; self._watermark_entries=[]; self._refresh_watermark_table(); self._refresh_live_preview(); self._save_style_preferences()

    def _remove_selected_watermarks(self):
        rows=sorted({index.row() for index in self.watermark_table.selectedIndexes()},reverse=True)
        for row in rows:
            if 0<=row<len(self._watermark_entries):
                self._watermark_entries.pop(row); self._watermark_paths.pop(row); self._watermark_images.pop(row)
        self._watermark_image=self._watermark_images[0] if self._watermark_images else QImage()
        summary="；".join(Path(path).name for path in self._watermark_paths)
        self.company_watermark.setText(f"已添加 {len(self._watermark_paths)} 张：{summary}" if summary else "")
        self.company_watermark.setToolTip("\n".join(self._watermark_paths)); self._refresh_watermark_table(); self._refresh_live_preview(); self._save_style_preferences()

    def _preview_margin_changed(self, value):
        if hasattr(self, "margin_v"):
            self.margin_v.setValue(value)
        self.preview_position_value.setText(f"距底部 {value}")

    def _sync_preview_margin(self, value):
        if not hasattr(self, "preview_position_slider"): return
        self.preview_position_slider.blockSignals(True); self.preview_position_slider.setValue(value); self.preview_position_slider.blockSignals(False)
        self.preview_position_value.setText(f"距底部 {value}")

    def load_audio_preview(self,path):
        if not path or not Path(path).is_file() or not hasattr(self,"audio_player"): return
        self._audio_edit_source=str(Path(path).resolve())
        offset=max(0,int(self.audio_offsets.get(self._audio_edit_source,0)))
        self.audio_start_seek.setValue(offset); self.audio_start_time.setText(self._clock(offset))
        self.audio_player.setSource(QUrl.fromLocalFile(path)); self.audio_player.setPosition(offset)
        self.audio_play_btn.setText("试听配音")

    def toggle_audio_preview(self):
        if self.audio_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.pause(); self.audio_play_btn.setText("继续试听")
        else:
            self.audio_player.play(); self.audio_play_btn.setText("暂停试听")

    def _audio_position_changed(self,value):
        if not self.audio_seek.isSliderDown(): self.audio_seek.setValue(value)
        self.audio_time.setText(f"{self._clock(value)} / {self._clock(self.audio_player.duration())}")

    def _audio_duration_changed(self,value):
        maximum=max(0,value-100)
        self.audio_seek.setRange(0,max(0,value)); self.audio_start_seek.setRange(0,maximum)
        saved=max(0,min(maximum,int(self.audio_offsets.get(self._audio_edit_source,0)))) if self._audio_edit_source else 0
        self.audio_start_seek.setValue(saved); self.audio_start_time.setText(self._clock(saved))
        self._audio_position_changed(self.audio_player.position())

    def _audio_start_changed(self,value):
        if not self._audio_edit_source: return
        value=max(0,int(value)); self.audio_offsets[self._audio_edit_source]=value
        self.audio_start_time.setText(self._clock(value)); self.audio_player.setPosition(value)
        self._save_style_preferences(); self._refresh_task_queue()

    def _preview_audio_start(self):
        if not self._audio_edit_source: return
        value=max(0,int(self.audio_offsets.get(self._audio_edit_source,self.audio_start_seek.value())))
        self.audio_player.setPosition(value); self.audio_player.play(); self.audio_play_btn.setText("暂停试听")

    @staticmethod
    def _clock(milliseconds):
        seconds=max(0,int(milliseconds/1000)); return f"{seconds//60:02d}:{seconds%60:02d}"

    def _preview_position_changed(self, value):
        if not self.seek.isSliderDown(): self.seek.setValue(value)
        expected=value+self._preview_audio_offset_ms
        if self._preview_external_audio and abs(self.audio_player.position()-expected) > 250:
            self.audio_player.setPosition(expected)
        self.time_label.setText(f"{self._clock(value)} / {self._clock(self.player.duration())}")

    def _preview_duration_changed(self, value):
        self.seek.setRange(0,max(0,value)); self._preview_position_changed(self.player.position())

    def _current_settings(self):
        preset=next(button.text() for button in self.preset_buttons if button.isChecked())
        watermark_fingerprint=watermark_config_fingerprint(self._watermark_entries)
        baked_videos=[]
        if watermark_fingerprint and hasattr(self,"videos"):
            for index in range(self.videos.count()):
                path=self.videos.item(index).text()
                if self._baked_watermark_matches(path,watermark_fingerprint):
                    baked_videos.append(str(Path(path).resolve()))
        return {"preset":preset,"font":self.font.currentText(),"font_size":self.font_size.value(),
                "caption_mode":self.caption_mode.currentText(),
                "free_animation":self.free_animation.currentText(),
                "free_page_seconds":self.free_page_seconds.value(),
                "line_length":self.line_length.value(),"outline_width":self.outline_width.value(),
                "line_width":self.line_width.value(),"letter_spacing":self.letter_spacing.value(),
                "word_spacing":self.word_spacing.value(),
                "line_spacing":self.line_spacing.value(),
                "max_words":self.max_words.value(),"highlight_padding":self.highlight_padding.value(),
                "highlight_padding_y":self.highlight_padding_y.value(),
                "animation_speed":self.animation_speed.value(),
                "position":self.position.currentText(),"margin_v":self.margin_v.value(),
                "audio_mode":self.audio_mode.currentText(),"audio_match_mode":self.audio_match_mode.currentText(),
                "original_volume":self.original_volume.value(),"background_volume":self.background_volume.value(),
                "audio_fade_mode":self.audio_fade_mode.currentText(),
                "audio_fade_in_ms":self.audio_fade_in.value(),"audio_fade_out_ms":self.audio_fade_out.value(),
                "audio_offsets":dict(self.audio_offsets),
                "clean_metadata":self.clean_metadata.isChecked(),
                "override_text":self.override_text.toPlainText().strip(),"encode_preset":self.encode_preset.currentText(),
                "encoder_backend":self.encoder_backend.currentText(),
                "timeline_overrides":dict(self.timeline_overrides),
                "word_timelines":dict(self.timeline_words),
                "free_texts":dict(self.free_texts),
                "free_default_text":self.override_text.toPlainText().strip(),
                "preview_word_srt":self.timeline_words.get(self._timeline_key(self._timeline_source()),""),
                "layers":[dict(layer) for layer in self.layers],
                "watermark_path":self._watermark_paths[0] if self._watermark_paths else "",
                "watermark_paths":list(self._watermark_paths),
                "watermarks":[dict(item) for item in self._watermark_entries],
                "watermark_baked_videos":baked_videos,
                "watermark_mode":self.watermark_mode.currentText(),
                "watermark_position":self.watermark_position.currentText(),
                "watermark_width":self.watermark_width.value(),
                "watermark_opacity":self.watermark_opacity.value(),
                "watermark_margin":self.watermark_margin.value(),
                "text_color":self._hex(self.text_color),"outline_color":self._hex(self.outline_color),
                "highlight_color":self._hex(self.highlight_color),"provider":self.provider.currentText(),
                "rename_enabled": self.rename_enabled.isChecked(),
                "rename_prefix": self.rename_prefix.text(),
                "rename_suffix_enabled": self.rename_suffix_enabled.isChecked(),
                "rename_suffix": self.rename_suffix.text(),
                "rename_date_enabled": self.rename_date_enabled.isChecked(),
                "rename_date": self.rename_date.text(),
                "rename_start_index": self.rename_start_index.value(),
                "rename_padding": self.rename_padding.value()}

    def render_effect_preview(self):
        item=self.videos.currentItem()
        if not item:
            QMessageBox.information(self,"没有预览视频","请先在左侧添加并选中一个视频。"); return
        try: ffmpeg=self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self,"缺少组件",str(exc)); return
        timeline_source=self._timeline_source()
        timeline_key=self._timeline_key(timeline_source)
        # Exact preview must use the selected task's own edited timeline, exactly as
        # final batch export does. Falling back to the shared editor caused previews
        # from one item to be compared with another item's final render.
        text=(self.timeline_overrides.get(timeline_key, "").strip()
              or self.override_text.toPlainText().strip()
              or self.tts_text.toPlainText().strip()
              or "让每一句文案跟随朗读跳动")
        if "-->" not in text and self.caption_mode.currentText() != "自由文案动画（不对口型）":
            text=re.sub(r"\s+"," ",text)[:100]
        preview_dir=Path(self.output.text())/".preview"; preview_dir.mkdir(parents=True,exist_ok=True)
        # Never reuse a media URL in the same application session.  Qt's media
        # backend may keep the old decoded clip when a deleted preview is later
        # recreated under the same filename, making changed controls appear to
        # have no effect.
        preview_token=f"{time.time_ns():x}"
        destination=preview_dir/f"effect_{short_media_id(item.text())}_{preview_token}.mp4"
        self.render_preview_btn.setEnabled(False); self.render_preview_btn.setText("正在生成 8 秒预览…")
        settings=self._current_settings(); matched=self._matched_source_for_video(item.text())
        if (matched and Path(matched).is_file() and Path(matched).resolve()!=Path(item.text()).resolve()
                and self.audio_mode.currentText() in ("替换为添加的音频", "原声＋背景音混合")):
            settings["preview_audio"]=matched
            settings["preview_audio_offset_ms"]=self.audio_offsets.get(self._timeline_key(matched),0)
        self.preview_thread=QThread(self); self.preview_worker=PreviewWorker(ffmpeg,item.text(),destination,text,settings)
        self.preview_worker.moveToThread(self.preview_thread); self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.finished.connect(self._effect_preview_done); self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self._preview_thread_ended); self.preview_thread.finished.connect(self.preview_thread.deleteLater); self.preview_thread.start()

    def _effect_preview_done(self, ok, result):
        self.render_preview_btn.setEnabled(True); self.render_preview_btn.setText("渲染 8 秒精确预览")
        if ok:
            self._precise_preview_files.add(str(result))
            self.load_video_preview(result, precise=True)
            # 预览生成后停在有字幕的画面，避免自动播放到第 8 秒后看起来像“没有效果”。
            QTimer.singleShot(220, lambda: self._pause_effect_preview_at(900))
            self.log.appendPlainText(f"效果预览已生成并载入播放器：{result}")
        else: QMessageBox.critical(self,"预览生成失败",result)

    def _clear_precise_preview(self):
        """Return to source/live preview and remove generated preview clips."""
        item=self.videos.currentItem()
        if item:
            source=self._matched_source_for_video(item.text())
            mode=self.audio_mode.currentText()
            external=(source if source and Path(source).is_file() and Path(source).resolve()!=Path(item.text()).resolve()
                      and mode in ("替换为添加的音频", "原声＋背景音混合") else "")
            offset=self.audio_offsets.get(self._timeline_key(external),0) if external else 0
            self.load_video_preview(item.text(),external,precise=False,
                                    mix_audio=mode=="原声＋背景音混合",audio_offset_ms=offset)
        pending=list(self._precise_preview_files); self._precise_preview_files.clear()
        def remove_files():
            removed=0
            for path in pending:
                try: Path(path).unlink(missing_ok=True); removed+=1
                except OSError: pass
            self._append_run_log(f"已清除精确预览，恢复实时预览。移除 {removed} 个临时预览文件。")
        QTimer.singleShot(700,remove_files)

    def _preview_thread_ended(self): self.preview_worker=None; self.preview_thread=None

    def _pause_effect_preview_at(self, milliseconds):
        self.player.pause(); self.audio_player.pause(); self.preview_frame_timer.stop(); self._seek_preview(milliseconds)
        self.seek.setValue(milliseconds)
        self.time_label.setText(f"{self._clock(milliseconds)} / {self._clock(self.player.duration() or self.seek.maximum())}")
        self.play_btn.setText("播放效果")

    def _matched_source_for_video(self, video_path):
        if not video_path: return ""
        videos=[self.videos.item(i).text() for i in range(self.videos.count())]
        audios=[self.audios.item(i).text() for i in range(self.audios.count())]
        try: index=videos.index(video_path)
        except ValueError: index=0
        mode=self.audio_match_mode.currentText() if hasattr(self,"audio_match_mode") else "自动匹配（同名优先，其次按队列）"
        matcher=CaptionWorker(videos,audios,Path("."),"",None,{"audio_match_mode":mode})
        return str(matcher._audio_for(Path(video_path),index))

    def _caption_source_for_video(self, video_path):
        """Return the dialogue track, never a background-music-only track."""
        if not video_path:
            return ""
        if self.audio_mode.currentText() == "替换为添加的音频":
            return self._matched_source_for_video(video_path)
        return str(video_path)

    def _video_selection_changed(self, video_path):
        if not video_path: return
        if hasattr(self,"task_queue") and self.videos.currentRow()>=0:
            self.task_queue.selectRow(self.videos.currentRow())
        source=self._matched_source_for_video(video_path)
        if hasattr(self,"combination_label"):
            saved=bool(self.free_texts.get(self._timeline_key(video_path),"").strip())
            self.combination_label.setText(
                f"当前任务组合：{Path(video_path).name}  ＋  {Path(source).name if source else '未匹配音频'}  ＋  "
                f"{'已保存文案' if saved else '待填写文案'}")
        mode=self.audio_mode.currentText()
        external = (source if source and Path(source).is_file() and Path(source).resolve() != Path(video_path).resolve()
                    and mode in ("替换为添加的音频", "原声＋背景音混合") else "")
        offset=self.audio_offsets.get(self._timeline_key(external),0) if external else 0
        self.load_video_preview(video_path, external, mix_audio=mode=="原声＋背景音混合",audio_offset_ms=offset)
        caption_source=self._caption_source_for_video(video_path)
        self._active_timeline_source=caption_source
        # 同步高亮匹配音频，方便核对；阻断信号避免音频选择反过来覆盖视频关联。
        if source and hasattr(self,"audios"):
            matches=self.audios.findItems(source,Qt.MatchFlag.MatchExactly)
            if matches:
                self._syncing_media_selection=True
                try: self.audios.setCurrentItem(matches[0])
                finally: self._syncing_media_selection=False
                if not external: self.load_audio_preview(source)
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            self._load_current_free_text()
        else:
            self._timeline_selection_changed(caption_source)

    def _audio_selection_changed(self, source):
        if self._syncing_media_selection: return
        if not source:
            self._rematch_current_video(); return
        self.load_audio_preview(source)
        video_item=self.videos.currentItem() if hasattr(self,"videos") else None
        caption_source=(self._caption_source_for_video(video_item.text()) if video_item else source)
        self._active_timeline_source=caption_source
        self._timeline_selection_changed(caption_source)

    def _rematch_current_video(self, *_args):
        item=self.videos.currentItem() if hasattr(self,"videos") else None
        if item: self._video_selection_changed(item.text())

    def _audio_mode_changed(self, mode):
        mixing = mode == "原声＋背景音混合"
        self.original_volume.setEnabled(mixing)
        self.background_volume.setEnabled(mixing)
        if (mode in ("替换为添加的音频", "原声＋背景音混合")
                and self.audio_match_mode.currentText() == "每个视频使用自身音频"
                and self.audios.count()):
            self.audio_match_mode.setCurrentText("严格按队列一一对应")
        self._update_preview_audio_levels()
        self._audio_fade_mode_changed(self.audio_fade_mode.currentText())
        self._refresh_live_preview()

    def _audio_fade_mode_changed(self, mode):
        external_mode=self.audio_mode.currentText() in ("替换为添加的音频","原声＋背景音混合")
        self.audio_fade_mode.setEnabled(external_mode)
        self.audio_fade_in.setEnabled(external_mode and mode in ("仅淡入","淡入＋淡出"))
        self.audio_fade_out.setEnabled(external_mode and mode in ("仅淡出","淡入＋淡出"))
        self._refresh_live_preview()

    def _update_preview_audio_levels(self, *_args):
        if not hasattr(self, "audio_output") or not hasattr(self, "audio_preview_output"):
            return
        if getattr(self, "audio_mode", None) and self.audio_mode.currentText() == "原声＋背景音混合":
            self.audio_output.setVolume(self.original_volume.value() / 100)
            self.audio_preview_output.setVolume(self.background_volume.value() / 100)

    def _timeline_source(self):
        video_item=self.videos.currentItem()
        if video_item: return self._caption_source_for_video(video_item.text())
        if self._active_timeline_source: return self._active_timeline_source
        audio_item=self.audios.currentItem()
        return audio_item.text() if audio_item else ""

    def _timeline_key(self, source):
        try: return str(Path(source).resolve())
        except Exception: return str(source)

    def _current_video_key(self):
        item = self.videos.currentItem() if hasattr(self, "videos") else None
        return self._timeline_key(item.text()) if item else ""

    def _load_current_free_text(self):
        key = self._current_video_key()
        self._loading_timeline = True
        try: self.override_text.setPlainText(self.free_texts.get(key, ""))
        finally: self._loading_timeline = False
        self.timeline_source_label.setText(
            f"当前自由文案：{Path(key).name}" if key else "当前自由文案：尚未选择视频")
        self._refresh_live_preview()

    def _caption_mode_changed(self, mode):
        free = mode == "自由文案动画（不对口型）"
        self.free_animation.setEnabled(free)
        self.free_page_seconds.setEnabled(free and self.free_animation.currentText() != "整段固定")
        self.provider.setEnabled(not free); self.extract_timeline_btn.setEnabled(not free); self.extract_all_btn.setEnabled(not free)
        if free:
            self._load_current_free_text()
        else:
            self._timeline_selection_changed(self._timeline_source())
        self._refresh_live_preview()

    def _free_animation_changed(self, animation):
        if hasattr(self, "free_page_seconds"):
            self.free_page_seconds.setEnabled(
                self.caption_mode.currentText() == "自由文案动画（不对口型）" and animation != "整段固定")
            self.free_page_seconds.setToolTip(
                "整段固定会覆盖整个视频时长，不使用每屏秒数。" if animation == "整段固定" else
                "自由文案分页动画中，每一屏字幕持续显示的时间。")
        self._refresh_live_preview()

    def _group_words_for_current_layout(self, word_srt, return_fix_count=False):
        return group_word_srt(
            word_srt, max_chars=max(18,self.line_length.value()*2),
            max_words=self.max_words.value(),
            return_fix_count=return_fix_count,
        )

    def _fix_current_overlaps(self):
        text=self.override_text.toPlainText().strip()
        if "-->" not in text:
            QMessageBox.information(self,"没有时间轴","请先提取字幕或载入 SRT。")
            return
        fixed,count=fix_srt_overlaps(text)
        if not count:
            self._append_run_log("当前字幕时间轴没有检测到重叠。")
            return
        self._loading_timeline=True
        try: self.override_text.setPlainText(fixed)
        finally: self._loading_timeline=False
        source=self._timeline_source()
        if source: self.timeline_overrides[self._timeline_key(source)]=fixed
        self._refresh_task_queue(); self._refresh_live_preview()
        self._append_run_log(f"已自动修正 {count} 处字幕时间重叠，文字内容和词级时间轴保持不变。")

    def _timeline_selection_changed(self, source):
        self._active_timeline_source=source or ""
        if hasattr(self,"timeline_source_label"):
            self.timeline_source_label.setText(f"当前字幕：{Path(source).name}" if source else "当前字幕：尚未选择视频")
        key=self._timeline_key(source) if source else ""
        text=self.timeline_overrides.get(key,"")
        if not text and key in self.timeline_words:
            text=self._group_words_for_current_layout(self.timeline_words[key])
        self._loading_timeline=True
        try: self.override_text.setPlainText(text)
        finally: self._loading_timeline=False
        self._refresh_live_preview()

    def _timeline_text_changed(self):
        if self._loading_timeline: return
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            key = self._current_video_key()
            if key:
                self.free_texts[key] = self.override_text.toPlainText()
                if hasattr(self,"combination_label"):
                    video=self.videos.currentItem().text() if self.videos.currentItem() else key
                    source=self._matched_source_for_video(video)
                    self.combination_label.setText(
                        f"当前任务组合：{Path(video).name}  ＋  {Path(source).name if source else '未匹配音频'}  ＋  "
                        f"{'已保存文案' if self.override_text.toPlainText().strip() else '待填写文案'}")
                self._refresh_task_queue()
            return
        source=self._timeline_source()
        if source: self.timeline_overrides[self._timeline_key(source)]=self.override_text.toPlainText()
        self._refresh_task_queue()

    def _apply_source_proofread(self):
        source_copy=self.source_proofread.toPlainText().strip()
        if not source_copy:
            QMessageBox.information(self,"没有源文案","请先粘贴用于校对的完整源文案。")
            return
        timeline=self.override_text.toPlainText().strip()
        source=self._timeline_source(); key=self._timeline_key(source) if source else ""
        if "-->" not in timeline and key:
            timeline=self.timeline_overrides.get(key,"") or self._group_words_for_current_layout(self.timeline_words.get(key,""))
        if "-->" not in timeline:
            QMessageBox.information(self,"没有时间轴","请先提取当前素材字幕或载入 SRT，再使用源文案校对。")
            return
        corrected=replace_srt_copy(timeline,normalize_required_capitalization(source_copy))
        self._loading_timeline=True
        try: self.override_text.setPlainText(corrected)
        finally: self._loading_timeline=False
        if key: self.timeline_overrides[key]=corrected
        self._refresh_task_queue(); self._refresh_live_preview()
        self._append_run_log(f"已用源文案校对字幕并保留原时间轴：{Path(source).name if source else '当前素材'}")

    def extract_timeline(self):
        source=self._timeline_source()
        if not source:
            QMessageBox.information(self,"没有音频","请先选中一个音频；未添加音频时也可以选中包含声音的视频。"); return
        if self.timeline_thread and self.timeline_thread.isRunning(): return
        provider=self.provider.currentText(); self.extract_timeline_btn.setEnabled(False); self.extract_timeline_btn.setText("正在重新识别时间轴…")
        self._append_run_log(f"开始提取选中素材字幕：{Path(source).name}（识别服务：{provider}）")
        self._start_timeline_activity(Path(source).name,2,92)
        self._timeline_pending_source=source
        self.timeline_thread=QThread(self); callback=lambda path:self.transcribe_callable(path,provider)
        self.timeline_worker=TimelineWorker(callback,source,self.output.text(),force_refresh=True); self.timeline_worker.moveToThread(self.timeline_thread)
        self.timeline_thread.started.connect(self.timeline_worker.run); self.timeline_worker.finished.connect(self._timeline_done); self.timeline_worker.finished.connect(self.timeline_thread.quit)
        self.timeline_thread.finished.connect(self._timeline_ended); self.timeline_thread.finished.connect(self.timeline_thread.deleteLater); self.timeline_thread.start()

    def extract_all_timelines(self):
        videos=[self.videos.item(i).text() for i in range(self.videos.count())]
        audios=[self.audios.item(i).text() for i in range(self.audios.count())]
        if not videos:
            QMessageBox.information(self,"没有视频","请先添加需要批量处理的视频素材。")
            return
        if self.timeline_thread and self.timeline_thread.isRunning(): return
        settings=self._current_settings()
        sources=[]
        for video in videos:
            value=self._caption_source_for_video(video)
            if value not in sources: sources.append(value)
        provider=self.provider.currentText(); callback=lambda path:self.transcribe_callable(path,provider)
        self.extract_timeline_btn.setEnabled(False); self.extract_all_btn.setEnabled(False)
        self.extract_all_btn.setText(f"排队提取 0/{len(sources)}")
        self.timeline_thread=QThread(self); self.timeline_worker=BatchTimelineWorker(callback,sources,self.output.text())
        self.timeline_worker.moveToThread(self.timeline_thread)
        self.timeline_thread.started.connect(self.timeline_worker.run)
        self.timeline_worker.item_started.connect(self._batch_timeline_item_started)
        self.timeline_worker.item_done.connect(self._batch_timeline_item_done)
        self.timeline_worker.item_failed.connect(self._batch_timeline_item_failed)
        self.timeline_worker.finished.connect(self._batch_timeline_done)
        self.timeline_worker.finished.connect(self.timeline_thread.quit)
        self.timeline_thread.finished.connect(self._timeline_ended)
        self.timeline_thread.finished.connect(self.timeline_thread.deleteLater)
        self._append_run_log(f"已建立批量字幕队列：{len(sources)} 个素材，将按视频匹配关系逐个处理。")
        self.timeline_thread.start()

    def _batch_timeline_item_started(self,source,index,total):
        base=round((index-1)/max(1,total)*100)
        cap=max(base+1,round((index-.08)/max(1,total)*100))
        self._append_run_log(f"[{index}/{total}] 开始识别：{Path(source).name}")
        self.extract_all_btn.setText(f"正在识别 {index}/{total}")
        self._start_timeline_activity(f"[{index}/{total}] {Path(source).name}",base,cap)

    def _batch_timeline_item_done(self,source,srt,chinese,index,total):
        self._stop_timeline_activity(round(index/max(1,total)*100))
        key=self._timeline_key(source); phrase_srt,fixes=self._group_words_for_current_layout(srt,True)
        self.timeline_words[key]=srt; self.timeline_overrides[key]=phrase_srt
        if chinese: self.timeline_chinese[key]=chinese
        self.extract_all_btn.setText(f"排队提取 {index}/{total}")
        self.log.appendPlainText(f"[{index}/{total}] 时间轴已归档到：{Path(source).name}")
        if fixes: self._append_run_log(f"[{index}/{total}] 已自动修正 {fixes} 处逐句字幕时间重叠。")
        if self._timeline_key(self._timeline_source())==key:
            self._loading_timeline=True
            try: self.override_text.setPlainText(phrase_srt)
            finally: self._loading_timeline=False
        self._refresh_task_queue()

    def _batch_timeline_item_failed(self,source,message,index,total):
        self._stop_timeline_activity(round(index/max(1,total)*100))
        text=f"[{index}/{total}] 字幕识别失败，已跳过并继续下一项：{Path(source).name}｜{message}"
        self._append_run_log(text)
        self.extract_all_btn.setText(f"排队提取 {index}/{total}")

    def _worker_timeline_ready(self,source,word_srt,phrase_srt):
        key=self._timeline_key(source)
        phrase_srt,fixes=fix_srt_overlaps(phrase_srt)
        self.timeline_words[key]=word_srt; self.timeline_overrides[key]=phrase_srt
        if fixes: self._append_run_log(f"已自动修正 {fixes} 处逐句字幕时间重叠：{Path(source).name}")
        if self._timeline_key(self._timeline_source())==key:
            self._loading_timeline=True
            try: self.override_text.setPlainText(phrase_srt)
            finally: self._loading_timeline=False
        self._refresh_task_queue()

    def _batch_timeline_done(self,ok,message):
        self._stop_timeline_activity(100)
        self.extract_timeline_btn.setEnabled(True); self.extract_all_btn.setEnabled(True)
        self.extract_all_btn.setText("批量提取全部")
        self._append_run_log(message)
        if not ok:
            self.run_status.setText("当前状态：字幕队列全部失败，请在“帮助 → 软件日志”查看原因")

    def _timeline_done(self,ok,result,chinese=""):
        self._stop_timeline_activity(100 if ok else self.progress.value())
        self.extract_timeline_btn.setEnabled(True); self.extract_timeline_btn.setText("重新提取选中素材")
        if ok:
            source=self._timeline_pending_source or self._timeline_source(); phrase_srt,fixes=self._group_words_for_current_layout(result,True)
            if source:
                key=self._timeline_key(source); self.timeline_words[key]=result; self.timeline_overrides[key]=phrase_srt
                if chinese: self.timeline_chinese[key]=chinese
                if self._timeline_key(self._timeline_source())==key:
                    self._loading_timeline=True
                    try: self.override_text.setPlainText(phrase_srt)
                    finally: self._loading_timeline=False
            self.log.appendPlainText("已重新识别并覆盖旧时间轴；词级时间轴已保留，编辑器已合并为逐句字幕。")
            if fixes: self._append_run_log(f"已自动修正 {fixes} 处逐句字幕时间重叠。")
            self._refresh_task_queue()
        else:
            self._append_run_log(f"选中素材字幕识别失败：{result}")
            self.run_status.setText("当前状态：当前字幕识别失败；错误已记录，可调整服务后重试")

    def _timeline_ended(self):
        self._stop_timeline_activity()
        self.timeline_worker=None; self.timeline_thread=None; self._timeline_pending_source=""
        if hasattr(self,"extract_timeline_btn"): self.extract_timeline_btn.setEnabled(True)
        if hasattr(self,"extract_all_btn"): self.extract_all_btn.setEnabled(True); self.extract_all_btn.setText("批量提取全部")

    def load_srt_file(self):
        path,_=QFileDialog.getOpenFileName(self,"载入字幕时间轴","","SRT 字幕 (*.srt);;文本 (*.txt)")
        if not path: return
        try:
            text=Path(path).read_text(encoding="utf-8-sig"); text,fixes=fix_srt_overlaps(text); self.override_text.setPlainText(text); source=self._timeline_source()
            if source: self.timeline_overrides[self._timeline_key(source)]=text
            self._append_run_log(f"已载入 SRT：{Path(path).name}"
                                 +(f"，并自动修正 {fixes} 处时间重叠。" if fixes else "，未检测到时间重叠。"))
        except Exception as exc: QMessageBox.critical(self,"无法读取字幕",str(exc))

    def _choose_videos(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择视频", "", "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)"); self._add(self.videos, files, VIDEO_EXTENSIONS)

    def _choose_audio(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频", "", "音频 (*.mp3 *.wav *.m4a *.flac *.aac *.ogg *.opus)"); self._add(self.audios, files, AUDIO_EXTENSIONS)

    def _choose_folder(self, widget, extensions):
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if folder: self._add(widget, [folder], extensions)

    def generate_tts(self):
        text = self.tts_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "没有文案", "请先输入需要转成语音的文案。")
            return
        videos = [Path(self.videos.item(i).text()) for i in range(self.videos.count())]
        scripts = [block.strip() for block in re.split(r"(?:\r?\n\s*---\s*\r?\n|(?:\r?\n\s*){2,})", text)
                   if block.strip()]
        if len(scripts) == 1 and len(videos) > 1:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) == len(videos): scripts = lines
        if videos and len(scripts) not in (1, len(videos)):
            QMessageBox.warning(
                self, "文案数量不匹配",
                f"当前有 {len(videos)} 个视频、{len(scripts)} 段文案。\n"
                "请让文案数量与视频一致；每段之间用空行或单独一行 --- 分隔。\n"
                "若只提供一段文案，则会生成一条共享配音。")
            return
        output = Path(self.output.text()); output.mkdir(parents=True, exist_ok=True)
        if videos and len(scripts) == len(videos):
            jobs = [(script, str(output / f"{video.stem}_配音.mp3"))
                    for script, video in zip(scripts, videos)]
        else:
            start = len(list(output.glob("配音_*.mp3"))) + 1
            jobs = [(script, str(output / f"配音_{start + index:03d}.mp3"))
                    for index, script in enumerate(scripts)]
        self.tts_generate.setEnabled(False); self.tts_generate.setText(f"排队生成 0/{len(jobs)}")
        self.tts_thread = QThread(self)
        self.tts_worker = BatchTtsWorker(self.tts_callable, jobs, self.tts_service.currentText(),
                                        self.tts_voice.currentText().strip())
        self.tts_worker.moveToThread(self.tts_thread); self.tts_thread.started.connect(self.tts_worker.run)
        self.tts_worker.item_done.connect(self._tts_item_done)
        self.tts_worker.finished.connect(self._tts_done); self.tts_worker.finished.connect(self.tts_thread.quit)
        self.tts_thread.finished.connect(self._tts_ended); self.tts_thread.finished.connect(self.tts_thread.deleteLater)
        self.tts_thread.start()

    def tts_service_changed(self, service):
        if not hasattr(self, "tts_voice"): return
        current = self.tts_voice.currentText()
        if service == "微软文字转语音":
            self._load_microsoft_voices()
        elif service == "Gemini 自然语音":
            self._load_gemini_voices()
        else:
            self.tts_voice.clear()
            self.tts_voice.addItem("请粘贴 ElevenLabs Voice ID")
        if current and ((service == "微软文字转语音" and current.endswith("Neural")) or
                        (service == "Gemini 自然语音" and "｜" in current) or
                        (service == "ElevenLabs API" and not current.endswith("Neural") and "｜" not in current)):
            self.tts_voice.setCurrentText(current)

    def _tts_item_done(self, ok, result, message, index, total):
        self.tts_generate.setText(f"排队生成 {index}/{total}")
        if ok:
            self._add(self.audios, [result], AUDIO_EXTENSIONS)
            self.log.appendPlainText(f"[{index}/{total}] {message}：{Path(result).name}")
        else:
            self.log.appendPlainText(f"[{index}/{total}] 配音失败，继续下一条：{message}")

    def _tts_done(self, ok, result):
        self.tts_generate.setEnabled(True); self.tts_generate.setText("批量生成并加入音频队列")
        self.log.appendPlainText(result)
        if self.audios.count():
            self.audios.setCurrentRow(0)
            self.log.appendPlainText("配音已按视频名称/队列建立匹配；可试听后再批量提取全部时间轴。")
        if not ok:
            self._append_run_log("批量配音存在失败项；已继续处理其余任务，可在“帮助 → 软件日志”查看详情。")

    def _tts_ended(self):
        self.tts_worker = None; self.tts_thread = None

    def pick_color(self, button):
        current = re.search(r"#[0-9A-Fa-f]{6}", button.text()); color = QColorDialog.getColor(QColor(current.group() if current else "#ffffff"), self)
        if color.isValid():
            button.setText(re.sub(r"#[0-9A-Fa-f]{6}", color.name().upper(), button.text())); self.update_style_preview(); self._refresh_live_preview(); self._save_style_preferences()

    def apply_preset(self, name):
        preset = PRESETS[name]
        for button in self.preset_buttons: button.setChecked(button.text() == name)
        highlight_label = "跟读文字" if preset["effect"] == "word_color" else "跟读背景"
        self.text_color.setText(f"文字 {preset['text']}"); self.outline_color.setText(f"描边 {preset['outline']}"); self.highlight_color.setText(f"{highlight_label} {preset['highlight']}")
        self.outline_width.setValue(preset["outline_width"])
        if "font" in preset: self.font.setCurrentText(preset["font"])
        if "font_size" in preset: self.font_size.setValue(preset["font_size"])
        if "line_length" in preset: self.line_length.setValue(preset["line_length"])
        if "line_width" in preset: self.line_width.setValue(preset["line_width"])
        if "letter_spacing" in preset: self.letter_spacing.setValue(preset["letter_spacing"])
        self.word_spacing.setValue(preset.get("word_spacing",0))
        if "line_spacing" in preset: self.line_spacing.setValue(preset["line_spacing"])
        if "margin_v" in preset: self.margin_v.setValue(preset["margin_v"])
        if "max_words" in preset: self.max_words.setValue(preset["max_words"])
        if "highlight_padding" in preset: self.highlight_padding.setValue(preset["highlight_padding"])
        self.highlight_padding_y.setValue(preset.get("highlight_padding_y",10))
        if "animation_speed" in preset: self.animation_speed.setValue(preset["animation_speed"])
        if hasattr(self, "preview_position_slider"):
            self.preview_position_slider.blockSignals(True)
            self.preview_position_slider.setValue(self.margin_v.value())
            self.preview_position_slider.blockSignals(False)
            self.preview_position_value.setText(f"距底部 {self.margin_v.value()}")
        self.update_style_preview(); self._refresh_live_preview()
        self._save_style_preferences()

    def update_style_preview(self):
        if not hasattr(self, "style_preview"): return
        text = self._hex(self.text_color); highlight = self._hex(self.highlight_color)
        self.style_preview.setText(
            f'<span style="color:{text};font-size:20px;font-weight:700;">整句稳定显示，当前词 </span>'
            f'<span style="background:{highlight};border-radius:8px;color:#ffffff;font-size:22px;font-weight:800;padding:6px 10px;">跟随朗读</span>')

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if folder: self.output.setText(folder)

    def _send_export_output_to_rename(self):
        root = Path(self.output.text()).expanduser()
        candidates = [(root, "批量输出"), (root / "00_分组合成", "分组合成")]
        available = []
        for folder, label in candidates:
            if not folder.is_dir():
                continue
            videos = [item for item in folder.iterdir()
                      if item.is_file() and item.suffix.casefold() in VIDEO_EXTENSIONS]
            if videos:
                available.append((max(item.stat().st_mtime_ns for item in videos), folder, label))
        if not available:
            self._request_rename_folder(root, "合成/批量输出")
            return
        _mtime, folder, label = max(available, key=lambda item: item[0])
        self._request_rename_folder(folder, label)

    def _request_rename_folder(self, folder, source_label):
        folder=Path(folder).expanduser()
        if not folder.is_dir():
            QMessageBox.information(self,"没有可加入的成品",f"{source_label}成品文件夹尚不存在：\n{folder}")
            return
        videos=[item for item in folder.iterdir()
                if item.is_file() and item.suffix.casefold() in VIDEO_EXTENSIONS]
        if not videos:
            QMessageBox.information(self,"没有可加入的成品",f"{source_label}文件夹中还没有可重命名的视频：\n{folder}")
            return
        resolved=str(folder.resolve())
        self._append_run_log(f"已把{source_label}成品加入批量重命名：{resolved}（{len(videos)} 个视频）")
        self.rename_folder_requested.emit(resolved)

    def refresh_sync_profiles(self):
        current = self.cloud_sync_profile.currentData() if hasattr(self, "cloud_sync_profile") else ""
        names, active = [], ""
        if callable(self.sync_profiles_callable):
            try:
                names, active = self.sync_profiles_callable()
            except Exception as exc:
                if hasattr(self, "log"): self.log.appendPlainText(f"读取同步方案失败：{exc}")
        self.cloud_sync_profile.blockSignals(True); self.cloud_sync_profile.clear()
        self.cloud_sync_profile.addItem("使用当前设置", "")
        for name in names: self.cloud_sync_profile.addItem(str(name), str(name))
        target = current or active
        index = self.cloud_sync_profile.findData(target)
        self.cloud_sync_profile.setCurrentIndex(index if index >= 0 else 0)
        self.cloud_sync_profile.blockSignals(False); self._update_cloud_sync_hint()

    def _open_sync_settings(self):
        if callable(self.open_sync_settings_callable): self.open_sync_settings_callable()

    def _update_cloud_sync_hint(self, *_args):
        if not hasattr(self, "cloud_sync_hint"): return
        if not self.cloud_sync_check.isChecked():
            self.cloud_sync_hint.setText("未开启：本次只批量生成本地 Reels 成品")
            return
        profile = self.cloud_sync_profile.currentData() or "当前设置"
        self.cloud_sync_hint.setText(f"已开启：本地批量生成完成后，使用“{profile}”上传并按配置写入 Google Sheets")

    def _hex(self, button): return re.search(r"#[0-9A-Fa-f]{6}", button.text()).group()

    def _clear_previews_and_releases(self):
        if hasattr(self, "player") and self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        if hasattr(self, "audio_player") and self.audio_player:
            self.audio_player.stop()
            self.audio_player.setSource(QUrl())
        if hasattr(self, "preview_capture") and self.preview_capture is not None:
            self.preview_capture.release()
            self.preview_capture = None
        if hasattr(self, "video_widget") and self.video_widget:
            self.video_widget.setText("正在执行批量合成中，预览已暂停以释放资源")
            self.video_widget.setPixmap(QPixmap())

    def run(self):
        videos = [self.videos.item(i).text() for i in range(self.videos.count())]
        audios = [self.audios.item(i).text() for i in range(self.audios.count())]
        if not videos: QMessageBox.information(self, "没有视频", "请先添加视频素材。"); return
        self._clear_previews_and_releases()
        try: ffmpeg = self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self, "缺少组件", str(exc)); return
        settings = self._current_settings(); self.generated_records = []; self._batch_expected_count=len(videos)
        # 只有 00_分组合成 中的全部中间视频都进入本次渲染队列，
        # 才在全部最终成品成功后删除目录，避免误删未处理的组。
        group_dir=(Path(self.output.text()).expanduser()/"00_分组合成").resolve()
        queued_group={str(Path(path).resolve()) for path in videos if Path(path).resolve().parent==group_dir}
        existing_group=({str(path.resolve()) for path in group_dir.iterdir()
                         if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS}
                        if group_dir.is_dir() else set())
        self._pending_group_cleanup_dir=(group_dir if existing_group and existing_group.issubset(queued_group) else None)
        self.log.clear(); self.progress.setValue(0)
        self.log_status.setText("任务已开始；详细记录写入“帮助 → 软件日志”")
        self.log_status.setStyleSheet("color:#7dd3fc;font-size:11px;")
        self.thread = QThread(self)
        callback = lambda path: self.transcribe_callable(path, settings["provider"])
        self.worker = CaptionWorker(videos, audios, self.output.text(), ffmpeg, callback, settings)
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append_run_log); self.worker.progress.connect(self.progress.setValue)
        self.worker.result.connect(self._batch_result_ready)
        self.worker.timeline_ready.connect(self._worker_timeline_ready)
        self.worker.finished.connect(self.done); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.ended); self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False); self.stop.setEnabled(True); self.thread.start()

    def cancel(self):
        if self.worker: self.worker.cancel()

    def _batch_result_ready(self, path, original, chinese):
        self.generated_records.append({"path":str(path), "original":str(original or ""), "chinese":str(chinese or "")})

    def done(self, ok, message):
        self.start.setEnabled(True); self.stop.setEnabled(False); self._append_run_log(message)
        self.run_status.setText("当前状态：已完成" if ok else "当前状态：执行失败，请到“帮助 → 软件日志”查看")
        self._cleanup_completed_group_intermediates(ok)
        if ok and self.cloud_sync_check.isChecked():
            files=[item["path"] for item in self.generated_records if Path(item.get("path","")).is_file()]
            if files and callable(self.cloud_sync_callable):
                profile=self.cloud_sync_profile.currentData() or ""
                self._append_run_log(f"本地成品已完成，开始使用同步方案“{profile or '当前设置'}”上传并填表……")
                try:
                    self.cloud_sync_callable(files, list(self.generated_records), profile)
                except Exception as exc:
                    self._append_run_log(f"自动上传未启动：{exc}；本地视频成品不受影响。")
                    QMessageBox.warning(self,"自动上传未启动",f"本地视频已经生成完成。\n\n上传/填表未启动：{exc}")
            elif not files:
                self._append_run_log("未找到本次生成的成品，已跳过自动上传。")
        (QMessageBox.information if ok else QMessageBox.critical)(self, "动态文案" if ok else "生成失败", message)

    def _cleanup_completed_group_intermediates(self, ok):
        folder=self._pending_group_cleanup_dir
        self._pending_group_cleanup_dir=None
        completed=[Path(item.get("path","")) for item in self.generated_records]
        all_completed=(ok and self._batch_expected_count > 0 and
                       len(completed)==self._batch_expected_count and
                       all(path.is_file() and path.stat().st_size>1024 for path in completed))
        if not folder: return False
        if not all_completed:
            self._append_run_log("本次未全部渲染成功，已保留分组合成中间文件供断点续接。")
            return False
        try:
            self._clear_previews_and_releases()
            import gc
            gc.collect()
            import time
            for i in range(5):
                try:
                    shutil.rmtree(folder)
                    break
                except OSError:
                    if i == 4:
                        raise
                    time.sleep(0.2)
            removed={str(Path(path).resolve()) for path in self.group_merge_outputs}
            self.group_merge_outputs=[]
            for key in list(self._baked_watermarks):
                if key in removed: self._baked_watermarks.pop(key,None)
            QSettings("VideoToolkit","DynamicReels").setValue(
                "baked_watermarks",json.dumps(self._baked_watermarks,ensure_ascii=False))
            self._append_run_log("最终成品已全部生成；已自动清理 00_分组合成 中间视频与断点缓存，输出目录只保留最终成品。")
            return True
        except OSError as exc:
            self._append_run_log(f"最终成品已生成，但中间目录自动清理失败：{exc}")
            write_app_log(f"清理分组合成中间目录失败：{folder}｜{exc}","ERROR","Reels")
            return False

    def ended(self): self.worker = None; self.thread = None
