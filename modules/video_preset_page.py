"""视频预设模块：布局对齐 Reels 编辑器（左素材 · 中预览 · 右设置 · 底时间轴）。

默认样式：标题 90/#820000 加粗；正文自动字号/#520000；蒙版 #ffffff 可调；
字体 Roboto / Roboto Condensed / Arimo；BGM/TTS/预设 I/O/批量渲染。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetrics, QImage, QKeySequence, QPainter,
    QPainterPath, QPen, QPixmap, QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QHeaderView, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .canva_timeline import CanvaTimelinePanel
from .dynamic_caption_page import (
    OPEN_SOURCE_FONTS, STATIC_BOLD_FONT_FILES, FontDownloadWorker,
    custom_font_dir, render_font_dir,
)
from .language_style import (
    fill_writing_language_combo, is_rtl_text, suggest_font_for_text,
    writing_language_from_ui,
)
from .path_picker import (
    AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, DropListWidget,
    collect_files, default_output_path, natural_key,
)
from .settings_page import find_media_tool, hidden_kwargs

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
PRESET_VERSION = 2
CANVAS_W, CANVAS_H = 1080, 1920

# 效果：与 Reels 常用静态/描边类一致（整段固定字幕，非卡拉 OK）
EFFECT_OPTIONS = [
    ("标准描边", "outline"),
    ("双眼皮（双描边）", "double_outline"),
    ("光晕", "glow"),
    ("阴影", "shadow"),
    ("无特效", "none"),
]

POSITION_OPTIONS = ("底部", "画面中间", "顶部")

# 参考模板（Downloads/参考：四条视频 + 两张成品图）+ 常用特效。
# 参考色、卡片范围和字号按 2026-08-05 实际抽帧重新校准；
# 标题与正文拥有独立字体、字号、颜色和粗细设置。
STYLE_QUICK_PRESETS = {
    # —— 参考视频模板 ——
    "参考1 · 山景祷告白卡": {
        "title_font": "Roboto", "body_font": "Roboto Condensed",
        "title_color": "#00278F", "body_color": "#79070E",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#000000", "outline_width": 0, "effect": "none",
        "highlight_color": "#111111", "shadow": 0,
        # 原视频有覆盖大部分画面的白色半透明卡片。
        "mask_enabled": True, "mask_color": "#F8FAF3", "mask_opacity": 82,
        "mask_x": 5.0, "mask_y": 7.0, "mask_w": 90.0, "mask_h": 86.0,
        "position": "顶部", "margin_v": 145, "line_spacing": 106,
        "title_align": "居中", "title_x_pct": 50, "title_width_pct": 82,
        "body_align": "居中", "body_x_pct": 50, "body_width_pct": 86,
        "title_y_pct": 10, "body_y_pct": 24,
        "body_flow": [{"from_y_pct": 72, "x_pct": 64, "width_pct": 58, "align": "居中"}],
    },
    "参考2 · 诗篇绿金笔记": {
        "title_font": "Arimo", "body_font": "Arimo",
        "title_color": "#526B05", "body_color": "#083B20",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#FFFFFF", "outline_width": 0, "effect": "none",
        "highlight_color": "#C9A227", "shadow": 0,
        # 纸张/装饰本来就在素材画面内；不要再叠加软件蒙版。
        "mask_enabled": False, "mask_color": "#FFFDF6", "mask_opacity": 94,
        "mask_x": 5.0, "mask_y": 4.0, "mask_w": 90.0, "mask_h": 92.0,
        "position": "顶部", "margin_v": 205, "line_spacing": 112,
        "title_align": "右对齐", "title_x_pct": 92, "title_width_pct": 58,
        "body_align": "居中", "body_x_pct": 55, "body_width_pct": 78,
        "title_y_pct": 12, "body_y_pct": 26,
        "body_flow": [{"from_y_pct": 64, "x_pct": 46, "width_pct": 70, "align": "居中"}],
    },
    "参考3 · 古卷酒红祷告": {
        "title_font": "Roboto Condensed", "body_font": "Roboto Condensed",
        "title_color": "#760407", "body_color": "#35170D",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#3D1F0A", "outline_width": 0, "effect": "none",
        "highlight_color": "#111111", "shadow": 1,
        # 羊皮纸和装饰本来就在素材画面内；不要再叠加软件蒙版。
        "mask_enabled": False, "mask_color": "#F4D89F", "mask_opacity": 82,
        "mask_x": 4.0, "mask_y": 5.0, "mask_w": 92.0, "mask_h": 90.0,
        "position": "顶部", "margin_v": 700, "line_spacing": 108,
        "title_align": "居中", "title_x_pct": 50, "title_width_pct": 84,
        "body_align": "居中", "body_x_pct": 50, "body_width_pct": 86,
        "title_y_pct": 42, "body_y_pct": 55,
        "body_flow": [],
    },
    "参考4 · 海岛蓝卡祷告": {
        "title_font": "Roboto", "body_font": "Arimo",
        "title_color": "#A43D2D", "body_color": "#173C9B",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#FFFFFF", "outline_width": 0, "effect": "none",
        "highlight_color": "#A84828", "shadow": 0,
        "mask_enabled": True, "mask_color": "#D8F1FC", "mask_opacity": 86,
        "mask_x": 5.0, "mask_y": 5.0, "mask_w": 90.0, "mask_h": 90.0,
        "position": "顶部", "margin_v": 115, "line_spacing": 102,
        "title_align": "居中", "title_x_pct": 50, "title_width_pct": 82,
        "body_align": "居中", "body_x_pct": 50, "body_width_pct": 84,
        "title_y_pct": 9, "body_y_pct": 20,
        "body_flow": [],
    },
    "参考5 · 绿色圣经笔记": {
        "title_font": "Arimo", "body_font": "Arimo",
        "title_color": "#083B20", "body_color": "#083B20",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#FFFFFF", "outline_width": 0, "effect": "none",
        "highlight_color": "#111111", "shadow": 0,
        "mask_enabled": False, "mask_color": "#FFFFFF", "mask_opacity": 0,
        "mask_x": 5.0, "mask_y": 5.0, "mask_w": 90.0, "mask_h": 90.0,
        "position": "顶部", "margin_v": 315, "line_spacing": 108,
        "title_align": "居中", "title_x_pct": 55, "title_width_pct": 76,
        "body_align": "居中", "body_x_pct": 55, "body_width_pct": 78,
        "title_y_pct": 18, "body_y_pct": 26,
        "body_flow": [{"from_y_pct": 64, "x_pct": 38, "width_pct": 58, "align": "居中"}],
    },
    "参考6 · 金框圣母祷告": {
        "title_font": "Roboto", "body_font": "Roboto Condensed",
        "title_color": "#B00000", "body_color": "#650708",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#FFFFFF", "outline_width": 0, "effect": "none",
        "highlight_color": "#111111", "shadow": 0,
        "mask_enabled": False, "mask_color": "#FFFFFF", "mask_opacity": 0,
        "mask_x": 10.0, "mask_y": 8.0, "mask_w": 80.0, "mask_h": 84.0,
        "position": "顶部", "margin_v": 220, "line_spacing": 106,
        "title_align": "居中", "title_x_pct": 50, "title_width_pct": 72,
        "body_align": "居中", "body_x_pct": 50, "body_width_pct": 74,
        "title_y_pct": 14, "body_y_pct": 22,
        "body_flow": [],
    },
    "参考7 · 耶稣百合经文": {
        "title_font": "Roboto", "body_font": "Arimo",
        "title_color": "#526B05", "body_color": "#526B05",
        "title_font_size": 90, "body_font_size": 45, "body_auto_size": True,
        "adaptive_layout": True,
        "title_bold": True, "body_bold": True,
        "outline_color": "#FFFFFF", "outline_width": 0, "effect": "none",
        "highlight_color": "#111111", "shadow": 0,
        "mask_enabled": False, "mask_color": "#FFFFFF", "mask_opacity": 0,
        "mask_x": 5.0, "mask_y": 5.0, "mask_w": 90.0, "mask_h": 90.0,
        "position": "顶部", "margin_v": 165, "line_spacing": 108,
        "title_align": "右对齐", "title_x_pct": 93, "title_width_pct": 58,
        "body_align": "居中", "body_x_pct": 54, "body_width_pct": 82,
        "title_y_pct": 13, "body_y_pct": 28,
        "body_flow": [{"from_y_pct": 62, "x_pct": 31, "width_pct": 50, "align": "居中"}],
    },
    # —— 特效快捷 ——
    "默认酒红标题": {
        "title_font": "Roboto", "body_font": "Roboto",
        "title_color": "#820000", "body_color": "#520000", "outline_color": "#FFFFFF",
        "highlight_color": "#111111", "outline_width": 0, "effect": "none",
        "title_bold": True, "shadow": 0, "mask_enabled": True, "mask_opacity": 70,
    },
    "双眼皮 经典红黄黑": {
        "title_color": "#FF0000", "body_color": "#FF0000", "outline_color": "#FFFF00",
        "highlight_color": "#111111", "outline_width": 3, "effect": "double_outline",
        "title_bold": True, "shadow": 0,
    },
    "双眼皮 极光绿白黑": {
        "title_color": "#FFFFFF", "body_color": "#FFFFFF", "outline_color": "#A3E635",
        "highlight_color": "#111111", "outline_width": 3, "effect": "double_outline",
        "title_bold": True, "shadow": 0,
    },
    "双眼皮 炫彩黄蓝黑": {
        "title_color": "#FACC15", "body_color": "#FACC15", "outline_color": "#2563EB",
        "highlight_color": "#111111", "outline_width": 3, "effect": "double_outline",
        "title_bold": True, "shadow": 0,
    },
    "黄字黑边（参考1·阿们强调）": {
        "title_color": "#FCFA30", "body_color": "#7E1619", "outline_color": "#000000",
        "highlight_color": "#111111", "outline_width": 5, "effect": "outline",
        "title_bold": True, "shadow": 0, "title_font_size": 100,
    },
    "白字黑边阴影": {
        "title_color": "#FFFFFF", "body_color": "#F8FAFC", "outline_color": "#000000",
        "highlight_color": "#111111", "outline_width": 4, "effect": "shadow",
        "title_bold": True, "shadow": 4,
    },
    "光晕紫": {
        "title_color": "#F5F3FF", "body_color": "#F5F3FF", "outline_color": "#7C3AED",
        "highlight_color": "#A855F7", "outline_width": 5, "effect": "glow",
        "title_bold": True, "shadow": 0,
    },
    # Facebook 参考（竖屏 9:16 居中大字）
    "FB 卡车黄字跟读": {
        "title_font": "Arial Black", "body_font": "Arial Black",
        "title_color": "#F7FF1A", "body_color": "#F8FAFC",
        "title_font_size": 92, "body_font_size": 78, "body_auto_size": True,
        "adaptive_layout": True, "title_bold": True, "body_bold": True,
        "outline_color": "#0A0A0A", "outline_width": 6, "effect": "outline",
        "highlight_color": "#F7FF1A", "shadow": 2,
        "mask_enabled": False, "mask_opacity": 0,
        "position": "画面中间", "margin_v": 420, "line_spacing": 108,
        "title_align": "居中", "title_x_pct": 50, "title_width_pct": 88,
        "body_align": "居中", "body_x_pct": 50, "body_width_pct": 90,
        "title_y_pct": 38, "body_y_pct": 48, "body_flow": [],
    },
    "FB 黄昏白字光晕": {
        "title_font": "Arial Black", "body_font": "Arial Black",
        "title_color": "#FFFFFF", "body_color": "#FFFFFF",
        "title_font_size": 100, "body_font_size": 88, "body_auto_size": True,
        "adaptive_layout": True, "title_bold": True, "body_bold": True,
        "outline_color": "#FFFFFF", "outline_width": 3, "effect": "glow",
        "highlight_color": "#FFFFFF", "shadow": 6,
        "mask_enabled": False, "mask_opacity": 0,
        "position": "画面中间", "margin_v": 400, "line_spacing": 112,
        "title_align": "居中", "title_x_pct": 50, "title_width_pct": 86,
        "body_align": "居中", "body_x_pct": 50, "body_width_pct": 88,
        "title_y_pct": 40, "body_y_pct": 52, "body_flow": [],
    },
}

DEFAULT_PRESET = {
    "version": PRESET_VERSION,
    "name": "默认视频预设",
    "title_font_size": 90,
    "body_font_size": 45,
    "body_auto_size": True,
    "adaptive_layout": True,
    "title_font": "Roboto",
    "body_font": "Roboto",
    "font_family": "Roboto",  # 兼容旧预设：同时作标题/正文回退
    "title_color": "#820000",
    "title_bold": True,
    "body_bold": False,
    "body_color": "#520000",
    "outline_color": "#FFFFFF",
    "outline_width": 0,
    "highlight_color": "#111111",  # 双眼皮外圈
    "background_color": "#00000000",  # 文字底色，00 alpha=透明
    "background_enabled": False,
    "effect": "outline",
    "shadow": 0,
    "letter_spacing": 0,
    "line_spacing": 110,
    "position": "底部",
    "margin_v": 380,
    "title_align": "居中",
    "title_x_pct": 50,
    "title_width_pct": 86,
    "body_align": "居中",
    "body_x_pct": 50,
    "body_width_pct": 86,
    "title_y_pct": None,
    "body_y_pct": None,
    "body_flow": [],
    "mask_color": "#ffffff",
    "mask_opacity": 70,
    "mask_x": 5.0,
    "mask_y": 55.0,
    "mask_w": 90.0,
    "mask_h": 30.0,
    "mask_enabled": True,
    "writing_language": "",
    "bgm_enabled": False,
    "bgm_selection_mode": "fixed",
    "bgm_path": "",
    "bgm_dir": "",
    "bgm_volume": 25,
    "keep_original_audio": True,
    "original_volume": 100,
    "tts_service": "微软文字转语音",
    "tts_voice": "",
    "output_dir": "",
}


def effective_char_count(text: str) -> int:
    """只统计可见字母/数字；忽略空格、标点和阿拉伯语组合音标。"""
    normalized = unicodedata.normalize("NFD", str(text or ""))
    return sum(1 for ch in normalized if unicodedata.category(ch)[:1] in {"L", "N"})


def body_font_size_for_chars(char_count: int) -> int:
    """按正文长度自动字号；最小不低于 20。"""
    n = max(0, int(char_count or 0))
    if n < 50:
        size = 72 - int(n * 12 / 49) if n else 72
    elif n <= 100:
        size = 55
    elif n < 200:
        size = int(55 - (n - 100) * 11 / 100)
    elif n <= 300:
        size = 44
    elif n < 350:
        size = int(44 - (n - 300) * 4 / 50)
    elif n <= 400:
        size = 40
    elif n < 500:
        size = int(40 - (n - 400) * 7 / 100)
    elif n <= 550:
        size = 33
    else:
        size = 33 - (n - 550) // 40
    return max(20, min(120, int(size)))


def body_layout_for_chars(char_count: int) -> tuple[int, float]:
    """按正文密度返回每行建议字符数和行距倍率；与自动字号档位配套。"""
    n = max(0, int(char_count or 0))
    if n < 50:
        return 12, 1.22
    if n <= 100:
        return 17, 1.16
    if n < 200:
        return 20, 1.12
    if n <= 300:
        return 23, 1.08
    if n < 350:
        return 24, 1.06
    if n <= 400:
        return 26, 1.04
    if n < 500:
        return 28, 1.02
    if n <= 550:
        return 30, 1.00
    return 32, 0.98


def fixed_body_layout(text: str, font_size: int, width_pct: float) -> tuple[int, float]:
    """固定预设只按字号和文字框宽度换行，不根据总字符数改变布局。"""
    width_px = CANVAS_W * max(20.0, min(100.0, float(width_pct or 86))) / 100
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", str(text or "")))
    average_glyph_width = max(8.0, float(font_size) * (1.0 if has_cjk else 0.68))
    return max(4, min(48, int(width_px / average_glyph_width))), 1.0


def ass_color(hex_color: str, alpha: str = "00") -> str:
    value = QColor(hex_color if str(hex_color).startswith("#") else f"#{hex_color}")
    if not value.isValid():
        value = QColor("#ffffff")
    return f"&H{alpha}{value.blue():02X}{value.green():02X}{value.red():02X}"


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    seconds -= hours * 3600
    minutes = int(seconds // 60)
    seconds -= minutes * 60
    return f"{hours}:{minutes:02d}:{seconds:05.2f}"


def media_duration(ffmpeg: str, path, fallback: float = 8.0) -> float:
    path = Path(path)
    if not path.is_file():
        return float(fallback)
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return float(fallback)
    ffprobe = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    try:
        result = subprocess.run(
            [str(ffprobe if ffprobe.is_file() else "ffprobe"),
             "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **hidden_kwargs(),
        )
        return max(0.1, float((result.stdout or "").strip() or fallback))
    except Exception:
        return float(fallback)


def find_bgm_file(bgm_dir, index: int = 0, video=None, randomize: bool = False):
    if not bgm_dir:
        return None
    path = Path(bgm_dir)
    if path.is_file():
        if path.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
            return path
        return None
    if not path.is_dir():
        return None
    files = sorted(
        [x for x in path.rglob("*")
         if x.is_file() and x.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS],
        key=lambda x: natural_key(x.name),
    )
    if not files:
        return None
    if randomize and video:
        import random
        h = hashlib.md5(f"{Path(video).resolve()}_{index}".encode("utf-8")).hexdigest()
        return random.Random(int(h, 16)).choice(files)
    return files[index % len(files)]


def random_bgm_start_ms(ffmpeg, bgm_file, video=None, index: int = 0) -> int:
    import random
    try:
        bgm_dur = float(media_duration(ffmpeg, bgm_file) or 0)
    except Exception:
        bgm_dur = 0.0
    if bgm_dur <= 2.0:
        return 0
    key = f"{Path(video).resolve() if video else 'bgm'}_{index}_preset_bgm"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(random.Random(int(h, 16)).uniform(0.0, max(0.1, bgm_dur - 1.0)) * 1000)


def wrap_text_lines(text: str, max_chars: int = 28) -> list[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        buf = ""
        for ch in paragraph:
            buf += ch
            if len(buf) >= max_chars and ch in " \t，。！？,.!?;；:：":
                lines.append(buf.strip())
                buf = ""
            elif len(buf) >= max_chars + 8:
                lines.append(buf.strip())
                buf = ""
        if buf.strip():
            lines.append(buf.strip())
    return lines or [text]


def wrap_text_region_lines(text: str, base_max_chars: int, base_width_pct: float,
                           body_y: float, body_step: float,
                           body_flow: list[dict]) -> list[str]:
    """按当前纵向画面区域换行，但不改变预设区域本身。

    上半段可以使用较宽的留白区；进入人物、花朵等主体所在的下半段后，
    后续行才改用该区域宽度。字符超出只继续产生新行，不触发整套布局重算。
    """
    source = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        return []
    regions = sorted(
        [dict(item) for item in (body_flow or []) if isinstance(item, dict)],
        key=lambda item: float(item.get("from_y_pct", 0)),
    )
    base_width = max(20.0, min(100.0, float(base_width_pct or 86)))
    result: list[str] = []

    def limit_for_line(line_index: int) -> int:
        line_y_pct = (body_y + line_index * body_step) / CANVAS_H * 100
        width = base_width
        for region in regions:
            if line_y_pct >= float(region.get("from_y_pct", 0)):
                width = max(20.0, min(100.0, float(region.get("width_pct", width))))
        return max(4, int(round(base_max_chars * width / base_width)))

    for paragraph in source.split("\n"):
        remaining = paragraph.strip()
        if not remaining:
            result.append("")
            continue
        while remaining:
            limit = limit_for_line(len(result))
            if len(remaining) <= limit:
                result.append(remaining)
                break
            hard_limit = min(len(remaining), limit + 8)
            cut = 0
            for index in range(limit - 1, hard_limit):
                if remaining[index] in " \t，。！？,.!?;；:：":
                    cut = index + 1
                    break
            if not cut:
                cut = hard_limit
            result.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
    return result or [source]


def wrap_title_lines(text: str, font_size: int = 90, width_pct: float = 86) -> list[str]:
    """标题按 1080 竖屏安全宽度分行；中文不依赖标点也能正确折行。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    width_scale = max(0.2, min(1.0, float(width_pct or 86) / 86.0))
    max_chars = max(4, min(18, int(900 / max(36, int(font_size)) * width_scale)))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if re.search(r"[\u3400-\u9fff]", paragraph):
            lines.extend(paragraph[i:i + max_chars]
                         for i in range(0, len(paragraph), max_chars))
        else:
            words = paragraph.split()
            if len(words) > 1:
                current = ""
                for word in words:
                    trial = f"{current} {word}".strip()
                    if current and len(trial) > max_chars + 4:
                        lines.append(current)
                        current = word
                    else:
                        current = trial
                if current:
                    lines.append(current)
            else:
                lines.extend(paragraph[i:i + max_chars + 4]
                             for i in range(0, len(paragraph), max_chars + 4))
    return lines or [text]


def _resolved_body_size(settings: dict, body: str) -> int:
    if settings.get("body_auto_size", True):
        return body_font_size_for_chars(effective_char_count(body))
    return max(20, int(settings.get("body_font_size") or 45))


def _content_box(settings: dict) -> tuple[float, float, float, float]:
    """返回文字安全区 (x, y, w, h) 像素，优先用蒙版；否则整屏留边。"""
    pad = 36.0
    if settings.get("mask_enabled", True):
        mx = CANVAS_W * float(settings.get("mask_x", 5)) / 100
        my = CANVAS_H * float(settings.get("mask_y", 8)) / 100
        mw = max(80.0, CANVAS_W * float(settings.get("mask_w", 90)) / 100)
        mh = max(80.0, CANVAS_H * float(settings.get("mask_h", 80)) / 100)
        return mx + pad, my + pad * 1.2, max(40.0, mw - pad * 2), max(40.0, mh - pad * 2.4)
    # 无蒙版：按模板 title_y / 底部边距推断内容区
    top = CANVAS_H * float(settings.get("title_y_pct") or 10) / 100 - 20
    top = max(40.0, min(CANVAS_H * 0.5, top))
    bottom_margin = max(80.0, float(settings.get("margin_v") or 120))
    height = max(200.0, CANVAS_H - top - bottom_margin)
    side = CANVAS_W * 0.07
    return side, top, CANVAS_W - side * 2, height


def _chars_for_width(font_size: int, width_px: float, text: str = "") -> int:
    """按字号与可用宽度估算每行字符上限（阿拉伯/拉丁/中文）。"""
    sample = str(text or "")
    if re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", sample):
        glyph = max(10.0, float(font_size) * 0.78)  # 阿拉伯略宽
    elif re.search(r"[\u3400-\u9fff]", sample):
        glyph = max(10.0, float(font_size) * 1.0)
    else:
        glyph = max(8.0, float(font_size) * 0.62)
    return max(4, min(48, int(width_px / glyph)))


def resolve_caption_layout(settings: dict, title: str, body: str) -> dict:
    """根据文案长度在安全区内自适应字号与 Y 位置（贴合参考竖屏卡片）。

    - 同一素材改字：字多→字号缩小、行更密、占满卡片；字少→字号放大、垂直居中偏上
    - 不是简单整页左/中/右：标题/正文各自 x_pct + body_flow 分区绕开装饰
    """
    title = (title or "").strip()
    body = (body or "").strip()
    adaptive = bool(settings.get("adaptive_layout", True))
    box_x, box_y, box_w, box_h = _content_box(settings)
    title_width_pct = max(20.0, min(100.0, float(settings.get("title_width_pct", 86))))
    body_width_pct = max(20.0, min(100.0, float(settings.get("body_width_pct", 86))))
    title_w = box_w * title_width_pct / 100.0 if adaptive else CANVAS_W * title_width_pct / 100.0
    body_w = box_w * body_width_pct / 100.0 if adaptive else CANVAS_W * body_width_pct / 100.0
    if adaptive:
        title_w = min(title_w, box_w)
        body_w = min(body_w, box_w)

    preferred_title = max(20, int(settings.get("title_font_size") or 90))
    preferred_body = _resolved_body_size(settings, body)
    line_sp = float(settings.get("line_spacing") or 110) / 100.0
    body_flow = [dict(item) for item in (settings.get("body_flow") or []) if isinstance(item, dict)]

    # —— 标题字号：保证能放下 ——
    title_size = preferred_title
    title_lines: list[str] = []
    if title:
        for try_size in range(preferred_title, 19, -2):
            max_c = _chars_for_width(try_size, title_w, title)
            lines = wrap_title_lines(title, try_size, title_width_pct)
            # 再用宽度收紧：过长行按字切开
            refined: list[str] = []
            for line in lines:
                if len(line) <= max_c + 2:
                    refined.append(line)
                else:
                    for i in range(0, len(line), max_c):
                        refined.append(line[i:i + max_c])
            title_h = try_size * max(1, len(refined)) * line_sp
            if title_h <= box_h * 0.38 or try_size <= 28:
                title_size = try_size
                title_lines = refined
                break
        if not title_lines:
            title_lines = wrap_title_lines(title, title_size, title_width_pct)

    title_block_h = title_size * max(1, len(title_lines)) * line_sp if title else 0.0
    gap = 28.0 if (title and body) else 0.0
    remain_h = max(80.0, box_h - title_block_h - gap - 20.0)

    # —— 正文字号：先按字符规则，再按剩余高度压缩 ——
    body_size = preferred_body
    density = 1.0
    body_lines: list[str] = []
    if body:
        if settings.get("body_auto_size", True):
            body_size = preferred_body
        else:
            body_size = max(20, int(settings.get("body_font_size") or 45))
        for try_size in range(body_size, 19, -1):
            count = effective_char_count(body)
            if settings.get("body_auto_size", True):
                max_c, density = body_layout_for_chars(count)
                max_c = max(4, int(round(max_c * body_width_pct / 86.0)))
            else:
                max_c, density = fixed_body_layout(body, try_size, body_width_pct)
            # 与宽度一致再收紧
            max_c = min(max_c, _chars_for_width(try_size, body_w, body))
            step = try_size * line_sp * density
            # 先粗 wrap，再走 region wrap 用 body_y 占位
            approx_y = box_y + title_block_h + gap
            lines = wrap_text_region_lines(
                body, max_c, body_width_pct, approx_y, step, body_flow
            )
            total_h = step * max(1, len(lines))
            if total_h <= remain_h or try_size <= 22:
                body_size = try_size
                body_lines = lines
                break
        if not body_lines:
            max_c = _chars_for_width(body_size, body_w, body)
            body_lines = wrap_text_lines(body, max_c)

    body_step = body_size * line_sp * density
    body_block_h = body_step * max(1, len(body_lines)) if body else 0.0
    total_h = title_block_h + gap + body_block_h

    # —— 垂直位置：优先模板锚点，文案变长/变短时在安全区内重排 ——
    preferred_title_y = None
    if settings.get("title_y_pct") is not None:
        preferred_title_y = CANVAS_H * float(settings["title_y_pct"]) / 100.0
    preferred_body_y = None
    if settings.get("body_y_pct") is not None:
        preferred_body_y = CANVAS_H * float(settings["body_y_pct"]) / 100.0

    if adaptive:
        # 短文案：尽量贴近模板锚点；长文案：从安全区顶部排，必要时整体上移
        if preferred_title_y is not None and title:
            title_y = preferred_title_y
        else:
            title_y = box_y + (0 if total_h > box_h * 0.92 else max(0.0, (box_h - total_h) * 0.12))
        # 保证标题不超出安全区底
        if title_y + title_block_h > box_y + box_h - 40:
            title_y = max(box_y, box_y + box_h - title_block_h - body_block_h - gap - 20)
        if body:
            if preferred_body_y is not None and total_h < box_h * 0.85:
                body_y = max(preferred_body_y, title_y + title_block_h + gap if title else preferred_body_y)
            else:
                body_y = (title_y + title_block_h + gap) if title else (
                    preferred_body_y if preferred_body_y is not None else box_y + 20
                )
            # 正文溢出则整体上移
            overflow = (body_y + body_block_h) - (box_y + box_h)
            if overflow > 0:
                shift = min(overflow + 10, max(0.0, title_y - box_y))
                title_y -= shift
                body_y -= shift
                if (body_y + body_block_h) > (box_y + box_h):
                    # 仍溢出：再压缩行距已在字号循环处理；这里裁到底边
                    body_y = max(box_y, box_y + box_h - body_block_h)
        else:
            body_y = title_y
    else:
        # 旧逻辑：固定锚点
        if preferred_title_y is not None:
            title_y = preferred_title_y
        else:
            title_y = box_y + 20
        if preferred_body_y is not None:
            body_y = preferred_body_y
        elif title:
            body_y = title_y + title_block_h + gap
        else:
            body_y = title_y

    # 最终 body_lines 用确定的 body_y 再 wrap 一次（body_flow 分区依赖 Y）
    if body:
        count = effective_char_count(body)
        if settings.get("body_auto_size", True):
            max_c, density = body_layout_for_chars(count)
            max_c = max(4, int(round(max_c * body_width_pct / 86.0)))
        else:
            max_c, density = fixed_body_layout(body, body_size, body_width_pct)
        max_c = min(max_c, _chars_for_width(body_size, body_w, body))
        body_step = body_size * line_sp * density
        body_lines = wrap_text_region_lines(
            body, max_c, body_width_pct, body_y, body_step, body_flow
        )

    align_codes = {"左对齐": 4, "居中": 5, "右对齐": 6}
    title_x = CANVAS_W * max(0.0, min(100.0, float(settings.get("title_x_pct", 50)))) / 100
    body_x = CANVAS_W * max(0.0, min(100.0, float(settings.get("body_x_pct", 50)))) / 100
    # 自适应时：默认 X 落在安全区中心（仍可用模板 x_pct 覆盖）
    if adaptive and settings.get("title_x_pct") is None:
        title_x = box_x + box_w / 2
    if adaptive and settings.get("body_x_pct") is None:
        body_x = box_x + box_w / 2

    title_an = align_codes.get(str(settings.get("title_align") or "居中"), 5)
    body_an = align_codes.get(str(settings.get("body_align") or "居中"), 5)

    lines_out = []
    title_step = title_size * line_sp
    for i, line in enumerate(title_lines):
        lines_out.append({
            "kind": "title", "text": line,
            "x": title_x, "y": title_y + i * title_step,
            "size": title_size, "align": title_an,
        })
    for i, line in enumerate(body_lines):
        line_y = body_y + i * body_step
        line_x, line_an = body_x, body_an
        for region in sorted(body_flow, key=lambda r: float(r.get("from_y_pct", 0))):
            if line_y / CANVAS_H * 100 >= float(region.get("from_y_pct", 0)):
                line_x = CANVAS_W * max(0.0, min(100.0, float(
                    region.get("x_pct", settings.get("body_x_pct", 50))))) / 100
                line_an = align_codes.get(
                    str(region.get("align") or settings.get("body_align") or "居中"), body_an)
        lines_out.append({
            "kind": "body", "text": line,
            "x": line_x, "y": line_y,
            "size": body_size, "align": line_an,
        })

    return {
        "title_size": title_size,
        "body_size": body_size,
        "title_y": title_y,
        "body_y": body_y,
        "title_x": title_x,
        "body_x": body_x,
        "title_lines": title_lines,
        "body_lines": body_lines,
        "body_step": body_step,
        "title_step": title_step,
        "lines": lines_out,
        "box": (box_x, box_y, box_w, box_h),
    }


def _text_style_tags(settings: dict, *, is_title: bool) -> str:
    """ASS override tags for fill / outline / shadow / glow / double-outline fill layer."""
    effect = str(settings.get("effect") or "outline")
    outline_w = max(0, min(16, int(settings.get("outline_width") or 0)))
    shadow = max(0, min(12, int(settings.get("shadow") or 0)))
    spacing = int(settings.get("letter_spacing") or 0)
    fill = ass_color(
        settings.get("title_color") if is_title else settings.get("body_color")
        or ("#820000" if is_title else "#520000")
    )
    outline = ass_color(settings.get("outline_color") or "#FFFFFF")
    bold = 1 if (settings.get("title_bold", True) if is_title else settings.get("body_bold", False)) else 0
    tags = fr"\b{bold}\1c{fill}\3c{outline}\fsp{spacing}"
    if effect == "none":
        tags += r"\bord0\shad0"
    elif effect == "glow":
        tags += fr"\bord{max(2, outline_w)}\shad0\blur3"
    elif effect == "shadow":
        tags += fr"\bord{outline_w}\shad{max(2, shadow or 3)}"
    elif effect == "double_outline":
        # 内层：黄/描边色；外层单独 Dialogue 用 highlight
        tags += fr"\bord{max(1, outline_w)}\shad0"
    else:  # outline
        tags += fr"\bord{outline_w}\shad{shadow}"
    if settings.get("background_enabled"):
        bg = ass_color(settings.get("background_color") or "#000000")
        tags += fr"\4c{bg}\4a&H60&\be1"
    return tags


def _double_outer_tags(settings: dict, *, is_title: bool) -> str:
    outline_w = max(1, min(16, int(settings.get("outline_width") or 3)))
    spacing = int(settings.get("letter_spacing") or 0)
    outer = ass_color(settings.get("highlight_color") or "#111111")
    bold = 1 if (settings.get("title_bold", True) if is_title else settings.get("body_bold", False)) else 0
    return fr"\b{bold}\1c{outer}\3c{outer}\bord{outline_w + 3}\shad0\fsp{spacing}"


def build_preset_ass(path: Path, title: str, body: str, settings: dict, duration_sec: float) -> Path:
    lang = settings.get("writing_language") or ""
    fallback_font = str(settings.get("font_family") or "Arial").replace(",", "")
    title_font = str(settings.get("title_font") or fallback_font).replace(",", "")
    body_font = str(settings.get("body_font") or fallback_font).replace(",", "")
    title = (title or "").strip()
    body = (body or "").strip()
    if is_rtl_text(title, lang):
        title_font = suggest_font_for_text(title_font, title, lang) or title_font
    if is_rtl_text(body, lang):
        body_font = suggest_font_for_text(body_font, body, lang) or body_font

    layout = resolve_caption_layout(settings, title, body)
    title_size = int(layout["title_size"])
    body_size = int(layout["body_size"])
    title_color = ass_color(settings.get("title_color") or "#820000")
    body_color = ass_color(settings.get("body_color") or "#520000")
    outline_color = ass_color(settings.get("outline_color") or "#FFFFFF")
    highlight = ass_color(settings.get("highlight_color") or "#111111")
    title_bold = -1 if settings.get("title_bold", True) else 0
    body_bold = -1 if settings.get("body_bold", False) else 0
    if any(key in title_font for key in STATIC_BOLD_FONT_FILES):
        title_bold = -1
    if any(key in body_font for key in STATIC_BOLD_FONT_FILES):
        body_bold = -1
    outline_w = max(0, min(16, int(settings.get("outline_width") or 0)))
    shadow = max(0, min(12, int(settings.get("shadow") or 0)))
    spacing = int(settings.get("letter_spacing") or 0)
    effect = str(settings.get("effect") or "outline")
    position = settings.get("position") or "底部"
    margin_v = max(20, min(900, int(settings.get("margin_v") or 380)))
    alignment = {"底部": 2, "画面中间": 5, "顶部": 8}.get(position, 2)
    end_t = ass_time(max(0.5, float(duration_sec)))
    events: list[str] = []

    if settings.get("mask_enabled", True):
        mx = CANVAS_W * float(settings.get("mask_x", 5)) / 100
        my = CANVAS_H * float(settings.get("mask_y", 55)) / 100
        mw = max(20.0, CANVAS_W * float(settings.get("mask_w", 90)) / 100)
        mh = max(20.0, CANVAS_H * float(settings.get("mask_h", 30)) / 100)
        opacity = max(0, min(100, int(settings.get("mask_opacity", 70))))
        alpha = f"{round(255 * (1 - opacity / 100)):02X}"
        mcolor = ass_color(settings.get("mask_color") or "#ffffff")
        rect = f"m 0 0 l {mw:.1f} 0 {mw:.1f} {mh:.1f} 0 {mh:.1f}"
        tag = ("{" + r"\an7\pos(" + f"{mx:.1f},{my:.1f}" + r")\p1\1c" + mcolor
               + r"\1a&H" + alpha + r"&\bord0\shad0}" + rect)
        events.append(f"Dialogue: 0,0:00:00.00,{end_t},Mask,,0,0,0,," + tag)

    def emit_line(layer: int, x: float, y: float, align: int,
                  size: int, text: str, is_title: bool, style: str):
        safe = text.replace("{", "（").replace("}", "）")
        selected_font = title_font if is_title else body_font
        base = ("{" + r"\an" + str(align) + r"\pos(" + f"{x:.1f},{y:.1f}" + r")\fn"
                + selected_font + r"\fs" + str(size))
        if effect == "double_outline":
            events.append(
                f"Dialogue: {layer},0:00:00.00,{end_t},{style},,0,0,0,,"
                + base + _double_outer_tags(settings, is_title=is_title) + "}" + safe
            )
            events.append(
                f"Dialogue: {layer + 1},0:00:00.00,{end_t},{style},,0,0,0,,"
                + base + _text_style_tags(settings, is_title=is_title) + "}" + safe
            )
        else:
            events.append(
                f"Dialogue: {layer},0:00:00.00,{end_t},{style},,0,0,0,,"
                + base + _text_style_tags(settings, is_title=is_title) + "}" + safe
            )

    for index, item in enumerate(layout["lines"]):
        is_title = item["kind"] == "title"
        emit_line(
            (10 if is_title else 40) + index * 2,
            float(item["x"]), float(item["y"]), int(item["align"]),
            int(item["size"]), str(item["text"]), is_title,
            "Title" if is_title else "Body",
        )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {CANVAS_W}
PlayResY: {CANVAS_H}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{title_font},{title_size},{title_color},{title_color},{outline_color},&H90000000,{title_bold},0,0,0,100,100,{spacing},0,1,{outline_w},{shadow},{alignment},40,40,{margin_v},1
Style: Body,{body_font},{body_size},{body_color},{body_color},{outline_color},&H90000000,{body_bold},0,0,0,100,100,{spacing},0,1,{outline_w},{shadow},{alignment},40,40,{margin_v},1
Style: DoubleOuter,{title_font},{title_size},{highlight},{highlight},{highlight},&H90000000,{title_bold},0,0,0,100,100,{spacing},0,1,{outline_w + 3},0,{alignment},40,40,{margin_v},1
Style: Mask,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return path


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复输出名：{path.name}")


def escape_ffmpeg_filter_path(path) -> str:
    value = str(path).replace("\\", "/")
    for source, target in (
        ("'", r"\'"), (":", r"\:"), (",", r"\,"), (";", r"\;"),
        ("[", r"\["), ("]", r"\]"), ("(", r"\("), (")", r"\)"), (" ", r"\ "),
    ):
        value = value.replace(source, target)
    return value


def ass_filter_expression(ass_path) -> str:
    """与 Reels 一致：ASS + fontsdir，保证开源/导入字体导出可找到。"""
    expression = f"ass=filename='{escape_ffmpeg_filter_path(ass_path)}'"
    try:
        folder = render_font_dir()
        if folder.is_dir():
            expression += f":fontsdir='{escape_ffmpeg_filter_path(folder)}'"
    except Exception:
        pass
    return expression


class VideoPresetRenderWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, jobs: list[dict], settings: dict, ffmpeg: str, text_to_speech_fn=None):
        super().__init__()
        self.jobs = jobs
        self.settings = dict(settings or {})
        self.ffmpeg = ffmpeg
        self.text_to_speech_fn = text_to_speech_fn
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            out_dir = Path(self.settings.get("output_dir") or default_output_path("video_presets"))
            out_dir.mkdir(parents=True, exist_ok=True)
            total = max(1, len(self.jobs))
            done = 0
            for job in self.jobs:
                if self.cancelled:
                    raise RuntimeError("任务已停止；已完成的文件仍保留在输出目录。")
                media = Path(job["media"])
                title = str(job.get("title") or "")
                body = str(job.get("body") or "")
                tts_path = Path(job["tts"]) if job.get("tts") else None
                self.log.emit(f"渲染：{media.name}")
                work = Path(tempfile.mkdtemp(prefix="vpreset_"))
                try:
                    if job.get("generate_tts") and not (tts_path and tts_path.is_file()):
                        if not callable(self.text_to_speech_fn):
                            raise RuntimeError("已选择文案转语音，但当前没有可用的 TTS 服务。")
                        # 标题+正文都要读；勿用 strip("。\n") 吃掉句首/句尾内容
                        _t = title.strip()
                        _b = body.strip()
                        if _t and _b:
                            joiner = "。" if re.search(r"[\u3400-\u9fff]", _t + _b) else ". "
                            if _t[-1:] in "。.!！?？;；":
                                speech_text = f"{_t} {_b}".strip()
                            else:
                                speech_text = f"{_t}{joiner}{_b}".strip()
                        else:
                            speech_text = _t or _b
                        if speech_text:
                            target = work / "batch_tts.mp3"
                            self.log.emit(f"生成配音：{media.name}")
                            generated = self.text_to_speech_fn(
                                speech_text,
                                str(job.get("tts_service") or self.settings.get("tts_service") or "微软文字转语音"),
                                str(job.get("tts_voice") or self.settings.get("tts_voice") or ""),
                                str(target),
                            )
                            tts_path = Path(generated) if generated else target
                            if not tts_path.is_file() or tts_path.stat().st_size < 128:
                                raise RuntimeError(f"未生成有效配音：{media.name}")
                    duration = media_duration(self.ffmpeg, media, fallback=8.0)
                    if tts_path and tts_path.is_file():
                        duration = max(duration, media_duration(self.ffmpeg, tts_path, fallback=duration))
                    ass = build_preset_ass(work / "caption.ass", title, body, self.settings, duration)
                    is_image = media.suffix.lower() in IMAGE_EXTENSIONS
                    vf = (
                        f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
                        f"crop={CANVAS_W}:{CANVAS_H},"
                        f"setsar=1,{ass_filter_expression(ass)}"
                    )
                    dest = unique_path(out_dir / f"{media.stem}_预设.mp4")
                    cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
                    if is_image:
                        cmd += ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(media)]
                    else:
                        cmd += ["-i", str(media)]

                    keep_orig = bool(self.settings.get("keep_original_audio", True)) and not is_image
                    has_tts = tts_path is not None and tts_path.is_file()
                    bgm_file = None
                    bgm_ss_ms = 0
                    if self.settings.get("bgm_enabled"):
                        mode = str(self.settings.get("bgm_selection_mode") or "fixed")
                        if mode == "random_folder":
                            bgm_file = find_bgm_file(
                                self.settings.get("bgm_dir"), done, media, randomize=True)
                            if bgm_file:
                                bgm_ss_ms = random_bgm_start_ms(self.ffmpeg, bgm_file, media, done)
                        else:
                            p = Path(str(self.settings.get("bgm_path") or ""))
                            if p.is_file():
                                bgm_file = p
                            elif self.settings.get("bgm_dir"):
                                bgm_file = find_bgm_file(
                                    self.settings.get("bgm_dir"), done, media, False)

                    if has_tts:
                        cmd += ["-i", str(tts_path)]
                    if bgm_file:
                        if bgm_ss_ms > 0:
                            cmd += ["-ss", f"{bgm_ss_ms / 1000:.3f}"]
                        cmd += ["-i", str(bgm_file)]

                    a_filters = []
                    amix_labels = []
                    next_a = 1
                    if keep_orig and not has_tts:
                        vol = max(0, min(200, int(self.settings.get("original_volume", 100)))) / 100
                        a_filters.append(
                            f"[0:a:0]aresample=48000,aformat=channel_layouts=stereo,volume={vol:.3f}[a_orig]"
                        )
                        amix_labels.append("[a_orig]")
                    if has_tts:
                        a_filters.append(
                            f"[{next_a}:a:0]aresample=48000,aformat=channel_layouts=stereo,volume=1.0[a_tts]"
                        )
                        amix_labels.append("[a_tts]")
                        next_a += 1
                    if bgm_file:
                        bvol = max(0, min(200, int(self.settings.get("bgm_volume", 25)))) / 100
                        a_filters.append(
                            f"[{next_a}:a:0]aresample=48000,aformat=channel_layouts=stereo,"
                            f"volume={bvol:.3f},apad=pad_dur=86400[a_bgm]"
                        )
                        amix_labels.append("[a_bgm]")

                    cmd += ["-vf", vf, "-t", f"{duration:.3f}"]
                    if len(amix_labels) >= 2:
                        filt = ";".join(a_filters) + ";" + "".join(amix_labels)
                        filt += (
                            f"amix=inputs={len(amix_labels)}:duration=first:"
                            f"dropout_transition=2:normalize=0[aout]"
                        )
                        cmd += ["-filter_complex", filt, "-map", "0:v:0", "-map", "[aout]"]
                    elif len(amix_labels) == 1:
                        filt = ";".join(a_filters)
                        cmd += ["-filter_complex", filt, "-map", "0:v:0", "-map", amix_labels[0]]
                    else:
                        cmd += ["-map", "0:v:0", "-an"]

                    cmd += [
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", str(dest),
                    ]
                    result = subprocess.run(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace", **hidden_kwargs(),
                    )
                    if result.returncode or not dest.is_file() or dest.stat().st_size < 1024:
                        err = (result.stderr or "")[-800:]
                        raise RuntimeError(f"渲染失败 {media.name}：{err or 'FFmpeg 未生成文件'}")
                    self.log.emit(f"完成：{dest}")
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                done += 1
                self.progress.emit(round(done / total * 100))
            self.finished.emit(True, f"已渲染 {done} 个视频。\n{out_dir}")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class ScriptProjectDialog(QDialog):
    """批量维护“标题 + 正文 + 视频素材”的一一对应关系。"""

    def __init__(self, rows: list[dict] | None = None, default_tts: bool = False, parent=None):
        super().__init__(parent)
        self.default_tts = bool(default_tts)
        self.setWindowTitle("批量添加文案与视频素材")
        self.resize(1050, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        hint = QLabel(
            "每行是一个项目：项目序号、标题、正文和视频素材严格对应。"
            "标题留空时，全部文字使用正文样式。"
        )
        hint.setStyleSheet("color:#7dd3fc;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["项目序号", "标题", "文案", "视频素材", "转语音", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(False)
        # 使用纯色，不跟随全局渐变主题，保证表格内容清楚。
        self.table.setStyleSheet(
            "QTableWidget{background:#0b1424;alternate-background-color:#0b1424;"
            "gridline-color:#334155;color:#e5edf8;}"
            "QTableWidget::item{background:#0b1424;color:#e5edf8;padding:5px;}"
            "QTableWidget::item:selected{background:#1d4ed8;color:#ffffff;}"
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(3, 245)
        root.addWidget(self.table, 1)

        tools = QHBoxLayout()
        add_btn = QPushButton("+ 添加项目")
        add_btn.clicked.connect(self._add_empty_row)
        paste_btn = QPushButton("从 Excel 粘贴")
        paste_btn.setToolTip(
            "支持：正文；标题/正文；项目序号/标题/正文；项目序号/标题/正文/素材路径。"
        )
        paste_btn.clicked.connect(self._paste_rows)
        media_btn = QPushButton("批量导入素材")
        media_btn.setToolTip("多选图片或视频后按文件名自然排序，依次匹配第 1、2、3… 个项目。")
        media_btn.clicked.connect(self._batch_choose_media)
        remove_btn = QPushButton("删除选中")
        remove_btn.clicked.connect(self._delete_selected)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self.table.setRowCount(0))
        for button in (add_btn, paste_btn, media_btn, remove_btn, clear_btn):
            tools.addWidget(button)
        tools.addStretch(1)
        root.addLayout(tools)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存项目")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for row in rows or []:
            self._add_empty_row(row)
        if self.table.rowCount() == 0:
            self._add_empty_row()

    @staticmethod
    def _media_filter() -> str:
        return (
            "图片/视频素材 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v "
            "*.jpg *.jpeg *.png *.webp *.bmp);;所有文件 (*.*)"
        )

    def _renumber(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0) or QTableWidgetItem()
            item.setText(str(row + 1))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)

    def _set_media(self, row: int, path: str):
        button = self.table.cellWidget(row, 3)
        if not isinstance(button, QPushButton):
            return
        path = str(path or "").strip()
        button.media_path = path
        button.setText(Path(path).name if path else "添加视频素材…")
        button.setToolTip(path or "为当前项目选择一个视频素材")

    def _choose_row_media(self, button: QPushButton):
        path, _ = QFileDialog.getOpenFileName(self, "选择当前项目的视频素材", "", self._media_filter())
        if not path:
            return
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 3) is button:
                self._set_media(row, path)
                break

    def _add_empty_row(self, data: dict | None = None):
        data = data or {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 42)
        self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table.setItem(row, 1, QTableWidgetItem(str(data.get("title") or "")))
        self.table.setItem(row, 2, QTableWidgetItem(str(data.get("body") or "")))
        media = QPushButton()
        media.setStyleSheet("QPushButton{background:#16243a;color:#e5edf8;text-align:left;padding:5px;}" )
        media.clicked.connect(lambda _checked=False, b=media: self._choose_row_media(b))
        self.table.setCellWidget(row, 3, media)
        self._set_media(row, str(data.get("media") or ""))
        tts = QTableWidgetItem("")
        tts.setFlags((tts.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
        tts.setCheckState(
            Qt.CheckState.Checked
            if bool(data.get("generate_tts", self.default_tts)) else Qt.CheckState.Unchecked
        )
        self.table.setItem(row, 4, tts)
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(lambda _checked=False, b=delete_btn: self._delete_button_row(b))
        self.table.setCellWidget(row, 5, delete_btn)
        self._renumber()

    def _delete_button_row(self, button: QPushButton):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 5) is button:
                self.table.removeRow(row)
                self._renumber()
                break

    def _delete_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._renumber()

    def _ensure_rows(self, count: int):
        while self.table.rowCount() < count:
            self._add_empty_row()

    @staticmethod
    def _parsed_clipboard_rows(text: str) -> list[dict]:
        result = []
        for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if not line.strip():
                continue
            cells = [cell.strip() for cell in line.split("\t")]
            if len(cells) == 1:
                cells = [cell.strip() for cell in re.split(r"\s*(?:\||｜)\s*", line, maxsplit=3)]
            if cells and cells[0].lower() in {"序号", "项目序号", "编号"}:
                continue
            number_first = bool(cells and re.fullmatch(r"\d+", cells[0] or ""))
            if number_first:
                cells = cells[1:]
            if len(cells) >= 3:
                result.append({"title": cells[0], "body": cells[1], "media": cells[2]})
            elif len(cells) == 2:
                result.append({"title": cells[0], "body": cells[1], "media": ""})
            else:
                result.append({"title": "", "body": cells[0] if cells else "", "media": ""})
        return result

    def _paste_rows(self):
        rows = self._parsed_clipboard_rows(QApplication.clipboard().text())
        if not rows:
            QMessageBox.information(self, "剪贴板为空", "请先从 Excel 或文本中复制文案。")
            return
        # 只有一个完全空的占位项目时，直接覆盖它。
        if self.table.rowCount() == 1:
            placeholder = self.get_rows(include_empty=True)[0]
            if not any((placeholder.get("media"), placeholder.get("title"), placeholder.get("body"))):
                self.table.setRowCount(0)
        start = self.table.rowCount()
        for data in rows:
            self._add_empty_row(data)
        self.table.selectRow(start)

    def _batch_choose_media(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "批量选择图片或视频素材", "", self._media_filter())
        if not paths:
            return
        paths = sorted(paths, key=lambda p: natural_key(Path(p).name))
        self._ensure_rows(len(paths))
        for row, path in enumerate(paths):
            self._set_media(row, path)

    def get_rows(self, include_empty: bool = False) -> list[dict]:
        rows = []
        for row in range(self.table.rowCount()):
            title_item = self.table.item(row, 1)
            body_item = self.table.item(row, 2)
            tts_item = self.table.item(row, 4)
            media_btn = self.table.cellWidget(row, 3)
            data = {
                "media": str(getattr(media_btn, "media_path", "") or ""),
                "title": title_item.text().strip() if title_item else "",
                "body": body_item.text().strip() if body_item else "",
                "generate_tts": bool(tts_item and tts_item.checkState() == Qt.CheckState.Checked),
            }
            if include_empty or any((data["media"], data["title"], data["body"])):
                rows.append(data)
        return rows

    def _validate_and_accept(self):
        rows = self.get_rows()
        if not rows:
            QMessageBox.information(self, "没有项目", "请至少添加一条文案和对应的视频素材。")
            return
        missing = [str(i + 1) for i, row in enumerate(rows) if not row.get("media")]
        if missing:
            QMessageBox.warning(self, "缺少素材", f"项目 {', '.join(missing)} 还没有添加图片或视频素材。")
            return
        invalid = [str(i + 1) for i, row in enumerate(rows) if not Path(row.get("media", "")).is_file()]
        if invalid:
            QMessageBox.warning(self, "素材不存在", f"项目 {', '.join(invalid)} 的素材路径不存在，请重新选择。")
            return
        self.accept()


class VideoPresetPage(QWidget):
    """布局对齐 Reels：左素材栏 · 中预览 · 右设置 · 底多轨时间轴。"""

    navigate_requested = Signal(int)

    def __init__(self, text_to_speech_fn=None, find_ffmpeg_fn=None, parent=None):
        super().__init__(parent)
        self._text_to_speech = text_to_speech_fn
        self._find_ffmpeg = find_ffmpeg_fn or (lambda: find_media_tool("ffmpeg") or "ffmpeg")
        self._thread = None
        self._worker = None
        self._tts_cache: dict[str, str] = {}
        self._loading_script_fields = False
        self._pending_script_rows: list[dict] = []
        self._settings_ini = QSettings("VideoToolkit", "VideoPreset")
        self._preview_base = QImage()
        self._preview_sound_on = False
        self._preview_video_volume = 0.65
        self._is_image_preview = False
        self._image_source = QImage()
        self._current_media_path = ""
        # 参考图专用的固定构图区。它们不由字符数量改写，只由预设或用户保存的
        # 配置决定；body_flow 用于下半段避开人物、花朵、十字架等主体。
        self._title_y_pct = None
        self._body_y_pct = None
        self._body_flow: list[dict] = []
        self._live_refresh = QTimer(self)
        self._live_refresh.setSingleShot(True)
        self._live_refresh.setInterval(40)
        self._live_refresh.timeout.connect(self._paint_preview)
        self._build_ui()
        self._load_memory()

    # ================================================================== UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(6)

        # —— 顶栏（同 Reels）——
        self.output_dir = QLineEdit(str(default_output_path("video_presets")))
        self.output_dir.setMinimumWidth(160)
        self.output_dir.setMaximumWidth(260)
        choose_out = QPushButton("选择…")
        choose_out.clicked.connect(self._pick_output)
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumWidth(90)
        self.progress.setMaximumWidth(140)
        self.progress_value = QLabel("0%")
        self.progress_value.setFixedWidth(36)
        self.progress.valueChanged.connect(lambda v: self.progress_value.setText(f"{v}%"))

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "background:#991b1b;color:white;border-color:#fca5a5;padding:3px 8px;min-height:18px;"
        )
        self.stop_btn.clicked.connect(self._stop_render)
        self.render_one_btn = QPushButton("渲染当前")
        self.render_one_btn.clicked.connect(lambda: self._start_render(False))
        self.render_all_btn = QPushButton("批量导出")
        self.render_all_btn.setObjectName("primary")
        self.render_all_btn.setStyleSheet("padding:3px 12px;min-height:18px;")
        self.render_all_btn.clicked.connect(lambda: self._start_render(True))

        header = QHBoxLayout()
        heading = QLabel("视频预设")
        heading.setObjectName("heading")
        flow = QLabel(
            " 素材 → 标题/正文 → 样式/蒙版 → 预览核对 → BGM/TTS → 时间轴 → 批量导出"
        )
        flow.setStyleSheet("font-size:11px;color:#94a3b8;margin-left:8px;")
        header.addWidget(heading)
        header.addWidget(flow)
        header.addStretch()
        header.addWidget(QLabel("输出:"))
        header.addWidget(self.output_dir)
        header.addWidget(choose_out)
        header.addWidget(self.progress)
        header.addWidget(self.progress_value)
        header.addWidget(self.render_one_btn)
        header.addWidget(self.stop_btn)
        header.addWidget(self.render_all_btn)
        root.addLayout(header)

        # —— 左：素材项目（竖向图标 + 内容栈，同 Reels）——
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)
        left.setMinimumWidth(260)

        source_group = QGroupBox("素材项目")
        source_group.setMinimumHeight(280)
        source_hl = QHBoxLayout(source_group)
        source_hl.setContentsMargins(8, 10, 8, 8)

        source_rail = QWidget()
        rail_l = QVBoxLayout(source_rail)
        rail_l.setContentsMargins(2, 2, 2, 2)
        rail_l.setSpacing(6)
        self.source_tool_buttons = []
        for i, title in enumerate(("素材", "文案/TTS", "背景音乐", "输出/日志")):
            btn = QPushButton(title)
            btn.setCheckable(True)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda checked=False, idx=i: self._show_source_tool(idx))
            rail_l.addWidget(btn)
            self.source_tool_buttons.append(btn)
        rail_l.addStretch()
        rail_scroll = QScrollArea()
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rail_scroll.setMinimumWidth(94)
        rail_scroll.setMaximumWidth(128)
        rail_scroll.setWidget(source_rail)

        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self._build_media_tab())
        self.source_stack.addWidget(self._build_script_tab())
        self.source_stack.addWidget(self._build_bgm_tab())
        self.source_stack.addWidget(self._build_output_tab())

        source_hl.addWidget(rail_scroll)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet("color:#334155;")
        source_hl.addWidget(divider)
        source_hl.addWidget(self.source_stack, 1)
        source_group.setStyleSheet(
            "QPushButton:checked{background:#2563eb;color:white;border-color:#60a5fa;font-weight:700;}"
        )
        left_layout.addWidget(source_group, 1)
        self._show_source_tool(0)

        # —— 中：视频预览（同 Reels）——
        center = QWidget()
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(4, 0, 4, 0)
        center_l.setSpacing(6)
        self.center_panel = center

        preview_group = QGroupBox("视频预览与定位")
        preview_l = QVBoxLayout(preview_group)
        preview_l.setContentsMargins(9, 10, 9, 8)

        self.video_widget = QLabel("添加或选择素材后在这里预览")
        self.video_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_widget.setMinimumSize(200, 240)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.video_widget.setScaledContents(False)
        self.video_widget.setStyleSheet(
            "background:#02050b;color:#64748b;border:1px solid #334155;border-radius:7px;"
        )
        preview_l.addWidget(self.video_widget, 1)
        # 与 Reels 一致：预览组本身占满中间列高度
        preview_group.setMinimumHeight(280)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.0)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_sink = QVideoSink(self)
        self.player.setVideoOutput(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._video_frame_changed)
        self.player.positionChanged.connect(self._preview_position_changed)
        self.player.durationChanged.connect(self._preview_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state)

        self.bgm_player = QMediaPlayer(self)
        self.bgm_audio = QAudioOutput(self)
        self.bgm_audio.setVolume(0.0)
        self.bgm_player.setAudioOutput(self.bgm_audio)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.play_btn.setToolTip("播放 / 暂停预览（空格）")
        self.play_btn.clicked.connect(self.toggle_preview)
        self._space_sc = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._space_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._space_sc.setAutoRepeat(False)
        self._space_sc.activated.connect(self.toggle_preview)
        self.sound_btn = QPushButton("🔇 静音")
        self.sound_btn.setCheckable(True)
        self.sound_btn.setChecked(True)
        self.sound_btn.setMinimumWidth(72)
        self.sound_btn.setToolTip("预览声音开关（默认静音）")
        self.sound_btn.toggled.connect(self._on_sound_toggled)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self._seek_preview)
        self.time_label = QLabel("00:00 / 00:00")
        controls.addWidget(self.play_btn)
        controls.addWidget(self.sound_btn)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.time_label)
        preview_l.addLayout(controls)

        live_row = QHBoxLayout()
        self.live_preview = QCheckBox("实时显示字幕 / 蒙版效果")
        self.live_preview.setChecked(True)
        self.live_preview.setToolTip("开启后在预览上叠加标题、正文与蒙版；改样式即时刷新")
        self.live_preview.toggled.connect(lambda _: self._schedule_live_refresh())
        live_hint = QLabel("勾选后预览叠加字幕效果；最终以导出为准")
        live_hint.setStyleSheet("color:#7dd3fc;")
        live_row.addWidget(self.live_preview)
        live_row.addStretch()
        live_row.addWidget(live_hint)
        preview_l.addLayout(live_row)

        pos_preview = QHBoxLayout()
        pos_preview.addWidget(QLabel("字幕上下位置"))
        self.preview_position_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_position_slider.setRange(20, 900)
        self.preview_position_slider.setValue(380)
        self.preview_position_slider.setToolTip("向右抬高字幕；与右侧「边距」同步")
        self.preview_position_value = QLabel("边距 380")
        self.preview_position_slider.valueChanged.connect(self._preview_margin_changed)
        pos_preview.addWidget(QLabel("低"))
        pos_preview.addWidget(self.preview_position_slider, 1)
        pos_preview.addWidget(QLabel("高"))
        pos_preview.addWidget(self.preview_position_value)
        preview_l.addLayout(pos_preview)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_preview_btn = QPushButton("刷新预览")
        self.refresh_preview_btn.setObjectName("primary")
        self.refresh_preview_btn.setToolTip("重新加载当前素材到预览与时间轴")
        self.refresh_preview_btn.clicked.connect(self._load_current_media)
        refresh_row.addWidget(self.refresh_preview_btn)
        preview_l.addLayout(refresh_row)
        center_l.addWidget(preview_group, 1)

        # —— 右：设置轨 + 栈（样式 / 蒙版）；预设管理合并进字幕样式 ——
        right_panel = QWidget()
        right_hl = QHBoxLayout(right_panel)
        right_hl.setContentsMargins(0, 0, 0, 0)
        right_panel.setMinimumWidth(280)

        right_rail = QWidget()
        rr_l = QVBoxLayout(right_rail)
        rr_l.setContentsMargins(2, 2, 2, 2)
        rr_l.setSpacing(6)
        self.right_setting_buttons = []
        for i, title in enumerate(("字幕样式", "蒙版")):
            btn = QPushButton(title)
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda checked=False, idx=i: self._show_right_setting(idx))
            rr_l.addWidget(btn)
            self.right_setting_buttons.append(btn)
        rr_l.addStretch()
        rr_scroll = QScrollArea()
        rr_scroll.setWidgetResizable(True)
        rr_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rr_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rr_scroll.setMinimumWidth(92)
        rr_scroll.setMaximumWidth(132)
        rr_scroll.setWidget(right_rail)

        self.right_settings_stack = QStackedWidget()
        self.right_settings_stack.addWidget(self._wrap_scroll(self._build_style_panel()))
        self.right_settings_stack.addWidget(self._wrap_scroll(self._build_mask_panel()))
        self._show_right_setting(0)

        right_hl.addWidget(rr_scroll)
        rdiv = QFrame()
        rdiv.setFrameShape(QFrame.Shape.VLine)
        rdiv.setStyleSheet("color:#334155;")
        right_hl.addWidget(rdiv)
        right_hl.addWidget(self.right_settings_stack, 1)

        # —— 工作区：与 Reels 一致 —— 顶栏提示 + 横向 [预览 | 设置]，预览占满剩余高度
        screen = QApplication.primaryScreen()
        screen_width = screen.availableGeometry().width() if screen else 1440
        usable = max(900, min(screen_width, 1920) - 40)
        left_w = max(280, int(usable * 0.28))
        right_w = max(580, usable - left_w)
        preview_w = int(right_w * 0.55)
        settings_w = right_w - preview_w

        work_group = QGroupBox("工作设置区 · 实时预览与字幕设计")
        self.work_group = work_group
        work_gl = QVBoxLayout(work_group)
        work_gl.setContentsMargins(7, 10, 7, 7)
        work_gl.setSpacing(4)

        work_top = QHBoxLayout()
        work_top.setContentsMargins(0, 0, 0, 2)
        work_hint = QLabel("中间预览 · 右侧改样式/蒙版即时叠加 · 底部时间轴")
        work_hint.setStyleSheet("color:#7dd3fc;font-size:11px;")
        work_hint.setWordWrap(True)
        work_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        work_hint.setMaximumHeight(22)
        work_top.addWidget(work_hint, 1)
        work_gl.addLayout(work_top, 0)

        center.setMinimumWidth(240)
        center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_panel.setMinimumWidth(280)
        right_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        preview_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        work_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.work_splitter = work_splitter
        work_splitter.setChildrenCollapsible(True)
        work_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        work_splitter.addWidget(center)
        work_splitter.addWidget(right_panel)
        work_splitter.setSizes([preview_w, settings_w])
        work_splitter.setStretchFactor(0, 3)
        work_splitter.setStretchFactor(1, 2)
        # 关键：必须 stretch=1，否则预览区被压在底部、上方大片空白（与 Reels 不一致）
        work_gl.addWidget(work_splitter, 1)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter = workspace
        workspace.setChildrenCollapsible(True)
        left.setMinimumWidth(260)
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        work_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        workspace.addWidget(left)
        workspace.addWidget(work_group)
        workspace.setSizes([left_w, right_w])
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 3)

        try:
            timeline_ffmpeg = self._find_ffmpeg()
        except Exception:
            timeline_ffmpeg = "ffmpeg"
        self.timeline = CanvaTimelinePanel(str(timeline_ffmpeg or "ffmpeg"))
        self.timeline.seekRequested.connect(self._seek_preview)
        self.timeline.bgmVolumeChanged.connect(self.bgm_volume.setValue)
        self.bgm_volume.valueChanged.connect(self.timeline.volume.setValue)

        timeline_splitter = QSplitter(Qt.Orientation.Vertical)
        self.timeline_splitter = timeline_splitter
        timeline_splitter.setChildrenCollapsible(False)
        timeline_splitter.addWidget(workspace)
        timeline_splitter.addWidget(self.timeline)
        timeline_splitter.setStretchFactor(0, 4)
        timeline_splitter.setStretchFactor(1, 2)
        timeline_splitter.setSizes([590, 245])
        root.addWidget(timeline_splitter, 1)

        self._connect_live_signals()
        self._refresh_auto_body_size_label()
        # 首帧后按窗口比例再平衡一次（同 Reels）
        QTimer.singleShot(0, self._rebalance_layout)

    def _wrap_scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def _build_media_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 4, 4, 4)
        self.media_list = DropListWidget()
        self.media_list.setMinimumHeight(110)
        self.media_list.paths_dropped.connect(self._add_media_paths)
        self.media_list.currentTextChanged.connect(self._on_media_selected)
        lay.addWidget(self.media_list, 1)
        row = QHBoxLayout()
        add_m = QPushButton("添加素材")
        add_m.clicked.connect(self._browse_media)
        add_f = QPushButton("添加文件夹")
        add_f.clicked.connect(self._browse_media_folder)
        clear_m = QPushButton("清空")
        clear_m.clicked.connect(self._clear_media)
        for b in (add_m, add_f, clear_m):
            row.addWidget(b)
        lay.addLayout(row)
        return tab

    def _build_script_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(6, 8, 6, 6)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("标题（字号 90，#820000 加粗）")
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText(
            "正文… 字号自动：<50→60+ · 50-100→55 · 200-300→44 · 350-400→40 · 500-550→33 · 最小20"
        )
        self.body_edit.setMinimumHeight(120)
        self.body_edit.textChanged.connect(self._on_script_changed)
        self.title_edit.textChanged.connect(self._on_current_script_fields_changed)
        self.auto_size_label = QLabel("正文字号（自动）：—")
        self.auto_size_label.setStyleSheet("color:#7dd3fc;")
        self.writing_language = QComboBox()
        fill_writing_language_combo(self.writing_language)
        self.writing_language.currentTextChanged.connect(lambda _: self._schedule_live_refresh())
        form.addRow("标题", self.title_edit)
        form.addRow("正文", self.body_edit)
        form.addRow("", self.auto_size_label)
        form.addRow("书写语言", self.writing_language)

        self.script_table = QTableWidget(0, 5)
        self.script_table.setHorizontalHeaderLabels(["序号", "素材", "标题", "正文", "转语音"])
        self.script_table.setMinimumHeight(190)
        self.script_table.setAlternatingRowColors(False)
        self.script_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.script_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.script_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.script_table.setStyleSheet(
            "QTableWidget{background:#0b1424;alternate-background-color:#0b1424;"
            "gridline-color:#334155;color:#e5edf8;}"
            "QTableWidget::item{background:#0b1424;color:#e5edf8;padding:4px;}"
            "QTableWidget::item:selected{background:#1d4ed8;color:#ffffff;}"
        )
        self.script_table.verticalHeader().setVisible(False)
        header = self.script_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.script_table.setColumnWidth(2, 150)
        self.script_table.itemChanged.connect(self._script_table_item_changed)
        self.script_table.cellClicked.connect(self._script_table_row_clicked)
        self.script_table.cellDoubleClicked.connect(lambda _row, _col: self._open_script_projects())
        self.batch_script_count = QLabel("未添加批量文案")
        self.batch_script_count.setStyleSheet("color:#94a3b8;")
        manage_batch = QPushButton("添加/管理文案…")
        manage_batch.setToolTip("打开项目表格：逐行添加项目序号、标题、正文和视频素材，支持批量导入。")
        manage_batch.clicked.connect(self._open_script_projects)
        batch_clear = QPushButton("清空文案")
        batch_clear.clicked.connect(self._clear_script_table_text)
        batch_row = QHBoxLayout()
        batch_row.addWidget(self.batch_script_count, 1)
        batch_row.addWidget(manage_batch)
        batch_row.addWidget(batch_clear)
        form.addRow("文案表格", self.script_table)
        form.addRow(batch_row)

        self.tts_enabled = QCheckBox("全部文案转语音（表格内可逐条取消）")
        self.tts_service = QComboBox()
        self.tts_service.addItems(["微软文字转语音", "Gemini 自然语音", "ElevenLabs API"])
        self.tts_voice = QLineEdit()
        self.tts_voice.setPlaceholderText("微软：en-US-JennyNeural / ElevenLabs Voice ID")
        form.addRow("转语音", self.tts_enabled)
        form.addRow("TTS 服务", self.tts_service)
        form.addRow("音色", self.tts_voice)
        tts_row = QHBoxLayout()
        gen = QPushButton("生成配音")
        gen.setObjectName("primary")
        gen.clicked.connect(self._generate_tts)
        self.tts_status = QLabel("未生成")
        self.tts_status.setStyleSheet("color:#94a3b8;")
        tts_row.addWidget(gen)
        tts_row.addWidget(self.tts_status, 1)
        form.addRow(tts_row)
        self.tts_enabled.toggled.connect(self._set_all_script_tts)
        self.tts_enabled.toggled.connect(self._sync_tts_controls)
        self._sync_tts_controls(False)
        return tab

    def _build_bgm_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(6, 8, 6, 6)
        self.bgm_enabled = QCheckBox("启用 BGM")
        self.bgm_mode = QComboBox()
        self.bgm_mode.addItems(["固定使用选中的音频", "随机从文件夹选择并随机截取"])
        self.bgm_path = QLineEdit()
        self.bgm_path.setPlaceholderText("单个音频…")
        pick_f = QPushButton("选文件")
        pick_f.clicked.connect(self._pick_bgm_file)
        frow = QHBoxLayout()
        frow.addWidget(self.bgm_path, 1)
        frow.addWidget(pick_f)
        self.bgm_dir = QLineEdit()
        self.bgm_dir.setPlaceholderText("BGM 文件夹…")
        pick_d = QPushButton("选文件夹")
        pick_d.clicked.connect(self._pick_bgm_dir)
        drow = QHBoxLayout()
        drow.addWidget(self.bgm_dir, 1)
        drow.addWidget(pick_d)
        self.bgm_volume = QSlider(Qt.Orientation.Horizontal)
        self.bgm_volume.setRange(0, 200)
        self.bgm_volume.setValue(25)
        self.bgm_volume.valueChanged.connect(self._update_preview_audio_levels)
        self.keep_original = QCheckBox("保留视频原声")
        self.keep_original.setChecked(True)
        form.addRow(self.bgm_enabled)
        form.addRow("选择方式", self.bgm_mode)
        form.addRow("固定音频", frow)
        form.addRow("文件夹", drow)
        form.addRow("BGM 音量", self.bgm_volume)
        form.addRow(self.keep_original)
        return tab

    def _build_output_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(6, 8, 6, 6)
        self.run_status = QLabel("等待任务")
        self.run_status.setStyleSheet(
            "color:#67e8f9;background:#0b1830;padding:3px 7px;border-radius:4px;font-weight:700;"
        )
        lay.addWidget(self.run_status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("本板块执行日志…")
        self.log.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;")
        lay.addWidget(self.log, 1)
        return tab

    def _build_style_panel(self) -> QWidget:
        """与 Reels 对齐：系统字体 + 开源字体 + 粗细/描边/阴影/双眼皮/位置。"""
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(10, 12, 10, 10)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(8)

        # 字幕预设：前四项按用户提供的参考视频复刻。
        self.style_quick = QComboBox()
        self.style_quick.addItem("（选择字幕预设）", "")
        for name in STYLE_QUICK_PRESETS:
            self.style_quick.addItem(name, name)
        self.style_quick.setToolTip(
            "选择后会同步标题/正文字体、字号、颜色、蒙版、位置和示例文案；"
            "仍可在下方继续微调。"
        )
        self.style_quick.currentIndexChanged.connect(self._apply_style_quick)
        form.addRow("字幕预设", self.style_quick)

        # 保存、加载、导入、导出紧跟在字幕预设下方，小屏幕也能直接看到。
        preset_title = QLabel("保存 / 导入导出")
        preset_title.setStyleSheet("color:#7dd3fc;font-weight:700;")
        form.addRow(preset_title)
        self.preset_name = QLineEdit("默认视频预设")
        self.preset_name.setPlaceholderText("输入预设名称后点击保存")
        form.addRow("预设名称", self.preset_name)

        preset_actions = QHBoxLayout()
        save_preset = QPushButton("保存")
        save_preset.setObjectName("primary")
        save_preset.setToolTip("保存当前设计好的字幕效果和相关预设配置到本机")
        save_preset.clicked.connect(self._save_preset_local)
        load_preset = QPushButton("加载")
        load_preset.setToolTip("从本机预设目录选择并加载 JSON 预设")
        load_preset.clicked.connect(self._load_preset_local)
        import_preset = QPushButton("导入")
        import_preset.setToolTip("从其他位置导入 JSON 预设")
        import_preset.clicked.connect(self._import_preset)
        export_preset = QPushButton("导出")
        export_preset.setToolTip("把当前设计导出为可备份、分享的 JSON 文件")
        export_preset.clicked.connect(self._export_preset)
        for button in (save_preset, load_preset, import_preset, export_preset):
            button.setMinimumWidth(58)
            preset_actions.addWidget(button)
        form.addRow(preset_actions)

        preset_tip = QLabel("保存后可随时加载；导出的 JSON 可在其他电脑导入，旧预设继续兼容。")
        preset_tip.setWordWrap(True)
        preset_tip.setStyleSheet("color:#94a3b8;font-size:11px;")
        form.addRow(preset_tip)

        # 标题/正文字体可独立设置；字体源仍与 Reels 共用。
        self._load_saved_font_files()
        self.title_font_family = QComboBox()
        self.title_font_family.setEditable(True)
        self.body_font_family = QComboBox()
        self.body_font_family.setEditable(True)
        # 兼容既有调用和第三方预设；新代码分别读取 title_font/body_font。
        self.font_family = self.title_font_family
        self._reload_font_combo(prefer="Roboto")
        title_font_row = QHBoxLayout()
        title_font_row.addWidget(self.title_font_family, 1)
        import_font = QPushButton("导入")
        import_font.setToolTip("导入本机 .ttf/.otf 字体（与 Reels 同一字体目录）")
        import_font.clicked.connect(self._import_font_files)
        open_font = QPushButton("开源字体")
        open_font.setToolTip("安装 Open Sans / Noto / Poppins 等开源字体（同 Reels）")
        open_font.clicked.connect(self._download_open_source_fonts)
        title_font_row.addWidget(import_font)
        title_font_row.addWidget(open_font)
        form.addRow("标题字体", title_font_row)
        form.addRow("正文字体", self.body_font_family)

        self.title_size = QSpinBox()
        self.title_size.setRange(20, 200)
        self.title_size.setValue(90)
        self.body_size = QSpinBox()
        self.body_size.setRange(20, 200)
        self.body_size.setValue(45)
        self.body_auto = QCheckBox("正文按字符数自动字号（最小 20）")
        self.body_auto.setChecked(True)
        self.body_auto.setToolTip(
            "自动字号：50 字以下 60–72；50–100 字 55；200–300 字 44；"
            "350–400 字 40；500–550 字 33；任何情况不低于 20。\n"
            "中间区间平滑过渡，并同步调整每行字符数和行距。"
        )
        self.body_auto.toggled.connect(lambda on: self.body_size.setEnabled(not on))
        self.body_auto.toggled.connect(lambda _on: self._refresh_auto_body_size_label())
        self.body_size.setEnabled(False)
        form.addRow("标题字号", self.title_size)
        form.addRow(self.body_auto)
        form.addRow("正文字号", self.body_size)

        self.title_color_btn = QPushButton("#820000")
        self.title_color_btn.clicked.connect(
            lambda: self._pick_color(self.title_color_btn, "#820000"))
        self._set_color_btn(self.title_color_btn, "#820000")
        self.body_color_btn = QPushButton("#520000")
        self.body_color_btn.clicked.connect(
            lambda: self._pick_color(self.body_color_btn, "#520000"))
        self._set_color_btn(self.body_color_btn, "#520000")
        self.title_bold = QCheckBox("标题加粗")
        self.title_bold.setChecked(True)
        self.body_bold = QCheckBox("正文加粗")
        form.addRow("标题颜色", self.title_color_btn)
        form.addRow("正文颜色", self.body_color_btn)
        bold_row = QHBoxLayout()
        bold_row.addWidget(self.title_bold)
        bold_row.addWidget(self.body_bold)
        form.addRow(bold_row)

        self.outline_color_btn = QPushButton("#FFFFFF")
        self.outline_color_btn.clicked.connect(
            lambda: self._pick_color(self.outline_color_btn, "#FFFFFF"))
        self._set_color_btn(self.outline_color_btn, "#FFFFFF")
        self.outline_width = QSpinBox()
        self.outline_width.setRange(0, 16)
        self.outline_width.setValue(0)
        self.outline_width.setSuffix(" px")
        form.addRow("描边颜色", self.outline_color_btn)
        form.addRow("描边宽度", self.outline_width)

        self.highlight_color_btn = QPushButton("#111111")
        self.highlight_color_btn.clicked.connect(
            lambda: self._pick_color(self.highlight_color_btn, "#111111"))
        self._set_color_btn(self.highlight_color_btn, "#111111")
        self.highlight_color_btn.setToolTip("双眼皮外圈颜色（double_outline）")
        form.addRow("外圈/高亮色", self.highlight_color_btn)

        self.effect = QComboBox()
        for label, code in EFFECT_OPTIONS:
            self.effect.addItem(label, code)
        self.effect.setToolTip(
            "标准描边 · 双眼皮（双描边，同 Reels）· 光晕 · 阴影 · 无特效\n"
            "导出走 libass，与 Reels 字体目录一致。"
        )
        form.addRow("字体效果", self.effect)

        self.shadow = QSpinBox()
        self.shadow.setRange(0, 12)
        self.shadow.setValue(0)
        self.shadow.setSuffix(" px")
        self.shadow.setToolTip("阴影深度；效果选「阴影」时更明显")
        form.addRow("阴影", self.shadow)

        self.background_enabled = QCheckBox("文字底色块")
        self.background_color_btn = QPushButton("#000000")
        self.background_color_btn.clicked.connect(
            lambda: self._pick_color(self.background_color_btn, "#000000"))
        self._set_color_btn(self.background_color_btn, "#000000")
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.background_enabled)
        bg_row.addWidget(self.background_color_btn, 1)
        form.addRow("背景色", bg_row)

        self.letter_spacing = QSpinBox()
        self.letter_spacing.setRange(-20, 40)
        self.letter_spacing.setValue(0)
        self.letter_spacing.setSuffix(" px")
        self.line_spacing = QSpinBox()
        self.line_spacing.setRange(80, 180)
        self.line_spacing.setValue(110)
        self.line_spacing.setSuffix(" %")
        form.addRow("字距", self.letter_spacing)
        form.addRow("行距", self.line_spacing)

        self.position = QComboBox()
        self.position.addItems(list(POSITION_OPTIONS))
        self.position.setCurrentText("底部")
        self.margin_v = QSpinBox()
        self.margin_v.setRange(20, 900)
        self.margin_v.setValue(380)
        self.margin_v.setToolTip("距底/顶边距；与预览区滑条同步")
        pos_row = QHBoxLayout()
        pos_row.addWidget(self.position, 1)
        pos_row.addWidget(QLabel("边距"))
        pos_row.addWidget(self.margin_v)
        form.addRow("字幕位置", pos_row)

        self.title_align = QComboBox()
        self.title_align.addItems(["左对齐", "居中", "右对齐"])
        self.title_align.setCurrentText("居中")
        self.title_x_pct = QSpinBox()
        self.title_x_pct.setRange(0, 100)
        self.title_x_pct.setValue(50)
        self.title_x_pct.setSuffix(" %")
        self.title_width_pct = QSpinBox()
        self.title_width_pct.setRange(20, 100)
        self.title_width_pct.setValue(86)
        self.title_width_pct.setSuffix(" %")
        title_layout = QHBoxLayout()
        title_layout.addWidget(self.title_align, 1)
        title_layout.addWidget(QLabel("X"))
        title_layout.addWidget(self.title_x_pct)
        title_layout.addWidget(QLabel("宽"))
        title_layout.addWidget(self.title_width_pct)
        form.addRow("标题布局", title_layout)

        self.body_align = QComboBox()
        self.body_align.addItems(["左对齐", "居中", "右对齐"])
        self.body_align.setCurrentText("居中")
        self.body_x_pct = QSpinBox()
        self.body_x_pct.setRange(0, 100)
        self.body_x_pct.setValue(50)
        self.body_x_pct.setSuffix(" %")
        self.body_width_pct = QSpinBox()
        self.body_width_pct.setRange(20, 100)
        self.body_width_pct.setValue(86)
        self.body_width_pct.setSuffix(" %")
        body_layout = QHBoxLayout()
        body_layout.addWidget(self.body_align, 1)
        body_layout.addWidget(QLabel("X"))
        body_layout.addWidget(self.body_x_pct)
        body_layout.addWidget(QLabel("宽"))
        body_layout.addWidget(self.body_width_pct)
        form.addRow("正文布局", body_layout)

        for widget in (
            self.title_align, self.title_x_pct, self.title_width_pct,
            self.body_align, self.body_x_pct, self.body_width_pct,
        ):
            widget.setToolTip("标题和正文可独立对齐、移动，并限制在素材留白区域内。")

        tip = QLabel(
            "字体列表 = 系统已装字体 + 本机导入 + 开源字体（与 Reels 共用 fonts 目录）。\n"
            "双眼皮 = 双层描边；导出使用 fontsdir，预览与成片一致。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#94a3b8;font-size:11px;")
        form.addRow(tip)

        return box

    def _build_mask_panel(self) -> QWidget:
        box = QGroupBox("蒙版（1080×1920）")
        form = QFormLayout(box)
        form.setContentsMargins(10, 14, 10, 10)
        self.mask_enabled = QCheckBox("启用蒙版")
        self.mask_enabled.setChecked(True)
        self.mask_color_btn = QPushButton("#ffffff")
        self.mask_color_btn.clicked.connect(
            lambda: self._pick_color(self.mask_color_btn, "#ffffff"))
        self._set_color_btn(self.mask_color_btn, "#ffffff")
        self.mask_opacity = QSpinBox()
        self.mask_opacity.setRange(0, 100)
        self.mask_opacity.setValue(70)
        self.mask_opacity.setSuffix(" %")
        self.mask_x = QDoubleSpinBox()
        self.mask_x.setRange(0, 100)
        self.mask_x.setValue(5)
        self.mask_x.setSuffix(" %")
        self.mask_y = QDoubleSpinBox()
        self.mask_y.setRange(0, 100)
        self.mask_y.setValue(55)
        self.mask_y.setSuffix(" %")
        self.mask_w = QDoubleSpinBox()
        self.mask_w.setRange(1, 100)
        self.mask_w.setValue(90)
        self.mask_w.setSuffix(" %")
        self.mask_h = QDoubleSpinBox()
        self.mask_h.setRange(1, 100)
        self.mask_h.setValue(30)
        self.mask_h.setSuffix(" %")
        form.addRow(self.mask_enabled)
        form.addRow("颜色", self.mask_color_btn)
        form.addRow("不透明度", self.mask_opacity)
        form.addRow("X", self.mask_x)
        form.addRow("Y", self.mask_y)
        form.addRow("宽", self.mask_w)
        form.addRow("高", self.mask_h)
        return box

    def _show_source_tool(self, index: int):
        self.source_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.source_tool_buttons):
            btn.setChecked(i == index)

    def _show_right_setting(self, index: int):
        self.right_settings_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.right_setting_buttons):
            btn.setChecked(i == index)

    def _connect_live_signals(self):
        widgets = [
            self.title_font_family, self.body_font_family,
            self.title_size, self.body_size, self.body_auto,
            self.title_bold, self.body_bold, self.outline_width, self.shadow,
            self.letter_spacing, self.line_spacing, self.margin_v, self.position,
            self.title_align, self.title_x_pct, self.title_width_pct,
            self.body_align, self.body_x_pct, self.body_width_pct,
            self.effect, self.background_enabled, self.mask_enabled, self.mask_opacity,
            self.mask_x, self.mask_y, self.mask_w, self.mask_h,
        ]
        for w in widgets:
            if hasattr(w, "valueChanged"):
                w.valueChanged.connect(lambda *_: self._schedule_live_refresh())
            if hasattr(w, "toggled"):
                w.toggled.connect(lambda *_: self._schedule_live_refresh())
            if hasattr(w, "currentTextChanged"):
                w.currentTextChanged.connect(lambda *_: self._schedule_live_refresh())
            if hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(lambda *_: self._schedule_live_refresh())
        self.margin_v.valueChanged.connect(self._sync_preview_margin_from_spin)

    def _preview_margin_changed(self, value: int):
        self.preview_position_value.setText(f"边距 {value}")
        if hasattr(self, "margin_v"):
            self.margin_v.blockSignals(True)
            self.margin_v.setValue(int(value))
            self.margin_v.blockSignals(False)
        self._schedule_live_refresh()

    def _sync_preview_margin_from_spin(self, value: int):
        if hasattr(self, "preview_position_slider"):
            self.preview_position_slider.blockSignals(True)
            self.preview_position_slider.setValue(int(value))
            self.preview_position_slider.blockSignals(False)
            self.preview_position_value.setText(f"边距 {value}")

    # —— 字体：与 Reels 共用 custom_font_dir / render_font_dir ——
    def _load_saved_font_files(self):
        try:
            for folder in (custom_font_dir(), render_font_dir()):
                if not folder.is_dir():
                    continue
                for path in folder.iterdir():
                    if path.suffix.lower() in (".ttf", ".otf", ".ttc"):
                        QFontDatabase.addApplicationFont(str(path))
        except Exception:
            pass

    def _reload_font_combo(self, prefer: str = "Roboto"):
        families = list(QFontDatabase.families())
        # 常用字体置顶
        pin = ["Roboto", "Roboto Condensed", "Arimo", "Arial", "Segoe UI",
               "Open Sans", "Noto Sans", "Noto Sans SC", "Poppins", "Libre Baskerville"]
        ordered = [f for f in pin if f in families] + [f for f in families if f not in pin]
        combos = [x for x in (
            getattr(self, "title_font_family", None),
            getattr(self, "body_font_family", None),
        ) if x is not None]
        for combo in combos:
            current = combo.currentText() or prefer
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(ordered)
            target = prefer if prefer in ordered else (
                current if current in ordered else (ordered[0] if ordered else "Arial"))
            idx = combo.findText(target)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(target)
            combo.blockSignals(False)

    def _register_font_files(self, paths) -> list[str]:
        families = []
        dest = custom_font_dir()
        dest.mkdir(parents=True, exist_ok=True)
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            target = dest / path.name
            try:
                if not target.exists() or target.stat().st_size != path.stat().st_size:
                    shutil.copy2(path, target)
            except OSError:
                target = path
            font_id = QFontDatabase.addApplicationFont(str(target))
            if font_id >= 0:
                families.extend(QFontDatabase.applicationFontFamilies(font_id))
        return families

    def _import_font_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "导入字体（与 Reels 共用）", "",
            "字体 (*.ttf *.otf *.ttc);;所有 (*.*)",
        )
        if not files:
            return
        families = self._register_font_files(files)
        self._reload_font_combo(prefer=families[0] if families else self.font_family.currentText())
        # 同步 fontsdir 缓存
        try:
            render_font_dir()
        except Exception:
            pass
        self._append_log(f"已导入字体：{', '.join(families) or Path(files[0]).name}")
        QMessageBox.information(self, "字体", f"已导入 {len(files)} 个字体文件。\n家族：{', '.join(families) or '（见列表）'}")

    def _download_open_source_fonts(self):
        names = list(OPEN_SOURCE_FONTS.keys())
        if not names:
            return
        self._append_log("正在下载开源字体…")
        self._font_thread = QThread()
        self._font_worker = FontDownloadWorker(names)
        self._font_worker.moveToThread(self._font_thread)
        self._font_thread.started.connect(self._font_worker.run)
        self._font_worker.finished.connect(self._on_open_fonts_done)
        self._font_thread.start()

    def _on_open_fonts_done(self, ok: bool, message: str, installed: list):
        try:
            if self._font_thread:
                self._font_thread.quit()
                self._font_thread.wait(8000)
        except Exception:
            pass
        self._font_thread = None
        self._font_worker = None
        if installed:
            self._register_font_files(installed)
            self._reload_font_combo()
            try:
                render_font_dir()
            except Exception:
                pass
        self._append_log(message)
        QMessageBox.information(self, "开源字体", message)

    def _apply_style_quick(self, index: int):
        name = self.style_quick.itemData(index) if index >= 0 else ""
        if not name or name not in STYLE_QUICK_PRESETS:
            return
        # 快捷预设只改变视觉参数，绝不能覆盖用户已经填写的标题、正文或批量项目。
        merged = self.current_settings()
        protected_content = {
            "title_text": merged.get("title_text", ""),
            "body_text": merged.get("body_text", ""),
            "script_rows": merged.get("script_rows", []),
        }
        style_data = dict(STYLE_QUICK_PRESETS[name])
        for key in ("title_text", "body_text", "script_rows", "batch_script_text"):
            style_data.pop(key, None)
        merged.update(style_data)
        merged.update(protected_content)
        merged["name"] = name
        self.apply_settings(merged)
        self._append_log(f"已套用字幕预设（文案保持不变）：{name}")

    # ================================================================== helpers
    def _set_color_btn(self, btn: QPushButton, color: str):
        c = color if str(color).startswith("#") else f"#{color}"
        btn.setText(c)
        light = QColor(c).lightness() > 140
        btn.setStyleSheet(
            f"QPushButton{{background:{c};color:{'#111' if light else '#fff'};"
            f"font-weight:700;padding:6px;border-radius:6px;border:1px solid #475569;}}"
        )
        self._schedule_live_refresh()

    def _pick_color(self, btn: QPushButton, fallback: str):
        current = QColor(btn.text() if btn.text().startswith("#") else fallback)
        color = QColorDialog.getColor(
            current if current.isValid() else QColor(fallback), self, "选择颜色")
        if color.isValid():
            self._set_color_btn(btn, color.name())

    def _append_log(self, text: str):
        self.log.appendPlainText(text)
        if hasattr(self, "run_status"):
            self.run_status.setText(text[:80])

    def _char_count(self) -> int:
        return effective_char_count(self.body_edit.toPlainText())

    def _refresh_auto_body_size_label(self):
        n = self._char_count()
        if hasattr(self, "body_auto") and not self.body_auto.isChecked():
            size = self.body_size.value() if hasattr(self, "body_size") else 45
            self.auto_size_label.setText(f"正文字号（固定）：{size}　·　有效字符 {n}（超出时不缩小）")
        else:
            size = body_font_size_for_chars(n)
            self.auto_size_label.setText(f"正文字号（自动）：{size}　·　有效字符 {n}")

    def _on_script_changed(self):
        self._refresh_auto_body_size_label()
        self._sync_current_fields_to_table()
        self._schedule_live_refresh()

    def _on_current_script_fields_changed(self, *_args):
        self._sync_current_fields_to_table()
        self._schedule_live_refresh()

    def _add_media_paths(self, paths):
        existing = {self.media_list.item(i).text() for i in range(self.media_list.count())}
        for p in collect_files(paths, MEDIA_EXTENSIONS):
            if p not in existing:
                self.media_list.addItem(p)
                existing.add(p)
        if self.media_list.count() and not self.media_list.currentItem():
            self.media_list.setCurrentRow(0)
        self._sync_script_table()
        if self.media_list.currentRow() >= 0:
            self._load_table_row_into_current(self.media_list.currentRow())

    def _clear_media(self):
        self.media_list.clear()
        if hasattr(self, "script_table"):
            self.script_table.setRowCount(0)
        self._refresh_batch_script_count()

    def _browse_media(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频或图片", "",
            "媒体 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.jpg *.jpeg *.png *.webp *.bmp);;所有 (*.*)",
        )
        if files:
            self._add_media_paths(files)

    def _browse_media_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if folder:
            self._add_media_paths([folder])

    def _pick_bgm_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 BGM", "",
            "音频 (*.mp3 *.wav *.m4a *.flac *.aac *.ogg);;所有 (*.*)",
        )
        if path:
            self.bgm_path.setText(path)
            self.bgm_enabled.setChecked(True)

    def _pick_bgm_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 BGM 文件夹")
        if folder:
            self.bgm_dir.setText(folder)
            self.bgm_enabled.setChecked(True)
            self.bgm_mode.setCurrentIndex(1)

    def _pick_output(self):
        folder = QFileDialog.getExistingDirectory(self, "输出目录")
        if folder:
            self.output_dir.setText(folder)

    @staticmethod
    def _legacy_batch_text_entries(text: str) -> list[dict]:
        """Read the previous paste format when importing an older preset."""
        text = str(text or "").strip()
        if not text:
            return []
        entries = []
        if re.search(r"(?m)^\s*---+\s*$", text):
            for block in re.split(r"(?m)^\s*---+\s*$", text):
                lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
                if lines:
                    entries.append({"title": lines[0], "body": "\n".join(lines[1:])})
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r"\s*(?:\t|\||｜)\s*", line, maxsplit=1)
                entries.append(
                    {"title": parts[0], "body": parts[1]}
                    if len(parts) == 2 else {"title": "", "body": line}
                )
        return entries

    def _script_item(self, row: int, column: int) -> QTableWidgetItem | None:
        return self.script_table.item(row, column) if 0 <= row < self.script_table.rowCount() else None

    def _table_script_rows(self) -> list[dict]:
        rows = []
        if not hasattr(self, "script_table"):
            return rows
        for row in range(self.script_table.rowCount()):
            media_item = self._script_item(row, 1)
            title_item = self._script_item(row, 2)
            body_item = self._script_item(row, 3)
            tts_item = self._script_item(row, 4)
            rows.append({
                "media": str(media_item.data(Qt.ItemDataRole.UserRole) or "") if media_item else "",
                "title": title_item.text() if title_item else "",
                "body": body_item.text() if body_item else "",
                "generate_tts": bool(tts_item and tts_item.checkState() == Qt.CheckState.Checked),
            })
        return rows

    def _parse_batch_scripts(self) -> list[dict]:
        return self._table_script_rows()

    def _sync_script_table(self):
        if not hasattr(self, "script_table"):
            return
        existing = {row.get("media", ""): row for row in self._table_script_rows() if row.get("media")}
        pending = list(getattr(self, "_pending_script_rows", []) or [])
        current_title = self.title_edit.text() if hasattr(self, "title_edit") else ""
        current_body = self.body_edit.toPlainText() if hasattr(self, "body_edit") else ""
        default_tts = bool(getattr(self, "tts_enabled", None) and self.tts_enabled.isChecked())
        self.script_table.blockSignals(True)
        try:
            self.script_table.setRowCount(self.media_list.count())
            for row in range(self.media_list.count()):
                media = self.media_list.item(row).text()
                saved = existing.get(media) or (pending[row] if row < len(pending) else {})
                values = [str(row + 1), Path(media).name, str(saved.get("title", current_title)), str(saved.get("body", current_body))]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column in (0, 1):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if column == 1:
                        item.setData(Qt.ItemDataRole.UserRole, media)
                        item.setToolTip(media)
                    self.script_table.setItem(row, column, item)
                tts_item = QTableWidgetItem("")
                tts_item.setFlags(
                    (tts_item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable
                )
                tts_item.setCheckState(
                    Qt.CheckState.Checked if bool(saved.get("generate_tts", default_tts)) else Qt.CheckState.Unchecked
                )
                self.script_table.setItem(row, 4, tts_item)
        finally:
            self.script_table.blockSignals(False)
        if self.media_list.count():
            self._pending_script_rows = []
        self._refresh_batch_script_count()

    def _open_script_projects(self):
        """在独立弹窗中维护项目、文案与视频的一一对应关系。"""
        rows = self._table_script_rows()
        dialog = ScriptProjectDialog(
            rows=rows,
            default_tts=bool(self.tts_enabled.isChecked()),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rows = dialog.get_rows()
        if not rows:
            return

        # 弹窗是项目关系的唯一来源；按弹窗顺序同步素材列表与原有渲染表格。
        self.media_list.blockSignals(True)
        self.script_table.blockSignals(True)
        try:
            self.media_list.clear()
            self.script_table.setRowCount(0)
            self._pending_script_rows = list(rows)
            for row in rows:
                self.media_list.addItem(str(row.get("media") or ""))
        finally:
            self.script_table.blockSignals(False)
            self.media_list.blockSignals(False)
        self._sync_script_table()
        if self.media_list.count():
            self.media_list.setCurrentRow(0)
            self._load_table_row_into_current(0)
        self._sync_tts_controls(any(row.get("generate_tts") for row in rows))

    def _paste_script_table(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        lines = [line for line in text.splitlines() if line.strip()]
        start = max(0, self.script_table.currentRow())
        if self.script_table.rowCount() == 0:
            QMessageBox.information(self, "没有素材", "请先添加素材，再按素材顺序粘贴文案。")
            return
        self.script_table.blockSignals(True)
        try:
            for offset, line in enumerate(lines):
                row = start + offset
                if row >= self.script_table.rowCount():
                    break
                parts = line.split("\t")
                if len(parts) < 2:
                    parts = re.split(r"\s*(?:\||｜)\s*", line, maxsplit=1)
                if len(parts) >= 2:
                    title, body = parts[0].strip(), parts[1].strip()
                else:
                    # One column means all content uses the body style.
                    title, body = "", line.strip()
                self._script_item(row, 2).setText(title)
                self._script_item(row, 3).setText(body)
        finally:
            self.script_table.blockSignals(False)
        self._refresh_batch_script_count()
        self._load_table_row_into_current(start)

    def _clear_script_table_text(self):
        self.script_table.blockSignals(True)
        try:
            for row in range(self.script_table.rowCount()):
                self._script_item(row, 2).setText("")
                self._script_item(row, 3).setText("")
        finally:
            self.script_table.blockSignals(False)
        self._refresh_batch_script_count()
        self._load_table_row_into_current(max(0, self.script_table.currentRow()))

    def _set_all_script_tts(self, enabled):
        if not hasattr(self, "script_table"):
            return
        self.script_table.blockSignals(True)
        try:
            for row in range(self.script_table.rowCount()):
                item = self._script_item(row, 4)
                if item:
                    item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        finally:
            self.script_table.blockSignals(False)
        self._refresh_batch_script_count()

    def _script_table_row_clicked(self, row: int, _column: int):
        if 0 <= row < self.media_list.count():
            self.media_list.setCurrentRow(row)

    def _script_table_item_changed(self, item: QTableWidgetItem):
        if item.column() == 4:
            self._refresh_batch_script_count()
            self._sync_tts_controls(any(row.get("generate_tts") for row in self._table_script_rows()))
        if item.row() == self.media_list.currentRow():
            self._load_table_row_into_current(item.row())

    def _load_table_row_into_current(self, row: int):
        if not hasattr(self, "script_table") or not (0 <= row < self.script_table.rowCount()):
            return
        self._loading_script_fields = True
        try:
            self.title_edit.setText(self._script_item(row, 2).text())
            self.body_edit.setPlainText(self._script_item(row, 3).text())
            self.script_table.selectRow(row)
        finally:
            self._loading_script_fields = False
        self._refresh_auto_body_size_label()
        self._schedule_live_refresh()

    def _sync_current_fields_to_table(self):
        if self._loading_script_fields or not hasattr(self, "script_table"):
            return
        row = self.media_list.currentRow()
        if not (0 <= row < self.script_table.rowCount()):
            return
        self.script_table.blockSignals(True)
        try:
            self._script_item(row, 2).setText(self.title_edit.text())
            self._script_item(row, 3).setText(self.body_edit.toPlainText())
        finally:
            self.script_table.blockSignals(False)
        self._refresh_batch_script_count()

    def _refresh_batch_script_count(self):
        rows = self._table_script_rows()
        count = sum(1 for row in rows if row.get("title", "").strip() or row.get("body", "").strip())
        spoken = sum(1 for row in rows if row.get("generate_tts"))
        self.batch_script_count.setText(
            f"已填写 {count}/{len(rows)} 条 · 转语音 {spoken} 条" if rows else "请先添加素材"
        )

    def _sync_tts_controls(self, enabled):
        for widget in (getattr(self, "tts_service", None), getattr(self, "tts_voice", None)):
            if widget is not None:
                widget.setEnabled(bool(enabled))

    def _current_script_tts_enabled(self) -> bool:
        row = self.media_list.currentRow() if hasattr(self, "media_list") else -1
        item = self._script_item(row, 4) if hasattr(self, "script_table") else None
        return bool(item and item.checkState() == Qt.CheckState.Checked)

    # ================================================================== settings
    def current_settings(self) -> dict:
        mode = "random_folder" if self.bgm_mode.currentIndex() == 1 else "fixed"
        effect = self.effect.currentData() if hasattr(self, "effect") else "outline"
        if effect is None:
            effect = "outline"
        return {
            "version": PRESET_VERSION,
            "name": self.preset_name.text().strip() or "未命名预设",
            "title_font_size": self.title_size.value(),
            "body_font_size": self.body_size.value(),
            "body_auto_size": self.body_auto.isChecked(),
            "adaptive_layout": True,
            "font_family": self.title_font_family.currentText().strip() or "Arial",
            "title_font": self.title_font_family.currentText().strip() or "Arial",
            "body_font": self.body_font_family.currentText().strip() or "Arial",
            "title_color": self.title_color_btn.text(),
            "title_bold": self.title_bold.isChecked(),
            "body_bold": self.body_bold.isChecked(),
            "body_color": self.body_color_btn.text(),
            "outline_color": self.outline_color_btn.text(),
            "outline_width": self.outline_width.value(),
            "highlight_color": self.highlight_color_btn.text(),
            "background_color": self.background_color_btn.text(),
            "background_enabled": self.background_enabled.isChecked(),
            "effect": effect,
            "shadow": self.shadow.value(),
            "letter_spacing": self.letter_spacing.value(),
            "line_spacing": self.line_spacing.value(),
            "position": self.position.currentText(),
            "margin_v": self.margin_v.value(),
            "title_align": self.title_align.currentText(),
            "title_x_pct": self.title_x_pct.value(),
            "title_width_pct": self.title_width_pct.value(),
            "title_y_pct": self._title_y_pct,
            "body_align": self.body_align.currentText(),
            "body_x_pct": self.body_x_pct.value(),
            "body_width_pct": self.body_width_pct.value(),
            "body_y_pct": self._body_y_pct,
            "body_flow": [dict(item) for item in self._body_flow],
            "mask_color": self.mask_color_btn.text(),
            "mask_opacity": self.mask_opacity.value(),
            "mask_x": self.mask_x.value(),
            "mask_y": self.mask_y.value(),
            "mask_w": self.mask_w.value(),
            "mask_h": self.mask_h.value(),
            "mask_enabled": self.mask_enabled.isChecked(),
            "writing_language": writing_language_from_ui(self.writing_language.currentText()),
            "bgm_enabled": self.bgm_enabled.isChecked(),
            "bgm_selection_mode": mode,
            "bgm_path": self.bgm_path.text().strip(),
            "bgm_dir": self.bgm_dir.text().strip(),
            "bgm_volume": self.bgm_volume.value(),
            "keep_original_audio": self.keep_original.isChecked(),
            "original_volume": 100,
            "tts_service": self.tts_service.currentText(),
            "tts_voice": self.tts_voice.text().strip(),
            "tts_enabled": self.tts_enabled.isChecked(),
            "output_dir": self.output_dir.text().strip(),
            "title_text": self.title_edit.text(),
            "body_text": self.body_edit.toPlainText(),
            "script_rows": self._table_script_rows(),
        }

    def apply_settings(self, data: dict):
        if not data:
            return
        self.preset_name.setText(str(data.get("name") or "默认视频预设"))
        self.title_size.setValue(max(20, int(data.get("title_font_size") or 90)))
        self.body_size.setValue(max(20, int(data.get("body_font_size") or 45)))
        auto = bool(data.get("body_auto_size", True))
        self.body_auto.setChecked(auto)
        self.body_size.setEnabled(not auto)
        fallback_font = str(data.get("font_family") or "Roboto")
        for combo, key in (
            (self.title_font_family, "title_font"),
            (self.body_font_family, "body_font"),
        ):
            font = str(data.get(key) or fallback_font)
            idx = combo.findText(font)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(font)
        self._set_color_btn(self.title_color_btn, data.get("title_color") or "#820000")
        self.title_bold.setChecked(bool(data.get("title_bold", True)))
        self.body_bold.setChecked(bool(data.get("body_bold", False)))
        self._set_color_btn(self.body_color_btn, data.get("body_color") or "#520000")
        self._set_color_btn(self.outline_color_btn, data.get("outline_color") or "#FFFFFF")
        self.outline_width.setValue(int(data.get("outline_width", 0)))
        self._set_color_btn(self.highlight_color_btn, data.get("highlight_color") or "#111111")
        self._set_color_btn(self.background_color_btn, data.get("background_color") or "#000000")
        self.background_enabled.setChecked(bool(data.get("background_enabled", False)))
        effect = str(data.get("effect") or "outline")
        for i in range(self.effect.count()):
            if self.effect.itemData(i) == effect:
                self.effect.setCurrentIndex(i)
                break
        self.shadow.setValue(int(data.get("shadow", 0)))
        self.letter_spacing.setValue(int(data.get("letter_spacing", 0)))
        self.line_spacing.setValue(int(data.get("line_spacing", 110)))
        pos = str(data.get("position") or "底部")
        pi = self.position.findText(pos)
        if pi >= 0:
            self.position.setCurrentIndex(pi)
        self.margin_v.setValue(int(data.get("margin_v", 380)))
        self._sync_preview_margin_from_spin(self.margin_v.value())
        self.title_align.setCurrentText(str(data.get("title_align") or "居中"))
        self.title_x_pct.setValue(int(data.get("title_x_pct", 50)))
        self.title_width_pct.setValue(int(data.get("title_width_pct", 86)))
        title_y = data.get("title_y_pct")
        self._title_y_pct = (
            max(0.0, min(100.0, float(title_y))) if title_y is not None else None
        )
        self.body_align.setCurrentText(str(data.get("body_align") or "居中"))
        self.body_x_pct.setValue(int(data.get("body_x_pct", 50)))
        self.body_width_pct.setValue(int(data.get("body_width_pct", 86)))
        body_y = data.get("body_y_pct")
        self._body_y_pct = (
            max(0.0, min(100.0, float(body_y))) if body_y is not None else None
        )
        flow = data.get("body_flow")
        self._body_flow = [dict(item) for item in flow if isinstance(item, dict)] \
            if isinstance(flow, list) else []
        self._set_color_btn(self.mask_color_btn, data.get("mask_color") or "#ffffff")
        self.mask_opacity.setValue(int(data.get("mask_opacity", 70)))
        self.mask_x.setValue(float(data.get("mask_x", 5)))
        self.mask_y.setValue(float(data.get("mask_y", 55)))
        self.mask_w.setValue(float(data.get("mask_w", 90)))
        self.mask_h.setValue(float(data.get("mask_h", 30)))
        self.mask_enabled.setChecked(bool(data.get("mask_enabled", True)))
        lang = str(data.get("writing_language") or "")
        for i in range(self.writing_language.count()):
            if self.writing_language.itemData(i) == lang or (not lang and i == 0):
                self.writing_language.setCurrentIndex(i)
                break
        self.bgm_enabled.setChecked(bool(data.get("bgm_enabled")))
        mode = str(data.get("bgm_selection_mode") or "fixed")
        self.bgm_mode.setCurrentIndex(1 if mode == "random_folder" else 0)
        self.bgm_path.setText(str(data.get("bgm_path") or ""))
        self.bgm_dir.setText(str(data.get("bgm_dir") or ""))
        self.bgm_volume.setValue(int(data.get("bgm_volume", 25)))
        self.keep_original.setChecked(bool(data.get("keep_original_audio", True)))
        svc = str(data.get("tts_service") or "微软文字转语音")
        si = self.tts_service.findText(svc)
        if si >= 0:
            self.tts_service.setCurrentIndex(si)
        self.tts_voice.setText(str(data.get("tts_voice") or ""))
        self.tts_enabled.setChecked(bool(data.get("tts_enabled", False)))
        if data.get("output_dir"):
            self.output_dir.setText(str(data["output_dir"]))
        if "title_text" in data:
            self.title_edit.setText(str(data.get("title_text") or ""))
        if "body_text" in data:
            self.body_edit.setPlainText(str(data.get("body_text") or ""))
        rows = data.get("script_rows")
        if isinstance(rows, list):
            self._pending_script_rows = [dict(row) for row in rows if isinstance(row, dict)]
        elif "batch_script_text" in data:
            self._pending_script_rows = self._legacy_batch_text_entries(data.get("batch_script_text"))
        self._sync_script_table()
        self._refresh_auto_body_size_label()
        self._schedule_live_refresh()

    def _presets_dir(self) -> Path:
        base = Path(os.environ.get("APPDATA") or Path.home()) / "VideoToolkit" / "video_presets"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _save_preset_local(self):
        data = self.current_settings()
        name = re.sub(r'[<>:"/\\|?*]', "_", data["name"]) or "preset"
        path = self._presets_dir() / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._settings_ini.setValue("last_preset", str(path))
        self._append_log(f"已保存预设：{path}")
        QMessageBox.information(self, "已保存", f"预设已保存到：\n{path}")

    def _load_preset_local(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载本机预设", str(self._presets_dir()), "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.apply_settings(data)
            self._append_log(f"已加载：{path}")
        except Exception as exc:
            QMessageBox.warning(self, "加载失败", str(exc))

    def _export_preset(self):
        data = self.current_settings()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出预设", f"{data['name']}.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._append_log(f"已导出：{path}")

    def _import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入预设", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.apply_settings(data)
            self._append_log(f"已导入：{path}")
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def _load_memory(self):
        last = self._settings_ini.value("last_preset", "")
        if last and Path(str(last)).is_file():
            try:
                data = json.loads(Path(str(last)).read_text(encoding="utf-8"))
                self.apply_settings(data)
            except Exception:
                pass

    # ================================================================== preview
    def _on_media_selected(self, text: str):
        row = self.media_list.currentRow()
        if hasattr(self, "script_table") and 0 <= row < self.script_table.rowCount():
            self._load_table_row_into_current(row)
        if text and Path(text).is_file():
            self._load_media_path(text)

    def _load_current_media(self):
        media = self._current_media()
        if media:
            self._load_media_path(str(media))
        else:
            self._append_log("请先添加并选择素材。")

    def _current_media(self) -> Path | None:
        item = self.media_list.currentItem()
        if item:
            p = Path(item.text())
            if p.is_file():
                return p
        if self.media_list.count():
            p = Path(self.media_list.item(0).text())
            if p.is_file():
                return p
        return None

    def _load_media_path(self, path: str):
        media = Path(path)
        if not media.is_file():
            return
        self._current_media_path = str(media.resolve())
        self.player.stop()
        self.bgm_player.stop()
        self._is_image_preview = media.suffix.lower() in IMAGE_EXTENSIONS
        self._preview_base = QImage()
        self._image_source = QImage()

        if self._is_image_preview:
            img = QImage(str(media))
            if img.isNull():
                self.video_widget.setText("无法加载图片")
                return
            self._image_source = img
            self.player.setSource(QUrl())
            self.seek.setRange(0, 8000)
            self.seek.setValue(0)
            self.time_label.setText("00:00 / 00:08")
            self.play_btn.setText("播放")
            self._letterbox_image(img)
            self._paint_preview()
        else:
            self.player.setSource(QUrl.fromLocalFile(str(media.resolve())))
            self.player.pause()
            self.play_btn.setText("播放")

        self._load_bgm_for_preview(media)
        self._refresh_timeline_for(media)
        self._update_preview_audio_levels()
        self._append_log(f"预览已加载：{media.name}")

    def _load_bgm_for_preview(self, media: Path):
        settings = self.current_settings()
        bgm = ""
        if settings.get("bgm_enabled"):
            if settings.get("bgm_selection_mode") == "random_folder":
                f = find_bgm_file(settings.get("bgm_dir"), 0, media, True)
                bgm = str(f) if f else ""
            else:
                bgm = settings.get("bgm_path") or ""
                if not Path(bgm).is_file() and settings.get("bgm_dir"):
                    f = find_bgm_file(settings.get("bgm_dir"), 0, media, False)
                    bgm = str(f) if f else ""
        if bgm and Path(bgm).is_file():
            self.bgm_player.setSource(QUrl.fromLocalFile(str(Path(bgm).resolve())))
        else:
            self.bgm_player.setSource(QUrl())

    def _letterbox_image(self, src: QImage):
        """等比完整放入预览控件（letterbox）。"""
        w = max(1, self.video_widget.width())
        h = max(1, self.video_widget.height())
        if src.isNull() or w < 4 or h < 4:
            return
        canvas = QImage(w, h, QImage.Format.Format_RGB32)
        canvas.fill(QColor("#02050b"))
        scaled = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        x = (w - scaled.width()) // 2
        y = (h - scaled.height()) // 2
        painter = QPainter(canvas)
        try:
            painter.drawImage(x, y, scaled)
        finally:
            painter.end()
        self._preview_base = canvas
        self._preview_content_rect = (x, y, scaled.width(), scaled.height())

    def _video_frame_changed(self, frame):
        if not frame.isValid():
            return
        img = frame.toImage()
        if img.isNull():
            return
        self._letterbox_image(img)
        self._paint_preview()

    def _schedule_live_refresh(self):
        self._live_refresh.start()

    def _paint_preview(self):
        if self._preview_base.isNull():
            if self._is_image_preview and not self._image_source.isNull():
                self._letterbox_image(self._image_source)
            else:
                return
        if self._preview_base.isNull():
            return
        out = QImage(self._preview_base)
        if self.live_preview.isChecked():
            self._draw_overlay(out)
        self.video_widget.setPixmap(QPixmap.fromImage(out))

    def _draw_overlay(self, canvas: QImage):
        """在 letterbox 内容区上按 1080×1920 比例叠蒙版与标题/正文。"""
        if canvas.isNull():
            return
        cx, cy, cw, ch = getattr(self, "_preview_content_rect", (0, 0, canvas.width(), canvas.height()))
        if cw < 8 or ch < 8:
            return
        settings = self.current_settings()
        painter = QPainter(canvas)
        try:
            self._draw_overlay_with_painter(painter, canvas, cx, cy, cw, ch, settings)
        finally:
            painter.end()

    def _draw_overlay_with_painter(self, painter, canvas, cx, cy, cw, ch, settings):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        sx = cw / CANVAS_W
        sy = ch / CANVAS_H

        if settings.get("mask_enabled", True):
            mx = cx + CANVAS_W * float(settings.get("mask_x", 5)) / 100 * sx
            my = cy + CANVAS_H * float(settings.get("mask_y", 55)) / 100 * sy
            mw = max(4.0, CANVAS_W * float(settings.get("mask_w", 90)) / 100 * sx)
            mh = max(4.0, CANVAS_H * float(settings.get("mask_h", 30)) / 100 * sy)
            opacity = max(0, min(100, int(settings.get("mask_opacity", 70))))
            color = QColor(settings.get("mask_color") or "#ffffff")
            color.setAlpha(int(255 * opacity / 100))
            painter.fillRect(int(mx), int(my), int(mw), int(mh), color)

        fallback_font = settings.get("font_family") or "Arial"
        title_font_name = settings.get("title_font") or fallback_font
        body_font_name = settings.get("body_font") or fallback_font
        title = (settings.get("title_text") or "").strip()
        body = (settings.get("body_text") or "").strip()
        lang = settings.get("writing_language") or ""
        try:
            title_font_name = suggest_font_for_text(title_font_name, title, lang) or title_font_name
            body_font_name = suggest_font_for_text(body_font_name, body, lang) or body_font_name
        except Exception:
            pass
        effect = str(settings.get("effect") or "outline")
        outline_w = max(0, int(settings.get("outline_width") or 0))
        shadow = max(0, int(settings.get("shadow") or 0))
        layout = resolve_caption_layout(settings, title, body)
        align_names = {4: "左对齐", 5: "居中", 6: "右对齐"}

        def draw_styled_text(
            text: str, x: float, y: float, size: int, fill_hex: str,
            bold: bool, font_name: str, text_align: str,
        ):
            font = QFont(font_name)
            font.setPixelSize(max(8, int(size * sy)))
            font.setBold(bool(bold))
            letter = int(settings.get("letter_spacing") or 0)
            if letter:
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter * sy)
            fm = QFontMetrics(font)
            path = QPainterPath()
            path.addText(0, 0, font, text)
            bounds = path.boundingRect()
            pen_w = max(1.0, outline_w * sy)
            outline = QColor(settings.get("outline_color") or "#FFFFFF")
            fill = QColor(fill_hex)
            highlight = QColor(settings.get("highlight_color") or "#111111")
            painter.save()
            if text_align == "左对齐":
                anchor_x = bounds.left()
            elif text_align == "右对齐":
                anchor_x = bounds.right()
            else:
                anchor_x = bounds.center().x()
            painter.translate(x - anchor_x, y)
            if effect == "double_outline":
                painter.setPen(QPen(highlight, (pen_w + 3 * sy) * 2,
                                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                painter.setPen(QPen(outline, pen_w * 2,
                                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPath(path)
            elif effect == "glow":
                glow = QColor(outline)
                for blur in (6, 4, 2):
                    glow.setAlpha(60)
                    painter.setPen(QPen(glow, pen_w + blur,
                                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPath(path)
            elif effect == "shadow":
                sh = max(2.0, (shadow or 3) * sy)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 140))
                painter.save()
                painter.translate(sh, sh)
                painter.drawPath(path)
                painter.restore()
                if outline_w > 0:
                    painter.setPen(QPen(outline, pen_w * 2,
                                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPath(path)
            elif effect == "none":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPath(path)
            else:
                if outline_w > 0:
                    painter.setPen(QPen(outline, pen_w * 2,
                                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawPath(path)
            painter.restore()
            return fm

        for item in layout["lines"]:
            is_title = item["kind"] == "title"
            px = cx + float(item["x"]) * sx
            py = cy + float(item["y"]) * sy
            align_name = align_names.get(int(item["align"]), "居中")
            draw_styled_text(
                str(item["text"]), px, py, int(item["size"]),
                (settings.get("title_color") if is_title else settings.get("body_color"))
                or ("#820000" if is_title else "#520000"),
                bool(settings.get("title_bold", True) if is_title else settings.get("body_bold", False)),
                title_font_name if is_title else body_font_name,
                align_name,
            )
        painter.end()
        painter.end()

    def toggle_preview(self):
        if self._is_image_preview:
            # 图片无时钟；点播放仅刷新叠加层
            self._paint_preview()
            return
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.bgm_player.pause()
            self.play_btn.setText("播放")
        else:
            if not self._preview_sound_on:
                self.sound_btn.setChecked(False)  # 开声
            self.player.play()
            if self.bgm_enabled.isChecked() and self.bgm_player.source().isValid():
                self.bgm_player.setPosition(self.player.position())
                self.bgm_player.play()
            self.play_btn.setText("暂停")

    def _on_playback_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("暂停")
        else:
            self.play_btn.setText("播放")
            if state != QMediaPlayer.PlaybackState.PlayingState:
                self.bgm_player.pause()

    def _on_sound_toggled(self, muted: bool):
        self._preview_sound_on = not muted
        self.sound_btn.setText("🔇 静音" if muted else "🔊 有声")
        self._update_preview_audio_levels()

    def _update_preview_audio_levels(self):
        if self._preview_sound_on:
            vol = self._preview_video_volume if self.keep_original.isChecked() else 0.0
            self.audio_output.setVolume(vol)
            bvol = max(0, min(200, self.bgm_volume.value())) / 100 * 0.5
            self.bgm_audio.setVolume(bvol if self.bgm_enabled.isChecked() else 0.0)
        else:
            self.audio_output.setVolume(0.0)
            self.bgm_audio.setVolume(0.0)

    def _seek_preview(self, ms: int):
        ms = max(0, int(ms))
        if not self._is_image_preview:
            self.player.setPosition(ms)
            if self.bgm_player.source().isValid():
                self.bgm_player.setPosition(ms)
        self.seek.blockSignals(True)
        self.seek.setValue(ms)
        self.seek.blockSignals(False)
        if self._is_image_preview:
            self._paint_preview()

    def _preview_position_changed(self, value: int):
        if self.seek.isSliderDown():
            return
        self.seek.blockSignals(True)
        self.seek.setValue(value)
        self.seek.blockSignals(False)
        dur = max(0, self.player.duration())
        self.time_label.setText(f"{self._fmt_ms(value)} / {self._fmt_ms(dur)}")
        try:
            if hasattr(self.timeline, "canvas"):
                self.timeline.canvas.position_ms = int(value)
                self.timeline.canvas.update()
        except Exception:
            pass

    def _preview_duration_changed(self, value: int):
        self.seek.setRange(0, max(0, int(value)))
        self.time_label.setText(f"00:00 / {self._fmt_ms(value)}")

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        ms = max(0, int(ms))
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"

    def _rebalance_layout(self):
        """按窗口宽高分配左栏 / 预览 / 设置 / 时间轴（对齐 Reels）。"""
        width = max(1, self.width())
        height = max(1, self.height())
        bucket = "compact" if width < 1250 else ("medium" if width < 1650 else "wide")
        if hasattr(self, "workspace_splitter"):
            if bucket == "compact":
                left_width = 270
            elif bucket == "medium":
                left_width = max(300, int(width * 0.27))
            else:
                left_width = max(360, int(width * 0.24))
            self.workspace_splitter.setSizes([left_width, max(520, width - left_width)])
        if hasattr(self, "work_splitter"):
            available = max(520, width - (270 if bucket == "compact" else int(width * 0.27)))
            preview_ratio = 0.46 if bucket == "compact" else (0.52 if bucket == "medium" else 0.56)
            preview_width = max(240, int(available * preview_ratio))
            self.work_splitter.setSizes([preview_width, max(280, available - preview_width)])
        if hasattr(self, "timeline_splitter"):
            timeline_height = 310 if height < 800 else (340 if height < 1000 else 380)
            self.timeline_splitter.setSizes([max(300, height - timeline_height), timeline_height])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(1, event.size().width())
        bucket = "compact" if width < 1250 else ("medium" if width < 1650 else "wide")
        if getattr(self, "_responsive_layout_bucket", None) != bucket:
            self._responsive_layout_bucket = bucket
            self._rebalance_layout()
        if self._is_image_preview and not self._image_source.isNull():
            self._letterbox_image(self._image_source)
            self._paint_preview()
        elif not self._preview_base.isNull():
            self._schedule_live_refresh()

    # ================================================================== timeline / TTS / render
    def _refresh_timeline_for(self, media: Path):
        try:
            ffmpeg = self._find_ffmpeg()
        except Exception:
            ffmpeg = "ffmpeg"
        if self._is_image_preview:
            dur_ms = 8000
        else:
            dur_ms = int(media_duration(ffmpeg, media, 8.0) * 1000)
        settings = self.current_settings()
        title = self.title_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        lines = [x for x in (title, body) if x]
        text = "\n".join(lines) or "（无文案）"
        end = self._ms_to_srt(dur_ms)
        srt = f"1\n00:00:00,000 --> {end}\n{text}\n"
        key = str(media.resolve())
        tts = ""
        if self._current_script_tts_enabled():
            tts = self._tts_cache.get(key) or self._tts_cache.get("__global__") or ""
        bgm = ""
        if settings.get("bgm_enabled"):
            if settings.get("bgm_selection_mode") == "random_folder":
                f = find_bgm_file(settings.get("bgm_dir"), 0, media, True)
                bgm = str(f) if f else ""
            else:
                bgm = settings.get("bgm_path") or ""
                if not Path(bgm).is_file() and settings.get("bgm_dir"):
                    f = find_bgm_file(settings.get("bgm_dir"), 0, media, False)
                    bgm = str(f) if f else ""
        try:
            self.timeline.set_project(
                video_path=str(media),
                duration_ms=dur_ms,
                srt=srt,
                bgm_path=bgm if bgm and Path(bgm).is_file() else "",
                tts_path=tts if tts and Path(tts).is_file() else "",
                original_audio_enabled=bool(settings.get("keep_original_audio", True)),
            )
        except Exception as exc:
            self._append_log(f"时间轴刷新失败：{exc}")

    @staticmethod
    def _ms_to_srt(ms: int) -> str:
        ms = max(0, int(ms))
        h, rem = divmod(ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, milli = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    def _generate_tts(self):
        if not callable(self._text_to_speech):
            QMessageBox.warning(self, "不可用", "未接入文案转语音服务。")
            return
        text = (self.title_edit.text().strip() + "。\n" + self.body_edit.toPlainText().strip()).strip("。\n ")
        if not text:
            QMessageBox.information(self, "文案为空", "请先填写标题或正文。")
            return
        row = self.media_list.currentRow()
        if 0 <= row < self.script_table.rowCount():
            item = self._script_item(row, 4)
            item.setCheckState(Qt.CheckState.Checked)
            self._sync_tts_controls(True)
        service = self.tts_service.currentText()
        voice = self.tts_voice.text().strip()
        out = Path(tempfile.gettempdir()) / f"vpreset_tts_{int(time.time() * 1000)}.mp3"
        try:
            self._append_log(f"TTS 生成中（{service}）…")
            result = self._text_to_speech(text, service, voice, str(out))
            path = Path(result) if result else out
            if not path.is_file() or path.stat().st_size < 128:
                raise RuntimeError("未生成有效音频文件")
            item = self.media_list.currentItem()
            key = str(Path(item.text()).resolve()) if item else "__global__"
            self._tts_cache[key] = str(path.resolve())
            self._tts_cache["__global__"] = str(path.resolve())
            self.tts_status.setText(f"已生成：{path.name}")
            self._append_log(f"TTS 完成：{path}")
            media = self._current_media()
            if media:
                self._refresh_timeline_for(media)
        except Exception as exc:
            self.tts_status.setText("生成失败")
            QMessageBox.warning(self, "TTS 失败", str(exc))
            self._append_log(f"TTS 失败：{exc}")

    def _start_render(self, all_items: bool = True):
        if self._thread is not None:
            QMessageBox.information(self, "进行中", "已有渲染任务，请先停止或等待完成。")
            return
        try:
            ffmpeg = self._find_ffmpeg()
            if not ffmpeg:
                raise RuntimeError("未找到 FFmpeg")
        except Exception as exc:
            QMessageBox.warning(self, "FFmpeg", f"未找到 FFmpeg：{exc}\n请到「设置与组件」安装。")
            return

        if all_items:
            items = [self.media_list.item(i).text() for i in range(self.media_list.count())]
        else:
            media = self._current_media()
            items = [str(media)] if media else []
        if not items:
            QMessageBox.information(self, "无素材", "请先添加视频或图片素材。")
            return

        settings = self.current_settings()
        batch_scripts = self._parse_batch_scripts()
        script_by_media = {
            str(Path(row.get("media", "")).resolve()): row
            for row in batch_scripts if row.get("media")
        }
        jobs = []
        for index, p in enumerate(items):
            key = str(Path(p).resolve()) if Path(p).is_file() else p
            script = script_by_media.get(key) or {
                "title": self.title_edit.text(), "body": self.body_edit.toPlainText(),
            }
            generate_tts = bool(script.get("generate_tts", False))
            if generate_tts:
                tts = self._tts_cache.get(key) or ""
            else:
                tts = ""
            jobs.append({
                "media": p,
                "title": script.get("title", ""),
                "body": script.get("body", ""),
                "tts": tts,
                "generate_tts": generate_tts,
                "tts_service": self.tts_service.currentText(),
                "tts_voice": self.tts_voice.text().strip(),
            })

        self.progress.setValue(0)
        self.render_one_btn.setEnabled(False)
        self.render_all_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker = VideoPresetRenderWorker(
            jobs, settings, str(ffmpeg), text_to_speech_fn=self._text_to_speech)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.finished.connect(self._render_finished)
        self._thread.start()
        self._append_log(f"开始渲染 {len(jobs)} 个任务…")

    def _stop_render(self):
        if self._worker:
            self._worker.cancel()
            self._append_log("正在停止…")

    def _render_finished(self, ok: bool, message: str):
        self.render_one_btn.setEnabled(True)
        self.render_all_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = None
        self._worker = None
        self._append_log(message)
        if ok:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.warning(self, "失败", message)
