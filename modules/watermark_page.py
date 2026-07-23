import json
import os
from io import BytesIO
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFontDatabase, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)
from .path_picker import default_output_path
from .path_picker import DropTableWidget, collect_files, load_subfolders
from .platform_utils import app_data_dir, media_tool_name


APP_DIR = app_data_dir() / "watermark_studio"
TEMPLATE_FILE = APP_DIR / "templates.json"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def bundled_path(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return Path(__file__).resolve().parent / name


def hidden_subprocess_kwargs():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


@dataclass
class Watermark:
    text: str = "示例水印"
    font_family: str = "Microsoft YaHei UI"
    font_size: int = 42
    font_color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: int = 0
    bg_color: str = "#000000"
    bg_enabled: bool = True
    rounded_bg: bool = True
    bg_opacity: int = 120
    opacity: int = 220
    position: str = "右下"
    margin_x: int = 36
    margin_y: int = 36
    x: int = 0
    y: int = 0
    padding: int = 12
    stroke_color: str = "#000000"
    stroke_width: int = 0


def ensure_app_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMPLATE_FILE.exists():
        default = {
            "默认右下角": [asdict(Watermark())],
            "顶部标题": [
                asdict(
                    Watermark(
                        text="品牌名称",
                        font_size=56,
                        position="顶部居中",
                        bg_color="#111827",
                        bg_opacity=150,
                    )
                )
            ],
            "双水印": [
                asdict(Watermark(text="主水印", position="右下")),
                asdict(
                    Watermark(
                        text="内部资料",
                        font_size=32,
                        font_color="#ffdf6e",
                        position="左上",
                        bg_opacity=90,
                    )
                ),
            ],
        }
        TEMPLATE_FILE.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")


def is_media(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS or path.suffix.lower() in IMAGE_EXTS


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def quote_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
        .replace("%", "\\%")
        .replace("\n", " ")
    )


def quote_font_path(value: str) -> str:
    path = str(Path(value).as_posix()).replace("\\", "/")
    path = path.replace(":", "\\:")
    return path.replace("'", "\\'")


def hex_to_rgba(hex_color: str, alpha: int):
    color = QColor(hex_color)
    return color.red(), color.green(), color.blue(), max(0, min(255, alpha))


def ffmpeg_color(hex_color: str, alpha: int) -> str:
    opacity = max(0, min(255, alpha)) / 255
    return f"{hex_color}@{opacity:.3f}"


def position_expr(mark: Watermark):
    mx = mark.margin_x
    my = mark.margin_y
    mapping = {
        "左上": (str(mx), str(my)),
        "顶部居中": ("(w-text_w)/2", str(my)),
        "右上": (f"w-text_w-{mx}", str(my)),
        "居中": ("(w-text_w)/2", "(h-text_h)/2"),
        "左下": (str(mx), f"h-text_h-{my}"),
        "底部居中": ("(w-text_w)/2", f"h-text_h-{my}"),
        "右下": (f"w-text_w-{mx}", f"h-text_h-{my}"),
        "自定义": (str(mark.x), str(mark.y)),
    }
    return mapping.get(mark.position, mapping["右下"])


def image_position(mark: Watermark, image_size, text_size):
    w, h = image_size
    tw, th = text_size
    mx, my = mark.margin_x, mark.margin_y
    mapping = {
        "左上": (mx, my),
        "顶部居中": ((w - tw) // 2, my),
        "右上": (w - tw - mx, my),
        "居中": ((w - tw) // 2, (h - th) // 2),
        "左下": (mx, h - th - my),
        "底部居中": ((w - tw) // 2, h - th - my),
        "右下": (w - tw - mx, h - th - my),
        "自定义": (mark.x, mark.y),
    }
    return mapping.get(mark.position, mapping["右下"])


def find_font_file(family: str):
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
    ]
    known = {
        "microsoftyaheiui": ["msyh.ttc", "msyhbd.ttc", "PingFang.ttc", "Hiragino Sans GB.ttc"],
        "microsoftyahei": ["msyh.ttc", "msyhbd.ttc", "PingFang.ttc", "Hiragino Sans GB.ttc"],
        "simsun": ["simsun.ttc"],
        "simhei": ["simhei.ttf"],
        "arial": ["arial.ttf"],
    }
    family_norm = family.lower().replace(" ", "")
    for folder in candidates:
        if not folder.exists():
            continue
        for name in known.get(family_norm, []):
            item = folder / name
            if item.exists():
                return str(item)
        for pattern in ("*.ttf", "*.ttc", "*.otf"):
            for item in folder.glob(pattern):
                name = item.stem.lower().replace(" ", "")
                if family_norm in name or name in family_norm:
                    return str(item)
    for folder in candidates:
        for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
            item = folder / name
            if item.exists():
                return str(item)
    for fallback in (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
    ):
        if fallback.exists(): return str(fallback)
    return None


def find_executable(name: str):
    # 优先检查本地bundled文件夹中的ffmpeg
    bundled = bundled_path(media_tool_name(name))
    if bundled.exists():
        return str(bundled)
    
    # 其次检查系统环境变量中的ffmpeg
    found = shutil.which(name)
    if found:
        return found
    
    # 最后检查ffmpeg同级目录中是否有其他工具
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).with_name(media_tool_name(name))
        if sibling.exists():
            return str(sibling)
    return None


class RenderWorker(QThread):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(int, int)

    def __init__(self, files, output_dir, watermarks, encoder, keep_audio, parent=None):
        super().__init__(parent)
        self.files = files
        self.output_dir = Path(output_dir)
        self.watermarks = watermarks
        self.encoder = encoder
        self.keep_audio = keep_audio
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        ok = 0
        failed = 0
        self.output_dir.mkdir(parents=True, exist_ok=True)
        total = len(self.files)
        for index, file_path in enumerate(self.files, 1):
            if self._stop:
                self.log.emit("任务已停止。")
                break
            path = Path(file_path)
            self.progress.emit(index - 1, total, path.name)
            try:
                if is_image(path):
                    self.render_image(path)
                elif is_video(path):
                    self.render_video(path)
                else:
                    self.log.emit(f"跳过不支持的文件：{path}")
                    continue
                ok += 1
                self.log.emit(f"完成：{path.name}")
            except Exception as exc:
                failed += 1
                self.log.emit(f"失败：{path.name} - {exc}")
        self.progress.emit(total, total, "完成")
        self.finished.emit(ok, failed)

    def output_path(self, src: Path):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        suffix = src.suffix.lower()
        stem = src.stem + "_watermarked"
        if is_image(src):
            suffix = ".png" if suffix in {".png", ".webp"} else suffix
        return self.output_dir / f"{stem}{suffix}"

    def render_image(self, src: Path):
        image = Image.open(src).convert("RGBA")
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for mark in self.watermarks:
            font_path = find_font_file(mark.font_family)
            font = ImageFont.truetype(font_path, mark.font_size) if font_path else ImageFont.load_default()
            bbox = draw.textbbox((0, 0), mark.text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            box_w = text_w + mark.padding * 2
            box_h = text_h + mark.padding * 2
            x, y = image_position(mark, image.size, (box_w, box_h))
            if mark.bg_enabled:
                draw.rounded_rectangle(
                    [x, y, x + box_w, y + box_h],
                    radius=6,
                    fill=hex_to_rgba(mark.bg_color, mark.bg_opacity),
                )
            draw.text(
                (x + mark.padding, y + mark.padding - bbox[1]),
                mark.text,
                font=font,
                fill=hex_to_rgba(mark.font_color, mark.opacity),
            )
        result = Image.alpha_composite(image, layer)
        out = self.output_path(src)
        if out.suffix.lower() in {".jpg", ".jpeg"}:
            result.convert("RGB").save(out, quality=96, subsampling=0)
        else:
            result.save(out)

    def render_video(self, src: Path):
        ffmpeg = find_executable("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 FFmpeg")
        vf = self.build_filter()
        out = self.output_path(src)
        cmd = [ffmpeg, "-y", "-i", str(src)]
        if vf and vf != "null":
            cmd += ["-vf", vf]
        if self.encoder == "自动/高质量":
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
        elif self.encoder == "Apple VideoToolbox":
            cmd += ["-c:v", "h264_videotoolbox", "-b:v", "8M"]
        elif self.encoder == "NVIDIA NVENC":
            cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "18", "-b:v", "0"]
        elif self.encoder == "AMD AMF":
            cmd += ["-c:v", "h264_amf", "-quality", "quality", "-qp_i", "18", "-qp_p", "20"]
        elif self.encoder == "Intel QSV":
            cmd += ["-c:v", "h264_qsv", "-global_quality", "18"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
        if self.keep_audio:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-an"]
        cmd += ["-map_metadata", "0", str(out)]
        self.log.emit("执行：" + " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", **hidden_subprocess_kwargs())
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "FFmpeg 渲染失败"
            if proc.stderr:
                # 提取更明确的错误信息
                lines = proc.stderr.strip().splitlines()
                message = next((line for line in reversed(lines) if line and not line.startswith("ffmpeg version") and not line.startswith("  ")), message)
            self.log.emit("FFmpeg 错误：" + message)
            raise RuntimeError(message)

    def build_filter(self):
        filters = []
        for mark in self.watermarks:
            if not mark.text:
                continue
            x_expr, y_expr = position_expr(mark)
            font_path = find_font_file(mark.font_family)
            parts = [
                f"text='{quote_drawtext(mark.text)}'",
                f"fontsize={mark.font_size}",
                f"fontcolor={ffmpeg_color(mark.font_color, mark.opacity)}",
                f"x={x_expr}",
                f"y={y_expr}",
            ]
            if font_path:
                parts.append(f"fontfile='{quote_font_path(font_path)}'")
            if mark.stroke_width > 0:
                parts += [
                    f"borderw={mark.stroke_width}",
                    f"bordercolor={ffmpeg_color(mark.stroke_color, 255)}",
                ]
            if mark.bg_enabled:
                parts += [
                    "box=1",
                    f"boxcolor={ffmpeg_color(mark.bg_color, mark.bg_opacity)}",
                    f"boxborderw={mark.padding}",
                ]
            filters.append("drawtext=" + ":".join(parts))
        return ",".join(filters) if filters else "null"


class InstallWorker(QThread):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, missing, parent=None):
        super().__init__(parent)
        self.missing = missing

    def run(self):
        commands = []
        if "PySide6" in self.missing or "Pillow" in self.missing:
            commands.append([sys.executable, "-m", "pip", "install", "-U", "PySide6", "Pillow"])
        if not find_executable("ffmpeg"):
            if sys.platform == "darwin" and shutil.which("brew"):
                commands.append([shutil.which("brew"), "install", "ffmpeg"])
            elif shutil.which("winget"):
                commands.append(
                    [
                        "winget",
                        "install",
                        "-e",
                        "--id",
                        "Gyan.FFmpeg",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ]
                )
            else:
                self.log.emit("未找到可用的组件安装器。请使用顶部“设置与组件”恢复 FFmpeg。")
                self.finished.emit(False, "FFmpeg 需要通过“设置与组件”恢复")
                return
        if not commands:
            self.log.emit("没有发现缺失依赖。")
            self.finished.emit(True, "依赖已经齐全")
            return
        ok = True
        message = "安装完成"
        for cmd in commands:
            try:
                self.log.emit("执行：" + " ".join(cmd))
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", **hidden_subprocess_kwargs())
                if proc.stdout.strip():
                    self.log.emit(proc.stdout[-2000:])
                if proc.stderr.strip():
                    self.log.emit(proc.stderr[-2000:])
                if proc.returncode != 0:
                    ok = False
                    message = f"安装命令失败：{' '.join(cmd)}"
            except Exception as exc:
                ok = False
                message = str(exc)
                self.log.emit("安装异常：" + str(exc))
        self.finished.emit(ok, message)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ensure_app_dir()
        self.setWindowTitle("水印工坊 - 视频/图片批量水印")
        icon_path = bundled_path("logo.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1240, 780)
        self.files = []
        self.watermarks = []
        self.templates = self.load_templates()
        self.render_worker = None
        self.install_worker = None
        self.missing_deps = []
        self.build_ui()
        self.preview_update_timer = QTimer(self)
        self.preview_update_timer.setSingleShot(True)
        self.preview_update_timer.setInterval(220)
        self.preview_update_timer.timeout.connect(self.refresh_preview)
        self._preview_source = None
        self._preview_source_path = None
        self._preview_source_mtime = None
        self.apply_theme()
        self.add_watermark(Watermark())
        self.refresh_templates()
        self.check_environment()

    def build_ui(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize())
        self.addToolBar(toolbar)
        act_add_files = QAction("添加文件", self)
        act_add_folder = QAction("添加文件夹", self)
        act_render = QAction("开始渲染", self)
        act_stop = QAction("停止", self)
        toolbar.addAction(act_add_files)
        toolbar.addAction(act_add_folder)
        toolbar.addSeparator()
        toolbar.addAction(act_render)
        toolbar.addAction(act_stop)
        act_add_files.triggered.connect(self.add_files)
        act_add_folder.triggered.connect(self.add_folder)
        act_render.triggered.connect(self.start_render)
        act_stop.triggered.connect(self.stop_render)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.build_left_panel())
        splitter.addWidget(self.build_right_panel())
        splitter.setSizes([420, 820])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

    def build_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        env_group = QGroupBox("运行环境")
        env_group.setObjectName("card")
        env_layout = QGridLayout(env_group)
        env_layout.setSpacing(6)
        env_layout.setContentsMargins(12, 12, 12, 12)
        self.env_label = QLabel("正在检查...")
        self.install_btn = QPushButton("自动安装缺失依赖")
        self.install_btn.clicked.connect(self.install_deps)
        env_layout.addWidget(self.env_label, 0, 0)
        env_layout.addWidget(self.install_btn, 0, 1)

        source_group = QGroupBox("素材队列")
        source_group.setObjectName("card")
        source_layout = QVBoxLayout(source_group)
        source_layout.setSpacing(6)
        source_layout.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        row.setSpacing(4)
        add_files = QPushButton("添加文件")
        add_folder = QPushButton("添加文件夹")
        clear_files = QPushButton("清空")
        add_files.clicked.connect(self.add_files)
        add_folder.clicked.connect(self.add_folder)
        clear_files.clicked.connect(self.clear_files)
        row.addWidget(add_files)
        row.addWidget(add_folder)
        row.addWidget(clear_files)
        self.file_table = DropTableWidget(0, 3); self.file_table.paths_dropped.connect(self.add_dropped_paths)
        self.file_table.setHorizontalHeaderLabels(["文件名", "类型", "路径"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        source_layout.addLayout(row)
        source_layout.addWidget(self.file_table)

        output_group = QGroupBox("输出设置")
        output_group.setObjectName("card")
        output_layout = QFormLayout(output_group)
        output_layout.setSpacing(6)
        output_layout.setContentsMargins(12, 12, 12, 12)
        out_row = QHBoxLayout()
        out_row.setSpacing(4)
        self.output_edit = QLineEdit(str(default_output_path("watermark_outputs")))
        out_btn = QPushButton("选择")
        out_btn.clicked.connect(self.choose_output)
        out_row.addWidget(self.output_edit)
        out_row.addWidget(out_btn)
        self.encoder_combo = QComboBox()
        if sys.platform == "darwin":
            self.encoder_combo.addItems(["自动/高质量", "Apple VideoToolbox", "CPU x264"])
        else:
            self.encoder_combo.addItems(["自动/高质量", "NVIDIA NVENC", "AMD AMF", "Intel QSV", "CPU x264"])
        self.audio_check = QCheckBox("保留原音频")
        self.audio_check.setChecked(True)
        output_layout.addRow("输出文件夹", out_row)
        output_layout.addRow("视频编码", self.encoder_combo)
        output_layout.addRow("", self.audio_check)

        layout.addWidget(env_group)
        env_group.setVisible(False)
        layout.addWidget(source_group, 1)
        layout.addWidget(output_group)
        return panel

    def build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        preview_group = QGroupBox("预览窗口")
        preview_group.setObjectName("card")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(6)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(6)
        ratio_row.addWidget(QLabel("预览比例"))
        self.preview_ratio_combo = QComboBox()
        self.preview_ratio_combo.addItems(["源比例", "9:16", "16:9", "1:1"])
        self.preview_ratio_combo.setCurrentText("源比例")
        self.preview_ratio_combo.currentTextChanged.connect(self.schedule_preview_refresh)
        ratio_row.addWidget(self.preview_ratio_combo)
        self.preview_grid_check = QCheckBox("应用网格")
        self.preview_grid_check.setChecked(True)
        self.preview_grid_check.setToolTip("勾选后在预览上显示对齐网格，取消则不显示")
        self.preview_grid_check.stateChanged.connect(self.schedule_preview_refresh)
        ratio_row.addWidget(self.preview_grid_check)
        ratio_row.addStretch()
        preview_layout.addLayout(ratio_row)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("添加素材\n自动显示预览")
        self.preview_label.setStyleSheet(
            "background: #050812; border: 1px solid #283445; border-radius: 8px;"
        )
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setMaximumHeight(300)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout.addWidget(self.preview_label, 1)

        list_row = QHBoxLayout()
        list_row.setSpacing(8)

        template_group = QGroupBox("模板")
        template_group.setObjectName("card")
        template_layout = QVBoxLayout(template_group)
        template_layout.setSpacing(6)
        template_layout.setContentsMargins(12, 12, 12, 12)
        self.template_list = QListWidget()
        self.template_list.itemDoubleClicked.connect(self.apply_template)
        self.template_list.setMaximumHeight(82)
        template_buttons = QHBoxLayout()
        template_buttons.setSpacing(6)
        save_tpl = QPushButton("保存")
        load_tpl = QPushButton("应用")
        delete_tpl = QPushButton("删除")
        save_tpl.clicked.connect(self.save_template)
        load_tpl.clicked.connect(lambda: self.apply_template(self.template_list.currentItem()))
        delete_tpl.clicked.connect(self.delete_template)
        template_buttons.addWidget(save_tpl)
        template_buttons.addWidget(load_tpl)
        template_buttons.addWidget(delete_tpl)
        template_layout.addWidget(self.template_list)
        template_layout.addLayout(template_buttons)

        mark_group = QGroupBox("水印列表")
        mark_group.setObjectName("card")
        mark_layout = QVBoxLayout(mark_group)
        mark_layout.setSpacing(6)
        mark_layout.setContentsMargins(12, 12, 12, 12)
        self.mark_list = QListWidget()
        self.mark_list.currentRowChanged.connect(self.load_mark_to_editor)
        self.mark_list.setMaximumHeight(82)
        mark_buttons = QHBoxLayout()
        mark_buttons.setSpacing(6)
        add_mark = QPushButton("新增")
        del_mark = QPushButton("删除")
        add_mark.clicked.connect(lambda: self.add_watermark(Watermark(text=f"水印 {len(self.watermarks)+1}")))
        del_mark.clicked.connect(self.delete_watermark)
        mark_buttons.addWidget(add_mark)
        mark_buttons.addWidget(del_mark)
        mark_layout.addWidget(self.mark_list)
        mark_layout.addLayout(mark_buttons)

        list_row.addWidget(template_group, 1)
        list_row.addWidget(mark_group, 1)

        editor_group = QGroupBox("水印属性")
        editor_group.setObjectName("card")
        editor_layout = QFormLayout(editor_group)
        editor_layout.setSpacing(6)
        editor_layout.setContentsMargins(12, 12, 12, 12)
        self.text_edit = QLineEdit()
        self.font_combo = QComboBox()
        self.font_combo.addItems(QFontDatabase.families())
        self.font_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 260)
        self.size_spin.setValue(42)
        self.font_color_btn = QPushButton()
        self.stroke_color_btn = QPushButton()
        self.bg_color_btn = QPushButton()
        self.bg_check = QCheckBox("水印背景")
        self.bg_check.setChecked(True)
        self.rounded_check = QCheckBox("圆角背景")
        self.rounded_check.setChecked(True)
        self.opacity_slider = self.make_slider(0, 255, 220)
        self.bg_opacity_slider = self.make_slider(0, 255, 120)
        self.stroke_width_spin = QSpinBox()
        self.stroke_width_spin.setRange(0, 20)
        self.stroke_width_spin.setValue(0)
        self.position_combo = QComboBox()
        self.position_combo.addItems(["左上", "顶部居中", "右上", "居中", "左下", "底部居中", "右下", "自定义"])
        self.position_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.position_combo.setMaximumWidth(100)
        self.position_combo.currentTextChanged.connect(self.update_custom_coords_visibility)
        self.margin_x_spin = QSpinBox()
        self.margin_x_spin.setRange(0, 2000)
        self.margin_x_spin.setValue(36)
        self.margin_y_spin = QSpinBox()
        self.margin_y_spin.setRange(0, 2000)
        self.margin_y_spin.setValue(36)
        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 10000)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 10000)
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 100)
        self.padding_spin.setValue(12)
        self.font_color_btn.clicked.connect(lambda: self.pick_color(self.font_color_btn))
        self.stroke_color_btn.clicked.connect(lambda: self.pick_color(self.stroke_color_btn))
        self.bg_color_btn.clicked.connect(lambda: self.pick_color(self.bg_color_btn))

        self.font_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.size_spin.setMaximumWidth(72)
        self.margin_x_spin.setMaximumWidth(72)
        self.margin_y_spin.setMaximumWidth(72)
        self.x_spin.setMaximumWidth(72)
        self.y_spin.setMaximumWidth(72)
        self.padding_spin.setMaximumWidth(72)
        self.font_color_btn.setFixedSize(26, 26)
        self.stroke_color_btn.setFixedSize(26, 26)
        self.bg_color_btn.setFixedSize(26, 26)
        self.font_color_btn.setCursor(Qt.PointingHandCursor)
        self.stroke_color_btn.setCursor(Qt.PointingHandCursor)
        self.bg_color_btn.setCursor(Qt.PointingHandCursor)
        self.stroke_width_spin.setMaximumWidth(72)
        self.opacity_slider.setMaximumWidth(180)
        self.bg_opacity_slider.setMaximumWidth(180)

        row_font = QHBoxLayout()
        row_font.setSpacing(4)
        row_font.addWidget(self.font_combo)
        row_font.addWidget(self.size_spin)
        row_font.addWidget(self.font_color_btn)

        row_style = QHBoxLayout()
        row_style.setSpacing(4)
        row_style.addWidget(QLabel("描边宽度"))
        row_style.addWidget(self.stroke_width_spin)
        row_style.addWidget(QLabel("描边颜色"))
        row_style.addWidget(self.stroke_color_btn)
        row_style.addWidget(QLabel("水印背景"))
        row_style.addWidget(self.bg_color_btn)
        row_style.addWidget(self.bg_check)
        self.rounded_check.setText("圆角")
        row_style.addWidget(self.rounded_check)

        row_alpha = QHBoxLayout()
        row_alpha.setSpacing(4)
        row_alpha.addWidget(QLabel("文字透明度"))
        row_alpha.addWidget(self.opacity_slider)
        row_alpha.addWidget(QLabel("背景透明度"))
        row_alpha.addWidget(self.bg_opacity_slider)

        row_position = QHBoxLayout()
        row_position.setSpacing(4)
        row_position.addWidget(self.position_combo)
        row_position.addWidget(QLabel("左右"))
        row_position.addWidget(self.margin_x_spin)
        row_position.addWidget(QLabel("上下"))
        row_position.addWidget(self.margin_y_spin)
        row_position.addWidget(QLabel("内距"))
        row_position.addWidget(self.padding_spin)

        row_custom = QHBoxLayout()
        row_custom.setSpacing(4)
        row_custom.addWidget(QLabel("X"))
        row_custom.addWidget(self.x_spin)
        row_custom.addWidget(QLabel("Y"))
        row_custom.addWidget(self.y_spin)

        self.custom_coords_widget = QWidget()
        self.custom_coords_widget.setLayout(row_custom)
        self.custom_coords_widget.setVisible(False)

        self.font_color_btn.setToolTip("字体颜色")
        self.stroke_color_btn.setToolTip("描边颜色")
        self.bg_color_btn.setToolTip("背景颜色")
        self.margin_x_spin.setToolTip("水平边距")
        self.margin_y_spin.setToolTip("垂直边距")
        self.padding_spin.setToolTip("文字内距")
        self.x_spin.setToolTip("自定义X坐标")
        self.y_spin.setToolTip("自定义Y坐标")

        self.update_color_button(self.font_color_btn, "#ffffff")
        self.update_color_button(self.stroke_color_btn, "#000000")
        self.update_color_button(self.bg_color_btn, "#000000")

        editor_layout.addRow("文字", self.text_edit)
        editor_layout.addRow("字体", row_font)
        editor_layout.addRow("描边/背景", row_style)
        editor_layout.addRow("透明度", row_alpha)
        editor_layout.addRow("位置", row_position)
        editor_layout.addRow(self.custom_coords_widget)

        for widget in [
            self.text_edit,
            self.font_combo,
            self.size_spin,
            self.bg_check,
            self.rounded_check,
            self.opacity_slider,
            self.bg_opacity_slider,
            self.stroke_width_spin,
            self.position_combo,
            self.margin_x_spin,
            self.margin_y_spin,
            self.x_spin,
            self.y_spin,
            self.padding_spin,
        ]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self.update_current_mark)
            if hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self.update_current_mark)
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self.update_current_mark)
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self.update_current_mark)

        editor_scroll = QScrollArea()
        editor_scroll.setWidget(editor_group)
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setMinimumHeight(190)
        editor_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        log_group = QGroupBox("日志")
        log_group.setObjectName("card")
        log_layout = QVBoxLayout(log_group)
        log_layout.setSpacing(6)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_label = QLabel("进度")
        log_label.setStyleSheet("font-weight: 600; color: #a5f3fc;")
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("等待渲染...")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.progress)
        log_layout.addWidget(self.log)

        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setSpacing(8)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.addLayout(list_row)
        settings_layout.addWidget(editor_scroll, 2)

        log_panel = QWidget()
        log_panel_layout = QVBoxLayout(log_panel)
        log_panel_layout.setSpacing(8)
        log_panel_layout.setContentsMargins(0, 0, 0, 0)
        log_panel_layout.addWidget(log_group, 1)

        bottom_splitter = QSplitter(Qt.Horizontal)
        bottom_splitter.addWidget(settings_panel)
        bottom_splitter.addWidget(log_panel)
        bottom_splitter.setSizes([700, 360])
        bottom_splitter.setChildrenCollapsible(False)

        layout.addWidget(preview_group, 4)
        layout.addWidget(bottom_splitter, 6)
        return panel

    def make_slider(self, minimum, maximum, value):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        return slider

    def update_custom_coords_visibility(self, text):
        visible = text == "自定义"
        if hasattr(self, "custom_coords_widget"):
            self.custom_coords_widget.setVisible(visible)

    def apply_theme(self):
        self.setStyleSheet("")

    def load_templates(self):
        ensure_app_dir()
        return json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))

    def save_templates_file(self):
        TEMPLATE_FILE.write_text(json.dumps(self.templates, ensure_ascii=False, indent=2), encoding="utf-8")

    def refresh_templates(self):
        self.template_list.clear()
        for name in self.templates:
            self.template_list.addItem(name)

    def check_environment(self):
        ffmpeg_ok = bool(find_executable("ffmpeg"))
        ffprobe_ok = bool(find_executable("ffprobe"))
        items = []
        items.append(("FFmpeg", ffmpeg_ok))
        items.append(("PySide6", True))
        items.append(("Pillow", True))
        missing = [name for name, ok in items if not ok]
        self.missing_deps = missing
        if missing:
            self.env_label.setText("缺失：" + "、".join(missing))
            self.install_btn.setEnabled(True)
        elif not ffprobe_ok:
            self.env_label.setText("运行环境可用：FFmpeg 正常；FFprobe 未找到（当前渲染不受影响）")
            self.install_btn.setEnabled(True)
        else:
            self.env_label.setText("运行环境正常：FFmpeg / FFprobe / GUI / 图片库")
            self.install_btn.setEnabled(True)

    def _invalidate_preview_source_cache(self):
        self._preview_source = None
        self._preview_source_path = None
        self._preview_source_mtime = None

    def schedule_preview_refresh(self, immediate=False, *args):
        if immediate:
            self.preview_update_timer.stop()
            self.refresh_preview()
        else:
            self.preview_update_timer.start()

    def install_deps(self):
        if self.install_worker and self.install_worker.isRunning():
            QMessageBox.information(self, "正在安装", "依赖安装任务正在运行，请稍等。")
            return
        self.check_environment()
        if not self.missing_deps:
            self.append_log("依赖检查完成：当前没有缺失项。")
            QMessageBox.information(self, "依赖已齐全", "当前电脑已经满足运行条件，不需要安装。")
            return
        self.append_log("开始安装缺失依赖：" + "、".join(self.missing_deps))
        self.env_label.setText("正在安装：" + "、".join(self.missing_deps))
        self.install_btn.setEnabled(False)
        self.install_btn.setText("安装中...")
        self.install_worker = InstallWorker(list(self.missing_deps))
        self.install_worker.log.connect(self.append_log)
        self.install_worker.finished.connect(self.on_install_finished)
        self.install_worker.start()

    def on_install_finished(self, ok, message):
        self.install_btn.setEnabled(True)
        self.install_btn.setText("自动安装缺失依赖")
        self.check_environment()
        self.append_log(message)
        if ok and not self.missing_deps:
            QMessageBox.information(self, "安装完成", "依赖安装完成，运行环境正常。")
        elif ok:
            QMessageBox.warning(self, "仍有缺失", "安装已执行，但仍检测到缺失项：" + "、".join(self.missing_deps))
        else:
            QMessageBox.warning(self, "安装失败", message)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择视频或图片",
            str(Path.home()),
            "媒体文件 (*.mp4 *.mov *.mkv *.avi *.wmv *.webm *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff)",
        )
        self.add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", str(Path.home()))
        if folder:
            self.add_dropped_paths([folder])

    def add_dropped_paths(self, paths):
        self.add_paths(collect_files(paths, predicate=is_media))



    def add_paths(self, paths):
        seen = set(self.files)
        for path in paths:
            p = str(Path(path))
            if p not in seen and is_media(Path(p)):
                self.files.append(p)
                seen.add(p)
        self.refresh_file_table()
        self._invalidate_preview_source_cache()
        self.schedule_preview_refresh()

    def refresh_file_table(self):
        self.file_table.setRowCount(len(self.files))
        for row, file_path in enumerate(self.files):
            p = Path(file_path)
            kind = "视频" if is_video(p) else "图片"
            self.file_table.setItem(row, 0, QTableWidgetItem(p.name))
            self.file_table.setItem(row, 1, QTableWidgetItem(kind))
            self.file_table.setItem(row, 2, QTableWidgetItem(str(p)))

    def clear_files(self):
        self.files.clear()
        self.refresh_file_table()
        self._invalidate_preview_source_cache()
        self.schedule_preview_refresh()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def add_watermark(self, mark):
        self.watermarks.append(mark)
        item = QListWidgetItem(mark.text or "未命名水印")
        self.mark_list.addItem(item)
        self.mark_list.setCurrentRow(len(self.watermarks) - 1)
        self.schedule_preview_refresh()

    def delete_watermark(self):
        row = self.mark_list.currentRow()
        if row < 0:
            return
        self.watermarks.pop(row)
        self.mark_list.takeItem(row)
        if self.watermarks:
            self.mark_list.setCurrentRow(min(row, len(self.watermarks) - 1))
        self.schedule_preview_refresh()

    def load_mark_to_editor(self, row):
        if row < 0 or row >= len(self.watermarks):
            return
        mark = self.watermarks[row]
        self.text_edit.blockSignals(True)
        self.font_combo.blockSignals(True)
        for widget in [
            self.size_spin,
            self.bg_check,
            self.rounded_check,
            self.opacity_slider,
            self.bg_opacity_slider,
            self.position_combo,
            self.margin_x_spin,
            self.margin_y_spin,
            self.x_spin,
            self.y_spin,
            self.padding_spin,
        ]:
            widget.blockSignals(True)
        self.text_edit.setText(mark.text)
        idx = self.font_combo.findText(mark.font_family)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.size_spin.setValue(mark.font_size)
        self.update_color_button(self.font_color_btn, mark.font_color)
        self.update_color_button(self.stroke_color_btn, getattr(mark, 'stroke_color', '#000000'))
        self.update_color_button(self.bg_color_btn, mark.bg_color)
        self.bg_check.setChecked(mark.bg_enabled)
        self.rounded_check.setChecked(getattr(mark, 'rounded_bg', True))
        self.opacity_slider.setValue(mark.opacity)
        self.bg_opacity_slider.setValue(mark.bg_opacity)
        self.stroke_width_spin.setValue(getattr(mark, 'stroke_width', 0))
        self.position_combo.setCurrentText(mark.position)
        self.margin_x_spin.setValue(mark.margin_x)
        self.margin_y_spin.setValue(mark.margin_y)
        self.x_spin.setValue(mark.x)
        self.y_spin.setValue(mark.y)
        self.padding_spin.setValue(mark.padding)
        self.text_edit.blockSignals(False)
        self.font_combo.blockSignals(False)
        for widget in [
            self.size_spin,
            self.bg_check,
            self.rounded_check,
            self.opacity_slider,
            self.bg_opacity_slider,
            self.position_combo,
            self.margin_x_spin,
            self.margin_y_spin,
            self.x_spin,
            self.y_spin,
            self.padding_spin,
        ]:
            widget.blockSignals(False)
        self.schedule_preview_refresh()

    def update_current_mark(self, *_):
        row = self.mark_list.currentRow()
        if row < 0 or row >= len(self.watermarks):
            return
        mark = self.watermarks[row]
        mark.text = self.text_edit.text()
        mark.font_family = self.font_combo.currentText()
        mark.font_size = self.size_spin.value()
        mark.font_color = self.font_color_btn.property("color") or "#ffffff"
        mark.bg_color = self.bg_color_btn.property("color") or "#000000"
        mark.bg_enabled = self.bg_check.isChecked()
        mark.rounded_bg = self.rounded_check.isChecked()
        mark.opacity = self.opacity_slider.value()
        mark.bg_opacity = self.bg_opacity_slider.value()
        mark.stroke_color = self.stroke_color_btn.property("color") or "#000000"
        mark.stroke_width = self.stroke_width_spin.value()
        mark.position = self.position_combo.currentText()
        mark.margin_x = self.margin_x_spin.value()
        mark.margin_y = self.margin_y_spin.value()
        mark.x = self.x_spin.value()
        mark.y = self.y_spin.value()
        mark.padding = self.padding_spin.value()
        item = self.mark_list.item(row)
        if item:
            item.setText(mark.text or "未命名水印")
        self.schedule_preview_refresh()

    def pick_color(self, button):
        current_color = button.property("color") or button.text() or "#ffffff"
        color = QColorDialog.getColor(QColor(current_color), self, "选择颜色")
        if color.isValid():
            self.update_color_button(button, color.name())
            self.update_current_mark()

    def update_color_button(self, button, color):
        button.setProperty("color", color)
        button.setText("")
        button.setStyleSheet(
            f"background: {color}; border: 1px solid #999; border-radius: 4px;"
        )

    def save_template(self):
        name, ok = QFileDialog.getSaveFileName(self, "保存模板为 JSON", str(APP_DIR / "template.json"), "JSON (*.json)")
        if ok and name:
            data = [asdict(mark) for mark in self.watermarks]
            Path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tpl_name = Path(name).stem
            self.templates[tpl_name] = data
            self.save_templates_file()
            self.refresh_templates()
            self.append_log(f"模板已保存：{tpl_name}")

    def apply_template(self, item):
        if not item:
            return
        data = self.templates.get(item.text())
        if not data:
            return
        self.watermarks = [Watermark(**mark) for mark in data]
        self.mark_list.clear()
        for mark in self.watermarks:
            self.mark_list.addItem(mark.text or "未命名水印")
        if self.watermarks:
            self.mark_list.setCurrentRow(0)
        self._invalidate_preview_source_cache()
        self.schedule_preview_refresh(immediate=True)

    def delete_template(self):
        item = self.template_list.currentItem()
        if not item:
            return
        self.templates.pop(item.text(), None)
        self.save_templates_file()
        self.refresh_templates()

    def get_preview_source(self):
        first_media = next((Path(p) for p in self.files if Path(p).exists()), None)
        if not first_media:
            return None
        current_mtime = first_media.stat().st_mtime if first_media.exists() else None
        if (
            self._preview_source is not None
            and self._preview_source_path == str(first_media)
            and self._preview_source_mtime == current_mtime
        ):
            return self._preview_source

        if is_image(first_media):
            try:
                image = Image.open(first_media).convert("RGBA")
                self._preview_source = image
                self._preview_source_path = str(first_media)
                self._preview_source_mtime = current_mtime
                return image
            except Exception:
                return None
        if is_video(first_media):
            ffmpeg = find_executable("ffmpeg")
            if not ffmpeg:
                return None
            try:
                cmd = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(first_media),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "pipe:1",
                ]
                proc = subprocess.run(cmd, capture_output=True, **hidden_subprocess_kwargs())
                if proc.returncode == 0 and proc.stdout:
                    image = Image.open(BytesIO(proc.stdout)).convert("RGBA")
                    self._preview_source = image
                    self._preview_source_path = str(first_media)
                    self._preview_source_mtime = current_mtime
                    return image
            except Exception:
                return None
        return None

    def get_media_resolution(self, file_path: Path):
        """获取媒体文件的实际分辨率"""
        if is_image(file_path):
            try:
                img = Image.open(file_path)
                return img.size
            except Exception:
                return (1920, 1080)
        elif is_video(file_path):
            # 使用 ffprobe 获取视频分辨率
            ffprobe = find_executable("ffprobe")
            if ffprobe:
                try:
                    cmd = [
                        ffprobe,
                        "-v", "error",
                        "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "csv=p=0",
                        str(file_path)
                    ]
                    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **hidden_subprocess_kwargs())
                    if proc.stdout.strip():
                        parts = proc.stdout.strip().split(',')
                        if len(parts) == 2:
                            w, h = int(parts[0]), int(parts[1])
                            return (w, h) if w > 0 and h > 0 else (1920, 1080)
                except Exception:
                    pass
            return (1920, 1080)
        return (1920, 1080)

    def get_preview_image(self):
        source = self.get_preview_source()
        return source.copy() if source is not None else None

    def draw_preview_grid(self, image):
        if not hasattr(self, "preview_grid_check") or not self.preview_grid_check.isChecked():
            return
        draw = ImageDraw.Draw(image)
        w, h = image.size
        color = (255, 255, 255, 64)
        for i in range(1, 3):
            x = int(w * i / 3)
            y = int(h * i / 3)
            draw.line([(x, 0), (x, h)], fill=color, width=1)
            draw.line([(0, y), (w, y)], fill=color, width=1)

    def make_preview_base(self):
        """根据预览比例生成预览画布"""
        ratio_text = "源比例"
        if hasattr(self, "preview_ratio_combo"):
            ratio_text = self.preview_ratio_combo.currentText()
        target_ratios = {"源比例": None, "9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0}
        target_ratio = target_ratios.get(ratio_text, None)

        first_file = next((Path(p) for p in self.files), None)
        if first_file and first_file.exists():
            orig_w, orig_h = self.get_media_resolution(first_file)
        else:
            orig_w, orig_h = 1920, 1080

        if target_ratio is None and orig_w > 0 and orig_h > 0:
            target_ratio = orig_w / orig_h
        if target_ratio is None:
            target_ratio = 9 / 16

        max_preview_w = 540
        max_preview_h = 380
        if target_ratio >= 1:
            preview_w = max_preview_w
            preview_h = min(max_preview_h, int(max_preview_w / target_ratio))
        else:
            preview_h = max_preview_h
            preview_w = min(max_preview_w, int(max_preview_h * target_ratio))
        preview_w = max(120, preview_w)
        preview_h = max(120, preview_h)

        base = Image.new("RGBA", (preview_w, preview_h), (12, 18, 30, 255))

        preview_image = self.get_preview_image()
        image_offset = (0, 0)
        image_scale = 1.0
        displayed_size = None
        if preview_image:
            try:
                preview_image = preview_image.copy()
                orig_size = preview_image.size
                preview_image.thumbnail((preview_w, preview_h), Image.Resampling.LANCZOS)
                displayed_size = preview_image.size
                image_offset = ((preview_w - preview_image.width) // 2, (preview_h - preview_image.height) // 2)
                if orig_size[0] > 0 and orig_size[1] > 0:
                    image_scale = preview_image.width / orig_size[0]
                base.alpha_composite(preview_image, image_offset)
            except Exception:
                preview_image = None
                displayed_size = None
        else:
            draw = ImageDraw.Draw(base)
            for y in range(preview_h):
                r = 12 + int(y / preview_h * 20)
                g = 18 + int(y / preview_h * 28)
                b = 30 + int(y / preview_h * 40)
                draw.line([(0, y), (preview_w, y)], fill=(r, g, b, 255))
            draw.rectangle([10, 10, preview_w - 10, preview_h - 10], outline=(55, 72, 95, 255), width=1)
            text = f"{orig_w}×{orig_h}"
            try:
                draw.text((preview_w // 2 - 20, preview_h // 2 - 8), text, fill=(135, 160, 185, 255))
            except Exception:
                pass

        self.draw_preview_grid(base)
        return base

    def refresh_preview(self):
        if not hasattr(self, "preview_label"):
            return
        try:
            base = self.make_preview_base()
            preview_image = self.get_preview_image()
            image_offset = (0, 0)
            image_scale = 1.0
            displayed_size = None
            if preview_image:
                try:
                    preview_image = preview_image.copy()
                    orig_size = preview_image.size
                    preview_image.thumbnail((base.width, base.height), Image.Resampling.LANCZOS)
                    displayed_size = preview_image.size
                    image_offset = ((base.width - preview_image.width) // 2, (base.height - preview_image.height) // 2)
                    if orig_size[0] > 0 and orig_size[1] > 0:
                        scale_x = preview_image.width / orig_size[0]
                        scale_y = preview_image.height / orig_size[1]
                        image_scale = min(scale_x, scale_y)
                except Exception:
                    preview_image = None
                    displayed_size = None
            layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            for mark in self.watermarks:
                if not mark.text:
                    continue
                font_path = find_font_file(mark.font_family)
                scaled_size = max(8, int(round(mark.font_size * image_scale))) if displayed_size else max(8, mark.font_size)
                scaled_padding = max(1, int(round(mark.padding * image_scale))) if displayed_size else mark.padding
                scaled_margin_x = int(round(mark.margin_x * image_scale)) if displayed_size else mark.margin_x
                scaled_margin_y = int(round(mark.margin_y * image_scale)) if displayed_size else mark.margin_y
                scaled_stroke = max(1, int(round(mark.stroke_width * image_scale))) if displayed_size and mark.stroke_width > 0 else mark.stroke_width
                try:
                    font = ImageFont.truetype(font_path, scaled_size) if font_path else ImageFont.load_default()
                except Exception:
                    font = ImageFont.load_default()
                bbox = draw.textbbox((0, 0), mark.text, font=font, stroke_width=scaled_stroke)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                box_w = text_w + scaled_padding * 2
                box_h = text_h + scaled_padding * 2
                if displayed_size:
                    temp_mark = Watermark(**asdict(mark))
                    temp_mark.margin_x = scaled_margin_x
                    temp_mark.margin_y = scaled_margin_y
                    temp_mark.padding = scaled_padding
                    temp_mark.x = int(round(mark.x * image_scale))
                    temp_mark.y = int(round(mark.y * image_scale))
                    x, y = image_position(temp_mark, displayed_size, (box_w, box_h))
                    x += image_offset[0]
                    y += image_offset[1]
                else:
                    x, y = image_position(mark, base.size, (box_w, box_h))
                x = max(0, min(base.width - box_w, x))
                y = max(0, min(base.height - box_h, y))
                if mark.bg_enabled:
                    if getattr(mark, 'rounded_bg', True):
                        radius = min(12, max(0, scaled_padding - scaled_stroke // 2))
                    else:
                        radius = 0
                    if radius > 0 and hasattr(draw, 'rounded_rectangle'):
                        draw.rounded_rectangle(
                            [x, y, x + box_w, y + box_h],
                            radius=radius,
                            fill=hex_to_rgba(mark.bg_color, mark.bg_opacity),
                        )
                    else:
                        draw.rectangle(
                            [x, y, x + box_w, y + box_h],
                            fill=hex_to_rgba(mark.bg_color, mark.bg_opacity),
                        )
                text_x = x + scaled_padding - bbox[0]
                text_y = y + scaled_padding - bbox[1]
                draw.text(
                    (text_x, text_y),
                    mark.text,
                    font=font,
                    fill=hex_to_rgba(mark.font_color, mark.opacity),
                    stroke_width=scaled_stroke,
                    stroke_fill=hex_to_rgba(mark.stroke_color, 255) if mark.stroke_width > 0 else None,
                )
            preview = Image.alpha_composite(base, layer).convert("RGB")
            buffer = BytesIO()
            preview.save(buffer, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue(), "PNG")
            scaled = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled)
        except Exception as exc:
            self.preview_label.setText(f"预览生成失败：{exc}")

    def start_render(self):
        self.update_current_mark()
        if not self.files:
            QMessageBox.warning(self, "缺少素材", "请先添加视频或图片。")
            return
        if not self.watermarks:
            QMessageBox.warning(self, "缺少水印", "请至少添加一条水印。")
            return
        out = self.output_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "缺少输出文件夹", "请选择输出文件夹。")
            return
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "正在渲染", "已有任务正在运行。")
            return
        self.progress.setValue(0)
        self.render_worker = RenderWorker(
            list(self.files),
            out,
            [Watermark(**asdict(mark)) for mark in self.watermarks],
            self.encoder_combo.currentText(),
            self.audio_check.isChecked(),
        )
        self.render_worker.progress.connect(self.on_progress)
        self.render_worker.log.connect(self.append_log)
        self.render_worker.finished.connect(self.on_finished)
        self.append_log("开始批量渲染...")
        self.render_worker.start()

    def stop_render(self):
        if self.render_worker and self.render_worker.isRunning():
            self.render_worker.stop()
            self.append_log("正在请求停止任务...")

    def on_progress(self, current, total, name):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        self.progress.setFormat(f"{current}/{total} {name}")

    def on_finished(self, ok, failed):
        self.append_log(f"渲染结束：成功 {ok}，失败 {failed}")
        QMessageBox.information(self, "完成", f"渲染结束：成功 {ok}，失败 {failed}")

    def append_log(self, text):
        if text:
            self.log.appendPlainText(str(text).strip())
            self.log.moveCursor(QTextCursor.End)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_preview_refresh(immediate=True)


def main():
    app = QApplication(sys.argv)
    icon_path = bundled_path("logo.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
