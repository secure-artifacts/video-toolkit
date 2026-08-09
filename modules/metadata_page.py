from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path

from PIL import ExifTags, Image
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .path_picker import (AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
                          DropListWidget, collect_files, default_output_path)
from .settings_page import find_media_tool, hidden_kwargs

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
_META_STRIP = [
    "-map_metadata", "-1", "-map_metadata:s", "-1", "-map_metadata:p", "-1",
    "-map_metadata:c", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
    "-metadata", "creation_time=", "-metadata", "date=", "-metadata", "location=",
    "-metadata", "title=", "-metadata", "artist=", "-metadata", "author=",
    "-metadata", "copyright=", "-metadata", "comment=", "-metadata", "description=",
    "-metadata", "encoder=",
]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复的输出文件名：{path.name}")


def _prepare_logo_rgba(logo_path: Path, opacity: float = 1.0) -> Image.Image:
    """Load logo as RGBA and apply opacity; soft-knockout near-black/white solid backgrounds."""
    with Image.open(logo_path) as im:
        logo = im.convert("RGBA")
    pixels = logo.load()
    w, h = logo.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < 8:
                continue
            if max(r, g, b) <= 18 or min(r, g, b) >= 248:
                if abs(r - g) < 12 and abs(g - b) < 12:
                    pixels[x, y] = (r, g, b, 0)
    if opacity < 0.999:
        r, g, b, a = logo.split()
        a = a.point(lambda v: int(v * max(0.0, min(1.0, opacity))))
        logo = Image.merge("RGBA", (r, g, b, a))
    return logo


def _corner_xy(position: str, base_w: int, base_h: int, mark_w: int, mark_h: int, margin: int):
    m = max(0, int(margin))
    mapping = {
        "左上": (m, m),
        "顶部居中": ((base_w - mark_w) // 2, m),
        "右上": (base_w - mark_w - m, m),
        "居中": ((base_w - mark_w) // 2, (base_h - mark_h) // 2),
        "左下": (m, base_h - mark_h - m),
        "底部居中": ((base_w - mark_w) // 2, base_h - mark_h - m),
        "右下": (base_w - mark_w - m, base_h - mark_h - m),
    }
    return mapping.get(position, mapping["右下"])


def _overlay_logo_on_image(base: Image.Image, logo_path: Path, cfg: dict) -> Image.Image:
    canvas = base.convert("RGBA")
    opacity = max(0.05, min(1.0, float(cfg.get("opacity", 100)) / 100.0))
    logo = _prepare_logo_rgba(logo_path, opacity)
    mode = str(cfg.get("mode") or "小 Logo 角标")
    if "全屏" in mode:
        logo = logo.resize(canvas.size, Image.Resampling.LANCZOS)
        x, y = 0, 0
    else:
        width_pct = max(4.0, min(80.0, float(cfg.get("width_pct", 18))))
        target_w = max(16, int(canvas.width * width_pct / 100.0))
        scale = target_w / max(1, logo.width)
        target_h = max(16, int(logo.height * scale))
        logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
        x, y = _corner_xy(
            str(cfg.get("position") or "右下"),
            canvas.width, canvas.height, logo.width, logo.height,
            int(cfg.get("margin", 28) or 28),
        )
    canvas.alpha_composite(logo, (max(0, x), max(0, y)))
    return canvas


class MetadataWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    file_done = Signal(str, str)

    def __init__(self, files, output, keep_structure=True, preserve_time=False, watermark=None):
        super().__init__()
        self.files = [Path(value) for value in files]
        self.output = Path(output)
        self.keep_structure = keep_structure
        self.preserve_time = preserve_time
        self.watermark = watermark if isinstance(watermark, dict) else None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def _wm_enabled(self) -> bool:
        if not self.watermark or not self.watermark.get("enabled"):
            return False
        path = Path(str(self.watermark.get("path") or ""))
        return path.is_file()

    def _image(self, source: Path, destination: Path):
        with Image.open(source) as image:
            clean = Image.new(image.mode, image.size)
            clean.putdata(list(image.getdata()))
            if self._wm_enabled():
                self.log.emit(f"  · 叠加水印：{Path(self.watermark['path']).name}")
                composed = _overlay_logo_on_image(
                    clean.convert("RGBA"), Path(self.watermark["path"]), self.watermark)
                if source.suffix.lower() in {".jpg", ".jpeg"}:
                    clean = composed.convert("RGB")
                else:
                    clean = composed
            options = {}
            suffix = source.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                if clean.mode not in {"RGB", "L"}:
                    clean = clean.convert("RGB")
                options = {"quality": 95, "optimize": True, "subsampling": 0}
            elif suffix == ".png":
                if clean.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                    clean = clean.convert("RGBA")
                options = {"optimize": True}
            clean.save(destination, **options)

    def _av(self, source: Path, destination: Path):
        ffmpeg = find_media_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 FFmpeg，请先到“设置与组件”一键安装。")
        if source.suffix.lower() in AUDIO_EXTENSIONS or not self._wm_enabled():
            self._av_copy_clean(ffmpeg, source, destination)
            return
        self._av_with_watermark(ffmpeg, source, destination)

    def _av_copy_clean(self, ffmpeg, source: Path, destination: Path):
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                   "-map", "0:V?", "-map", "0:a?", "-map", "0:s?",
                   *_META_STRIP, "-c", "copy", str(destination)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())

        if result.returncode:
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                       "-map", "0:V?", "-map", "0:a?",
                       *_META_STRIP, "-c", "copy", str(destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())

        if result.returncode:
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                       "-map", "0:V?", "-map", "0:a?", "-map_metadata", "-1",
                       "-map_metadata:s", "-1", "-map_chapters", "-1", "-metadata", "creation_time=",
                       "-metadata", "location=", "-metadata", "title=", "-metadata", "artist=",
                       "-metadata", "copyright=", "-metadata", "comment=", "-c", "copy", str(destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())

        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "FFmpeg 清除元数据失败")

    def _av_with_watermark(self, ffmpeg, source: Path, destination: Path):
        """重编码画面 + 烧录水印 + 清除元数据。"""
        logo = Path(self.watermark["path"])
        self.log.emit(f"  · 清理元数据并烧录水印（需重编码画面）：{logo.name}")
        mode = str(self.watermark.get("mode") or "小 Logo 角标")
        opacity = max(0.05, min(1.0, float(self.watermark.get("opacity", 100)) / 100.0))
        width_pct = max(0.04, min(0.80, float(self.watermark.get("width_pct", 18)) / 100.0))
        margin = max(0, int(self.watermark.get("margin", 28) or 28))
        position = str(self.watermark.get("position") or "右下")
        pos_map = {
            "左上": (str(margin), str(margin)),
            "顶部居中": ("(main_w-overlay_w)/2", str(margin)),
            "右上": (f"main_w-overlay_w-{margin}", str(margin)),
            "居中": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
            "左下": (str(margin), f"main_h-overlay_h-{margin}"),
            "底部居中": ("(main_w-overlay_w)/2", f"main_h-overlay_h-{margin}"),
            "右下": (f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"),
        }
        ox, oy = pos_map.get(position, pos_map["右下"])

        cache = self.output / ".watermark_cache"
        cache.mkdir(parents=True, exist_ok=True)
        prepared = cache / f"{logo.stem}_o{int(opacity * 100)}.png"
        try:
            _prepare_logo_rgba(logo, opacity).save(prepared, "PNG")
            logo_input = prepared
        except Exception:
            logo_input = logo

        if "全屏" in mode:
            fc = (
                f"[0:v]setpts=PTS-STARTPTS,format=yuv420p[base];"
                f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[wmraw];"
                f"[wmraw][base]scale2ref=w=iw:h=ih[wm][base2];"
                f"[base2][wm]overlay=0:0:format=auto:eof_action=repeat[vout]"
            )
        else:
            fc = (
                f"[0:v]setpts=PTS-STARTPTS,format=yuv420p[base];"
                f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[wmraw];"
                f"[wmraw][base]scale2ref=w=main_w*{width_pct:.4f}:h=ow/mdar[wm][base2];"
                f"[base2][wm]overlay={ox}:{oy}:format=auto:eof_action=repeat[vout]"
            )

        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-loop", "1", "-i", str(logo_input),
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            *_META_STRIP,
            "-shortest", "-movflags", "+faststart",
            str(destination),
        ]
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode or not destination.is_file() or destination.stat().st_size < 1024:
            raise RuntimeError(
                (result.stderr or "").strip() or "FFmpeg 水印合成失败（请换透明 PNG Logo 重试）")

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            common = None
            if self.keep_structure and self.files:
                try:
                    common = Path(os.path.commonpath([str(path.parent) for path in self.files]))
                except ValueError:
                    common = None
            completed = 0
            wm_note = "（清理+水印）" if self._wm_enabled() else ""
            for source in self.files:
                if self.cancelled:
                    raise RuntimeError("任务已停止；已完成的文件仍保留在输出目录。")
                relative_parent = Path()
                if common:
                    try:
                        relative_parent = source.parent.relative_to(common)
                    except ValueError:
                        pass
                destination_dir = self.output / relative_parent
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = unique_path(destination_dir / source.name)
                self.log.emit(f"正在处理{wm_note}：{source.name}")
                if source.suffix.lower() in IMAGE_EXTENSIONS:
                    self._image(source, destination)
                else:
                    self._av(source, destination)
                if self.preserve_time:
                    stat = source.stat()
                    os.utime(destination, (stat.st_atime, stat.st_mtime))
                completed += 1
                self.progress.emit(round(completed / len(self.files) * 100))
                self.log.emit(f"完成：{destination}")
                self.file_done.emit(str(source), str(destination))
            msg = f"已处理 {completed} 个素材（清除元数据"
            if self._wm_enabled():
                msg += " + 水印合成"
            msg += f"）。\n{self.output}"
            self.finished.emit(True, msg)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class MetadataPage(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.files = []
        self.cleaned_files = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)
        title = QLabel("批量清除素材元数据")
        title.setObjectName("heading")
        root.addWidget(title)
        note = QLabel(
            "隐私清理会强制删除 GPS、拍摄时间、设备/序列号、作者版权、唯一标识、标题描述、软件来源、"
            "章节、附件和封面图；图片重建像素并清除 EXIF/XMP/IPTC。原文件不会被修改。"
            "可选「水印合成」：清理同时把 Logo 烧进画面（视频会重编码）。"
            "注意：文件名以及画面、声音中直接出现的隐私内容需要另行处理。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#94a3b8;")
        root.addWidget(note)
        split = QSplitter()
        source = QGroupBox("素材队列（支持拖入文件或文件夹）")
        source_layout = QVBoxLayout(source)
        self.list = DropListWidget()
        self.list.paths_dropped.connect(self.add_paths)
        self.list.currentTextChanged.connect(self.inspect_selected)
        source_layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        add_files = QPushButton("添加文件")
        add_files.clicked.connect(self.choose_files)
        add_folder = QPushButton("添加文件夹")
        add_folder.clicked.connect(self.choose_folder)
        remove = QPushButton("移除选中")
        remove.clicked.connect(lambda: [self.list.takeItem(i.row()) for i in reversed(self.list.selectedIndexes())])
        clear = QPushButton("清空")
        clear.clicked.connect(self.list.clear)
        for button in (add_files, add_folder, remove, clear):
            buttons.addWidget(button)
        source_layout.addLayout(buttons)

        options = QGroupBox("输出与执行")
        options_layout = QVBoxLayout(options)
        form = QFormLayout()
        self.output = QLineEdit(str(default_output_path("metadata_clean_outputs")))
        out_row = QHBoxLayout()
        out_row.addWidget(self.output)
        choose = QPushButton("选择…")
        choose.clicked.connect(self.choose_output)
        out_row.addWidget(choose)
        form.addRow("输出目录", out_row)
        self.keep_structure = QCheckBox("保留输入文件夹层级")
        self.keep_structure.setChecked(True)
        self.preserve_time = QCheckBox("保留文件系统修改时间（隐私清理模式下禁用）")
        self.preserve_time.setChecked(False)
        self.preserve_time.setEnabled(False)
        self.preserve_time.setToolTip("拍摄/修改时间可能用于推断活动轨迹，因此隐私清理固定使用新的输出时间。")
        form.addRow("目录结构", self.keep_structure)
        form.addRow("文件时间", self.preserve_time)
        options_layout.addLayout(form)

        # —— 水印合成（可选）——
        wm_box = QGroupBox("水印合成（可选）")
        wm_layout = QFormLayout(wm_box)
        self.wm_enable = QCheckBox("清理时同时烧录水印")
        self.wm_enable.setToolTip("开启后图片用 PIL 叠图；视频重编码并 overlay Logo，同时清除元数据。")
        self.wm_path = QLineEdit()
        self.wm_path.setPlaceholderText("选择 PNG / JPG Logo（推荐透明 PNG）")
        wm_path_row = QHBoxLayout()
        wm_path_row.addWidget(self.wm_path)
        wm_browse = QPushButton("选择…")
        wm_browse.clicked.connect(self.choose_watermark)
        wm_path_row.addWidget(wm_browse)
        self.wm_mode = QComboBox()
        self.wm_mode.addItems(["小 Logo 角标", "9:16 全屏覆盖"])
        self.wm_position = QComboBox()
        self.wm_position.addItems(["右下", "右上", "左下", "左上", "顶部居中", "底部居中", "居中"])
        self.wm_width = QSpinBox()
        self.wm_width.setRange(4, 80)
        self.wm_width.setValue(18)
        self.wm_width.setSuffix(" %")
        self.wm_width.setToolTip("角标模式：相对画面宽度的 Logo 宽度")
        self.wm_opacity = QSpinBox()
        self.wm_opacity.setRange(5, 100)
        self.wm_opacity.setValue(90)
        self.wm_opacity.setSuffix(" %")
        self.wm_margin = QSpinBox()
        self.wm_margin.setRange(0, 200)
        self.wm_margin.setValue(28)
        self.wm_margin.setSuffix(" px")
        wm_layout.addRow(self.wm_enable)
        wm_layout.addRow("Logo 文件", wm_path_row)
        wm_layout.addRow("模式", self.wm_mode)
        wm_layout.addRow("位置", self.wm_position)
        wm_layout.addRow("宽度", self.wm_width)
        wm_layout.addRow("不透明度", self.wm_opacity)
        wm_layout.addRow("边距", self.wm_margin)

        def _sync_wm_enabled(on: bool):
            for w in (self.wm_path, wm_browse, self.wm_mode, self.wm_position,
                      self.wm_width, self.wm_opacity, self.wm_margin):
                w.setEnabled(bool(on))
            self.wm_position.setEnabled(bool(on) and "全屏" not in self.wm_mode.currentText())
            self.wm_width.setEnabled(bool(on) and "全屏" not in self.wm_mode.currentText())
            self.wm_margin.setEnabled(bool(on) and "全屏" not in self.wm_mode.currentText())

        self.wm_enable.toggled.connect(_sync_wm_enabled)
        self.wm_mode.currentTextChanged.connect(
            lambda _t: _sync_wm_enabled(self.wm_enable.isChecked()))
        _sync_wm_enabled(False)
        options_layout.addWidget(wm_box)

        inspection = QGroupBox("元数据检查（选中左侧素材自动读取）")
        inspection_layout = QVBoxLayout(inspection)
        self.inspect_status = QLabel("请选择一个素材查看清理前信息；完成清理后会自动显示前后对比。")
        self.inspect_status.setWordWrap(True)
        self.inspect_status.setStyleSheet("color:#7dd3fc;")
        inspection_layout.addWidget(self.inspect_status)
        compare = QHBoxLayout()
        before_box = QVBoxLayout()
        after_box = QVBoxLayout()
        before_box.addWidget(QLabel("清理前 · 原素材"))
        after_box.addWidget(QLabel("清理后 · 输出成品"))
        self.before_metadata = QPlainTextEdit()
        self.before_metadata.setReadOnly(True)
        self.before_metadata.setMinimumHeight(190)
        self.after_metadata = QPlainTextEdit()
        self.after_metadata.setReadOnly(True)
        self.after_metadata.setMinimumHeight(190)
        metadata_style = "font-family:Consolas,'Microsoft YaHei UI';font-size:12px;"
        self.before_metadata.setStyleSheet(metadata_style)
        self.after_metadata.setStyleSheet(metadata_style)
        before_box.addWidget(self.before_metadata)
        after_box.addWidget(self.after_metadata)
        compare.addLayout(before_box, 1)
        compare.addLayout(after_box, 1)
        inspection_layout.addLayout(compare)
        options_layout.addWidget(inspection)
        self.progress = QProgressBar()
        options_layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        options_layout.addWidget(self.log, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        self.stop = QPushButton("停止")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        self.start = QPushButton("开始批量清除")
        self.start.setObjectName("primary")
        self.start.clicked.connect(self.run)
        actions.addWidget(self.stop)
        actions.addWidget(self.start)
        options_layout.addLayout(actions)
        split.addWidget(source)
        split.addWidget(options)
        split.setSizes([560, 720])
        root.addWidget(split, 1)

    def add_paths(self, paths):
        found = collect_files(paths, MEDIA_EXTENSIONS)
        existing = {self.list.item(i).text() for i in range(self.list.count())}
        for path in found:
            if path not in existing:
                self.list.addItem(path)
                existing.add(path)
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    @staticmethod
    def _privacy_risks(tag_items):
        rules = [
            ("位置/GPS（必须清理）", ("gps", "location", "latitude", "longitude", "altitude", "iso6709", "geotag")),
            ("拍摄与创建时间（必须清理）", ("datetime", "creation_time", "creationdate", "createdate", "modifydate", "timestamp", "date_time")),
            ("设备与序列号（必须清理）", ("make", "model", "serial", "cameraowner", "lensmake", "lensmodel", "hostcomputer", "device")),
            ("作者/版权/联系方式（必须清理）", ("artist", "author", "copyright", "creator", "owner", "byline", "credit", "contact", "email", "publisher", "rights")),
            ("唯一标识符（必须清理）", ("documentid", "instanceid", "uniqueid", "uuid", "identifier", "assetid", "contentid", "mediaid")),
            ("标题/描述/关键词（建议清理）", ("title", "comment", "description", "subject", "keyword", "category", "caption", "synopsis", "lyrics")),
            ("软件与处理来源（建议清理）", ("software", "encoder", "encoded_by", "application", "processingsoftware", "tool")),
            ("人物/人脸区域信息（必须清理）", ("personinimage", "mwg-rs", "regioninfo", "faceregion", "people")),
        ]
        found = {}
        for key, value in tag_items:
            haystack = (str(key) + " " + str(value)[:300]).casefold().replace(" ", "").replace("_", "").replace("-", "")
            for category, patterns in rules:
                if any(pattern.replace("_", "").replace("-", "") in haystack for pattern in patterns):
                    found.setdefault(category, []).append(str(key))
                    break
        return found

    def _append_risk_scan(self, lines, tag_items):
        risks = self._privacy_risks(tag_items)
        lines += ["", "【隐私风险扫描】"]
        if risks:
            for category, keys in risks.items():
                lines.append(f"⚠ {category}：{', '.join(dict.fromkeys(keys))}")
        else:
            lines.append("✓ 未检测到已知的高风险隐私字段")
        return sum(len(values) for values in risks.values())

    def _metadata_details(self, value):
        path = Path(value)
        if not path.is_file():
            return "文件不存在。", 0
        lines = [f"文件：{path.name}", f"大小：{path.stat().st_size:,} 字节", f"扩展名：{path.suffix.lower()}"]
        metadata_count = 0
        tag_items = []
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                with Image.open(path) as image:
                    lines += [f"格式：{image.format}", f"尺寸：{image.width} × {image.height}",
                              f"色彩模式：{image.mode}", "", "【EXIF / 图片元数据】"]
                    exif = image.getexif()
                    for key, val in exif.items():
                        name = ExifTags.TAGS.get(key, str(key))
                        lines.append(f"{name}: {str(val)[:500]}")
                        tag_items.append((name, val))
                        metadata_count += 1
                    for key, val in image.info.items():
                        if key.lower() not in {"exif"}:
                            lines.append(f"{key}: {str(val)[:500]}")
                            tag_items.append((key, val))
                            metadata_count += 1
                    if metadata_count == 0:
                        lines.append("未检测到 EXIF/XMP 等附加信息")
            except Exception as exc:
                lines.append(f"读取图片信息失败：{exc}")
            self._append_risk_scan(lines, tag_items)
            return "\n".join(lines), metadata_count
        ffprobe = find_media_tool("ffprobe")
        if not ffprobe:
            return "\n".join(lines + ["", "未找到 FFprobe，无法读取音视频元数据。"]), 0
        command = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            return "\n".join(lines + ["", result.stderr.strip() or "FFprobe 读取失败"]), 0
        payload = json.loads(result.stdout or "{}")
        fmt = payload.get("format", {})
        lines += [f"容器：{fmt.get('format_long_name') or fmt.get('format_name', '')}",
                  f"时长：{fmt.get('duration', '')} 秒", f"码率：{fmt.get('bit_rate', '')}", "", "【容器元数据】"]
        tags = fmt.get("tags", {}) or {}
        for key, val in tags.items():
            lines.append(f"{key}: {val}")
            tag_items.append((key, val))
            metadata_count += 1
        if not tags:
            lines.append("未检测到容器附加信息")
        for index, stream in enumerate(payload.get("streams", []), 1):
            lines += ["", f"【轨道 {index} · {stream.get('codec_type', 'unknown')}】",
                      f"编码：{stream.get('codec_long_name') or stream.get('codec_name', '')}"]
            for key in ("profile", "width", "height", "r_frame_rate", "sample_rate", "channels",
                        "channel_layout", "bit_rate"):
                if stream.get(key) not in (None, ""):
                    lines.append(f"{key}: {stream[key]}")
            stream_tags = stream.get("tags", {}) or {}
            for key, val in stream_tags.items():
                lines.append(f"tag.{key}: {val}")
                tag_items.append((key, val))
                metadata_count += 1
        self._append_risk_scan(lines, tag_items)
        return "\n".join(lines), metadata_count

    def inspect_selected(self, path):
        if not path:
            self.before_metadata.clear()
            self.after_metadata.clear()
            return
        before, before_count = self._metadata_details(path)
        self.before_metadata.setPlainText(before)
        cleaned = self.cleaned_files.get(str(Path(path)))
        if cleaned and Path(cleaned).is_file():
            after, after_count = self._metadata_details(cleaned)
            self.after_metadata.setPlainText(after)
            removed = max(0, before_count - after_count)
            self.inspect_status.setText(
                f"检测完成：清理前 {before_count} 项附加信息，清理后 {after_count} 项，已减少 {removed} 项。"
                "编码、尺寸、时长等技术参数会保留。")
            self.inspect_status.setStyleSheet("color:#86efac;")
        else:
            self.after_metadata.setPlainText("尚未生成对应的清理成品。")
            self.inspect_status.setText(
                f"原素材检测到 {before_count} 项附加信息；执行清理后将在右侧自动显示结果。")
            self.inspect_status.setStyleSheet("color:#7dd3fc;")

    def _file_cleaned(self, source, destination):
        self.cleaned_files[str(Path(source))] = destination
        if self.list.currentItem() and self.list.currentItem().text() == source:
            self.inspect_selected(source)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择素材", "",
            "媒体文件 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.flac *.aac "
            "*.ogg *.opus *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff)")
        self.add_paths(files)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if folder:
            self.add_paths([folder])

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if folder:
            self.output.setText(folder)

    def choose_watermark(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择水印图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if path:
            self.wm_path.setText(path)
            self.wm_enable.setChecked(True)

    def _watermark_cfg(self):
        if not self.wm_enable.isChecked():
            return None
        path = self.wm_path.text().strip()
        if not path or not Path(path).is_file():
            return None
        return {
            "enabled": True,
            "path": path,
            "mode": self.wm_mode.currentText(),
            "position": self.wm_position.currentText(),
            "width_pct": int(self.wm_width.value()),
            "opacity": int(self.wm_opacity.value()),
            "margin": int(self.wm_margin.value()),
        }

    def run(self):
        files = [self.list.item(i).text() for i in range(self.list.count())]
        if not files:
            QMessageBox.information(self, "没有素材", "请先添加视频、音频或图片。")
            return
        if self.wm_enable.isChecked() and not (self.wm_path.text().strip() and Path(self.wm_path.text().strip()).is_file()):
            QMessageBox.warning(self, "水印", "已勾选水印合成，请先选择有效的 Logo 图片。")
            return
        if getattr(self, "thread", None):
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前清理结束。")
                    return
            except RuntimeError:
                self.thread = None
        self.log.clear()
        self.progress.setValue(0)
        self.thread = QThread(self)
        self.worker = MetadataWorker(
            files, self.output.text(), self.keep_structure.isChecked(),
            self.preserve_time.isChecked(), watermark=self._watermark_cfg())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.file_done.connect(self._file_cleaned)
        self.worker.finished.connect(self.done)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._ended)
        self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.thread.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()

    def done(self, ok, message):
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(
            self, "元数据清除" if ok else "处理失败", message)

    def _ended(self):
        self.worker = None
        self.thread = None
