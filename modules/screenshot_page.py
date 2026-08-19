import sys
import os
import cv2
import json
import time
import subprocess
import urllib.request
import ctypes
import logging
import tempfile
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFileDialog, QProgressBar, QMessageBox,
    QFrame, QFormLayout, QGroupBox, QScrollArea, QSplitter, QCheckBox, QSpinBox,
    QTabWidget,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QIcon
from .path_picker import DropTextEdit, VIDEO_EXTENSIONS, collect_files, load_subfolders
from .platform_utils import app_data_dir, open_local_path

# --- 日誌路徑與配置 ---
# 這裡記錄所有：執行錯誤、沒截取成功的記錄、失敗的記錄
LOG_DIR = str(app_data_dir() / "logs")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    test_path = os.path.join(LOG_DIR, ".write_test")
    with open(test_path, "a", encoding="utf-8"):
        pass
    os.remove(test_path)
except OSError:
    LOG_DIR = os.path.join(tempfile.gettempdir(), "VideoToolkit", "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
# Include the PID so a preview left open cannot lock the next preview's log file.
LOG_FILE = os.path.join(LOG_DIR, f"execution_detailed_{os.getpid()}.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp",
    ".heic", ".heif", ".avif",
}
IMAGE_OUTPUT_FORMATS = {
    "PNG（无损）": ("PNG", ".png"),
    "WebP（无损）": ("WEBP", ".webp"),
    "TIFF（无损）": ("TIFF", ".tiff"),
    "BMP（无损）": ("BMP", ".bmp"),
    "HEIF / HEIC（无损优先）": ("HEIF", ".heic"),
    "AVIF（无损优先）": ("AVIF", ".avif"),
    "JPEG（最高质量，有损格式）": ("JPEG", ".jpg"),
}

# --- 核心處理線程 ---
class ProcessThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal()
    folder_ready_signal = Signal(str)

    def __init__(self, urls, count, interval, folder, prefix):
        super().__init__()
        self.urls = urls
        self.count = count
        self.interval = interval
        self.folder = folder
        self.prefix = prefix
        self.history_path = str(app_data_dir() / "screenshot_history.json")

    def load_history(self):
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
            except: return set()
        return set()

    def save_history(self, url):
        history = list(self.load_history())
        if url not in history:
            history.append(url)
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f)

    def run(self):
        proxy = urllib.request.getproxies().get('https')
        history = self.load_history()
        total_tasks = len([u for u in self.urls if str(u).strip()])
        logging.info(f"=== 启动任务: 处理 {total_tasks} 个来源 ===")
        self.log_signal.emit("════════ 批量截图开始 ════════")
        self.log_signal.emit(
            f"任务数：{total_tasks}  |  每条截图 {self.count} 张  |  间隔 {self.interval}s"
        )
        self.log_signal.emit(f"输出目录：{self.folder}  |  前缀：{self.prefix}")
        if proxy:
            self.log_signal.emit(f"系统代理：{proxy}")

        need_ytdlp = any(not os.path.isfile(item.strip()) for item in self.urls if item.strip())
        if need_ytdlp:
            from .ytdlp_utils import ytdlp_status
            ok, detail = ytdlp_status()
            if not ok:
                msg = "环境错误：未安装 yt-dlp，网络链接无法解析。请到「设置与组件」一键更新 yt-dlp。"
                self.log_signal.emit(f"❌ {msg}")
                logging.error(msg)
                self.finished_signal.emit()
                return
            self.log_signal.emit(f"yt-dlp：{detail}（网络链接解析依赖此组件）")

        ok_n, skip_n, fail_n = 0, 0, 0
        for index, url in enumerate(self.urls):
            url = url.strip()
            if not url:
                continue
            is_local = os.path.isfile(url)
            task_no = index + 1
            label = os.path.basename(url) if is_local else (url[:80] + ("…" if len(url) > 80 else ""))

            # 查重跳过
            if not is_local and url in history:
                skip_n += 1
                self.log_signal.emit(f"⚠️ [{task_no}/{total_tasks}] 跳过已处理链接：{label}")
                logging.info(f"跳过已处理 URL: {url}")
                self.progress_signal.emit(int(task_no / max(1, total_tasks) * 100))
                continue

            temp_video = None
            try:
                self.log_signal.emit(
                    f"▶ [{task_no}/{total_tasks}] "
                    f"{'本地视频' if is_local else '网络视频'}：{label}"
                )
                logging.info(f"开始处理: {url}")
                if is_local:
                    temp_video = url
                    self.log_signal.emit(f"  路径：{url}")
                else:
                    self.log_signal.emit("  正在用 yt-dlp 解析并下载…")
                    from .ytdlp_utils import download_media
                    outtmpl = f'temp_{int(time.time())}_{task_no}.%(ext)s'
                    temp_video, info = download_media(
                        url,
                        outtmpl,
                        format_spec="mp4/best",
                        proxy=proxy,
                        log=self.log_signal.emit,
                    )
                    title = (info or {}).get("title") or ""
                    duration = (info or {}).get("duration")
                    if title:
                        self.log_signal.emit(f"  标题：{title}")
                    if duration:
                        self.log_signal.emit(f"  时长：{float(duration):.1f}s")
                    self.log_signal.emit(f"  已下载临时文件：{os.path.basename(temp_video)}")

                # 截图目录
                f_idx = 1
                while True:
                    out_path = os.path.join(self.folder, f"{self.prefix}_{f_idx:03d}")
                    if not os.path.exists(out_path):
                        break
                    f_idx += 1

                os.makedirs(out_path, exist_ok=True)
                cap = cv2.VideoCapture(temp_video)
                if not cap.isOpened():
                    raise Exception("无法打开视频（解码失败或路径无效）")

                fps = cap.get(cv2.CAP_PROP_FPS) or 0
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                vid_dur = (frame_count / fps) if fps > 1 else 0
                self.log_signal.emit(
                    f"  画面：{width}×{height}"
                    + (f"  |  时长约 {vid_dur:.1f}s" if vid_dur else "")
                    + (f"  |  {fps:.1f}fps" if fps else "")
                )
                self.log_signal.emit(
                    f"  开始截图：共 {self.count} 张，间隔 {self.interval}s → {out_path}"
                )

                sc = 0
                for i in range(self.count):
                    pos_ms = i * self.interval * 1000
                    cap.set(cv2.CAP_PROP_POS_MSEC, pos_ms)
                    ret, frame = cap.read()
                    if ret:
                        shot_name = f"shot_{i+1:03d}.jpg"
                        cv2.imwrite(os.path.join(out_path, shot_name), frame)
                        sc += 1
                        # 每张或每 5 张汇报一次，避免刷屏又不太干
                        if self.count <= 8 or (i + 1) % max(1, self.count // 5) == 0 or i == 0 or i + 1 == self.count:
                            self.log_signal.emit(
                                f"    ✓ {shot_name} @ {pos_ms/1000:.1f}s"
                            )
                    else:
                        self.log_signal.emit(
                            f"    ✗ 第 {i+1} 张失败（时间点 {pos_ms/1000:.1f}s 无画面）"
                        )
                cap.release()

                if sc > 0:
                    if not is_local:
                        self.save_history(url)
                    ok_n += 1
                    self.log_signal.emit(
                        f"✅ [{task_no}/{total_tasks}] 完成：{sc}/{self.count} 张 → {out_path}"
                    )
                    logging.info(f"成功截取 {sc} 张。链接: {url} → {out_path}")
                    self.folder_ready_signal.emit(out_path)
                else:
                    raise Exception("视频已就绪但未能截取任何画面（时间点可能超出片长）")

            except Exception as e:
                fail_n += 1
                error_log = f"任务 {task_no} 失败: {str(e)} | URL: {url}"
                self.log_signal.emit(f"❌ [{task_no}/{total_tasks}] 失败：{e}")
                self.log_signal.emit(f"   来源：{label}")
                logging.error(error_log)

            finally:
                if temp_video and not is_local and os.path.exists(temp_video):
                    try:
                        os.remove(temp_video)
                        self.log_signal.emit("  已清理临时下载文件")
                    except Exception:
                        pass
                self.progress_signal.emit(int(task_no / max(1, total_tasks) * 100))

        self.log_signal.emit("════════ 批量截图结束 ════════")
        self.log_signal.emit(
            f"成功 {ok_n}  |  跳过 {skip_n}  |  失败 {fail_n}  |  输出根目录：{self.folder}"
        )
        logging.info("=== 所有任务执行完毕 ===")
        self.finished_signal.emit()


class ImageConvertThread(QThread):
    """批量图片格式转换；无损格式保持像素，JPEG 明确按最高质量输出。"""
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(int, int, str)

    def __init__(self, paths, output_dir, format_label, quality=100,
                 preserve_metadata=True, overwrite=False):
        super().__init__()
        self.paths = [str(Path(p)) for p in paths]
        self.output_dir = str(output_dir)
        self.format_label = str(format_label)
        self.quality = max(1, min(100, int(quality)))
        self.preserve_metadata = bool(preserve_metadata)
        self.overwrite = bool(overwrite)

    @staticmethod
    def _register_heif():
        try:
            from pillow_heif import register_heif_opener, register_avif_opener
            register_heif_opener()
            try:
                register_avif_opener()
            except Exception:
                pass
            return True, ""
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _flatten_alpha(image):
        from PIL import Image
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")

    def _destination(self, src: Path, extension: str) -> Path:
        out = Path(self.output_dir) / f"{src.stem}{extension}"
        if self.overwrite or not out.exists():
            return out
        index = 2
        while True:
            candidate = out.with_name(f"{out.stem}_{index}{out.suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    @staticmethod
    def _clean_error(exc) -> str:
        """去掉 Qt QPainter 刷屏警告，只保留可读原因。"""
        text = str(exc or "").strip() or "未知错误"
        # 偶发：其它线程/预览的 QPainter 警告被拼进异常文本
        lines = [
            ln.strip() for ln in text.replace("\r", "\n").split("\n")
            if ln.strip() and "QPainter::" not in ln
        ]
        cleaned = " ".join(lines) if lines else text
        if "QPainter" in cleaned and not lines:
            return (
                "内部绘图冲突（通常可重试）。若持续失败，请关掉预览窗口后再转换，"
                "或改导出为 PNG。"
            )
        return cleaned[:500]

    def run(self):
        try:
            from PIL import Image, ImageOps
        except Exception as exc:
            self.log_signal.emit(f"❌ Pillow 不可用：{exc}")
            self.finished_signal.emit(0, len(self.paths), self.output_dir)
            return
        fmt, extension = IMAGE_OUTPUT_FORMATS.get(
            self.format_label, IMAGE_OUTPUT_FORMATS["PNG（无损）"]
        )
        heif_ok, heif_error = self._register_heif()
        if (fmt in {"HEIF", "AVIF"} or any(Path(p).suffix.lower() in {".heic", ".heif", ".avif"}
                                            for p in self.paths)) and not heif_ok:
            self.log_signal.emit(
                "❌ HEIF/HEIC/AVIF 编解码组件不可用。请安装或更新 pillow-heif。"
                + (f" 详情：{heif_error}" if heif_error else "")
            )
            self.finished_signal.emit(0, len(self.paths), self.output_dir)
            return
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        ok = fail = 0
        first_error = ""
        self.log_signal.emit("════════ 图片格式转换开始 ════════")
        self.log_signal.emit(f"输入 {len(self.paths)} 张 → {self.format_label} → {self.output_dir}")
        for index, path_text in enumerate(self.paths, 1):
            src = Path(path_text)
            try:
                # 仅用 Pillow 读写，不经 QImage/QPainter，避免与主界面预览抢画笔
                with Image.open(src) as opened:
                    opened.load()
                    image = ImageOps.exif_transpose(opened)
                    # 部分 HEIC/CMYK 需先转标准模式
                    if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                    metadata = {}
                    if self.preserve_metadata:
                        exif = opened.info.get("exif")
                        icc = opened.info.get("icc_profile")
                        if exif:
                            metadata["exif"] = exif
                        if icc:
                            metadata["icc_profile"] = icc
                    save_options = dict(metadata)
                    if fmt == "PNG":
                        if image.mode == "P":
                            image = image.convert("RGBA")
                        save_options.update(optimize=True, compress_level=9)
                    elif fmt == "WEBP":
                        if image.mode == "P":
                            image = image.convert("RGBA")
                        save_options.update(lossless=True, quality=100, method=6)
                    elif fmt == "TIFF":
                        save_options.update(compression="tiff_lzw")
                    elif fmt == "JPEG":
                        image = self._flatten_alpha(image)
                        save_options.update(quality=self.quality, subsampling=0, optimize=True)
                    elif fmt == "BMP":
                        image = self._flatten_alpha(image)
                    elif fmt in {"HEIF", "AVIF"}:
                        if image.mode not in ("RGB", "RGBA"):
                            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                        save_options.update(quality=100, lossless=True, chroma="444")
                    destination = self._destination(src, extension)
                    try:
                        image.save(str(destination), format=fmt, **save_options)
                    except Exception:
                        # 元数据不兼容时去掉 EXIF/ICC 再试；仍失败则回退 PNG
                        bare = {k: v for k, v in save_options.items() if k not in ("exif", "icc_profile")}
                        try:
                            image.save(str(destination), format=fmt, **bare)
                        except Exception:
                            if fmt != "PNG":
                                destination = self._destination(src, ".png")
                                rgb = image if image.mode in ("RGB", "RGBA") else image.convert("RGBA")
                                rgb.save(str(destination), format="PNG", optimize=True, compress_level=9)
                                self.log_signal.emit(
                                    f"⚠️ [{index}/{len(self.paths)}] {src.name} 目标格式失败，已回退 PNG"
                                )
                            else:
                                raise
                ok += 1
                self.log_signal.emit(
                    f"✓ [{index}/{len(self.paths)}] {src.name} → {destination.name}"
                )
            except Exception as exc:
                fail += 1
                reason = self._clean_error(exc)
                if not first_error:
                    first_error = f"{src.name}：{reason}"
                self.log_signal.emit(f"❌ [{index}/{len(self.paths)}] {src.name}：{reason}")
            self.progress_signal.emit(int(index / max(1, len(self.paths)) * 100))
        self.log_signal.emit(f"════════ 转换完成：成功 {ok}｜失败 {fail} ════════")
        if first_error:
            self.log_signal.emit(f"首个失败原因：{first_error}")
        self.finished_signal.emit(ok, fail, self.output_dir)

# --- 主界面 ---
class VideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.last_folder = ""
        self.image_convert_paths = []
        self.convert_thread = None
        self.initUI()

    def initUI(self):
        self.setWindowTitle("图片工具")
        self.setMinimumSize(760, 620)
        self.setStyleSheet("")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)

        title = QLabel("🖼 图片工具")
        title.setObjectName("heading")
        root.addWidget(title)
        sub = QLabel("使用标签页切换「批量截图」与「图片格式转换」。依赖与 FFmpeg 请在顶部「设置与组件」管理。")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#94a3b8;")
        root.addWidget(sub)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # ─── 左侧面板 ─────────────────────────────
        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 10, 12, 10)
        left_layout.setSpacing(8)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # ═══════════ Tab 1: 批量截图 ═══════════
        tab_screenshot = QWidget()
        tab_ss_layout = QVBoxLayout(tab_screenshot)
        tab_ss_layout.setContentsMargins(0, 8, 0, 0)
        tab_ss_layout.setSpacing(8)

        tab_ss_layout.addWidget(QLabel("1. 视频来源（每行一个；支持 YouTube / Facebook / Instagram / TikTok）"))
        self.url_input = DropTextEdit()
        self.url_input.paths_dropped.connect(self.add_local_paths)
        self.url_input.setPlaceholderText("粘贴网络链接，或直接拖入本地视频/文件夹")
        self.url_input.setMinimumHeight(120)
        tab_ss_layout.addWidget(self.url_input, 1)
        source_btns = QHBoxLayout()
        self.btn_local = QPushButton("＋ 添加本地视频")
        self.btn_local.clicked.connect(self.add_local_videos)
        self.btn_folder = QPushButton("＋ 添加文件夹")
        self.btn_folder.clicked.connect(self.add_local_folder)
        source_btns.addWidget(self.btn_local)
        source_btns.addWidget(self.btn_folder)
        source_btns.addStretch()
        tab_ss_layout.addLayout(source_btns)

        params_group = QGroupBox("2. 截图参数")
        form = QFormLayout(params_group)
        form.setContentsMargins(10, 12, 10, 10)
        form.setSpacing(8)
        self.count_in = QLineEdit("10")
        self.interval_in = QLineEdit("0.5")
        self.prefix_in = QLineEdit("Shot")
        form.addRow("截图数量", self.count_in)
        form.addRow("间隔（秒）", self.interval_in)
        form.addRow("保存前缀", self.prefix_in)
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(os.path.join(os.path.expanduser("~"), "Pictures"))
        btn_path = QPushButton("选择目录")
        btn_path.clicked.connect(self.select_dir)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(btn_path)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        form.addRow("输出目录", path_widget)
        tab_ss_layout.addWidget(params_group)

        self.ss_pbar = QProgressBar()
        tab_ss_layout.addWidget(self.ss_pbar)
        self.run_btn = QPushButton("开始批量截图")
        self.run_btn.setObjectName("primary")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.start_task)
        tab_ss_layout.addWidget(self.run_btn)

        self.tab_widget.addTab(tab_screenshot, "📷 批量截图")

        # ═══════════ Tab 2: 图片格式转换 ═══════════
        tab_convert = QWidget()
        tab_cv_layout = QVBoxLayout(tab_convert)
        tab_cv_layout.setContentsMargins(0, 8, 0, 0)
        tab_cv_layout.setSpacing(8)

        convert_group = QGroupBox("图片格式转换（支持 HEIF / HEIC）")
        convert_form = QFormLayout(convert_group)
        convert_form.setContentsMargins(10, 12, 10, 10)
        convert_form.setSpacing(7)
        self.convert_source = QLineEdit()
        self.convert_source.setReadOnly(True)
        self.convert_source.setPlaceholderText("尚未选择图片；支持 JPG、PNG、WebP、TIFF、BMP、HEIF、HEIC、AVIF")
        source_row = QHBoxLayout()
        source_row.addWidget(self.convert_source, 1)
        choose_images = QPushButton("选图片")
        choose_images.setToolTip("选择一张或多张图片进行批量格式转换")
        choose_images.clicked.connect(self.select_convert_images)
        choose_image_folder = QPushButton("选文件夹")
        choose_image_folder.setToolTip("递归读取文件夹内支持的图片格式")
        choose_image_folder.clicked.connect(self.select_convert_folder)
        source_row.addWidget(choose_images)
        source_row.addWidget(choose_image_folder)
        convert_form.addRow("图片来源", source_row)

        self.convert_format = QComboBox()
        self.convert_format.addItems(list(IMAGE_OUTPUT_FORMATS))
        self.convert_format.setCurrentText("PNG（无损）")
        self.convert_format.setToolTip(
            "PNG/WebP/TIFF/BMP 使用无损编码；HEIF/AVIF 使用编解码器的无损模式；"
            "JPEG 格式本身有损，将使用最高质量和 4:4:4 色度。"
        )
        convert_form.addRow("目标格式", self.convert_format)

        convert_options = QHBoxLayout()
        self.convert_quality = QSpinBox()
        self.convert_quality.setRange(80, 100)
        self.convert_quality.setValue(100)
        self.convert_quality.setSuffix(" %")
        self.convert_quality.setToolTip("仅 JPEG 使用此质量；其他目标格式优先使用无损模式")
        self.convert_metadata = QCheckBox("保留 EXIF / 色彩配置")
        self.convert_metadata.setChecked(True)
        self.convert_overwrite = QCheckBox("覆盖同名")
        convert_options.addWidget(QLabel("JPEG质量"))
        convert_options.addWidget(self.convert_quality)
        convert_options.addWidget(self.convert_metadata)
        convert_options.addWidget(self.convert_overwrite)
        convert_form.addRow(convert_options)

        self.convert_output = QLineEdit(os.path.join(os.path.expanduser("~"), "Pictures", "Converted"))
        output_row = QHBoxLayout()
        output_row.addWidget(self.convert_output, 1)
        choose_convert_output = QPushButton("选择")
        choose_convert_output.clicked.connect(self.select_convert_output)
        output_row.addWidget(choose_convert_output)
        convert_form.addRow("保存目录", output_row)

        convert_hint = QLabel("无损指像素不经有损压缩；不同色彩空间之间转换仍可能受格式能力限制。")
        convert_hint.setWordWrap(True)
        convert_hint.setStyleSheet("color:#94a3b8;font-size:11px;")
        convert_form.addRow(convert_hint)
        tab_cv_layout.addWidget(convert_group, 1)

        self.cv_pbar = QProgressBar()
        tab_cv_layout.addWidget(self.cv_pbar)
        self.convert_btn = QPushButton("开始转换")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setMinimumHeight(36)
        self.convert_btn.clicked.connect(self.start_image_conversion)
        tab_cv_layout.addWidget(self.convert_btn)

        self.tab_widget.addTab(tab_convert, "🖼 图片格式转换")

        left_layout.addWidget(self.tab_widget, 1)

        # ─── 公共工具栏（始终可见）───────────────────
        tools = QGroupBox("维护与输出")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.setSpacing(6)
        tool_tip = QLabel("FFmpeg / yt-dlp 请到顶部「设置与组件」统一检测与一键更新。")
        tool_tip.setStyleSheet("color:#94a3b8;font-size:11px;")
        tool_tip.setWordWrap(True)
        tools_layout.addWidget(tool_tip)
        tool_row = QHBoxLayout()
        self.btn_log = QPushButton("完整执行日志")
        self.btn_log.clicked.connect(self.view_log)
        tool_row.addWidget(self.btn_log)
        tool_row.addStretch()
        tools_layout.addLayout(tool_row)
        out_row = QHBoxLayout()
        self.btn_open = QPushButton("打开完成文件夹")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(lambda: open_local_path(self.last_folder))
        btn_clear = QPushButton("清空历史查重")
        btn_clear.clicked.connect(self.clear_history)
        out_row.addWidget(self.btn_open)
        out_row.addWidget(btn_clear)
        out_row.addStretch()
        tools_layout.addLayout(out_row)
        left_layout.addWidget(tools)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left)

        # ─── 右侧日志面板（共享）─────────────────────
        right = QFrame()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(8)
        right_layout.addWidget(QLabel("运行日志"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("任务进度与错误信息会显示在这里…")
        self.log_view.setStyleSheet(
            "background:#0b1424;color:#86efac;font-family:Consolas,'Microsoft YaHei UI';font-size:12px;"
        )
        right_layout.addWidget(self.log_view, 1)

        split.addWidget(left_scroll)
        split.addWidget(right)
        split.setSizes([560, 720])
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)


    def view_log(self):
        """核心功能：打開後台日誌文件"""
        if os.path.exists(LOG_FILE):
            open_local_path(LOG_FILE)
        else:
            QMessageBox.warning(self, "提示", "日誌文件尚未生成。")

    def select_dir(self):
        d = QFileDialog.getExistingDirectory(self, "選擇路徑")
        if d: self.path_edit.setText(d)

    def add_local_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择本地视频", "",
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.wmv *.webm *.m4v *.flv);;所有文件 (*.*)")
        self.add_local_paths(files)

    def add_local_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if folder: self.add_local_paths([folder])

    def add_local_paths(self, paths):
        files = collect_files(paths, VIDEO_EXTENSIONS)
        if not files: return
        existing = [line.strip() for line in self.url_input.toPlainText().splitlines() if line.strip()]
        existing.extend(path for path in files if path not in existing)
        self.url_input.setPlainText("\n".join(existing))

    def _set_convert_paths(self, paths):
        existing = set(self.image_convert_paths)
        for path in paths or []:
            resolved = str(Path(path).resolve())
            if Path(resolved).is_file() and Path(resolved).suffix.lower() in IMAGE_EXTENSIONS:
                existing.add(resolved)
        self.image_convert_paths = sorted(existing, key=lambda value: value.lower())
        if self.image_convert_paths:
            names = "；".join(Path(p).name for p in self.image_convert_paths[:3])
            if len(self.image_convert_paths) > 3:
                names += "…"
            self.convert_source.setText(f"已选 {len(self.image_convert_paths)} 张：{names}")
            self.convert_source.setToolTip("\n".join(self.image_convert_paths))
        else:
            self.convert_source.clear()
            self.convert_source.setToolTip("")

    def select_convert_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要转换的图片", "",
            "图片 (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp *.heic *.heif *.avif);;所有文件 (*.*)",
        )
        self._set_convert_paths(files)

    def select_convert_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        files = [
            str(path) for path in Path(folder).rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        self._set_convert_paths(files)

    def select_convert_output(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择转换图片保存目录", self.convert_output.text().strip()
        )
        if folder:
            self.convert_output.setText(folder)

    def start_image_conversion(self):
        if self.convert_thread and self.convert_thread.isRunning():
            QMessageBox.information(self, "图片转换", "当前转换任务仍在运行。")
            return
        if not self.image_convert_paths:
            QMessageBox.warning(self, "图片转换", "请先选择图片或图片文件夹。")
            return
        output = self.convert_output.text().strip()
        if not output:
            QMessageBox.warning(self, "图片转换", "请选择保存目录。")
            return
        self.convert_btn.setEnabled(False)
        self.cv_pbar.setValue(0)
        self.convert_thread = ImageConvertThread(
            self.image_convert_paths,
            output,
            self.convert_format.currentText(),
            self.convert_quality.value(),
            self.convert_metadata.isChecked(),
            self.convert_overwrite.isChecked(),
        )
        self.convert_thread.log_signal.connect(self.log_view.append)
        self.convert_thread.progress_signal.connect(self.cv_pbar.setValue)
        self.convert_thread.finished_signal.connect(self._image_conversion_finished)
        self.convert_thread.start()

    def _image_conversion_finished(self, ok, fail, folder):
        self.convert_btn.setEnabled(True)
        if ok:
            self.last_folder = folder
            self.btn_open.setEnabled(True)
        if fail and ok == 0:
            QMessageBox.warning(
                self,
                "图片格式转换失败",
                f"全部 {fail} 张都未转换成功。\n\n"
                "请查看右侧日志中的「首个失败原因」。\n"
                "常见处理：安装/更新 pillow-heif；或改导出 PNG 再试；"
                "若提示绘图冲突，请先关掉其它页面的视频预览。",
            )
        elif fail:
            QMessageBox.warning(
                self,
                "图片转换完成",
                f"成功 {ok} 张，失败 {fail} 张。\n详情请查看右侧日志。",
            )
        else:
            QMessageBox.information(self, "图片转换完成", f"已成功转换 {ok} 张图片。")


    def clear_history(self):
        path = str(app_data_dir() / "screenshot_history.json")
        if os.path.exists(path):
            os.remove(path)
            QMessageBox.information(self, "完成", "歷史記錄已重置。")

    def start_task(self):
        urls = [u.strip() for u in self.url_input.toPlainText().split('\n') if u.strip()]
        if not urls: return
        self.run_btn.setEnabled(False)
        self.thread = ProcessThread(urls, int(self.count_in.text()), float(self.interval_in.text()),
                                   self.path_edit.text(), self.prefix_in.text())
        self.thread.log_signal.connect(self.log_view.append)
        self.thread.progress_signal.connect(self.ss_pbar.setValue)
        self.thread.folder_ready_signal.connect(lambda p: (setattr(self, 'last_folder', p), self.btn_open.setEnabled(True)))
        self.thread.finished_signal.connect(lambda: self.run_btn.setEnabled(True))
        self.thread.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTool()
    window.show()
    sys.exit(app.exec())
