from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .platform_utils import app_data_dir, bundled_media_tool, media_tool_name, validate_media_tool


PYTHON_COMPONENTS = [
    ("PySide6", "PySide6", "PySide6"),
    ("Pillow", "PIL", "Pillow"),
    ("OpenCV", "cv2", "opencv-python"),
    ("yt-dlp", "yt_dlp", "yt-dlp"),
    ("SceneDetect", "scenedetect", "scenedetect[opencv]"),
    ("MoviePy", "moviepy", "moviepy"),
    ("Requests", "requests", "requests"),
    ("本地 Whisper", "faster_whisper", "faster-whisper"),
    ("ONNX Runtime / VAD", "onnxruntime", "onnxruntime"),
    ("无密钥翻译", "deep_translator", "deep-translator"),
    ("Google Drive / Sheets", "googleapiclient", "google-api-python-client google-auth"),
    ("Google OAuth 授权", "google_auth_oauthlib", "google-auth-oauthlib"),
    ("微软文字转语音", "edge_tts", "edge-tts"),
]


def toolkit_dir() -> Path:
    return app_data_dir()


def component_bin() -> Path:
    path = toolkit_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hidden_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def find_media_tool(name: str):
    local = component_bin() / media_tool_name(name)
    bundled = bundled_media_tool(name)
    if validate_media_tool(local,name): return str(local)
    if validate_media_tool(bundled,name): return str(bundled)
    found=shutil.which(name)
    return found if found and validate_media_tool(found,name) else None


def component_rows():
    rows = []
    for label, module, package in PYTHON_COMPONENTS:
        ok = importlib.util.find_spec(module) is not None
        version = ""
        if ok:
            try:
                version = importlib.metadata.version(package.split("[")[0])
            except Exception:
                version = "已安装"
        rows.append({"name": label, "type": "Python 依赖", "ok": ok,
                     "detail": version or f"缺少：{package}", "package": package})
    for name in ("ffmpeg", "ffprobe"):
        path = find_media_tool(name)
        rows.append({"name": name.upper(), "type": "媒体组件", "ok": bool(path),
                     "detail": path or "未找到", "package": ""})
    return rows


def package_dist_names(package: str) -> list[str]:
    """package 字段可能是 'a b' 或 'a[extra]'，拆成 pip 发行名列表。"""
    names = []
    for part in str(package or "").split():
        name = part.split("[")[0].strip()
        if name:
            names.append(name)
    return names


def package_installed_version(package: str) -> str:
    """读取已安装包版本；未安装返回空字符串。多包时返回第一个有版本的。"""
    for name in package_dist_names(package):
        try:
            return importlib.metadata.version(name)
        except Exception:
            continue
    return ""


def resolve_python_cmd() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("python3") or "python"


class CheckUpdatesWorker(QObject):
    """联网检查本软件清单里所有 Python 依赖是否有新版本（不安装）。"""
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str, object)  # ok, message, outdated_map {dist: {current, latest}}

    def run(self):
        outdated: dict[str, dict] = {}
        try:
            python_cmd = resolve_python_cmd()
            self.log.emit("──────── 检查全部 Python 组件更新 ────────")
            self.log.emit("正在查询 PyPI / 当前环境已安装版本（需要网络）…")
            self.progress.emit(5)

            # 1) 本机已安装版本
            installed: dict[str, str] = {}
            for _label, _mod, package in PYTHON_COMPONENTS:
                for dist in package_dist_names(package):
                    ver = package_installed_version(dist)
                    if ver:
                        installed[dist.lower()] = ver
            self.log.emit(f"清单内已安装 {len(installed)} 个发行包，开始对比最新版…")
            self.progress.emit(15)

            # 2) pip list --outdated（只覆盖已安装且有更新的；可能较慢，先提示）
            self.log.emit("正在联网查询可升级包（pip list --outdated，通常 10–60 秒）…")
            self.progress.emit(30)
            result = subprocess.run(
                [
                    python_cmd, "-m", "pip", "list", "--outdated",
                    "--format=json", "--disable-pip-version-check",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", **hidden_kwargs(),
            )
            self.log.emit("查询完成，正在汇总结果…")
            self.progress.emit(70)
            pip_outdated = {}
            if result.returncode == 0 and (result.stdout or "").strip():
                try:
                    import json
                    data = json.loads(result.stdout)
                    if isinstance(data, list):
                        for item in data:
                            name = str(item.get("name") or "").strip()
                            if not name:
                                continue
                            pip_outdated[name.lower()] = {
                                "current": str(item.get("version") or ""),
                                "latest": str(item.get("latest_version") or item.get("latest") or ""),
                            }
                except Exception as exc:
                    self.log.emit(f"解析 pip list 结果失败：{exc}，改用逐包查询。")

            # 3) 映射到我们的组件清单
            tracked = set()
            for _label, _mod, package in PYTHON_COMPONENTS:
                for dist in package_dist_names(package):
                    tracked.add(dist.lower())

            for dist_l, info in pip_outdated.items():
                if dist_l in tracked:
                    outdated[dist_l] = info

            # 4) 对清单内已安装但不在 outdated 列表的包，标为最新；未安装单独说明
            lines = []
            up_to_date = 0
            missing = 0
            for label, _mod, package in PYTHON_COMPONENTS:
                dists = package_dist_names(package)
                if not dists:
                    continue
                dist = dists[0]
                cur = package_installed_version(dist)
                if not cur:
                    missing += 1
                    lines.append(f"  ✕ {label}（{dist}）：未安装")
                    continue
                info = outdated.get(dist.lower())
                if info and info.get("latest") and info.get("latest") != cur:
                    latest = info["latest"]
                    lines.append(f"  ↑ {label}（{dist}）：{cur}  →  可更新到 {latest}")
                else:
                    up_to_date += 1
                    lines.append(f"  ✓ {label}（{dist}）：{cur}（已是最新）")

            self.progress.emit(100)
            self.log.emit("检查结果：")
            for line in lines:
                self.log.emit(line)

            can_update = len(outdated)
            summary = (
                f"检查完成：可更新 {can_update} 个，已最新 {up_to_date} 个，未安装 {missing} 个。"
            )
            if can_update:
                summary += "\n可点「一键更新全部 Python 依赖」升级；yt-dlp 也可单独更新。"
            else:
                summary += "\nPython 依赖均已最新（或未安装的请用「一键安装缺少组件」）。"
            self.log.emit("──────── 检查结束 ────────")
            self.log.emit(summary)
            # FFmpeg 说明
            self.log.emit(
                "提示：FFmpeg/FFprobe 不走 pip；可用「重新安装 FFmpeg / FFprobe」强制重装。"
            )
            self.finished.emit(True, summary, outdated)
        except Exception as exc:
            self.finished.emit(False, str(exc), {})


class InstallWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, packages, install_media=False):
        super().__init__()
        self.packages = packages
        self.install_media = install_media

    def run(self):
        try:
            # 展开 "a b" 多包字符串，保留 extras 如 scenedetect[opencv]
            expanded = []
            for raw in self.packages:
                for token in str(raw).split():
                    token = token.strip()
                    if token:
                        expanded.append(token)
            # 去重保序
            seen = set()
            self.packages = []
            for p in expanded:
                key = p.split("[")[0].strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    self.packages.append(p)

            steps = len(self.packages) + (1 if self.install_media else 0)
            if not steps:
                self.finished.emit(True, "所有组件均已齐全")
                return
            completed = 0
            summary_bits = []
            if self.packages:
                python_cmd = resolve_python_cmd()
                # 更新前记录版本，便于日志对比
                before_versions = {pkg: package_installed_version(pkg) for pkg in self.packages}
                only_ytdlp = (
                    len(self.packages) == 1
                    and self.packages[0].split("[")[0].strip().lower() in ("yt-dlp", "yt_dlp")
                )
                total_pkgs = len(self.packages)
                if only_ytdlp:
                    old_v = before_versions.get(self.packages[0]) or "未安装"
                    self.log.emit("──────── yt-dlp 一键更新 ────────")
                    self.log.emit(f"当前版本：{old_v}")
                    self.log.emit("正在下载并升级 yt-dlp（实时进度见下方，请稍候）…")
                else:
                    self.log.emit(f"──────── 安装/升级 Python 依赖（共 {total_pkgs} 个）────────")
                    for i, pkg in enumerate(self.packages, 1):
                        old_v = before_versions.get(pkg) or "未安装"
                        self.log.emit(f"  [{i}/{total_pkgs}] {pkg}：更新前 {old_v}")
                    self.log.emit("开始下载（pip 进度会持续输出，请勿以为卡住）…")

                # 逐包安装，便于显示进度；避免一次卡很久无输出
                failed = []
                for i, pkg in enumerate(self.packages, 1):
                    if self.cancelled if hasattr(self, "cancelled") else False:
                        raise RuntimeError("用户已取消")
                    old_v = before_versions.get(pkg) or "未安装"
                    self.log.emit(f"▶ [{i}/{total_pkgs}] 正在处理：{pkg}（当前 {old_v}）")
                    self.progress.emit(max(1, round((i - 1) / max(1, steps) * 90)))
                    command = [
                        python_cmd, "-m", "pip", "install", "--upgrade",
                        "--disable-pip-version-check",
                        "--progress-bar", "off",  # 文本进度更干净
                        pkg,
                    ]
                    # 实时读 pip 输出
                    rc = self._run_pip_streaming(command, pkg_index=i, pkg_total=total_pkgs)
                    # 读新版本
                    dist_name = pkg.split("[")[0].strip()
                    new_v = package_installed_version(dist_name)
                    if not new_v:
                        show = subprocess.run(
                            [python_cmd, "-m", "pip", "show", dist_name],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace", **hidden_kwargs(),
                        )
                        for line in (show.stdout or "").splitlines():
                            if line.lower().startswith("version:"):
                                new_v = line.split(":", 1)[1].strip()
                                break
                    new_v = new_v or "未知"
                    if rc != 0:
                        failed.append(pkg)
                        self.log.emit(f"  ✕ [{i}/{total_pkgs}] {pkg} 失败")
                        continue
                    if old_v == new_v:
                        line = f"  ✓ [{i}/{total_pkgs}] {pkg}：已是最新 {new_v}"
                    else:
                        line = f"  ✓ [{i}/{total_pkgs}] {pkg}：{old_v}  →  {new_v}"
                    self.log.emit(line)
                    summary_bits.append(line.strip())
                    self.progress.emit(max(1, round(i / max(1, steps) * 90)))

                if failed:
                    raise RuntimeError(
                        "部分依赖安装失败：" + "、".join(failed)
                        + "。请查看上方日志（网络/权限/代理）。"
                    )

                if only_ytdlp:
                    new_v = package_installed_version("yt-dlp") or "未知"
                    old_v = before_versions.get(self.packages[0]) or "未安装"
                    self.log.emit("──────── 更新结束 ────────")
                    if old_v == new_v:
                        self.log.emit(f"yt-dlp 当前版本：{new_v}（与更新前相同，已是最新）")
                    else:
                        self.log.emit(f"yt-dlp 更新完成：{old_v}  →  {new_v}")

                completed += len(self.packages)
                self.progress.emit(round(completed / steps * 100) if steps else 100)
            if self.install_media:
                self._install_ffmpeg()
                completed += 1
                self.progress.emit(round(completed / steps * 100))
                summary_bits.append("FFmpeg / FFprobe 已安装或恢复")
            msg = "组件安装完成，请重新检测"
            if summary_bits:
                msg = "组件安装完成：\n" + "\n".join(summary_bits) + "\n请重新检测"
            self.finished.emit(True, msg)
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _run_pip_streaming(self, command: list, pkg_index: int = 1, pkg_total: int = 1) -> int:
        """运行 pip 并实时把关键行写到日志，避免长时间无输出误以为卡住。"""
        env = os.environ.copy()
        # 强制 pip 非交互、禁用进度条乱码
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                **hidden_kwargs(),
            )
        except Exception as exc:
            self.log.emit(f"  无法启动 pip：{exc}")
            return 1

        interesting_keys = (
            "collecting ", "downloading ", "using cached", "installing ",
            "successfully installed", "requirement already", "uninstalling ",
            "error", "failed", "warning", "building wheel", "obtained ",
            "from ", "http",
        )
        line_count = 0
        last_heartbeat = 0
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = (raw or "").rstrip()
                if not line:
                    continue
                line_count += 1
                low = line.lower()
                # 心跳：每 15 行输出一次，证明还在跑
                if line_count - last_heartbeat >= 15:
                    last_heartbeat = line_count
                    self.log.emit(f"  …仍在下载/安装 {pkg_index}/{pkg_total}（已收到 {line_count} 行输出）")
                if any(k in low for k in interesting_keys):
                    # 截断过长的 URL 行
                    show = line if len(line) <= 160 else line[:140] + "…"
                    self.log.emit(f"  {show}")
            rc = proc.wait(timeout=3600)
            return int(rc)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            self.log.emit("  超时：单包安装超过 60 分钟，已终止")
            return 1
        except Exception as exc:
            try:
                proc.kill()
            except Exception:
                pass
            self.log.emit(f"  读取 pip 输出失败：{exc}")
            return 1

    def _install_ffmpeg(self):
        if sys.platform == "darwin":
            self.log.emit("正在从应用内置组件恢复 FFmpeg / FFprobe …")
            restored = True
            for name in ("ffmpeg", "ffprobe"):
                source = bundled_media_tool(name)
                target = component_bin() / media_tool_name(name)
                if not source.exists():
                    restored = False
                    break
                shutil.copy2(source, target)
                target.chmod(target.stat().st_mode | 0o111)
            if restored:
                return
            brew = shutil.which("brew")
            if not brew:
                raise RuntimeError("应用内置媒体组件不可用，且未检测到 Homebrew。请重新安装完整应用包。")
            self.log.emit("正在通过 Homebrew 安装 FFmpeg / FFprobe …")
            result = subprocess.run([brew, "install", "ffmpeg"], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            self.log.emit(result.stdout[-5000:])
            if result.returncode != 0:
                raise RuntimeError("Homebrew 安装 FFmpeg 失败，请查看日志")
            return
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        self.log.emit("正在下载 FFmpeg Essentials（包含 FFmpeg 与 FFprobe）…")
        self.log.emit(f"下载地址：{url}")
        with tempfile.TemporaryDirectory(prefix="video_toolkit_ffmpeg_") as temp_name:
            archive = Path(temp_name) / "ffmpeg.zip"
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                if total:
                    self.log.emit(f"文件大小约 {total / (1024 * 1024):.1f} MB，请稍候…")
                else:
                    self.log.emit("文件大小未知，开始下载（会持续汇报进度）…")
                received = 0
                last_log_pct = -1
                with archive.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                            received += len(chunk)
                            if total:
                                pct = min(95, round(received / total * 95))
                                self.progress.emit(pct)
                                # 每 10% 写一行日志
                                if pct // 10 > last_log_pct // 10:
                                    last_log_pct = pct
                                    self.log.emit(
                                        f"  下载进度 {pct}%（{received / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB）"
                                    )
                            else:
                                mb = received / (1024 * 1024)
                                if int(mb) > 0 and int(mb) % 5 == 0:
                                    self.log.emit(f"  已下载约 {mb:.0f} MB…")
            self.log.emit("下载完成，正在解压媒体组件 …")
            with zipfile.ZipFile(archive) as package:
                members = package.namelist()
                for executable in ("ffmpeg.exe", "ffprobe.exe"):
                    member = next((x for x in members if x.lower().endswith("/bin/" + executable)), None)
                    if not member:
                        raise RuntimeError(f"安装包中未找到 {executable}")
                    with package.open(member) as source, (component_bin() / executable).open("wb") as target:
                        shutil.copyfileobj(source, target)
        bin_text = str(component_bin())
        if bin_text not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = bin_text + os.pathsep + os.environ.get("PATH", "")


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.rows = []
        # 最近一次「检查更新」结果：{dist_lower: {current, latest}}
        self._outdated_map: dict = {}
        self.build_ui()
        self.refresh()

    def build_ui(self):
        layout = QVBoxLayout(self); self.main_layout = layout
        layout.setContentsMargins(24, 16, 24, 16); layout.setSpacing(8)
        title = QLabel("🛠 组件检测与安装"); title.setObjectName("heading")
        layout.addWidget(title)
        sub = QLabel(
            "「重新检测」只看本机是否已安装；「检查更新」会联网对比全部 Python 依赖是否有新版。\n"
            "安装/更新过程静默执行，不弹出命令窗口。"
        )
        sub.setStyleSheet("color:#94a3b8;font-size:13px;")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("重新检测全部")
        self.refresh_btn.setToolTip("仅检测本机是否已安装及本地版本，不联网查新版。")
        self.refresh_btn.clicked.connect(self.refresh)
        self.check_update_btn = QPushButton("检查全部更新")
        self.check_update_btn.setToolTip(
            "联网检查清单内全部 Python 依赖是否有新版本（不安装）。\n"
            "FFmpeg 需单独用「重新安装 FFmpeg」处理。"
        )
        self.check_update_btn.clicked.connect(self.check_all_updates)
        self.install_btn = QPushButton("一键安装缺少组件")
        self.install_btn.setObjectName("primary")
        self.install_btn.setToolTip("只安装当前标记为「缺少」的组件，不升级已有版本。")
        self.install_btn.clicked.connect(self.install_missing)
        self.update_all_btn = QPushButton("一键更新全部 Python 依赖")
        self.update_all_btn.setToolTip(
            "对清单内全部 Python 包执行 pip install --upgrade（含 yt-dlp、OpenCV 等）。\n"
            "建议先点「检查全部更新」查看可升级项；耗时取决于网络。"
        )
        self.update_all_btn.clicked.connect(self.update_all_python)
        self.media_btn = QPushButton("重新安装 FFmpeg / FFprobe")
        self.media_btn.clicked.connect(lambda: self.start_install([], True))
        self.ytdlp_btn = QPushButton("一键更新 yt-dlp")
        self.ytdlp_btn.setToolTip(
            "仅强制升级 yt-dlp（批量截图/网络链接字幕提取）。\n"
            "解析 Facebook/YouTube 失败时优先点此更新。"
        )
        self.ytdlp_btn.clicked.connect(self.update_ytdlp)
        # 两行按钮，避免挤成一团
        actions.addWidget(self.refresh_btn)
        actions.addWidget(self.check_update_btn)
        actions.addWidget(self.install_btn)
        actions.addStretch()
        layout.addLayout(actions)
        actions2 = QHBoxLayout()
        actions2.addWidget(self.update_all_btn)
        actions2.addWidget(self.ytdlp_btn)
        actions2.addWidget(self.media_btn)
        actions2.addStretch()
        layout.addLayout(actions2)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["组件", "类型", "状态", "版本或位置"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(200)
        layout.addWidget(self.log)

    def add_font_management(self, import_callback, library_callback, font_folder):
        """Install one-time font management beside other reusable components."""
        if hasattr(self, "font_management_group"):
            return
        group = QGroupBox("字幕字体管理")
        self.font_management_group = group
        row = QHBoxLayout(group)
        row.addWidget(QLabel(f"字体目录：{font_folder}"), 1)
        import_button = QPushButton("导入本地字体…")
        import_button.setToolTip("导入 TTF、OTF 或 TTC，之后可在 Reels 字幕样式中直接选择")
        import_button.clicked.connect(import_callback)
        library_button = QPushButton("开源字体库…")
        library_button.setToolTip("从 Google Fonts 官方仓库安装开源字体，下载一次后离线使用")
        library_button.clicked.connect(library_callback)
        row.addWidget(import_button); row.addWidget(library_button)
        self.main_layout.insertWidget(3, group)

    def refresh(self):
        self.rows = component_rows()
        self.table.setRowCount(0)
        for data in self.rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            status = "✓ 正常" if data["ok"] else "✕ 缺少"
            detail = data["detail"]
            # 合并「检查更新」结果到表格
            if data["ok"] and data["type"] == "Python 依赖" and self._outdated_map:
                for dist in package_dist_names(data.get("package") or ""):
                    info = self._outdated_map.get(dist.lower())
                    if info and info.get("latest"):
                        cur = info.get("current") or package_installed_version(dist) or ""
                        latest = info["latest"]
                        if latest and cur and latest != cur:
                            status = "↑ 可更新"
                            detail = f"{cur}  →  最新 {latest}"
                        break
            values = (data["name"], data["type"], status, detail)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 2:
                    if "缺少" in status:
                        item.setForeground(QColor("#ef4444"))
                    elif "可更新" in status:
                        item.setForeground(QColor("#f59e0b"))
                    else:
                        item.setForeground(QColor("#22c55e"))
                self.table.setItem(row, col, item)
        missing = sum(not x["ok"] for x in self.rows)
        self.install_btn.setText(f"一键安装缺少组件（{missing}）")
        can_up = len(self._outdated_map or {})
        if hasattr(self, "update_all_btn"):
            self.update_all_btn.setText(
                f"一键更新全部 Python 依赖（{can_up} 个可升）" if can_up
                else "一键更新全部 Python 依赖"
            )

    def install_missing(self):
        packages = [x["package"] for x in self.rows if not x["ok"] and x["type"] == "Python 依赖"]
        media = any(not x["ok"] and x["type"] == "媒体组件" for x in self.rows)
        if not packages and not media:
            QMessageBox.information(self, "无需安装", "没有缺少的组件。若要升级已有版本，请用「检查全部更新」/「一键更新全部」。")
            return
        self.start_install(packages, media)

    def update_ytdlp(self):
        """强制升级 yt-dlp（网络截图 / 链接字幕提取）。"""
        old = package_installed_version("yt-dlp") or "未安装"
        self.start_install(
            ["yt-dlp"], False,
            force_title=f"正在更新 yt-dlp …（当前版本：{old}）",
        )

    def update_all_python(self):
        """升级清单内全部 Python 依赖（pip --upgrade）。"""
        packages = []
        for _label, _mod, package in PYTHON_COMPONENTS:
            # 整段 package 可能是 "a b" 或多个带 extras 的名
            for token in str(package).split():
                token = token.strip()
                if token:
                    packages.append(token)
        # 去重保序（按发行名）
        seen = set()
        unique = []
        for p in packages:
            key = p.split("[")[0].strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(p)
        if not unique:
            QMessageBox.information(self, "没有包", "清单为空。")
            return
        n = len(unique)
        # 若刚检查过更新，优先只升可更新的（更快）；否则升全部
        if self._outdated_map:
            to_upgrade = [
                p for p in unique
                if p.split("[")[0].strip().lower() in self._outdated_map
            ]
            if to_upgrade:
                unique = to_upgrade
                n = len(unique)
                tip = f"将升级检查到的 {n} 个可更新组件。"
            else:
                tip = f"未检测到可更新项，将仍对全部 {n} 个包执行 --upgrade（确认是否已最新）。"
        else:
            tip = f"将升级约 {n} 个 Python 组件（pip install --upgrade）。"
        reply = QMessageBox.question(
            self, "更新全部 Python 依赖",
            f"{tip}\n可能需要数分钟，并依赖网络。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.start_install(
            unique, False,
            force_title=f"正在一键更新 Python 依赖（共 {n} 个）…",
        )

    def check_all_updates(self):
        """联网检查全部 Python 组件是否有新版本。"""
        if self.thread:
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前安装/检查结束。")
                    return
            except RuntimeError:
                self.thread = None
        self.log.clear()
        self.progress.setValue(0)
        self.log.appendPlainText("开始检查全部 Python 组件更新…")
        self.thread = QThread(self)
        self.worker = CheckUpdatesWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        from PySide6.QtCore import Qt
        self.worker.finished.connect(self._check_updates_done, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_ended)
        self.thread.finished.connect(self.thread.deleteLater)
        self._set_action_buttons_enabled(False)
        self.thread.start()

    def _check_updates_done(self, ok, message, outdated_map):
        self._set_action_buttons_enabled(True)
        self._outdated_map = dict(outdated_map or {}) if ok else {}
        self.refresh()
        if ok:
            QMessageBox.information(self, "检查更新", message)
        else:
            QMessageBox.critical(self, "检查更新失败", message)

    def start_install(self, packages, media, force_title=None):
        if self.thread:
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "安装进行中", "请等待当前安装结束。")
                    return
            except RuntimeError:
                self.thread = None
        self.log.clear(); self.progress.setValue(0)
        if force_title:
            self.log.appendPlainText(force_title)
        self.thread = QThread(self); self.worker = InstallWorker(packages, media); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        from PySide6.QtCore import Qt
        self.worker.finished.connect(self.done, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.thread.quit); self.thread.finished.connect(self._thread_ended)
        self.thread.finished.connect(self.thread.deleteLater)
        self._set_action_buttons_enabled(False)
        self.thread.start()

    def _set_action_buttons_enabled(self, enabled: bool):
        for name in (
            "install_btn", "media_btn", "ytdlp_btn", "refresh_btn",
            "check_update_btn", "update_all_btn",
        ):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    def done(self, ok, message):
        self._set_action_buttons_enabled(True)
        # 安装/更新后清空 outdated 缓存，需重新检查
        if ok:
            self._outdated_map = {}
        self.log.appendPlainText(message)
        self.refresh()
        (QMessageBox.information if ok else QMessageBox.critical)(self, "组件管理", message)

    def _thread_ended(self):
        worker = self.worker
        self.worker = None
        self.thread = None
        if worker is not None:
            worker.deleteLater()
