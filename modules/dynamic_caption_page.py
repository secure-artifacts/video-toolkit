from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import cv2

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QVBoxLayout, QWidget,
)

from .path_picker import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, DropListWidget, collect_files, natural_key
from .settings_page import hidden_kwargs
from .text_rules import normalize_required_capitalization


PRESETS = {
    "Descript 经典黄": {"text": "#F8FAFC", "outline": "#111111", "highlight": "#FACC15", "outline_width": 5,
                         "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                         "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
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


def group_word_srt(srt, max_chars=36, max_duration=4.6, max_words=8):
    """把词级时间轴合并成便于阅读/编辑的逐句 SRT，保留首尾真实时间。"""
    words = parse_srt(srt)
    if not words: return srt
    # 已经是正常句级字幕时不重复合并。
    if len(words) <= 2 or sum(len(tokens_for(text)) for _,_,text in words) > len(words) * 2:
        return srt
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
    return "\n\n".join(blocks)+"\n"


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


def write_ass(path, srt, settings, word_srt=""):
    preset = PRESETS[settings["preset"]]
    text_color = ass_color(settings["text_color"])
    outline_color = ass_color(settings["outline_color"])
    highlight = ass_color(settings["highlight_color"])
    font = settings["font"].replace(",", "")
    alignment = {"底部": 2, "画面中间": 5, "顶部": 8}.get(settings.get("position", "底部"), 2)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{font},{settings['font_size']},{text_color},{text_color},{outline_color},&H90000000,-1,0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,{settings['outline_width']},2,{alignment},40,40,{settings['margin_v']},1
Style: Active,{font},{settings['font_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,0,0,{alignment},40,40,{settings['margin_v']},1
Style: ActiveColor,{font},{settings['font_size']},{highlight},{highlight},{outline_color},&H90000000,-1,0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,{settings['outline_width']},2,{alignment},40,40,{settings['margin_v']},1
Style: HighlightBox,{font},{settings['font_size']},{highlight},{highlight},{highlight},{highlight},-1,0,0,0,100,100,{settings.get('letter_spacing',0)},0,1,0,0,7,0,0,0,1

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
        if layer.get("type") != "mask" or not layer.get("enabled", True):
            continue
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
    precise_words = parse_srt(word_srt)
    font_size = settings["font_size"]
    metric_font = QFont(font)
    metric_font.setPixelSize(font_size)
    metric_font.setBold(True)
    letter_spacing = float(settings.get("letter_spacing", 0))
    metric_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    metrics = QFontMetricsF(metric_font)
    line_gap = max(font_size, metrics.height()) * max(70, min(180, int(settings.get("line_spacing", 116)))) / 100
    word_gap = max(font_size * .16, metrics.horizontalAdvance(" "))
    max_line_width = 1080 * max(40, min(96, int(settings.get("line_width", 86)))) / 100
    padding_x = int(settings.get("highlight_padding", max(12, font_size * .2)))
    padding_y = max(7, int(font_size * .11))
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
        if fixed_all and "\n" in safe:
            lines = [tokens_for(line) for line in safe.splitlines() if tokens_for(line)]
        else:
            lines=[]; current=[]
            for token in tokens:
                candidate=" ".join(current+[token])
                candidate_width = sum(metrics.horizontalAdvance(value) for value in current + [token])
                candidate_width += word_gap * len(current)
                if current and (len(candidate)>settings["line_length"] or candidate_width>max_line_width):
                    lines.append(current); current=[token]
                else: current.append(token)
            if current: lines.append(current)

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
            if position == "顶部": center_y=settings["margin_v"]+line_gap*(len(page_lines)-1)/2
            elif position == "画面中间": center_y=960
            else: center_y=1920-settings["margin_v"]-line_gap*(len(page_lines)-1)/2
            for line_index,line_tokens in enumerate(page_lines):
                y=center_y+(line_index-(len(page_lines)-1)/2)*line_gap
                def estimated_width(value):
                    # 每个词独立占位；基础词和高亮词复用完全相同的坐标。
                    return max(font_size * .55, metrics.horizontalAdvance(value))
                widths=[estimated_width(token) for token in line_tokens]
                total=sum(widths)+word_gap*max(0,len(widths)-1); cursor=540-total/2
                for local_index,token in enumerate(line_tokens):
                    width=widths[local_index]; x=cursor+width/2; cursor+=width+word_gap
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
    log = Signal(str); progress = Signal(int); result = Signal(str, str)
    timeline_ready = Signal(str, str, str); finished = Signal(bool, str)

    def __init__(self, videos, audios, output, ffmpeg, transcribe, settings):
        super().__init__(); self.videos = [Path(p) for p in videos]; self.audios = [Path(p) for p in audios]
        self.output = Path(output); self.ffmpeg = ffmpeg; self.transcribe = transcribe; self.settings = settings; self.cancelled = False

    def cancel(self): self.cancelled = True

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
        if mode == "严格按队列一一对应":
            return self.audios[min(index, len(self.audios) - 1)], "队列顺序"
        video_key = self._match_stem(video)
        same = next((audio for audio in self.audios if self._match_stem(audio) == video_key), None)
        if same is not None:
            return same, "同名自动匹配"
        if len(self.audios) == 1:
            return self.audios[0], "唯一音频"
        return self.audios[min(index, len(self.audios) - 1)], "队列顺序"

    def _audio_for(self, video, index):
        return self._audio_selection(video, index)[0]

    def _clean_video(self, video):
        clean_dir = self.output / "00_无元数据素材"; clean_dir.mkdir(parents=True, exist_ok=True)
        destination = clean_dir / video.name
        if destination.exists() and destination.stat().st_size > 0:
            ffmpeg_path = Path(self.ffmpeg)
            ffprobe = ffmpeg_path.with_name("ffprobe" + ffmpeg_path.suffix)
            probe = subprocess.run(
                [str(ffprobe), "-v", "error", "-select_streams", "V:0",
                 "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1", str(destination)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", **hidden_kwargs(),
            ) if ffprobe.exists() else None
            if probe is None or (probe.returncode == 0 and "video" in probe.stdout):
                self.log.emit(f"续接：复用已清理素材 {destination.name}"); return destination
            self.log.emit(f"检测到上次遗留的无效文件，自动重新清理：{destination.name}")
            try:
                destination.unlink()
            except OSError as exc:
                raise RuntimeError(f"无法覆盖上次失败留下的文件：{destination}\n{exc}") from exc
        # Reels 输入只需要主画面和音轨。部分手机、剪辑软件或下载器会在 MP4
        # 中附带 timed metadata / data / attachment 流；使用 `-map 0` 会把这些
        # codec=none 的辅助流也复制进新 MP4，导致 muxer 无法写入文件头。
        # 大写 V 排除 attached_pic，全部音轨仍按码流原样复制，不改变声道数、
        # 采样率或音频编码。
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                   "-map", "0:V:0", "-map", "0:a?",
                   "-map_metadata", "-1", "-map_metadata:s", "-1",
                   "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                   "-map_chapters", "-1", "-sn", "-dn", "-c:v", "copy", "-c:a", "copy",
                   str(destination)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            # FFmpeg 可能已留下一个不完整文件；删除它，避免断点续接误判为成功。
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(f"Reels 素材元数据清理失败：{video.name}\n{result.stderr[-500:]}")
        self.log.emit(f"已清理素材元数据：{destination.name}"); return destination

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            for index, video in enumerate(self.videos):
                if self.cancelled: raise RuntimeError("任务已停止；已完成的动态文案视频仍保留。")
                render_video = self._clean_video(video) if self.settings["clean_metadata"] else video
                audio, match_reason = self._audio_selection(video, index)
                self.log.emit(
                    f"[{index + 1}/{len(self.videos)}] 素材匹配：{video.name}  ←  {audio.name}（{match_reason}）"
                )
                source_key = str(audio.resolve())
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
                    sidecar = audio.with_suffix(".srt")
                    if saved_word_srt:
                        srt = saved_word_srt
                        original = " ".join(text for _,_,text in parse_srt(srt)); chinese = ""
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 复用已提取的词级时间轴：{audio.name}")
                    elif sidecar.exists() and sidecar.stat().st_size:
                        srt = sidecar.read_text(encoding="utf-8-sig")
                        original = " ".join(text for _, _, text in parse_srt(srt)); chinese = ""
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 使用配音的真实词级时间轴：{sidecar.name}")
                    else:
                        self.log.emit(f"[{index + 1}/{len(self.videos)}] 从音频提取词级时间轴：{audio.name}")
                        original, chinese, srt = self.transcribe(str(audio))
                    if not srt.strip(): raise RuntimeError(f"未识别到有效字幕：{audio.name}")
                    word_srt = srt
                    phrase_srt = group_word_srt(word_srt, self.settings["line_length"] * 2,
                                                max_words=self.settings.get("max_words", 8))
                    override = str(self.settings.get("timeline_overrides", {}).get(str(audio.resolve()), "")).strip()
                    if override:
                        if "-->" in override:
                            phrase_srt = override
                            self.log.emit("已应用人工修订后的逐句 SRT，逐词时间轴继续驱动高亮。")
                        else:
                            phrase_srt = replace_srt_copy(phrase_srt, override)
                            self.log.emit("已应用人工修订文案，并保留词级时间轴。")
                self.timeline_ready.emit(source_key, word_srt, phrase_srt)
                ass = self.output / f".{video.stem}_dynamic.ass"
                write_ass(ass, phrase_srt, self.settings, word_srt)
                destination = self.output / f"{video.stem}_动态文案.mp4"
                ass_filter = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
                command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(render_video)]
                external = audio.resolve() != video.resolve()
                if external: command += ["-i", str(audio)]
                command += ["-vf", f"ass='{ass_filter}'", "-map", "0:v:0"]
                if external and self.settings["audio_mode"] == "替换为添加的音频":
                    command += ["-map", "1:a:0", "-shortest"]
                else:
                    command += ["-map", "0:a?"]
                # 不指定 -ac，保留源音频声道；字幕烧录只重编码画面。
                command += ["-c:v", "libx264", "-preset", self.settings["encode_preset"], "-crf", "20",
                            "-c:a", "aac", "-b:a", "192k"]
                if external and self.settings["audio_mode"] == "替换为添加的音频": command += ["-ac", "2"]
                command += ["-movflags", "+faststart", str(destination)]
                process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
                try: ass.unlink()
                except OSError: pass
                if process.returncode: raise RuntimeError(process.stderr.strip() or "动态文案渲染失败")
                self.result.emit(str(destination), original)
                self.progress.emit(round((index + 1) / len(self.videos) * 100))
                self.log.emit(f"成品：{destination}")
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
        ass = self.destination.with_suffix(".ass")
        try:
            if self.settings.get("caption_mode") == "自由文案动画（不对口型）":
                sample = free_caption_srt(self.text, 8.0, self.settings)
            else:
                sample = self.text if "-->" in self.text else f"1\n00:00:00,000 --> 00:00:08,000\n{self.text}\n"
            write_ass(ass, sample, self.settings, self.settings.get("preview_word_srt", ""))
            ass_filter = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.source)]
            preview_audio = Path(str(self.settings.get("preview_audio", "")))
            external = preview_audio.is_file() and preview_audio.resolve() != self.source.resolve()
            if external:
                command += ["-i", str(preview_audio)]
            command += ["-t", "8", "-vf", f"ass='{ass_filter}'", "-map", "0:v:0"]
            command += ["-map", "1:a:0"] if external else ["-map", "0:a?"]
            command += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-c:a", "aac",
                        "-b:a", "160k"]
            if external:
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
    finished = Signal(bool, str)

    def __init__(self, callback, path):
        super().__init__(); self.callback = callback; self.path = path

    def run(self):
        try:
            _original, _chinese, srt = self.callback(self.path)
            self.finished.emit(True, srt)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class BatchTimelineWorker(QObject):
    item_done = Signal(str, str, int, int)
    finished = Signal(bool, str)

    def __init__(self, callback, paths):
        super().__init__(); self.callback = callback; self.paths = list(paths)

    def run(self):
        try:
            total = len(self.paths)
            for index, path in enumerate(self.paths, 1):
                sidecar = Path(path).with_suffix(".srt")
                if sidecar.exists() and sidecar.stat().st_size:
                    srt = sidecar.read_text(encoding="utf-8-sig")
                else:
                    _original, _chinese, srt = self.callback(path)
                if not srt.strip():
                    raise RuntimeError(f"没有识别到字幕：{Path(path).name}")
                self.item_done.emit(str(path), srt, index, total)
            self.finished.emit(True, f"已按队列完成 {total} 个素材的时间轴提取。")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class DynamicCaptionPage(QWidget):
    def __init__(self, transcribe_callable, tts_callable, find_ffmpeg, providers, default_provider):
        super().__init__(); self.transcribe_callable = transcribe_callable; self.find_ffmpeg = find_ffmpeg
        self.tts_callable = tts_callable; self.providers = providers; self.thread = None; self.worker = None
        self.tts_thread = None; self.tts_worker = None; self.timeline_overrides = {}; self.timeline_words = {}; self._loading_timeline = False
        self.free_texts = {}
        self._active_timeline_source = ""; self._syncing_media_selection = False; self._timeline_pending_source = ""
        # 图层列表按“上层在前”保存；渲染时反向绘制，便于用户理解上移/下移。
        self.layers = [{"type": "caption", "name": "字幕层"}]
        self._mask_counter = 0
        self._build_ui(default_provider)

    def _build_ui(self, default_provider):
        root = QVBoxLayout(self); root.setContentsMargins(12, 8, 12, 10); root.setSpacing(6)
        header = QHBoxLayout(); heading = QLabel("动态 Reels 制作流水线"); heading.setObjectName("heading")
        header.addWidget(heading); header.addStretch(); header.addWidget(QLabel("清理素材 → 配音 → 字幕样式 → 视频预览 → 批量输出")); root.addLayout(header)

        workspace = QSplitter(Qt.Orientation.Horizontal); workspace.setChildrenCollapsible(False)

        # 左栏：素材、文案与运行输出集中在一个窄操作区。
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0,0,4,0); left_layout.setSpacing(6)
        left.setMinimumWidth(340); left.setMaximumWidth(430)
        source_group = QGroupBox("1. 素材与文案"); source_group_layout = QVBoxLayout(source_group); source_group_layout.setContentsMargins(8,10,8,8)
        source_group.setMinimumHeight(255); source_group.setMaximumHeight(360)
        source_tabs = QTabWidget()

        video_tab = QWidget(); vg = QVBoxLayout(video_tab); vg.setContentsMargins(4,4,4,4)
        self.videos = DropListWidget(); self.videos.setMinimumHeight(150)
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
        self.tts_text = QPlainTextEdit(); self.tts_text.setMinimumHeight(95); self.tts_text.setPlaceholderText(
            "粘贴一条或多条文案。批量时每段对应一个视频，段落之间用空行或单独一行 --- 分隔。")
        text_tab_layout.addWidget(self.tts_text,1)
        self.tts_service = QComboBox(); self.tts_service.addItems(
            ["Gemini 自然语音", "ElevenLabs API", "微软文字转语音"])
        self.tts_voice = QComboBox(); self.tts_voice.setEditable(True); self._load_gemini_voices()
        self.tts_service.currentTextChanged.connect(self.tts_service_changed)
        self.tts_generate = QPushButton("批量生成并加入音频队列"); self.tts_generate.clicked.connect(self.generate_tts)
        tts_line1 = QHBoxLayout(); tts_line1.addWidget(self.tts_service); tts_line1.addWidget(self.tts_voice,1)
        text_tab_layout.addLayout(tts_line1); text_tab_layout.addWidget(self.tts_generate)
        source_tabs.addTab(video_tab,"视频素材"); source_tabs.addTab(audio_tab,"音频素材"); source_tabs.addTab(text_tab,"文案配音")
        source_tabs.setStyleSheet("QTabBar::tab{background:#17243a;color:#cbd5e1;padding:6px 9px;min-width:72px;border:1px solid #334155;} QTabBar::tab:selected{background:#2563eb;color:white;font-weight:700;} QTabWidget::pane{border:1px solid #334155;}")
        self.audio_player=QMediaPlayer(self); self.audio_preview_output=QAudioOutput(self); self.audio_preview_output.setVolume(.8); self.audio_player.setAudioOutput(self.audio_preview_output)
        self._preview_external_audio = False
        self.audio_player.positionChanged.connect(self._audio_position_changed); self.audio_player.durationChanged.connect(self._audio_duration_changed)
        audio_controls=QHBoxLayout(); self.audio_play_btn=QPushButton("试听配音"); self.audio_play_btn.clicked.connect(self.toggle_audio_preview)
        self.audio_seek=QSlider(Qt.Orientation.Horizontal); self.audio_seek.setRange(0,0); self.audio_seek.sliderMoved.connect(self.audio_player.setPosition)
        self.audio_time=QLabel("00:00 / 00:00"); audio_controls.addWidget(self.audio_play_btn); audio_controls.addWidget(self.audio_seek,1); audio_controls.addWidget(self.audio_time); audio_tab_layout.addLayout(audio_controls)
        source_group_layout.addWidget(source_tabs); left_layout.addWidget(source_group,3)

        # 右侧工作区中的视频播放器、时间轴和快速效果预览。
        center = QWidget(); center_layout = QVBoxLayout(center); center_layout.setContentsMargins(4,0,4,0); center_layout.setSpacing(6)
        preview_group = QGroupBox("视频预览与定位"); preview_layout = QVBoxLayout(preview_group); preview_layout.setContentsMargins(9,10,9,8)
        # Windows 上 QVideoWidget 在部分显卡/解码器组合下只有声音没有画面。
        # 画面统一交给 OpenCV 解码并显示，QMediaPlayer 只负责音频和播放时钟。
        self.video_widget = QLabel("添加或选择视频后在这里预览")
        self.video_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_widget.setMinimumSize(330,390)
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
        self.live_refresh_timer = QTimer(self); self.live_refresh_timer.setSingleShot(True); self.live_refresh_timer.setInterval(70)
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
        render_row=QHBoxLayout(); render_row.addStretch(); render_row.addWidget(self.render_preview_btn)
        preview_layout.addLayout(render_row); center_layout.addWidget(preview_group,1)
        self.style_preview = QLabel(); self.style_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.style_preview.setMinimumHeight(76)
        self.style_preview.setVisible(False)

        # 右栏：设置独立滚动，任何窗口高度都不会把控件压扁。
        settings_scroll = QScrollArea(); settings_scroll.setWidgetResizable(True); settings_scroll.setMinimumWidth(430)
        settings_body = QWidget(); settings_layout = QVBoxLayout(settings_body); settings_layout.setContentsMargins(4,0,8,4); settings_layout.setSpacing(7)
        preset_group = QGroupBox("3. 字幕样式与动画"); pg = QVBoxLayout(preset_group); pg.setContentsMargins(10,12,10,10); pg.setSpacing(8)
        preset_grid = QGridLayout(); preset_grid.setSpacing(6); self.preset_buttons=[]
        for index,name in enumerate(PRESETS):
            button=QPushButton(name); button.setCheckable(True); button.setMinimumHeight(32); button.clicked.connect(lambda checked=False,n=name:self.apply_preset(n)); preset_grid.addWidget(button,index//3,index%3); self.preset_buttons.append(button)
        pg.addLayout(preset_grid)
        form = QFormLayout(); form.setVerticalSpacing(9); form.setHorizontalSpacing(8)
        self.provider=QComboBox(); self.provider.addItems(self.providers); self.provider.setCurrentText(default_provider)
        self.caption_mode=QComboBox(); self.caption_mode.addItems(["语音同步字幕", "自由文案动画（不对口型）"])
        self.caption_mode.setToolTip("语音同步会提取词级时间轴；自由文案按固定时长分页，不要求与人物口型一致。")
        self.caption_mode.currentTextChanged.connect(self._caption_mode_changed)
        self.free_animation=QComboBox(); self.free_animation.addItems(["逐字出现", "逐行出现", "由下向上", "淡入淡出", "整段固定"])
        self.free_animation.currentTextChanged.connect(self._free_animation_changed)
        self.free_page_seconds=QSpinBox(); self.free_page_seconds.setRange(1,20); self.free_page_seconds.setValue(3); self.free_page_seconds.setSuffix(" 秒/屏")
        free_line=QHBoxLayout(); free_line.addWidget(self.free_animation,1); free_line.addWidget(self.free_page_seconds)
        self.font=QComboBox(); self.font.addItems(QFontDatabase.families()); self.font.setCurrentText("Microsoft YaHei")
        self.font_size=QSpinBox(); self.font_size.setRange(20,160); self.font_size.setValue(58)
        font_line=QHBoxLayout(); font_line.addWidget(self.font,1); font_line.addWidget(QLabel("字号")); font_line.addWidget(self.font_size)
        self.line_length=QSpinBox(); self.line_length.setRange(6,60); self.line_length.setValue(18)
        self.line_width=QSpinBox(); self.line_width.setRange(40,96); self.line_width.setValue(86); self.line_width.setSuffix(" %")
        self.line_width.setToolTip("字幕一行最多占画面宽度的百分比；超过后自动换行")
        self.letter_spacing=QSpinBox(); self.letter_spacing.setRange(-5,30); self.letter_spacing.setValue(0); self.letter_spacing.setSuffix(" px")
        self.letter_spacing.setToolTip("调整同一个单词或文字内部的字与字间距")
        self.line_spacing=QSpinBox(); self.line_spacing.setRange(70,180); self.line_spacing.setValue(116); self.line_spacing.setSuffix(" %")
        self.line_spacing.setToolTip("调整两排字幕基线之间的距离，100% 约等于一行文字高度")
        self.max_words=QSpinBox(); self.max_words.setRange(3,12); self.max_words.setValue(7)
        self.highlight_padding=QSpinBox(); self.highlight_padding.setRange(6,36); self.highlight_padding.setValue(18)
        self.animation_speed=QSpinBox(); self.animation_speed.setRange(60,360); self.animation_speed.setValue(150); self.animation_speed.setSuffix(" ms")
        self.outline_width=QSpinBox(); self.outline_width.setRange(0,12); self.outline_width.setValue(3)
        self.position=QComboBox(); self.position.addItems(["底部","画面中间","顶部"])
        self.margin_v=QSpinBox(); self.margin_v.setRange(20,900); self.margin_v.setValue(250)
        self.margin_v.valueChanged.connect(self._sync_preview_margin)
        position_line=QHBoxLayout(); position_line.addWidget(self.position); position_line.addWidget(QLabel("边距")); position_line.addWidget(self.margin_v)
        self.audio_mode=QComboBox(); self.audio_mode.addItems(["替换为添加的音频","保留视频原音"])
        self.audio_mode.currentTextChanged.connect(self._rematch_current_video)
        self.audio_match_mode=QComboBox(); self.audio_match_mode.addItems([
            "自动匹配（同名优先，其次按队列）", "严格按队列一一对应", "每个视频使用自身音频",
        ])
        self.audio_match_mode.setToolTip("批处理时每个视频应使用哪一条音频和字幕时间轴")
        self.audio_match_mode.currentTextChanged.connect(self._rematch_current_video)
        self.audio_match_mode.currentTextChanged.connect(self._refresh_task_queue)
        self.clean_metadata=QCheckBox("输出前无损清除视频素材元数据"); self.clean_metadata.setChecked(True)
        self.encode_preset=QComboBox(); self.encode_preset.addItems(["veryfast","faster","fast","medium"])
        phrase_line=QHBoxLayout(); phrase_line.addWidget(QLabel("每句词数")); phrase_line.addWidget(self.max_words); phrase_line.addWidget(QLabel("每行字符")); phrase_line.addWidget(self.line_length)
        width_line=QHBoxLayout(); width_line.addWidget(QLabel("字幕行宽")); width_line.addWidget(self.line_width)
        spacing_line=QHBoxLayout(); spacing_line.addWidget(QLabel("字间距")); spacing_line.addWidget(self.letter_spacing); spacing_line.addWidget(QLabel("行距")); spacing_line.addWidget(self.line_spacing)
        effect_line=QHBoxLayout(); effect_line.addWidget(QLabel("色块留白")); effect_line.addWidget(self.highlight_padding); effect_line.addWidget(QLabel("动画")); effect_line.addWidget(self.animation_speed)
        form.addRow("字幕模式",self.caption_mode); form.addRow("自由动画",free_line)
        form.addRow("字体",font_line); form.addRow("自然分句",phrase_line); form.addRow("排版宽度",width_line); form.addRow("字幕间距",spacing_line)
        form.addRow("跟读效果",effect_line)
        form.addRow("字幕位置",position_line); form.addRow("描边宽度",self.outline_width); form.addRow("音频匹配",self.audio_match_mode); form.addRow("音频处理",self.audio_mode); form.addRow("渲染质量",self.encode_preset); form.addRow("素材清理",self.clean_metadata)
        pg.addLayout(form)
        batch_style_hint=QLabel("✓ 每个视频、匹配音频和文案组成独立任务；这里只批量套用字幕样式、蒙版和动画，最后统一批量导出。")
        batch_style_hint.setWordWrap(True); batch_style_hint.setStyleSheet("color:#67e8f9;background:#0b1830;padding:6px;border-radius:5px;")
        pg.addWidget(batch_style_hint)
        colors=QGridLayout(); self.text_color=QPushButton("文字 #FFFFFF"); self.outline_color=QPushButton("描边 #111827"); self.highlight_color=QPushButton("跟读背景 #8B5CF6")
        for index,button in enumerate((self.text_color,self.outline_color,self.highlight_color)):
            button.setMinimumHeight(32); button.clicked.connect(lambda checked=False,b=button:self.pick_color(b)); colors.addWidget(button,index//2,index%2)
        pg.addLayout(colors); settings_layout.addWidget(preset_group)

        layer_group = QGroupBox("4. 蒙版与图层顺序")
        layer_layout = QVBoxLayout(layer_group); layer_layout.setContentsMargins(9,11,9,8); layer_layout.setSpacing(6)
        layer_tip = QLabel("列表上方会覆盖下方；字幕层和蒙版可直接上移或下移。")
        layer_tip.setStyleSheet("color:#7dd3fc;"); layer_tip.setWordWrap(True); layer_layout.addWidget(layer_tip)
        self.layer_list = QListWidget(); self.layer_list.setMinimumHeight(92); self.layer_list.setMaximumHeight(130)
        self.layer_list.currentRowChanged.connect(self._layer_selected); layer_layout.addWidget(self.layer_list)
        layer_actions = QHBoxLayout()
        add_mask = QPushButton("＋ 添加蒙版"); add_mask.clicked.connect(self._add_mask_layer)
        delete_layer = QPushButton("删除"); delete_layer.clicked.connect(self._delete_layer)
        move_up = QPushButton("上移"); move_up.clicked.connect(lambda:self._move_layer(-1))
        move_down = QPushButton("下移"); move_down.clicked.connect(lambda:self._move_layer(1))
        for button in (add_mask, delete_layer, move_up, move_down): layer_actions.addWidget(button)
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
        layer_layout.addLayout(quick_positions); settings_layout.addWidget(layer_group)
        revise_group=QGroupBox("5. 字幕时间轴与文字调整"); revise_layout=QVBoxLayout(revise_group); revise_layout.setContentsMargins(9,11,9,8)
        provider_row=QHBoxLayout(); provider_row.addWidget(QLabel("字幕识别服务")); provider_row.addWidget(self.provider,1); revise_layout.addLayout(provider_row)
        self.combination_label=QLabel("当前任务组合：尚未选择视频")
        self.combination_label.setWordWrap(True); self.combination_label.setStyleSheet("color:#67e8f9;background:#0b1830;padding:5px 7px;border-radius:4px;")
        revise_layout.addWidget(self.combination_label)
        queue_title=QLabel("批处理对应队列（序号相同即为同一组任务）")
        queue_title.setStyleSheet("color:#cbd5e1;"); revise_layout.addWidget(queue_title)
        self.task_queue=QTableWidget(0,4)
        self.task_queue.setHorizontalHeaderLabels(["序号","视频","匹配音频","文案"])
        self.task_queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_queue.setAlternatingRowColors(True); self.task_queue.setMaximumHeight(142)
        self.task_queue.verticalHeader().setVisible(False)
        self.task_queue.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.task_queue.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.task_queue.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.task_queue.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.task_queue.cellClicked.connect(lambda row,_column:self.videos.setCurrentRow(row))
        revise_layout.addWidget(self.task_queue)
        self.timeline_source_label=QLabel("当前字幕：尚未选择视频")
        self.timeline_source_label.setStyleSheet("color:#facc15;background:#111827;padding:5px 7px;border-radius:4px;")
        self.timeline_source_label.setWordWrap(True); revise_layout.addWidget(self.timeline_source_label)
        timeline_actions=QHBoxLayout(); self.extract_timeline_btn=QPushButton("提取选中素材"); self.extract_timeline_btn.clicked.connect(self.extract_timeline)
        self.extract_all_btn=QPushButton("批量提取全部"); self.extract_all_btn.clicked.connect(self.extract_all_timelines)
        load_sidecar=QPushButton("载入 SRT…"); load_sidecar.clicked.connect(self.load_srt_file); timeline_actions.addWidget(self.extract_timeline_btn); timeline_actions.addWidget(self.extract_all_btn); timeline_actions.addWidget(load_sidecar)
        revise_layout.addLayout(timeline_actions)
        timeline_hint=QLabel("语音同步：按时间轴对齐朗读。自由动画：每个视频保存自己的文案；整段固定保留全部手动换行，不限制行数和每屏秒数。")
        timeline_hint.setWordWrap(True); timeline_hint.setStyleSheet("color:#7dd3fc;"); revise_layout.addWidget(timeline_hint)
        self.override_text=QPlainTextEdit(); self.override_text.setMinimumHeight(190); self.override_text.setPlaceholderText("1\n00:00:00,250 --> 00:00:00,780\nPrimeira\n\n2\n00:00:00,790 --> 00:00:01,240\npalavra")
        self.override_text.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;")
        self.override_text.textChanged.connect(self._timeline_text_changed)
        revise_layout.addWidget(self.override_text); settings_layout.addWidget(revise_group); settings_layout.addStretch(); settings_scroll.setWidget(settings_body)

        # 左下角的输出与日志保持窄而完整，不再横跨整个窗口挤压预览。
        output_group=QGroupBox("2. 输出与运行"); og=QVBoxLayout(output_group); og.setContentsMargins(8,10,8,8); og.setSpacing(6)
        outrow=QHBoxLayout(); self.output=QLineEdit(str(Path.cwd()/"dynamic_caption_outputs")); self.output.setToolTip(self.output.text()); outrow.addWidget(QLabel("输出")); outrow.addWidget(self.output,1)
        choose=QPushButton("选择…"); choose.clicked.connect(self.choose_output); outrow.addWidget(choose); og.addLayout(outrow)
        self.progress=QProgressBar(); self.progress.setMinimumHeight(20); og.addWidget(self.progress)
        status_row=QHBoxLayout()
        self.stop=QPushButton("停止"); self.stop.setEnabled(False); self.stop.clicked.connect(self.cancel)
        self.start=QPushButton("开始批量生成 Reels"); self.start.setObjectName("primary"); self.start.clicked.connect(self.run); status_row.addWidget(self.stop); status_row.addWidget(self.start,1); og.addLayout(status_row)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMinimumHeight(115); self.log.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;line-height:1.35;")
        og.addWidget(self.log,1); left_layout.addWidget(output_group,2)

        # 右侧工作设置区：预览与全部设置等高延伸到底部。
        work_group=QGroupBox("工作设置区 · 实时预览与字幕设计")
        work_group_layout=QVBoxLayout(work_group); work_group_layout.setContentsMargins(7,10,7,7)
        work_splitter=QSplitter(Qt.Orientation.Horizontal); work_splitter.setChildrenCollapsible(False)
        center.setMinimumWidth(500); settings_scroll.setMinimumWidth(430)
        work_splitter.addWidget(center); work_splitter.addWidget(settings_scroll); work_splitter.setSizes([650,500])
        work_group_layout.addWidget(work_splitter)
        workspace.addWidget(left); workspace.addWidget(work_group); workspace.setSizes([380,1080]); root.addWidget(workspace,1)

        self.preview_thread=None; self.preview_worker=None; self.timeline_thread=None; self.timeline_worker=None
        self._refresh_layer_list(0)
        self._refresh_task_queue()
        self._connect_live_preview_signals()
        self._caption_mode_changed(self.caption_mode.currentText())
        self.apply_preset("Descript 经典黄")

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

    def load_video_preview(self, path, external_audio=""):
        if not path or not Path(path).is_file(): return
        if self.preview_capture is not None:
            self.preview_capture.release()
        self.preview_capture = None
        self.preview_base_image = QImage(); self.seek.setRange(0,0)
        self._preview_external_audio = bool(external_audio and Path(external_audio).is_file())
        self.audio_output.setVolume(0 if self._preview_external_audio else .65)
        self.player.setSource(QUrl.fromLocalFile(path)); self.player.play()
        if self._preview_external_audio:
            self.audio_player.setSource(QUrl.fromLocalFile(external_audio))
            self.audio_player.setPosition(0); self.audio_player.play(); self.audio_play_btn.setText("暂停配音")
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
                self.audio_player.setPosition(self.player.position()); self.audio_player.play()
            self.player.play(); self.play_btn.setText("暂停")

    def _seek_preview(self, milliseconds):
        self.player.setPosition(int(milliseconds))
        if self._preview_external_audio: self.audio_player.setPosition(int(milliseconds))
        # QVideoSink 会在跳转完成后送来对应帧；短暂等待期间保留上一帧，不阻塞界面。

    def _video_frame_changed(self, frame):
        if not frame or not frame.isValid(): return
        image = frame.toImage()
        if image.isNull(): return
        self.preview_base_image = image.copy()
        self._display_cached_preview()

    def _display_cached_preview(self):
        if self.preview_base_image.isNull():
            return
        # 先缩到预览控件尺寸再绘制字幕，避免每帧在 1080x1920 原图上做昂贵的路径绘制。
        image = self.preview_base_image.scaled(
            self.video_widget.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation)
        if getattr(self, "live_preview", None) and self.live_preview.isChecked():
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
        if getattr(self, "live_preview", None) and self.live_preview.isChecked():
            self._paint_live_layers(image, target / 1000)
        pixmap = QPixmap.fromImage(image).scaled(
            self.video_widget.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.video_widget.setPixmap(pixmap)

    def _connect_live_preview_signals(self):
        for control in (self.font, self.position, self.free_animation):
            control.currentTextChanged.connect(self._refresh_live_preview)
        for control in (self.font_size, self.line_length, self.line_width, self.letter_spacing, self.line_spacing,
                        self.max_words, self.highlight_padding,
                        self.animation_speed, self.outline_width, self.margin_v, self.free_page_seconds):
            control.valueChanged.connect(self._refresh_live_preview)
        self.override_text.textChanged.connect(self._refresh_live_preview)

    def _refresh_live_preview(self, *_args):
        # 预览只重绘缓存画面，不重新解码视频；参数变化后立即同步。
        if hasattr(self,"preview_base_image") and not self.preview_base_image.isNull():
            self._display_cached_preview()

    def _live_caption_data(self, seconds):
        phrase_srt = self.override_text.toPlainText().strip() if hasattr(self, "override_text") else ""
        source = self._timeline_source() if hasattr(self, "audios") else ""
        word_srt = self.timeline_words.get(self._timeline_key(source), "") if source else ""
        if self.caption_mode.currentText() == "自由文案动画（不对口型）":
            duration=max(8.0,(self.player.duration() or 0)/1000)
            phrase_srt=free_caption_srt(phrase_srt,duration,self._current_settings())
            word_srt=""
        if phrase_srt and "-->" not in phrase_srt:
            phrase_srt = ""
        if not phrase_srt and word_srt:
            phrase_srt = group_word_srt(word_srt, max_chars=max(18, self.line_length.value() * 2),
                                        max_words=self.max_words.value())
        phrase_events = parse_srt(phrase_srt) if phrase_srt else []
        event = next((item for item in phrase_events if item[0] <= seconds <= item[1]), None)
        if event is None and phrase_events:
            event = min(phrase_events, key=lambda item: abs(item[0] - seconds))
        if event:
            text = event[2]
            word_events = [item for item in parse_srt(word_srt)
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
                elif layer.get("type") == "caption":
                    self._paint_live_caption(painter,image,seconds)
        finally:
            painter.end()

    def _paint_live_caption(self, painter, image, seconds):
        settings = self._current_settings(); preset = PRESETS[settings["preset"]]
        text, active_word = self._live_caption_data(seconds); tokens = tokens_for(text)
        if not tokens: return
        fixed_all = (settings.get("caption_mode") == "自由文案动画（不对口型）" and
                     settings.get("free_animation") == "整段固定")
        font=QFont(settings["font"]); font.setPixelSize(settings["font_size"]); font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, settings.get("letter_spacing",0))
        metrics=QFontMetricsF(font)
        gap=max(settings["font_size"]*.16,metrics.horizontalAdvance(" "))
        line_gap=max(settings["font_size"],metrics.height())*settings.get("line_spacing",116)/100
        max_line_width=1080*settings.get("line_width",86)/100
        if fixed_all and "\n" in text:
            lines=[tokens_for(line) for line in text.splitlines() if tokens_for(line)]
        else:
            lines=[]; current=[]
            for token in tokens:
                candidate=" ".join(current+[token])
                candidate_width=sum(metrics.horizontalAdvance(value) for value in current+[token])+gap*len(current)
                if current and (len(candidate)>settings["line_length"] or candidate_width>max_line_width):
                    lines.append(current); current=[token]
                else: current.append(token)
            if current: lines.append(current)
        # 与最终导出一致：一个画面最多两排。根据当前朗读词切换到对应分页。
        pages=([lines] if fixed_all else [lines[index:index+2] for index in range(0,len(lines),2)]) or [[]]
        active_page=0
        if active_word:
            for page_index,page in enumerate(pages):
                if any(active_word == token for line in page for token in line):
                    active_page=page_index; break
        lines=pages[active_page]
        if settings["position"]=="顶部": center_y=settings["margin_v"]+line_gap*(len(lines)-1)/2
        elif settings["position"]=="画面中间": center_y=960
        else: center_y=1920-settings["margin_v"]-line_gap*(len(lines)-1)/2
        base_color=QColor(settings["text_color"]); outline=QColor(settings["outline_color"]); highlight=QColor(settings["highlight_color"])
        effect=preset["effect"]; active_used=False
        for line_index,line in enumerate(lines):
            widths=[max(settings["font_size"]*.55,metrics.horizontalAdvance(token)) for token in line]
            total=sum(widths)+gap*max(0,len(line)-1); cursor=(1080-total)/2
            baseline=center_y+(line_index-(len(lines)-1)/2)*line_gap+metrics.ascent()/2-metrics.descent()/2
            for token,width in zip(line,widths):
                is_active=not active_used and token==active_word
                if is_active: active_used=True
                if is_active and effect in ("descript","heygen","highlight"):
                    pad=max(4,settings["highlight_padding"]); box=QColor(highlight); painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(box)
                    painter.drawRoundedRect(int(cursor-pad),int(baseline-metrics.ascent()-pad*.45),int(width+pad*2),int(metrics.height()+pad*.9),max(5,int(pad*.7)),max(5,int(pad*.7)))
                path=QPainterPath(); path.addText(cursor,baseline,font,token)
                pen_width=max(1.0,settings["outline_width"])
                painter.setPen(QPen(outline,pen_width*2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(path)
                fill=highlight if is_active and effect in ("word_color","pop","underline") else base_color
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(fill); painter.drawPath(path)
                if is_active and effect=="underline":
                    painter.setPen(QPen(highlight,max(2,pen_width))); painter.drawLine(int(cursor),int(baseline+metrics.descent()+3),int(cursor+width),int(baseline+metrics.descent()+3))
                cursor+=width+gap

    def _refresh_layer_list(self, selected=0):
        if not hasattr(self,"layer_list"): return
        self.layer_list.blockSignals(True); self.layer_list.clear()
        for index,layer in enumerate(self.layers):
            prefix="字幕" if layer.get("type")=="caption" else "蒙版"
            self.layer_list.addItem(f"{index+1}. {prefix} · {layer.get('name',prefix)}")
        self.layer_list.setCurrentRow(max(0,min(selected,len(self.layers)-1)))
        self.layer_list.blockSignals(False); self._layer_selected(self.layer_list.currentRow())

    def _add_mask_layer(self):
        self._mask_counter+=1; caption_index=next((i for i,l in enumerate(self.layers) if l.get("type")=="caption"),0)
        layer={"type":"mask","name":f"蒙版 {self._mask_counter}","enabled":True,"x":10,"y":66,"w":80,"h":15,"color":"#000000","opacity":55,"radius":35}
        self.layers.insert(caption_index+1,layer); self._refresh_layer_list(caption_index+1); self._refresh_live_preview()

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
        layer=self.layers[row] if 0<=row<len(self.layers) else None; enabled=bool(layer and layer.get("type")=="mask")
        for control in (self.mask_color,self.mask_opacity,self.mask_x,self.mask_y,self.mask_w,self.mask_h,self.mask_radius,*self.mask_quick_buttons): control.setEnabled(enabled)
        if not enabled: return
        controls=((self.mask_x,"x"),(self.mask_y,"y"),(self.mask_w,"w"),(self.mask_h,"h"),(self.mask_opacity,"opacity"),(self.mask_radius,"radius"))
        for control,key in controls: control.blockSignals(True); control.setValue(int(layer.get(key,0))); control.blockSignals(False)
        self.mask_color.setText(f"蒙版颜色 {layer.get('color','#000000')}"); self.mask_opacity_value.setText(f"{layer.get('opacity',55)}%")

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

    def _pick_mask_color(self):
        row=self.layer_list.currentRow()
        if row<0 or self.layers[row].get("type")!="mask": return
        color=QColorDialog.getColor(QColor(self.layers[row].get("color","#000000")),self)
        if color.isValid():
            self.layers[row]["color"]=color.name().upper(); self.mask_color.setText(f"蒙版颜色 {color.name().upper()}"); self._refresh_live_preview()

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
        self.audio_player.setSource(QUrl.fromLocalFile(path)); self.audio_play_btn.setText("试听配音")

    def toggle_audio_preview(self):
        if self.audio_player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.pause(); self.audio_play_btn.setText("继续试听")
        else:
            self.audio_player.play(); self.audio_play_btn.setText("暂停试听")

    def _audio_position_changed(self,value):
        if not self.audio_seek.isSliderDown(): self.audio_seek.setValue(value)
        self.audio_time.setText(f"{self._clock(value)} / {self._clock(self.audio_player.duration())}")

    def _audio_duration_changed(self,value):
        self.audio_seek.setRange(0,max(0,value)); self._audio_position_changed(self.audio_player.position())

    @staticmethod
    def _clock(milliseconds):
        seconds=max(0,int(milliseconds/1000)); return f"{seconds//60:02d}:{seconds%60:02d}"

    def _preview_position_changed(self, value):
        if not self.seek.isSliderDown(): self.seek.setValue(value)
        if self._preview_external_audio and abs(self.audio_player.position()-value) > 250:
            self.audio_player.setPosition(value)
        self.time_label.setText(f"{self._clock(value)} / {self._clock(self.player.duration())}")

    def _preview_duration_changed(self, value):
        self.seek.setRange(0,max(0,value)); self._preview_position_changed(self.player.position())

    def _current_settings(self):
        preset=next(button.text() for button in self.preset_buttons if button.isChecked())
        return {"preset":preset,"font":self.font.currentText(),"font_size":self.font_size.value(),
                "caption_mode":self.caption_mode.currentText(),
                "free_animation":self.free_animation.currentText(),
                "free_page_seconds":self.free_page_seconds.value(),
                "line_length":self.line_length.value(),"outline_width":self.outline_width.value(),
                "line_width":self.line_width.value(),"letter_spacing":self.letter_spacing.value(),
                "line_spacing":self.line_spacing.value(),
                "max_words":self.max_words.value(),"highlight_padding":self.highlight_padding.value(),
                "animation_speed":self.animation_speed.value(),
                "position":self.position.currentText(),"margin_v":self.margin_v.value(),
                "audio_mode":self.audio_mode.currentText(),"audio_match_mode":self.audio_match_mode.currentText(),
                "clean_metadata":self.clean_metadata.isChecked(),
                "override_text":self.override_text.toPlainText().strip(),"encode_preset":self.encode_preset.currentText(),
                "timeline_overrides":dict(self.timeline_overrides),
                "word_timelines":dict(self.timeline_words),
                "free_texts":dict(self.free_texts),
                "free_default_text":self.override_text.toPlainText().strip(),
                "preview_word_srt":self.timeline_words.get(self._timeline_key(self._timeline_source()),""),
                "layers":[dict(layer) for layer in self.layers],
                "text_color":self._hex(self.text_color),"outline_color":self._hex(self.outline_color),
                "highlight_color":self._hex(self.highlight_color),"provider":self.provider.currentText()}

    def render_effect_preview(self):
        item=self.videos.currentItem()
        if not item:
            QMessageBox.information(self,"没有预览视频","请先在左侧添加并选中一个视频。"); return
        try: ffmpeg=self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self,"缺少组件",str(exc)); return
        text=(self.override_text.toPlainText().strip() or self.tts_text.toPlainText().strip() or "让每一句文案跟随朗读跳动")
        if "-->" not in text and self.caption_mode.currentText() != "自由文案动画（不对口型）":
            text=re.sub(r"\s+"," ",text)[:100]
        preview_dir=Path(self.output.text())/".preview"; preview_dir.mkdir(parents=True,exist_ok=True)
        destination=preview_dir/f"effect_{Path(item.text()).stem}_{len(list(preview_dir.glob('effect_*.mp4'))) + 1}.mp4"
        self.render_preview_btn.setEnabled(False); self.render_preview_btn.setText("正在生成 8 秒预览…")
        settings=self._current_settings(); matched=self._matched_source_for_video(item.text())
        if (matched and Path(matched).is_file() and Path(matched).resolve()!=Path(item.text()).resolve()
                and self.audio_mode.currentText()=="替换为添加的音频"):
            settings["preview_audio"]=matched
        self.preview_thread=QThread(self); self.preview_worker=PreviewWorker(ffmpeg,item.text(),destination,text,settings)
        self.preview_worker.moveToThread(self.preview_thread); self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.finished.connect(self._effect_preview_done); self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self._preview_thread_ended); self.preview_thread.finished.connect(self.preview_thread.deleteLater); self.preview_thread.start()

    def _effect_preview_done(self, ok, result):
        self.render_preview_btn.setEnabled(True); self.render_preview_btn.setText("渲染 8 秒精确预览")
        if ok:
            self.load_video_preview(result)
            # 预览生成后停在有字幕的画面，避免自动播放到第 8 秒后看起来像“没有效果”。
            QTimer.singleShot(220, lambda: self._pause_effect_preview_at(900))
            self.log.appendPlainText(f"效果预览已生成并载入播放器：{result}")
        else: QMessageBox.critical(self,"预览生成失败",result)

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
        external = (source if source and Path(source).is_file() and Path(source).resolve() != Path(video_path).resolve()
                    and self.audio_mode.currentText() == "替换为添加的音频" else "")
        self.load_video_preview(video_path, external)
        self._active_timeline_source=source
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
            self._timeline_selection_changed(source)

    def _audio_selection_changed(self, source):
        if self._syncing_media_selection: return
        if not source:
            self._rematch_current_video(); return
        self.load_audio_preview(source)
        self._active_timeline_source=source
        self._timeline_selection_changed(source)

    def _rematch_current_video(self, *_args):
        item=self.videos.currentItem() if hasattr(self,"videos") else None
        if item: self._video_selection_changed(item.text())

    def _timeline_source(self):
        if self._active_timeline_source: return self._active_timeline_source
        video_item=self.videos.currentItem()
        if video_item: return self._matched_source_for_video(video_item.text())
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

    def _group_words_for_current_layout(self, word_srt):
        return group_word_srt(
            word_srt, max_chars=max(18,self.line_length.value()*2),
            max_words=self.max_words.value(),
        )

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

    def extract_timeline(self):
        source=self._timeline_source()
        if not source:
            QMessageBox.information(self,"没有音频","请先选中一个音频；未添加音频时也可以选中包含声音的视频。"); return
        sidecar=Path(source).with_suffix(".srt")
        if sidecar.exists() and sidecar.stat().st_size:
            words=sidecar.read_text(encoding="utf-8-sig"); text=self._group_words_for_current_layout(words)
            self.timeline_words[self._timeline_key(source)]=words; self.override_text.setPlainText(text)
            self.timeline_overrides[self._timeline_key(source)]=text; self.log.appendPlainText(f"已载入配音时间轴并合并为逐句字幕：{sidecar}"); return
        if self.timeline_thread and self.timeline_thread.isRunning(): return
        provider=self.provider.currentText(); self.extract_timeline_btn.setEnabled(False); self.extract_timeline_btn.setText("正在识别词级时间轴…")
        self._timeline_pending_source=source
        self.timeline_thread=QThread(self); callback=lambda path:self.transcribe_callable(path,provider)
        self.timeline_worker=TimelineWorker(callback,source); self.timeline_worker.moveToThread(self.timeline_thread)
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
        matcher=CaptionWorker(videos,audios,Path(self.output.text()),"",None,settings)
        sources=[]
        for index,video in enumerate(matcher.videos):
            source=matcher._audio_for(video,index)
            value=str(source)
            if value not in sources: sources.append(value)
        provider=self.provider.currentText(); callback=lambda path:self.transcribe_callable(path,provider)
        self.extract_timeline_btn.setEnabled(False); self.extract_all_btn.setEnabled(False)
        self.extract_all_btn.setText(f"排队提取 0/{len(sources)}")
        self.timeline_thread=QThread(self); self.timeline_worker=BatchTimelineWorker(callback,sources)
        self.timeline_worker.moveToThread(self.timeline_thread)
        self.timeline_thread.started.connect(self.timeline_worker.run)
        self.timeline_worker.item_done.connect(self._batch_timeline_item_done)
        self.timeline_worker.finished.connect(self._batch_timeline_done)
        self.timeline_worker.finished.connect(self.timeline_thread.quit)
        self.timeline_thread.finished.connect(self._timeline_ended)
        self.timeline_thread.finished.connect(self.timeline_thread.deleteLater)
        self.log.appendPlainText(f"已建立批量时间轴队列：{len(sources)} 个素材，将按视频匹配关系逐个处理。")
        self.timeline_thread.start()

    def _batch_timeline_item_done(self,source,srt,index,total):
        key=self._timeline_key(source); phrase_srt=self._group_words_for_current_layout(srt)
        self.timeline_words[key]=srt; self.timeline_overrides[key]=phrase_srt
        self.extract_all_btn.setText(f"排队提取 {index}/{total}")
        self.log.appendPlainText(f"[{index}/{total}] 时间轴已归档到：{Path(source).name}")
        if self._timeline_key(self._timeline_source())==key:
            self._loading_timeline=True
            try: self.override_text.setPlainText(phrase_srt)
            finally: self._loading_timeline=False
        self._refresh_task_queue()

    def _worker_timeline_ready(self,source,word_srt,phrase_srt):
        key=self._timeline_key(source)
        self.timeline_words[key]=word_srt; self.timeline_overrides[key]=phrase_srt
        if self._timeline_key(self._timeline_source())==key:
            self._loading_timeline=True
            try: self.override_text.setPlainText(phrase_srt)
            finally: self._loading_timeline=False
        self._refresh_task_queue()

    def _batch_timeline_done(self,ok,message):
        self.extract_timeline_btn.setEnabled(True); self.extract_all_btn.setEnabled(True)
        self.extract_all_btn.setText("批量提取全部")
        if ok: self.log.appendPlainText(message)
        else: QMessageBox.critical(self,"批量时间轴提取失败",message)

    def _timeline_done(self,ok,result):
        self.extract_timeline_btn.setEnabled(True); self.extract_timeline_btn.setText("提取选中素材")
        if ok:
            source=self._timeline_pending_source or self._timeline_source(); phrase_srt=self._group_words_for_current_layout(result)
            if source:
                key=self._timeline_key(source); self.timeline_words[key]=result; self.timeline_overrides[key]=phrase_srt
                if self._timeline_key(self._timeline_source())==key:
                    self._loading_timeline=True
                    try: self.override_text.setPlainText(phrase_srt)
                    finally: self._loading_timeline=False
            self.log.appendPlainText("词级时间轴已保留；编辑器已合并为逐句字幕，可修改每句话的时间和文字。")
            self._refresh_task_queue()
        else: QMessageBox.critical(self,"时间轴提取失败",result)

    def _timeline_ended(self):
        self.timeline_worker=None; self.timeline_thread=None; self._timeline_pending_source=""
        if hasattr(self,"extract_timeline_btn"): self.extract_timeline_btn.setEnabled(True)
        if hasattr(self,"extract_all_btn"): self.extract_all_btn.setEnabled(True); self.extract_all_btn.setText("批量提取全部")

    def load_srt_file(self):
        path,_=QFileDialog.getOpenFileName(self,"载入字幕时间轴","","SRT 字幕 (*.srt);;文本 (*.txt)")
        if not path: return
        try:
            text=Path(path).read_text(encoding="utf-8-sig"); self.override_text.setPlainText(text); source=self._timeline_source()
            if source: self.timeline_overrides[self._timeline_key(source)]=text
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
            QMessageBox.warning(self, "批量配音完成（含失败项）", result)

    def _tts_ended(self):
        self.tts_worker = None; self.tts_thread = None

    def pick_color(self, button):
        current = re.search(r"#[0-9A-Fa-f]{6}", button.text()); color = QColorDialog.getColor(QColor(current.group() if current else "#ffffff"), self)
        if color.isValid():
            button.setText(re.sub(r"#[0-9A-Fa-f]{6}", color.name().upper(), button.text())); self.update_style_preview(); self._refresh_live_preview()

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
        if "margin_v" in preset: self.margin_v.setValue(preset["margin_v"])
        if "max_words" in preset: self.max_words.setValue(preset["max_words"])
        if "highlight_padding" in preset: self.highlight_padding.setValue(preset["highlight_padding"])
        if "animation_speed" in preset: self.animation_speed.setValue(preset["animation_speed"])
        if hasattr(self, "preview_position_slider"):
            self.preview_position_slider.blockSignals(True)
            self.preview_position_slider.setValue(self.margin_v.value())
            self.preview_position_slider.blockSignals(False)
            self.preview_position_value.setText(f"距底部 {self.margin_v.value()}")
        self.update_style_preview(); self._refresh_live_preview()

    def update_style_preview(self):
        if not hasattr(self, "style_preview"): return
        text = self._hex(self.text_color); highlight = self._hex(self.highlight_color)
        self.style_preview.setText(
            f'<span style="color:{text};font-size:20px;font-weight:700;">整句稳定显示，当前词 </span>'
            f'<span style="background:{highlight};border-radius:8px;color:#ffffff;font-size:22px;font-weight:800;padding:6px 10px;">跟随朗读</span>')

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if folder: self.output.setText(folder)

    def _hex(self, button): return re.search(r"#[0-9A-Fa-f]{6}", button.text()).group()

    def run(self):
        videos = [self.videos.item(i).text() for i in range(self.videos.count())]
        audios = [self.audios.item(i).text() for i in range(self.audios.count())]
        if not videos: QMessageBox.information(self, "没有视频", "请先添加视频素材。"); return
        try: ffmpeg = self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self, "缺少组件", str(exc)); return
        settings = self._current_settings()
        self.log.clear(); self.progress.setValue(0); self.thread = QThread(self)
        callback = lambda path: self.transcribe_callable(path, settings["provider"])
        self.worker = CaptionWorker(videos, audios, self.output.text(), ffmpeg, callback, settings)
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText); self.worker.progress.connect(self.progress.setValue)
        self.worker.timeline_ready.connect(self._worker_timeline_ready)
        self.worker.finished.connect(self.done); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.ended); self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False); self.stop.setEnabled(True); self.thread.start()

    def cancel(self):
        if self.worker: self.worker.cancel()

    def done(self, ok, message):
        self.start.setEnabled(True); self.stop.setEnabled(False); self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(self, "动态文案" if ok else "生成失败", message)

    def ended(self): self.worker = None; self.thread = None
