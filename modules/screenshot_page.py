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
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFileDialog, QProgressBar, QMessageBox,
    QFrame, QFormLayout, QGroupBox, QScrollArea, QSplitter,
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
        logging.info(f"=== 啟動任務: 處理 {len(self.urls)} 個鏈接 ===")

        YoutubeDL = None
        if any(not os.path.isfile(item.strip()) for item in self.urls if item.strip()):
            try:
                from yt_dlp import YoutubeDL
            except ImportError:
                msg = "環境錯誤：未安裝 yt-dlp 庫，網絡鏈接無法解析"
                self.log_signal.emit(f"❌ {msg}")
                logging.error(msg)
                return

        for index, url in enumerate(self.urls):
            url = url.strip()
            if not url: continue
            is_local = os.path.isfile(url)
            
            # 查重跳過記錄
            if not is_local and url in history:
                self.log_signal.emit(f"⚠️ 跳過已存在鏈接")
                logging.info(f"跳過已處理 URL: {url}")
                continue

            temp_video = None
            try:
                self.log_signal.emit(f"🎬 [任務 {index+1}] {'正在读取本地视频' if is_local else '正在获取网络视频'}...")
                logging.info(f"開始處理: {url}")
                if is_local:
                    temp_video = url
                else:
                    ydl_opts = {
                        'outtmpl': f'temp_{int(time.time())}.%(ext)s',
                        'format': 'mp4/best',
                        'quiet': True,
                        'proxy': proxy,
                        'nocheckcertificate': True,
                    }
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        temp_video = ydl.prepare_filename(info)

                # 截圖邏輯
                f_idx = 1
                while True:
                    out_path = os.path.join(self.folder, f"{self.prefix}_{f_idx:03d}")
                    if not os.path.exists(out_path): break
                    f_idx += 1

                os.makedirs(out_path, exist_ok=True)
                cap = cv2.VideoCapture(temp_video)
                
                sc = 0
                for i in range(self.count):
                    cap.set(cv2.CAP_PROP_POS_MSEC, i * self.interval * 1000)
                    ret, frame = cap.read()
                    if ret:
                        cv2.imwrite(os.path.join(out_path, f"shot_{i+1:03d}.jpg"), frame)
                        sc += 1
                cap.release()

                if sc > 0:
                    if not is_local:
                        self.save_history(url)
                    self.log_signal.emit(f"✅ 成功完成: {os.path.basename(out_path)}")
                    logging.info(f"成功截取 {sc} 張圖。鏈接: {url}")
                    self.folder_ready_signal.emit(out_path)
                else:
                    raise Exception("視頻下載成功但無法解析畫面內容")
                
            except Exception as e:
                # 這裡記錄所有執行錯誤和沒成功的記錄
                error_log = f"任務 {index+1} 失敗: {str(e)} | URL: {url}"
                self.log_signal.emit(f"❌ 執行出錯，請查看日誌")
                logging.error(error_log)
                
            finally:
                if temp_video and not is_local and os.path.exists(temp_video):
                    try: os.remove(temp_video)
                    except: pass
                self.progress_signal.emit(int((index + 1) / len(self.urls) * 100))

        logging.info("=== 所有任務執行完畢 ===")
        self.finished_signal.emit()

# --- 主界面 ---
class VideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.last_folder = ""
        self.initUI()

    def initUI(self):
        # 与自动流水线一致：左参数配置，右输出日志
        self.setWindowTitle("批量截图")
        self.setMinimumSize(760, 620)
        self.setStyleSheet("")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)

        title = QLabel("📷 批量截图")
        title.setObjectName("heading")
        root.addWidget(title)
        sub = QLabel("支持网络链接与本地视频；左侧配置参数，右侧查看执行日志。依赖与 FFmpeg 请在顶部「设置与组件」管理。")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#94a3b8;")
        root.addWidget(sub)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 10, 12, 10)
        left_layout.setSpacing(8)

        left_layout.addWidget(QLabel("1. 视频来源（每行一个；支持 YouTube / Facebook / Instagram / TikTok）"))
        self.url_input = DropTextEdit()
        self.url_input.paths_dropped.connect(self.add_local_paths)
        self.url_input.setPlaceholderText("粘贴网络链接，或直接拖入本地视频/文件夹")
        self.url_input.setMinimumHeight(120)
        left_layout.addWidget(self.url_input, 1)
        source_btns = QHBoxLayout()
        self.btn_local = QPushButton("＋ 添加本地视频")
        self.btn_local.clicked.connect(self.add_local_videos)
        self.btn_folder = QPushButton("＋ 添加文件夹")
        self.btn_folder.clicked.connect(self.add_local_folder)
        source_btns.addWidget(self.btn_local)
        source_btns.addWidget(self.btn_folder)
        source_btns.addStretch()
        left_layout.addLayout(source_btns)

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
        left_layout.addWidget(params_group)

        tools = QGroupBox("3. 维护与输出")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.setSpacing(6)
        tool_row = QHBoxLayout()
        self.btn_upd = QPushButton("更新 yt-dlp")
        self.btn_upd.clicked.connect(self.update_ytdlp)
        self.btn_chk = QPushButton("检查 FFmpeg")
        self.btn_chk.clicked.connect(self.check_ffmpeg)
        self.btn_log = QPushButton("完整执行日志")
        self.btn_log.clicked.connect(self.view_log)
        tool_row.addWidget(self.btn_upd)
        tool_row.addWidget(self.btn_chk)
        tool_row.addWidget(self.btn_log)
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

        self.pbar = QProgressBar()
        left_layout.addWidget(self.pbar)
        self.run_btn = QPushButton("开始批量截图")
        self.run_btn.setObjectName("primary")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.start_task)
        left_layout.addWidget(self.run_btn)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left)

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

    # --- 功能邏輯 ---
    def update_ytdlp(self):
        """核心功能：更新解析組件"""
        self.log_view.append("🔄 正在啟動 Yt-DLP 強制更新程序...")
        logging.info("用戶觸發更新組件")
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "--no-cache-dir"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        except Exception as e:
            self.log_view.append(f"❌ 無法啟動更新: {e}")

    def check_ffmpeg(self):
        """核心功能：檢測解碼器"""
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                                 shell=False, creationflags=flags)
            if res.returncode == 0:
                msg = "✅ FFmpeg 解碼器檢測正常！"
                QMessageBox.information(self, "檢測成功", msg + "\n" + res.stdout.split('\n')[0])
                logging.info(msg)
            else: raise Exception()
        except:
            QMessageBox.critical(self, "錯誤", "❌ 未檢測到 FFmpeg！這會導致高畫質視頻截取失敗。")
            logging.error("檢測不到 FFmpeg")

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
        self.thread.progress_signal.connect(self.pbar.setValue)
        self.thread.folder_ready_signal.connect(lambda p: (setattr(self, 'last_folder', p), self.btn_open.setEnabled(True)))
        self.thread.finished_signal.connect(lambda: self.run_btn.setEnabled(True))
        self.thread.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTool()
    window.show()
    sys.exit(app.exec())
