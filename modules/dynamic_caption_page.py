from __future__ import annotations

import re
import subprocess
from pathlib import Path

import cv2

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .path_picker import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, DropListWidget, collect_files, natural_key
from .settings_page import hidden_kwargs


PRESETS = {
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
        text = " ".join(lines[timing_index + 1:]).strip()
        if text: result.append((start, max(start + .1, end), text))
    return result


def group_word_srt(srt, max_chars=36, max_duration=5.2):
    """把词级时间轴合并成便于阅读/编辑的逐句 SRT，保留首尾真实时间。"""
    words = parse_srt(srt)
    if not words: return srt
    # 已经是正常句级字幕时不重复合并。
    if len(words) <= 2 or sum(len(tokens_for(text)) for _,_,text in words) > len(words) * 2:
        return srt
    phrases=[]; current=[]; start=None; end=None
    for w_start,w_end,text in words:
        if start is None: start=w_start
        candidate=(" ".join(current+[text])).strip()
        current.append(text); end=w_end
        sentence_end=bool(re.search(r"[.!?。！？…][\"'”’)]?$",text))
        if sentence_end or len(candidate)>=max_chars or end-start>=max_duration:
            phrases.append((start,end," ".join(current))); current=[]; start=end=None
    if current: phrases.append((start or 0,end or (start or 0)+1," ".join(current)))
    blocks=[]
    for index,(start,end,text) in enumerate(phrases,1):
        def stamp(value):
            ms=max(0,round(value*1000)); h,rem=divmod(ms,3600000); m,rem=divmod(rem,60000); sec,milli=divmod(rem,1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{milli:03d}"
        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}")
    return "\n\n".join(blocks)+"\n"


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
Style: Base,{font},{settings['font_size']},{text_color},{text_color},{outline_color},&H90000000,-1,0,0,0,100,100,0,0,1,{settings['outline_width']},2,{alignment},40,40,{settings['margin_v']},1
Style: Active,{font},{settings['font_size']},&H00FFFFFF,&H00FFFFFF,{highlight},{highlight},-1,0,0,0,100,100,0,0,3,{settings['outline_width']},0,{alignment},40,40,{max(20, settings['margin_v'] - 90)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    precise_words = parse_srt(word_srt)
    font_size = settings["font_size"]
    metric_font = QFont(font)
    metric_font.setPixelSize(font_size)
    metric_font.setBold(True)
    metrics = QFontMetricsF(metric_font)
    line_gap = font_size * 1.32
    position = settings.get("position", "底部")
    for start, end, text in parse_srt(srt):
        safe = text.replace("{", "（").replace("}", "）")
        tokens = tokens_for(safe)
        if not tokens: continue
        effect = preset["effect"]
        # 先按用户设置拆成可读的逐句行。
        lines=[]; current=[]
        for token in tokens:
            candidate=" ".join(current+[token])
            if current and len(candidate)>settings["line_length"]:
                lines.append(current); current=[token]
            else: current.append(token)
        if current: lines.append(current)
        if position == "顶部": center_y=settings["margin_v"]+line_gap*(len(lines)-1)/2
        elif position == "画面中间": center_y=960
        else: center_y=1920-settings["margin_v"]-line_gap*(len(lines)-1)/2

        phrase_words=[item for item in precise_words if item[0] < end+.08 and item[1] > start-.08]
        if len(phrase_words) >= len(tokens):
            timings=[(phrase_words[i][0],phrase_words[i][1]) for i in range(len(tokens))]
        else:
            duration=max(.08,(end-start)/len(tokens)); timings=[(start+duration*i,min(end,start+duration*(i+1))) for i in range(len(tokens))]

        token_index=0
        for line_index,line_tokens in enumerate(lines):
            y=center_y+(line_index-(len(lines)-1)/2)*line_gap
            line_text=" ".join(line_tokens)
            base_override=fr"{{\an5\pos(540,{y:.1f})}}"
            if effect == "glow": base_override=fr"{{\an5\pos(540,{y:.1f})\blur3}}"
            events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Base,,0,0,0,,{base_override}{line_text}")
            if effect in ("outline","glow"):
                token_index += len(line_tokens); continue

            def estimated_width(value):
                # 使用当前字体的真实粗体宽度定位高亮词，避免背景块与原词错位。
                return max(font_size * .55, metrics.horizontalAdvance(value))
            widths=[estimated_width(token) for token in line_tokens]
            space=max(font_size * .25, metrics.horizontalAdvance(" "))
            total=sum(widths)+space*max(0,len(widths)-1); cursor=540-total/2
            for local_index,token in enumerate(line_tokens):
                x=cursor+widths[local_index]/2; cursor+=widths[local_index]+space
                token_start,token_end=timings[token_index]; token_index+=1
                if effect == "heygen": override=fr"{{\an5\pos({x:.1f},{y:.1f})\fscx100\fscy100}}"
                elif effect == "pop": override=fr"{{\an5\pos({x:.1f},{y:.1f})\fscx75\fscy75\t(0,140,\fscx108\fscy108)\t(140,220,\fscx100\fscy100)}}"
                elif effect == "underline": override=fr"{{\an5\pos({x:.1f},{y:.1f})\u1}}"
                else: override=fr"{{\an5\pos({x:.1f},{y:.1f})\fscx96\fscy96\t(0,110,\fscx104\fscy104)}}"
                events.append(f"Dialogue: 1,{ass_time(token_start)},{ass_time(token_end)},Active,,0,0,0,,{override}{token}")
    path.write_text(header + "\n".join(events), encoding="utf-8-sig")


class CaptionWorker(QObject):
    log = Signal(str); progress = Signal(int); result = Signal(str, str); finished = Signal(bool, str)

    def __init__(self, videos, audios, output, ffmpeg, transcribe, settings):
        super().__init__(); self.videos = [Path(p) for p in videos]; self.audios = [Path(p) for p in audios]
        self.output = Path(output); self.ffmpeg = ffmpeg; self.transcribe = transcribe; self.settings = settings; self.cancelled = False

    def cancel(self): self.cancelled = True

    def _audio_for(self, video, index):
        if not self.audios: return video
        if len(self.audios) == 1: return self.audios[0]
        same = next((audio for audio in self.audios if audio.stem.casefold() == video.stem.casefold()), None)
        return same or self.audios[min(index, len(self.audios) - 1)]

    def _clean_video(self, video):
        clean_dir = self.output / "00_无元数据素材"; clean_dir.mkdir(parents=True, exist_ok=True)
        destination = clean_dir / video.name
        if destination.exists() and destination.stat().st_size > 0:
            self.log.emit(f"续接：复用已清理素材 {destination.name}"); return destination
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                   "-map", "0", "-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy", str(destination)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            raise RuntimeError(f"Reels 素材元数据清理失败：{video.name}\n{result.stderr[-500:]}")
        self.log.emit(f"已清理素材元数据：{destination.name}"); return destination

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            for index, video in enumerate(self.videos):
                if self.cancelled: raise RuntimeError("任务已停止；已完成的动态文案视频仍保留。")
                render_video = self._clean_video(video) if self.settings["clean_metadata"] else video
                audio = self._audio_for(video, index)
                source_key = str(audio.resolve())
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
                phrase_srt = group_word_srt(word_srt, self.settings["line_length"] * 2)
                override = str(self.settings.get("timeline_overrides", {}).get(str(audio.resolve()), "")).strip()
                if not override and len(self.audios) <= 1: override = self.settings.get("override_text", "").strip()
                if override:
                    if "-->" in override:
                        phrase_srt = override
                        self.log.emit("已应用人工修订后的逐句 SRT，逐词时间轴继续驱动高亮。")
                    else:
                        phrase_srt = replace_srt_copy(phrase_srt, override)
                        self.log.emit("已应用人工修订文案，并保留词级时间轴。")
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


class PreviewWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, ffmpeg, source, destination, text, settings):
        super().__init__(); self.ffmpeg = ffmpeg; self.source = Path(source)
        self.destination = Path(destination); self.text = text; self.settings = settings

    def run(self):
        ass = self.destination.with_suffix(".ass")
        try:
            sample = self.text if "-->" in self.text else f"1\n00:00:00,000 --> 00:00:08,000\n{self.text}\n"
            write_ass(ass, sample, self.settings, self.settings.get("preview_word_srt", ""))
            ass_filter = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.source),
                       "-t", "8", "-vf", f"ass='{ass_filter}'", "-map", "0:v:0", "-map", "0:a?",
                       "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-c:a", "aac",
                       "-b:a", "160k", "-movflags", "+faststart", str(self.destination)]
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


class DynamicCaptionPage(QWidget):
    def __init__(self, transcribe_callable, tts_callable, find_ffmpeg, providers, default_provider):
        super().__init__(); self.transcribe_callable = transcribe_callable; self.find_ffmpeg = find_ffmpeg
        self.tts_callable = tts_callable; self.providers = providers; self.thread = None; self.worker = None
        self.tts_thread = None; self.tts_worker = None; self.timeline_overrides = {}; self.timeline_words = {}; self._loading_timeline = False
        self._build_ui(default_provider)

    def _build_ui(self, default_provider):
        root = QVBoxLayout(self); root.setContentsMargins(12, 8, 12, 10); root.setSpacing(6)
        header = QHBoxLayout(); heading = QLabel("动态 Reels 制作流水线"); heading.setObjectName("heading")
        header.addWidget(heading); header.addStretch(); header.addWidget(QLabel("清理素材 → 配音 → 字幕样式 → 视频预览 → 批量输出")); root.addLayout(header)

        workspace = QSplitter(Qt.Orientation.Horizontal); workspace.setChildrenCollapsible(False)

        # 左栏：素材与配音，始终保留足够的可操作高度。
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0,0,4,0); left_layout.setSpacing(6)
        video_group = QGroupBox("1. 视频素材"); vg = QVBoxLayout(video_group); vg.setContentsMargins(9,10,9,8)
        self.videos = DropListWidget(); self.videos.setMinimumHeight(150)
        self.videos.paths_dropped.connect(lambda p: self._add(self.videos, p, VIDEO_EXTENSIONS))
        self.videos.currentTextChanged.connect(self.load_video_preview); vg.addWidget(self.videos, 1)
        vrow = QHBoxLayout(); vb = QPushButton("添加视频"); vb.clicked.connect(self._choose_videos)
        vf = QPushButton("添加文件夹"); vf.clicked.connect(lambda: self._choose_folder(self.videos, VIDEO_EXTENSIONS))
        vc = QPushButton("清空"); vc.clicked.connect(self.videos.clear)
        for button in (vb,vf,vc): vrow.addWidget(button)
        vg.addLayout(vrow); left_layout.addWidget(video_group, 1)

        audio_group = QGroupBox("2. 音频 / 文案转语音"); ag = QVBoxLayout(audio_group); ag.setContentsMargins(9,10,9,8)
        source_tabs = QTabWidget(); audio_tab = QWidget(); audio_tab_layout = QVBoxLayout(audio_tab); audio_tab_layout.setContentsMargins(4,4,4,4)
        self.audios = DropListWidget(); self.audios.setMinimumHeight(95); self.audios.paths_dropped.connect(lambda p: self._add(self.audios, p, AUDIO_EXTENSIONS))
        self.audios.currentTextChanged.connect(self._timeline_selection_changed)
        self.audios.currentTextChanged.connect(self.load_audio_preview)
        arow = QHBoxLayout(); ab = QPushButton("添加音频"); ab.clicked.connect(self._choose_audio)
        af = QPushButton("添加文件夹"); af.clicked.connect(lambda: self._choose_folder(self.audios, AUDIO_EXTENSIONS))
        ac = QPushButton("清空"); ac.clicked.connect(self.audios.clear)
        for button in (ab,af,ac): arow.addWidget(button)
        audio_tab_layout.addWidget(self.audios,1); audio_tab_layout.addLayout(arow)
        text_tab = QWidget(); text_tab_layout = QVBoxLayout(text_tab); text_tab_layout.setContentsMargins(4,4,4,4)
        self.tts_text = QPlainTextEdit(); self.tts_text.setMinimumHeight(95); self.tts_text.setPlaceholderText("粘贴文案；生成的配音会自动加入音频队列。")
        text_tab_layout.addWidget(self.tts_text,1)
        self.tts_service = QComboBox(); self.tts_service.addItems(["微软文字转语音", "ElevenLabs API"])
        self.tts_voice = QComboBox(); self.tts_voice.setEditable(True); self._load_microsoft_voices()
        self.tts_service.currentTextChanged.connect(self.tts_service_changed)
        self.tts_generate = QPushButton("生成并加入音频"); self.tts_generate.clicked.connect(self.generate_tts)
        tts_line1 = QHBoxLayout(); tts_line1.addWidget(self.tts_service); tts_line1.addWidget(self.tts_voice,1)
        text_tab_layout.addLayout(tts_line1); text_tab_layout.addWidget(self.tts_generate)
        source_tabs.addTab(audio_tab,"音频转文字"); source_tabs.addTab(text_tab,"文案生成配音")
        source_tabs.setStyleSheet("QTabBar::tab{background:#17243a;color:#cbd5e1;padding:8px 18px;border:1px solid #334155;} QTabBar::tab:selected{background:#2563eb;color:white;font-weight:700;} QTabWidget::pane{border:1px solid #334155;}")
        ag.addWidget(source_tabs)
        self.audio_player=QMediaPlayer(self); self.audio_preview_output=QAudioOutput(self); self.audio_preview_output.setVolume(.8); self.audio_player.setAudioOutput(self.audio_preview_output)
        self.audio_player.positionChanged.connect(self._audio_position_changed); self.audio_player.durationChanged.connect(self._audio_duration_changed)
        audio_controls=QHBoxLayout(); self.audio_play_btn=QPushButton("试听配音"); self.audio_play_btn.clicked.connect(self.toggle_audio_preview)
        self.audio_seek=QSlider(Qt.Orientation.Horizontal); self.audio_seek.setRange(0,0); self.audio_seek.sliderMoved.connect(self.audio_player.setPosition)
        self.audio_time=QLabel("00:00 / 00:00"); audio_controls.addWidget(self.audio_play_btn); audio_controls.addWidget(self.audio_seek,1); audio_controls.addWidget(self.audio_time); ag.addLayout(audio_controls)
        left_layout.addWidget(audio_group,1)

        # 中栏：真正的视频播放器、时间轴和快速效果预览。
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
        self.player.positionChanged.connect(self._preview_position_changed); self.player.durationChanged.connect(self._preview_duration_changed)
        self.player.errorOccurred.connect(lambda _error,message:self.log.appendPlainText(f"播放器错误：{message}") if hasattr(self,"log") else None)
        self.preview_capture = None
        self.preview_frame_timer = QTimer(self); self.preview_frame_timer.setInterval(40); self.preview_frame_timer.timeout.connect(self._render_preview_frame)
        preview_layout.addWidget(self.video_widget,1)
        timeline = QHBoxLayout(); self.play_btn = QPushButton("播放"); self.play_btn.clicked.connect(self.toggle_preview)
        self.seek = QSlider(Qt.Orientation.Horizontal); self.seek.setRange(0,0); self.seek.sliderMoved.connect(self._seek_preview)
        self.time_label = QLabel("00:00 / 00:00"); timeline.addWidget(self.play_btn); timeline.addWidget(self.seek,1); timeline.addWidget(self.time_label); preview_layout.addLayout(timeline)
        position_preview = QHBoxLayout()
        position_preview.addWidget(QLabel("字幕上下位置"))
        self.preview_position_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_position_slider.setRange(20, 900)
        self.preview_position_slider.setValue(350)
        self.preview_position_slider.setToolTip("向右移动会把字幕向上抬高；重新生成 8 秒预览后生效")
        self.preview_position_value = QLabel("距底部 350")
        self.preview_position_slider.valueChanged.connect(self._preview_margin_changed)
        position_preview.addWidget(QLabel("低")); position_preview.addWidget(self.preview_position_slider, 1)
        position_preview.addWidget(QLabel("高")); position_preview.addWidget(self.preview_position_value)
        preview_layout.addLayout(position_preview)
        self.render_preview_btn = QPushButton("生成前 8 秒字幕效果预览"); self.render_preview_btn.setObjectName("primary"); self.render_preview_btn.clicked.connect(self.render_effect_preview)
        preview_layout.addWidget(self.render_preview_btn); center_layout.addWidget(preview_group,1)
        self.style_preview = QLabel(); self.style_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.style_preview.setMinimumHeight(76)
        self.style_preview.setVisible(False)

        # 右栏：设置独立滚动，任何窗口高度都不会把控件压扁。
        settings_scroll = QScrollArea(); settings_scroll.setWidgetResizable(True); settings_scroll.setMinimumWidth(430)
        settings_body = QWidget(); settings_layout = QVBoxLayout(settings_body); settings_layout.setContentsMargins(4,0,8,4); settings_layout.setSpacing(7)
        preset_group = QGroupBox("3. 字幕样式与动画"); pg = QVBoxLayout(preset_group); pg.setContentsMargins(10,12,10,10); pg.setSpacing(8)
        preset_grid = QGridLayout(); preset_grid.setSpacing(6); self.preset_buttons=[]
        for index,name in enumerate(PRESETS):
            button=QPushButton(name); button.setCheckable(True); button.setMinimumHeight(32); button.clicked.connect(lambda checked=False,n=name:self.apply_preset(n)); preset_grid.addWidget(button,index//2,index%2); self.preset_buttons.append(button)
        pg.addLayout(preset_grid)
        form = QFormLayout(); form.setVerticalSpacing(9); form.setHorizontalSpacing(8)
        self.provider=QComboBox(); self.provider.addItems(self.providers); self.provider.setCurrentText(default_provider)
        self.font=QComboBox(); self.font.addItems(QFontDatabase.families()); self.font.setCurrentText("Microsoft YaHei")
        self.font_size=QSpinBox(); self.font_size.setRange(20,160); self.font_size.setValue(58)
        font_line=QHBoxLayout(); font_line.addWidget(self.font,1); font_line.addWidget(QLabel("字号")); font_line.addWidget(self.font_size)
        self.line_length=QSpinBox(); self.line_length.setRange(6,60); self.line_length.setValue(18)
        self.outline_width=QSpinBox(); self.outline_width.setRange(0,12); self.outline_width.setValue(3)
        self.position=QComboBox(); self.position.addItems(["底部","画面中间","顶部"])
        self.margin_v=QSpinBox(); self.margin_v.setRange(20,900); self.margin_v.setValue(250)
        self.margin_v.valueChanged.connect(self._sync_preview_margin)
        position_line=QHBoxLayout(); position_line.addWidget(self.position); position_line.addWidget(QLabel("边距")); position_line.addWidget(self.margin_v)
        self.audio_mode=QComboBox(); self.audio_mode.addItems(["替换为添加的音频","保留视频原音"])
        self.clean_metadata=QCheckBox("输出前无损清除视频素材元数据"); self.clean_metadata.setChecked(True)
        self.encode_preset=QComboBox(); self.encode_preset.addItems(["veryfast","faster","fast","medium"])
        form.addRow("识别服务",self.provider); form.addRow("字体",font_line); form.addRow("每行字数",self.line_length)
        form.addRow("字幕位置",position_line); form.addRow("描边宽度",self.outline_width); form.addRow("音频处理",self.audio_mode); form.addRow("渲染质量",self.encode_preset); form.addRow("素材清理",self.clean_metadata)
        pg.addLayout(form)
        colors=QGridLayout(); self.text_color=QPushButton("文字 #FFFFFF"); self.outline_color=QPushButton("描边 #111827"); self.highlight_color=QPushButton("跟读背景 #8B5CF6")
        for index,button in enumerate((self.text_color,self.outline_color,self.highlight_color)):
            button.setMinimumHeight(32); button.clicked.connect(lambda checked=False,b=button:self.pick_color(b)); colors.addWidget(button,index//2,index%2)
        pg.addLayout(colors); settings_layout.addWidget(preset_group)
        revise_group=QGroupBox("字幕时间轴与文字调整"); revise_layout=QVBoxLayout(revise_group); revise_layout.setContentsMargins(9,11,9,8)
        timeline_actions=QHBoxLayout(); self.extract_timeline_btn=QPushButton("提取选中音频时间轴"); self.extract_timeline_btn.clicked.connect(self.extract_timeline)
        load_sidecar=QPushButton("载入 SRT…"); load_sidecar.clicked.connect(self.load_srt_file); timeline_actions.addWidget(self.extract_timeline_btn); timeline_actions.addWidget(load_sidecar)
        revise_layout.addLayout(timeline_actions)
        timeline_hint=QLabel("可直接修改每段的开始/结束时间和文字；逐词动画将严格使用这些时间戳。")
        timeline_hint.setWordWrap(True); timeline_hint.setStyleSheet("color:#7dd3fc;"); revise_layout.addWidget(timeline_hint)
        self.override_text=QPlainTextEdit(); self.override_text.setMinimumHeight(190); self.override_text.setPlaceholderText("1\n00:00:00,250 --> 00:00:00,780\nPrimeira\n\n2\n00:00:00,790 --> 00:00:01,240\npalavra")
        self.override_text.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;")
        self.override_text.textChanged.connect(self._timeline_text_changed)
        revise_layout.addWidget(self.override_text); settings_layout.addWidget(revise_group); settings_layout.addStretch(); settings_scroll.setWidget(settings_body)

        workspace.addWidget(left); workspace.addWidget(center); workspace.addWidget(settings_scroll); workspace.setSizes([330,590,470]); root.addWidget(workspace,1)

        # 底部日志独占整行，不再被表单挤压。
        output_group=QGroupBox("4. 批量生成与运行日志"); og=QVBoxLayout(output_group); og.setContentsMargins(10,10,10,8); og.setSpacing(6)
        outrow=QHBoxLayout(); self.output=QLineEdit(str(Path.cwd()/"dynamic_caption_outputs")); outrow.addWidget(QLabel("输出目录")); outrow.addWidget(self.output,1)
        choose=QPushButton("选择…"); choose.clicked.connect(self.choose_output); outrow.addWidget(choose); og.addLayout(outrow)
        status_row=QHBoxLayout(); self.progress=QProgressBar(); self.progress.setMinimumHeight(20); status_row.addWidget(self.progress,1)
        self.stop=QPushButton("停止"); self.stop.setEnabled(False); self.stop.clicked.connect(self.cancel)
        self.start=QPushButton("开始批量生成 Reels"); self.start.setObjectName("primary"); self.start.clicked.connect(self.run); status_row.addWidget(self.stop); status_row.addWidget(self.start); og.addLayout(status_row)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMinimumHeight(105); self.log.setMaximumHeight(145); self.log.setStyleSheet("font-family:Consolas,'Microsoft YaHei UI';font-size:12px;line-height:1.35;")
        og.addWidget(self.log); root.addWidget(output_group)

        self.preview_thread=None; self.preview_worker=None; self.timeline_thread=None; self.timeline_worker=None; self.apply_preset("HeyGen 跟读")

    def _add(self, widget, paths, extensions):
        existing = {widget.item(i).text() for i in range(widget.count())}
        for path in collect_files(paths, extensions):
            if path not in existing: widget.addItem(path); existing.add(path)
        if widget.count() and widget.currentRow() < 0: widget.setCurrentRow(0)

    def _load_microsoft_voices(self):
        self.tts_voice.clear()
        self.tts_voice.addItems([
            "pt-PT-RaquelNeural", "pt-PT-DuarteNeural",
            "pt-BR-FranciscaNeural", "pt-BR-AntonioNeural",
            "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "en-US-JennyNeural",
        ])
        self.tts_voice.setToolTip("pt-PT 是欧洲葡萄牙语；pt-BR 是巴西葡萄牙语。")

    def load_video_preview(self, path):
        if not path or not Path(path).is_file(): return
        if self.preview_capture is not None:
            self.preview_capture.release()
        self.preview_capture = cv2.VideoCapture(str(path))
        fps = self.preview_capture.get(cv2.CAP_PROP_FPS) or 25.0
        frames = self.preview_capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = int(frames / fps * 1000) if frames else 0
        if duration: self.seek.setRange(0, duration)
        self.player.setSource(QUrl.fromLocalFile(path)); self.player.play()
        self.preview_frame_timer.start(); self._seek_preview(0); self.play_btn.setText("暂停")

    def toggle_preview(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause(); self.preview_frame_timer.stop(); self.play_btn.setText("播放")
        else:
            self.player.play(); self.preview_frame_timer.start(); self.play_btn.setText("暂停")

    def _seek_preview(self, milliseconds):
        self.player.setPosition(int(milliseconds))
        if self.preview_capture is not None:
            self.preview_capture.set(cv2.CAP_PROP_POS_MSEC, max(0, int(milliseconds)))
            self._render_preview_frame(force=True, target_override=milliseconds)

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
        pixmap = QPixmap.fromImage(image).scaled(
            self.video_widget.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.video_widget.setPixmap(pixmap)

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
        self.time_label.setText(f"{self._clock(value)} / {self._clock(self.player.duration())}")

    def _preview_duration_changed(self, value):
        self.seek.setRange(0,max(0,value)); self._preview_position_changed(self.player.position())

    def _current_settings(self):
        preset=next(button.text() for button in self.preset_buttons if button.isChecked())
        return {"preset":preset,"font":self.font.currentText(),"font_size":self.font_size.value(),
                "line_length":self.line_length.value(),"outline_width":self.outline_width.value(),
                "position":self.position.currentText(),"margin_v":self.margin_v.value(),
                "audio_mode":self.audio_mode.currentText(),"clean_metadata":self.clean_metadata.isChecked(),
                "override_text":self.override_text.toPlainText().strip(),"encode_preset":self.encode_preset.currentText(),
                "timeline_overrides":dict(self.timeline_overrides),
                "word_timelines":dict(self.timeline_words),
                "preview_word_srt":self.timeline_words.get(self._timeline_key(self._timeline_source()),""),
                "text_color":self._hex(self.text_color),"outline_color":self._hex(self.outline_color),
                "highlight_color":self._hex(self.highlight_color),"provider":self.provider.currentText()}

    def render_effect_preview(self):
        item=self.videos.currentItem()
        if not item:
            QMessageBox.information(self,"没有预览视频","请先在左侧添加并选中一个视频。"); return
        try: ffmpeg=self.find_ffmpeg()
        except Exception as exc: QMessageBox.critical(self,"缺少组件",str(exc)); return
        text=(self.override_text.toPlainText().strip() or self.tts_text.toPlainText().strip() or "让每一句文案跟随朗读跳动")
        if "-->" not in text: text=re.sub(r"\s+"," ",text)[:100]
        preview_dir=Path(self.output.text())/".preview"; preview_dir.mkdir(parents=True,exist_ok=True)
        destination=preview_dir/f"effect_{Path(item.text()).stem}_{len(list(preview_dir.glob('effect_*.mp4'))) + 1}.mp4"
        self.render_preview_btn.setEnabled(False); self.render_preview_btn.setText("正在生成 8 秒预览…")
        self.preview_thread=QThread(self); self.preview_worker=PreviewWorker(ffmpeg,item.text(),destination,text,self._current_settings())
        self.preview_worker.moveToThread(self.preview_thread); self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.finished.connect(self._effect_preview_done); self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self._preview_thread_ended); self.preview_thread.finished.connect(self.preview_thread.deleteLater); self.preview_thread.start()

    def _effect_preview_done(self, ok, result):
        self.render_preview_btn.setEnabled(True); self.render_preview_btn.setText("生成前 8 秒字幕效果预览")
        if ok:
            self.load_video_preview(result)
            # 预览生成后停在有字幕的画面，避免自动播放到第 8 秒后看起来像“没有效果”。
            QTimer.singleShot(220, lambda: self._pause_effect_preview_at(900))
            self.log.appendPlainText(f"效果预览已生成并载入播放器：{result}")
        else: QMessageBox.critical(self,"预览生成失败",result)

    def _preview_thread_ended(self): self.preview_worker=None; self.preview_thread=None

    def _pause_effect_preview_at(self, milliseconds):
        self.player.pause(); self.preview_frame_timer.stop(); self._seek_preview(milliseconds)
        self.seek.setValue(milliseconds)
        self.time_label.setText(f"{self._clock(milliseconds)} / {self._clock(self.player.duration() or self.seek.maximum())}")
        self.play_btn.setText("播放效果")

    def _timeline_source(self):
        audio_item=self.audios.currentItem()
        if audio_item: return audio_item.text()
        video_item=self.videos.currentItem()
        return video_item.text() if video_item else ""

    def _timeline_key(self, source):
        try: return str(Path(source).resolve())
        except Exception: return str(source)

    def _timeline_selection_changed(self, source):
        self._loading_timeline=True
        try: self.override_text.setPlainText(self.timeline_overrides.get(self._timeline_key(source),""))
        finally: self._loading_timeline=False

    def _timeline_text_changed(self):
        if self._loading_timeline: return
        source=self._timeline_source()
        if source: self.timeline_overrides[self._timeline_key(source)]=self.override_text.toPlainText()

    def extract_timeline(self):
        source=self._timeline_source()
        if not source:
            QMessageBox.information(self,"没有音频","请先选中一个音频；未添加音频时也可以选中包含声音的视频。"); return
        sidecar=Path(source).with_suffix(".srt")
        if sidecar.exists() and sidecar.stat().st_size:
            words=sidecar.read_text(encoding="utf-8-sig"); text=group_word_srt(words)
            self.timeline_words[self._timeline_key(source)]=words; self.override_text.setPlainText(text)
            self.timeline_overrides[self._timeline_key(source)]=text; self.log.appendPlainText(f"已载入配音时间轴并合并为逐句字幕：{sidecar}"); return
        if self.timeline_thread and self.timeline_thread.isRunning(): return
        provider=self.provider.currentText(); self.extract_timeline_btn.setEnabled(False); self.extract_timeline_btn.setText("正在识别词级时间轴…")
        self.timeline_thread=QThread(self); callback=lambda path:self.transcribe_callable(path,provider)
        self.timeline_worker=TimelineWorker(callback,source); self.timeline_worker.moveToThread(self.timeline_thread)
        self.timeline_thread.started.connect(self.timeline_worker.run); self.timeline_worker.finished.connect(self._timeline_done); self.timeline_worker.finished.connect(self.timeline_thread.quit)
        self.timeline_thread.finished.connect(self._timeline_ended); self.timeline_thread.finished.connect(self.timeline_thread.deleteLater); self.timeline_thread.start()

    def _timeline_done(self,ok,result):
        self.extract_timeline_btn.setEnabled(True); self.extract_timeline_btn.setText("提取选中音频时间轴")
        if ok:
            source=self._timeline_source(); phrase_srt=group_word_srt(result)
            self.override_text.setPlainText(phrase_srt)
            if source:
                key=self._timeline_key(source); self.timeline_words[key]=result; self.timeline_overrides[key]=phrase_srt
            self.log.appendPlainText("词级时间轴已保留；编辑器已合并为逐句字幕，可修改每句话的时间和文字。")
        else: QMessageBox.critical(self,"时间轴提取失败",result)

    def _timeline_ended(self): self.timeline_worker=None; self.timeline_thread=None

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
        output = Path(self.output.text()); output.mkdir(parents=True, exist_ok=True)
        destination = str(output / f"配音_{len(list(output.glob('配音_*.mp3'))) + 1:03d}.mp3")
        self.tts_generate.setEnabled(False); self.tts_generate.setText("正在生成…")
        self.tts_thread = QThread(self)
        self.tts_worker = TtsWorker(self.tts_callable, text, self.tts_service.currentText(), self.tts_voice.currentText().strip(), destination)
        self.tts_worker.moveToThread(self.tts_thread); self.tts_thread.started.connect(self.tts_worker.run)
        self.tts_worker.finished.connect(self._tts_done); self.tts_worker.finished.connect(self.tts_thread.quit)
        self.tts_thread.finished.connect(self._tts_ended); self.tts_thread.finished.connect(self.tts_thread.deleteLater)
        self.tts_thread.start()

    def tts_service_changed(self, service):
        if not hasattr(self, "tts_voice"): return
        current = self.tts_voice.currentText()
        if service == "微软文字转语音":
            self._load_microsoft_voices()
        else:
            self.tts_voice.clear()
            self.tts_voice.addItem("请粘贴 ElevenLabs Voice ID")
        if current and ((service == "微软文字转语音" and current.endswith("Neural")) or (service != "微软文字转语音" and not current.endswith("Neural"))):
            self.tts_voice.setCurrentText(current)

    def _tts_done(self, ok, result):
        self.tts_generate.setEnabled(True); self.tts_generate.setText("生成并加入音频")
        if ok:
            self._add(self.audios, [result], AUDIO_EXTENSIONS)
            matches=self.audios.findItems(result,Qt.MatchFlag.MatchExactly)
            if matches: self.audios.setCurrentItem(matches[0])
            self.log.appendPlainText(f"文案配音已生成：{result}\n正在按实际语音自动提取词级时间轴…")
            QTimer.singleShot(0,self.extract_timeline)
        else:
            QMessageBox.critical(self, "文字转语音失败", result)

    def _tts_ended(self):
        self.tts_worker = None; self.tts_thread = None

    def pick_color(self, button):
        current = re.search(r"#[0-9A-Fa-f]{6}", button.text()); color = QColorDialog.getColor(QColor(current.group() if current else "#ffffff"), self)
        if color.isValid():
            button.setText(re.sub(r"#[0-9A-Fa-f]{6}", color.name().upper(), button.text())); self.update_style_preview()

    def apply_preset(self, name):
        preset = PRESETS[name]
        for button in self.preset_buttons: button.setChecked(button.text() == name)
        self.text_color.setText(f"文字 {preset['text']}"); self.outline_color.setText(f"描边 {preset['outline']}"); self.highlight_color.setText(f"跟读背景 {preset['highlight']}")
        self.outline_width.setValue(preset["outline_width"])
        if "font" in preset: self.font.setCurrentText(preset["font"])
        if "font_size" in preset: self.font_size.setValue(preset["font_size"])
        if "line_length" in preset: self.line_length.setValue(preset["line_length"])
        if "margin_v" in preset: self.margin_v.setValue(preset["margin_v"])
        if hasattr(self, "preview_position_slider"):
            self.preview_position_slider.blockSignals(True)
            self.preview_position_slider.setValue(self.margin_v.value())
            self.preview_position_slider.blockSignals(False)
            self.preview_position_value.setText(f"距底部 {self.margin_v.value()}")
        self.update_style_preview()

    def update_style_preview(self):
        if not hasattr(self, "style_preview"): return
        text = self._hex(self.text_color); highlight = self._hex(self.highlight_color)
        self.style_preview.setText(
            f'<span style="color:{text};font-size:20px;font-weight:700;">让每一句文案 </span>'
            f'<span style="background:{highlight};color:#ffffff;font-size:24px;font-weight:800;padding:5px;">跟随朗读跳动</span>')

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
        self.worker.finished.connect(self.done); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.ended); self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False); self.stop.setEnabled(True); self.thread.start()

    def cancel(self):
        if self.worker: self.worker.cancel()

    def done(self, ok, message):
        self.start.setEnabled(True); self.stop.setEnabled(False); self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(self, "动态文案" if ok else "生成失败", message)

    def ended(self): self.worker = None; self.thread = None
