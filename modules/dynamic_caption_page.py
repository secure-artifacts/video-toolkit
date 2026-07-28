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

from PySide6.QtCore import QObject, QRectF, QSettings, QThread, QTimer, Qt, QUrl, Signal, QDate
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontInfo, QFontMetricsF, QImage, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QDateEdit, QTextBrowser,
    QAbstractSpinBox,
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QTabWidget,
    QStackedWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QVBoxLayout, QWidget,
)

from .path_picker import (
    AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS, DropFolderLineEdit, DropListWidget, DropButton, DropTableWidget, collect_files, default_output_path, natural_key,
)

ALLOWED_VIDEO_INPUTS = VIDEO_EXTENSIONS.union(IMAGE_EXTENSIONS)


def _configure_numeric_spin(spin, min_width=104, min_height=28):
    """保证 SpinBox 数字与后缀完整显示（Win11 窄栏不会裁成 I/O/x 残影）。"""
    spin.setMinimumWidth(int(min_width))
    spin.setMinimumHeight(int(min_height))
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
    # MinimumExpanding：布局优先保证内容宽度，避免被两侧预设列表挤扁
    spin.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
    try:
        spin.setKeyboardTracking(True)
    except Exception:
        pass
    return spin


from .group_merge import (
    GroupMergeWorker,
    build_segmented_edit_state,
    discover_groups,
    load_group_segments_map,
    merge_transition_labels,
    resolve_merge_transition,
    split_group_script,
    try_rebuild_segments_sidecar,
)
from .settings_page import hidden_kwargs
from .text_rules import normalize_required_capitalization, normalize_subtitle_text
from .language_style import (
    WRITING_LANGUAGE_OPTIONS, effective_letter_spacing, fill_writing_language_combo,
    is_rtl_text, prepare_ass_dialogue_text, should_disable_word_highlight,
    suggest_font_for_text, writing_language_from_ui,
)
from .video_encoding import (
    ENCODER_LABELS, encoder_args, resolve_encoder, calculate_target_size,
    diagnose_encoders, encoder_probe_detail,
)
from .app_logging import write_app_log
from .canva_timeline import CanvaTimelinePanel, TransitionPresetButton
from .platform_utils import app_data_dir
from .rename_page import clean_filename_part, safe_filename


PRESETS = {
    "Descript 经典黄": {"text": "#F8FAFC", "outline": "#111111", "highlight": "#FACC15", "outline_width": 5,
                         "effect": "word_color", "font": "Arial", "font_size": 90, "line_length": 26,
                         "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                         "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "双眼皮 经典红黄黑": {"text": "#FF0000", "outline": "#FFFF00", "highlight": "#111111", "outline_width": 3,
                           "effect": "double_outline", "font": "Arial", "font_size": 90, "line_length": 26,
                           "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                           "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "双眼皮 极光绿白黑": {"text": "#FFFFFF", "outline": "#A3E635", "highlight": "#111111", "outline_width": 3,
                           "effect": "double_outline", "font": "Arial", "font_size": 90, "line_length": 26,
                           "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                           "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "双眼皮 炫彩黄蓝黑": {"text": "#FACC15", "outline": "#2563EB", "highlight": "#111111", "outline_width": 3,
                           "effect": "double_outline", "font": "Arial", "font_size": 90, "line_length": 26,
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
    # CapCut/Reels：先整句语义排版定稿（位置固定），再按语速逐词弹出；句末硬切防叠字
    "Reels 语义重点": {
        "text": "#FFFFFF", "outline": "#0A0A0A", "highlight": "#FFFFFF", "outline_width": 5,
        "effect": "semantic_stack", "font_size": 86, "line_length": 22,
        "letter_spacing": -1, "line_spacing": 115, "margin_v": 480,
        "max_words": 7, "highlight_padding": 10, "animation_speed": 70,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 88,
        # 重点词约 +18%，其余约 -22%，差距能看清又不过分
        "semantic_large_ratio": 1.18,
        "semantic_small_ratio": 0.78,
        # 不再提前出字，严格跟词级时间，避免「字幕提前导致对不上」
        "semantic_lead_ms": 0,
    },
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

CAPTION_RENDERER_VERSION = 10


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
        effect = self.preset.get("effect", "word_color")
        indicator_color = self.preset["text"] if effect == "double_outline" else self.preset["highlight"]
        painter.fillRect(2,7,6,max(10,self.height()-14),QColor(indicator_color))
        name_font = QFont(self.font()); name_font.setPixelSize(11); name_font.setBold(False); painter.setFont(name_font)
        painter.setPen(QColor("#CBD5E1")); painter.drawText(QRectF(14,4,self.width()-20,18),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,self.name)
        sample = "字幕样式"; font = QFont(self.preset.get("font","Arial")); font.setPixelSize(17); font.setBold(True)
        painter.setFont(font); metrics=QFontMetricsF(font); width=metrics.horizontalAdvance(sample); x=14; baseline=48
        text_color=QColor(self.preset["text"]); highlight=QColor(self.preset["highlight"]); outline=QColor(self.preset["outline"])
        if effect in ("descript","heygen","highlight"):
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(highlight); painter.drawRoundedRect(QRectF(x-3,27,width+8,24),5,5)
            painter.setPen(text_color); painter.drawText(x,baseline,sample)
        elif effect == "underline":
            painter.setPen(text_color); painter.drawText(x,baseline,sample); painter.setPen(QPen(highlight,3)); painter.drawLine(int(x),52,int(x+width),52)
        elif effect in ("outline","glow"):
            path=QPainterPath(); path.addText(x,baseline,font,sample)
            if effect == "glow": painter.setPen(QPen(highlight,7)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
            painter.setPen(QPen(outline,max(2,int(self.preset.get("outline_width",3))))); painter.setBrush(text_color); painter.drawPath(path)
        elif effect == "double_outline":
            path=QPainterPath(); path.addText(x,baseline,font,sample)
            painter.setPen(QPen(highlight,max(2,int(self.preset.get("outline_width",3)))+4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setPen(QPen(outline,max(2,int(self.preset.get("outline_width",3))),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(text_color)
            painter.drawPath(path)
        elif effect == "word_color":
            painter.setPen(text_color); painter.drawText(x,baseline,"字幕"); x2=x+metrics.horizontalAdvance("字幕")
            painter.setPen(highlight); painter.drawText(x2,baseline,"样式")
        elif effect in ("semantic_stack", "word_scale"):
            # 预览卡：大号重点 + 小号陪衬，示意语义堆叠
            small = QFont(font); small.setPixelSize(11); small.setBold(True)
            big = QFont(font); big.setPixelSize(18); big.setBold(True)
            painter.setFont(big); painter.setPen(text_color); painter.drawText(x, baseline - 2, "重点")
            painter.setFont(small); painter.setPen(text_color)
            painter.drawText(x + QFontMetricsF(big).horizontalAdvance("重点") + 3, baseline, "铺陈")
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


def parse_srt(srt, language=None):
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
        # 专名大小写 + 语言包引号/书写规范（希腊 «»、中文标点等）。
        text = normalize_subtitle_text("\n".join(lines[timing_index + 1:]).strip(), language=language)
        if text: result.append((start, max(start + .1, end), text))
    return result


def extract_first_srt_line(srt_content):
    if not srt_content:
        return ""
    entries = parse_srt(srt_content)
    if entries:
        text = entries[0][2].strip().replace("\n", " ")
        text = re.sub(r'[\\/:*?"<>|]', "", text)
        return text
    return ""


def shift_srt_timestamps(srt_content, shift_seconds):
    if not srt_content or shift_seconds == 0.0:
        return srt_content
    pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
    
    def replace_time(match):
        h, m, s, ms = map(int, match.groups())
        total_seconds = h * 3600 + m * 60 + s + ms / 1000.0
        new_seconds = max(0.0, total_seconds - shift_seconds)
        
        new_h = int(new_seconds // 3600)
        new_seconds %= 3600
        new_m = int(new_seconds // 60)
        new_seconds %= 60
        new_s = int(new_seconds)
        new_ms = int(round((new_seconds - new_s) * 1000))
        
        return f"{new_h:02d}:{new_m:02d}:{new_s:02d},{new_ms:03d}"
        
    return pattern.sub(replace_time, srt_content)


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


def group_word_srt(srt, max_chars=36, max_duration=4.6, max_words=999, return_fix_count=False):
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
        # 完全根据语音停顿与语义自适应，仅通过 max_chars (字宽限制，最多2行) 作硬切分
        if current and ((pause >= .52 and len(current) >= 2) or len(current) >= max_words or len(candidate) > max_chars
                        or (w_end - (start or w_start)) > max_duration):
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
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except Exception:
        pass
    # Some packaged Windows builds contain ffmpeg.exe but no adjacent
    # ffprobe.exe.  Falling back to ffmpeg's input header keeps audio
    # detection reliable instead of silently treating every source as mute.
    try:
        result = subprocess.run(
            [str(ffmpeg_path), "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **hidden_kwargs())
        return bool(re.search(r"Stream\s+#.*:\s+Audio:", result.stderr or ""))
    except Exception:
        return False


def render_timeline_edits(ffmpeg, source, state, cache_dir):
    """Materialize the visual editor's ordered video cuts before the normal render pipeline."""
    source=Path(source)
    tracks=(state or {}).get("tracks",{})
    segments=list(tracks.get("video",[]) or [])
    if not segments:
        return source
    segments=sorted(segments,key=lambda item:(int(item.get("start",0)),int(item.get("end",0))))
    transitions=list((state or {}).get("transitions",[]) or [])
    original_duration=max(1,int(media_duration(ffmpeg,source)*1000))
    unchanged=(len(segments)==1 and int(segments[0].get("source_start",0))<=5
               and abs(int(segments[0].get("source_end",original_duration))-original_duration)<=20)
    original_audio_enabled=bool((state or {}).get("original_audio_enabled",True))
    if unchanged and original_audio_enabled and not transitions:
        return source
    payload=json.dumps({"source":str(source.resolve()),"mtime":source.stat().st_mtime_ns,
                        "segments":segments,"audio":original_audio_enabled,
                        "transitions":transitions},sort_keys=True)
    key=hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    cache=Path(cache_dir)/".timeline_edit_cache"; cache.mkdir(parents=True,exist_ok=True)
    output=cache/f"{source.stem[:28]}_{key}.mp4"
    if output.is_file() and output.stat().st_size>1024:
        return output
    has_audio=original_audio_enabled and media_has_audio(ffmpeg,source)
    filters=[]; concat_inputs=[]; segment_durations=[]
    for index,item in enumerate(segments):
        start=max(0,float(item.get("source_start",0))/1000)
        end=max(start+.08,float(item.get("source_end",0))/1000)
        segment_durations.append(end-start)
        filters.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
        concat_inputs.append(f"[v{index}]")
        if has_audio:
            filters.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]")
            concat_inputs.append(f"[a{index}]")
    if transitions and len(segments)>1:
        video_output="[v0]"
        audio_output="[a0]" if has_audio else ""
        accumulated=segment_durations[0]
        for index in range(1,len(segments)):
            boundary=int(segments[index-1].get("end",0))
            marker=min(
                transitions,
                key=lambda item:abs(int(item.get("position",0))-boundary),
                default=None,
            )
            if marker and abs(int(marker.get("position",0))-boundary)<=1000:
                cfg=resolve_merge_transition(marker.get("name"))
                requested=max(.10,float(marker.get("duration_ms",500))/1000)
            else:
                cfg=None
                requested=.001
            duration=min(requested,segment_durations[index-1]*.45,segment_durations[index]*.45)
            duration=max(.001,duration)
            transition_key=(cfg or {}).get("xfade","fade")
            offset=max(.001,accumulated-duration)
            next_video=f"[vx{index}]"
            filters.append(
                f"{video_output}[v{index}]xfade=transition={transition_key}:"
                f"duration={duration:.3f}:offset={offset:.3f}{next_video}"
            )
            video_output=next_video
            if has_audio:
                next_audio=f"[ax{index}]"
                filters.append(
                    f"{audio_output}[a{index}]acrossfade=d={duration:.3f}:"
                    f"c1=tri:c2=tri{next_audio}"
                )
                audio_output=next_audio
            accumulated+=segment_durations[index]-duration
        maps=["-map",video_output]
        if has_audio:
            maps+=["-map",audio_output]
        else:
            maps+=["-an"]
    elif has_audio:
        filters.append("".join(concat_inputs)+f"concat=n={len(segments)}:v=1:a=1[vout][aout]")
        maps=["-map","[vout]","-map","[aout]"]
    else:
        filters.append("".join(f"[v{i}]" for i in range(len(segments)))+
                       f"concat=n={len(segments)}:v=1:a=0[vout]")
        maps=["-map","[vout]","-an"]
    command=[ffmpeg,"-hide_banner","-loglevel","error","-y","-i",str(source),
             "-filter_complex",";".join(filters),*maps,
             "-c:v","libx264","-preset","ultrafast","-crf","22","-pix_fmt","yuv420p","-threads","0"]
    if has_audio:
        command+=["-c:a","aac","-b:a","160k"]
    command.append(str(output))
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if result.returncode!=0 or not output.is_file():
        raise RuntimeError("时间轴切片渲染失败："+result.stderr.decode("utf-8","replace")[-800:])
    return output


def render_timeline_audio(ffmpeg, source, clips, cache_dir, label="audio"):
    """Render sliced/moved audio clips, including gaps, into one timeline-aligned track."""
    source=Path(source)
    clips=list(clips or [])
    if not source.is_file() or not clips:
        return None
    payload=json.dumps({"source":str(source.resolve()),"mtime":source.stat().st_mtime_ns,
                        "clips":clips},sort_keys=True)
    key=hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    cache=Path(cache_dir)/".timeline_edit_cache"; cache.mkdir(parents=True,exist_ok=True)
    output=cache/f"{label}_{key}.m4a"
    if output.is_file() and output.stat().st_size>512:
        return output
    filters=[]; outputs=[]
    for index,item in enumerate(clips):
        source_start=max(0,float(item.get("source_start",0))/1000)
        source_end=max(source_start+.08,float(item.get("source_end",0))/1000)
        timeline_start=max(0,int(item.get("start",0) or 0))
        chain=(f"[0:a]atrim=start={source_start:.3f}:end={source_end:.3f},"
               "asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo")
        if timeline_start:
            chain+=f",adelay={timeline_start}|{timeline_start}"
        chain+=f"[a{index}]"
        filters.append(chain); outputs.append(f"[a{index}]")
    if len(outputs)>1:
        filters.append("".join(outputs)+
                       f"amix=inputs={len(outputs)}:duration=longest:normalize=0[aout]")
        output_label="[aout]"
    else:
        output_label=outputs[0]
    command=[ffmpeg,"-hide_banner","-loglevel","error","-y","-i",str(source),
             "-filter_complex",";".join(filters),"-map",output_label,
             "-c:a","aac","-b:a","192k","-ar","48000",str(output)]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if result.returncode!=0 or not output.is_file():
        raise RuntimeError("音频轨道切片渲染失败："+result.stderr.decode("utf-8","replace")[-800:])
    return output


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
                       fade_out_ms=500, duration=0, background_delay_ms=0):
    """Shared FFmpeg graph used by exact preview and final export."""
    original = max(0, min(200, int(original_volume))) / 100
    background = max(0, min(200, int(background_volume))) / 100
    background_filters=["aresample=48000","aformat=channel_layouts=stereo",f"volume={background:.3f}"]
    if int(background_delay_ms or 0)>0:
        background_filters.append(f"adelay={int(background_delay_ms)}|{int(background_delay_ms)}")
    background_filters.extend(added_audio_fade_filters(
        fade_mode,fade_in_ms,fade_out_ms,duration))
    return (
        f"[0:a:0]aresample=48000,aformat=channel_layouts=stereo,volume={original:.3f}[original_audio];"
        f"[1:a:0]{','.join(background_filters)}[background_audio];"
        "[original_audio][background_audio]amix=inputs=2:duration=longest:"
        "dropout_transition=2:normalize=0[aout]"
    )


def replacement_audio_filter(fade_mode="直接加入（无淡入淡出）", fade_in_ms=500,
                             fade_out_ms=500, duration=0, delay_ms=0):
    """Pad a replacement track with silence; -shortest then keeps video length."""
    filters=["aresample=48000","aformat=channel_layouts=stereo"]
    if int(delay_ms or 0)>0:
        filters.append(f"adelay={int(delay_ms)}|{int(delay_ms)}")
    filters.extend(added_audio_fade_filters(fade_mode,fade_in_ms,fade_out_ms,duration))
    filters.append("apad=pad_dur=86400")
    return f"[1:a:0]{','.join(filters)}[aout]"


def bgm_mix_audio_filter(dialogue_input, bgm_input, original_volume=100, background_volume=25,
                         fade_mode="直接加入（无淡入淡出）", fade_in_ms=500, fade_out_ms=500,
                         duration=0, dialogue_delay_ms=0, bgm_delay_ms=0):
    dialogue_vol = max(0, min(200, int(original_volume))) / 100
    bgm_vol = max(0, min(200, int(background_volume))) / 100
    bgm_filters = ["aresample=48000", "aformat=channel_layouts=stereo", f"volume={bgm_vol:.3f}"]
    if int(bgm_delay_ms or 0)>0:
        bgm_filters.append(f"adelay={int(bgm_delay_ms)}|{int(bgm_delay_ms)}")
    bgm_filters.extend(added_audio_fade_filters(fade_mode, fade_in_ms, fade_out_ms, duration))
    dialogue_filters=["aresample=48000","aformat=channel_layouts=stereo",f"volume={dialogue_vol:.3f}"]
    if int(dialogue_delay_ms or 0)>0:
        dialogue_filters.append(f"adelay={int(dialogue_delay_ms)}|{int(dialogue_delay_ms)}")
    return (
        f"{dialogue_input}{','.join(dialogue_filters)}[dialogue_audio];"
        f"{bgm_input}{','.join(bgm_filters)}[bgm_audio];"
        "[dialogue_audio][bgm_audio]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0[aout]"
    )


def bgm_only_audio_filter(bgm_input, background_volume=25,
                          fade_mode="", fade_in_ms=500, fade_out_ms=500,
                          duration=0, bgm_delay_ms=0):
    """Build a valid output track when BGM exists but the source has no audio."""
    bgm_vol = max(0, min(200, int(background_volume))) / 100
    filters = [
        "aresample=48000",
        "aformat=channel_layouts=stereo",
        f"volume={bgm_vol:.3f}",
    ]
    if int(bgm_delay_ms or 0) > 0:
        delay = int(bgm_delay_ms)
        filters.append(f"adelay={delay}|{delay}")
    filters.extend(added_audio_fade_filters(
        fade_mode, fade_in_ms, fade_out_ms, duration))
    filters.append("apad=pad_dur=86400")
    return f"{bgm_input}{','.join(filters)}[aout]"


def find_bgm_file(bgm_dir, index, video=None, randomize=False):
    """Resolve a BGM path from a single file or a folder of audio/video clips."""
    if not bgm_dir:
        return None
    path = Path(bgm_dir)
    if path.is_file():
        if path.suffix.lower() in AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS):
            return path
        return None
    if not path.is_dir():
        return None
    bgm_files = sorted(
        [x for x in path.rglob("*") if x.is_file()
         and x.suffix.lower() in AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS)],
        key=lambda x: natural_key(x.name)
    )
    if not bgm_files:
        return None
    if randomize and video:
        import random, hashlib
        # 使用基于视频绝对路径和索引的 MD5 哈希种子，保证重启后分配结果一致且分布均匀
        h = hashlib.md5(f"{Path(video).resolve()}_{index}".encode("utf-8")).hexdigest()
        rnd = random.Random(int(h, 16))
        return rnd.choice(bgm_files)
    return bgm_files[index % len(bgm_files)]


def random_bgm_start_ms(ffmpeg, bgm_file, video=None, index=0, seed_tag="bgm_crop"):
    """Stable per-video random start offset so BGM is not always from 0s."""
    import random, hashlib
    try:
        bgm_dur = float(media_duration(ffmpeg, bgm_file) or 0)
    except Exception:
        bgm_dur = 0.0
    if bgm_dur <= 2.0:
        return 0
    key = f"{Path(video).resolve() if video else 'bgm'}_{index}_{seed_tag}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    rnd = random.Random(int(h, 16))
    return int(rnd.uniform(0.0, max(0.1, bgm_dur - 1.0)) * 1000)


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
    motion_fp = []
    for item in settings.get("motion_tracks") or []:
        if not isinstance(item, dict):
            continue
        pts = item.get("points") or []
        motion_fp.append({
            "id": item.get("id"), "mode": item.get("mode"), "blur": item.get("blur"),
            "n": len(pts),
            "p0": pts[0] if pts else None,
            "p1": pts[-1] if pts else None,
        })
    payload={"video":_media_signature(video),"audio":_media_signature(audio),"settings":settings,
             "watermarks":watermark_files,"font_assets":font_assets,
             "motion_tracks": motion_fp,
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
    lang = settings.get("caption_language") or settings.get("language")
    value = normalize_subtitle_text(str(text or "").strip(), language=lang)
    if not value:
        return ""
    if "-->" in value:
        return normalize_subtitle_text(value, language=lang)
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


# 虚词/功能词：语义重点排版时默认小号；内容词按得分挑大号
_EMPHASIS_STOPWORDS = {
    # English
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "for", "with", "as", "at",
    "by", "from", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did", "have", "has",
    "had", "will", "would", "can", "could", "should", "may", "might", "must", "this", "that", "these",
    "those", "it", "its", "my", "your", "his", "her", "our", "their", "me", "you", "him", "them",
    "we", "they", "i", "not", "no", "so", "than", "then", "too", "very", "just", "also", "only",
    "into", "about", "over", "after", "before", "when", "what", "who", "which", "how", "why", "all",
    "any", "some", "more", "most", "other", "such", "own", "same", "both", "each", "few", "many",
    "much", "up", "out", "off", "down", "again", "further", "once", "here", "there", "where", "while",
    "because", "though", "although", "until", "unless", "whether", "nor", "yet", "per", "via",
    # Portuguese / Spanish common function words
    "o", "os", "as", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos", "e", "em", "no",
    "na", "nos", "nas", "que", "se", "por", "para", "com", "sem", "ao", "aos", "ou", "mas", "como",
    "já", "não", "nao", "mais", "el", "la", "los", "las", "un", "una", "del", "al", "y", "en",
    "lo", "le", "les", "su", "sus", "mi", "tu", "me", "te", "nos", "vos", "es", "son", "está",
    "esta", "são", "sao", "ser", "estar", "foi", "era", "há", "ha", "tem", "ter", "um", "uma",
    "pra", "pro", "pela", "pelo", "pelas", "pelos", "entre", "sobre", "até", "ate", "depois",
    "antes", "quando", "onde", "quem", "qual", "quais", "porque", "pois", "então", "entao",
    # Chinese particles / light words
    "的", "了", "着", "过", "在", "是", "和", "与", "或", "就", "都", "也", "还", "很", "把", "被",
    "让", "给", "从", "向", "到", "对", "等", "及", "而", "并", "又", "再", "已", "将", "会", "能",
    "要", "可", "这", "那", "哪", "什么", "怎么", "一个", "一些", "没有", "不是", "我们", "你们",
    "他们", "她们", "它们", "自己",
}


def _token_core(token: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff']+", "", str(token or ""), flags=re.UNICODE)


def select_emphasis_words(tokens):
    """按语义启发式挑选重点词（大号）；虚词/介词等小号。结果对同一句稳定可复现。"""
    tokens = list(tokens or [])
    n = len(tokens)
    if n == 0:
        return []
    scores = []
    for index, token in enumerate(tokens):
        core = _token_core(token)
        if not core:
            scores.append(-100.0)
            continue
        low = core.casefold()
        is_cjk = bool(re.search(r"[\u3400-\u9fff]", core))
        if low in _EMPHASIS_STOPWORDS or core in _EMPHASIS_STOPWORDS:
            scores.append(-12.0)
            continue
        # 过短的拉丁虚词倾向
        if not is_cjk and len(core) <= 2:
            scores.append(-4.0)
            continue
        score = 8.0 + min(len(core), 14)
        if index == 0:
            score += 2.5
        if index == n - 1:
            score += 3.5
        # 稳定“随机”扰动：同一词在同一句里结果固定，不同句有变化
        score += (abs(hash(f"{low}:{index}:{n}")) % 9)
        scores.append(score)

    content = [i for i, s in enumerate(scores) if s > 0]
    if not content:
        # 全是虚词时至少强调首尾有字的词，避免整屏全小
        emph = [False] * n
        for i in range(n):
            if _token_core(tokens[i]):
                emph[i] = True
                break
        for i in range(n - 1, -1, -1):
            if _token_core(tokens[i]):
                emph[i] = True
                break
        return emph

    # 短句 1 个重点，中句 2 个，长句最多 3 个
    if n <= 3:
        k = 1
    elif n <= 8:
        k = 2
    else:
        k = 3
    k = min(k, len(content))

    # 优先句首/句尾实词做大号（更像参考：bless … safe），再用得分补足
    picks = []
    picks.append(content[0])
    if k >= 2 and content[-1] != content[0]:
        picks.append(content[-1])
    ranked = sorted(content, key=lambda i: scores[i], reverse=True)
    for i in ranked:
        if len(picks) >= k:
            break
        if i in picks:
            continue
        # 尽量不与已选重点相邻，中间留给小号铺陈
        if any(abs(i - p) == 1 for p in picks):
            continue
        picks.append(i)
    if len(picks) < k:
        for i in ranked:
            if i in picks:
                continue
            picks.append(i)
            if len(picks) >= k:
                break
    emph = [False] * n
    for i in picks:
        emph[i] = True
    return emph


def _semantic_non_overlapping_phrases(entries, gap=0.08):
    """保证相邻句 end[i] <= start[i+1]-gap；必要时后移下一句，绝不把结束时间拉过下一句。"""
    if not entries:
        return []
    gap = max(0.02, float(gap))
    min_dur = 0.05
    out = [[float(s), float(e), t] for s, e, t in entries]
    # 1) 缩短过长的结束时间
    for i in range(len(out) - 1):
        limit = out[i + 1][0] - gap
        if out[i][1] > limit:
            out[i][1] = limit
    # 2) 若缩短后无效，后移下一句起点（而不是拉长当前句）
    for i in range(len(out) - 1):
        if out[i][1] < out[i][0] + min_dur:
            out[i][1] = out[i][0] + min_dur
        if out[i][1] > out[i + 1][0] - gap:
            out[i + 1][0] = out[i][1] + gap
            if out[i + 1][1] < out[i + 1][0] + min_dur:
                out[i + 1][1] = out[i + 1][0] + min_dur
    # 3) 丢弃仍无效的空窗
    cleaned = []
    for s, e, t in out:
        if e > s + 0.02 and str(t).strip():
            cleaned.append((s, e, t))
    return cleaned


def semantic_stack_layout(tokens, emphasized, settings):
    """
    语义堆叠排版：
    - 重点词：大号，独占一行
    - 普通词：小号，成组排成一行（自动按宽度换行）
    返回 lines: [[{token, large, size, width}, ...], ...]
    """
    tokens = list(tokens or [])
    if not tokens:
        return []
    if not emphasized or len(emphasized) != len(tokens):
        emphasized = select_emphasis_words(tokens)

    # 重点约 +18%、其余约 -22%（相对 base），层次清晰又不过分
    large_size, small_size = _semantic_font_sizes(settings)
    max_width = 1080 * max(40, min(96, int(settings.get("line_width", 88)))) / 100
    family = str(settings.get("font", "Arial"))
    bold = caption_uses_bold_face(settings)
    letter = float(settings.get("letter_spacing", 0))

    def make_metrics(size):
        font = QFont(family)
        font.setPixelSize(size)
        font.setBold(bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter)
        return QFontMetricsF(font)

    m_large = make_metrics(large_size)
    m_small = make_metrics(small_size)
    gap_large = max(2.0, m_large.horizontalAdvance(" ") + float(settings.get("word_spacing", 0)))
    gap_small = max(2.0, m_small.horizontalAdvance(" ") + float(settings.get("word_spacing", 0)))

    lines = []
    small_buf = []
    # 小号行不宜过长，参考图一般 2～4 词一行，更整齐
    max_small_words = max(2, min(5, int(settings.get("semantic_small_words", 3))))

    def flush_small():
        nonlocal small_buf
        if not small_buf:
            return
        current = []
        current_w = 0.0
        for item in small_buf:
            extra = gap_small if current else 0.0
            too_wide = current and current_w + extra + item["width"] > max_width * 0.90
            too_many = current and len(current) >= max_small_words
            if too_wide or too_many:
                lines.append(current)
                current = [item]
                current_w = item["width"]
            else:
                current.append(item)
                current_w += extra + item["width"]
        if current:
            lines.append(current)
        small_buf = []

    for token, is_large in zip(tokens, emphasized):
        if is_large:
            flush_small()
            width = max(large_size * 0.4, m_large.horizontalAdvance(token))
            lines.append([{
                "token": token, "large": True, "size": large_size, "width": width,
            }])
        else:
            width = max(small_size * 0.35, m_small.horizontalAdvance(token))
            small_buf.append({
                "token": token, "large": False, "size": small_size, "width": width,
            })
    flush_small()
    return lines


def _semantic_font_sizes(settings):
    """与 layout 一致的大小号像素尺寸（重点明显大于其余，但不过分夸张）。"""
    base = max(24, int(settings.get("font_size", 86)))
    large_ratio = float(settings.get("semantic_large_ratio", 1.18))
    small_ratio = float(settings.get("semantic_small_ratio", 0.78))
    large_size = max(28, int(round(base * max(1.05, min(1.35, large_ratio)))))
    small_size = max(20, int(round(base * max(0.65, min(0.92, small_ratio)))))
    if small_size >= large_size - 4:
        small_size = max(20, large_size - 12)
    return large_size, small_size


def semantic_stack_geometry(lines, settings):
    """把语义堆叠行居中摆到 1080x1920 画布，返回与 lines 同结构的几何信息。"""
    if not lines:
        return []
    large_size, small_size = _semantic_font_sizes(settings)
    family = str(settings.get("font", "Arial"))
    bold = caption_uses_bold_face(settings)
    letter = float(settings.get("letter_spacing", 0))

    def make_metrics(size):
        font = QFont(family)
        font.setPixelSize(size)
        font.setBold(bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter)
        return QFontMetricsF(font)

    m_large = make_metrics(large_size)
    m_small = make_metrics(small_size)
    gap_large = max(2.0, m_large.horizontalAdvance(" ") + float(settings.get("word_spacing", 0)))
    gap_small = max(2.0, m_small.horizontalAdvance(" ") + float(settings.get("word_spacing", 0)))
    spacing = max(70, min(180, int(settings.get("line_spacing", 118)))) / 100.0

    line_heights = []
    for line in lines:
        if any(item.get("large") for item in line):
            line_heights.append(max(large_size * 1.05, m_large.height()) * spacing)
        else:
            line_heights.append(max(small_size * 1.15, m_small.height()) * spacing * 0.92)

    total_h = sum(line_heights)
    position = settings.get("position", "画面中间")
    if position == "顶部":
        top = float(settings.get("margin_v", 250))
    elif position == "画面中间":
        top = max(80.0, 960.0 - total_h / 2.0)
    else:
        top = max(80.0, 1920.0 - float(settings.get("margin_v", 250)) - total_h)

    result = []
    y_cursor = top
    for line, height in zip(lines, line_heights):
        gap = gap_large if any(item.get("large") for item in line) else gap_small
        widths = [float(item["width"]) for item in line]
        total_w = sum(widths) + gap * max(0, len(widths) - 1)
        x_cursor = (1080.0 - total_w) / 2.0
        center_y = y_cursor + height / 2.0
        metrics = m_large if any(item.get("large") for item in line) else m_small
        baseline = center_y + metrics.ascent() / 2.0 - metrics.descent() / 2.0
        row = []
        for item, width in zip(line, widths):
            row.append({
                **item,
                "left": x_cursor,
                "x": x_cursor + width / 2.0,
                "y": center_y,
                "baseline": baseline,
                "width": width,
            })
            x_cursor += width + gap
        result.append(row)
        y_cursor += height
    return result


def _srt_stamp(value):
    milliseconds = max(0, round(float(value) * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _is_cjk_heavy(text):
    sample = str(text or "")
    if not sample:
        return False
    cjk = sum(1 for ch in sample if "\u3400" <= ch <= "\u9fff")
    letters = sum(1 for ch in sample if ch.isalpha() or "\u3400" <= ch <= "\u9fff")
    return letters > 0 and cjk / max(1, letters) > 0.35


def align_source_text_to_srt_cues(events, source_text):
    """Map plain source script onto existing SRT cues. Timestamps stay with events.

    Returns list[str] new cue texts (same length as events).
    """
    from difflib import SequenceMatcher

    if not events:
        return []
    source_text = re.sub(r"\s+", " ", str(source_text or "").strip())
    if not source_text:
        return [text for _s, _e, text in events]

    old_texts = [str(text or "").strip() for _s, _e, text in events]
    # 1) 句/行数恰好相等：一一对应
    chunks = [
        value.strip()
        for value in re.split(r"(?<=[。！？.!?…])\s*|\r?\n+", source_text)
        if value.strip()
    ]
    if len(chunks) == len(events):
        return chunks

    is_cjk = _is_cjk_heavy(source_text + "".join(old_texts))
    sep = "" if is_cjk else " "
    asr_tokens = []
    cue_of = []
    for index, text in enumerate(old_texts):
        toks = tokens_for(text)
        if not toks:
            # 空 cue 仍占位，后续用邻近插入
            continue
        for tok in toks:
            asr_tokens.append(tok)
            cue_of.append(index)
    src_tokens = tokens_for(source_text)
    if not src_tokens:
        return old_texts
    if not asr_tokens:
        # 均匀拆到各 cue
        n = len(events)
        out = [[] for _ in range(n)]
        for i, tok in enumerate(src_tokens):
            out[min(n - 1, i * n // max(1, len(src_tokens)))].append(tok)
        return [sep.join(parts) if parts else old_texts[i] for i, parts in enumerate(out)]

    # 2) 词级对齐：把原文 token 填回各 cue
    cue_tokens = [[] for _ in events]
    sm = SequenceMatcher(a=asr_tokens, b=src_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for offset, k in enumerate(range(i1, i2)):
                cue_tokens[cue_of[k]].append(src_tokens[j1 + offset])
        elif tag == "replace":
            src_slice = src_tokens[j1:j2]
            if i1 >= i2:
                target = cue_of[min(i1, len(cue_of) - 1)] if cue_of else 0
                cue_tokens[target].extend(src_slice)
            elif not src_slice:
                continue
            else:
                # 按 ASR 段覆盖的 cue 权重分配原文片段
                covered = cue_of[i1:i2]
                # 稳定顺序的 cue 列表
                order = []
                for c in covered:
                    if c not in order:
                        order.append(c)
                weights = [covered.count(c) for c in order]
                total = sum(weights) or len(order)
                pos = 0
                for oi, c in enumerate(order):
                    if oi == len(order) - 1:
                        piece = src_slice[pos:]
                    else:
                        take = max(1, round(len(src_slice) * weights[oi] / total))
                        take = min(take, max(0, len(src_slice) - pos - (len(order) - oi - 1)))
                        piece = src_slice[pos:pos + take]
                        pos += take
                    cue_tokens[c].extend(piece)
        elif tag == "delete":
            # 丢掉识别多出来的词，不写入
            continue
        elif tag == "insert":
            # 原文多出来的词：插到最近 cue
            if i1 < len(cue_of):
                target = cue_of[i1]
            elif cue_of:
                target = cue_of[-1]
            else:
                target = 0
            cue_tokens[target].extend(src_tokens[j1:j2])

    # 3) 空 cue 回退：按比例从原文剩余再填，或保留旧文
    used = sum(len(parts) for parts in cue_tokens)
    if used < len(src_tokens) * 0.5:
        # 对齐失败过多 → 按 ASR 词数权重比例切
        weights = [max(1, len(tokens_for(t))) for t in old_texts]
        total_w = sum(weights) or len(weights)
        pos = 0
        out = []
        for i, w in enumerate(weights):
            if i == len(weights) - 1:
                piece = src_tokens[pos:]
            else:
                take = max(1, round(len(src_tokens) * w / total_w))
                remaining_cues = len(weights) - i - 1
                take = min(take, max(0, len(src_tokens) - pos - remaining_cues))
                take = max(0, take)
                piece = src_tokens[pos:pos + take]
                pos += take
            out.append(sep.join(piece) if piece else old_texts[i])
        return out

    result = []
    for i, parts in enumerate(cue_tokens):
        if parts:
            result.append(sep.join(parts))
        else:
            result.append(old_texts[i])
    return result


def proofread_srt_keep_timestamps(srt, source_text, language=None):
    """Replace cue texts with aligned source script; keep all timestamps.

    Returns (new_srt, changes) where changes is
    [{"index", "start", "end", "old", "new"}, ...].
    """
    events = parse_srt(srt, language=language)
    if not events or not str(source_text or "").strip():
        return srt, []
    cleaned = normalize_subtitle_text(str(source_text).strip(), language=language) if language else str(source_text).strip()
    cleaned = normalize_required_capitalization(cleaned)
    new_texts = align_source_text_to_srt_cues(events, cleaned)
    changes = []
    blocks = []
    for index, ((start, end, old_text), new_text) in enumerate(zip(events, new_texts), 1):
        new_text = normalize_subtitle_text(str(new_text or "").strip(), language=language) if language else str(new_text or "").strip()
        if not new_text:
            new_text = old_text
        if (old_text or "").strip() != (new_text or "").strip():
            changes.append({
                "index": index,
                "start": start,
                "end": end,
                "old": old_text,
                "new": new_text,
            })
        blocks.append(f"{index}\n{_srt_stamp(start)} --> {_srt_stamp(end)}\n{new_text}")
    return "\n\n".join(blocks) + "\n", changes


def html_word_diff(old_text, new_text):
    """HTML snippet: equal plain, changed/new words in red, deleted struck."""
    from difflib import SequenceMatcher
    import html as html_lib

    old_t = tokens_for(old_text or "")
    new_t = tokens_for(new_text or "")
    is_cjk = _is_cjk_heavy((old_text or "") + (new_text or ""))
    sep = "" if is_cjk else " "
    if not old_t and not new_t:
        return ""
    if old_t == new_t:
        return html_lib.escape(sep.join(new_t))
    sm = SequenceMatcher(a=old_t, b=new_t, autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            chunk = sep.join(new_t[j1:j2])
            if chunk:
                parts.append(html_lib.escape(chunk))
        elif tag == "delete":
            chunk = sep.join(old_t[i1:i2])
            if chunk:
                parts.append(
                    f'<span style="color:#f87171;text-decoration:line-through;opacity:.85;">'
                    f"{html_lib.escape(chunk)}</span>"
                )
        elif tag in ("insert", "replace"):
            chunk = sep.join(new_t[j1:j2])
            if chunk:
                parts.append(
                    f'<span style="color:#f87171;font-weight:700;background:rgba(248,113,113,.12);">'
                    f"{html_lib.escape(chunk)}</span>"
                )
            if tag == "replace":
                deleted = sep.join(old_t[i1:i2])
                if deleted and not chunk:
                    parts.append(
                        f'<span style="color:#f87171;text-decoration:line-through;">'
                        f"{html_lib.escape(deleted)}</span>"
                    )
    joiner = "" if is_cjk else " "
    return joiner.join(parts)


def replace_srt_copy(srt, copy_text):
    """Backward-compatible: proofread and return only the SRT string."""
    new_srt, _changes = proofread_srt_keep_timestamps(srt, copy_text)
    return new_srt


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


def watermark_filter_graph(ass_filter, settings, watermark_input_index, v_filter_str=None):
    ass_expression=ass_filter_expression(ass_filter,settings)
    opacity = max(5, min(100, int(settings.get("watermark_opacity", 90)))) / 100
    mode = settings.get("watermark_mode", "9:16 ȫ")
    video_prefix = f"[0:v]{v_filter_str + ',' if v_filter_str else ''}{ass_expression}[captioned];"
    if mode == "9:16 ȫ" and settings.get("watermark_prepared"):
        return (video_prefix +
                f"[{watermark_input_index}:v]format=rgba[wm];"
                "[captioned][wm]overlay=0:0:eof_action=repeat[outv]")
    prefix = (
        video_prefix +
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
    for source,target in (("'",r"\'"),(":",r"\:"),(",",r"\,"),(";",r"\;"),
                          ("[",r"\["),("]",r"\]"),("(",r"\("),(")",r"\)"),(" ",r"\ ")):
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
    lang = (settings.get("caption_language") or settings.get("writing_language")
            or settings.get("language") or None)
    sample_text = " ".join(text for _, _, text in parse_srt(srt, language=lang)[:8])
    render_settings = dict(settings)
    render_settings["caption_language"] = lang
    render_settings["language"] = lang
    spacing = effective_letter_spacing(render_settings, sample_text)
    render_settings["letter_spacing"] = spacing
    if is_rtl_text(sample_text, lang):
        # 阿拉伯语等连写文：强制 0 字距，并建议可用字体（有则替换）
        hinted = suggest_font_for_text(str(render_settings.get("font", "Arial")), sample_text, lang)
        if hinted:
            render_settings["font"] = hinted
    metric_font = caption_layout_context(render_settings)[0]
    font = str(render_settings.get("font", "Arial")).replace(",", "")
    alignment = {"底部": 2, "画面中间": 5, "顶部": 8}.get(settings.get("position", "底部"), 2)
    is_static_bold = any(key in font for key in STATIC_BOLD_FONT_FILES)
    bold_flag=-1 if (caption_uses_bold_face(render_settings) or is_static_bold) else 0
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{font},{render_settings['font_size']},{text_color},{text_color},{outline_color},&H90000000,{bold_flag},0,0,0,100,100,{spacing},0,1,{render_settings['outline_width']},2,{alignment},40,40,{render_settings['margin_v']},1
Style: DoubleOuter,{font},{render_settings['font_size']},{highlight},{highlight},{highlight},&H90000000,{bold_flag},0,0,0,100,100,{spacing},0,1,{render_settings['outline_width'] + 3},2,{alignment},40,40,{render_settings['margin_v']},1
Style: Active,{font},{render_settings['font_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{bold_flag},0,0,0,100,100,{spacing},0,1,0,0,{alignment},40,40,{render_settings['margin_v']},1
Style: ActiveColor,{font},{render_settings['font_size']},{highlight},{highlight},{outline_color},&H90000000,{bold_flag},0,0,0,100,100,{spacing},0,1,{render_settings['outline_width']},2,{alignment},40,40,{render_settings['margin_v']},1
Style: HighlightBox,{font},{render_settings['font_size']},{highlight},{highlight},{highlight},{highlight},{bold_flag},0,0,0,100,100,{spacing},0,1,0,0,7,0,0,0,1

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
    font_size = render_settings["font_size"]
    layout_context=caption_layout_context(render_settings)
    _metric_font,metrics,word_gap,line_gap,max_line_width=layout_context
    padding_x = int(render_settings.get("highlight_padding", max(12, font_size * .2)))
    padding_y = max(0, int(render_settings.get("highlight_padding_y", max(7, font_size * .11))))
    animation_ms = int(render_settings.get("animation_speed", 150))
    position = render_settings.get("position", "底部")
    free_mode = render_settings.get("caption_mode") == "自由文案动画（不对口型）"
    free_animation = render_settings.get("free_animation", "淡入淡出")
    effect_name = preset.get("effect", "word_color")
    phrase_entries = list(parse_srt(srt, language=lang))
    # 语义堆叠：句与句时间窗必须互斥。绝不能用 max(start+min, end) 把结束时间
    # 硬拉长越过下一句起点——那正是「只有这个效果叠字」的根因。
    if effect_name in ("semantic_stack", "word_scale"):
        # 句与句硬切空隙略大，上一句读完立刻让位，避免停留叠到下一句
        phrase_entries = _semantic_non_overlapping_phrases(phrase_entries, gap=0.10)

    for phrase_index, (start, end, text) in enumerate(phrase_entries):
        safe = text.replace("{", "（").replace("}", "）")
        allow_rtl_words = bool(render_settings.get("rtl_word_highlight", False))
        # RTL 默认整句 + 方向标记；勾选「RTL 逐词高亮」时走下方逐词路径并对每个词包 RLE
        if should_disable_word_highlight(safe, lang, allow_rtl_word_highlight=allow_rtl_words):
            display = prepare_ass_dialogue_text(safe, lang).replace("\n", r"\N")
            an = {"底部": 2, "画面中间": 5, "顶部": 8}.get(position, 2)
            override = fr"{{\an{an}\fad(70,70)}}"
            if preset["effect"] == "double_outline":
                events.append(
                    f"Dialogue: {caption_layer},{ass_time(start)},{ass_time(end)},"
                    f"DoubleOuter,,0,0,0,,{override}{display}")
                events.append(
                    f"Dialogue: {caption_layer + 1},{ass_time(start)},{ass_time(end)},"
                    f"Base,,0,0,0,,{override}{display}")
            else:
                events.append(
                    f"Dialogue: {caption_layer},{ass_time(start)},{ass_time(end)},"
                    f"Base,,0,0,0,,{override}{display}")
            continue
        tokens = tokens_for(safe)
        if not tokens: continue
        effect = preset["effect"]
        rtl_token_mode = is_rtl_text(safe, lang) and allow_rtl_words
        fixed_all = free_mode and free_animation == "整段固定"

        # Use the word midpoint to assign it to exactly one phrase.  Overlap
        # tolerances made boundary words appear in two adjacent phrases and
        # could produce two highlighted words at the same time.
        phrase_words=[item for item in precise_words
                      if start-.01 <= (item[0]+item[1])/2 <= end+.01]
        if len(phrase_words) >= len(tokens):
            timings=[(phrase_words[i][0],phrase_words[i][1]) for i in range(len(tokens))]
        else:
            duration=max(.08,(end-start)/len(tokens)); timings=[(start+duration*i,min(end,start+duration*(i+1))) for i in range(len(tokens))]

        # —— 语义重点：底层先整句语义排版定稿（位置固定，相当于透明底稿），
        # 上层按词级语速逐词弹出；本句 end 硬切，杜绝停留叠到下一句 ——
        if effect in ("semantic_stack", "word_scale"):
            geo_settings = dict(render_settings)
            geo_settings["position"] = "画面中间"
            for key in ("semantic_large_ratio", "semantic_small_ratio", "semantic_lead_ms",
                        "semantic_max_lines", "semantic_small_words"):
                if key not in geo_settings and key in preset:
                    geo_settings[key] = preset[key]
            # 词时间夹进本句，并保证单调递增，避免抢先/乱序
            clamped = []
            prev_s = start
            span = max(0.08, end - start)
            for i, (w_start, w_end) in enumerate(timings):
                cs = max(start, min(float(w_start), end - 0.04))
                cs = max(cs, prev_s)
                # 均匀兜底：若时间挤在一起，按序号拉开一点，仍不超出本句
                ideal = start + span * i / max(1, len(timings))
                if cs > ideal + 0.35:
                    cs = max(prev_s, ideal)
                ce = max(cs + 0.04, min(float(w_end), end))
                clamped.append((cs, ce))
                prev_s = cs + 0.02
            timings = clamped

            # ① 整句语义定稿：大小号 + 行位一次算死（未读词不显示，但占位已定）
            emphasized = select_emphasis_words(tokens)
            stack_lines = semantic_stack_layout(tokens, emphasized, geo_settings)
            max_stack_lines = max(3, min(6, int(geo_settings.get("semantic_max_lines", 5))))
            stack_pages = (
                [stack_lines]
                if fixed_all or len(stack_lines) <= max_stack_lines
                else [stack_lines[i:i + max_stack_lines] for i in range(0, len(stack_lines), max_stack_lines)]
            )
            lead_ms = geo_settings.get("semantic_lead_ms", 0)
            try:
                lead_ms = float(lead_ms)
            except (TypeError, ValueError):
                lead_ms = 0.0
            lead = max(0.0, min(0.08, lead_ms / 1000.0))
            pop_ms = max(40, min(110, int(animation_ms)))
            fad_in = max(15, min(45, pop_ms // 2))
            token_index = 0
            for page_lines in stack_pages:
                page_token_count = sum(len(line) for line in page_lines)
                if page_token_count <= 0:
                    continue
                page_first = token_index
                next_index = token_index + page_token_count
                # 本页硬结束于：下一页首词 / 本句 end（不向后拉）
                if next_index < len(timings):
                    page_end = min(end, timings[next_index][0])
                else:
                    page_end = end
                page_end = min(page_end, end)
                if page_end <= timings[page_first][0] + 0.02:
                    page_end = min(end, timings[page_first][0] + 0.05)
                if page_end <= start:
                    token_index += page_token_count
                    continue
                # 整页几何按「全句已排好」的最终位置
                geometry = semantic_stack_geometry(page_lines, geo_settings)
                local_i = 0
                for line, line_geo in zip(page_lines, geometry):
                    for item, geo in zip(line, line_geo):
                        ti = page_first + local_i
                        token_start, _token_end = timings[ti] if ti < len(timings) else (start, end)
                        # ② 上层逐词弹出：严格跟语速，默认不提前
                        visible_start = max(start, token_start - lead)
                        visible_start = min(visible_start, page_end - 0.03)
                        # ③ 本页/本句结束立刻消失（硬切，无淡出尾巴）
                        visible_end = page_end
                        local_i += 1
                        if visible_start >= visible_end - 0.015:
                            continue
                        draw = prepare_ass_dialogue_text(item["token"], lang) if rtl_token_mode else item["token"]
                        size = int(item.get("size") or font_size)
                        x, y = geo["x"], geo["y"]
                        # 透明底稿不渲染；只在朗读时刻弹出到最终位置
                        override = (
                            fr"{{\an5\pos({x:.1f},{y:.1f})\fs{size}"
                            fr"\fscx90\fscy90"
                            fr"\t(0,{pop_ms},\fscx108\fscy108)"
                            fr"\t({pop_ms},{pop_ms + 45},\fscx100\fscy100)"
                            fr"\fad({fad_in},0)}}"
                        )
                        events.append(
                            f"Dialogue: {caption_layer},{ass_time(visible_start)},{ass_time(visible_end)},"
                            f"Base,,0,0,0,,{override}{draw}"
                        )
                token_index += page_token_count
            continue

        # 整段固定保留手动换行，且允许任意行数；其他模式继续自动排版分页。
        lines=caption_wrapped_lines(safe,render_settings,fixed_all,layout_context)

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
            geometry=caption_page_geometry(page_lines,render_settings,layout_context)
            for line_index,(line_tokens,line_geometry) in enumerate(zip(page_lines,geometry)):
                for local_index,(token,item) in enumerate(zip(line_tokens,line_geometry)):
                    width=item["width"]; x=item["x"]; y=item["y"]
                    token_start,token_end=timings[token_index]; token_index+=1
                    # RTL 实验性逐词：每个词单独包方向标记
                    draw = prepare_ass_dialogue_text(token, lang) if rtl_token_mode else token
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
                        if effect == "double_outline":
                            events.append(
                                f"Dialogue: {caption_layer},{ass_time(visible_start)},{ass_time(page_end)},"
                                f"DoubleOuter,,0,0,0,,{override}{draw}")
                            events.append(
                                f"Dialogue: {caption_layer + 1},{ass_time(visible_start)},{ass_time(page_end)},"
                                f"Base,,0,0,0,,{override}{draw}")
                        else:
                            events.append(
                                f"Dialogue: {caption_layer},{ass_time(visible_start)},{ass_time(page_end)},"
                                f"Base,,0,0,0,,{override}{draw}")
                        continue
                    intro=fr"{{\an5\pos({x:.1f},{y:.1f})\fad(70,70)}}"
                    if effect == "glow": intro=fr"{{\an5\pos({x:.1f},{y:.1f})\blur3\fad(70,70)}}"
                    if effect == "double_outline":
                        events.append(f"Dialogue: {caption_layer},{ass_time(page_start)},{ass_time(page_end)},DoubleOuter,,0,0,0,,{intro}{draw}")
                        events.append(f"Dialogue: {caption_layer + 1},{ass_time(page_start)},{ass_time(page_end)},Base,,0,0,0,,{intro}{draw}")
                        continue
                    events.append(f"Dialogue: {caption_layer},{ass_time(page_start)},{ass_time(page_end)},Base,,0,0,0,,{intro}{draw}")
                    if effect in ("outline","glow","double_outline"): continue

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
                    events.append(f"Dialogue: {caption_layer + 2},{ass_time(token_start)},{ass_time(token_end)},{active_style},,0,0,0,,{active_override}{draw}")
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
        # 主音频（添加的音频列表）是和“文案转音频”、“音频和视频合并”使用的，绝对不能随机分配。
        # 无论在界面上选择了何种匹配方式，主音频始终严格按“同名优先，其次队列一一对应”逻辑进行绑定。
        mode = self.settings.get("audio_match_mode", "自动匹配（同名优先，其次按队列）")
        if not self.audios or mode == "每个视频使用自身音频":
            return video, "视频自身音频"

        # 优先同名匹配
        video_key = self._match_stem(video)
        same = next((audio for audio in self.audios if self._match_stem(audio) == video_key), None)
        if same is not None:
            return same, "同名自动匹配"

        # 其次按队列顺序一一对应
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
            # 每个子任务只含 1 个视频时 index 恒为 0；把队列绝对序号写入 settings，
            # 保证批量重命名序号 / 自定义标题按整批队列顺序递增。
            child_settings = dict(self.settings)
            child_settings["rename_batch_index"] = index
            child=CaptionWorker([video],child_audios,self.output,self.ffmpeg,self.transcribe,child_settings)
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
            requested = self.settings.get("encoder_backend", "auto")
            encoder = resolve_encoder(self.ffmpeg, requested)
            if encoder == "cpu":
                self.log.emit(
                    "视频编码：CPU 兼容模式（较慢，易占满 CPU 导致预览卡顿）。"
                    "请把编码加速改为「自动硬件加速」或「Windows 硬件编码 (MF)」。"
                )
                # 只探测一次、且跳过极慢的 QSV 冷启动，避免每次批处理卡 30s+
                if not getattr(self, "_encoder_diag_done", False):
                    self._encoder_diag_done = True
                    try:
                        for key in ("nvenc", "mf", "amf"):
                            ok, reason = encoder_probe_detail(self.ffmpeg, key)
                            label = ENCODER_LABELS.get(key, key)
                            self.log.emit(
                                f"  · {label}：{'可用' if ok else '不可用'}"
                                + (f" — {reason}" if (not ok and reason) else "")
                            )
                    except Exception as exc:
                        self.log.emit(f"  · 硬编探测异常：{exc}")
                    self.log.emit(
                        "提示：GTX 1070 若 NVENC 失败，多半是驱动过旧；"
                        "可不升驱动，直接选手动「Windows 硬件编码 (MF)」。"
                    )
            elif encoder == "nvenc":
                self.log.emit("视频编码：NVIDIA NVENC（显卡硬编，占用 CPU 低、速度快）")
            elif encoder == "mf":
                self.log.emit(
                    "视频编码：Windows 硬件编码 Media Foundation（不依赖 NVENC API，"
                    "可显著降低 CPU 占用）"
                )
            elif encoder == "qsv":
                self.log.emit("视频编码：Intel Quick Sync（核显硬编）")
            elif encoder == "amf":
                self.log.emit("视频编码：AMD AMF（显卡硬编）")
            else:
                self.log.emit(f"视频编码：{ENCODER_LABELS.get(encoder, encoder)}")
            from .video_encoding import encoder_key as _encoder_key
            want = _encoder_key(requested)
            if want not in ("auto", "cpu") and want != encoder:
                _ok, why = encoder_probe_detail(self.ffmpeg, want)
                self.log.emit(
                    f"提醒：已选「{ENCODER_LABELS.get(want, want)}」但不可用，"
                    f"已回退到 {ENCODER_LABELS.get(encoder, encoder)}。"
                    + (f" 原因：{why}" if why else "")
                )
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
                edit_state=dict(self.settings.get("timeline_edits",{}).get(str(video.resolve()),{}) or {})
                edit_tracks=edit_state.get("tracks",{}) or {}
                # The explicit "sound synthesis" choice is the export source of
                # truth.  A group-output timeline used to default to mute and
                # could silently override "video original + BGM".
                requested_audio_mode = str(self.settings.get("audio_mode", "保留视频原音"))
                replacement_requested = (
                    "清除视频原音" in requested_audio_mode
                    or "消除视频原音" in requested_audio_mode
                    or "清除视频噪音" in requested_audio_mode
                    or "替换" in requested_audio_mode
                )
                has_replacement_audio = audio.resolve() != video.resolve()
                edit_state["original_audio_enabled"] = not (
                    replacement_requested and has_replacement_audio
                )
                tts_track_state=(edit_tracks.get("tts") or [{}])[0]
                bgm_track_state=(edit_tracks.get("bgm") or [{}])[0]
                tts_delay_ms=max(0,int(tts_track_state.get("start",0) or 0))
                bgm_delay_ms=max(0,int(bgm_track_state.get("start",0) or 0))
                if edit_state.get("tracks"):
                    render_video=render_timeline_edits(self.ffmpeg,video,edit_state,self.output)
                    self.log.emit(
                        f"[{index + 1}/{len(self.videos)}] 已应用时间轴切片/删除："
                        f"{len(edit_state.get('tracks',{}).get('video',[]))} 个视频片段；"
                        f"原声{'保留' if edit_state.get('original_audio_enabled',True) else '静音'}。")
                # 动态追踪模糊：在字幕烧录前处理画面（不影响字幕/音轨时间）
                motion_tracks = [
                    t for t in (self.settings.get("motion_tracks") or [])
                    if isinstance(t, dict) and t.get("mode") == "blur" and t.get("points")
                ]
                if motion_tracks and Path(render_video).suffix.lower() not in IMAGE_EXTENSIONS:
                    try:
                        from .motion_track import apply_tracks_to_video
                        self.log.emit(
                            f"[{index + 1}/{len(self.videos)}] 正在应用动态追踪模糊（{len(motion_tracks)} 条路径）…"
                        )
                        render_video = apply_tracks_to_video(
                            self.ffmpeg, render_video, motion_tracks, self.output,
                        )
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 追踪模糊已写入画面缓存。")
                    except Exception as track_exc:
                        self.log.emit(
                            f"[{index + 1}/{len(self.videos)}] 追踪模糊跳过：{track_exc}"
                        )
                source_key = str(caption_audio.resolve())
                speech_media=(render_video if caption_audio.resolve()==video.resolve() else caption_audio)
                
                # Check for manual slice bounds [start-end] in overrides or free texts
                manual_bounds = None
                override = str(self.settings.get("timeline_overrides", {}).get(source_key, "")).strip()
                free_text = str(self.settings.get("free_texts", {}).get(str(video.resolve()), "")).strip()
                text_to_check = override or free_text
                if text_to_check:
                    match = re.search(r'\[\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*\]', text_to_check)
                    if match:
                        manual_bounds = (float(match.group(1)), float(match.group(2)))

                if self.settings.get("caption_mode") == "自由文案动画（不对口型）":
                    video_key = str(video.resolve())
                    copy_text = str(self.settings.get("free_texts", {}).get(video_key, "")).strip()
                    if manual_bounds is not None:
                        copy_text = re.sub(r'\[\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*\]', '', copy_text).strip()
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
                    elif render_video==video and _load_timeline_cache(self.output,caption_audio):
                        srt=_load_timeline_cache(self.output,caption_audio)
                        original=" ".join(text for _,_,text in parse_srt(srt))
                        chinese = str(self.settings.get("timeline_chinese", {}).get(source_key, "")).strip()
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 断点续接：复用已提取字幕 {caption_audio.name}")
                    else:
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 从对白音轨提取词级时间轴：{speech_media.name}")
                        original, chinese, srt = self.transcribe(str(speech_media))
                        if str(srt or "").strip() and render_video==video:
                            _save_timeline_cache(self.output,caption_audio,srt)
                    if not srt.strip(): raise RuntimeError(f"未识别到有效字幕：{caption_audio.name}")
                    word_srt = srt
                    phrase_srt = group_word_srt(word_srt, self.settings["line_length"] * 2,
                                                max_words=self.settings.get("max_words", 8))
                    override = str(self.settings.get("timeline_overrides", {}).get(str(caption_audio.resolve()), "")).strip()
                    if manual_bounds is not None:
                        override = re.sub(r'\[\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*\]', '', override).strip()
                    if override:
                        if "-->" in override:
                            phrase_srt = override
                            self.log.emit("已应用人工修订后的逐句 SRT，逐词时间轴继续驱动高亮。")
                        else:
                            phrase_srt = replace_srt_copy(phrase_srt, override)
                            self.log.emit("已应用人工修订文案，并保留词级时间轴。")
                if manual_bounds is not None:
                    v_start = manual_bounds[0]
                    if v_start > 0.0:
                        phrase_srt = shift_srt_timestamps(phrase_srt, v_start)
                        word_srt = shift_srt_timestamps(word_srt, v_start)
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 正在将字幕时间轴向前平移 {v_start:.2f} 秒以适配切片视频。")
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
                    # 父 run() 为每个视频 spawn 单片 child 时 index 恒为 0；
                    # 优先使用整批队列绝对序号，保证 001/002/003… 正确递增。
                    batch_index = self.settings.get("rename_batch_index")
                    if batch_index is None:
                        batch_index = index
                    else:
                        try:
                            batch_index = int(batch_index)
                        except (TypeError, ValueError):
                            batch_index = index

                    prefix_part = clean_filename_part(rename_prefix, fallback="") if rename_prefix else ""
                    suffix_part = clean_filename_part(rename_suffix, fallback="") if rename_suffix else ""
                    date_part = clean_filename_part(rename_date, fallback="") if rename_date else ""

                    # 自定义标题列表：按队列顺序每行一个；有内容时覆盖自动提取标题。
                    # 空行占位保留位置（第 N 行对应第 N 个视频）；不限制标题字符数
                    # （仅在 safe_filename 时按整名最大长度截断）。
                    custom_titles = self.settings.get("rename_titles") or []
                    if isinstance(custom_titles, str):
                        custom_titles = [line.strip() for line in custom_titles.splitlines()]
                    else:
                        custom_titles = [str(x).strip() for x in list(custom_titles)]

                    title_text = ""
                    if 0 <= batch_index < len(custom_titles) and custom_titles[batch_index]:
                        title_text = custom_titles[batch_index]
                        self.log.emit(
                            f"[{index + 1}/{len(self.videos)}] 使用自定义标题列表第 {batch_index + 1} 行命名。"
                        )
                    if not title_text:
                        title_text = chinese or ""
                        if not title_text or title_text.strip().startswith("【"):
                            short_orig = original[:200] if original else ""
                            translated = translate_to_chinese_free(short_orig)
                            if translated:
                                title_text = translated
                            else:
                                title_text = original or video.stem
                    title_part = clean_filename_part(title_text, fallback="", max_chars=None)

                    seq_str = str(rename_start_index + batch_index).zfill(rename_padding)

                    parts = [seq_str]
                    for part in (prefix_part, title_part, date_part):
                        if part:
                            parts.append(part)
                    base = "-".join(parts)
                    if suffix_part:
                        base += suffix_part if suffix_part.startswith("-") else "-" + suffix_part

                    safe_name, _truncated = safe_filename(base + video.suffix, self.output)
                    destination = self.output / safe_name
                    self.log.emit(
                        f"[{index + 1}/{len(self.videos)}] 成品重命名：{safe_name}（序号 {seq_str}）"
                    )
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
                if any(t.get("mode") == "blur" and t.get("points") for t in (self.settings.get("motion_tracks") or []) if isinstance(t, dict)):
                    stages.append("追踪模糊")
                stage_text="、".join(["字幕",*stages])
                if watermark_already_baked:
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 当前水印已在分组合成阶段烧录，本次跳过重复水印。")
                self.log.emit(f"[{index + 1}/{len(self.videos)}] 正在烧录{stage_text}并编码视频，请等待…")
                self.progress.emit(round((index + .55) / max(1,len(self.videos)) * 100))
                ass_filter = ass
                is_image = render_video.suffix.lower() in IMAGE_EXTENSIONS
                external = audio.resolve() != video.resolve()
                if edit_state and "tts" in edit_tracks and not edit_tracks.get("tts"):
                    external = False
                audio_mode = self.settings.get("audio_mode", "保留视频原音")
                if "清除视频原音" in audio_mode or "消除视频原音" in audio_mode or "清除视频噪音" in audio_mode or "替换" in audio_mode:
                    audio_mode = "替换为添加 of 音频"  # Map internally to key string
                    audio_mode = "替换为添加的音频"
                elif "混合" in audio_mode or "原声＋背景" in audio_mode:
                    audio_mode = "原声＋背景音混合"
                else:
                    audio_mode = "保留视频原音"
                
                mix_audio = external and audio_mode == "原声＋背景音混合"
                replace_audio = external and audio_mode == "替换为添加的音频"
                source_has_audio = False if is_image else media_has_audio(self.ffmpeg, render_video)
                if audio_mode == "替换为添加的音频" and not external:
                    self.log.emit(
                        f"[{index + 1}/{len(self.videos)}] 未匹配到文字转语音或配音文件，"
                        "本条任务临时保留视频原声，并继续按设置添加背景音乐。"
                    )
                if audio_mode == "原声＋背景音混合" and not external:
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 未匹配到独立背景音，已保留视频原声继续处理。")
                
                # Target dimensions scaling
                src_w, src_h = media_video_size(self.ffmpeg, render_video)
                aspect_ratio = self.settings.get("aspect_ratio", "原始比例")
                resolution = self.settings.get("resolution", "默认最高")
                target_w, target_h = calculate_target_size(src_w, src_h, aspect_ratio, resolution)
                need_resize = (aspect_ratio != "原始比例" or resolution != "默认最高")
                
                audio_duration = 0.0
                if external and audio.is_file():
                    audio_duration = media_duration(self.ffmpeg, audio)
                    if manual_bounds is not None:
                        audio_duration = max(0.05, audio_duration - manual_bounds[0])
                
                if is_image:
                    video_duration = audio_duration if audio_duration > 0.0 else 5.0
                else:
                    video_duration = media_duration(self.ffmpeg, render_video)
                    if manual_bounds is not None:
                        v_start, v_end = manual_bounds
                        v_start = max(0.0, min(video_duration, v_start))
                        v_end = max(v_start + 0.05, min(video_duration, v_end))
                        video_duration = v_end - v_start
                
                # Check video extension
                extend_mode = self.settings.get("video_extend_mode", "不处理")
                loop_video = False
                extend_filters = []
                
                if not is_image and audio_duration > video_duration:
                    if extend_mode == "不处理":
                        extend_mode = "循环播放视频"
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 提示：视频时长（{video_duration:.2f}秒）较短，已自动启用“循环播放视频”以匹配配音时长（{audio_duration:.2f}秒）。")
                    
                    diff = audio_duration - video_duration
                    if extend_mode == "循环播放视频":
                        loop_video = True
                    elif extend_mode == "最后一帧延长/冻结":
                        extend_filters.append(f"tpad=stop_duration={diff:.3f}:stop_mode=clone")
                    elif extend_mode == "速度拉伸（减速延长）":
                        speed_ratio = video_duration / audio_duration
                        extend_filters.append(f"setpts=PTS/{speed_ratio:.4f}")
                    video_duration = audio_duration
                    
                v_filters = []
                if need_resize:
                    v_filters.append(f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}:(iw-ow)/2:(ih-oh)/2,setsar=1")
                v_filters.append("fps=30")
                if extend_filters:
                    v_filters.extend(extend_filters)
                v_filter_str = ",".join(v_filters) if v_filters else ""
                
                command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
                if is_image:
                    command += ["-loop", "1", "-t", f"{video_duration:.3f}"]
                elif loop_video:
                    command += ["-stream_loop", "-1"]
                if not is_image and manual_bounds is not None:
                    v_start, v_end = manual_bounds
                    v_orig_dur = media_duration(self.ffmpeg, render_video)
                    v_start = max(0.0, min(v_orig_dur, v_start))
                    v_end = max(v_start + 0.05, min(v_orig_dur, v_end))
                    command += ["-ss", f"{v_start:.3f}", "-t", f"{v_end - v_start:.3f}"]
                command += ["-i", str(render_video)]
                
                if external and match_reason == "随机匹配背景音":
                    import random, hashlib
                    audio_dur = media_duration(self.ffmpeg, audio)
                    if audio_dur > video_duration:
                        max_start = audio_dur - video_duration
                        # 使用基于视频绝对路径和索引的 MD5 哈希种子，保证重启后分配结果一致且分布均匀
                        h = hashlib.md5(f"{video.resolve()}_{index}_crop".encode("utf-8")).hexdigest()
                        rnd = random.Random(int(h, 16))
                        random_start = rnd.uniform(0.0, max_start)
                        audio_offset_ms = int(random_start * 1000)
                    else:
                        if audio_dur > 1.0:
                            h = hashlib.md5(f"{video.resolve()}_{index}_crop".encode("utf-8")).hexdigest()
                            rnd = random.Random(int(h, 16))
                            random_start = rnd.uniform(0.0, min(5.0, audio_dur - 0.5))
                            audio_offset_ms = int(random_start * 1000)
                        else:
                            audio_offset_ms = 0
                    self.log.emit(f"[{index + 1}/{len(self.videos)}] 随机匹配背景音：选用 {audio.name}，随机起始裁剪点为 {audio_offset_ms / 1000:.2f} 秒。")
                else:
                    audio_offset_ms = (int(self.settings.get("audio_offsets", {}).get(str(audio.resolve()), 0))
                                       if external else 0)
                if external and tts_track_state:
                    audio_offset_ms=max(0,int(tts_track_state.get("source_start",audio_offset_ms) or 0))
                if external and edit_tracks.get("tts"):
                    edited_audio=render_timeline_audio(
                        self.ffmpeg,audio,edit_tracks.get("tts"),self.output,"tts")
                    if edited_audio:
                        audio=edited_audio
                        audio_offset_ms=0
                        tts_delay_ms=0
                if external:
                    if mix_audio and not edit_tracks.get("tts"): command += ["-stream_loop", "-1"]
                    if manual_bounds is not None:
                        a_start, a_end = manual_bounds
                        a_dur = max(0.05, a_end - a_start)
                        command += ["-ss", f"{a_start:.3f}", "-t", f"{a_dur:.3f}"]
                    elif audio_offset_ms > 0:
                        command += ["-ss", f"{audio_offset_ms / 1000:.3f}"]
                    command += ["-i", str(audio)]

                randomize_bgm = str(
                    self.settings.get("bgm_selection_mode","")
                ).startswith("随机")
                selected_bgm=Path(str(self.settings.get("selected_bgm_path","")))
                bgm_file=(
                    (selected_bgm if selected_bgm.is_file() else
                     find_bgm_file(self.settings.get("bgm_dir"),index,video,
                                   randomize=randomize_bgm))
                    if self.settings.get("bgm_enabled",False) else None
                )
                bgm_offset_ms = 0
                if bgm_file:
                    bgm_input_index = 2 if external else 1
                    if not edit_tracks.get("bgm"):
                        command += ["-stream_loop", "-1"]
                    if randomize_bgm:
                        import random, hashlib
                        bgm_dur = media_duration(self.ffmpeg, bgm_file)
                        if bgm_dur > 2.0:
                            h = hashlib.md5(f"{video.resolve()}_{index}_bgm_crop".encode("utf-8")).hexdigest()
                            rnd = random.Random(int(h, 16))
                            bgm_offset_ms = int(rnd.uniform(0.0, bgm_dur - 1.0) * 1000)
                    if bgm_track_state:
                        bgm_offset_ms=max(0,int(bgm_track_state.get("source_start",bgm_offset_ms) or 0))
                    if edit_tracks.get("bgm"):
                        edited_bgm=render_timeline_audio(
                            self.ffmpeg,bgm_file,edit_tracks.get("bgm"),self.output,"bgm")
                        if edited_bgm:
                            bgm_file=edited_bgm
                            bgm_offset_ms=0
                            bgm_delay_ms=0
                    if bgm_offset_ms > 0:
                        command += ["-ss", f"{bgm_offset_ms / 1000:.3f}"]
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 背景音乐随机分配并随机截取：选用 {bgm_file.name}，随机起始裁剪点为 {bgm_offset_ms / 1000:.2f} 秒。")
                    command += ["-i", str(bgm_file)]
                else:
                    bgm_input_index = None
                    if self.settings.get("bgm_enabled",False):
                        self.log.emit(
                            f"[{index + 1}/{len(self.videos)}] 未在所选路径中找到可用的背景音乐文件；"
                            "请检查文件/文件夹路径和音频格式。当前视频将按声音合成方式保留原声。"
                        )
                watermark_entries=[] if watermark_already_baked else (self.settings.get("watermarks") or [])
                watermark_paths=[] if watermark_already_baked else (self.settings.get("watermark_paths") or [self.settings.get("watermark_path","")])
                watermark = (prepared_watermark_composite(self.ffmpeg,render_video,watermark_entries,self.output)
                             if watermark_entries else prepared_watermark_stack(watermark_paths,self.output))
                watermark_enabled = watermark.is_file()
                render_settings=self.settings
                if watermark_enabled and watermark_entries:
                    render_settings=dict(self.settings); render_settings.update({"watermark_prepared":True,"watermark_mode":"9:16 全屏覆盖"})
                elif watermark_enabled and self.settings.get("watermark_mode","9:16 全屏覆盖")=="9:16 全屏覆盖":
                    watermark=prepared_fullframe_watermark(
                        self.ffmpeg,render_video,watermark,self.output,self.settings.get("watermark_opacity",90))
                    render_settings=dict(self.settings); render_settings["watermark_prepared"]=True
                watermark_input = 1
                if external: watermark_input += 1
                if bgm_file: watermark_input += 1
                
                # Output limits
                if loop_video:
                    command += ["-t", f"{video_duration:.3f}"]
                    
                if bgm_file:
                    dialogue_input = "[1:a:0]" if replace_audio else "[0:a:0]"
                    bgm_input = f"[{bgm_input_index}:a:0]"
                    dialogue_has_audio = (
                        media_has_audio(self.ffmpeg, audio)
                        if replace_audio else source_has_audio
                    )
                    if dialogue_has_audio:
                        audio_graph = bgm_mix_audio_filter(
                            dialogue_input, bgm_input,
                            self.settings.get("original_volume", 100),
                            self.settings.get("background_volume", 25),
                            self.settings.get("audio_fade_mode"),
                            self.settings.get("audio_fade_in_ms", 500),
                            self.settings.get("audio_fade_out_ms", 500),
                            video_duration,
                            tts_delay_ms if replace_audio else 0,
                            bgm_delay_ms,
                        )
                    else:
                        audio_graph = bgm_only_audio_filter(
                            bgm_input,
                            self.settings.get("background_volume", 25),
                            self.settings.get("audio_fade_mode"),
                            self.settings.get("audio_fade_in_ms", 500),
                            self.settings.get("audio_fade_out_ms", 500),
                            video_duration,
                            bgm_delay_ms,
                        )
                        self.log.emit(
                            f"[{index + 1}/{len(self.videos)}] 视频没有可用原声音轨，"
                            f"成品将使用背景音乐：{bgm_file.name}。"
                        )
                else:
                    audio_graph = (mixed_audio_filter(self.settings.get("original_volume", 100),
                                                      self.settings.get("background_volume", 25),
                                                      self.settings.get("audio_fade_mode"),
                                                      self.settings.get("audio_fade_in_ms",500),
                                                      self.settings.get("audio_fade_out_ms",500),video_duration,
                                                      tts_delay_ms)
                                   if mix_audio and source_has_audio else
                                   (replacement_audio_filter(self.settings.get("audio_fade_mode"),
                                                             self.settings.get("audio_fade_in_ms",500),
                                                             self.settings.get("audio_fade_out_ms",500),video_duration,
                                                             tts_delay_ms)
                                    if replace_audio else ""))
                if watermark_enabled:
                    # Decode the static PNG once; overlay=eof_action=repeat keeps that frame
                    # for the whole video without decoding/scaling the same image every frame.
                    command += ["-i", str(watermark)]
                    graph = watermark_filter_graph(ass_filter, render_settings, watermark_input, v_filter_str)
                    if audio_graph: graph += ";" + audio_graph
                    command += ["-filter_complex", graph,
                                "-map", "[outv]"]
                else:
                    vf_expr = ass_filter_expression(ass_filter,self.settings)
                    if v_filter_str:
                        vf_expr = f"{v_filter_str},{vf_expr}"
                    command += ["-vf", vf_expr, "-map", "0:v:0"]
                    if audio_graph: command += ["-filter_complex", audio_graph]
                if audio_graph:
                    command += ["-map", "[aout]", "-shortest"]
                    if bgm_file:
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 正在混音：添加配音音量 {self.settings.get('original_volume',100)}%，"
                                      f"背景音乐({bgm_file.name})音量 {self.settings.get('background_volume',25)}%。")
                    elif mix_audio:
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
                command += ["-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
                if (external or bgm_file) and audio_mode in ("替换为添加的音频", "原声＋背景音混合"):
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
            try:
                checkpoint_path = Path(self.output) / "reels_checkpoint.json"
                if checkpoint_path.is_file():
                    checkpoint_path.unlink()
            except Exception:
                pass
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
    log = Signal(str)

    def __init__(self, ffmpeg, source, destination, text, settings):
        super().__init__(); self.ffmpeg = ffmpeg; self.source = Path(source)
        self.destination = Path(destination); self.text = text; self.settings = settings

    def run(self):
        ass = temporary_ass_path("preview")
        try:
            source = Path(self.source)
            # 先把多轨时间轴（切片/挪动/转场）物化成真实视频，再叠字幕/水印
            edit_state = dict(self.settings.get("timeline_edits") or {})
            cache_dir = Path(self.settings.get("preview_cache_dir") or self.destination.parent)
            if edit_state.get("tracks", {}).get("video") or edit_state.get("transitions"):
                self.log.emit("轨道渲染：正在根据时间轴切片/转场生成画面…")
                source = Path(render_timeline_edits(self.ffmpeg, source, edit_state, cache_dir))
                self.log.emit(f"轨道画面已就绪：{source.name}")

            video_dur = max(0.2, float(media_duration(self.ffmpeg, source) or 0.2))
            # 轨道预览默认整段；超长片限制上限以免卡死（可用 settings 覆盖）
            max_preview = float(self.settings.get("preview_max_seconds") or 45.0)
            preview_duration = min(video_dur, max_preview)
            if video_dur > max_preview + 0.5:
                self.log.emit(
                    f"轨道预览时长 {video_dur:.1f}s 过长，本次截取前 {max_preview:.0f}s 核对（完整长度仍在最终导出）。"
                )

            if self.settings.get("caption_mode") == "自由文案动画（不对口型）":
                sample = free_caption_srt(self.text, preview_duration, self.settings)
            elif "-->" in self.text:
                sample = self.text
            else:
                end_ms = int(max(0.5, preview_duration) * 1000)
                h, rem = divmod(end_ms, 3600000)
                m, rem = divmod(rem, 60000)
                s, ms = divmod(rem, 1000)
                sample = (
                    f"1\n00:00:00,000 --> {h:02d}:{m:02d}:{s:02d},{ms:03d}\n"
                    f"{self.text}\n"
                )
            write_ass(ass, sample, self.settings, self.settings.get("preview_word_srt", ""))
            ass_filter = ass
            preview_audio = Path(str(self.settings.get("preview_audio", "")))
            external = preview_audio.is_file() and preview_audio.resolve() != Path(self.source).resolve()
            # 若时间轴上 TTS 轨被切过，先渲染对齐后的配音
            tts_clips = list((edit_state.get("tracks") or {}).get("tts") or [])
            if external and tts_clips:
                edited_tts = render_timeline_audio(
                    self.ffmpeg, preview_audio, tts_clips, cache_dir, "preview_tts"
                )
                if edited_tts:
                    preview_audio = Path(edited_tts)
                    self.settings = dict(self.settings)
                    self.settings["preview_audio_offset_ms"] = 0
            audio_mode = self.settings.get("audio_mode", "保留视频原音")
            mix_audio = external and audio_mode == "原声＋背景音混合"
            replace_audio = external and audio_mode == "替换为添加的音频"
            source_has_audio = media_has_audio(self.ffmpeg, source)
            baked_watermarks={str(Path(path).resolve()) for path in self.settings.get("watermark_baked_videos",[]) }
            watermark_already_baked=str(Path(self.source).resolve()) in baked_watermarks or str(source.resolve()) in baked_watermarks
            watermark_entries=[] if watermark_already_baked else (self.settings.get("watermarks") or [])
            watermark_paths=[] if watermark_already_baked else (self.settings.get("watermark_paths") or [self.settings.get("watermark_path","")])
            watermark = (prepared_watermark_composite(self.ffmpeg,source,watermark_entries,self.destination.parent)
                         if watermark_entries else prepared_watermark_stack(watermark_paths,self.destination.parent))
            watermark_enabled = watermark.is_file()
            render_settings=self.settings
            if watermark_enabled and watermark_entries:
                render_settings=dict(self.settings); render_settings.update({"watermark_prepared":True,"watermark_mode":"9:16 全屏覆盖"})
            elif watermark_enabled and self.settings.get("watermark_mode","9:16 全屏覆盖")=="9:16 全屏覆盖":
                watermark=prepared_fullframe_watermark(
                    self.ffmpeg,source,watermark,self.destination.parent,self.settings.get("watermark_opacity",100))
                render_settings=dict(self.settings); render_settings["watermark_prepared"]=True
            watermark_input = 2 if external else 1
            # Target dimensions scaling
            src_w, src_h = media_video_size(self.ffmpeg, source)
            aspect_ratio = self.settings.get("aspect_ratio", "原始比例")
            resolution = self.settings.get("resolution", "默认最高")
            target_w, target_h = calculate_target_size(src_w, src_h, aspect_ratio, resolution)
            need_resize = (aspect_ratio != "原始比例" or resolution != "默认最高")

            audio_dur = 0.0
            if external and preview_audio.is_file():
                audio_dur = media_duration(self.ffmpeg, preview_audio)

            extend_mode = self.settings.get("video_extend_mode", "不处理")
            loop_video = False
            extend_filters = []

            if audio_dur > video_dur and extend_mode != "不处理":
                diff = audio_dur - video_dur
                if extend_mode == "循环播放视频":
                    loop_video = True
                elif extend_mode == "最后一帧延长/冻结":
                    extend_filters.append(f"tpad=stop_duration={diff:.3f}:stop_mode=clone")
                elif extend_mode == "速度拉伸（减速延长）":
                    speed_ratio = video_dur / audio_dur
                    extend_filters.append(f"setpts=PTS/{speed_ratio:.4f}")
                video_dur = audio_dur
                preview_duration = min(video_dur, max_preview)

            # BGM 轨（可选）：预览时一并混入，贴近最终导出
            bgm_path = Path(str(self.settings.get("preview_bgm") or ""))
            bgm_enabled = bool(self.settings.get("bgm_enabled")) and bgm_path.is_file()
            bgm_clips = list((edit_state.get("tracks") or {}).get("bgm") or [])
            bgm_offset_ms = max(0, int(self.settings.get("preview_bgm_offset_ms") or 0))
            if bgm_enabled and bgm_clips:
                edited_bgm = render_timeline_audio(
                    self.ffmpeg, bgm_path, bgm_clips, cache_dir, "preview_bgm"
                )
                if edited_bgm:
                    bgm_path = Path(edited_bgm)
                    bgm_offset_ms = 0

            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
            if loop_video:
                command += ["-stream_loop", "-1"]
            command += ["-i", str(source)]
            if external:
                if mix_audio: command += ["-stream_loop", "-1"]
                preview_offset=max(0,int(self.settings.get("preview_audio_offset_ms",0)))
                if preview_offset: command += ["-ss",f"{preview_offset/1000:.3f}"]
                command += ["-i", str(preview_audio)]
            if bgm_enabled:
                if not bgm_clips:
                    command += ["-stream_loop", "-1"]
                if bgm_offset_ms > 0:
                    command += ["-ss", f"{bgm_offset_ms / 1000:.3f}"]
                command += ["-i", str(bgm_path)]
                watermark_input = (3 if external else 2)

            v_filters = []
            if need_resize:
                v_filters.append(f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}:(iw-ow)/2:(ih-oh)/2,setsar=1")
            if extend_filters:
                v_filters.extend(extend_filters)
            v_filter_str = ",".join(v_filters) if v_filters else ""

            # Build audio graph
            bgm_vol = int(self.settings.get("background_volume", 25) or 25)
            if bgm_enabled and external and mix_audio and source_has_audio:
                # 原声 + 配音混合后再加 BGM 较复杂；预览简化为：原声/配音主轨 + BGM
                bgm_in = "[2:a]" if external else "[1:a]"
                dialogue_in = "[1:a]" if external else "[0:a]"
                audio_graph = (
                    f"[0:a]aformat=channel_layouts=stereo,volume="
                    f"{max(0,min(200,int(self.settings.get('original_volume',100))))/100:.3f}[oa];"
                    f"{dialogue_in}aformat=channel_layouts=stereo,volume=1.0[da];"
                    f"[oa][da]amix=inputs=2:duration=first:dropout_transition=2[mix];"
                    f"{bgm_in}aformat=channel_layouts=stereo,volume="
                    f"{max(0,min(200,bgm_vol))/100:.3f}[ba];"
                    f"[mix][ba]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                )
            elif bgm_enabled and not external and source_has_audio:
                audio_graph = bgm_mix_audio_filter(
                    "[0:a]", "[1:a]",
                    self.settings.get("original_volume", 100),
                    bgm_vol,
                    self.settings.get("audio_fade_mode", "直接加入（无淡入淡出）"),
                    self.settings.get("audio_fade_in_ms", 500),
                    self.settings.get("audio_fade_out_ms", 500),
                    preview_duration,
                )
            elif bgm_enabled and external and replace_audio:
                audio_graph = bgm_mix_audio_filter(
                    "[1:a]", "[2:a]",
                    100,
                    bgm_vol,
                    self.settings.get("audio_fade_mode", "直接加入（无淡入淡出）"),
                    self.settings.get("audio_fade_in_ms", 500),
                    self.settings.get("audio_fade_out_ms", 500),
                    preview_duration,
                )
            else:
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

            command += ["-t", f"{preview_duration:.3f}"]
            self.log.emit(f"轨道渲染预览：编码约 {preview_duration:.1f}s（含字幕/水印核对）…")

            if watermark_enabled:
                graph = watermark_filter_graph(ass_filter, render_settings, watermark_input, v_filter_str)
                if audio_graph: graph += ";" + audio_graph
                command += ["-i", str(watermark), "-filter_complex",
                            graph, "-map", "[outv]"]
            else:
                vf_expr = ass_filter_expression(ass_filter,self.settings)
                if v_filter_str:
                    vf_expr = f"{v_filter_str},{vf_expr}"
                command += ["-vf", vf_expr, "-map", "0:v:0"]
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
            elif bgm_enabled:
                command += ["-ac", "2", "-shortest"]
            command += ["-movflags", "+faststart", str(self.destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
            if result.returncode: raise RuntimeError(result.stderr.strip() or "轨道渲染预览失败")
            self.finished.emit(True, str(self.destination))
        except Exception as exc:
            self.finished.emit(False, str(exc))
        finally:
            try: ass.unlink()
            except OSError: pass
class ScrollRedirectFilter(QObject):
    """未聚焦的 Spin/Combo 上滚轮：滚动外层区域，不改控件值。

    禁止对同一 QWheelEvent 再 sendEvent（Win11/Qt6 会 CE_INVALIDATED / 卡死）。
    """

    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self.scroll_area = scroll_area

    def eventFilter(self, obj, event):
        try:
            from PySide6.QtCore import QEvent
            if event is None:
                return False
            if event.type() == QEvent.Type.Wheel:
                if hasattr(obj, "hasFocus") and obj.hasFocus():
                    return False
                scroll = self.scroll_area
                if scroll is not None:
                    try:
                        angle = event.angleDelta()
                        dy = int(angle.y()) if angle is not None else 0
                        if dy == 0:
                            pixel = event.pixelDelta()
                            dy = int(pixel.y()) if pixel is not None else 0
                        bar = scroll.verticalScrollBar()
                        if bar is not None and dy:
                            steps = max(1, bar.singleStep() * 3)
                            if abs(dy) >= 15:
                                bar.setValue(bar.value() - int(dy / 120.0 * steps))
                            else:
                                bar.setValue(bar.value() - (steps if dy > 0 else -steps))
                    except Exception:
                        pass
                    return True
            elif event.type() == QEvent.Type.Leave:
                if hasattr(obj, "clearFocus"):
                    obj.clearFocus()
        except Exception:
            return False
        return super().eventFilter(obj, event)


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
        actions.addWidget(paste_all)
        calc_btn=QPushButton("🧮 时间换算工具"); calc_btn.clicked.connect(self._open_calc)
        actions.addWidget(calc_btn)
        actions.addStretch()
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

    def _open_calc(self):
        dialog = TimeCalculatorDialog(self)
        dialog.exec()

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


class ScriptProofreadDialog(QDialog):
    """Paste plain source script, compare with extracted SRT text (red diffs),
    apply replacements while keeping all timestamps."""

    def __init__(self, parent=None, timeline_srt="", preset_source=""):
        super().__init__(parent)
        self.setWindowTitle("文案校对（保留时间戳）")
        self.setMinimumSize(920, 640)
        self.resize(1000, 700)
        self._timeline_srt = str(timeline_srt or "")
        self._result_srt = ""
        self._change_count = 0
        self._language = None
        try:
            if parent is not None and hasattr(parent, "writing_language"):
                self._language = writing_language_from_ui(parent.writing_language.currentText())
        except Exception:
            self._language = None

        root = QVBoxLayout(self)
        root.setSpacing(8)
        tip = QLabel(
            "左侧为识别出的字幕（带时间）；右侧粘贴无时间戳的原文案。\n"
            "点击「对比预览」后，差异处用红色标出。提交替换只改文字，时间戳仍用音频识别结果。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#7dd3fc;padding:4px;")
        root.addWidget(tip)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(QLabel("① 提取字幕（只读）"))
        self.extracted_view = QTextBrowser()
        self.extracted_view.setOpenExternalLinks(False)
        self.extracted_view.setStyleSheet(
            "QTextBrowser { font-family: Consolas,'Microsoft YaHei UI'; font-size: 12px; }"
        )
        left_l.addWidget(self.extracted_view, 1)
        split.addWidget(left)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.addWidget(QLabel("② 原文案（粘贴，不要时间戳）"))
        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText(
            "在此粘贴完整正确文案……\n支持整段或按句换行；无需 00:00:00 --> 时间轴。"
        )
        self.source_edit.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas,'Microsoft YaHei UI'; font-size: 12px; }"
        )
        if preset_source:
            self.source_edit.setPlainText(preset_source)
        right_l.addWidget(self.source_edit, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 2)

        mid = QHBoxLayout()
        self.compare_btn = QPushButton("对比预览")
        self.compare_btn.setObjectName("primary")
        self.compare_btn.clicked.connect(self._run_compare)
        self.summary_label = QLabel("尚未对比")
        self.summary_label.setStyleSheet("color:#facc15;")
        mid.addWidget(self.compare_btn)
        mid.addWidget(self.summary_label, 1)
        root.addLayout(mid)

        root.addWidget(QLabel("③ 差异明细（红字 = 将修改处）"))
        self.diff_view = QTextBrowser()
        self.diff_view.setOpenExternalLinks(False)
        self.diff_view.setMinimumHeight(160)
        self.diff_view.setStyleSheet(
            "QTextBrowser { font-family: Consolas,'Microsoft YaHei UI'; font-size: 12px; }"
        )
        root.addWidget(self.diff_view, 2)

        root.addWidget(QLabel("④ 校对后 SRT 预览（时间戳未改）"))
        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setMinimumHeight(120)
        self.result_view.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas,'Microsoft YaHei UI'; font-size: 11px; color:#cbd5e1; }"
        )
        root.addWidget(self.result_view, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("提交替换")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_replace)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        root.addWidget(buttons)

        self._fill_extracted_readonly()
        self.source_edit.textChanged.connect(self._on_source_changed)

    def _fill_extracted_readonly(self):
        events = parse_srt(self._timeline_srt, language=self._language)
        import html as html_lib
        if not events:
            self.extracted_view.setHtml("<p style='color:#94a3b8;'>（无有效字幕条目）</p>")
            return
        rows = [
            "<div style='color:#e2e8f0;line-height:1.45;'>"
        ]
        for index, (start, end, text) in enumerate(events, 1):
            rows.append(
                f"<div style='margin:0 0 10px 0;padding:6px 8px;background:#0f172a;"
                f"border-left:3px solid #334155;border-radius:4px;'>"
                f"<div style='color:#64748b;font-size:11px;'>#{index}　"
                f"{html_lib.escape(_srt_stamp(start))} → {html_lib.escape(_srt_stamp(end))}</div>"
                f"<div style='margin-top:3px;'>{html_lib.escape(text)}</div></div>"
            )
        rows.append("</div>")
        self.extracted_view.setHtml("".join(rows))

    def _on_source_changed(self):
        # 文案改动后需重新对比才允许提交
        if self._result_srt:
            self._result_srt = ""
            self._change_count = 0
            self._ok_btn.setEnabled(False)
            self.summary_label.setText("原文案已修改，请重新「对比预览」")
            self.summary_label.setStyleSheet("color:#fbbf24;")

    def _run_compare(self):
        source = self.source_edit.toPlainText().strip()
        if not source:
            QMessageBox.information(self, "没有原文案", "请先在右侧粘贴无时间戳的原文案。")
            return
        if "-->" not in self._timeline_srt:
            QMessageBox.warning(self, "没有时间轴", "提取字幕无效，请关闭后重新提取。")
            return
        new_srt, changes = proofread_srt_keep_timestamps(
            self._timeline_srt, source, language=self._language,
        )
        self._result_srt = new_srt
        self._change_count = len(changes)
        self.result_view.setPlainText(new_srt)
        self._ok_btn.setEnabled(True)

        import html as html_lib
        if not changes:
            self.summary_label.setText("对比完成：文字与原文案一致，无需修改（0 处差异）")
            self.summary_label.setStyleSheet("color:#86efac;")
            self.diff_view.setHtml(
                "<p style='color:#86efac;'>未发现需要替换的文字差异。仍可提交（结果与当前字幕相同）。</p>"
            )
            return

        self.summary_label.setText(f"对比完成：共 {len(changes)} 处需要修改（红字为新文案）")
        self.summary_label.setStyleSheet("color:#f87171;font-weight:700;")
        parts = [
            "<div style='color:#e2e8f0;line-height:1.5;'>"
            f"<p style='color:#facc15;'>共 <b>{len(changes)}</b> 条字幕文字将变更；时间戳全部保留。</p>"
        ]
        for item in changes:
            old_html = html_lib.escape(item["old"])
            new_html = html_word_diff(item["old"], item["new"])
            parts.append(
                f"<div style='margin:0 0 12px 0;padding:8px 10px;background:#111827;"
                f"border:1px solid #334155;border-radius:6px;'>"
                f"<div style='color:#94a3b8;font-size:11px;'>#{item['index']}　"
                f"{html_lib.escape(_srt_stamp(item['start']))} → "
                f"{html_lib.escape(_srt_stamp(item['end']))}</div>"
                f"<div style='margin-top:4px;color:#94a3b8;'>提取：{old_html}</div>"
                f"<div style='margin-top:4px;'>校对：{new_html}</div>"
                f"</div>"
            )
        parts.append("</div>")
        self.diff_view.setHtml("".join(parts))

    def _accept_replace(self):
        if not self._result_srt:
            self._run_compare()
        if not self._result_srt:
            return
        self.accept()

    def result_srt(self):
        return self._result_srt

    def result_change_count(self):
        return int(self._change_count or 0)

    def source_script(self):
        return self.source_edit.toPlainText().strip()


class GroupMergeReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("每日分组合成报表")
        self.setMinimumSize(600, 450)
        
        layout = QVBoxLayout(self)
        
        # Date selector
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("选择日期:"))
        self.date_picker = QDateEdit()
        self.date_picker.setCalendarPopup(True)
        self.date_picker.setDate(QDate.currentDate())
        self.date_picker.dateChanged.connect(self.update_report)
        date_layout.addWidget(self.date_picker)
        date_layout.addStretch()
        layout.addLayout(date_layout)
        
        # Report display
        self.report_text = QTextBrowser()
        self.report_text.setReadOnly(True)
        self.report_text.setFont(QFont("Consolas", 10))
        layout.addWidget(self.report_text)
        
        # Buttons layout
        btn_layout = QHBoxLayout()
        
        self.copy_list_btn = QPushButton("详细列表 (TSV)")
        self.copy_list_btn.clicked.connect(self.copy_detailed_list)
        btn_layout.addWidget(self.copy_list_btn)
        
        self.copy_summary_btn = QPushButton("报表总结 (TSV)")
        self.copy_summary_btn.clicked.connect(self.copy_summary)
        btn_layout.addWidget(self.copy_summary_btn)
        
        self.copy_all_btn = QPushButton("复制全部")
        self.copy_all_btn.clicked.connect(self.copy_all)
        btn_layout.addWidget(self.copy_all_btn)
        
        self.clear_btn = QPushButton("清除今日历史")
        self.clear_btn.setStyleSheet("color: #fca5a5;")
        self.clear_btn.clicked.connect(self.clear_today_history)
        btn_layout.addWidget(self.clear_btn)
        
        layout.addLayout(btn_layout)
        
        self.update_report()
        
    def _get_history(self):
        try:
            from modules.platform_utils import app_data_dir
            history_path = app_data_dir() / "group_merge_history.json"
            if history_path.is_file():
                return json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []
        
    def _get_filtered_unique_entries(self):
        selected_date = self.date_picker.date().toString("yyyy-MM-dd")
        history = self._get_history()
        
        # Filter by selected date
        date_entries = [e for e in history if e.get("date") == selected_date]
        
        # De-duplicate by group_name, keeping the latest successful attempt
        unique_entries = {}
        for entry in date_entries:
            name = entry.get("group_name")
            if name:
                unique_entries[name] = entry
                
        return list(unique_entries.values())
        
    @staticmethod
    def _fmt_duration(seconds):
        try:
            sec = max(0.0, float(seconds or 0))
        except (TypeError, ValueError):
            sec = 0.0
        total = int(round(sec))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d} ({sec:.2f}s)"
        return f"{m}:{s:02d} ({sec:.2f}s)"

    def update_report(self):
        entries = self._get_filtered_unique_entries()
        
        # Calculate summary
        total_videos = len(entries)
        total_clips = sum(int(e.get("clip_count", 0)) for e in entries)
        total_output_sec = sum(float(e.get("output_duration_sec") or 0) for e in entries)
        total_segments_sec = sum(float(e.get("segments_total_sec") or 0) for e in entries)
        
        # Build HTML for display
        html = f"<h3>每日合成报表 ({self.date_picker.date().toString('yyyy-MM-dd')})</h3>"
        html += "<h4>详细列表</h4>"
        html += "<table border='1' cellpadding='4' style='border-collapse: collapse; border: 1px solid #334155;'>"
        html += (
            "<tr style='background: #1e293b;'>"
            "<th>合成时间</th><th>视频组</th><th>片段数</th>"
            "<th>各分段时长</th><th>成品总时长</th><th>成品文件名</th></tr>"
        )
        for e in entries:
            segs = e.get("segment_durations") or []
            if segs:
                seg_html = "<br/>".join(
                    f"{i+1}. {s.get('name','')} — {self._fmt_duration(s.get('duration_sec'))}"
                    for i, s in enumerate(segs)
                )
            else:
                seg_html = "<span style='color:#a8a29e;'>—</span>"
            out_dur = e.get("output_duration_sec")
            out_html = self._fmt_duration(out_dur) if out_dur else "<span style='color:#a8a29e;'>—</span>"
            ts = str(e.get("timestamp", "")).split(" ")
            time_part = ts[1] if len(ts) > 1 else e.get("timestamp", "")
            html += (
                f"<tr><td>{time_part}</td><td>{e.get('group_name')}</td>"
                f"<td align='center'>{e.get('clip_count')}</td>"
                f"<td style='font-size:12px;'>{seg_html}</td>"
                f"<td align='center'>{out_html}</td>"
                f"<td>{e.get('output_name')}</td></tr>"
            )
        if not entries:
            html += "<tr><td colspan='6' align='center' style='color:#a8a29e;'>当天无合成成功的历史记录 (数据为 0)</td></tr>"
        html += "</table>"
        
        html += "<h4>报表总结</h4>"
        html += "<table border='1' cellpadding='4' style='border-collapse: collapse; border: 1px solid #334155;'>"
        html += f"<tr><td style='background: #1e293b;'><b>实际合成视频组数 (去重)</b></td><td align='center'>{total_videos}</td></tr>"
        html += f"<tr><td style='background: #1e293b;'><b>实际合成总片段数 (去重)</b></td><td align='center'>{total_clips}</td></tr>"
        html += f"<tr><td style='background: #1e293b;'><b>分段素材时长合计</b></td><td align='center'>{self._fmt_duration(total_segments_sec)}</td></tr>"
        html += f"<tr><td style='background: #1e293b;'><b>成品总时长合计</b></td><td align='center'>{self._fmt_duration(total_output_sec)}</td></tr>"
        html += "</table>"
        
        self.report_text.setHtml(html)
        
    def copy_detailed_list(self):
        entries = self._get_filtered_unique_entries()
        lines = ["合成时间\t视频组(文件夹)\t已合成片段数\t各分段时长\t成品总时长(秒)\t成品文件名"]
        for e in entries:
            time_part = str(e.get("timestamp", "")).split(" ")
            time_part = time_part[1] if len(time_part) > 1 else e.get("timestamp", "")
            segs = e.get("segment_durations") or []
            seg_text = "; ".join(
                f"{s.get('name','')}={float(s.get('duration_sec') or 0):.2f}s" for s in segs
            ) if segs else ""
            out_dur = e.get("output_duration_sec")
            out_text = f"{float(out_dur):.2f}" if out_dur not in (None, "") else ""
            lines.append(
                f"{time_part}\t{e.get('group_name')}\t{e.get('clip_count')}\t"
                f"{seg_text}\t{out_text}\t{e.get('output_name')}"
            )
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "复制成功", "详细列表已以 TSV 格式复制到剪贴板，可直接粘贴到 Google Sheets 或 Excel。")
        
    def copy_summary(self):
        entries = self._get_filtered_unique_entries()
        total_videos = len(entries)
        total_clips = sum(int(e.get("clip_count", 0)) for e in entries)
        total_output_sec = sum(float(e.get("output_duration_sec") or 0) for e in entries)
        total_segments_sec = sum(float(e.get("segments_total_sec") or 0) for e in entries)
        
        lines = [
            "指标\t数值",
            f"实际合成视频组数 (去重)\t{total_videos}",
            f"实际合成总片段数 (去重)\t{total_clips}",
            f"分段素材时长合计(秒)\t{total_segments_sec:.2f}",
            f"成品总时长合计(秒)\t{total_output_sec:.2f}",
        ]
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "复制成功", "总结已以 TSV 格式复制到剪贴板，可直接粘贴到 Google Sheets 或 Excel。")
        
    def copy_all(self):
        entries = self._get_filtered_unique_entries()
        total_videos = len(entries)
        total_clips = sum(int(e.get("clip_count", 0)) for e in entries)
        total_output_sec = sum(float(e.get("output_duration_sec") or 0) for e in entries)
        total_segments_sec = sum(float(e.get("segments_total_sec") or 0) for e in entries)
        
        selected_date = self.date_picker.date().toString("yyyy-MM-dd")
        text = f"每日合成报表 ({selected_date})\n\n"
        text += "详细列表\n"
        text += "合成时间\t视频组(文件夹)\t已合成片段数\t各分段时长\t成品总时长(秒)\t成品文件名\n"
        for e in entries:
            time_part = str(e.get("timestamp", "")).split(" ")
            time_part = time_part[1] if len(time_part) > 1 else e.get("timestamp", "")
            segs = e.get("segment_durations") or []
            seg_text = "; ".join(
                f"{s.get('name','')}={float(s.get('duration_sec') or 0):.2f}s" for s in segs
            ) if segs else ""
            out_dur = e.get("output_duration_sec")
            out_text = f"{float(out_dur):.2f}" if out_dur not in (None, "") else ""
            text += (
                f"{time_part}\t{e.get('group_name')}\t{e.get('clip_count')}\t"
                f"{seg_text}\t{out_text}\t{e.get('output_name')}\n"
            )
        if not entries:
            text += "(无数据)\n"
        text += "\n报表总结\n"
        text += f"实际合成视频组数 (去重)\t{total_videos}\n"
        text += f"实际合成总片段数 (去重)\t{total_clips}\n"
        text += f"分段素材时长合计(秒)\t{total_segments_sec:.2f}\n"
        text += f"成品总时长合计(秒)\t{total_output_sec:.2f}\n"
        
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "复制成功", "所有报表内容已复制到剪贴板。")
        
    def clear_today_history(self):
        selected_date = self.date_picker.date().toString("yyyy-MM-dd")
        reply = QMessageBox.question(
            self, "确认清除", f"是否确认清除 {selected_date} 的所有合成历史记录？该操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from modules.platform_utils import app_data_dir
                history_path = app_data_dir() / "group_merge_history.json"
                if history_path.is_file():
                    history = json.loads(history_path.read_text(encoding="utf-8"))
                    new_history = [e for e in history if e.get("date") != selected_date]
                    history_path.write_text(json.dumps(new_history, ensure_ascii=False, indent=2), encoding="utf-8")
                self.update_report()
            except Exception as exc:
                QMessageBox.critical(self, "清除失败", str(exc))


class DynamicCaptionPage(QWidget):
    rename_folder_requested = Signal(str)
    navigate_requested = Signal(int)

    def __init__(self, transcribe_callable, tts_callable, find_ffmpeg, providers, default_provider,
                 sync_profiles_callable=None, cloud_sync_callable=None, open_sync_settings_callable=None, store=None):
        super().__init__(); self.transcribe_callable = transcribe_callable; self.find_ffmpeg = find_ffmpeg
        self.tts_callable = tts_callable; self.providers = providers; self.thread = None; self.worker = None
        self.store = store
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
        self.timeline_edit_states = {}
        self._selected_bgm_path = ""
        self._timeline_activity_started=0.0; self._timeline_activity_label=""
        self._timeline_activity_base=0; self._timeline_activity_cap=90
        self._timeline_activity_timer=QTimer(self); self._timeline_activity_timer.setInterval(800)
        self._timeline_activity_timer.timeout.connect(self._timeline_activity_tick)
        self._restoring_style = False
        # 图层列表按“上层在前”保存；渲染时反向绘制，便于用户理解上移/下移。
        self.layers = [{"type": "caption", "name": "字幕层"}]
        # 动态追踪路径（模糊/标签）；与字幕轨独立，导出时在烧录字幕前作用于画面
        self.motion_tracks = []
        self.selection_debounce_timer = QTimer(self)
        self.selection_debounce_timer.setSingleShot(True)
        # 稍长防抖：快速连点队列/反复合成时合并加载请求，减轻 QMediaPlayer 压力
        self.selection_debounce_timer.setInterval(280)
        self.selection_debounce_timer.timeout.connect(self._on_debounce_load_media)
        
        self.audio_debounce_timer = QTimer(self)
        self.audio_debounce_timer.setSingleShot(True)
        self.audio_debounce_timer.setInterval(280)
        self.audio_debounce_timer.timeout.connect(self._on_debounce_load_audio)
        # 预览会话：世代号作废过期回调；串行加载避免频繁 setSource 卡死/报错
        self._preview_token = 0
        self._preview_suppress_errors = False
        self._preview_load_timer = QTimer(self)
        self._preview_load_timer.setSingleShot(True)
        self._preview_load_timer.setInterval(90)
        self._preview_load_timer.timeout.connect(self._apply_pending_preview_load)
        self._pending_preview_load = None  # dict | None
        self._preview_loaded_path = ""  # 当前预览已绑定的源路径，避免过期 duration 回调错绑
        self._media_duration_cache = {}  # path_key -> duration_ms
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
        self.videos.paths_dropped.connect(lambda p: self._add(self.videos, p, ALLOWED_VIDEO_INPUTS))
        self.videos.currentTextChanged.connect(self._video_selection_changed); vg.addWidget(self.videos, 1)
        vrow = QHBoxLayout(); vb = QPushButton("添加视频"); vb.clicked.connect(self._choose_videos)
        vf = QPushButton("添加文件夹"); vf.clicked.connect(lambda: self._choose_folder(self.videos, ALLOWED_VIDEO_INPUTS))
        vc = QPushButton("清空"); vc.clicked.connect(lambda: self._clear_media_queue(self.videos))
        for button in (vb,vf,vc): vrow.addWidget(button)
        vg.addLayout(vrow)

        audio_tab = QWidget(); audio_tab_layout = QVBoxLayout(audio_tab); audio_tab_layout.setContentsMargins(4,4,4,4)
        self.audios = DropListWidget(); self.audios.setMinimumHeight(95); self.audios.paths_dropped.connect(lambda p: self._add(self.audios, p, AUDIO_EXTENSIONS))
        self.audios.currentTextChanged.connect(self._audio_selection_changed)
        arow = QHBoxLayout()
        ab = QPushButton("批量添加音频"); ab.clicked.connect(self._choose_audio)
        ab.setToolTip("可一次多选音频文件加入队列（也可拖入列表或选文件夹）")
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
        self.group_table = QTableWidget(0,5); self.group_table.setHorizontalHeaderLabels(["序号","文件夹","片段","文件列表","自定义转场"])
        self.group_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.group_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.group_table.setMinimumHeight(120)
        self.group_table.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.group_table.verticalHeader().setVisible(False)
        self.group_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed)
        self.group_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.group_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Fixed)
        self.group_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        self.group_table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.ResizeToContents)
        self.group_table.setColumnWidth(0,42); self.group_table.setColumnWidth(2,46); self.group_table.setColumnWidth(4,100)
        self.group_table.currentCellChanged.connect(self._group_selection_changed)
        group_layout.addWidget(self.group_table,1)
        sort_row = QHBoxLayout(); sort_row.addWidget(QLabel("排序"))
        self.group_sort_mode = QComboBox(); self.group_sort_mode.addItems(["文件名自然排序（推荐）","按分段文案自动匹配"])
        self.group_sort_mode.currentTextChanged.connect(self._group_sort_mode_changed)
        self.group_trim_mode = QComboBox()
        self.group_trim_mode.addItems([
            "智能混合边界（推荐）",
            "仅按文案边界",
            "快速声音边界",
            "不裁剪（保留完整片段）",
        ])
        self.group_trim_mode.setCurrentText("智能混合边界（推荐）")
        self.group_trim_mode.setToolTip(
            "智能混合模式会用文案首词/末词时间定位正文，再用声音检测修正首尾；"
            "识别失败会自动退回本地声音检测，不会中断整批任务。"
        )
        self.group_head_padding = QSpinBox(); self.group_head_padding.setRange(0,1000); self.group_head_padding.setValue(100); self.group_head_padding.setSuffix(" ms")
        # 尾保护默认加大，减轻 ASR 词尾偏早导致的吞尾音
        self.group_tail_padding = QSpinBox(); self.group_tail_padding.setRange(0,1500); self.group_tail_padding.setValue(280); self.group_tail_padding.setSuffix(" ms")
        sort_row.addWidget(self.group_sort_mode,1); group_layout.addLayout(sort_row)
        trim_mode_row=QHBoxLayout(); trim_mode_row.addWidget(QLabel("裁剪")); trim_mode_row.addWidget(self.group_trim_mode,1)
        group_layout.addLayout(trim_mode_row)
        # 不转文案：合成后不自动提取字幕（快速声音边界尤其常用；与左侧「合成并转文字」联动）
        self.group_skip_transcript = QCheckBox("不转文案")
        self.group_skip_transcript.setToolTip(
            "勾选后：分组合成完成不自动提取字幕（不跑转文字）。\n"
            "适合「快速声音边界」大批量去口气；需要字幕时可取消勾选或事后手动提取。\n"
            "注意：若排序为「按分段文案自动匹配」，合成过程中仍会识别语音用于排序，与本选项无关。"
        )
        self.group_skip_transcript.setChecked(False)
        skip_row = QHBoxLayout()
        skip_row.addWidget(self.group_skip_transcript)
        skip_row.addStretch(1)
        group_layout.addLayout(skip_row)
        self.group_head_padding.setMinimumWidth(78); self.group_tail_padding.setMinimumWidth(78)
        self.group_head_padding.setToolTip("第一词前最多保留的保护时间，防止吞掉词首发音")
        self.group_tail_padding.setToolTip(
            "最后一词后额外保留时间（推荐 250–400ms）。ASR 词尾常偏早，过小会吞尾音。"
        )
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
        self.group_auto_timeline.setToolTip("与右侧「不转文案」相反：勾选则合成后自动批量提取字幕。")
        self.group_auto_timeline.toggled.connect(self._sync_group_transcript_flags_from_auto)
        self.group_skip_transcript.toggled.connect(self._sync_group_transcript_flags_from_skip)
        self.group_trim_mode.currentTextChanged.connect(self._on_group_trim_mode_changed)
        self.group_merge_start = QPushButton("合成"); self.group_merge_start.setObjectName("primary"); self.group_merge_start.setFixedSize(100,42); self.group_merge_start.clicked.connect(self.start_group_merge)
        self.group_merge_stop = QPushButton("停止"); self.group_merge_stop.setFixedSize(100,42); self.group_merge_stop.setEnabled(False); self.group_merge_stop.clicked.connect(self.stop_group_merge)
        self.group_merge_selected = QPushButton("重新合成选中组"); self.group_merge_selected.setFixedSize(100,36); self.group_merge_selected.clicked.connect(self.start_group_merge_selected)
        self.group_merge_report_btn = QPushButton("合成报表"); self.group_merge_report_btn.setFixedSize(100,36); self.group_merge_report_btn.clicked.connect(self._show_group_merge_report)
        group_action_layout.addWidget(self.group_auto_timeline)
        self.group_watermark_button=QPushButton("水印 / 蒙版")
        self.group_watermark_button.clicked.connect(lambda:self._open_left_setting("watermark"))
        group_action_layout.addWidget(self.group_watermark_button)
        group_action_layout.addWidget(self.group_merge_start); group_action_layout.addWidget(self.group_merge_stop)
        group_action_layout.addWidget(self.group_merge_selected)
        self.group_bgm_button=QPushButton("添加背景音乐")
        self.group_bgm_button.setToolTip("选择当前合成项目使用的背景音乐，并显示到独立 BGM 轨道")
        self.group_bgm_button.clicked.connect(self._choose_bgm_file)
        group_action_layout.addWidget(self.group_bgm_button)
        group_action_layout.addWidget(self.group_merge_report_btn)
        group_action_layout.addStretch()
        group_action_panel.setFixedWidth(126)

        project_action_panel=QWidget(); self.project_action_panel=project_action_panel
        project_action_layout=QVBoxLayout(project_action_panel); project_action_layout.setContentsMargins(2,4,2,2); project_action_layout.setSpacing(5)
        self.proj_auto_timeline = QCheckBox("合成并转文字"); self.proj_auto_timeline.setChecked(True)
        self.proj_burn_watermark = QCheckBox("水印"); self.proj_burn_watermark.setChecked(False)
        self.project_start_btn = QPushButton("合成"); self.project_start_btn.setObjectName("primary"); self.project_start_btn.setFixedSize(100,42); self.project_start_btn.clicked.connect(self.start_project_synthesis)
        self.project_stop_btn = QPushButton("停止"); self.project_stop_btn.setFixedSize(100,42); self.project_stop_btn.setEnabled(False); self.project_stop_btn.clicked.connect(self.stop_project_synthesis)
        project_action_layout.addWidget(self.proj_auto_timeline)
        project_action_layout.addWidget(self.proj_burn_watermark)
        project_action_layout.addWidget(self.project_start_btn); project_action_layout.addWidget(self.project_stop_btn)
        project_action_layout.addStretch()
        project_action_panel.setFixedWidth(126)

        image_tab = QWidget()
        self.image_tab = image_tab
        img_layout = QVBoxLayout(image_tab)
        img_layout.setContentsMargins(4, 4, 4, 4)
        
        self.images = DropListWidget()
        self.images.setMinimumHeight(95)
        self.images.paths_dropped.connect(lambda p: self._add(self.images, p, IMAGE_EXTENSIONS))
        img_layout.addWidget(self.images, 1)
        
        img_btn_row = QHBoxLayout()
        add_img_btn = QPushButton("添加图片")
        add_img_btn.clicked.connect(self._choose_images)
        clear_img_btn = QPushButton("清空")
        clear_img_btn.clicked.connect(lambda: self._clear_media_queue(self.images))
        img_btn_row.addWidget(add_img_btn)
        img_btn_row.addWidget(clear_img_btn)
        img_layout.addLayout(img_btn_row)
        
        img_settings = QFormLayout()
        img_settings.setContentsMargins(4, 4, 4, 4)
        img_settings.setSpacing(6)
        
        self.img_duration = QDoubleSpinBox()
        self.img_duration.setRange(0.5, 30.0)
        self.img_duration.setValue(3.0)
        self.img_duration.setSuffix(" 秒")
        self.img_duration.setToolTip("每张图片在生成的视频中停留的时长（秒）")
        
        self.img_transition = QComboBox()
        self.img_transition.addItems(["无转场", *merge_transition_labels()])
        self.img_transition.setToolTip("图片与图片之间的合并转场效果")
        
        self.img_trans_dur = QDoubleSpinBox()
        self.img_trans_dur.setRange(0.1, 5.0)
        self.img_trans_dur.setValue(0.5)
        self.img_trans_dur.setSuffix(" 秒")
        self.img_trans_dur.setToolTip("转场动画持续时间（秒）")
        
        self.img_animation = QComboBox()
        self.img_animation.addItems(["静态图片", "智能慢速变焦（Ken Burns）"])
        self.img_animation.setToolTip("使静态图片动起来，模拟真实摄像机慢速推拉摇移（Ken Burns）效果")
        
        img_settings.addRow("单图时长", self.img_duration)
        img_settings.addRow("转场动画", self.img_transition)
        img_settings.addRow("转场时长", self.img_trans_dur)
        img_settings.addRow("动画效果", self.img_animation)
        img_layout.addLayout(img_settings)
        
        self.img_generate = QPushButton("生成幻灯片视频并入队")
        self.img_generate.setObjectName("primary")
        self.img_generate.clicked.connect(self.generate_image_slideshow)
        img_layout.addWidget(self.img_generate)

        # Define project_tab
        project_tab = QWidget()
        proj_layout = QVBoxLayout(project_tab)
        proj_layout.setContentsMargins(4, 4, 4, 4)
        proj_layout.setSpacing(6)
        
        # Table widget
        self.project_table = ProjectTableWidget(0, 6)
        self.project_table.setHorizontalHeaderLabels(["项目名称", "语音文案 (双击编辑)", "素材列表 (可拖入视频/图片)", "背景音乐 (可选)", "画幅尺寸", "状态"])
        self.project_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.project_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.project_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.project_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.project_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.project_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.project_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.project_table.setMinimumHeight(150)
        self.project_table.cellDoubleClicked.connect(self._project_cell_double_clicked)
        self.project_table.currentCellChanged.connect(self._project_current_cell_changed)
        proj_layout.addWidget(self.project_table, 2)
        
        # Toolbar at top of table (let's add a layout)
        proj_toolbar = QHBoxLayout()
        add_proj_btn = QPushButton("＋ 新增项目")
        add_proj_btn.clicked.connect(self._add_project_dialog)
        del_proj_btn = QPushButton("➖ 删除项目")
        del_proj_btn.clicked.connect(self._delete_selected_projects)
        paste_proj_btn = QPushButton("📋 从 Excel 粘贴")
        paste_proj_btn.clicked.connect(self._paste_projects_from_clipboard)
        batch_audio_proj_btn = QPushButton("🎵 批量导入外部配音")
        batch_audio_proj_btn.setToolTip(
            "一次选择多个已转好的音频，按文件名排序后写入各行「语音文案」列；\n"
            "该行将跳过 TTS，直接用外部音频合成。行数不足会自动补行。"
        )
        batch_audio_proj_btn.clicked.connect(self._batch_import_project_external_audio)
        clear_proj_btn = QPushButton("🧹 清空项目")
        clear_proj_btn.clicked.connect(self._clear_projects)
        proj_toolbar.addWidget(add_proj_btn)
        proj_toolbar.addWidget(del_proj_btn)
        proj_toolbar.addWidget(paste_proj_btn)
        proj_toolbar.addWidget(batch_audio_proj_btn)
        proj_toolbar.addWidget(clear_proj_btn)
        proj_layout.insertLayout(0, proj_toolbar) # Put it at the top!
        
        # Large plain text editor at bottom for editing current row's script
        self.project_script_edit = QPlainTextEdit()
        self.project_script_edit.setPlaceholderText("在此处编辑当前选中项目的详细多行长文案...")
        self.project_script_edit.setMinimumHeight(65)
        self.project_script_edit.textChanged.connect(self._project_script_edit_changed)
        proj_layout.addWidget(QLabel("选中行文案详细编辑区域:"), 0)
        proj_layout.addWidget(self.project_script_edit, 1)
        
        # Project tab settings form - spaced out beautifully
        proj_settings_form = QFormLayout()
        proj_settings_form.setSpacing(10)
        
        self.proj_img_transition = QComboBox()
        self.proj_img_transition.addItems(["无转场", *merge_transition_labels()])
        proj_settings_form.addRow("图片转场效果:", self.proj_img_transition)
        
        self.proj_transition_dur = QDoubleSpinBox()
        self.proj_transition_dur.setRange(0.1, 5.0)
        self.proj_transition_dur.setValue(0.5)
        self.proj_transition_dur.setSuffix(" 秒")
        proj_settings_form.addRow("转场持续时间:", self.proj_transition_dur)
        
        self.proj_img_animation = QComboBox()
        self.proj_img_animation.addItems(["静态图片", "智能慢速变焦（Ken Burns）"])
        proj_settings_form.addRow("图片动画效果:", self.proj_img_animation)
        
        self.proj_ai_service = QComboBox()
        self.proj_ai_service.addItems(["未启用 (使用本地变焦特效)", "Luma API", "Kling API (可灵)"])
        proj_settings_form.addRow("AI 视频生成(可选):", self.proj_ai_service)
        
        self.proj_tts_service = QComboBox()
        self.proj_tts_service.addItems(["微软文字转语音", "Gemini 自然语音", "ElevenLabs API"])
        self.proj_tts_service.currentTextChanged.connect(self._on_proj_tts_service_changed)
        proj_settings_form.addRow("配音转写服务:", self.proj_tts_service)
        
        self.proj_tts_voice = QComboBox()
        self.proj_tts_voice.setEditable(True)
        # Load voices matching the initial tts_voice
        for idx in range(self.tts_voice.count()):
            self.proj_tts_voice.addItem(self.tts_voice.itemText(idx))
        self.proj_tts_voice.setCurrentText(self.tts_voice.currentText())
        self.proj_tts_voice.currentTextChanged.connect(self._on_proj_tts_voice_changed)
        proj_settings_form.addRow("语音配音音色:", self.proj_tts_voice)
        
        proj_layout.addLayout(proj_settings_form)
        
        # Initialize default row
        self._add_project_row()

        # Connect signals for auto save preference
        self.proj_img_transition.currentTextChanged.connect(self._save_style_preferences)
        self.proj_img_animation.currentTextChanged.connect(self._save_style_preferences)
        self.proj_transition_dur.valueChanged.connect(self._save_style_preferences)
        self.proj_ai_service.currentTextChanged.connect(self._save_style_preferences)
        self.proj_tts_service.currentTextChanged.connect(self._save_style_preferences)
        self.proj_tts_voice.currentTextChanged.connect(self._save_style_preferences)
        for page in (group_tab, video_tab, audio_tab, text_tab, project_tab): source_stack.addWidget(page)
        source_tools=QVBoxLayout(); source_tools.setContentsMargins(4,0,0,0); source_tools.setSpacing(5)
        self.source_tool_buttons=[]
        for index,label in enumerate(("分组合成","视频字幕","图文配音成片")):
            button=DropButton(label) if index in (1, 2) else QPushButton(label)
            button.setCheckable(True); button.setFixedSize(130,42)
            button.setToolTip({0:"分组去口气音并合成",1:"视频素材队列",2:"图文配音一键成片"}[index])
            button.clicked.connect(lambda checked=False,i=index:self._show_source_tool(i))
            if index == 1:
                button.paths_dropped.connect(lambda p: self._add(self.videos, p, ALLOWED_VIDEO_INPUTS))
            elif index == 2:
                button.paths_dropped.connect(self._on_project_tab_dropped)
            source_tools.addWidget(button); self.source_tool_buttons.append(button)
        source_tools.addStretch()
        source_rail=QWidget(); source_rail_layout=QVBoxLayout(source_rail); source_rail_layout.setContentsMargins(0,0,0,0); source_rail_layout.setSpacing(5)
        source_rail_layout.addLayout(source_tools)
        source_rail_layout.addWidget(group_action_panel,1)
        source_rail_layout.addWidget(project_action_panel,1)
        source_rail.setFixedWidth(138)
        source_group_layout.addWidget(source_rail)
        source_divider=QFrame(); source_divider.setFrameShape(QFrame.Shape.VLine)
        source_divider.setStyleSheet("color:#334155;")
        source_group_layout.addWidget(source_divider)
        source_group_layout.addWidget(source_stack,1)
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
        self.player.errorOccurred.connect(self._on_preview_player_error)
        self.bgm_player = QMediaPlayer(self)
        self.bgm_audio_output = QAudioOutput(self)
        self.bgm_audio_output.setVolume(.4)
        self.bgm_player.setAudioOutput(self.bgm_audio_output)
        self.player.playbackStateChanged.connect(self._on_player_playback_state_changed)
        if hasattr(self, "audio_player"):
            self.audio_player.errorOccurred.connect(self._on_preview_player_error)
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
        live_hint = QLabel("样式实时看；轨道拖动后点「轨道渲染预览」听看调整结果")
        live_hint.setStyleSheet("color:#7dd3fc;")
        live_row.addWidget(self.live_preview); live_row.addStretch(); live_row.addWidget(live_hint)
        preview_layout.addLayout(live_row)
        self.render_preview_btn = QPushButton("轨道渲染预览")
        self.render_preview_btn.setObjectName("primary")
        self.render_preview_btn.setToolTip(
            "把时间轴上的视频切片/挪动/转场 + 字幕/水印/BGM 渲染成可播放片段。\n"
            "比「重新合成」快，专门用来核对轨道调整，不等于整组重跑。"
        )
        self.render_preview_btn.clicked.connect(self.render_effect_preview)
        self.render_preview_btn.setMaximumWidth(230)
        self.clear_preview_btn=QPushButton("清除轨道预览"); self.clear_preview_btn.clicked.connect(self._clear_precise_preview)
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
        self.font_size=QSpinBox(); self.font_size.setRange(10,600); self.font_size.setValue(58)
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
        self.max_words=QSpinBox(); self.max_words.setRange(1,20); self.max_words.setValue(7)
        self.highlight_padding=QSpinBox(); self.highlight_padding.setRange(0,120); self.highlight_padding.setValue(18); self.highlight_padding.setSuffix(" px")
        self.highlight_padding.setToolTip("跟读色块左右留白")
        self.highlight_padding_y=QSpinBox(); self.highlight_padding_y.setRange(0,120); self.highlight_padding_y.setValue(10); self.highlight_padding_y.setSuffix(" px")
        self.highlight_padding_y.setToolTip("跟读色块上下留白")
        self.animation_speed=QSpinBox(); self.animation_speed.setRange(60,360); self.animation_speed.setValue(150); self.animation_speed.setSuffix(" ms")
        self.outline_width=QSpinBox(); self.outline_width.setRange(0,12); self.outline_width.setValue(3)
        self.position=QComboBox(); self.position.addItems(["底部","画面中间","顶部"])
        self.position.currentTextChanged.connect(self._position_changed)
        self.margin_v=QSpinBox(); self.margin_v.setRange(20,900); self.margin_v.setValue(250)
        self.margin_v.valueChanged.connect(self._sync_preview_margin)
        position_line=QHBoxLayout(); position_line.addWidget(self.position); position_line.addWidget(QLabel("边距")); position_line.addWidget(self.margin_v)
        # 窄栏/Win11 下 SpinBox 被压扁时数字残成 I/O/x；后缀（px/%/ms）更要加宽
        for spin, width in (
            (self.font_size, 100), (self.max_words, 88), (self.line_length, 88),
            (self.line_width, 110), (self.letter_spacing, 110), (self.word_spacing, 110),
            (self.line_spacing, 110), (self.highlight_padding, 110), (self.highlight_padding_y, 110),
            (self.animation_speed, 110), (self.outline_width, 88), (self.margin_v, 100),
            (self.free_page_seconds, 120),
        ):
            _configure_numeric_spin(spin, min_width=width)
        self.bgm_dir_input = DropFolderLineEdit(); self.bgm_dir_input.setPlaceholderText("留空不添加背景音乐")
        self.bgm_dir_input.folder_dropped.connect(self._bgm_folder_dropped)
        self.audio_mode=QComboBox(); self.audio_mode.addItems([
            "视频原声",
            "视频原声＋背景音乐",
            "视频配音＋背景音乐",
        ])
        self.audio_mode.currentTextChanged.connect(self._rematch_current_video)
        self.audio_mode.currentTextChanged.connect(self._audio_mode_changed)
        self.original_volume=QSpinBox(); self.original_volume.setRange(0,200); self.original_volume.setValue(100); self.original_volume.setSuffix(" %")
        self.background_volume=QSpinBox(); self.background_volume.setRange(0,200); self.background_volume.setValue(25); self.background_volume.setSuffix(" %")
        _configure_numeric_spin(self.original_volume, min_width=100)
        _configure_numeric_spin(self.background_volume, min_width=100)
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
        _configure_numeric_spin(self.audio_fade_in, min_width=110)
        _configure_numeric_spin(self.audio_fade_out, min_width=110)
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
        self.encoder_backend.setToolTip(
            "推荐「自动硬件加速」。CPU 兼容模式最慢且占满 CPU，预览也会卡。\n"
            "Alienware 等游戏本优先 NVIDIA NVENC。"
        )
        self.encode_preset=QComboBox()
        self.encode_preset.addItems(["ultrafast", "veryfast", "faster", "fast", "medium"])
        self.encode_preset.setCurrentText("veryfast")
        self.encode_preset.setToolTip("仅 CPU 模式生效。越快画质略降；口播成片用 veryfast/ultrafast 即可。")
        self.writing_language = QComboBox()
        fill_writing_language_combo(self.writing_language, "")
        self.writing_language.setToolTip(
            "书写规范语言包：引号/标点/RTL 方向。自动检测根据文案字符判断；"
            "可选手动指定希腊、阿拉伯、希伯来等。规则内置，无需系统语言包。")
        self.rtl_word_highlight = QCheckBox("RTL 逐词高亮（实验）")
        self.rtl_word_highlight.setToolTip(
            "阿拉伯语/希伯来语默认整句烧录以免破坏连写；勾选后尝试逐词高亮（可能影响字形连接）。")
        for combo in (self.caption_mode,self.free_animation,self.font,self.position,self.audio_match_mode,self.audio_mode,
                      self.audio_fade_mode,self.encoder_backend,self.encode_preset,self.writing_language):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8); combo.setMinimumWidth(0)
        phrase_line=QHBoxLayout(); phrase_line.addWidget(QLabel("每句词数")); phrase_line.addWidget(self.max_words); phrase_line.addWidget(QLabel("每行字符")); phrase_line.addWidget(self.line_length)
        width_line=QHBoxLayout(); width_line.addWidget(QLabel("字幕行宽")); width_line.addWidget(self.line_width)
        spacing_line=QHBoxLayout(); spacing_line.addWidget(QLabel("字间距")); spacing_line.addWidget(self.letter_spacing); spacing_line.addWidget(QLabel("词间距")); spacing_line.addWidget(self.word_spacing)
        line_spacing_line=QHBoxLayout(); line_spacing_line.addWidget(QLabel("行距")); line_spacing_line.addWidget(self.line_spacing); line_spacing_line.addStretch(1)
        effect_line=QHBoxLayout(); effect_line.addWidget(QLabel("左右")); effect_line.addWidget(self.highlight_padding); effect_line.addWidget(QLabel("上下")); effect_line.addWidget(self.highlight_padding_y)
        form.addRow("字幕模式",self.caption_mode); form.addRow("自由动画",free_line)
        form.addRow("书写语言", self.writing_language)
        form.addRow("", self.rtl_word_highlight)
        form.addRow("字体",font_line); form.addRow("自然分句",phrase_line); form.addRow("排版宽度",width_line); form.addRow("字幕间距",spacing_line)
        form.addRow("行间距",line_spacing_line); form.addRow("色块留白",effect_line); form.addRow("跟读动画",self.animation_speed)
        form.addRow("字幕位置",position_line); form.addRow("描边宽度",self.outline_width)
        batch_style_hint=QLabel("✓ 每个视频、匹配音频和文案组成独立任务；这里只批量套用字幕样式、蒙版 and 动画，最后统一批量导出。")
        batch_style_hint.setWordWrap(True); batch_style_hint.setStyleSheet("color:#67e8f9;background:#0b1830;padding:6px;border-radius:5px;")
        colors=QGridLayout(); self.text_color=QPushButton("文字 #FFFFFF"); self.outline_color=QPushButton("描边 #111827"); self.highlight_color=QPushButton("跟读背景 #8B5CF6")
        for index,button in enumerate((self.text_color,self.outline_color,self.highlight_color)):
            button.setMinimumHeight(32); button.clicked.connect(lambda checked=False,b=button:self.pick_color(b)); colors.addWidget(button,index//2,index%2)
        # 样式参数区：保证 SpinBox 列宽，避免被右侧预设列表挤扁导致数字残影
        style_controls=QWidget()
        style_controls.setMinimumWidth(360)
        style_controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        style_controls_layout=QVBoxLayout(style_controls); style_controls_layout.setContentsMargins(0,0,0,0); style_controls_layout.setSpacing(7)
        compact_style_grid=QGridLayout()
        compact_style_grid.setHorizontalSpacing(10); compact_style_grid.setVerticalSpacing(8)
        compact_rows=(
            ("字幕模式",self.caption_mode,"自由动画",self.free_animation),
            ("每屏时长",self.free_page_seconds,"书写语言",self.writing_language),
            ("字体",self.font,"字号",self.font_size),
            ("每句词数",self.max_words,"每行字符",self.line_length),
            ("字幕行宽",self.line_width,"跟读动画",self.animation_speed),
            ("字间距",self.letter_spacing,"词间距",self.word_spacing),
            ("行距",self.line_spacing,"描边宽度",self.outline_width),
            ("色块左右",self.highlight_padding,"色块上下",self.highlight_padding_y),
            ("字幕位置",self.position,"位置边距",self.margin_v),
        )
        for row,(left_label,left_control,right_label,right_control) in enumerate(compact_rows):
            left_lab = QLabel(left_label)
            right_lab = QLabel(right_label)
            left_lab.setMinimumWidth(56)
            right_lab.setMinimumWidth(56)
            compact_style_grid.addWidget(left_lab, row, 0)
            compact_style_grid.addWidget(left_control, row, 1)
            compact_style_grid.addWidget(right_lab, row, 2)
            compact_style_grid.addWidget(right_control, row, 3)
        compact_style_grid.addWidget(self.rtl_word_highlight,len(compact_rows),0,1,4)
        # 两列控件区有最小宽度，防止 Win11 高 DPI 下被压到裁字
        compact_style_grid.setColumnMinimumWidth(1, 110)
        compact_style_grid.setColumnMinimumWidth(3, 110)
        compact_style_grid.setColumnStretch(1, 1)
        compact_style_grid.setColumnStretch(3, 1)
        style_controls_layout.addLayout(compact_style_grid)
        style_controls_layout.addWidget(batch_style_hint)
        style_controls_layout.addLayout(colors)
        style_controls_layout.addStretch()
        preset_panel=QWidget(); preset_panel.setMinimumWidth(150); preset_panel.setMaximumWidth(180)
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
        preset_panel.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.preset_list_widget.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.preset_list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        preset_list.addWidget(self.preset_list_widget, 1)
        pg.addWidget(style_controls,1); pg.addWidget(preset_panel)
        settings_layout.addWidget(preset_group)

        # 🎵 5. 音频与背景音乐
        audio_group = QGroupBox("🎵 5. 音频与背景音乐")
        audio_layout = QVBoxLayout(audio_group); audio_layout.setContentsMargins(10,12,10,10); audio_layout.setSpacing(7)
        audio_form = QFormLayout(); audio_form.setVerticalSpacing(9); audio_form.setHorizontalSpacing(8)
        self.audio_match_label=QLabel("配音匹配")
        self.audio_match_mode.setCurrentText("自动匹配（同名优先，其次按队列）")
        self.audio_match_label.setParent(self); self.audio_match_label.hide()
        self.audio_match_mode.setParent(self); self.audio_match_mode.hide()
        audio_form.addRow("声音合成方式", self.audio_mode)
        bgm_picker = QHBoxLayout()
        bgm_btn = QPushButton("浏览…"); bgm_btn.clicked.connect(self._choose_bgm_folder)
        bgm_picker.addWidget(self.bgm_dir_input); bgm_picker.addWidget(bgm_btn)
        bgm_widget = QWidget(); bgm_widget.setLayout(bgm_picker)
        # 来源统一由左侧“添加背景音乐”页顶部选择，避免重复出现第二个路径框。
        bgm_widget.setParent(self)
        bgm_widget.hide()
        audio_form.addRow("音轨音量", audio_volume_line)
        audio_form.addRow("音轨淡化", self.audio_fade_mode)
        audio_form.addRow("淡化时长", fade_time_line)
        audio_layout.addLayout(audio_form)
        self.audio_form=audio_form
        settings_layout.addWidget(audio_group)
        self.audio_group = audio_group

        # ⚙️ 8. 运行与编码加速
        hardware_group = QGroupBox("⚙️ 9. 运行与编码加速")
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
        self.layer_text_font=QComboBox(); self.layer_text_font.addItems(QFontDatabase.families())
        if self.layer_text_font.findText("Microsoft YaHei")<0:
            self.layer_text_font.insertItem(0,"Microsoft YaHei")
        self.layer_text_font.setCurrentText("Microsoft YaHei")
        self.layer_text_size=QSpinBox(); self.layer_text_size.setRange(12,220); self.layer_text_size.setValue(58)
        self.layer_text_color=QPushButton("文字颜色 #FFFFFF"); self.layer_text_color.clicked.connect(self._pick_layer_text_color)
        self.layer_text_outline_color=QPushButton("描边颜色 #111111")
        self.layer_text_outline_color.clicked.connect(self._pick_layer_text_outline_color)
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
        self.task_queue=DropTableWidget(0,4)
        self.task_queue.paths_dropped.connect(self._on_task_queue_dropped)
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
        self.proofread_btn=QPushButton("文案校对")
        self.proofread_btn.setToolTip(
            "粘贴无时间戳的原文案，与提取字幕对比；\n"
            "只替换文字、保留音频识别的时间戳。差异用红色标出。"
        )
        self.proofread_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #f59e0b, stop:1 #d97706); border-color:#fbbf24; color:white; font-weight:700; }"
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #fbbf24, stop:1 #f59e0b); }"
        )
        self.proofread_btn.clicked.connect(self._open_script_proofread_dialog)
        load_sidecar=QPushButton("载入 SRT…"); load_sidecar.clicked.connect(self.load_srt_file)
        timeline_actions.addWidget(self.extract_timeline_btn)
        timeline_actions.addWidget(self.extract_all_btn)
        timeline_actions.addWidget(self.fix_overlap_btn)
        timeline_actions.addWidget(self.proofread_btn)
        timeline_actions.addWidget(load_sidecar)
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
                # 🎬 7. 视频比例与分辨率/转场
        video_opts_group = QGroupBox("🎬 7. 视频比例、分辨率与延长/转场")
        video_opts_layout = QVBoxLayout(video_opts_group); video_opts_layout.setContentsMargins(10,12,10,10); video_opts_layout.setSpacing(7)
        video_opts_form = QFormLayout(); video_opts_form.setVerticalSpacing(9); video_opts_form.setHorizontalSpacing(8)
        self.aspect_ratio = QComboBox(); self.aspect_ratio.addItems(["原始比例", "16:9", "3:4", "1:1"])
        self.resolution = QComboBox(); self.resolution.addItems(["默认最高", "720p", "1080p", "2K", "4K"])
        self.video_extend_mode = QComboBox(); self.video_extend_mode.addItems(["不处理", "循环播放视频", "最后一帧延长/冻结", "速度拉伸（减速延长）"])
        self.transition_name = QComboBox()
        self.transition_name.addItems(merge_transition_labels())
        self.transition_duration = QDoubleSpinBox()
        self.transition_duration.setRange(0.10, 2.50)
        self.transition_duration.setSingleStep(0.05)
        self.transition_duration.setDecimals(2)
        self.transition_duration.setValue(0.50)
        self.transition_duration.setSuffix(" 秒")
        self.transition_duration.setMinimumWidth(96)
        self.transition_duration.setToolTip(
            "片段之间转场持续时长。切换转场类型时会填入该类型推荐默认值，可再手动改。"
            "实际时长不会超过最短片段的 45%，避免素材过短导致失败。"
        )
        self.aspect_ratio.setToolTip("分组合成与批量导出都会统一到此画面比例。")
        self.resolution.setToolTip("分组合成与批量导出都会统一到此分辨率。")
        self.video_extend_mode.setToolTip(
            "仅「开始批量导出」生效：当替换/混合音频比画面更长时，如何把视频拉长对齐音频。"
            "左侧「合成」多片段合并不使用此项。"
        )
        self.transition_name.setToolTip(
            "仅左侧「合成」且组内 ≥2 个片段时生效。\n"
            "达芬奇风格：交叉叠化 / Cross Dissolve / Crash Zoom / 平滑剪接（hblur 近似，非光流 AI）。\n"
            "「开始批量导出」不再做片段间转场。"
        )
        self.transition_name.currentTextChanged.connect(self._transition_name_changed)
        for combo in (self.aspect_ratio, self.resolution, self.video_extend_mode, self.transition_name):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8); combo.setMinimumWidth(0)
        video_opts_form.addRow("画面比例", self.aspect_ratio)
        video_opts_form.addRow("画面分辨率", self.resolution)
        video_opts_form.addRow("视频延长", self.video_extend_mode)
        video_opts_form.addRow("合并转场", self.transition_name)
        video_opts_form.addRow("转场时长", self.transition_duration)
        video_opts_layout.addLayout(video_opts_form)
        transition_title = QLabel("转场效果")
        transition_title.setStyleSheet("color:#7dd3fc;font-weight:700;margin-top:4px;")
        video_opts_layout.addWidget(transition_title)
        transition_grid = QGridLayout()
        transition_grid.setSpacing(5)
        self.transition_buttons = []
        transition_symbols = ("∅", "▧", "⇆", "◫", "↗", "↙", "⊕", "◉", "≋", "⌁", "◈", "▤")
        for index, transition_label in enumerate(merge_transition_labels()):
            transition_button = TransitionPresetButton(
                f"{transition_symbols[index % len(transition_symbols)]}\n{transition_label}",
                transition_label,
            )
            transition_button.setCheckable(True)
            transition_button.setMinimumHeight(50)
            transition_button.setToolTip(f"点击应用转场：{transition_label}")
            transition_button.clicked.connect(
                lambda checked=False, name=transition_label: self.transition_name.setCurrentText(name)
            )
            transition_grid.addWidget(transition_button, index // 3, index % 3)
            self.transition_buttons.append((transition_label, transition_button))
        video_opts_layout.addLayout(transition_grid)
        self.video_opts_group = video_opts_group
        self._transition_name_changed(self.transition_name.currentText())

        rename_group = QGroupBox("🏷️ 8. 自动重命名（使用文案标题）")
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

        rename_titles_hint = QLabel(
            "自定义标题列表（可选）：每行一个标题，按左侧队列顺序对应。"
            "填写后导出时优先使用此处标题；序号 / 前缀 / 日期 / 后缀仍按上方规则拼接。"
            "一批导出完成后会自动清空，下一批请重新粘贴文案（避免沿用上一批标题）。"
        )
        rename_titles_hint.setWordWrap(True)
        rename_titles_hint.setStyleSheet("color:#94a3b8;font-size:11px;")
        rename_layout.addWidget(rename_titles_hint)
        self.rename_custom_titles = QPlainTextEdit()
        self.rename_custom_titles.setPlaceholderText(
            "例如队列有 3 个视频时可粘贴：\n"
            "第一支成片标题\n"
            "第二支成片标题\n"
            "第三支成片标题\n"
            "（留空则仍自动提取文案标题；本批导出成功后会自动清空）"
        )
        self.rename_custom_titles.setMinimumHeight(88)
        self.rename_custom_titles.setMaximumHeight(160)
        rename_layout.addWidget(self.rename_custom_titles)
        
        # Add the jump button inside Section 7
        self.output_to_rename = QPushButton("👉 导入已生成成品并转到 [批量重命名] 板块")
        self.output_to_rename.setMinimumHeight(28)
        self.output_to_rename.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #6d28d9);
                border: 1px solid #a78bfa;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a78bfa, stop:1 #8b5cf6);
            }
        """)
        self.output_to_rename.clicked.connect(self._send_export_output_to_rename)
        rename_layout.addWidget(self.output_to_rename)

        # 设置页：左侧仅保留二级按钮，右侧直接显示配置，避免多层点击。
        left_settings_scroll = QScrollArea()
        left_settings_scroll.setWidgetResizable(True)
        left_settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_settings_body = QWidget()
        left_settings_layout = QHBoxLayout(left_settings_body)
        left_settings_layout.setContentsMargins(4,4,4,4)
        left_settings_layout.setSpacing(7)
        left_setting_nav_widget=QWidget(); left_setting_nav_widget.setFixedWidth(124)
        left_setting_nav = QVBoxLayout(left_setting_nav_widget)
        left_setting_nav.setContentsMargins(2,2,2,2)
        self.left_setting_buttons = []
        self.left_settings_stack = QStackedWidget()
        self._left_setting_keys = {"batch":0, "encoding":1, "output":2}
        for index, title in enumerate(("批量上传", "编码", "输出与运行")):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, i=index:self._show_left_setting_index(i))
            left_setting_nav.addWidget(button)
            self.left_setting_buttons.append(button)
        left_setting_nav.addStretch()
        left_settings_layout.addWidget(left_setting_nav_widget)
        left_setting_separator=QFrame(); left_setting_separator.setFrameShape(QFrame.Shape.VLine)
        left_setting_separator.setStyleSheet("color:#334155;")
        left_settings_layout.addWidget(left_setting_separator)

        upload_group = QGroupBox("☁ 上传与填写表格")
        upload_layout = QVBoxLayout(upload_group)
        upload_layout.setContentsMargins(9,11,9,8)
        upload_layout.setSpacing(7)
        upload_layout.addWidget(self.cloud_sync_check)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("同步方案"))
        profile_row.addWidget(self.cloud_sync_profile, 1)
        profile_row.addWidget(configure_sync)
        upload_layout.addLayout(profile_row)
        upload_hint = QLabel("授权、Drive 文件夹、Google Sheets 与填写字段都在这里统一配置。")
        upload_hint.setWordWrap(True)
        upload_hint.setStyleSheet("color:#94a3b8;font-size:11px;")
        upload_layout.addWidget(upload_hint)
        open_rename_workspace = QPushButton("打开完整批量重命名工作区")
        open_rename_workspace.clicked.connect(lambda:self.navigate_requested.emit(4))
        upload_pipeline = QPushButton("打开上传 / 填表流水线")
        upload_pipeline.clicked.connect(lambda:self.navigate_requested.emit(8))
        batch_page = QWidget()
        batch_layout = QVBoxLayout(batch_page); batch_layout.setContentsMargins(0,0,0,0)
        batch_layout.addWidget(rename_group)
        batch_layout.addWidget(open_rename_workspace)
        batch_layout.addWidget(upload_group)
        batch_layout.addWidget(upload_pipeline)
        batch_layout.addStretch()

        encoding_page = QWidget()
        encoding_page_layout = QVBoxLayout(encoding_page)
        encoding_page_layout.setContentsMargins(0,0,0,0)
        encoding_page_layout.addWidget(hardware_group)
        encoding_page_layout.addStretch()

        output_page = QWidget()
        self.output_settings_layout = QVBoxLayout(output_page)
        self.output_settings_layout.setContentsMargins(0,0,0,0)

        for page_widget in (batch_page, encoding_page, output_page):
            page_scroll = QScrollArea()
            page_scroll.setWidgetResizable(True)
            page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page_scroll.setWidget(page_widget)
            self.left_settings_stack.addWidget(page_scroll)
        left_settings_layout.addWidget(self.left_settings_stack,1)
        self._show_left_setting_index(0)
        left_setting_nav_widget.hide()
        left_setting_separator.hide()
        left_settings_scroll.setWidget(left_settings_body)
        source_stack.addWidget(left_settings_scroll)
        settings_button = QPushButton("设置")
        settings_button.setCheckable(True)
        settings_button.setFixedSize(130,42)
        settings_button.setToolTip("批量重命名、上传与填写表格")
        settings_button.clicked.connect(lambda checked=False:self._show_source_tool(3))
        self.source_tool_buttons.append(settings_button)

        # 水印是独立编辑页面；蒙版移到右侧字幕预设下方。
        watermark_editor=QScrollArea(); watermark_editor.setWidgetResizable(True)
        watermark_editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        watermark_body=QWidget(); watermark_editor_layout=QVBoxLayout(watermark_body)
        watermark_heading=QLabel("水印编辑")
        watermark_heading.setStyleSheet("font-size:18px;font-weight:800;color:#f8fafc;")
        watermark_editor_layout.addWidget(watermark_heading)
        watermark_editor_layout.addWidget(QLabel("添加图片后，可分别设置位置、大小、透明度和边距。"))
        watermark_file_row=QHBoxLayout()
        choose_watermark.setText("添加图片")
        watermark_file_row.addWidget(choose_watermark)
        watermark_file_row.addWidget(self.company_watermark,1)
        watermark_file_row.addWidget(clear_watermark)
        watermark_file_row.addWidget(clear_all_watermarks)
        watermark_editor_layout.addLayout(watermark_file_row)
        watermark_editor_layout.addWidget(self.watermark_table,1)
        self.group_burn_watermark.setText("合成时启用水印")
        watermark_editor_layout.addWidget(self.group_burn_watermark)
        self.proj_burn_watermark.setParent(self)
        self.proj_burn_watermark.hide()
        watermark_mode_editor=QHBoxLayout()
        watermark_mode_editor.addWidget(QLabel("覆盖方式")); watermark_mode_editor.addWidget(self.watermark_mode,1)
        watermark_editor_layout.addLayout(watermark_mode_editor)
        watermark_control_editor=QHBoxLayout()
        watermark_control_editor.addWidget(QLabel("位置")); watermark_control_editor.addWidget(self.watermark_position,1)
        watermark_control_editor.addWidget(QLabel("宽度")); watermark_control_editor.addWidget(self.watermark_width)
        watermark_control_editor.addWidget(QLabel("透明度")); watermark_control_editor.addWidget(self.watermark_opacity)
        watermark_control_editor.addWidget(QLabel("边距")); watermark_control_editor.addWidget(self.watermark_margin)
        watermark_editor_layout.addLayout(watermark_control_editor)
        watermark_editor_layout.addStretch()
        watermark_editor.setWidget(watermark_body)
        source_stack.addWidget(watermark_editor)

        # “添加背景音乐”是独立编辑入口，统一承载原音频页的全部能力。
        bgm_editor=QScrollArea(); bgm_editor.setWidgetResizable(True)
        bgm_editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bgm_body=QWidget(); bgm_editor_layout=QVBoxLayout(bgm_body)
        bgm_heading=QLabel("背景音乐与音频")
        bgm_heading.setStyleSheet("font-size:18px;font-weight:800;color:#f8fafc;")
        bgm_editor_layout.addWidget(bgm_heading)
        bgm_editor_layout.addWidget(QLabel(
            "可固定使用单个音频，也可从文件夹随机匹配并随机截取起始位置。"
        ))
        bgm_source_group=QGroupBox("音频来源")
        bgm_source_layout=QVBoxLayout(bgm_source_group)
        bgm_source_buttons=QHBoxLayout()
        choose_fixed_bgm=QPushButton("选择音频文件")
        choose_fixed_bgm.setObjectName("primary")
        choose_fixed_bgm.clicked.connect(self._choose_bgm_file)
        choose_bgm_folder=QPushButton("选择音频文件夹")
        choose_bgm_folder.clicked.connect(self._choose_bgm_folder)
        bgm_source_buttons.addWidget(choose_fixed_bgm)
        bgm_source_buttons.addWidget(choose_bgm_folder)
        bgm_source_layout.addLayout(bgm_source_buttons)
        self.bgm_source_display=QLineEdit()
        self.bgm_source_display.setReadOnly(True)
        self.bgm_source_display.setPlaceholderText("尚未选择音频文件或文件夹")
        bgm_source_layout.addWidget(self.bgm_source_display)
        bgm_mode_row=QHBoxLayout()
        self.bgm_enabled=QCheckBox()
        self.bgm_enabled.setChecked(False)
        self.bgm_enabled.toggled.connect(self._bgm_enabled_changed)
        self.bgm_enabled.setParent(self); self.bgm_enabled.hide()
        bgm_mode_row.addWidget(QLabel("BGM 选择方式"))
        self.bgm_selection_mode=QComboBox()
        self.bgm_selection_mode.addItems(("固定使用选中的音频", "随机从文件夹选择并随机截取"))
        self.bgm_selection_mode.currentTextChanged.connect(self._bgm_selection_mode_changed)
        bgm_mode_row.addWidget(self.bgm_selection_mode,1)
        bgm_source_layout.addLayout(bgm_mode_row)
        bgm_editor_layout.addWidget(bgm_source_group)

        bgm_preview_group=QGroupBox("起始点与试听")
        bgm_preview_layout=QVBoxLayout(bgm_preview_group)
        bgm_play_row=QHBoxLayout()
        self.audio_play_btn.setText("试听背景音乐")
        bgm_play_row.addWidget(self.audio_play_btn)
        bgm_play_row.addWidget(self.audio_seek,1)
        bgm_play_row.addWidget(self.audio_time)
        bgm_preview_layout.addLayout(bgm_play_row)
        bgm_start_row=QHBoxLayout()
        bgm_start_row.addWidget(QLabel("固定起始点"))
        bgm_start_row.addWidget(self.audio_start_seek,1)
        bgm_start_row.addWidget(self.audio_start_time)
        bgm_start_row.addWidget(self.audio_start_preview)
        bgm_preview_layout.addLayout(bgm_start_row)
        bgm_editor_layout.addWidget(bgm_preview_group)
        audio_group.setTitle("声音合成")
        bgm_editor_layout.addWidget(audio_group)
        bgm_editor_layout.addStretch()
        bgm_editor.setWidget(bgm_body)
        source_stack.addWidget(bgm_editor)
        self._audio_mode_changed(self.audio_mode.currentText())

        # 固定通用工具栏：顺序和位置不随任务页切换。
        for mode,button in enumerate(self.source_tool_buttons[:3]):
            button.setProperty("sourceMode",mode)
        self.group_watermark_button.setText("水印")
        self.group_watermark_button.setCheckable(True)
        self.group_watermark_button.setProperty("sourceMode",4)
        self.group_watermark_button.clicked.disconnect()
        self.group_watermark_button.clicked.connect(lambda checked=False:self._show_source_tool(4))
        self.group_bgm_button.clicked.disconnect()
        self.group_bgm_button.setCheckable(True)
        self.group_bgm_button.setProperty("sourceMode",5)
        self.group_bgm_button.clicked.connect(lambda checked=False:self._show_source_tool(5))
        self.group_merge_start.clicked.disconnect()
        self.group_merge_start.clicked.connect(self._run_context_synthesis)
        self.group_merge_stop.clicked.disconnect()
        self.group_merge_stop.clicked.connect(self._stop_context_synthesis)
        settings_button.setProperty("sourceMode",3)
        self.source_tool_buttons.insert(3,self.group_watermark_button)
        self.source_tool_buttons.insert(4,self.group_bgm_button)
        for position,button in enumerate((
            self.group_watermark_button,
            self.group_bgm_button,
            self.group_merge_start,
            self.group_merge_selected,
            self.group_merge_stop,
            settings_button,
        ),start=3):
            button.setFixedSize(130,42)
            source_tools.insertWidget(position,button)
        for offset, button in enumerate(self.left_setting_buttons):
            left_setting_nav.removeWidget(button)
            button.setFixedSize(130,36)
            button.setText(("└ 批量上传", "└ 编码", "└ 输出与运行")[offset])
            button.clicked.disconnect()
            button.clicked.connect(
                lambda checked=False, i=offset: (
                    self._show_source_tool(3),
                    self._show_left_setting_index(i),
                )
            )
            source_tools.insertWidget(9 + offset, button)
        self.group_action_panel.hide()
        self.project_action_panel.hide()

        # 字幕识别和提取出的时间戳放在右侧“字幕预设”顶部。
        caption_tools_group = QGroupBox("字幕识别")
        caption_tools_layout = QVBoxLayout(caption_tools_group)
        caption_provider_row = QHBoxLayout()
        caption_provider_row.addWidget(QLabel("服务"))
        caption_provider_row.addWidget(self.provider,1)
        caption_tools_layout.addLayout(caption_provider_row)
        caption_tools_layout.addWidget(self.combination_label)
        caption_tools_layout.addWidget(self.timeline_source_label)
        caption_buttons = QHBoxLayout()
        for button in (
            self.extract_timeline_btn, self.extract_all_btn, self.fix_overlap_btn,
            self.proofread_btn, load_sidecar,
        ):
            caption_buttons.addWidget(button)
        caption_tools_layout.addLayout(caption_buttons)
        self.timeline_timestamp_view=QPlainTextEdit()
        self.timeline_timestamp_view.setReadOnly(False)
        self.timeline_timestamp_view.setMinimumHeight(150)
        self.timeline_timestamp_view.setPlaceholderText(
            "提取字幕后可直接修改时间戳或文字；修改会同步到底部字幕轨道和最终导出。"
        )
        self.timeline_timestamp_view.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;")
        self.override_text.textChanged.connect(self._sync_timeline_timestamp_view)
        self.timeline_timestamp_view.textChanged.connect(
            self._timeline_timestamp_editor_changed
        )
        self.override_text.setParent(self); self.override_text.hide()
        self.source_proofread.setParent(self); self.source_proofread.hide()
        revise_group.hide()

        queue_title.hide(); self.videos.hide()
        vg.insertWidget(0,self.task_queue,1)
        self._make_collapsible(rename_group,"automatic_rename",False)
        self._make_collapsible(hardware_group,"hardware_acceleration",False)

        mask_group=QGroupBox("蒙版")
        mask_group_layout=QVBoxLayout(mask_group)
        mask_group_layout.addWidget(self.layer_list,1)
        mask_actions=QHBoxLayout()
        add_mask.setText("添加蒙版")
        for button in (add_mask,add_text,delete_layer,move_up,move_down):
            mask_actions.addWidget(button)
        mask_group_layout.addLayout(mask_actions)
        mask_editor_grid=QGridLayout()
        mask_editor_grid.addWidget(self.mask_color,0,0,1,2)
        mask_editor_grid.addWidget(QLabel("透明度"),0,2)
        mask_editor_grid.addWidget(self.mask_opacity,0,3,1,2)
        mask_editor_grid.addWidget(self.mask_opacity_value,0,5)
        for index,(label,control) in enumerate((
            ("左",self.mask_x),("上",self.mask_y),("宽",self.mask_w),("高",self.mask_h)
        )):
            row=1+index//2; column=(index%2)*3
            mask_editor_grid.addWidget(QLabel(label),row,column)
            mask_editor_grid.addWidget(control,row,column+1,1,2)
        mask_editor_grid.addWidget(QLabel("圆角"),3,0)
        mask_editor_grid.addWidget(self.mask_radius,3,1,1,2)
        mask_group_layout.addLayout(mask_editor_grid)
        mask_quick=QGridLayout(); mask_quick.addWidget(QLabel("快速定位"),0,0,2,1)
        for index,button in enumerate(self.mask_quick_buttons):
            mask_quick.addWidget(button,index//2,index%2+1)
        mask_group_layout.addLayout(mask_quick)
        self.text_layer_editor_group=QGroupBox("文字图层编辑")
        text_layer_editor_layout=QGridLayout(self.text_layer_editor_group)
        text_layer_editor_layout.setHorizontalSpacing(7)
        text_layer_editor_layout.setVerticalSpacing(6)
        text_layer_editor_layout.addWidget(QLabel("文字内容"),0,0)
        text_layer_editor_layout.addWidget(self.layer_text,0,1,1,5)
        text_layer_editor_layout.addWidget(QLabel("字体"),1,0)
        text_layer_editor_layout.addWidget(self.layer_text_font,1,1,1,2)
        text_layer_editor_layout.addWidget(QLabel("字号"),1,3)
        text_layer_editor_layout.addWidget(self.layer_text_size,1,4,1,2)
        text_layer_editor_layout.addWidget(self.layer_text_color,2,0,1,2)
        text_layer_editor_layout.addWidget(self.layer_text_outline_color,2,2,1,2)
        text_layer_editor_layout.addWidget(QLabel("描边宽度"),2,4)
        text_layer_editor_layout.addWidget(self.layer_text_outline,2,5)
        text_layer_editor_layout.addWidget(QLabel("透明度"),3,0)
        text_layer_editor_layout.addWidget(self.layer_text_opacity,3,1)
        text_layer_editor_layout.addWidget(QLabel("横向位置"),3,2)
        text_layer_editor_layout.addWidget(self.layer_text_x,3,3)
        text_layer_editor_layout.addWidget(QLabel("纵向位置"),3,4)
        text_layer_editor_layout.addWidget(self.layer_text_y,3,5)
        text_layer_editor_layout.addWidget(QLabel("快速定位"),4,0)
        for index,button in enumerate(self.text_quick_buttons):
            text_layer_editor_layout.addWidget(button,4,index+1)

        # 右侧六个独立入口；按钮区与配置区之间保持清晰分割线。
        right_panel = QWidget()
        right_panel_layout = QHBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(0,0,0,0)
        right_rail = QWidget(); right_rail.setFixedWidth(118)
        right_rail_layout = QVBoxLayout(right_rail); right_rail_layout.setContentsMargins(3,3,3,3)
        self.right_settings_stack = QStackedWidget()
        self.right_setting_buttons = []
        recognition_page_content=QWidget()
        recognition_page_layout=QVBoxLayout(recognition_page_content)
        recognition_page_layout.addWidget(caption_tools_group)
        recognition_page_layout.addWidget(self.timeline_timestamp_view,1)

        style_page_content=QWidget(); style_page_layout=QVBoxLayout(style_page_content)
        style_controls.setMaximumWidth(16777215); style_page_layout.addWidget(style_controls); style_page_layout.addStretch()

        preset_page_content=QWidget(); preset_page_layout=QVBoxLayout(preset_page_content)
        preset_panel.setMaximumWidth(16777215)
        preset_page_layout.addWidget(preset_panel,1)

        mask_page_content=QWidget(); mask_page_layout=QVBoxLayout(mask_page_content)
        mask_page_layout.addWidget(mask_group)
        mask_page_layout.addWidget(self.text_layer_editor_group)
        mask_page_layout.addStretch()

        video_settings_group=QGroupBox("视频设置")
        video_settings_layout=QFormLayout(video_settings_group)
        video_settings_layout.addRow("画面比例", self.aspect_ratio)
        video_settings_layout.addRow("画面分辨率", self.resolution)
        video_settings_layout.addRow("视频延长", self.video_extend_mode)
        video_settings_page_content=QWidget()
        video_settings_page_layout=QVBoxLayout(video_settings_page_content)
        video_settings_page_layout.addWidget(video_settings_group)
        video_settings_page_layout.addStretch()

        video_effects_group=QGroupBox("转场预设")
        video_effects_layout=QVBoxLayout(video_effects_group)
        self.transition_selected_label=QLabel("当前批量效果：无转场")
        self.transition_selected_label.setStyleSheet(
            "background:#0b2a4a;color:#7dd3fc;border:1px solid #38bdf8;"
            "border-radius:5px;padding:7px 10px;font-weight:800;"
        )
        video_effects_layout.addWidget(self.transition_selected_label)
        transition_duration_row=QHBoxLayout()
        transition_duration_row.addWidget(QLabel("转场时长"))
        transition_duration_row.addWidget(self.transition_duration,1)
        video_effects_layout.addLayout(transition_duration_row)
        transition_hint=QLabel(
            "单击：设置批量统一转场。拖到视频轨道或在轨道右键：添加局部转场。"
        )
        transition_hint.setWordWrap(True)
        transition_hint.setStyleSheet("color:#7dd3fc;font-size:11px;")
        video_effects_layout.addWidget(transition_hint)
        transition_preset_grid=QGridLayout()
        transition_preset_grid.setSpacing(5)
        for index, (_name, button) in enumerate(self.transition_buttons):
            button.setStyleSheet(
                "QPushButton:checked{background:#2563eb;color:white;"
                "border:2px solid #93c5fd;font-weight:800;}"
            )
            transition_preset_grid.addWidget(button,index//3,index%3)
        video_effects_layout.addLayout(transition_preset_grid)

        # —— 动态追踪 / 追踪模糊（画面轨独立，不改字幕时间）——
        track_group = QGroupBox("动态追踪 / 追踪模糊")
        track_layout = QVBoxLayout(track_group)
        track_tip = QLabel(
            "用法：播放到目标出现的位置 → 填写框选区域（画面百分比）→ 开始追踪。\n"
            "「追踪模糊」导出时对跟随区域做高斯模糊（适合打码人脸/车牌）。\n"
            "与专业剪辑一致：字幕轨与音视频分离，改字幕不会推动 BGM/原声。"
        )
        track_tip.setWordWrap(True)
        track_tip.setStyleSheet("color:#7dd3fc;font-size:11px;")
        track_layout.addWidget(track_tip)
        track_grid = QGridLayout()
        self.track_x = QDoubleSpinBox(); self.track_x.setRange(0, 95); self.track_x.setValue(35); self.track_x.setSuffix(" %")
        self.track_y = QDoubleSpinBox(); self.track_y.setRange(0, 95); self.track_y.setValue(25); self.track_y.setSuffix(" %")
        self.track_w = QDoubleSpinBox(); self.track_w.setRange(2, 80); self.track_w.setValue(20); self.track_w.setSuffix(" %")
        self.track_h = QDoubleSpinBox(); self.track_h.setRange(2, 80); self.track_h.setValue(20); self.track_h.setSuffix(" %")
        self.track_duration = QSpinBox(); self.track_duration.setRange(0, 600); self.track_duration.setValue(8); self.track_duration.setSuffix(" 秒")
        self.track_duration.setToolTip("0 = 从当前播放头追到片尾")
        self.track_blur = QSpinBox(); self.track_blur.setRange(3, 48); self.track_blur.setValue(18); self.track_blur.setSuffix(" 强度")
        self.track_mode = QComboBox(); self.track_mode.addItems(["追踪模糊（打码）", "追踪标签（仅路径+文字）"])
        self.track_label = QLineEdit(); self.track_label.setPlaceholderText("可选标签文字（如「马赛克」）")
        for spin in (self.track_x, self.track_y, self.track_w, self.track_h, self.track_duration, self.track_blur):
            _configure_numeric_spin(spin, min_width=96)
        track_grid.addWidget(QLabel("左 X"), 0, 0); track_grid.addWidget(self.track_x, 0, 1)
        track_grid.addWidget(QLabel("上 Y"), 0, 2); track_grid.addWidget(self.track_y, 0, 3)
        track_grid.addWidget(QLabel("宽 W"), 1, 0); track_grid.addWidget(self.track_w, 1, 1)
        track_grid.addWidget(QLabel("高 H"), 1, 2); track_grid.addWidget(self.track_h, 1, 3)
        track_grid.addWidget(QLabel("时长"), 2, 0); track_grid.addWidget(self.track_duration, 2, 1)
        track_grid.addWidget(QLabel("模糊"), 2, 2); track_grid.addWidget(self.track_blur, 2, 3)
        track_grid.addWidget(QLabel("模式"), 3, 0); track_grid.addWidget(self.track_mode, 3, 1, 1, 3)
        track_grid.addWidget(QLabel("标签"), 4, 0); track_grid.addWidget(self.track_label, 4, 1, 1, 3)
        track_layout.addLayout(track_grid)
        track_btns = QHBoxLayout()
        self.track_run_btn = QPushButton("绘制区域并追踪")
        self.track_run_btn.setToolTip("在当前播放帧上拖拽框选目标，然后自动跟踪并可选追踪模糊")
        self.track_run_btn.clicked.connect(self._run_motion_track)
        self.track_delete_btn = QPushButton("删除选中")
        self.track_delete_btn.clicked.connect(self._delete_selected_motion_track)
        self.track_clear_btn = QPushButton("清空全部")
        self.track_clear_btn.clicked.connect(self._clear_motion_tracks)
        track_btns.addWidget(self.track_run_btn)
        track_btns.addWidget(self.track_delete_btn)
        track_btns.addWidget(self.track_clear_btn)
        track_layout.addLayout(track_btns)
        self.track_list = QListWidget()
        self.track_list.setMinimumHeight(90)
        self.track_list.setToolTip("导出时会应用列表中的追踪模糊到成品画面")
        track_layout.addWidget(self.track_list)
        self.track_status = QLabel("当前无追踪路径")
        self.track_status.setStyleSheet("color:#94a3b8;font-size:11px;")
        track_layout.addWidget(self.track_status)

        effects_page_content=QWidget(); effects_page_layout=QVBoxLayout(effects_page_content)
        effects_page_layout.addWidget(video_effects_group)
        effects_page_layout.addWidget(track_group)
        effects_page_layout.addStretch()

        # 图片之间的转场与视频片段转场使用相同 FFmpeg 预设，但保持独立默认值。
        # 两个图片工作流共享同一份右侧控制，避免分别维护两套选项。
        self.proj_img_transition.currentTextChanged.connect(self.img_transition.setCurrentText)
        self.img_transition.currentTextChanged.connect(self.proj_img_transition.setCurrentText)
        self.proj_transition_dur.valueChanged.connect(self.img_trans_dur.setValue)
        self.img_trans_dur.valueChanged.connect(self.proj_transition_dur.setValue)
        self.proj_img_animation.currentTextChanged.connect(self.img_animation.setCurrentText)
        self.img_animation.currentTextChanged.connect(self.proj_img_animation.setCurrentText)
        for form_layout, controls in (
            (img_settings,(self.img_transition,self.img_trans_dur,self.img_animation)),
            (proj_settings_form,(self.proj_img_transition,self.proj_transition_dur,self.proj_img_animation)),
        ):
            for control in controls:
                label=form_layout.labelForField(control)
                if label is not None:
                    label.hide()
                control.hide()

        image_effects_page_content=QWidget()
        image_effects_page_layout=QVBoxLayout(image_effects_page_content)
        image_effects_group=QGroupBox("图片转场预设")
        image_effects_layout=QVBoxLayout(image_effects_group)
        self.image_transition_selected_label=QLabel("当前图片效果：无转场")
        self.image_transition_selected_label.setStyleSheet(
            "background:#0b2a4a;color:#7dd3fc;border:1px solid #38bdf8;"
            "border-radius:5px;padding:7px 10px;font-weight:800;"
        )
        image_effects_layout.addWidget(self.image_transition_selected_label)
        image_duration_row=QHBoxLayout()
        image_duration_row.addWidget(QLabel("转场时长"))
        image_duration_row.addWidget(self.proj_transition_dur,1)
        image_effects_layout.addLayout(image_duration_row)
        image_animation_row=QHBoxLayout()
        image_animation_row.addWidget(QLabel("图片动画"))
        image_animation_row.addWidget(self.proj_img_animation,1)
        self.proj_transition_dur.show()
        self.proj_img_animation.show()
        image_effects_layout.addLayout(image_animation_row)
        image_effects_hint=QLabel("单击预设后，幻灯片与图文配音成片统一调用该图片转场。")
        image_effects_hint.setWordWrap(True)
        image_effects_hint.setStyleSheet("color:#7dd3fc;font-size:11px;")
        image_effects_layout.addWidget(image_effects_hint)
        image_transition_grid=QGridLayout(); image_transition_grid.setSpacing(5)
        self.image_transition_buttons=[]
        for index,transition_label in enumerate(merge_transition_labels()):
            image_button=QPushButton(
                f"{transition_symbols[index % len(transition_symbols)]}\n{transition_label}"
            )
            image_button.setCheckable(True)
            image_button.setMinimumHeight(50)
            image_button.setStyleSheet(
                "QPushButton:checked{background:#2563eb;color:white;"
                "border:2px solid #93c5fd;font-weight:800;}"
            )
            image_button.clicked.connect(
                lambda checked=False,name=transition_label:
                self.proj_img_transition.setCurrentText(name)
            )
            image_transition_grid.addWidget(image_button,index//3,index%3)
            self.image_transition_buttons.append((transition_label,image_button))
        image_effects_layout.addLayout(image_transition_grid)
        image_effects_page_layout.addWidget(image_effects_group)
        image_effects_page_layout.addStretch()
        self.proj_img_transition.currentTextChanged.connect(self._image_transition_name_changed)
        self._image_transition_name_changed(self.proj_img_transition.currentText())

        for page_content in (
            recognition_page_content,
            style_page_content,
            preset_page_content,
            mask_page_content,
            video_settings_page_content,
            effects_page_content,
            image_effects_page_content,
        ):
            page_scroll = QScrollArea()
            page_scroll.setWidgetResizable(True)
            page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page_scroll.setWidget(page_content)
            self.right_settings_stack.addWidget(page_scroll)
        for index, title in enumerate((
            "字幕识别", "字幕设置", "字幕预设", "蒙版", "视频设置", "视频效果", "图片效果"
        )):
            button=QPushButton(title); button.setCheckable(True); button.setMinimumHeight(44)
            button.clicked.connect(lambda checked=False,i=index:self._show_right_setting(i))
            right_rail_layout.addWidget(button)
            self.right_setting_buttons.append(button)
        right_rail_layout.addStretch()
        right_panel_layout.addWidget(right_rail)
        right_separator=QFrame(); right_separator.setFrameShape(QFrame.Shape.VLine)
        right_separator.setStyleSheet("color:#334155;")
        right_panel_layout.addWidget(right_separator)
        right_panel_layout.addWidget(self.right_settings_stack,1)
        self._show_right_setting(0)

        self._wheel_redirector = ScrollRedirectFilter(right_panel)
        for widget_class in (QComboBox, QSpinBox, QSlider):
            for widget in self.findChildren(widget_class):
                widget.installEventFilter(self._wheel_redirector)
                widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

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
        self.cloud_sync_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.cloud_sync_hint.setOpenExternalLinks(True)
        self.cloud_sync_hint.setWordWrap(True); self.cloud_sync_hint.setStyleSheet("color:#7dd3fc;font-size:11px;")
        self.cloud_sync_check.toggled.connect(self._update_cloud_sync_hint)
        self.cloud_sync_profile.currentTextChanged.connect(self._update_cloud_sync_hint)
        og.addWidget(self.cloud_sync_hint)
        self.log_status=QLabel(); self.log_status.hide()
        self.log=QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        self.log.setPlaceholderText("本板块执行日志会显示在这里…")
        self.log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;line-height:1.35;")
        og.addWidget(self.log,1)
        log_hint=QLabel("运行记录同时写入顶部“查看软件日志”。")
        log_hint.setStyleSheet("color:#64748b;font-size:11px;")
        og.addWidget(log_hint)
        self.output_settings_layout.addWidget(output_group,1)

        # Proportional sizes based on screen resolution
        screen = QApplication.primaryScreen()
        screen_width = screen.geometry().width() if screen else 1920
        left_w = int(screen_width * 0.23)
        right_w = screen_width - left_w
        preview_w = int(right_w * 0.55)
        settings_w = right_w - preview_w

        # 右侧工作设置区：预览与全部设置；下方独立放置 Canva 风格多轨时间轴。
        work_group=QGroupBox("工作设置区 · 实时预览与字幕设计")
        work_group_layout=QVBoxLayout(work_group); work_group_layout.setContentsMargins(7,10,7,7)
        work_splitter=QSplitter(Qt.Orientation.Horizontal); work_splitter.setChildrenCollapsible(False)
        center.setMinimumWidth(380); right_panel.setMinimumWidth(400)
        work_splitter.addWidget(center); work_splitter.addWidget(right_panel); work_splitter.setSizes([preview_w,settings_w])
        work_splitter.setStretchFactor(0, 3)
        work_splitter.setStretchFactor(1, 2)
        work_group_layout.addWidget(work_splitter)
        workspace.addWidget(left); workspace.addWidget(work_group); workspace.setSizes([left_w,right_w])
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 3)

        try:
            timeline_ffmpeg = self.find_ffmpeg()
        except Exception:
            timeline_ffmpeg = "ffmpeg"
        self.canva_timeline = CanvaTimelinePanel(timeline_ffmpeg)
        self.canva_timeline.set_transition_catalog(
            merge_transition_labels(), int(self.transition_duration.value() * 1000)
        )
        self.transition_duration.valueChanged.connect(
            lambda value: self.canva_timeline.set_transition_duration(int(value * 1000))
        )
        self.canva_timeline.srtChanged.connect(self._timeline_track_srt_changed)
        self.canva_timeline.seekRequested.connect(self._seek_preview)
        self.canva_timeline.timelineEdited.connect(self._timeline_edit_changed)
        self.canva_timeline.originalAudioChanged.connect(self._timeline_original_audio_changed)
        self.canva_timeline.bgmVolumeChanged.connect(self.background_volume.setValue)
        self.background_volume.valueChanged.connect(self.canva_timeline.volume.setValue)
        timeline_splitter = QSplitter(Qt.Orientation.Vertical)
        timeline_splitter.setChildrenCollapsible(False)
        timeline_splitter.addWidget(workspace)
        timeline_splitter.addWidget(self.canva_timeline)
        timeline_splitter.setStretchFactor(0, 4)
        timeline_splitter.setStretchFactor(1, 2)
        timeline_splitter.setSizes([590, 245])
        root.addWidget(timeline_splitter,1)

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
        self.tts_service.currentTextChanged.connect(self._on_global_tts_service_changed)
        self.tts_voice.currentTextChanged.connect(self._on_global_tts_voice_changed)
        self._connect_live_preview_signals()
        self.refresh_sync_profiles()

    def _show_source_tool(self, index):
        self._active_source_tool_index=index
        if index in (0,1,2):
            self._last_work_source_mode=index
        if hasattr(self,"source_stack"):
            stack_idx = index
            if index == 2:
                stack_idx = 4
            elif index == 3:
                stack_idx = 5
            elif index == 4:
                stack_idx = 6
            elif index == 5:
                stack_idx = 7
            self.source_stack.setCurrentIndex(stack_idx)
        if hasattr(self,"group_action_panel"):
            self.group_action_panel.hide()
        if hasattr(self,"project_action_panel"):
            self.project_action_panel.hide()
        for button in getattr(self,"source_tool_buttons",[]):
            mode_value=button.property("sourceMode")
            button.setChecked((int(mode_value) if mode_value is not None else -1)==index)

    def _run_context_synthesis(self):
        mode=getattr(self,"_last_work_source_mode",0)
        if mode==2:
            self.start_project_synthesis()
            if getattr(self,"_project_thread",None):
                self.group_merge_start.setEnabled(False)
                self.group_merge_stop.setEnabled(True)
        elif mode==1:
            self.run()
            if getattr(self,"thread",None):
                self.group_merge_start.setEnabled(False)
                self.group_merge_stop.setEnabled(True)
        else:
            self.start_group_merge()

    def _stop_context_synthesis(self):
        mode=getattr(self,"_last_work_source_mode",0)
        if mode==2:
            self.stop_project_synthesis()
        elif mode==1:
            self.cancel()
            self.group_merge_start.setEnabled(True)
            self.group_merge_stop.setEnabled(False)
        else:
            self.stop_group_merge()

    def _choose_bgm_source(self):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        menu=QMenu(self)
        single=menu.addAction("添加单个背景音乐")
        folder=menu.addAction("添加背景音乐文件夹")
        action=menu.exec(QCursor.pos())
        if action==single:
            self._choose_bgm_file()
        elif action==folder:
            self._choose_bgm_folder()
            self._selected_bgm_path=""
            self._append_run_log("已添加背景音乐文件夹，将按任务队列匹配到 BGM 轨道。")
            self._refresh_canva_timeline()

    def _sync_timeline_timestamp_view(self):
        if hasattr(self,"timeline_timestamp_view"):
            text=self.override_text.toPlainText()
            if self.timeline_timestamp_view.toPlainText()==text:
                return
            self.timeline_timestamp_view.blockSignals(True)
            self.timeline_timestamp_view.setPlainText(text)
            self.timeline_timestamp_view.blockSignals(False)

    def _timeline_timestamp_editor_changed(self):
        if not hasattr(self,"override_text"):
            return
        text=self.timeline_timestamp_view.toPlainText()
        if self.override_text.toPlainText()!=text:
            self.override_text.setPlainText(text)

    def _show_left_setting_index(self, index):
        if not hasattr(self, "left_settings_stack"):
            return
        index=max(0,min(index,self.left_settings_stack.count()-1))
        self.left_settings_stack.setCurrentIndex(index)
        for button_index,button in enumerate(getattr(self,"left_setting_buttons",[])):
            button.setChecked(button_index==index)

    def _open_left_setting(self, key):
        self._show_source_tool(3)
        self._show_left_setting_index(getattr(self,"_left_setting_keys",{}).get(key,0))

    def _show_right_setting(self, index):
        if not hasattr(self,"right_settings_stack"):
            return
        index=max(0,min(index,self.right_settings_stack.count()-1))
        self.right_settings_stack.setCurrentIndex(index)
        for button_index,button in enumerate(getattr(self,"right_setting_buttons",[])):
            button.setChecked(button_index==index)

    def _choose_bgm_file(self):
        path,_=QFileDialog.getOpenFileName(
            self,"选择背景音乐","",
            "音频或视频 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mov *.mkv *.avi *.webm);;"
            "所有文件 (*.*)")
        if not path:
            return
        self._selected_bgm_path=str(Path(path).resolve())
        self.bgm_dir_input.setText(str(Path(path).resolve().parent))
        if hasattr(self,"bgm_source_display"):
            self.bgm_source_display.setText(self._selected_bgm_path)
        if hasattr(self,"bgm_selection_mode"):
            self.bgm_selection_mode.blockSignals(True)
            self.bgm_selection_mode.setCurrentIndex(0)
            self.bgm_selection_mode.blockSignals(False)
        self.load_audio_preview(self._selected_bgm_path)
        self._append_run_log(f"已添加背景音乐轨道：{Path(path).name}")
        self._refresh_canva_timeline()

    def _bgm_selection_mode_changed(self, text):
        random_mode = str(text).startswith("随机")
        if random_mode:
            self._selected_bgm_path=""
        self.audio_start_seek.setEnabled(not random_mode)
        self.audio_start_preview.setEnabled(not random_mode)
        self.audio_start_time.setEnabled(not random_mode)
        self._append_run_log(
            "背景音乐已设为随机文件与随机起点。"
            if random_mode else "背景音乐已设为固定音频与固定起始点。"
        )
        self._refresh_canva_timeline()

    def _bgm_enabled_changed(self, enabled):
        enabled=bool(enabled)
        self.background_volume.setEnabled(enabled)
        self._append_run_log(
            "已启用背景音乐，将在最终合成时加入 BGM 轨道。"
            if enabled else "已关闭背景音乐，最终合成不会加入 BGM 轨道。"
        )
        self._refresh_canva_timeline()

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
            self._append_run_log(
                "已保存分组字幕对应表；排序已设为「按分段文案自动匹配」："
                "将识别各片段语音，按你粘贴的文案顺序一一匹配后拼接（不是按文件名 1、2、3…）。"
            )

    def _scan_group_parent(self, folder):
        folder = str(folder or "").strip()
        self._save_current_group_script()
        self.group_merge_groups = discover_groups(folder)
        self.group_table.setRowCount(len(self.group_merge_groups))
        for row, (group_folder, clips) in enumerate(self.group_merge_groups):
            file_names="；".join(Path(clip).name for clip in sorted(clips,key=lambda p:natural_key(Path(p).name)))
            for column, value in enumerate((f"{row + 1:02d}", group_folder.name, str(len(clips)),file_names)):
                item = QTableWidgetItem(value); item.setToolTip(str(group_folder)); self.group_table.setItem(row, column, item)
            combo = QComboBox()
            combo.addItems(["跟随全局", *merge_transition_labels()])
            combo.setStyleSheet("QComboBox { background: #1e293b; border: 1px solid #475569; border-radius: 4px; color: #cbd5e1; }")
            self.group_table.setCellWidget(row, 4, combo)
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

    def start_group_merge_selected(self):
        if self.group_merge_thread and self.group_merge_thread.isRunning():
            return
        self._save_current_group_script()
        selected_row = self.group_table.currentRow()
        if selected_row == -1 or not self.group_merge_groups or selected_row >= len(self.group_merge_groups):
            QMessageBox.warning(self, "未选择视频组", "请先在列表中选中一个视频组（项目）！")
            return
            
        group_folder, clips = self.group_merge_groups[selected_row]
        if "文案" in self.group_sort_mode.currentText():
            if not self.group_scripts.get(str(group_folder.resolve()), "").strip():
                QMessageBox.information(self, "缺少分段文案", f"选中的“{group_folder.name}”组尚未填写分段文案！")
                return
                
        try:
            ffmpeg = self.find_ffmpeg()
        except Exception as exc:
            QMessageBox.critical(self, "缺少组件", str(exc)); return
            
        if hasattr(self, "selection_debounce_timer"):
            self.selection_debounce_timer.stop()
        self._pending_video_path = None
        self._clear_previews_and_releases()
        
        output = Path(self.output.text()) / "00_分组合成"
        provider = self.provider.currentText()
        callback = lambda path: self.transcribe_callable(path, provider)
        
        group_custom_transitions = {}
        for row in range(self.group_table.rowCount()):
            folder_item = self.group_table.item(row, 1)
            if folder_item:
                folder_path = folder_item.toolTip()
                combo = self.group_table.cellWidget(row, 4)
                if isinstance(combo, QComboBox):
                    resolved_key = Path(folder_path).resolve().as_posix().lower()
                    group_custom_transitions[resolved_key] = combo.currentText()
                    
        settings = {
            "sort_mode": "script" if "文案" in self.group_sort_mode.currentText() else "natural",
            "trim_mode": ("none" if "不裁剪" in self.group_trim_mode.currentText()
                          else "hybrid" if "混合" in self.group_trim_mode.currentText()
                          else "text" if "文案" in self.group_trim_mode.currentText() else "fast"),
            "scripts": dict(self.group_scripts),
            "head_padding_ms": self.group_head_padding.value(),
            "tail_padding_ms": self.group_tail_padding.value(),
            "silence_threshold_db": self.group_silence_threshold.value(),
            "silence_min_ms": self.group_silence_min.value(),
            "resume": False,
            "encoder_backend": self.encoder_backend.currentText(),
            "encode_preset": self.encode_preset.currentText(),
            "clean_metadata": self.clean_metadata.isChecked(),
            "transition_name": self.transition_name.currentText(),
            "transition_duration": float(self.transition_duration.value()),
            "aspect_ratio": self.aspect_ratio.currentText(),
            "resolution": self.resolution.currentText(),
            "video_extend_mode": self.video_extend_mode.currentText(),
            "group_custom_transitions": group_custom_transitions,
        }
        
        watermark_fingerprint = watermark_config_fingerprint(self._watermark_entries)
        burn_watermark = bool(self.group_burn_watermark.isChecked() and watermark_fingerprint)
        settings["burn_watermark"] = burn_watermark
        if burn_watermark:
            watermark_entries = [dict(item) for item in self._watermark_entries]
            settings["watermark_prepare"] = (
                lambda video, cache, entries=watermark_entries:
                str(prepared_watermark_composite(ffmpeg, video, entries, cache))
            )
            
        self._active_group_watermark_fingerprint = watermark_fingerprint if burn_watermark else ""
        self._group_auto_extract_requested = self._group_wants_auto_transcript()
        self._group_auto_extract_pending = False
        # 只更新选中组：不要清空已有合成列表与视频队列，避免其它组微调丢失
        self._group_merge_replace_queue = False
        self._group_merge_session_outputs = []
        expected_name = f"{group_folder.name}_去口气音合成.mp4"
        # 预计算成品路径，合成后仅替换这一条
        self._group_merge_target_names = {expected_name}
        self.group_merge_thread = QThread(self)
        
        selected_groups = [self.group_merge_groups[selected_row]]
        self.group_merge_worker = GroupMergeWorker(selected_groups, output, ffmpeg, callback, settings)
        self.group_merge_worker.moveToThread(self.group_merge_thread)
        self.group_merge_thread.started.connect(self.group_merge_worker.run)
        self.group_merge_worker.log.connect(self._append_run_log)
        self.group_merge_worker.progress.connect(self.progress.setValue)
        self.group_merge_worker.item_done.connect(self._group_merge_item_done)
        self.group_merge_worker.finished.connect(self._group_merge_finished)
        self.group_merge_worker.finished.connect(self.group_merge_thread.quit)
        self.group_merge_thread.finished.connect(self._group_merge_ended)
        self.group_merge_thread.finished.connect(self.group_merge_thread.deleteLater)
        
        self.group_merge_start.setEnabled(False)
        self.group_merge_stop.setEnabled(True)
        self.group_merge_selected.setEnabled(False)
        self.progress.setValue(0)
        
        self._append_run_log(
            f"开始单独重新合成组：{group_folder.name} (共 {len(clips)} 段)；强制覆盖该组缓存。"
            f" 视频字幕队列中其它组保持不动，仅更新 {expected_name}。"
        )
        self.group_merge_thread.start()


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
        # 第二次合成会覆盖 00_分组合成 下同名成品；若预览播放器仍占用该文件，
        # Windows 上 FFmpeg 写入会得到残缺 mp4，随后 QMediaPlayer 报
        # “Invalid data found when processing input”。
        if hasattr(self, "selection_debounce_timer"):
            self.selection_debounce_timer.stop()
        self._pending_video_path = None
        self._clear_previews_and_releases()
        output = Path(self.output.text()) / "00_分组合成"
        provider = self.provider.currentText()
        callback = lambda path: self.transcribe_callable(path, provider)
        
        group_custom_transitions = {}
        for row in range(self.group_table.rowCount()):
            folder_item = self.group_table.item(row, 1)
            if folder_item:
                folder_path = folder_item.toolTip()
                combo = self.group_table.cellWidget(row, 4)
                if isinstance(combo, QComboBox):
                    resolved_key = Path(folder_path).resolve().as_posix().lower()
                    group_custom_transitions[resolved_key] = combo.currentText()
                    
        settings = {
            "sort_mode": "script" if "文案" in self.group_sort_mode.currentText() else "natural",
            "trim_mode": ("none" if "不裁剪" in self.group_trim_mode.currentText()
                          else "hybrid" if "混合" in self.group_trim_mode.currentText()
                          else "text" if "文案" in self.group_trim_mode.currentText() else "fast"),
            "scripts": dict(self.group_scripts),
            "group_custom_transitions": group_custom_transitions,
            "head_padding_ms": self.group_head_padding.value(),
            "tail_padding_ms": self.group_tail_padding.value(),
            "silence_threshold_db": self.group_silence_threshold.value(),
            "silence_min_ms": self.group_silence_min.value(),
            "resume": True,
            "encoder_backend": self.encoder_backend.currentText(),
            "encode_preset": self.encode_preset.currentText(),
            "clean_metadata": self.clean_metadata.isChecked(),
            # 第 7 节选项：此前未传入合成 Worker，导致合并转场/比例/分辨率一直不生效
            "transition_name": self.transition_name.currentText(),
            "transition_duration": float(self.transition_duration.value()),
            "aspect_ratio": self.aspect_ratio.currentText(),
            "resolution": self.resolution.currentText(),
            "video_extend_mode": self.video_extend_mode.currentText(),
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
        self._group_auto_extract_requested=self._group_wants_auto_transcript()
        self._group_auto_extract_pending=False
        # 全量合成：完成后用全部成品刷新队列；仍保留非分组合成的其它视频条目
        self._group_merge_replace_queue = False
        self._group_merge_session_outputs = []
        self._group_merge_target_names = set()
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
        self.group_merge_start.setEnabled(False); self.group_merge_stop.setEnabled(True); self.group_merge_selected.setEnabled(False); self.progress.setValue(0)
        if settings["sort_mode"] == "natural":
            if settings["trim_mode"] == "hybrid":
                self._append_run_log("开始智能混合分组合成：文件名自然排序 → 文案首尾定位 → 声音边界修正 → 自动去口气音 → 无缝合成；不核对字幕内容。")
            elif settings["trim_mode"] == "text":
                self._append_run_log("开始文案边界分组合成：文件名自然排序 → 识别每段首词/末词时间 → 自动去口气音 → 无缝合成。")
            else:
                self._append_run_log("开始快速分组合成：文件名自然排序 → 本地检测首尾声音 → 去口气音 → 无缝合成。")
        else:
            self._append_run_log("开始文案匹配合成：识别片段文字 → 按文案排序 → 去口气音 → 无缝合成。")
        transition = settings.get("transition_name") or "无转场"
        if transition and transition != "无转场":
            dur = float(settings.get("transition_duration") or 0.5)
            self._append_run_log(
                f"合并转场：{transition}，时长 {dur:.2f}s（多片段组内 xfade；仅 1 个片段的组无转场）。"
                f" 画面 {settings.get('aspect_ratio')} / {settings.get('resolution')}。"
            )
        else:
            self._append_run_log("合并转场：无（硬切拼接）。")
        self.group_merge_thread.start()

    def _transition_name_changed(self, name):
        """切换批量转场时填入推荐时长；局部轨道转场始终可调时长。"""
        if not hasattr(self, "transition_duration"):
            return
        cfg = resolve_merge_transition(name)
        enabled = cfg is not None
        self.transition_duration.setEnabled(True)
        if enabled:
            default_dur = float(cfg.get("duration") or 0.5)
            self.transition_duration.blockSignals(True)
            self.transition_duration.setValue(default_dur)
            self.transition_duration.blockSignals(False)
            if hasattr(self, "canva_timeline"):
                self.canva_timeline.set_transition_duration(int(default_dur * 1000))
        for transition_label, button in getattr(self, "transition_buttons", []):
            button.setChecked(transition_label == name)
        if hasattr(self,"transition_selected_label"):
            self.transition_selected_label.setText(f"当前批量效果：{name or '无转场'}")

    def _image_transition_name_changed(self, name):
        cfg=resolve_merge_transition(name)
        if cfg and hasattr(self,"proj_transition_dur"):
            duration=float(cfg.get("duration") or .5)
            self.proj_transition_dur.setValue(duration)
        for transition_label,button in getattr(self,"image_transition_buttons",[]):
            button.setChecked(transition_label==name)
        if hasattr(self,"image_transition_selected_label"):
            self.image_transition_selected_label.setText(
                f"当前图片效果：{name or '无转场'}"
            )

    def stop_group_merge(self):
        if self.group_merge_worker:
            self.group_merge_worker.cancel()
            self.group_merge_stop.setEnabled(False)
            self.run_status.setText("当前状态：正在停止分组合成…")
            self.log.appendPlainText("正在停止当前处理；已完成内容会保留，下次可直接断点续接。")

    def _group_wants_auto_transcript(self):
        """是否在合成后自动转文字。勾选「不转文案」时关闭。"""
        if hasattr(self, "group_skip_transcript") and self.group_skip_transcript.isChecked():
            return False
        return bool(getattr(self, "group_auto_timeline", None) and self.group_auto_timeline.isChecked())

    def _sync_group_transcript_flags_from_skip(self, checked: bool):
        self._user_set_transcript_pref = True
        if not hasattr(self, "group_auto_timeline"):
            return
        self.group_auto_timeline.blockSignals(True)
        self.group_auto_timeline.setChecked(not bool(checked))
        self.group_auto_timeline.blockSignals(False)

    def _sync_group_transcript_flags_from_auto(self, checked: bool):
        self._user_set_transcript_pref = True
        if not hasattr(self, "group_skip_transcript"):
            return
        self.group_skip_transcript.blockSignals(True)
        self.group_skip_transcript.setChecked(not bool(checked))
        self.group_skip_transcript.blockSignals(False)

    def _on_group_trim_mode_changed(self, text: str):
        """切换到快速声音边界时，若用户未手动改过偏好，默认勾选「不转文案」。"""
        if "快速" in str(text) and hasattr(self, "group_skip_transcript"):
            if (
                hasattr(self, "group_auto_timeline")
                and self.group_auto_timeline.isChecked()
                and not getattr(self, "_user_set_transcript_pref", False)
            ):
                # 程序自动勾选，不记为用户偏好
                self.group_skip_transcript.blockSignals(True)
                self.group_skip_transcript.setChecked(True)
                self.group_skip_transcript.blockSignals(False)
                self.group_auto_timeline.blockSignals(True)
                self.group_auto_timeline.setChecked(False)
                self.group_auto_timeline.blockSignals(False)

    def _group_merge_item_done(self, output, group_name, index, total):
        if output not in self.group_merge_outputs:
            self.group_merge_outputs.append(output)
        session = getattr(self, "_group_merge_session_outputs", None)
        if session is None:
            self._group_merge_session_outputs = []
            session = self._group_merge_session_outputs
        if output not in session:
            session.append(output)
        if self._active_group_watermark_fingerprint and Path(output).is_file():
            key=str(Path(output).resolve())
            self._baked_watermarks[key]={"source":_media_signature(output),
                                         "watermark":self._active_group_watermark_fingerprint}
            QSettings("VideoToolkit","DynamicReels").setValue(
                "baked_watermarks",json.dumps(self._baked_watermarks,ensure_ascii=False))
        # 成品被覆盖后，丢弃该条旧时间轴剪辑状态，下次加载会按 segments 重新拆段
        try:
            video_key = self._timeline_key(output)
            if video_key in self.timeline_edit_states:
                self.timeline_edit_states.pop(video_key, None)
            # 若字幕源就是成品本身，保留已提取文案；仅清除剪辑分段
        except Exception:
            pass
        self.log.appendPlainText(f"[{index}/{total}] {group_name} 已加入合成结果队列。")
        
        # Calculate clip count / durations and record history
        clip_count = 0
        segment_durations = []
        try:
            ffmpeg = self.find_ffmpeg()
        except Exception:
            ffmpeg = "ffmpeg"
        if hasattr(self, "group_merge_groups"):
            for folder, clips in self.group_merge_groups:
                if folder.name == group_name:
                    clip_count = len(clips)
                    for clip in clips:
                        try:
                            dur = float(media_duration(ffmpeg, str(clip), fallback=0.0) or 0.0)
                        except Exception:
                            dur = 0.0
                        segment_durations.append({
                            "name": Path(clip).name,
                            "duration_sec": round(dur, 3),
                        })
                    break
        output_duration = 0.0
        if Path(output).is_file():
            try:
                output_duration = float(media_duration(ffmpeg, str(output), fallback=0.0) or 0.0)
            except Exception:
                output_duration = 0.0
        self._record_group_merge_history(
            group_name, clip_count, Path(output).name,
            segment_durations=segment_durations,
            output_duration_sec=round(output_duration, 3),
        )

    def _load_group_merge_outputs(self, auto_extract=False, only_session=False):
        """把合成成品放进视频字幕队列。

        only_session=True（重新合成选中组）：只更新本次成品，不清空其它视频与微调。
        only_session=False（全量合成）：确保全部成品在队列中，并保留队列里其它非本次条目。
        """
        session = list(getattr(self, "_group_merge_session_outputs", None) or [])
        pool = session if only_session and session else list(self.group_merge_outputs)
        outputs = [
            path for path in pool
            if Path(path).is_file() and Path(path).stat().st_size > 1024
        ]
        if not outputs:
            return
        # 加载前松手，防止立刻选中队列第一项时仍锁着旧句柄
        if hasattr(self, "selection_debounce_timer"):
            self.selection_debounce_timer.stop()
        self._pending_video_path = None
        self._clear_previews_and_releases()

        replace_queue = bool(getattr(self, "_group_merge_replace_queue", False))
        if replace_queue and not only_session:
            self.videos.clear()
            self._add(self.videos, outputs, ALLOWED_VIDEO_INPUTS)
        else:
            # 就地更新：同名/同路径替换为最新成品，其它条目不动
            existing_by_name = {}
            for i in range(self.videos.count()):
                text = self.videos.item(i).text()
                existing_by_name[Path(text).name] = i
            focus_path = outputs[-1]
            for path in outputs:
                name = Path(path).name
                if name in existing_by_name:
                    row = existing_by_name[name]
                    self.videos.item(row).setText(path)
                else:
                    # 也按 resolve 路径去重
                    resolved = str(Path(path).resolve())
                    found = False
                    for i in range(self.videos.count()):
                        try:
                            if str(Path(self.videos.item(i).text()).resolve()) == resolved:
                                self.videos.item(i).setText(path)
                                found = True
                                break
                        except Exception:
                            continue
                    if not found:
                        self.videos.addItem(path)
                # 尽量重建分段 sidecar（旧成品无 json 时从 cache 恢复）
                try:
                    try:
                        ff = self.find_ffmpeg()
                    except Exception:
                        ff = None
                    try_rebuild_segments_sidecar(path, ffmpeg=ff)
                except Exception:
                    pass
            # 选中本次更新的最后一条
            for i in range(self.videos.count()):
                try:
                    if Path(self.videos.item(i).text()).name == Path(focus_path).name:
                        self.videos.setCurrentRow(i)
                        break
                except Exception:
                    continue

        self._refresh_task_queue()
        # 队列变更会触发选中 → 防抖加载；再延迟一拍确保文件句柄已释放
        if self.videos.count() > 0:
            current = self.videos.currentItem()
            pick = current.text() if current else (
                self.videos.item(0).text() if self.videos.item(0) else ""
            )
            if pick:
                QTimer.singleShot(180, lambda p=pick: self._video_selection_changed(p))
        # Automatic extraction is deliberately started by _group_merge_ended(),
        # after the merge worker thread is fully released.  This method only loads
        # finished files into the normal video/task queue.

    def _group_merge_finished(self, ok, message):
        only_session = not bool(getattr(self, "_group_merge_replace_queue", False))
        # 选中组重合成：only_session 始终 True；全量合成也会用「合并进队列」策略
        only_session = True
        if ok:
            try:
                for path in json.loads(message).get("outputs", []):
                    if path not in self.group_merge_outputs:
                        self.group_merge_outputs.append(path)
                    session = getattr(self, "_group_merge_session_outputs", None)
                    if session is not None and path not in session:
                        session.append(path)
            except Exception:
                pass
            self.progress.setValue(100)
            self._load_group_merge_outputs(auto_extract=False, only_session=only_session)
            session_n = len(getattr(self, "_group_merge_session_outputs", None) or self.group_merge_outputs)
            # 自动转文字：仅针对本次会话新成品（避免重合成一组时重提全部字幕）
            pending_paths = list(getattr(self, "_group_merge_session_outputs", None) or [])
            self._group_auto_extract_paths = pending_paths if pending_paths else list(self.group_merge_outputs)
            self._group_auto_extract_pending = bool(
                self._group_auto_extract_requested and self._group_auto_extract_paths
            )
            self.log.appendPlainText(
                f"分组合成完成：本次更新 {session_n} 个完整视频（队列中其它条目未清空）。"
                + (" 线程释放后将仅为本次成品提取字幕。" if self._group_auto_extract_pending else " 未启用自动转文字，可稍后手动提取。")
            )
            self.run_status.setText("当前状态：分组合成完成" + ("，等待提取字幕" if self._group_auto_extract_pending else ""))
        else:
            self._group_auto_extract_pending=False
            self._group_auto_extract_paths = []
            if self.group_merge_outputs or getattr(self, "_group_merge_session_outputs", None):
                # 停止或失败时只并入已完成的视频，不要在后台又启动字幕提取
                self._load_group_merge_outputs(auto_extract=False, only_session=True)
                done_n = len(getattr(self, "_group_merge_session_outputs", None) or self.group_merge_outputs)
                message += f"\n\n已完成的 {done_n} 组仍已并入视频队列，其它条目未清空，可修复后断点续接。"
            if "已停止" in message:
                self._append_run_log(message)
                self.run_status.setText("当前状态：已停止，可直接再次开始并断点续接")
            else:
                QMessageBox.critical(self, "分组合成失败", message)
                self.run_status.setText("当前状态：分组合成失败，请查看日志")

    def _group_merge_ended(self):
        should_extract=bool(self._group_auto_extract_pending)
        extract_paths = list(getattr(self, "_group_auto_extract_paths", None) or [])
        self.group_merge_start.setEnabled(True); self.group_merge_stop.setEnabled(False); self.group_merge_selected.setEnabled(True)
        self.group_merge_worker = None; self.group_merge_thread = None
        self._active_group_watermark_fingerprint=""
        self._group_auto_extract_pending=False
        self._group_auto_extract_paths = []
        self._group_merge_session_outputs = []
        self._group_merge_target_names = set()
        self._append_run_log("分组合成任务已释放，可以直接开始下一次任务。")
        if should_extract:
            self.run_status.setText("当前状态：合成完成，正在提取字幕")
            if extract_paths and len(extract_paths) < max(1, self.videos.count()):
                self._append_run_log(
                    f"已启用“合成并转文字”：仅为本次 {len(extract_paths)} 个成品提取字幕，其它组字幕保留。"
                )
                QTimer.singleShot(0, lambda paths=extract_paths: self._extract_timelines_for_paths(paths))
            else:
                self._append_run_log("已启用“合成并转文字”：现在开始对合成成品提取字幕。")
                QTimer.singleShot(0, self.extract_all_timelines)

    def _on_task_queue_dropped(self, paths):
        videos = []
        audios = []
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext in ALLOWED_VIDEO_INPUTS:
                videos.append(path)
            elif ext in AUDIO_EXTENSIONS:
                audios.append(path)
        if videos:
            self._add(self.videos, videos, ALLOWED_VIDEO_INPUTS)
        if audios:
            self._add(self.audios, audios, AUDIO_EXTENSIONS)

    def _on_debounce_load_media(self):
        video_path = getattr(self, "_pending_video_path", None)
        source = getattr(self, "_pending_video_source", None)
        if not video_path: return
        
        mode = self._get_audio_mode_internal()
        external = (source if source and Path(source).is_file() and Path(source).resolve() != Path(video_path).resolve()
                    and mode in ("替换为添加的音频", "原声＋背景音混合") else "")
        offset = self.audio_offsets.get(self._timeline_key(external), 0) if external else 0
        
        self.load_video_preview(video_path, external, mix_audio=mode=="原声＋背景音混合", audio_offset_ms=offset)
        
        caption_source = self._caption_source_for_video(video_path)
        self._active_timeline_source = caption_source
        
        # Sync audio selection
        if source and hasattr(self, "audios"):
            matches = self.audios.findItems(source, Qt.MatchFlag.MatchExactly)
            if matches:
                self._syncing_media_selection = True
                try:
                    self.audios.setCurrentItem(matches[0])
                finally:
                    self._syncing_media_selection = False
                if not external:
                    self.load_audio_preview(source)
                    
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            self._load_current_free_text()
        else:
            self._timeline_selection_changed(caption_source)
        # 立刻刷新时间轴（用缓存/探测时长，不依赖播放器是否已拿到 duration）
        self._refresh_canva_timeline(video_path)
        # 播放器异步就绪后再补一次，确保时长与分段缩放精确
        QTimer.singleShot(120, lambda p=video_path: self._refresh_canva_timeline_if_current(p))
        QTimer.singleShot(450, lambda p=video_path: self._refresh_canva_timeline_if_current(p))

    def _on_debounce_load_audio(self):
        source = getattr(self, "_pending_audio_source", None)
        if not source: return
        self.load_audio_preview(source)
        video_item = self.videos.currentItem() if hasattr(self, "videos") else None
        caption_source = (self._caption_source_for_video(video_item.text()) if video_item else source)
        self._active_timeline_source = caption_source
        self._timeline_selection_changed(caption_source)

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

    def _on_preview_player_error(self, _error=None, message=""):
        """切换/覆盖文件时的瞬时 Invalid data 不刷屏；仅记录仍有效会话中的真实错误。"""
        if getattr(self, "_preview_suppress_errors", False):
            return
        text = str(message or "").strip()
        if not text:
            return
        # 常见：源被清空、文件刚被覆盖、尚未写完
        lower = text.casefold()
        if any(k in lower for k in (
            "invalid data", "could not open", "no media", "resource error",
            "无法打开", "无效", "not open",
        )):
            return
        if hasattr(self, "log") and self.log is not None:
            self.log.appendPlainText(f"播放器错误：{text}")

    def _bump_preview_token(self):
        self._preview_token = int(getattr(self, "_preview_token", 0)) + 1
        return self._preview_token

    def _release_preview_media(self, placeholder=None, suppress_ms=120):
        """停止解码并释放文件句柄，便于合成覆盖同名成品。"""
        self._preview_suppress_errors = True
        if hasattr(self, "preview_frame_timer"):
            self.preview_frame_timer.stop()
        if hasattr(self, "live_refresh_timer"):
            self.live_refresh_timer.stop()
        if hasattr(self, "preview_load_timer") or hasattr(self, "_preview_load_timer"):
            try:
                self._preview_load_timer.stop()
            except Exception:
                pass
        for player in (getattr(self, "player", None), getattr(self, "audio_player", None), getattr(self, "bgm_player", None)):
            if player is None:
                continue
            try:
                player.stop()
            except Exception:
                pass
            try:
                player.setSource(QUrl())
            except Exception:
                pass
        if getattr(self, "preview_capture", None) is not None:
            try:
                self.preview_capture.release()
            except Exception:
                pass
            self.preview_capture = None
        self.preview_base_image = QImage()
        self._preview_is_image = False
        if hasattr(self, "seek"):
            self.seek.setRange(0, 0)
        if placeholder and hasattr(self, "video_widget") and self.video_widget:
            self.video_widget.setText(placeholder)
            self.video_widget.setPixmap(QPixmap())
        # 短时抑制：setSource(空) 与切换瞬间的 Invalid data
        QTimer.singleShot(max(40, int(suppress_ms)), self._end_preview_error_suppress)

    def _end_preview_error_suppress(self):
        self._preview_suppress_errors = False

    def load_video_preview(self, path, external_audio="", precise=False, mix_audio=False, audio_offset_ms=0):
        """对外入口：作废旧会话 → 释放句柄 → 延迟串行加载，支持频繁切换。"""
        media = Path(path) if path else None
        if not media or not media.is_file():
            return
        try:
            if media.stat().st_size < 1024:
                return
        except OSError:
            return
        token = self._bump_preview_token()
        self._precise_preview_active = bool(precise)
        self._pending_preview_load = {
            "token": token,
            "path": str(media.resolve()),
            "external_audio": str(external_audio or ""),
            "precise": bool(precise),
            "mix_audio": bool(mix_audio),
            "audio_offset_ms": max(0, int(audio_offset_ms or 0)),
        }
        self._release_preview_media(
            placeholder="正在加载预览…",
            suppress_ms=160,
        )
        # 给 Windows 一点时间松开上一段文件，再 setSource
        self._preview_load_timer.start(90)

    def _apply_pending_preview_load(self):
        job = getattr(self, "_pending_preview_load", None)
        if not job:
            return
        token = job.get("token")
        if token != getattr(self, "_preview_token", 0):
            return  # 已被更新的切换请求作废
        media = Path(job.get("path", ""))
        if not media.is_file():
            return
        try:
            size = media.stat().st_size
        except OSError:
            return
        # 文件可能仍在被 FFmpeg 写入：稍后重试（同 token）
        if size < 1024 or media.name.endswith(".tmp") or ".tmp_" in media.name:
            if token == self._preview_token:
                self._preview_load_timer.start(160)
            return
        # 短暂稳定：两次体积一致才加载，避免半截文件
        prev = job.get("_size")
        if prev is None or prev != size:
            job["_size"] = size
            job["_stable"] = 0
            self._pending_preview_load = job
            if token == self._preview_token:
                self._preview_load_timer.start(100)
            return
        job["_stable"] = int(job.get("_stable", 0)) + 1
        if job["_stable"] < 1:
            self._pending_preview_load = job
            if token == self._preview_token:
                self._preview_load_timer.start(80)
            return

        external = job.get("external_audio") or ""
        mix_audio = bool(job.get("mix_audio"))
        audio_offset_ms = int(job.get("audio_offset_ms") or 0)
        self._precise_preview_active = bool(job.get("precise"))
        self._preview_external_audio = bool(external and Path(external).is_file())
        self._preview_audio_offset_ms = audio_offset_ms if self._preview_external_audio else 0
        abs_path = str(media.resolve())
        self._preview_loaded_path = abs_path
        is_image = media.suffix.lower() in IMAGE_EXTENSIONS
        self._preview_is_image = is_image
        try:
            if is_image:
                image = QImage(abs_path)
                if not image.isNull():
                    target_size = self.video_widget.size()
                    if target_size.width() > 0 and target_size.height() > 0:
                        self.preview_base_image = image.scaled(
                            target_size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
                    else:
                        self.preview_base_image = image.copy()
                if self._preview_external_audio:
                    self._preview_external_audio = False  # Play through main player instead!
                    self.audio_output.setVolume(.65)
                    self.player.setSource(QUrl.fromLocalFile(str(Path(external).resolve())))
                    if token != self._preview_token:
                        return
                    self.player.play()
                else:
                    self.audio_output.setVolume(0)
                    self.player.setSource(QUrl())
                    self._preview_duration_changed(5000)
                    self._display_cached_preview()
            
            # Resolve BGM settings
            self._preview_bgm_active = False
            self._preview_bgm_file = None
            self._preview_bgm_offset_ms = 0
            
            bgm_dir = self.bgm_dir_input.text().strip() if hasattr(self, "bgm_dir_input") else ""
            if hasattr(self,"bgm_enabled") and self.bgm_enabled.isChecked():
                video_index = 0
                for i in range(self.videos.count()):
                    if self.videos.item(i).text() == str(media):
                        video_index = i
                        break
                selected=Path(str(getattr(self,"_selected_bgm_path","")))
                path_bgm = Path(bgm_dir)
                random_bgm=self.bgm_selection_mode.currentText().startswith("随机")
                if selected.is_file() and not random_bgm:
                    self._preview_bgm_file=selected
                elif path_bgm.is_file():
                    self._preview_bgm_file = path_bgm
                elif path_bgm.is_dir():
                    self._preview_bgm_file = find_bgm_file(
                        str(path_bgm),video_index,str(media),randomize=random_bgm
                    )
                
                if self._preview_bgm_file and self._preview_bgm_file.is_file():
                    self._preview_bgm_active = True
                    if random_bgm:
                        import hashlib
                        h = hashlib.md5(f"{media.resolve()}_{video_index}".encode("utf-8")).hexdigest()
                        self._preview_bgm_offset_ms = (int(h, 16) % 30) * 1000
                    else:
                        self._preview_bgm_offset_ms=int(
                            self.audio_offsets.get(str(self._preview_bgm_file.resolve()),0)
                        )

            if self._preview_bgm_active:
                self.bgm_player.setSource(QUrl.fromLocalFile(str(self._preview_bgm_file.resolve())))
                bgm_vol = self.background_volume.value() / 100 if hasattr(self, "background_volume") else 0.4
                self.bgm_audio_output.setVolume(bgm_vol)
            else:
                self.bgm_player.setSource(QUrl())

            if not is_image:
                self.audio_output.setVolume(
                    self.original_volume.value() / 100 if self._preview_external_audio and mix_audio else
                    (0 if self._preview_external_audio else .65)
                )
                self.player.setSource(QUrl.fromLocalFile(abs_path))
                if token != self._preview_token:
                    return
                self.player.play()
                if self._preview_external_audio:
                    self.audio_player.setSource(QUrl.fromLocalFile(str(Path(external).resolve())))
                    if token != self._preview_token:
                        return
                    self.audio_preview_output.setVolume(
                        self.background_volume.value() / 100 if mix_audio else .8)
                    self.audio_player.setPosition(self._preview_audio_offset_ms)
                    self.audio_player.play()
                    if hasattr(self, "audio_play_btn"):
                        self.audio_play_btn.setText("暂停配音")
                else:
                    self.audio_player.pause()
            if token != self._preview_token:
                return
            self.preview_frame_timer.stop()
            self._seek_preview(0)
            if hasattr(self, "play_btn"):
                self.play_btn.setText("暂停")
            # 加载成功：清空 pending，允许正常收帧
            if token == self._preview_token:
                self._pending_preview_load = None
                self._preview_suppress_errors = False
        except Exception as exc:
            if token == self._preview_token and hasattr(self, "log") and self.log is not None:
                self.log.appendPlainText(f"预览加载失败（可忽略并重选视频）：{exc}")

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
        if getattr(self, "_preview_bgm_active", False) and hasattr(self, "bgm_player"):
            self.bgm_player.setPosition(int(milliseconds) + self._preview_bgm_offset_ms)
        # QVideoSink 会在跳转完成后送来对应帧；短暂等待期间保留上一帧，不阻塞界面。

    def _video_frame_changed(self, frame):
        if not frame or not frame.isValid():
            return
        # 加载切换中忽略旧解码器冲刷出来的帧，避免闪一下错图或异常
        if getattr(self, "_preview_suppress_errors", False):
            return
        if getattr(self, "_pending_preview_load", None):
            # 仍在排队加载时忽略
            job = self._pending_preview_load
            if job and job.get("token") == getattr(self, "_preview_token", 0) and job.get("_stable", 0) < 1:
                return
        # Throttle: if the timer is already active, we are processing a queued frame.
        # Skip this frame to save GUI CPU and memory copy overhead!
        if self.live_refresh_timer.isActive():
            return

        image = frame.toImage()
        if image.isNull():
            return

        # Scale the image immediately to the size of self.video_widget!
        # Since the widget size is small, scaling here is extremely fast and light.
        target_size = self.video_widget.size()
        if target_size.width() > 0 and target_size.height() > 0:
            self.preview_base_image = image.scaled(
                target_size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation)
        else:
            self.preview_base_image = image.copy()

        self.live_refresh_timer.start()

    def _display_cached_preview(self):
        if self.preview_base_image.isNull():
            return
        # Copy the pre-scaled image to paint on it. No need to scale again!
        image = self.preview_base_image.copy()
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
                        self.watermark_mode, self.watermark_position, self.writing_language,
                        # 第 7 节：此前改了不记忆，重启后回默认
                        self.aspect_ratio, self.resolution, self.video_extend_mode, self.transition_name):
            control.currentTextChanged.connect(self._refresh_live_preview)
            control.currentTextChanged.connect(self._save_style_preferences)
        self.transition_duration.valueChanged.connect(self._save_style_preferences)
        self.rtl_word_highlight.toggled.connect(self._save_style_preferences)
        self.rtl_word_highlight.toggled.connect(self._refresh_live_preview)
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
        self.rename_custom_titles.textChanged.connect(self._save_style_preferences)
        self.group_burn_watermark.toggled.connect(self._save_style_preferences)
        self.output.textChanged.connect(self._save_style_preferences)
        self.bgm_dir_input.textChanged.connect(self._save_style_preferences)
        self.bgm_selection_mode.currentTextChanged.connect(self._save_style_preferences)
        self.bgm_enabled.toggled.connect(self._save_style_preferences)
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
        else:
            # First, clean the temporary "网红大红黄" preset if it exists in the saved presets
            original_len = len(self.all_presets)
            self.all_presets = [x for x in self.all_presets if x["name"] != "网红大红黄"]
            modified = len(self.all_presets) != original_len

            # 迁移旧 Reels 预设名 → 语义重点堆叠
            _reels_aliases = {"Reels 白字柔影", "Reels 重点放大"}
            for item in self.all_presets:
                if item.get("is_custom"):
                    continue
                if item.get("name") in _reels_aliases:
                    item["name"] = "Reels 语义重点"
                    item["data"] = dict(PRESETS["Reels 语义重点"])
                    modified = True
                elif item.get("name") in PRESETS and item.get("data") != PRESETS[item["name"]]:
                    item["data"] = dict(PRESETS[item["name"]])
                    modified = True
            # 去重：迁移后可能出现多个同名系统预设
            seen_names = set()
            deduped = []
            for item in self.all_presets:
                name = item.get("name")
                if name in seen_names and not item.get("is_custom"):
                    modified = True
                    continue
                seen_names.add(name)
                deduped.append(item)
            self.all_presets = deduped
            
            # Auto-merge any new default system presets that are not in the user's config
            existing_names = {x["name"] for x in self.all_presets}
            for name, preset_dict in PRESETS.items():
                if name not in existing_names:
                    # Insert before the first custom preset, or at the end
                    insert_idx = len(self.all_presets)
                    for i, x in enumerate(self.all_presets):
                        if x.get("is_custom", False):
                            insert_idx = i
                            break
                    self.all_presets.insert(insert_idx, {
                        "name": name,
                        "is_custom": False,
                        "data": preset_dict
                    })
                    modified = True
            if modified:
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
            "audio_mode":self._get_audio_mode_internal(),"encoder_backend":self.encoder_backend.currentText(),
            "original_volume":self.original_volume.value(),"background_volume":self.background_volume.value(),
            "audio_fade_mode":self.audio_fade_mode.currentText(),
            "audio_fade_in_ms":self.audio_fade_in.value(),"audio_fade_out_ms":self.audio_fade_out.value(),
            "encode_preset":self.encode_preset.currentText(),"clean_metadata":self.clean_metadata.isChecked(),
            "watermark_mode":self.watermark_mode.currentText(),"watermark_position":self.watermark_position.currentText(),
            "watermark_width":self.watermark_width.value(),"watermark_opacity":self.watermark_opacity.value(),
            "watermark_margin":self.watermark_margin.value(),"text_color":self._hex(self.text_color),
            "outline_color":self._hex(self.outline_color),"highlight_color":self._hex(self.highlight_color),
            "audio_offsets":dict(self.audio_offsets),
            "bgm_dir": self.bgm_dir_input.text().strip() if hasattr(self, "bgm_dir_input") else "",
            "bgm_selection_mode": (
                self.bgm_selection_mode.currentText()
                if hasattr(self,"bgm_selection_mode") else ""
            ),
            "bgm_enabled": (
                self.bgm_enabled.isChecked() if hasattr(self,"bgm_enabled") else False
            ),
            "aspect_ratio": self.aspect_ratio.currentText(),
            "resolution": self.resolution.currentText(),
            "video_extend_mode": self.video_extend_mode.currentText(),
            "transition_name": self.transition_name.currentText(),
            "transition_duration": float(self.transition_duration.value()),
            "rename_enabled": self.rename_enabled.isChecked(),
            "rename_prefix": self.rename_prefix.text(),
            "rename_date_enabled": self.rename_date_enabled.isChecked(),
            "rename_date": self.rename_date.text(),
            "rename_suffix_enabled": self.rename_suffix_enabled.isChecked(),
            "rename_suffix": self.rename_suffix.text(),
            "rename_start_index": self.rename_start_index.value(),
            "rename_padding": self.rename_padding.value(),
            "rename_titles": self._rename_titles_list(),
            "group_burn_watermark": self.group_burn_watermark.isChecked(),
            "watermark_paths": list(self._watermark_paths),
            "watermarks": [dict(item) for item in self._watermark_entries],
            "timeline_chinese": dict(self.timeline_chinese),
            "output_dir": self.output.text(),
            "writing_language": writing_language_from_ui(self.writing_language.currentText()),
            "rtl_word_highlight": self.rtl_word_highlight.isChecked(),
            "proj_bgm_folder": "",
            "proj_img_transition": self.proj_img_transition.currentText() if hasattr(self, "proj_img_transition") else "无转场",
            "proj_img_animation": self.proj_img_animation.currentText() if hasattr(self, "proj_img_animation") else "静态图片",
            "proj_transition_dur": float(self.proj_transition_dur.value()) if hasattr(self, "proj_transition_dur") else 0.5,
            "proj_ai_service": self.proj_ai_service.currentText() if hasattr(self, "proj_ai_service") else "未启用 (使用本地变焦特效)",
            "proj_ai_key": "",
        }

    def _get_audio_mode_internal(self, text=None):
        txt = text if text is not None else (self.audio_mode.currentText() if hasattr(self, "audio_mode") else "")
        if ("视频配音" in txt or "清除视频原音" in txt or "消除视频原音" in txt
                or "清除视频噪音" in txt or "替换" in txt):
            return "替换为添加的音频"
        return "保留视频原音"

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
        if preset in ("Reels 白字柔影", "Reels 重点放大"):
            preset = "Reels 语义重点"
        if preset in PRESETS: self.apply_preset(preset)
        combos={"font":self.font,"caption_mode":self.caption_mode,"free_animation":self.free_animation,
                "position":self.position,"audio_match_mode":self.audio_match_mode,"audio_mode":self.audio_mode,
                "audio_fade_mode":self.audio_fade_mode,
                "encoder_backend":self.encoder_backend,"encode_preset":self.encode_preset,
                "watermark_mode":self.watermark_mode,"watermark_position":self.watermark_position,
                "aspect_ratio":self.aspect_ratio,"resolution":self.resolution,
                "video_extend_mode":self.video_extend_mode,"transition_name":self.transition_name}
        spins={"font_size":self.font_size,"free_page_seconds":self.free_page_seconds,"line_length":self.line_length,
               "line_width":self.line_width,"letter_spacing":self.letter_spacing,"word_spacing":self.word_spacing,
               "line_spacing":self.line_spacing,"max_words":self.max_words,"highlight_padding":self.highlight_padding,
               "highlight_padding_y":self.highlight_padding_y,"animation_speed":self.animation_speed,
               "outline_width":self.outline_width,"margin_v":self.margin_v,"watermark_width":self.watermark_width,
               "original_volume":self.original_volume,"background_volume":self.background_volume,
               "audio_fade_in_ms":self.audio_fade_in,"audio_fade_out_ms":self.audio_fade_out,
               "watermark_opacity":self.watermark_opacity,"watermark_margin":self.watermark_margin,
               "transition_duration":self.transition_duration}
        for key,control in combos.items():
            if key in saved:
                val = str(saved[key])
                if key == "audio_mode":
                    if val == "替换为添加的音频":
                        val = "视频配音＋背景音乐"
                    elif val == "原声＋背景音混合":
                        val = "视频原声＋背景音乐"
                    elif val == "保留视频原音":
                        val = "视频原声"
                control.setCurrentText(val)
        for key,control in spins.items():
            if key in saved:
                try: control.setValue(float(saved[key]) if isinstance(control.value(),float) else int(saved[key]))
                except (TypeError,ValueError): pass
        if "bgm_dir" in saved:
            self.bgm_dir_input.setText(str(saved["bgm_dir"]))
            if hasattr(self,"bgm_source_display") and not self.bgm_source_display.text():
                self.bgm_source_display.setText(str(saved["bgm_dir"]))
        if "bgm_selection_mode" in saved and hasattr(self,"bgm_selection_mode"):
            self.bgm_selection_mode.setCurrentText(str(saved["bgm_selection_mode"]))
        self._audio_mode_changed(self.audio_mode.currentText())
        if "proj_img_transition" in saved and hasattr(self, "proj_img_transition"):
            self.proj_img_transition.setCurrentText(str(saved["proj_img_transition"]))
        if "proj_img_animation" in saved and hasattr(self, "proj_img_animation"):
            self.proj_img_animation.setCurrentText(str(saved["proj_img_animation"]))
        if "proj_transition_dur" in saved and hasattr(self, "proj_transition_dur"):
            self.proj_transition_dur.setValue(float(saved["proj_transition_dur"]))
        if "proj_ai_service" in saved and hasattr(self, "proj_ai_service"):
            self.proj_ai_service.setCurrentText(str(saved["proj_ai_service"]))
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
        import datetime
        self.rename_date.setText(datetime.date.today().strftime("%Y%m%d"))
        if "rename_suffix_enabled" in saved:
            self.rename_suffix_enabled.setChecked(bool(saved["rename_suffix_enabled"]))
        if "rename_suffix" in saved:
            self.rename_suffix.setText(str(saved["rename_suffix"]))
        if "rename_start_index" in saved:
            self.rename_start_index.setValue(int(saved["rename_start_index"]))
        if "rename_padding" in saved:
            self.rename_padding.setValue(int(saved["rename_padding"]))
        if "rename_titles" in saved:
            titles = saved.get("rename_titles") or []
            if isinstance(titles, str):
                self.rename_custom_titles.setPlainText(titles)
            elif isinstance(titles, list):
                self.rename_custom_titles.setPlainText(
                    "\n".join(str(x) for x in titles if str(x).strip())
                )
        if "group_burn_watermark" in saved:
            self.group_burn_watermark.setChecked(bool(saved["group_burn_watermark"]))
        if "writing_language" in saved or "caption_language" in saved:
            code = str(saved.get("writing_language") or saved.get("caption_language") or "")
            fill_writing_language_combo(self.writing_language, code)
        if "rtl_word_highlight" in saved:
            self.rtl_word_highlight.setChecked(bool(saved["rtl_word_highlight"]))

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
            settings=self._current_settings()
            preset_name = settings.get("preset")
            if preset_name in ("Reels 白字柔影", "Reels 重点放大"):
                preset_name = "Reels 语义重点"
            preset = PRESETS.get(preset_name) or next(iter(PRESETS.values()))
            context=caption_layout_context(settings)
            self._live_caption_style_cache={"settings":settings,"preset":preset,"context":context}
        settings=self._live_caption_style_cache["settings"]; preset=self._live_caption_style_cache["preset"]
        text, active_word = self._live_caption_data(seconds); tokens = tokens_for(text)
        if not tokens: return
        fixed_all = (settings.get("caption_mode") == "自由文案动画（不对口型）" and
                     settings.get("free_animation") == "整段固定")
        context=self._live_caption_style_cache["context"]; font,metrics,_gap,_line_gap,_max_line_width=context
        base_color=QColor(settings["text_color"]); outline=QColor(settings["outline_color"]); highlight=QColor(settings["highlight_color"])
        effect=preset["effect"]; active_used=False
        pen_width=max(1.0,settings["outline_width"])

        # 语义重点：整句定稿占位，只绘制已读到的词（位置与导出一致，不随逐词重排）
        if effect in ("semantic_stack", "word_scale"):
            geo_settings = dict(settings)
            geo_settings["position"] = "画面中间"
            preset_data = preset if isinstance(preset, dict) else {}
            for key in ("semantic_large_ratio", "semantic_small_ratio", "semantic_max_lines"):
                if key not in geo_settings and key in preset_data:
                    geo_settings[key] = preset_data[key]
            emphasized = select_emphasis_words(tokens)
            # 底稿：整句排版
            full_lines = semantic_stack_layout(tokens, emphasized, geo_settings)
            max_stack_lines = max(3, min(6, int(geo_settings.get("semantic_max_lines", 5))))
            full_pages = (
                [full_lines]
                if fixed_all or len(full_lines) <= max_stack_lines
                else [full_lines[i:i + max_stack_lines] for i in range(0, len(full_lines), max_stack_lines)]
            ) or [[]]
            # 当前读到第几个词
            cut = len(tokens)
            if active_word:
                for i, tok in enumerate(tokens):
                    if tok == active_word:
                        cut = i + 1
                        break
            spoken = set(range(cut))
            # 落在哪一页：按词序号
            page_index = 0
            cursor = 0
            for pi, page in enumerate(full_pages):
                count = sum(len(line) for line in page)
                if cut - 1 < cursor + count:
                    page_index = pi
                    break
                cursor += count
            page_lines = full_pages[page_index]
            page_token_offset = sum(sum(len(line) for line in full_pages[i]) for i in range(page_index))
            geometry = semantic_stack_geometry(page_lines, geo_settings)
            family = str(settings.get("font", "Arial"))
            bold = caption_uses_bold_face(settings)
            letter = float(settings.get("letter_spacing", 0))
            flat_i = 0
            for line, line_geo in zip(page_lines, geometry):
                for item, geo in zip(line, line_geo):
                    global_i = page_token_offset + flat_i
                    flat_i += 1
                    if global_i not in spoken:
                        continue  # 未读到的词：透明底稿不画
                    size = int(item.get("size") or settings.get("font_size", 86))
                    word_font = QFont(family)
                    word_font.setPixelSize(size)
                    word_font.setBold(bold)
                    word_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter)
                    path = QPainterPath()
                    path.addText(0, 0, word_font, item["token"])
                    painter.save()
                    painter.translate(geo["left"], geo["baseline"])
                    painter.setPen(QPen(outline, pen_width * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(base_color)
                    painter.drawPath(path)
                    painter.restore()
            return

        lines=caption_wrapped_lines(text,settings,fixed_all,context)
        # 与最终导出一致：一个画面最多两排。根据当前朗读词切换到对应分页。
        pages=([lines] if fixed_all else [lines[index:index+2] for index in range(0,len(lines),2)]) or [[]]
        active_page=0
        if active_word:
            for page_index,page in enumerate(pages):
                if any(active_word == token for line in page for token in line):
                    active_page=page_index; break
        lines=pages[active_page]; geometry=caption_page_geometry(lines,settings,context)
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
                if effect == "double_outline":
                    outer_pen_width = (pen_width + 3) * 2
                    painter.setPen(QPen(highlight, outer_pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                    painter.setPen(QPen(outline, pen_width * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.drawPath(path)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(base_color)
                    painter.drawPath(path)
                else:
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
        text_controls=(self.layer_text,self.layer_text_font,self.layer_text_size,self.layer_text_color,
                       self.layer_text_outline_color,self.layer_text_outline,
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
            self.layer_text_outline_color.setText(f"描边颜色 {layer.get('outline','#111111')}")

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

    def _pick_layer_text_outline_color(self):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="text": return
        color=QColorDialog.getColor(QColor(self.layers[row].get("outline","#111111")),self)
        if color.isValid():
            self.layers[row]["outline"]=color.name().upper()
            self.layer_text_outline_color.setText(f"描边颜色 {color.name().upper()}")
            self._refresh_live_preview()

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
        pos = self.position.currentText() if hasattr(self, "position") else "底部"
        if pos == "顶部":
            self.preview_position_value.setText(f"距顶部 {value}")
        elif pos == "画面中间":
            self.preview_position_value.setText("居中 (忽略边距)")
        else:
            self.preview_position_value.setText(f"距底部 {value}")

    def _sync_preview_margin(self, value):
        if not hasattr(self, "preview_position_slider"): return
        self.preview_position_slider.blockSignals(True); self.preview_position_slider.setValue(value); self.preview_position_slider.blockSignals(False)
        pos = self.position.currentText() if hasattr(self, "position") else "底部"
        if pos == "顶部":
            self.preview_position_value.setText(f"距顶部 {value}")
        elif pos == "画面中间":
            self.preview_position_value.setText("居中 (忽略边距)")
        else:
            self.preview_position_value.setText(f"距底部 {value}")

    def _position_changed(self, text):
        is_center = text == "画面中间"
        is_top = text == "顶部"
        if hasattr(self, "margin_v"):
            self.margin_v.setEnabled(not is_center)
        if hasattr(self, "preview_position_slider"):
            self.preview_position_slider.setEnabled(not is_center)
        val = self.margin_v.value() if hasattr(self, "margin_v") else 250
        if hasattr(self, "preview_position_value"):
            if is_center:
                self.preview_position_value.setText("居中 (忽略边距)")
            elif is_top:
                self.preview_position_value.setText(f"距顶部 {val}")
            else:
                self.preview_position_value.setText(f"距底部 {val}")

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
        if hasattr(self, "canva_timeline"):
            self.canva_timeline.set_position(value)
        expected=value+self._preview_audio_offset_ms
        if self._preview_external_audio and abs(self.audio_player.position()-expected) > 250:
            self.audio_player.setPosition(expected)
        if getattr(self, "_preview_bgm_active", False) and hasattr(self, "bgm_player"):
            expected_bgm = value + self._preview_bgm_offset_ms
            if abs(self.bgm_player.position() - expected_bgm) > 250:
                self.bgm_player.setPosition(expected_bgm)
        self.time_label.setText(f"{self._clock(value)} / {self._clock(self.player.duration())}")
        if getattr(self, "_preview_is_image", False):
            self._display_cached_preview()

    def _preview_duration_changed(self, value):
        self.seek.setRange(0,max(0,value)); self._preview_position_changed(self.player.position())
        if value > 0:
            # 只刷新「当前预览路径」对应的时间轴，避免快速切换时旧视频 duration 串到新项目
            path = getattr(self, "_preview_loaded_path", "") or ""
            if not path:
                item = self.videos.currentItem() if hasattr(self, "videos") else None
                path = item.text() if item else ""
            if path:
                try:
                    key = self._timeline_key(path)
                    if key:
                        self._media_duration_cache[key] = int(value)
                except Exception:
                    pass
                self._refresh_canva_timeline(path)

    def _current_settings(self):
        preset = next((button.text() for button in self.preset_buttons if button.isChecked()), None)
        if not preset and self.preset_buttons:
            preset = self.preset_buttons[0].text()
        if not preset:
            preset = "Descript 💬"
        watermark_fingerprint=watermark_config_fingerprint(self._watermark_entries)
        baked_videos=[]
        if watermark_fingerprint and hasattr(self,"videos"):
            for index in range(self.videos.count()):
                path=self.videos.item(index).text()
                if self._baked_watermark_matches(path,watermark_fingerprint):
                    baked_videos.append(str(Path(path).resolve()))
        writing_lang = writing_language_from_ui(self.writing_language.currentText())
        return {"preset":preset,"font":self.font.currentText(),"font_size":self.font_size.value(),
                "caption_mode":self.caption_mode.currentText(),
                "free_animation":self.free_animation.currentText(),
                "free_page_seconds":self.free_page_seconds.value(),
                "writing_language": writing_lang,
                "caption_language": writing_lang,
                "language": writing_lang,
                "rtl_word_highlight": self.rtl_word_highlight.isChecked(),
                "line_length":self.line_length.value(),"outline_width":self.outline_width.value(),
                "line_width":self.line_width.value(),"letter_spacing":self.letter_spacing.value(),
                "word_spacing":self.word_spacing.value(),
                "line_spacing":self.line_spacing.value(),
                "max_words":self.max_words.value(),"highlight_padding":self.highlight_padding.value(),
                "highlight_padding_y":self.highlight_padding_y.value(),
                "animation_speed":self.animation_speed.value(),
                "position":self.position.currentText(),"margin_v":self.margin_v.value(),
                "audio_mode":self._get_audio_mode_internal(),"audio_match_mode":self.audio_match_mode.currentText(),
                "original_volume":self.original_volume.value(),"background_volume":self.background_volume.value(),
                "audio_fade_mode":self.audio_fade_mode.currentText(),
                "audio_fade_in_ms":self.audio_fade_in.value(),"audio_fade_out_ms":self.audio_fade_out.value(),
                "bgm_dir": self.bgm_dir_input.text().strip(),
                "bgm_selection_mode": (
                    self.bgm_selection_mode.currentText()
                    if hasattr(self,"bgm_selection_mode") else ""
                ),
                "bgm_enabled": (
                    self.bgm_enabled.isChecked() if hasattr(self,"bgm_enabled") else False
                ),
                "audio_offsets":dict(self.audio_offsets),
                "clean_metadata":self.clean_metadata.isChecked(),
                "override_text":self.override_text.toPlainText().strip(),"encode_preset":self.encode_preset.currentText(),
                "encoder_backend":self.encoder_backend.currentText(),
                "timeline_overrides":dict(self.timeline_overrides),
                "timeline_edits":dict(self.timeline_edit_states),
                "selected_bgm_path":self._selected_bgm_path,
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
                "bgm_dir": self.bgm_dir_input.text().strip(),
            "text_color":self._hex(self.text_color),"outline_color":self._hex(self.outline_color),
                "highlight_color":self._hex(self.highlight_color),"provider":self.provider.currentText(),
                "aspect_ratio": self.aspect_ratio.currentText(),
                "resolution": self.resolution.currentText(),
                "video_extend_mode": self.video_extend_mode.currentText(),
                "transition_name": self.transition_name.currentText(),
                "transition_duration": float(self.transition_duration.value()),
                "rename_enabled": self.rename_enabled.isChecked(),
                "rename_prefix": self.rename_prefix.text(),
                "rename_suffix_enabled": self.rename_suffix_enabled.isChecked(),
                "rename_suffix": self.rename_suffix.text(),
                "rename_date_enabled": self.rename_date_enabled.isChecked(),
                "rename_date": self.rename_date.text(),
                "rename_start_index": self.rename_start_index.value(),
                "rename_padding": self.rename_padding.value(),
                "rename_titles": self._rename_titles_list(),
                "motion_tracks": json.loads(json.dumps(self.motion_tracks, ensure_ascii=False)),
                }

    def _refresh_motion_track_list(self):
        if not hasattr(self, "track_list"):
            return
        self.track_list.clear()
        for track in self.motion_tracks:
            mode = "模糊" if track.get("mode") == "blur" else "标签"
            n = len(track.get("points") or [])
            t0 = int((track.get("points") or [{}])[0].get("t_ms", track.get("start_ms", 0)) or 0)
            t1 = int((track.get("points") or [{}])[-1].get("t_ms", t0) or t0)
            label = str(track.get("label") or "").strip()
            text = f"[{mode}] {n}点  {self._clock(t0)}–{self._clock(t1)}"
            if label:
                text += f"  「{label}」"
            if track.get("mode") == "blur":
                text += f"  blur={track.get('blur', 18)}"
            self.track_list.addItem(text)
        if hasattr(self, "track_status"):
            self.track_status.setText(
                f"已保存 {len(self.motion_tracks)} 条追踪路径；批量导出时自动应用到画面。"
                if self.motion_tracks else "当前无追踪路径"
            )

    def _run_motion_track(self):
        item = self.videos.currentItem() if hasattr(self, "videos") else None
        if not item:
            QMessageBox.information(self, "没有视频", "请先在左侧队列选中要追踪的视频。")
            return
        video_path = item.text()
        if not Path(video_path).is_file():
            QMessageBox.warning(self, "文件不存在", video_path)
            return
        start_ms = int(self.player.position() if hasattr(self, "player") else 0)
        # 先在当前帧上绘制区域（专业剪辑式框选），再自动跟踪
        try:
            from .roi_picker import RoiPickerDialog
            dlg = RoiPickerDialog(video_path, start_ms, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            pct = dlg.percentages()
            if not pct:
                QMessageBox.information(self, "未框选", "请拖拽绘制一个有效区域。")
                return
            x_pct, y_pct, w_pct, h_pct = pct
            self.track_x.setValue(round(x_pct, 2))
            self.track_y.setValue(round(y_pct, 2))
            self.track_w.setValue(round(w_pct, 2))
            self.track_h.setValue(round(h_pct, 2))
        except Exception as exc:
            QMessageBox.warning(
                self, "框选失败",
                f"无法打开绘制窗口（{exc}），将使用右侧百分比数值。",
            )
            x_pct = float(self.track_x.value())
            y_pct = float(self.track_y.value())
            w_pct = float(self.track_w.value())
            h_pct = float(self.track_h.value())
        duration_sec = int(self.track_duration.value()) if hasattr(self, "track_duration") else 8
        duration_ms = 0 if duration_sec <= 0 else duration_sec * 1000
        mode = "blur" if "模糊" in self.track_mode.currentText() else "label"
        self.track_run_btn.setEnabled(False)
        self.track_run_btn.setText("追踪中…")
        self.track_status.setText("正在跟踪目标，请稍候…")
        QApplication.processEvents()
        try:
            from .motion_track import track_region, new_track_record
            points = track_region(
                video_path,
                x_pct=float(x_pct),
                y_pct=float(y_pct),
                w_pct=float(w_pct),
                h_pct=float(h_pct),
                start_ms=start_ms,
                duration_ms=duration_ms,
                progress_cb=lambda fi, ef, n: self.track_status.setText(
                    f"追踪中… 帧 {fi}/{ef}，已采样 {n} 点"
                ),
            )
            record = new_track_record(
                points,
                mode=mode,
                blur=int(self.track_blur.value()),
                label=self.track_label.text().strip(),
                start_ms=start_ms,
            )
            self.motion_tracks.append(record)
            self._refresh_motion_track_list()
            self._append_run_log(
                f"动态追踪完成：{len(points)} 个关键帧，模式={'模糊' if mode == 'blur' else '标签'}，"
                f"起始 {self._clock(start_ms)}。"
            )
            QMessageBox.information(
                self, "追踪完成",
                f"已记录 {len(points)} 个跟踪点。\n导出时会将「追踪模糊」烧进画面。",
            )
        except Exception as exc:
            QMessageBox.critical(self, "追踪失败", str(exc))
            self.track_status.setText(f"追踪失败：{exc}")
        finally:
            self.track_run_btn.setEnabled(True)
            self.track_run_btn.setText("从当前帧开始追踪")

    def _delete_selected_motion_track(self):
        row = self.track_list.currentRow() if hasattr(self, "track_list") else -1
        if row < 0 or row >= len(self.motion_tracks):
            QMessageBox.information(self, "未选择", "请先在列表中选中一条追踪路径。")
            return
        self.motion_tracks.pop(row)
        self._refresh_motion_track_list()

    def _clear_motion_tracks(self):
        if not self.motion_tracks:
            return
        if QMessageBox.question(self, "清空追踪", "确定删除全部动态追踪路径？") != QMessageBox.StandardButton.Yes:
            return
        self.motion_tracks = []
        self._refresh_motion_track_list()

    def _rename_titles_list(self):
        """按行解析自定义标题；保留中间空行作为占位，去掉末尾空行。"""
        lines = [line.strip() for line in self.rename_custom_titles.toPlainText().splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def render_effect_preview(self):
        item=self.videos.currentItem()
        if not item:
            QMessageBox.information(self,"没有预览视频","请先在左侧添加并选中一个视频。"); return
        try: ffmpeg=self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self,"缺少组件",str(exc)); return
        timeline_source=self._timeline_source()
        timeline_key=self._timeline_key(timeline_source)
        video_key=self._timeline_key(item.text())
        # 轨道渲染预览：用当前选中视频自己的时间轴状态 + 字幕，不拿别的任务的文案串台
        text=(self.timeline_overrides.get(timeline_key, "").strip()
              or self.override_text.toPlainText().strip()
              or self.tts_text.toPlainText().strip()
              or "让每一句文案跟随朗读跳动")
        if "-->" not in text and self.caption_mode.currentText() != "自由文案动画（不对口型）":
            text=re.sub(r"\s+"," ",text)[:100]
        preview_dir=Path(self.output.text())/".preview"; preview_dir.mkdir(parents=True,exist_ok=True)
        # Never reuse a media URL in the same application session.
        preview_token=f"{time.time_ns():x}"
        destination=preview_dir/f"track_{short_media_id(item.text())}_{preview_token}.mp4"
        self.render_preview_btn.setEnabled(False)
        self.render_preview_btn.setText("正在轨道渲染…")
        settings=self._current_settings()
        settings["preview_cache_dir"] = str(preview_dir)
        # 带上当前时间轴拖动/切片结果（核心：不重跑分组合成）
        edit_state = dict(self.timeline_edit_states.get(video_key, {}) or {})
        settings["timeline_edits"] = edit_state
        matched=self._matched_source_for_video(item.text())
        if (matched and Path(matched).is_file() and Path(matched).resolve()!=Path(item.text()).resolve()
                and self._get_audio_mode_internal() in ("替换为添加的音频", "原声＋背景音混合")):
            settings["preview_audio"]=matched
            settings["preview_audio_offset_ms"]=self.audio_offsets.get(self._timeline_key(matched),0)
        # BGM：固定文件或文件夹随机
        bgm = self._timeline_bgm_path(item.text())
        if bgm and Path(bgm).is_file() and getattr(self, "bgm_enabled", None) and self.bgm_enabled.isChecked():
            settings["preview_bgm"] = bgm
            settings["bgm_enabled"] = True
            if hasattr(self, "bgm_selection_mode") and str(self.bgm_selection_mode.currentText()).startswith("随机"):
                settings["preview_bgm_offset_ms"] = random_bgm_start_ms(
                    ffmpeg, bgm, item.text(), 0, "preview_bgm"
                )
            elif hasattr(self, "audio_start_seek"):
                settings["preview_bgm_offset_ms"] = int(self.audio_start_seek.value() or 0)
        track_bits = []
        tracks = (edit_state.get("tracks") or {})
        if tracks.get("video"):
            track_bits.append(f"视频段×{len(tracks['video'])}")
        if tracks.get("tts"):
            track_bits.append(f"配音段×{len(tracks['tts'])}")
        if tracks.get("bgm"):
            track_bits.append(f"BGM段×{len(tracks['bgm'])}")
        if edit_state.get("transitions"):
            track_bits.append(f"转场×{len(edit_state['transitions'])}")
        self._append_run_log(
            "开始轨道渲染预览"
            + (f"（{', '.join(track_bits)}）" if track_bits else "（完整源片 + 当前字幕/水印）")
            + "… 不会重新跑分组合成。"
        )
        self.preview_thread=QThread(self)
        self.preview_worker=PreviewWorker(ffmpeg,item.text(),destination,text,settings)
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.started.connect(self.preview_worker.run)
        if hasattr(self.preview_worker, "log"):
            self.preview_worker.log.connect(self._append_run_log)
        self.preview_worker.finished.connect(self._effect_preview_done)
        self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self._preview_thread_ended)
        self.preview_thread.finished.connect(self.preview_thread.deleteLater)
        self.preview_thread.start()

    def _effect_preview_done(self, ok, result):
        self.render_preview_btn.setEnabled(True)
        self.render_preview_btn.setText("轨道渲染预览")
        if ok:
            self._precise_preview_files.add(str(result))
            self.load_video_preview(result, precise=True)
            # 预览生成后停在靠前有内容的画面，避免自动播完才发现效果
            QTimer.singleShot(220, lambda: self._pause_effect_preview_at(900))
            self.log.appendPlainText(f"轨道渲染预览已载入播放器：{result}")
        else:
            QMessageBox.critical(self,"轨道渲染预览失败",result)

    def _clear_precise_preview(self):
        """Return to source/live preview and remove generated preview clips."""
        item=self.videos.currentItem()
        if item:
            source=self._matched_source_for_video(item.text())
            mode=self._get_audio_mode_internal()
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
            self._append_run_log(f"已清除轨道预览，恢复源片实时预览。移除 {removed} 个临时文件。")
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
        if self._get_audio_mode_internal() == "替换为添加的音频":
            return self._matched_source_for_video(video_path)
        return str(video_path)

    def _video_selection_changed(self, video_path):
        if not video_path: return
        if hasattr(self,"task_queue") and self.videos.currentRow()>=0:
            self.task_queue.selectRow(self.videos.currentRow())
        
        # Save selection metadata immediately so UI labels update instantly
        source = self._matched_source_for_video(video_path)
        if hasattr(self,"combination_label"):
            saved = bool(self.free_texts.get(self._timeline_key(video_path),"").strip())
            self.combination_label.setText(
                f"当前任务组合：{Path(video_path).name}  ＋  {Path(source).name if source else '未匹配音频'}  ＋  "
                f"{'已保存文案' if saved else '待填写文案'}")
                
        # Debounce the heavy media loading to prevent QMediaPlayer deadlocks
        self._pending_video_path = video_path
        self._pending_video_source = source
        self.selection_debounce_timer.start()

    def _audio_selection_changed(self, source):
        if self._syncing_media_selection: return
        if not source:
            self._rematch_current_video(); return
            
        # Debounce audio loading
        self._pending_audio_source = source
        self.audio_debounce_timer.start()

    def _rematch_current_video(self, *_args):
        item=self.videos.currentItem() if hasattr(self,"videos") else None
        if item: self._video_selection_changed(item.text())

    def _bgm_folder_dropped(self, path):
        self.bgm_dir_input.setText(path)
        self._selected_bgm_path=""
        if hasattr(self,"bgm_source_display"):
            self.bgm_source_display.setText(str(Path(path).resolve()))
        if hasattr(self,"bgm_selection_mode"):
            self.bgm_selection_mode.setCurrentIndex(1)
        self._audio_mode_changed(self.audio_mode.currentText())
        self._load_first_bgm_preview(path)

    def _choose_bgm_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择背景音乐文件夹")
        if path:
            self.bgm_dir_input.setText(path)
            self._selected_bgm_path=""
            if hasattr(self,"bgm_source_display"):
                self.bgm_source_display.setText(str(Path(path).resolve()))
            if hasattr(self,"bgm_selection_mode"):
                self.bgm_selection_mode.setCurrentIndex(1)
            self._audio_mode_changed(self.audio_mode.currentText())
            self._load_first_bgm_preview(path)
            self._append_run_log("已添加背景音乐文件夹，将为任务随机选择音乐和起始点。")
            self._refresh_canva_timeline()

    def _load_first_bgm_preview(self, folder):
        path=Path(str(folder))
        if not path.is_dir():
            return
        candidates=sorted(
            (item for item in path.iterdir()
             if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS)),
            key=lambda item:natural_key(item.name),
        )
        if candidates:
            self.load_audio_preview(str(candidates[0]))

    def _audio_mode_changed(self, mode_text):
        mode = self._get_audio_mode_internal(mode_text)
        uses_bgm="背景音乐" in str(mode_text)
        self.bgm_enabled.setChecked(uses_bgm)
        self.audio_match_mode.setCurrentText("自动匹配（同名优先，其次按队列）")
        self.original_volume.setEnabled(uses_bgm and mode=="保留视频原音")
        self.background_volume.setEnabled(uses_bgm)
        self._update_preview_audio_levels()
        self._audio_fade_mode_changed(self.audio_fade_mode.currentText())
        self._refresh_live_preview()

    def _audio_fade_mode_changed(self, mode):
        external_mode=(
            self._get_audio_mode_internal()=="替换为添加的音频"
            or (hasattr(self,"bgm_enabled") and self.bgm_enabled.isChecked())
        )
        self.audio_fade_mode.setEnabled(external_mode)
        self.audio_fade_in.setEnabled(external_mode and mode in ("仅淡入","淡入＋淡出"))
        self.audio_fade_out.setEnabled(external_mode and mode in ("仅淡出","淡入＋淡出"))
        self._refresh_live_preview()

    def _update_preview_audio_levels(self, *_args):
        if not hasattr(self, "audio_output") or not hasattr(self, "audio_preview_output"):
            return
        if getattr(self, "audio_mode", None) and self._get_audio_mode_internal() == "原声＋背景音混合":
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
        if hasattr(self, "canva_timeline"):
            self.canva_timeline.set_srt(text)
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
            if hasattr(self, "canva_timeline"):
                self.canva_timeline.set_srt(self.override_text.toPlainText())
            return
        source=self._timeline_source()
        if source: self.timeline_overrides[self._timeline_key(source)]=self.override_text.toPlainText()
        if hasattr(self, "canva_timeline"):
            self.canva_timeline.set_srt(self.override_text.toPlainText())
        self._refresh_task_queue()

    def _timeline_track_srt_changed(self, text):
        """Apply edge drags from the visual track to the existing SRT source of truth."""
        if not hasattr(self, "override_text"):
            return
        self.override_text.setPlainText(str(text or ""))
        self._append_run_log("已从多轨时间轴更新字幕起止时间，并同步到 SRT 编辑器。")

    def _timeline_bgm_path(self, video_path):
        if hasattr(self,"bgm_enabled") and not self.bgm_enabled.isChecked():
            return ""
        if self._selected_bgm_path and Path(self._selected_bgm_path).is_file():
            return self._selected_bgm_path
        folder = self.bgm_dir_input.text().strip() if hasattr(self, "bgm_dir_input") else ""
        if folder and Path(folder).is_dir():
            for child in sorted(Path(folder).iterdir(), key=lambda item: natural_key(item.name)):
                if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS):
                    return str(child)
        return ""

    def _timeline_tts_path(self, video_path):
        source=self._matched_source_for_video(video_path)
        if source and Path(source).is_file() and Path(source).resolve()!=Path(video_path).resolve():
            return source
        return ""

    def _timeline_edit_changed(self, state):
        key=self._current_video_key()
        if key:
            self.timeline_edit_states[key]=dict(state or {})
            self._append_run_log(
                "时间轴已更新。点「轨道渲染预览」可听看调整结果；"
                "「重新合成选中组」才会整组重跑去口气合成。"
            )

    def _timeline_original_audio_changed(self, enabled):
        key=self._current_video_key()
        if key:
            state=dict(self.timeline_edit_states.get(key,{}) or {})
            state["original_audio_enabled"]=bool(enabled)
            self.timeline_edit_states[key]=state
        if not enabled and self._timeline_tts_path(key):
            self.audio_mode.setCurrentText("使用配音/添加的音频（消除视频原音，可另混背景音乐）")
        self._append_run_log("视频原声轨道已开启。" if enabled else "视频原声轨道已静音；导出时不会保留原视频声音。")

    def _refresh_canva_timeline_if_current(self, video_path: str):
        """仅当仍选中该视频时刷新，避免快速切换时迟到的定时器写错轨。"""
        if not video_path or not hasattr(self, "videos"):
            return
        item = self.videos.currentItem()
        if not item:
            return
        try:
            if self._timeline_key(item.text()) != self._timeline_key(video_path):
                return
        except Exception:
            if item.text() != video_path:
                return
        self._refresh_canva_timeline(video_path)

    def _resolve_timeline_duration_ms(self, video_path: str) -> int:
        """优先播放器时长（且路径匹配），否则缓存 / ffprobe，保证分段轨不必等预览解码。"""
        path = str(video_path or "")
        if not path:
            return 0
        video_key = self._timeline_key(path)
        player_ms = 0
        if hasattr(self, "player"):
            try:
                player_ms = int(self.player.duration() or 0)
            except Exception:
                player_ms = 0
        loaded = str(getattr(self, "_preview_loaded_path", "") or "")
        player_matches = False
        if player_ms > 0 and loaded:
            try:
                player_matches = self._timeline_key(loaded) == video_key
            except Exception:
                player_matches = Path(loaded).name == Path(path).name
        if player_ms > 0 and (player_matches or not loaded):
            self._media_duration_cache[video_key] = player_ms
            return player_ms
        cached = int(self._media_duration_cache.get(video_key) or 0)
        if cached > 0:
            return cached
        # sidecar 总时长作备选（不依赖 ffprobe）
        try:
            data = load_group_segments_map(path)
            if data:
                total = sum(max(0, int(s.get("duration_ms") or 0)) for s in (data.get("segments") or []))
                if total >= 200:
                    self._media_duration_cache[video_key] = total
                    return total
        except Exception:
            pass
        try:
            ff = self.find_ffmpeg()
            sec = float(media_duration(ff, path, fallback=0.0) or 0.0)
            if sec > 0.05:
                ms = max(1000, int(round(sec * 1000)))
                self._media_duration_cache[video_key] = ms
                return ms
        except Exception:
            pass
        return 0

    def _refresh_canva_timeline(self, video_path=""):
        if not hasattr(self, "canva_timeline") or not hasattr(self, "videos"):
            return
        if not video_path:
            item = self.videos.currentItem()
            video_path = item.text() if item else ""
        if not video_path:
            return
        # 若调用方指定了路径，但用户已切到别的视频，则忽略（防过期回调）
        current = self.videos.currentItem()
        if current:
            try:
                if self._timeline_key(current.text()) != self._timeline_key(video_path):
                    # 允许仅用当前项；过期的 path 直接丢弃
                    return
            except Exception:
                pass
        source = self._caption_source_for_video(video_path)
        key = self._timeline_key(source)
        srt = self.override_text.toPlainText() if hasattr(self, "override_text") else ""
        if key:
            srt = self.timeline_overrides.get(key, srt)
        duration = self._resolve_timeline_duration_ms(video_path)
        video_key = self._timeline_key(video_path)
        edit_state = dict(self.timeline_edit_states.get(video_key, {}) or {})
        is_group_output = any(
            self._timeline_key(path) == video_key
            for path in getattr(self, "group_merge_outputs", [])
        ) or Path(video_path).name.endswith("去口气音合成.mp4") or Path(video_path).name.endswith("_去口气音合成.mp4")
        # Prefer segmented bars (one bar per original clip) when sidecar exists.
        # Do not overwrite if user already has multi-segment custom layout.
        existing_video = list((edit_state.get("tracks") or {}).get("video") or [])
        # 时长尚未就绪时也允许先拆段（用 sidecar 合计），避免必须来回切换
        can_auto_segment = (
            (not edit_state.get("segmented"))
            and len(existing_video) <= 1
        )
        if can_auto_segment:
            # 旧成品无 sidecar 时，尝试从 .group_merge_cache 恢复分段（有 json 则很快）
            try:
                try:
                    ff = self.find_ffmpeg()
                except Exception:
                    ff = None
                try_rebuild_segments_sidecar(video_path, ffmpeg=ff)
            except Exception:
                pass
            if duration <= 0:
                try:
                    data = load_group_segments_map(video_path)
                    if data:
                        duration = max(
                            1000,
                            sum(max(80, int(s.get("duration_ms") or 0)) for s in (data.get("segments") or [])),
                        )
                except Exception:
                    pass
            segmented = build_segmented_edit_state(
                video_path, max(duration, 1000), original_audio_enabled=True,
            )
            if segmented:
                edit_state = segmented
                self.timeline_edit_states[video_key] = dict(edit_state)
                # 只在首次拆段时记日志，避免 duration 回调刷屏
                if not getattr(self, "_segment_log_keys", None):
                    self._segment_log_keys = set()
                if video_key not in self._segment_log_keys:
                    self._segment_log_keys.add(video_key)
                    self._append_run_log(
                        f"时间轴已按合成段落拆分：{len(segmented['tracks']['video'])} 段视频/音频，"
                        "可单独拖动有问题的一段（两端恢复内容、中间改位置）。"
                        "最终导出仍是一个完整视频，分段仅便于编辑定位。"
                    )
            elif is_group_output and not existing_video and duration > 0:
                edit_state = {
                    "duration_ms": duration,
                    "original_audio_enabled": True,
                    "tracks": {
                        "video": [{"start": 0, "end": duration, "source_start": 0, "source_end": duration,
                                   "source_duration": duration, "name": Path(video_path).name}],
                        "original_audio": [{"start": 0, "end": duration, "source_start": 0, "source_end": duration,
                                            "source_duration": duration, "name": "视频原声"}],
                        "bgm": [], "tts": [],
                    },
                }
                self.timeline_edit_states[video_key] = edit_state
        elif edit_state.get("segmented") and duration > 0:
            # 已有分段但时长更新：按真实时长重算条宽，避免第一次用了近似时长
            prev = int(edit_state.get("duration_ms") or 0)
            if prev > 0 and abs(prev - duration) > 80:
                rebuilt = build_segmented_edit_state(
                    video_path, duration, original_audio_enabled=True,
                )
                if rebuilt and len((rebuilt.get("tracks") or {}).get("video") or []) == len(existing_video):
                    # 保留用户若只改了名字等；这里以重算为准（未手改 source 时最稳）
                    # 若用户已微调过多段，不覆盖（条数相同且 segmented 但有手动痕迹较难判断：仅当尚未手改 source 偏移）
                    user_tweaked = False
                    for bar in existing_video:
                        if int(bar.get("start", 0)) != int(bar.get("source_start", 0)):
                            user_tweaked = True
                            break
                        if int(bar.get("end", 0)) - int(bar.get("start", 0)) != int(bar.get("source_end", 0)) - int(bar.get("source_start", 0)):
                            user_tweaked = True
                            break
                    if not user_tweaked:
                        edit_state = rebuilt
                        self.timeline_edit_states[video_key] = dict(edit_state)
        if duration <= 0:
            duration = max(1000, int(edit_state.get("duration_ms") or 0), 1000)
        original_audio_enabled = bool(edit_state.get("original_audio_enabled", not is_group_output))
        self.canva_timeline.set_project(
            video_path,
            duration,
            srt,
            self._timeline_bgm_path(video_path),
            self._timeline_tts_path(video_path),
            original_audio_enabled,
            edit_state,
        )

    def _current_timeline_srt_text(self):
        """Return current editable SRT (override / timestamp view / word group)."""
        timeline = ""
        if hasattr(self, "timeline_timestamp_view"):
            timeline = self.timeline_timestamp_view.toPlainText().strip()
        if "-->" not in timeline and hasattr(self, "override_text"):
            timeline = self.override_text.toPlainText().strip()
        source = self._timeline_source()
        key = self._timeline_key(source) if source else ""
        if "-->" not in timeline and key:
            timeline = (
                self.timeline_overrides.get(key, "")
                or self._group_words_for_current_layout(self.timeline_words.get(key, ""))
            )
        return timeline or ""

    def _open_script_proofread_dialog(self):
        timeline = self._current_timeline_srt_text()
        if "-->" not in timeline:
            QMessageBox.information(
                self, "没有时间轴",
                "请先提取当前素材字幕或载入 SRT，再使用文案校对。\n"
                "校对只替换文字，时间戳保持音频识别结果。",
            )
            return
        preset = ""
        if hasattr(self, "source_proofread"):
            preset = self.source_proofread.toPlainText().strip()
        dialog = ScriptProofreadDialog(self, timeline_srt=timeline, preset_source=preset)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        corrected = dialog.result_srt()
        if not corrected or "-->" not in corrected:
            return
        changes = dialog.result_change_count()
        self._loading_timeline = True
        try:
            if hasattr(self, "override_text"):
                self.override_text.setPlainText(corrected)
            if hasattr(self, "timeline_timestamp_view"):
                self.timeline_timestamp_view.blockSignals(True)
                self.timeline_timestamp_view.setPlainText(corrected)
                self.timeline_timestamp_view.blockSignals(False)
        finally:
            self._loading_timeline = False
        source = self._timeline_source()
        key = self._timeline_key(source) if source else ""
        if key:
            self.timeline_overrides[key] = corrected
        if hasattr(self, "source_proofread"):
            self.source_proofread.setPlainText(dialog.source_script())
        if hasattr(self, "canva_timeline"):
            self.canva_timeline.set_srt(corrected)
        self._refresh_task_queue()
        self._refresh_live_preview()
        name = Path(source).name if source else "当前素材"
        self._append_run_log(
            f"文案校对已提交：{name}，共 {changes} 处文字修改，时间戳未改动。"
        )

    def _apply_source_proofread(self):
        """Legacy tab path：无对比弹窗，直接按源文案覆盖（仍保留时间戳）。"""
        source_copy = self.source_proofread.toPlainText().strip() if hasattr(self, "source_proofread") else ""
        if not source_copy:
            self._open_script_proofread_dialog()
            return
        timeline = self._current_timeline_srt_text()
        if "-->" not in timeline:
            QMessageBox.information(self, "没有时间轴", "请先提取当前素材字幕或载入 SRT，再使用源文案校对。")
            return
        lang = None
        try:
            lang = writing_language_from_ui(self.writing_language.currentText()) if hasattr(self, "writing_language") else None
        except Exception:
            lang = None
        corrected, changes = proofread_srt_keep_timestamps(
            timeline, normalize_required_capitalization(source_copy), language=lang,
        )
        self._loading_timeline = True
        try:
            self.override_text.setPlainText(corrected)
        finally:
            self._loading_timeline = False
        source = self._timeline_source()
        key = self._timeline_key(source) if source else ""
        if key:
            self.timeline_overrides[key] = corrected
        if hasattr(self, "canva_timeline"):
            self.canva_timeline.set_srt(corrected)
        self._refresh_task_queue()
        self._refresh_live_preview()
        self._append_run_log(
            f"已用源文案校对字幕并保留原时间轴：{Path(source).name if source else '当前素材'}"
            f"（{len(changes)} 处修改）"
        )

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
        if not videos:
            QMessageBox.information(self,"没有视频","请先添加需要批量处理的视频素材。")
            return
        self._extract_timelines_for_paths(videos)

    def _extract_timelines_for_paths(self, video_paths):
        """仅为指定视频提取字幕，其它条目的 timeline_overrides 不动。"""
        videos = [str(p) for p in (video_paths or []) if p and Path(p).is_file()]
        if not videos:
            return
        if self.timeline_thread and self.timeline_thread.isRunning():
            return
        sources = []
        for video in videos:
            value = self._caption_source_for_video(video)
            if value and value not in sources:
                sources.append(value)
        if not sources:
            return
        provider = self.provider.currentText()
        callback = lambda path: self.transcribe_callable(path, provider)
        self.extract_timeline_btn.setEnabled(False)
        self.extract_all_btn.setEnabled(False)
        self.extract_all_btn.setText(f"排队提取 0/{len(sources)}")
        self.timeline_thread = QThread(self)
        self.timeline_worker = BatchTimelineWorker(callback, sources, self.output.text())
        self.timeline_worker.moveToThread(self.timeline_thread)
        self.timeline_thread.started.connect(self.timeline_worker.run)
        self.timeline_worker.item_started.connect(self._batch_timeline_item_started)
        self.timeline_worker.item_done.connect(self._batch_timeline_item_done)
        self.timeline_worker.item_failed.connect(self._batch_timeline_item_failed)
        self.timeline_worker.finished.connect(self._batch_timeline_done)
        self.timeline_worker.finished.connect(self.timeline_thread.quit)
        self.timeline_thread.finished.connect(self._timeline_ended)
        self.timeline_thread.finished.connect(self.timeline_thread.deleteLater)
        self._append_run_log(
            f"已建立字幕队列：{len(sources)} 个素材（仅本次列表，其它组字幕保留）。"
        )
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
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            self.free_texts[key]=phrase_srt
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
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            self.free_texts[key]=phrase_srt
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
                if self.caption_mode.currentText() == "自由文案动画（不对口型）":
                    self.free_texts[key]=phrase_srt
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
            if source:
                key=self._timeline_key(source)
                self.timeline_overrides[key]=text
                if self.caption_mode.currentText() == "自由文案动画（不对口型）":
                    self.free_texts[key]=text
            self._append_run_log(f"已载入 SRT：{Path(path).name}"
                                 +(f"，并自动修正 {fixes} 处时间重叠。" if fixes else "，未检测到时间重叠。"))
        except Exception as exc: QMessageBox.critical(self,"无法读取字幕",str(exc))

    def _choose_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频与图片素材", "",
            "视频与图片 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.png *.jpg *.jpeg *.webp);;视频 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;图片 (*.png *.jpg *.jpeg *.webp)"
        )
        self._add(self.videos, files, ALLOWED_VIDEO_INPUTS)

    def _choose_audio(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频", "", "音频 (*.mp3 *.wav *.m4a *.flac *.aac *.ogg *.opus)"); self._add(self.audios, files, AUDIO_EXTENSIONS)

    def _choose_folder(self, widget, extensions):
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if folder: self._add(widget, [folder], extensions)

    def generate_tts(self):
        scripts = []
        for r in range(self.tts_text.rowCount()):
            item = self.tts_text.item(r, 1)
            if item and item.text().strip():
                scripts.append(item.text().strip())
        if not scripts:
            QMessageBox.information(self, "没有文案", "请先输入需要转成语音的文案。")
            return
        videos = [Path(self.videos.item(i).text()) for i in range(self.videos.count())]
        if videos and len(scripts) not in (1, len(videos)):
            QMessageBox.warning(
                self, "文案数量不匹配",
                f"当前有 {len(videos)} 个视频、{len(scripts)} 段文案。\n"
                "请让文案数量与视频一致。\n"
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
        if getattr(self, "tts_thread", None):
            try:
                if self.tts_thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前配音任务结束。")
                    return
            except RuntimeError:
                self.tts_thread = None
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
        if preset["effect"] == "word_color":
            highlight_label = "跟读文字"
        elif preset["effect"] in ("semantic_stack", "word_scale"):
            highlight_label = "重点词"
        else:
            highlight_label = "跟读背景"
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
        if hasattr(self, "position"):
            self.position.setCurrentText(preset.get("position", "底部"))
        # 出字方式类预设：一并切换字幕模式（如语音同步）
        if "caption_mode" in preset and hasattr(self, "caption_mode"):
            self.caption_mode.setCurrentText(preset["caption_mode"])
        if "free_animation" in preset and hasattr(self, "free_animation"):
            self.free_animation.setCurrentText(preset["free_animation"])
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
                      if item.is_file() and item.suffix.casefold() in ALLOWED_VIDEO_INPUTS]
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
                if item.is_file() and item.suffix.casefold() in ALLOWED_VIDEO_INPUTS]
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
        self._bump_preview_token()
        self._pending_preview_load = None
        if hasattr(self, "selection_debounce_timer"):
            self.selection_debounce_timer.stop()
        if hasattr(self, "audio_debounce_timer"):
            self.audio_debounce_timer.stop()
        self._pending_video_path = None
        self._release_preview_media(
            placeholder="正在执行任务，预览已暂停以释放文件…",
            suppress_ms=200,
        )

    def run(self):
        videos = [self.videos.item(i).text() for i in range(self.videos.count())]
        audios = [self.audios.item(i).text() for i in range(self.audios.count())]
        if not videos: QMessageBox.information(self, "没有视频", "请先添加视频素材。"); return
        if getattr(self, "thread", None):
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前批量导出结束，或先点停止。")
                    return
            except RuntimeError:
                self.thread = None
        self._clear_previews_and_releases()
        try: ffmpeg = self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self, "缺少组件", str(exc)); return
        settings = self._current_settings(); self.generated_records = []; self._batch_expected_count=len(videos)
        # 只有 00_分组合成 中的全部中间视频都进入本次渲染队列，
        # 才在全部最终成品成功后删除目录，避免误删未处理的组。
        group_dir=(Path(self.output.text()).expanduser()/"00_分组合成").resolve()
        queued_group={str(Path(path).resolve()) for path in videos if Path(path).resolve().parent==group_dir}
        existing_group=({str(path.resolve()) for path in group_dir.iterdir()
                         if path.is_file() and path.suffix.casefold() in ALLOWED_VIDEO_INPUTS}
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
        self.generated_records.append({
            "path": str(path),
            "original": str(original or ""),
            "chinese": str(chinese or ""),
            "language": self.writing_language.currentText()
        })

    def done(self, ok, message):
        self.start.setEnabled(True); self.stop.setEnabled(False); self._append_run_log(message)
        self.group_merge_start.setEnabled(True); self.group_merge_stop.setEnabled(False)
        self.run_status.setText("当前状态：已完成" if ok else "当前状态：执行失败，请到“帮助 → 软件日志”查看")
        self._cleanup_completed_group_intermediates(ok)
        # 一批批量导出结束后清空自定义标题，避免下一批误用上一批文案、重复命名。
        if ok and hasattr(self, "rename_custom_titles"):
            previous = self.rename_custom_titles.toPlainText().strip()
            self.rename_custom_titles.clear()
            if previous:
                self._append_run_log("本批导出完成，已清空「自定义标题列表」；下一批请重新粘贴文案。")
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
            # 先停预览，避免 WinError 32 占用 .watermark_cache / 中间 mp4
            self._clear_previews_and_releases()
            try:
                if hasattr(self, "player"):
                    self.player.stop()
                    self.player.setSource(QUrl())
                if hasattr(self, "audio_player"):
                    self.audio_player.stop()
                    self.audio_player.setSource(QUrl())
                if hasattr(self, "bgm_player"):
                    self.bgm_player.stop()
                    self.bgm_player.setSource(QUrl())
            except Exception:
                pass
            import gc
            gc.collect()
            import time
            folder = Path(folder)
            last_exc = None
            for i in range(8):
                try:
                    if not folder.exists():
                        last_exc = None
                        break
                    # 先尽量删文件，再删目录（减少整树 rmtree 被单个锁文件卡死）
                    for root, dirs, files in os.walk(folder, topdown=False):
                        for name in files:
                            path = Path(root) / name
                            try:
                                path.unlink(missing_ok=True)
                            except OSError:
                                pass
                        for name in dirs:
                            try:
                                (Path(root) / name).rmdir()
                            except OSError:
                                pass
                    try:
                        folder.rmdir()
                    except OSError:
                        shutil.rmtree(folder, ignore_errors=True)
                    if not folder.exists():
                        last_exc = None
                        break
                    last_exc = OSError(f"目录仍存在：{folder}")
                except OSError as exc:
                    last_exc = exc
                time.sleep(0.25 + i * 0.15)
            if last_exc is not None and folder.exists():
                # 不把「有几个缓存删不掉」当成失败：成品已在
                self._append_run_log(
                    f"最终成品已全部生成。中间目录部分文件仍被占用未删净（可稍后手动删 "
                    f"00_分组合成）：{last_exc}"
                )
                write_app_log(f"清理分组合成中间目录部分失败：{folder}｜{last_exc}", "WARN", "Reels")
            else:
                self._append_run_log(
                    "最终成品已全部生成；已自动清理 00_分组合成 中间视频与断点缓存，输出目录只保留最终成品。"
                )
            removed={str(Path(path).resolve()) for path in self.group_merge_outputs}
            self.group_merge_outputs=[]
            for key in list(self._baked_watermarks):
                if key in removed: self._baked_watermarks.pop(key,None)
            QSettings("VideoToolkit","DynamicReels").setValue(
                "baked_watermarks",json.dumps(self._baked_watermarks,ensure_ascii=False))
            return True
        except OSError as exc:
            self._append_run_log(f"最终成品已生成，但中间目录自动清理失败：{exc}")
            write_app_log(f"清理分组合成中间目录失败：{folder}｜{exc}","ERROR","Reels")
            return False

    def ended(self): self.worker = None; self.thread = None

    def _choose_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片素材", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        self._add(self.images, files, IMAGE_EXTENSIONS)

    def generate_image_slideshow(self):
        images = [self.images.item(i).text() for i in range(self.images.count())]
        if not images:
            QMessageBox.information(self, "没有图片", "请先在图片列表中添加要转场生成视频的图片素材。")
            return
        
        try:
            ffmpeg = self.find_ffmpeg()
        except Exception as exc:
            QMessageBox.critical(self, "缺少组件", str(exc))
            return
            
        dest_dir = Path(self.output.text()) / "00_幻灯片生成"
        dest_dir.mkdir(parents=True, exist_ok=True)
        import time
        dest_file = dest_dir / f"slideshow_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        
        self.img_generate.setEnabled(False)
        self.img_generate.setText("正在生成转场视频…")
        
        self._slideshow_thread = QThread(self)
        self._slideshow_worker = SlideshowWorker(
            ffmpeg=ffmpeg,
            images=images,
            destination=dest_file,
            single_dur=self.img_duration.value(),
            transition_name=self.img_transition.currentText(),
            transition_dur=self.img_trans_dur.value(),
            animation_name=self.img_animation.currentText(),
            settings=self._current_settings()
        )
        self._slideshow_worker.moveToThread(self._slideshow_thread)
        self._slideshow_thread.started.connect(self._slideshow_worker.run)
        self._slideshow_worker.log.connect(self._append_run_log)
        self._slideshow_worker.finished.connect(self._on_slideshow_finished)
        self._slideshow_worker.finished.connect(self._slideshow_thread.quit)
        self._slideshow_thread.finished.connect(self._slideshow_thread.deleteLater)
        self._slideshow_thread.start()

    def _on_slideshow_finished(self, ok, result):
        self.img_generate.setEnabled(True)
        self.img_generate.setText("生成幻灯片视频并入队")
        if ok:
            QMessageBox.information(self, "生成成功", f"转场视频已成功生成并自动加入到了视频素材队列：\n{Path(result).name}")
            self._add(self.videos, [result], ALLOWED_VIDEO_INPUTS)
            # Switch view to video tab to show it's queued
            self._show_source_tool(1)
        else:
            QMessageBox.critical(self, "生成失败", f"转场视频生成失败：\n{result}")

    def _on_proj_tts_service_changed(self, text):
        try:
            if hasattr(self, "tts_service") and self.tts_service and self.tts_service.currentText() != text:
                self.tts_service.setCurrentText(text)
        except RuntimeError:
            pass
            
    def _on_proj_tts_voice_changed(self, text):
        try:
            if hasattr(self, "tts_voice") and self.tts_voice and self.tts_voice.currentText() != text:
                self.tts_voice.setCurrentText(text)
        except RuntimeError:
            pass
            
    def _on_global_tts_service_changed(self, text):
        try:
            if hasattr(self, "proj_tts_service") and self.proj_tts_service:
                self.proj_tts_service.blockSignals(True)
                self.proj_tts_service.setCurrentText(text)
                self.proj_tts_service.blockSignals(False)
        except RuntimeError:
            pass
            
        # Repopulate project voices dropdown
        try:
            if hasattr(self, "proj_tts_voice") and self.proj_tts_voice and hasattr(self, "tts_voice") and self.tts_voice:
                self.proj_tts_voice.blockSignals(True)
                self.proj_tts_voice.clear()
                for idx in range(self.tts_voice.count()):
                    self.proj_tts_voice.addItem(self.tts_voice.itemText(idx))
                self.proj_tts_voice.setCurrentText(self.tts_voice.currentText())
                self.proj_tts_voice.blockSignals(False)
        except RuntimeError:
            pass
            
    def _on_global_tts_voice_changed(self, text):
        try:
            if hasattr(self, "proj_tts_voice") and self.proj_tts_voice:
                self.proj_tts_voice.blockSignals(True)
                self.proj_tts_voice.setCurrentText(text)
                self.proj_tts_voice.blockSignals(False)
        except RuntimeError:
            pass

    def _add_project_dialog(self):
        dialog = ProjectAddDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data_list = dialog.get_data()
            added = 0
            
            # If the main table only has one row and it's completely empty, remove it first
            is_empty_table = (self.project_table.rowCount() == 1 and
                              (not self.project_table.item(0, 1) or not self.project_table.item(0, 1).text().strip()) and
                              (not self.project_table.item(0, 2) or not self.project_table.item(0, 2).text().strip()))
            if is_empty_table:
                self.project_table.setRowCount(0)
                
            for data in data_list:
                if not data["script"].strip():
                    continue
                self._add_project_row(
                    name=data["name"],
                    script=data["script"],
                    materials=";".join(data["materials"]),
                    bgm=data["bgm"],
                    dim=data["dim"]
                )
                added += 1
            if added:
                self._append_run_log(f"已批量新增 {added} 个项目组到任务列表中。")

    def _on_project_tab_dropped(self, files):
        if files:
            name = f"video_{time.strftime('%Y%m%d_%H%M%S')}"
            self._add_project_row(name=name, materials=";".join(files))
            self._show_source_tool(2)



    def _delete_selected_projects(self):
        selected_ranges = self.project_table.selectedRanges()
        if not selected_ranges:
            return
        rows_to_remove = set()
        for r in selected_ranges:
            for row in range(r.topRow(), r.bottomRow() + 1):
                rows_to_remove.add(row)
        for row in sorted(rows_to_remove, reverse=True):
            self.project_table.removeRow(row)
        self._refresh_project_script_edit()

    def _clear_projects(self):
        if self.project_table.rowCount() == 0:
            return
        reply = QMessageBox.question(self, "确认清空", "是否确定清空所有项目组列表？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.project_table.setRowCount(0)
            self._add_project_row()

    def _batch_import_project_external_audio(self):
        """Assign multiple pre-made audio files to consecutive project rows as script=path."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "批量选择外部配音音频", "",
            "音频文件 (*.mp3 *.wav *.aac *.ogg *.m4a *.flac *.opus)"
        )
        if not files:
            return
        files = sorted(files, key=lambda p: natural_key(Path(p).name))
        while self.project_table.rowCount() < len(files):
            self._add_project_row()
        for i, path in enumerate(files):
            # Column 1 = script / external audio path
            item = self.project_table.item(i, 1)
            if item is None:
                item = QTableWidgetItem()
                self.project_table.setItem(i, 1, item)
            item.setText(path)
            name_item = self.project_table.item(i, 0)
            if name_item is None:
                name_item = QTableWidgetItem()
                self.project_table.setItem(i, 0, name_item)
            cur_name = name_item.text().strip()
            if not cur_name or cur_name.startswith("video_") or cur_name.startswith("项目"):
                name_item.setText(Path(path).stem)
        self._refresh_project_script_edit()
        QMessageBox.information(
            self, "批量导入完成",
            f"已写入 {len(files)} 条外部配音路径到「语音文案」列。\n"
            "合成时将跳过文字转语音，直接使用这些音频。",
        )

    def _project_cell_double_clicked(self, row, col):
        if col == 2:  # Materials
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择该项目的图片/视频素材", "",
                "素材 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.avi *.mov *.mkv)"
            )
            if files:
                item = self.project_table.item(row, col)
                if not item:
                    item = QTableWidgetItem()
                    self.project_table.setItem(row, col, item)
                item.setText(";".join(files))
        elif col == 3:  # BGM
            file, _ = QFileDialog.getOpenFileName(
                self, "选择背景音乐", "",
                "音频 (*.mp3 *.wav *.aac *.ogg)"
            )
            if file:
                item = self.project_table.item(row, col)
                if not item:
                    item = QTableWidgetItem()
                    self.project_table.setItem(row, col, item)
                item.setText(file)

    def _project_current_cell_changed(self, currentRow, currentColumn, previousRow, previousColumn):
        self._refresh_project_script_edit()

    def _refresh_project_script_edit(self):
        row = self.project_table.currentRow()
        if row >= 0:
            script_item = self.project_table.item(row, 1)
            script_text = script_item.text() if script_item else ""
            self._updating_project_script = True
            try:
                self.project_script_edit.setPlainText(script_text)
            finally:
                self._updating_project_script = False
        else:
            self.project_script_edit.clear()

    def _project_script_edit_changed(self):
        if getattr(self, "_updating_project_script", False):
            return
        row = self.project_table.currentRow()
        if row >= 0:
            item = self.project_table.item(row, 1)
            if not item:
                item = QTableWidgetItem()
                self.project_table.setItem(row, 1, item)
            item.setText(self.project_script_edit.toPlainText())

    def _add_project_row(self, name="", script="", materials="", bgm="随机分配 (全局BGM)", dim="9:16"):
        row = self.project_table.rowCount()
        self.project_table.insertRow(row)
        if not name:
            name = f"video_{time.strftime('%Y%m%d_%H%M%S')}_{row+1}"
        item_name = QTableWidgetItem(name)
        self.project_table.setItem(row, 0, item_name)
        item_script = QTableWidgetItem(script)
        self.project_table.setItem(row, 1, item_script)
        item_materials = QTableWidgetItem(materials)
        item_materials.setToolTip("双击选择图片/视频素材；或将文件直接拖入此行")
        self.project_table.setItem(row, 2, item_materials)
        item_bgm = QTableWidgetItem(bgm)
        self.project_table.setItem(row, 3, item_bgm)
        dim_combo = QComboBox()
        dim_combo.addItems(["9:16", "16:9", "1:1", "4:3"])
        dim_combo.setCurrentText(dim)
        self.project_table.setCellWidget(row, 4, dim_combo)
        item_status = QTableWidgetItem("等待")
        self.project_table.setItem(row, 5, item_status)

    def _paste_projects_from_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            QMessageBox.information(self, "剪贴板为空", "请先从 Excel/WPS 复制项目数据。")
            return
        rows = text.split("\n")
        added_count = 0
        for row_str in rows:
            if not row_str.strip():
                continue
            cols = row_str.split("\t")
            name = f"video_{time.strftime('%Y%m%d_%H%M%S')}_{added_count+1}"
            script = ""
            materials = ""
            bgm = "随机分配 (全局BGM)"
            dim = "9:16"
            
            if len(cols) >= 1:
                if len(cols) == 1:
                    script = cols[0].strip()
                else:
                    name = cols[0].strip() or name
                    script = cols[1].strip()
            if len(cols) >= 3:
                materials = cols[2].strip()
            if len(cols) >= 4:
                bgm = cols[3].strip() or bgm
            if len(cols) >= 5:
                dim = cols[4].strip() or dim
            
            # Clean paths
            if materials:
                materials = materials.strip('"').strip("'")
            if bgm:
                bgm = bgm.strip('"').strip("'")
                
            self._add_project_row(name, script, materials, bgm, dim)
            added_count += 1
        self._append_run_log(f"已从剪贴板自动导入 {added_count} 个项目。")

    def start_project_synthesis(self):
        if getattr(self, "_project_thread", None):
            try:
                if self._project_thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前大片合成任务结束。")
                    return
            except RuntimeError:
                self._project_thread = None
        projects = []
        for r in range(self.project_table.rowCount()):
            name_item = self.project_table.item(r, 0)
            name = name_item.text().strip() if name_item else ""
            script_item = self.project_table.item(r, 1)
            script = script_item.text().strip() if script_item else ""
            materials_item = self.project_table.item(r, 2)
            materials_str = materials_item.text().strip() if materials_item else ""
            bgm_item = self.project_table.item(r, 3)
            bgm = bgm_item.text().strip() if bgm_item else ""
            dim_combo = self.project_table.cellWidget(r, 4)
            dim = dim_combo.currentText() if dim_combo else "9:16"
            
            if not script:
                continue
            
            m_list = []
            if materials_str:
                m_list = [p.strip() for p in materials_str.split(";") if p.strip()]
                if len(m_list) == 1 and Path(m_list[0]).is_dir():
                    m_list = collect_files([m_list[0]], ALLOWED_VIDEO_INPUTS)
            
            projects.append({
                "row_idx": r,
                "name": name,
                "script": script,
                "materials": m_list,
                "bgm": bgm,
                "dim": dim
            })
            
        if not projects:
            QMessageBox.information(self, "没有任务", "项目列表中没有需要生成的有效任务行。")
            return
            
        try:
            ffmpeg = self.find_ffmpeg()
        except Exception as exc:
            QMessageBox.critical(self, "缺少组件", str(exc))
            return
            
        settings = self._current_settings()
        settings["image_animation"] = self.proj_img_animation.currentText()
        settings["transition_name"] = self.proj_img_transition.currentText()
        settings["transition_duration"] = self.proj_transition_dur.value()
        settings["provider"] = self.provider.currentText()
        
        # Read the shared BGM folder from the right settings panel directly
        bgm_dir = self.bgm_dir_input.text().strip()
        
        # Retrieve the API key from the global Key Store if Luma or Kling is selected
        ai_service = self.proj_ai_service.currentText()
        ai_key = ""
        if ai_service == "Luma API":
            if not self.store:
                QMessageBox.warning(self, "缺少组件", "未检测到有效的密钥存储组件！")
                return
            candidates = self.store.candidates("Luma")
            if not candidates:
                QMessageBox.warning(self, "缺少密钥", "未在“API密钥管理”中检测到有效的 Luma API 密钥，请先添加！")
                return
            ai_key = candidates[0]["key"]
        elif ai_service == "Kling API (可灵)":
            if not self.store:
                QMessageBox.warning(self, "缺少组件", "未检测到有效的密钥存储组件！")
                return
            candidates = self.store.candidates("Kling")
            if not candidates:
                QMessageBox.warning(self, "缺少密钥", "未在“API密钥管理”中检测到有效的 Kling API 密钥，请先添加！")
                return
            ai_key = candidates[0]["key"]
            
        settings["proj_ai_service"] = ai_service
        settings["proj_ai_key"] = ai_key
        
        # Setup watermark details for project synthesis
        watermark_fingerprint = watermark_config_fingerprint(self._watermark_entries)
        burn_watermark = bool(self.proj_burn_watermark.isChecked() and watermark_fingerprint)
        if self.proj_burn_watermark.isChecked() and not watermark_fingerprint:
            self._append_run_log("已勾选项目成片时烧录水印，但没有有效水印图片，本次按无水印合成。")
        settings["burn_watermark"] = burn_watermark
        if burn_watermark:
            watermark_entries = [dict(item) for item in self._watermark_entries]
            settings["watermark_prepare"] = (
                lambda video, cache, entries=watermark_entries:
                str(prepared_watermark_composite(ffmpeg, video, entries, cache))
            )
            
        self._clear_previews_and_releases()
        self.project_start_btn.setEnabled(False)
        self.project_stop_btn.setEnabled(True)
        
        self._project_thread = QThread(self)
        self._project_worker = ProjectGroupWorker(
            ffmpeg=ffmpeg,
            ffprobe=str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)),
            tts_callable=self.tts_callable,
            transcribe_callable=self.transcribe_callable,
            tts_service=self.tts_service.currentText(),
            tts_voice=self.tts_voice.currentText(),
            tts_speed=getattr(self, "tts_speed", None),
            bgm_dir=bgm_dir,
            projects=projects,
            settings=settings
        )
        self._project_worker.moveToThread(self._project_thread)
        self._project_thread.started.connect(self._project_worker.run)
        self._project_worker.log.connect(self._append_run_log)
        self._project_worker.progress.connect(self._on_project_progress)
        self._project_worker.item_done.connect(self._on_project_item_done)
        self._project_worker.finished.connect(self._on_project_finished)
        self._project_worker.finished.connect(self._project_thread.quit)
        self._project_thread.finished.connect(self._project_thread.deleteLater)
        self._project_thread.start()

    def stop_project_synthesis(self):
        if hasattr(self, "_project_worker") and self._project_worker:
            self._project_worker.cancel()
        self.stop_project_synthesis_btn()

    def stop_project_synthesis_btn(self):
        self.project_start_btn.setEnabled(True)
        self.project_stop_btn.setEnabled(False)
        if hasattr(self,"group_merge_start"): self.group_merge_start.setEnabled(True)
        if hasattr(self,"group_merge_stop"): self.group_merge_stop.setEnabled(False)

    def _on_project_progress(self, val):
        self.project_start_btn.setText("合成中")

    def _on_project_item_done(self, output_file, name, srt):
        for r in range(self.project_table.rowCount()):
            name_item = self.project_table.item(r, 0)
            if name_item and name_item.text().strip() == name:
                self.project_table.setItem(r, 5, QTableWidgetItem("成功"))
                break
        
        self._add(self.videos, [output_file], ALLOWED_VIDEO_INPUTS)
        
        key = self._timeline_key(str(Path(output_file).resolve()))
        self.timeline_words[key] = srt
        self.timeline_chinese[key] = ""
        
        # Default audio mode to keep original sound (since TTS + BGM are already mixed in project synthesis)
        self.audio_mode.setCurrentText("仅保留视频原音（无配音/无BGM）")
        
        for i in range(self.videos.count()):
            if self.videos.item(i).text() == str(output_file):
                self.videos.setCurrentRow(i)
                break

    def _on_project_finished(self, ok, message):
        self.stop_project_synthesis_btn()
        self.project_start_btn.setText("合成")
        if ok:
            QMessageBox.information(self, "批量成片完成", message)
            self._show_source_tool(1)
        else:
            QMessageBox.critical(self, "成片失败", f"批量制作发生错误：\n{message}")



    def _record_group_merge_history(
        self, group_name, clip_count, output_name,
        segment_durations=None, output_duration_sec=0.0,
    ):
        try:
            from modules.platform_utils import app_data_dir
            history_path = app_data_dir() / "group_merge_history.json"
            history = []
            if history_path.is_file():
                try:
                    history = json.loads(history_path.read_text(encoding="utf-8"))
                except Exception:
                    history = []
            import datetime
            now = datetime.datetime.now()
            segments = list(segment_durations or [])
            entry = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "group_name": group_name,
                "clip_count": clip_count,
                "output_name": output_name,
                "segment_durations": segments,
                "output_duration_sec": float(output_duration_sec or 0.0),
                "segments_total_sec": round(
                    sum(float(s.get("duration_sec") or 0) for s in segments), 3
                ),
            }
            history.append(entry)
            history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            if hasattr(self, "_append_run_log"):
                self._append_run_log(f"记录分组合成历史失败：{exc}")

    def _show_group_merge_report(self):
        dialog = GroupMergeReportDialog(self)
        dialog.exec()

    def _on_player_playback_state_changed(self, state):
        if state != QMediaPlayer.PlaybackState.PlayingState:
            if getattr(self, "_preview_external_audio", False):
                self.audio_player.pause()
            if getattr(self, "_preview_bgm_active", False) and hasattr(self, "bgm_player"):
                self.bgm_player.pause()
            self.play_btn.setText("播放")
        else:
            if getattr(self, "_preview_external_audio", False):
                self.audio_player.setPosition(self.player.position() + self._preview_audio_offset_ms)
                self.audio_player.play()
            if getattr(self, "_preview_bgm_active", False) and hasattr(self, "bgm_player"):
                bgm_pos = self.player.position() + self._preview_bgm_offset_ms
                self.bgm_player.setPosition(bgm_pos)
                self.bgm_player.play()
            self.play_btn.setText("暂停")

class SlideshowWorker(QObject):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, ffmpeg, images, destination, single_dur, transition_name, transition_dur, animation_name, settings):
        super().__init__()
        self.ffmpeg = str(ffmpeg)
        self.images = [Path(p) for p in images]
        self.destination = Path(destination)
        self.single_dur = float(single_dur)
        self.transition_name = str(transition_name)
        self.transition_dur = float(transition_dur)
        self.animation_name = str(animation_name)
        self.settings = dict(settings)

    def run(self):
        try:
            import subprocess, shutil
            # Ensure images have same dimensions. Scale to standard 1080x1920 portrait first.
            temp_dir = self.destination.parent / f"temp_{self.destination.stem}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            self.log.emit(f"开始处理 {len(self.images)} 张图片，统一分辨率为 1080x1920，准备生成转场视频…")
            
            scaled_clips = []
            for idx, img in enumerate(self.images):
                scaled_dest = temp_dir / f"scaled_{idx:03d}.mp4"
                
                # Check for slow zoom (Ken Burns) animation
                v_filter = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(iw-ow)/2:(ih-oh)/2")
                if self.animation_name == "智能慢速变焦（Ken Burns）":
                    # For zoompan, input must be a SINGLE frame (NO -loop 1), and zoompan generates the frames based on 'd' parameter.
                    v_filter = (
                        "scale=1920:3413:force_original_aspect_ratio=increase,crop=1920:3413,"
                        f"zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={int(self.single_dur * 30)}:s=1080x1920:fps=30"
                    )
                    cmd = [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(img),
                        "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                        str(scaled_dest)
                    ]
                else:
                    # Static image: use -loop 1 -t
                    v_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
                    cmd = [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-loop", "1", "-t", f"{self.single_dur:.3f}", "-i", str(img),
                        "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                        str(scaled_dest)
                    ]
                
                creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                if res.returncode != 0:
                    err = (res.stdout or b"").decode("utf-8", errors="replace")
                    raise RuntimeError(f"处理图片 {img.name} 失败：{err}")
                scaled_clips.append(scaled_dest)

            # Apply xfade transitions
            transition_cfg = resolve_merge_transition(self.transition_name)
            transition_key = (transition_cfg or {}).get("xfade") if transition_cfg else None
            
            if transition_key and len(scaled_clips) > 1:
                # Calculate actual transition duration safely
                actual_transition_duration = min(self.transition_dur, max(0.12, self.single_dur * 0.45))
                self.log.emit(f"应用图片转场效果「{self.transition_name}」 (xfade={transition_key}，时长 {actual_transition_duration:.2f}秒)。")
                
                concat_command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
                for path in scaled_clips:
                    concat_command += ["-i", str(path)]
                
                # Build filter complex for video crossfade
                v_in = "[0:v]"
                current_offset = self.single_dur - actual_transition_duration
                
                filter_parts = []
                for i in range(1, len(scaled_clips)):
                    next_v = f"[{i}:v]"
                    out_v = f"[v_out_{i}]"
                    
                    filter_parts.append(
                        f"{v_in}{next_v}xfade=transition={transition_key}:duration={actual_transition_duration}:offset={current_offset:.3f}{out_v}"
                    )
                    v_in = out_v
                    current_offset = current_offset + self.single_dur - actual_transition_duration
                
                # Add silent audio stream matching the duration
                filter_parts.append(f"aevalsrc=0:d={current_offset + actual_transition_duration:.3f}[a]")
                
                filter_complex_str = ";".join(filter_parts)
                concat_command += [
                    "-filter_complex", filter_complex_str,
                    "-map", v_in,
                    "-map", "[a]"
                ]
                
                encoder = resolve_encoder(self.ffmpeg, self.settings.get("encoder_backend", "auto"))
                concat_command += encoder_args(encoder, self.settings.get("encode_preset", "veryfast"))
                concat_command += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
                concat_command += ["-movflags", "+faststart", str(self.destination)]
            else:
                self.log.emit("直接拼接生成幻灯片视频。")
                # Create a file list for concat demuxer
                list_file = temp_dir / "list.txt"
                with open(list_file, "w", encoding="utf-8") as f:
                    for clip in scaled_clips:
                        f.write(f"file '{clip.name}'\n")
                
                # Add a silent audio stream matching the duration
                total_duration = self.single_dur * len(scaled_clips)
                concat_command = [
                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={total_duration:.3f}",
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(self.destination)
                ]
            
            creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(concat_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
            
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            if res.returncode != 0:
                err = (res.stdout or b"").decode("utf-8", errors="replace")
                raise RuntimeError(f"合成幻灯片失败：{err}")
                
            self.finished.emit(True, str(self.destination))
        except Exception as exc:
            self.finished.emit(False, str(exc))


class ProjectTableWidget(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            files = [u.toLocalFile() for u in urls if u.isLocalFile()]
            if files:
                pos = event.position() if hasattr(event, "position") else event.pos()
                index = self.indexAt(pos.toPoint() if hasattr(pos, "toPoint") else pos)
                if index.isValid():
                    row = index.row()
                    target_col = 2
                    item = self.item(row, target_col)
                    if not item:
                        item = QTableWidgetItem()
                        self.setItem(row, target_col, item)
                    
                    existing = item.text().split(";") if item.text() else []
                    new_files = [f for f in files if f not in existing]
                    item.setText(";".join(existing + new_files))
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)


class ProjectGroupWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    item_done = Signal(str, str, str)  # output_file, name, srt
    finished = Signal(bool, str)

    def __init__(self, ffmpeg, ffprobe, tts_callable, transcribe_callable, tts_service, tts_voice, tts_speed, bgm_dir, projects, settings):
        super().__init__()
        self.ffmpeg = str(ffmpeg)
        self.ffprobe = str(ffprobe)
        self.tts_callable = tts_callable
        self.transcribe_callable = transcribe_callable
        self.tts_service = tts_service
        self.tts_voice = tts_voice
        self.tts_speed = tts_speed
        self.bgm_dir = Path(bgm_dir) if bgm_dir else None
        self.projects = projects # [{"row_idx": int, "name": str, "script": str, "materials": list, "bgm": str, "dim": str}]
        self.settings = dict(settings)
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        import subprocess, shutil, hashlib, json, time, os, random
        from pathlib import Path
        from .video_encoding import encoder_args, resolve_encoder
        
        encoder = resolve_encoder(self.ffmpeg, self.settings.get("encoder_backend", "auto"))
        outputs = []
        failures = []
        
        try:
            for idx, proj in enumerate(self.projects, 1):
                if self.cancelled:
                    self.finished.emit(False, "任务已取消。")
                    return
                
                name = proj.get("name") or f"project_{idx}"
                script = proj.get("script", "").strip()
                materials = [Path(m) for m in proj.get("materials", [])]
                bgm_choice = proj.get("bgm", "").strip()
                dim = proj.get("dim", "9:16")
                
                self.log.emit(f"[{idx}/{len(self.projects)}] 开始处理项目: {name}")
                self.progress.emit(int((idx - 1) / len(self.projects) * 100))
                
                res_map = {
                    "9:16": (1080, 1920),
                    "16:9": (1920, 1080),
                    "1:1": (1080, 1080),
                    "4:3": (1440, 1080)
                }
                target_w, target_h = res_map.get(dim, (1080, 1920))
                
                is_audio_file = False
                try:
                    if Path(script).is_file() and Path(script).suffix.lower() in [".mp3", ".wav", ".aac", ".ogg", ".m4a"]:
                        is_audio_file = True
                except Exception:
                    pass
                
                output_dir = Path(self.settings.get("output_dir", "."))
                output_dir.mkdir(parents=True, exist_ok=True)
                
                temp_dir = output_dir / f"temp_proj_{name}_{time.time_ns()}"
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                tts_path = temp_dir / "tts.mp3"
                
                if is_audio_file:
                    self.log.emit(f"项目 {name} 正在使用指定的外部配音音频文件...")
                    shutil.copy(script, tts_path)
                else:
                    if not script:
                        failures.append(f"项目 {name}：文案为空")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        continue
                    
                    tts_state = tts_path.with_suffix(".tts.json")
                    tts_fingerprint = hashlib.sha256(f"{self.tts_service}\n{self.tts_voice}\n{script}".encode("utf-8")).hexdigest()
                    
                    reused_tts = False
                    if tts_state.exists() and tts_path.exists() and tts_path.stat().st_size > 256:
                        try:
                            saved = json.loads(tts_state.read_text(encoding="utf-8"))
                            if saved.get("fingerprint") == tts_fingerprint:
                                reused_tts = True
                        except Exception:
                            pass
                    
                    if not reused_tts:
                        self.log.emit(f"正在为项目 {name} 生成语音配音...")
                        self.tts_callable(script, self.tts_service, self.tts_voice, str(tts_path))
                        tts_state.write_text(json.dumps({"fingerprint": tts_fingerprint, "service": self.tts_service, "voice": self.tts_voice}, ensure_ascii=False, indent=2), encoding="utf-8")
                    else:
                        self.log.emit(f"复用已生成的配音缓存: {name}")
                
                ffprobe_cmd = [
                    self.ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(tts_path)
                ]
                creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                res = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=creation)
                try:
                    tts_duration = float(res.stdout.strip())
                except Exception:
                    tts_duration = 5.0
                
                self.log.emit(f"语音配音时长为: {tts_duration:.2f} 秒")
                
                self.log.emit(f"正在从配音中提取精确字幕时间轴...")
                provider = self.settings.get("provider", "Whisper (本地/较慢)")
                _, _, word_srt = self.transcribe_callable(str(tts_path), provider)
                if not word_srt.strip():
                    raise RuntimeError("未识别到有效字幕时间轴")
                
                if not materials:
                    failures.append(f"项目 {name}：未添加素材")
                    continue
                
                images = [m for m in materials if m.suffix.lower() in IMAGE_EXTENSIONS]
                videos = [m for m in materials if m.suffix.lower() in VIDEO_EXTENSIONS]
                
                dest_file = output_dir / f"{name}_成品.mp4"
                
                if len(images) == len(materials):
                    self.log.emit(f"正在将 {len(images)} 张图片生成为带有转场和变焦的视频段...")
                    single_dur = (tts_duration + self.settings.get("transition_duration", 0.5) * (len(images) - 1)) / len(images)
                    single_dur = max(0.5, single_dur)
                    
                    slideshow_temp = temp_dir / "slideshow.mp4"
                    
                    scaled_clips = []
                    for idx_img, img in enumerate(images):
                        scaled_dest = temp_dir / f"scaled_{idx_img:03d}.mp4"
                        
                        v_filter = f"scale={target_w*2}:{target_h*2}:force_original_aspect_ratio=increase,crop={target_w*2}:{target_h*2}"
                        anim_name = self.settings.get("image_animation", "智能慢速变焦（Ken Burns）")
                        if anim_name == "智能慢速变焦（Ken Burns）":
                            v_filter += f",zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={int(single_dur * 30)}:s={target_w}x{target_h}:fps=30,setsar=1"
                        else:
                            v_filter = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
                            
                        if anim_name == "智能慢速变焦（Ken Burns）":
                            cmd = [
                                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                "-i", str(img),
                                "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                                str(scaled_dest)
                            ]
                        else:
                            cmd = [
                                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                "-loop", "1", "-t", f"{single_dur:.3f}", "-i", str(img),
                                "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                                str(scaled_dest)
                            ]
                        
                        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                        if res.returncode != 0:
                            err = (res.stdout or b"").decode("utf-8", errors="replace")
                            raise RuntimeError(f"处理图片 {img.name} 失败：{err}")
                        scaled_clips.append(scaled_dest)
                    
                    transition_name = self.settings.get("transition_name", "叠化")
                    transition_cfg = resolve_merge_transition(transition_name)
                    transition_key = (transition_cfg or {}).get("xfade") if transition_cfg else None
                    
                    if transition_key and len(scaled_clips) > 1:
                        actual_trans_dur = min(self.settings.get("transition_duration", 0.5), single_dur * 0.45)
                        concat_cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
                        for path in scaled_clips:
                            concat_cmd += ["-i", str(path)]
                        
                        v_in = "[0:v]"
                        current_offset = single_dur - actual_trans_dur
                        filter_parts = []
                        for i in range(1, len(scaled_clips)):
                            next_v = f"[{i}:v]"
                            out_v = f"[v_out_{i}]"
                            filter_parts.append(
                                f"{v_in}{next_v}xfade=transition={transition_key}:duration={actual_trans_dur:.3f}:offset={current_offset:.3f}{out_v}"
                            )
                            v_in = out_v
                            current_offset = current_offset + single_dur - actual_trans_dur
                        
                        concat_cmd += [
                            "-filter_complex", ";".join(filter_parts),
                            "-map", v_in
                        ]
                        concat_cmd += encoder_args(encoder, "veryfast")
                        concat_cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(slideshow_temp)]
                    else:
                        list_file = temp_dir / "list.txt"
                        with open(list_file, "w", encoding="utf-8") as f:
                            for clip in scaled_clips:
                                f.write(f"file '{clip.name}'\n")
                        concat_cmd = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "concat", "-safe", "0", "-i", str(list_file),
                            "-c:v", "copy", "-movflags", "+faststart", str(slideshow_temp)
                        ]
                    
                    res = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                    if res.returncode != 0:
                        err = (res.stdout or b"").decode("utf-8", errors="replace")
                        raise RuntimeError(f"合并视频片段失败：{err}")
                    
                    main_video = slideshow_temp
                else:
                    self.log.emit("正在处理视频/混合素材的分辨率对齐与裁剪...")
                    scaled_clips = []
                    for idx_m, mat in enumerate(materials):
                        scaled_dest = temp_dir / f"scaled_{idx_m:03d}.mp4"
                        
                        if mat.suffix.lower() in IMAGE_EXTENSIONS:
                            v_filter = f"scale={target_w*2}:{target_h*2}:force_original_aspect_ratio=increase,crop={target_w*2}:{target_h*2}"
                            anim_name = self.settings.get("image_animation", "智能慢速变焦（Ken Burns）")
                            if anim_name == "智能慢速变焦（Ken Burns）":
                                v_filter += f",zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d=150:s={target_w}x{target_h}:fps=30,setsar=1"
                                cmd = [
                                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                    "-i", str(mat),
                                    "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                                    str(scaled_dest)
                                ]
                            else:
                                v_filter = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
                                cmd = [
                                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                    "-loop", "1", "-t", "5.000", "-i", str(mat),
                                    "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                                    str(scaled_dest)
                                ]
                        else:
                            v_filter = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
                            cmd = [
                                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                "-i", str(mat),
                                "-vf", v_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                                "-an", str(scaled_dest)
                            ]
                        
                        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                        if res.returncode != 0:
                            err = (res.stdout or b"").decode("utf-8", errors="replace")
                            raise RuntimeError(f"对齐素材 {mat.name} 尺寸失败：{err}")
                        scaled_clips.append(scaled_dest)
                    
                    merged_temp = temp_dir / "merged_temp.mp4"
                    list_file = temp_dir / "list.txt"
                    with open(list_file, "w", encoding="utf-8") as f:
                        for clip in scaled_clips:
                            f.write(f"file '{clip.name}'\n")
                    
                    concat_cmd = [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(list_file),
                        "-c:v", "copy", "-movflags", "+faststart", str(merged_temp)
                    ]
                    res = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                    if res.returncode != 0:
                        err = (res.stdout or b"").decode("utf-8", errors="replace")
                        raise RuntimeError(f"合并素材片段失败：{err}")
                    
                    ffprobe_cmd = [
                        self.ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(merged_temp)
                    ]
                    res = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, text=True, creationflags=creation)
                    try:
                        v_dur = float(res.stdout.strip())
                    except:
                        v_dur = 0
                    
                    if v_dur < tts_duration:
                        self.log.emit(f"素材总长 ({v_dur:.2f}s) 短于配音时长 ({tts_duration:.2f}s)，自动循环素材以对齐音频...")
                        loop_count = int(tts_duration // v_dur) + 1
                        looped_temp = temp_dir / "looped_temp.mp4"
                        
                        loop_cmd = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-stream_loop", str(loop_count), "-i", str(merged_temp),
                            "-t", f"{tts_duration:.3f}", "-c", "copy", str(looped_temp)
                        ]
                        res = subprocess.run(loop_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                        if res.returncode != 0:
                            main_video = merged_temp
                        else:
                            main_video = looped_temp
                    else:
                        cropped_temp = temp_dir / "cropped_temp.mp4"
                        crop_cmd = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(merged_temp), "-t", f"{tts_duration:.3f}",
                            "-c", "copy", str(cropped_temp)
                        ]
                        res = subprocess.run(crop_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                        if res.returncode == 0:
                            main_video = cropped_temp
                        else:
                            main_video = merged_temp
                
                self.log.emit("正在合成配音音频 and 背景音乐，进行最终音频混缩...")
                bgm_file = None
                if bgm_choice == "无背景音":
                    pass
                elif bgm_choice.startswith("随机分配") and self.bgm_dir and self.bgm_dir.is_dir():
                    bgm_file = find_bgm_file(str(self.bgm_dir), idx, randomize=True)
                elif Path(bgm_choice).is_file():
                    bgm_file = Path(bgm_choice)
                
                mix_inputs = [
                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(main_video),
                    "-i", str(tts_path)
                ]
                
                if bgm_file:
                    bgm_offset_s = 0
                    if bgm_choice.startswith("随机分配"):
                        res = subprocess.run([
                            self.ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(bgm_file)
                        ], stdout=subprocess.PIPE, text=True, creationflags=creation)
                        try:
                            bgm_dur = float(res.stdout.strip())
                            if bgm_dur > tts_duration + 5:
                                bgm_offset_s = random.randint(0, int(bgm_dur - tts_duration - 2))
                        except Exception:
                            pass
                    
                    if bgm_offset_s > 0:
                        mix_inputs += ["-ss", f"{bgm_offset_s:.3f}", "-i", str(bgm_file)]
                    else:
                        mix_inputs += ["-i", str(bgm_file)]
                        
                    bgm_vol = float(self.settings.get("background_volume", 15)) / 100.0
                    filter_complex = (
                        f"[1:a]volume=1.0[tts];"
                        f"[2:a]volume={bgm_vol:.3f},aloop=loop=-1:size=2e9[bgm];"
                        f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                    )
                    mix_inputs += [
                        "-filter_complex", filter_complex,
                        "-map", "0:v:0",
                        "-map", "[aout]"
                    ]
                else:
                    mix_inputs += [
                        "-map", "0:v:0",
                        "-map", "1:a:0"
                    ]
                
                mix_inputs += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(dest_file)]
                res = subprocess.run(mix_inputs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                if res.returncode != 0:
                    err = (res.stdout or b"").decode("utf-8", errors="replace")
                    raise RuntimeError(f"混音失败：{err}")
                
                # Apply watermark if requested and configured
                watermark_img = None
                prepare_watermark = self.settings.get("watermark_prepare")
                if self.settings.get("burn_watermark") and callable(prepare_watermark):
                    try:
                        watermark_img = prepare_watermark(str(dest_file), str(temp_dir))
                    except Exception as e:
                        self.log.emit(f"准备水印图失败: {e}")
                if watermark_img and Path(watermark_img).is_file():
                    self.log.emit(f"项目 {name} 正在烧录公司水印...")
                    watermarked_file = dest_file.with_name(dest_file.stem + "_wm.mp4")
                    wm_cmd = [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(dest_file), "-i", str(watermark_img),
                        "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
                        "-map", "[v]", "-map", "0:a:0",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                        str(watermarked_file)
                    ]
                    res = subprocess.run(wm_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                    if res.returncode == 0:
                        dest_file.unlink()
                        watermarked_file.rename(dest_file)
                    else:
                        err = (res.stdout or b"").decode("utf-8", errors="replace")
                        self.log.emit(f"烧录水印失败：{err}，将使用无水印版本")
                
                shutil.rmtree(temp_dir, ignore_errors=True)
                
                self.log.emit(f"项目 {name} 一键生成半成品成功！已导出：{dest_file.name}")
                outputs.append(str(dest_file.resolve()))
                
                self.item_done.emit(str(dest_file.resolve()), name, word_srt)
                
            self.progress.emit(100)
            if failures:
                self.finished.emit(True, f"批量制作完成（有部分失败）：\n" + "\n".join(failures))
            else:
                self.finished.emit(True, f"批量制作成功！共处理 {len(self.projects)} 个项目，已自动载入“视频”列表。")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class ScriptCellWidget(QWidget):
    def __init__(self, parent_dialog, parent_row):
        super().__init__()
        self.parent_dialog = parent_dialog
        self.row_idx = parent_row
        self.audio_path = ""
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("在此输入配音文案...")
        layout.addWidget(self.text_edit, 1)
        
        self.audio_btn = QPushButton("🎤 外部音频/配音 (可选)...")
        self.audio_btn.setStyleSheet("QPushButton { text-align: left; padding: 2px 4px; font-size: 11px; color: #a8a29e; border: none; background: transparent; }")
        self.audio_btn.clicked.connect(self._choose_audio)
        layout.addWidget(self.audio_btn)
        
    def _choose_audio(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "选择配音音频", "",
            "音频文件 (*.mp3 *.wav *.aac *.ogg *.m4a)"
        )
        if file:
            self.set_audio(file)
        else:
            if self.audio_path:
                reply = QMessageBox.question(
                    self, "清除配音", "是否清除已选的外部配音音频，恢复使用文字配音？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.clear_audio()
                    
    def set_audio(self, path):
        self.audio_path = path
        self.audio_btn.setText(f"🎤 外部配音: {Path(path).name}")
        self.audio_btn.setStyleSheet("QPushButton { text-align: left; padding: 2px 4px; font-size: 11px; color: #4ade80; border: none; background: transparent; }")
        self.text_edit.setEnabled(False)
        self.text_edit.setPlainText(f"[已指定外部音频: {Path(path).name}]")
        
    def set_text(self, text):
        self.clear_audio()
        self.text_edit.setPlainText(text)
        
    def clear_audio(self):
        self.audio_path = ""
        self.audio_btn.setText("🎤 外部音频/配音 (可选)...")
        self.audio_btn.setStyleSheet("QPushButton { text-align: left; padding: 2px 4px; font-size: 11px; color: #a8a29e; border: none; background: transparent; }")
        self.text_edit.setEnabled(True)
        self.text_edit.setPlainText("")
        
    def get_value(self):
        if self.audio_path:
            return self.audio_path
        return self.text_edit.toPlainText().strip()


class ProjectAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量新增图文配音成片项目")
        self.resize(1000, 600)
        self.parent_page = parent
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)
        
        tip = QLabel(
            "批量添加项目表格：可手动多行添加，或「从 Excel 粘贴」导入文案。\n"
            "• 语音：每行写文案（走 TTS），或使用「批量导入外部配音」一次选中多个已转好的音频，按顺序填入各行。\n"
            "• 素材/BGM：点单元格按钮选择；BGM 空或随机时用全局随机分配。"
        )
        tip.setStyleSheet("color:#7dd3fc;background:#0b1830;padding:8px;border-radius:5px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        
        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["项目名称", "语音文案", "素材文件 (点击选择)", "背景音乐 (点击选择)", "画幅尺寸", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        # Adjust table column widths
        self.table.setColumnWidth(0, 120)  # Project Name
        self.table.setColumnWidth(1, 320)  # Script
        self.table.setColumnWidth(2, 180)  # Materials
        self.table.setColumnWidth(3, 180)  # BGM
        self.table.setColumnWidth(4, 90)   # Aspect Ratio
        self.table.setColumnWidth(5, 70)   # Delete
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive) # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)     # Script
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive) # Materials
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive) # BGM
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Dimension
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # Actions
        
        layout.addWidget(self.table, 1)
        
        # Bottom tool buttons
        tool_bar = QHBoxLayout()
        add_row_btn = QPushButton("➕ 添加一行")
        add_row_btn.clicked.connect(self._add_empty_row_btn)
        paste_excel_btn = QPushButton("📋 从 Excel 粘贴")
        paste_excel_btn.clicked.connect(self._paste_from_excel)
        batch_audio_btn = QPushButton("🎵 批量导入外部配音")
        batch_audio_btn.setToolTip(
            "一次选择多个已转好的音频（mp3/wav…），按文件名自然排序后依次填入各行「语音文案」列；\n"
            "行数不足会自动补行。该行将跳过 TTS，直接用外部音频与素材合成。"
        )
        batch_audio_btn.clicked.connect(self._batch_import_external_audio)
        clear_all_btn = QPushButton("🧹 清空全部")
        clear_all_btn.clicked.connect(self._clear_all_rows)
        
        tool_bar.addWidget(add_row_btn)
        tool_bar.addWidget(paste_excel_btn)
        tool_bar.addWidget(batch_audio_btn)
        tool_bar.addWidget(clear_all_btn)
        tool_bar.addStretch()
        
        # OK / Cancel
        btns = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        tool_bar.addLayout(btns)
        
        layout.addLayout(tool_bar)
        
        # Add one initial empty row
        self._add_empty_row()
        
    def _add_empty_row_btn(self):
        self._add_empty_row()
        
    def _add_empty_row(self, name="", script="", materials="", bgm=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 80)
        
        # 1. Project Name (QLineEdit) - Sequentially numbered default names
        name_edit = QLineEdit()
        name_edit.setText(name or f"项目 {row + 1}")
        self.table.setCellWidget(row, 0, name_edit)
        
        # 2. Script (ScriptCellWidget)
        script_widget = ScriptCellWidget(self, row)
        if script:
            try:
                if Path(script).is_file() and Path(script).suffix.lower() in [".mp3", ".wav", ".aac", ".ogg", ".m4a"]:
                    script_widget.set_audio(script)
                else:
                    script_widget.set_text(script)
            except Exception:
                script_widget.set_text(script)
        self.table.setCellWidget(row, 1, script_widget)
        
        # 3. Materials (Button representing list)
        mat_btn = QPushButton()
        mat_btn.setStyleSheet("QPushButton { text-align: left; padding: 6px; }")
        mat_files = []
        if materials:
            mat_files = [p.strip() for p in materials.split(";") if p.strip()]
            mat_files = sorted(mat_files, key=lambda p: natural_key(Path(p).name))
            
        mat_btn.mat_list = mat_files
        if mat_files:
            mat_btn.setText(f"📁 已选 {len(mat_files)} 个素材")
            mat_btn.setToolTip("\n".join(Path(p).name for p in mat_files))
        else:
            mat_btn.setText("📁 点击选择素材...")
            mat_btn.setToolTip("暂无素材")
            
        mat_btn.clicked.connect(lambda: self._on_materials_clicked(mat_btn))
        self.table.setCellWidget(row, 2, mat_btn)
        
        # 4. BGM (Button representing path)
        bgm_btn = QPushButton()
        bgm_btn.setStyleSheet("QPushButton { text-align: left; padding: 6px; }")
        bgm_val = bgm.strip() if bgm else "随机分配 (全局BGM)"
        bgm_btn.bgm_path = bgm_val
        if bgm_val != "随机分配 (全局BGM)":
            bgm_btn.setText(f"🎵 {Path(bgm_val).name}")
            bgm_btn.setToolTip(bgm_val)
        else:
            bgm_btn.setText("🎲 随机分配")
            bgm_btn.setToolTip("")
            
        bgm_btn.clicked.connect(lambda: self._on_bgm_clicked(bgm_btn))
        self.table.setCellWidget(row, 3, bgm_btn)
        
        # 5. Aspect Ratio (QComboBox)
        dim_combo = QComboBox()
        dim_combo.addItems(["9:16", "16:9", "1:1", "4:3"])
        self.table.setCellWidget(row, 4, dim_combo)
        
        # 6. Delete action
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_row)
        self.table.setCellWidget(row, 5, del_btn)
        
    def _delete_row(self):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 5) == self.sender():
                self.table.removeRow(r)
                break
                
    def _clear_all_rows(self):
        self.table.setRowCount(0)
        
    def _on_materials_clicked(self, btn):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择该项目的图片/视频素材", "",
            "所有素材 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.avi *.mov *.mkv)"
        )
        if files:
            # Sort files naturally
            sorted_files = sorted(files, key=lambda p: natural_key(Path(p).name))
            btn.mat_list = sorted_files
            btn.setText(f"📁 已选 {len(sorted_files)} 个素材")
            btn.setToolTip("\n".join(Path(p).name for p in sorted_files))
            
    def _on_bgm_clicked(self, btn):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        menu = QMenu(self)
        action_choose = menu.addAction("🎵 指定音频文件...")
        action_random = menu.addAction("🎲 设为随机分配 (默认)")
        
        action = menu.exec(QCursor.pos())
        if action == action_choose:
            file, _ = QFileDialog.getOpenFileName(
                self, "选择背景音乐", "",
                "音频文件 (*.mp3 *.wav *.aac *.ogg)"
            )
            if file:
                btn.bgm_path = file
                btn.setText(f"🎵 {Path(file).name}")
                btn.setToolTip(file)
        elif action == action_random:
            btn.bgm_path = "随机分配 (全局BGM)"
            btn.setText("🎲 随机分配")
            btn.setToolTip("")
            
    def _batch_import_external_audio(self):
        """Multi-select audio files and assign one per project row (create rows if needed)."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "批量选择外部配音音频", "",
            "音频文件 (*.mp3 *.wav *.aac *.ogg *.m4a *.flac *.opus)"
        )
        if not files:
            return
        files = sorted(files, key=lambda p: natural_key(Path(p).name))
        # Ensure enough rows
        while self.table.rowCount() < len(files):
            self._add_empty_row()
        assigned = 0
        for i, path in enumerate(files):
            widget = self.table.cellWidget(i, 1)
            if widget is None:
                continue
            if hasattr(widget, "set_audio"):
                widget.set_audio(path)
                assigned += 1
            # Name from audio stem if still default-like
            name_edit = self.table.cellWidget(i, 0)
            if isinstance(name_edit, QLineEdit):
                cur = name_edit.text().strip()
                if not cur or cur.startswith("项目 "):
                    name_edit.setText(Path(path).stem)
        QMessageBox.information(
            self, "批量导入完成",
            f"已将 {assigned} 个外部配音按顺序填入表格。\n"
            f"这些行将跳过文字转语音，直接使用音频文件合成。",
        )

    def _paste_from_excel(self):
        txt = QApplication.clipboard().text()
        if not txt.strip():
            QMessageBox.information(self, "剪贴板为空", "未在剪贴板中检测到任何内容。")
            return
            
        added_count = 0
        current_rows = self.table.rowCount()
        for row_str in txt.splitlines():
            if not row_str.strip():
                continue
            cols = row_str.split("\t")
            name = f"项目 {current_rows + added_count + 1}"
            script = ""
            materials = ""
            bgm = "随机分配 (全局BGM)"
            
            if len(cols) >= 1:
                if len(cols) == 1:
                    script = cols[0].strip()
                else:
                    name = cols[0].strip() or name
                    script = cols[1].strip()
            if len(cols) >= 3:
                materials = cols[2].strip()
            if len(cols) >= 4:
                bgm = cols[3].strip() or bgm
                
            if materials:
                materials = materials.strip('"').strip("'")
            if bgm:
                bgm = bgm.strip('"').strip("'")
                
            self._add_empty_row(name, script, materials, bgm)
            added_count += 1
            
    def get_data(self):
        results = []
        for r in range(self.table.rowCount()):
            name_widget = self.table.cellWidget(r, 0)
            script_widget = self.table.cellWidget(r, 1)
            mat_widget = self.table.cellWidget(r, 2)
            bgm_widget = self.table.cellWidget(r, 3)
            dim_widget = self.table.cellWidget(r, 4)
            
            if name_widget and script_widget:
                name = name_widget.text().strip()
                script = script_widget.get_value()
                
                materials_list = getattr(mat_widget, "mat_list", [])
                bgm_path = getattr(bgm_widget, "bgm_path", "随机分配 (全局BGM)")
                dim = dim_widget.currentText()
                
                results.append({
                    "name": name,
                    "script": script,
                    "materials": materials_list,
                    "bgm": bgm_path,
                    "dim": dim
                })
        return results

class TimeCalculatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("时间轴/切片换算小工具")
        self.setMinimumSize(420, 360)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Guide label
        guide = QLabel(
            "<b>使用说明：</b><br/>"
            "支持输入：秒数（如 75）、分:秒（如 1:15）、分:秒.毫秒（如 1:15.30）<br/>"
            "转换后将生成 <code>[开始-结束]</code> 格式的切片标记，复制到对应字幕前即可限制片段区间。"
        )
        guide.setWordWrap(True)
        guide.setStyleSheet("color: #93c5fd; background: #1e293b; padding: 10px; border-radius: 5px;")
        layout.addWidget(guide)
        
        # Form
        form = QFormLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("例如: 0:05 或 5")
        self.start_input.setText("0:00")
        
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("例如: 1:30 或 90")
        self.end_input.setText("0:30")
        
        form.addRow("开始时间 (Start):", self.start_input)
        form.addRow("结束时间 (End):", self.end_input)
        layout.addLayout(form)
        
        # Result display
        result_layout = QHBoxLayout()
        self.result_label = QLineEdit()
        self.result_label.setReadOnly(True)
        self.result_label.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setStyleSheet("color: #4ade80; background: #0f172a; padding: 8px;")
        result_layout.addWidget(self.result_label)
        
        self.copy_btn = QPushButton("复制")
        self.copy_btn.setFixedWidth(80)
        self.copy_btn.clicked.connect(self.copy_result)
        result_layout.addWidget(self.copy_btn)
        layout.addLayout(result_layout)
        
        # Status message
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #fca5a5;")
        layout.addWidget(self.status_label)
        
        # Connect signals
        self.start_input.textChanged.connect(self.calculate)
        self.end_input.textChanged.connect(self.calculate)
        
        self.calculate()
        
    def parse_time(self, text):
        text = text.strip()
        if not text:
            return 0.0
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 2:
                m = float(parts[0])
                s = float(parts[1])
                return m * 60 + s
            elif len(parts) == 3:
                h = float(parts[0])
                m = float(parts[1])
                s = float(parts[2])
                return h * 3600 + m * 60 + s
        else:
            return float(text)
            
    def calculate(self):
        try:
            self.status_label.setText("")
            start_sec = self.parse_time(self.start_input.text())
            end_sec = self.parse_time(self.end_input.text())
            
            if start_sec < 0 or end_sec < 0:
                raise ValueError("时间不能为负数")
                
            if start_sec >= end_sec:
                self.result_label.setText("")
                self.status_label.setText("开始时间必须小于结束时间")
                return
                
            res = f"[{start_sec:.2f}-{end_sec:.2f}]"
            self.result_label.setText(res)
        except Exception as exc:
            self.result_label.setText("")
            self.status_label.setText(f"输入格式有误: {exc}")
            
    def copy_result(self):
        text = self.result_label.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", f"已复制：{text}\n可以粘贴到字幕文本对应的开头。")
