"""独立「文字转语音」板块。

对齐浏览器插件 Eleven V3 Batch Pro 的扣点方式：
- 网页会话 Bearer / xi-api-key → 官方 api.us.elevenlabs.io TTS
- 批量文案卡片、缓存、导出目录、模型/音色选择

亦支持微软 edge-tts、Gemini；所有生成结果按指纹缓存到输出目录。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QThread, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .path_picker import default_output_path
from .platform_utils import app_data_dir
from .settings_page import find_media_tool, hidden_kwargs

try:
    from . import elevenlabs_web_auth as el_web
except Exception:  # pragma: no cover
    el_web = None

try:
    from .dynamic_caption_page import (
        REVERB_MODE_NAMES,
        apply_ethereal_reverb_file,
        normalize_reverb_mode,
    )
except Exception:  # pragma: no cover
    REVERB_MODE_NAMES = ("小房间", "大厅", "教堂", "板式混响", "回声")

    def normalize_reverb_mode(mode):
        return str(mode or "小房间")

    def apply_ethereal_reverb_file(*_a, **_k):
        pass


CACHE_DIR_NAME = ".tts_cache"
DRAFT_FILE = app_data_dir() / "tts_studio" / "drafts.json"


def _safe_stem(text: str, index: int) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())[:40]
    raw = re.sub(r'[\\/:*?"<>|]+', "_", raw).strip(" ._") or f"item_{index:03d}"
    return raw


def _fingerprint(service: str, voice: str, model: str, text: str,
                 reverb: bool, amount: int, mode: str) -> str:
    payload = (
        f"{service}\n{voice}\n{model}\n{text.strip()}\n"
        f"rvb={int(reverb)}:{amount}:{mode}:v1"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TtsBatchWorker(QObject):
    progress = Signal(int, int, str)  # done, total, message
    item_done = Signal(int, bool, str, str)  # index, ok, path_or_err, message
    finished = Signal(bool, str)

    def __init__(self, jobs, generate_fn, output_dir, use_cache=True):
        super().__init__()
        self.jobs = list(jobs or [])  # dict: text, service, voice, model, reverb...
        self.generate_fn = generate_fn
        self.output_dir = Path(output_dir)
        self.use_cache = bool(use_cache)
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            cache_root = self.output_dir / CACHE_DIR_NAME
            cache_root.mkdir(parents=True, exist_ok=True)
            total = max(1, len(self.jobs))
            ok_n = 0
            fail_n = 0
            for i, job in enumerate(self.jobs):
                if self.cancelled:
                    self.finished.emit(False, f"已停止：成功 {ok_n}，失败 {fail_n}，未处理 {total - i}")
                    return
                text = str(job.get("text") or "").strip()
                if not text:
                    self.item_done.emit(i, False, "", "空文案，已跳过")
                    fail_n += 1
                    continue
                service = str(job.get("service") or "微软文字转语音")
                voice = str(job.get("voice") or "")
                model = str(job.get("model") or "eleven_flash_v2_5")
                reverb = bool(job.get("reverb"))
                amount = int(job.get("reverb_amount") or 30)
                mode = normalize_reverb_mode(job.get("reverb_mode") or "小房间")
                fp = _fingerprint(service, voice, model, text, reverb, amount, mode)
                cache_mp3 = cache_root / f"{fp[:20]}.mp3"
                cache_meta = cache_root / f"{fp[:20]}.json"
                name = f"{i + 1:03d}_{_safe_stem(text, i + 1)}.mp3"
                dest = self.output_dir / name
                # 避免重名覆盖
                n = 2
                while dest.exists() and dest.resolve() != cache_mp3.resolve():
                    dest = self.output_dir / f"{i + 1:03d}_{_safe_stem(text, i + 1)}_{n}.mp3"
                    n += 1

                try:
                    if self.use_cache and cache_mp3.is_file() and cache_mp3.stat().st_size > 256:
                        shutil.copy2(cache_mp3, dest)
                        self.item_done.emit(i, True, str(dest), "缓存命中")
                        ok_n += 1
                    else:
                        self.progress.emit(i, total, f"生成中 {i + 1}/{total}…")
                        path = Path(self.generate_fn(
                            text, service, voice, str(cache_mp3), model=model,
                        ))
                        if not path.is_file() or path.stat().st_size < 256:
                            raise RuntimeError("未生成有效音频")
                        if reverb:
                            ffmpeg = find_media_tool("ffmpeg")
                            if ffmpeg:
                                apply_ethereal_reverb_file(ffmpeg, path, amount, mode=mode)
                        cache_meta.write_text(json.dumps({
                            "fingerprint": fp,
                            "service": service,
                            "voice": voice,
                            "model": model,
                            "reverb": reverb,
                            "chars": len(text),
                            "created": time.time(),
                        }, ensure_ascii=False, indent=2), encoding="utf-8")
                        if path.resolve() != dest.resolve():
                            shutil.copy2(path, dest)
                        self.item_done.emit(i, True, str(dest), "生成成功")
                        ok_n += 1
                except Exception as exc:
                    fail_n += 1
                    self.item_done.emit(i, False, "", str(exc))
                self.progress.emit(i + 1, total, f"进度 {i + 1}/{total}")
                # 插件同款：条目间稍作间隔，降低风控
                if i + 1 < total and not self.cancelled and service == "ElevenLabs":
                    time.sleep(1.2)
            msg = f"完成：成功 {ok_n}，失败 {fail_n}。\n输出：{self.output_dir}"
            self.finished.emit(fail_n == 0, msg)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class TtsPage(QWidget):
    """独立文字转语音工作台。"""

    navigate_requested = Signal(int)

    def __init__(self, text_to_speech_fn=None, store=None, parent=None):
        super().__init__(parent)
        self._tts_fn = text_to_speech_fn
        self.store = store
        self.thread = None
        self.worker = None
        self._cards: list[QPlainTextEdit] = []
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._build_ui()
        self._load_drafts()
        self.refresh_voices()

    # ── UI ─────────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        # 左侧控制
        left = QVBoxLayout()
        left.setSpacing(10)
        title = QLabel("文字转语音")
        title.setObjectName("heading")
        left.addWidget(title)
        tip = QLabel(
            "独立配音工坊 · 三种引擎互不影响：\n"
            "• 微软：edge-tts 免费，选 Neural 音色即可（没有 Flash 模型）\n"
            "• ElevenLabs：密钥/网页会话 + EL 模型 + Voice ID，扣官方点数\n"
            "• Gemini：需 Gemini Key + 预置音色名\n"
            "支持批量卡片、Excel 粘贴、本地缓存、混响、试听"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#94a3b8;font-size:12px;")
        left.addWidget(tip)

        form = QFormLayout()
        self._form = form
        self.service = QComboBox()
        self.service.addItems(["微软文字转语音", "ElevenLabs", "Gemini 自然语音"])
        self.service.currentTextChanged.connect(self._on_service_changed)
        form.addRow("引擎", self.service)

        # —— 仅 ElevenLabs 显示 ——
        self.model = QComboBox()
        if el_web:
            for mid, label in el_web.TTS_MODEL_CHOICES:
                self.model.addItem(label, mid)
        else:
            self.model.addItem("Flash v2.5", "eleven_flash_v2_5")
        self.model.setToolTip("仅 ElevenLabs 有效。微软/Gemini 无此概念，选其它引擎时会自动隐藏。")
        form.addRow("EL 模型", self.model)
        self._model_row = form.rowCount() - 1

        voice_row = QHBoxLayout()
        self.voice = QComboBox()
        self.voice.setEditable(True)
        self.voice.setMinimumWidth(220)
        self.voice.setPlaceholderText("音色")
        self.refresh_btn = QPushButton("刷新音色")
        self.refresh_btn.setToolTip("ElevenLabs：从账号拉取音色列表；微软/Gemini：恢复内置列表")
        self.refresh_btn.clicked.connect(self.refresh_voices)
        voice_row.addWidget(self.voice, 1)
        voice_row.addWidget(self.refresh_btn)
        form.addRow("音色", voice_row)
        self._voice_row = form.rowCount() - 1

        self.output = QLineEdit(str(default_output_path("tts_outputs")))
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        pick = QPushButton("…")
        pick.clicked.connect(self._pick_output)
        out_row.addWidget(pick)
        form.addRow("输出目录", out_row)

        self.use_cache = QCheckBox("启用缓存（相同参数不重复生成）")
        self.use_cache.setChecked(True)
        form.addRow(self.use_cache)

        self.reverb = QCheckBox("混响")
        self.reverb.setChecked(False)
        self.reverb_mode = QComboBox()
        self.reverb_mode.addItems(list(REVERB_MODE_NAMES))
        self.reverb_mode.setCurrentText("小房间")
        self.reverb_amt = QSpinBox()
        self.reverb_amt.setRange(10, 100)
        self.reverb_amt.setValue(30)
        self.reverb_amt.setSuffix("%")
        rv = QHBoxLayout()
        rv.addWidget(self.reverb)
        rv.addWidget(self.reverb_mode)
        rv.addWidget(self.reverb_amt)
        rv.addStretch(1)
        form.addRow("音效", rv)

        left.addLayout(form)

        self.quota_label = QLabel("")
        self.quota_label.setWordWrap(True)
        self.quota_label.setStyleSheet("color:#7dd3fc;font-size:12px;")
        left.addWidget(self.quota_label)

        self.keys_btn = QPushButton("打开密钥管理（ElevenLabs / Gemini）")
        self.keys_btn.clicked.connect(lambda: self.navigate_requested.emit(7))
        left.addWidget(self.keys_btn)

        self.progress = QProgressBar()
        left.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        left.addWidget(self.log, 1)

        actions = QHBoxLayout()
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.run_btn = QPushButton("开始批量生成")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._start)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.run_btn)
        left.addLayout(actions)

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setMinimumWidth(360)
        left_w.setMaximumWidth(440)

        # 右侧文案列表
        right = QVBoxLayout()
        bar = QHBoxLayout()
        bar.addWidget(QLabel("文案列表（支持 Excel/表格多行粘贴）"))
        bar.addStretch(1)
        add_btn = QPushButton("+ 新增")
        add_btn.clicked.connect(lambda: self._add_card(""))
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_cards)
        paste_btn = QPushButton("粘贴导入")
        paste_btn.clicked.connect(self._paste_import)
        bar.addWidget(paste_btn)
        bar.addWidget(clear_btn)
        bar.addWidget(add_btn)
        right.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_host)
        right.addWidget(self.scroll, 1)

        self.stats = QLabel("总字数: 0  ·  预计消耗: 0 字符（EL）")
        self.stats.setStyleSheet("color:#94a3b8;")
        right.addWidget(self.stats)

        right_w = QWidget()
        right_w.setLayout(right)

        split = QSplitter()
        split.addWidget(left_w)
        split.addWidget(right_w)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        root.addWidget(split)

        self._on_service_changed(self.service.currentText())
        if not self._cards:
            self._add_card("")

    def _add_card(self, text: str = ""):
        box = QGroupBox(f"#{len(self._cards) + 1}")
        lay = QVBoxLayout(box)
        ta = QPlainTextEdit()
        ta.setPlaceholderText("在此输入或粘贴文案…")
        ta.setPlainText(text)
        ta.setMinimumHeight(72)
        ta.textChanged.connect(self._update_stats)
        ta.textChanged.connect(self._save_drafts)
        lay.addWidget(ta)
        row = QHBoxLayout()
        play = QPushButton("试听最近生成")
        play.clicked.connect(lambda _=False, t=ta: self._play_latest_for(t))
        rm = QPushButton("删除")
        rm.clicked.connect(lambda _=False, b=box, t=ta: self._remove_card(b, t))
        row.addWidget(play)
        row.addStretch(1)
        row.addWidget(rm)
        lay.addLayout(row)
        # insert before stretch
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, box)
        self._cards.append(ta)
        self._renumber()
        self._update_stats()

    def _remove_card(self, box: QGroupBox, ta: QPlainTextEdit):
        if ta in self._cards:
            self._cards.remove(ta)
        box.setParent(None)
        box.deleteLater()
        if not self._cards:
            self._add_card("")
        self._renumber()
        self._update_stats()
        self._save_drafts()

    def _clear_cards(self):
        if QMessageBox.question(self, "清空", "清空所有文案？") != QMessageBox.StandardButton.Yes:
            return
        for ta in list(self._cards):
            w = ta.parent()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()
        self._add_card("")
        self._save_drafts()

    def _renumber(self):
        for i, ta in enumerate(self._cards):
            p = ta.parent()
            if isinstance(p, QGroupBox):
                p.setTitle(f"#{i + 1}")

    def _paste_import(self):
        text = QApplication.clipboard().text() or ""
        if not text.strip():
            QMessageBox.information(self, "粘贴", "剪贴板为空。")
            return
        segments = [s.strip() for s in re.split(r"[\r\n\t]+", text) if s.strip()]
        if len(segments) <= 1 and "\t" not in text and text.count("\n") < 1:
            # 单段 → 填入当前空卡
            if self._cards and not self._cards[-1].toPlainText().strip():
                self._cards[-1].setPlainText(text.strip())
            else:
                self._add_card(text.strip())
        else:
            empty_only = len(self._cards) == 1 and not self._cards[0].toPlainText().strip()
            if empty_only:
                self._cards[0].parent().setParent(None)
                self._cards.clear()
            for s in segments:
                self._add_card(s)
        self._update_stats()
        self._save_drafts()
        self.log.appendPlainText(f"已导入 {len(segments)} 条文案")

    def _update_stats(self):
        texts = [ta.toPlainText().strip() for ta in self._cards if ta.toPlainText().strip()]
        chars = sum(len(t) for t in texts)
        name = self.service.currentText() if hasattr(self, "service") else ""
        if "Eleven" in (name or ""):
            extra = f"预计 EL 消耗: {chars} 字符"
        elif "微软" in (name or ""):
            extra = "微软 edge-tts · 免费不扣点数"
        elif "Gemini" in (name or ""):
            extra = "Gemini TTS · 按 Google 配额计费"
        else:
            extra = ""
        self.stats.setText(f"条目: {len(texts)}  ·  总字数: {chars}  ·  {extra}")

    def _save_drafts(self):
        try:
            DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
            drafts = [ta.toPlainText() for ta in self._cards]
            DRAFT_FILE.write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_drafts(self):
        try:
            if DRAFT_FILE.is_file():
                data = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    for t in data:
                        self._add_card(str(t or ""))
                    return
        except Exception:
            pass
        self._add_card("")

    def _pick_output(self):
        d = QFileDialog.getExistingDirectory(self, "输出目录", self.output.text())
        if d:
            self.output.setText(d)

    def _on_service_changed(self, name: str):
        """按引擎切换控件：微软/Gemini 无 EL 模型；额度条只对 ElevenLabs 有意义。"""
        name = name or ""
        is_el = "Eleven" in name
        is_ms = "微软" in name
        is_gem = "Gemini" in name

        # 整行显示/隐藏（Qt6 setRowVisible）
        try:
            self._form.setRowVisible(self._model_row, is_el)
        except Exception:
            self.model.setVisible(is_el)
            self.model.setEnabled(is_el)

        self.quota_label.setVisible(True)
        self.keys_btn.setVisible(is_el or is_gem)

        if is_ms:
            try:
                self._form.setRowVisible(self._voice_row, True)
                # 改标签文字
                lab = self._form.itemAt(self._voice_row, QFormLayout.ItemRole.LabelRole)
                if lab and lab.widget():
                    lab.widget().setText("微软音色")
            except Exception:
                pass
            self.voice.setPlaceholderText("如 zh-CN-XiaoxiaoNeural")
            self.voice.setEditable(True)
            self.refresh_btn.setText("恢复默认音色")
            self.use_cache.setText("启用缓存（相同文案/音色不重复生成）")
            self.quota_label.setText("当前引擎：微软 edge-tts（免费 · 无密钥 · 无 Flash 模型）")
            self.quota_label.setStyleSheet("color:#86efac;font-size:12px;")
            self.voice.blockSignals(True)
            self.voice.clear()
            for v in (
                "zh-CN-XiaoxiaoNeural｜晓晓（中文）",
                "zh-CN-YunxiNeural｜云希（中文）",
                "zh-CN-XiaoyiNeural｜晓伊",
                "pt-BR-FranciscaNeural｜Francisca（葡语-巴西）",
                "pt-PT-RaquelNeural｜Raquel（葡语-葡萄牙）",
                "en-US-JennyNeural｜Jenny（英语）",
                "en-US-GuyNeural｜Guy（英语）",
                "es-ES-ElviraNeural｜Elvira（西语）",
                "fr-FR-DeniseNeural｜Denise（法语）",
                "ja-JP-NanamiNeural｜Nanami（日语）",
                "ko-KR-SunHiNeural｜SunHi（韩语）",
                "ar-SA-ZariyahNeural｜Zariyah（阿语）",
            ):
                self.voice.addItem(v)
            self.voice.setCurrentIndex(0)
            self.voice.blockSignals(False)
        elif is_gem:
            try:
                lab = self._form.itemAt(self._voice_row, QFormLayout.ItemRole.LabelRole)
                if lab and lab.widget():
                    lab.widget().setText("Gemini 音色")
            except Exception:
                pass
            self.voice.setPlaceholderText("预置音色名，如 Kore")
            self.voice.setEditable(True)
            self.refresh_btn.setText("恢复默认音色")
            self.use_cache.setText("启用缓存（相同文案/音色不重复生成）")
            self.quota_label.setText("当前引擎：Gemini（需 API Key · 无 EL 模型）")
            self.quota_label.setStyleSheet("color:#7dd3fc;font-size:12px;")
            self.keys_btn.setText("打开密钥管理（添加 Gemini Key）")
            self.voice.blockSignals(True)
            self.voice.clear()
            for v in ("Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"):
                self.voice.addItem(v)
            self.voice.setCurrentIndex(0)
            self.voice.blockSignals(False)
        else:
            try:
                lab = self._form.itemAt(self._voice_row, QFormLayout.ItemRole.LabelRole)
                if lab and lab.widget():
                    lab.widget().setText("EL 音色")
            except Exception:
                pass
            self.voice.setPlaceholderText("Voice ID 或从列表选择")
            self.voice.setEditable(True)
            self.refresh_btn.setText("刷新音色/额度")
            self.use_cache.setText("启用缓存（相同文案/音色/模型不重复扣点）")
            self.keys_btn.setText("打开密钥管理（网页会话 / sk_ API Key）")
            self.quota_label.setText("当前引擎：ElevenLabs · 点击「刷新音色/额度」同步…")
            self.quota_label.setStyleSheet("color:#fbbf24;font-size:12px;")
            self.refresh_voices()

        self._update_stats()

    def refresh_voices(self):
        name = self.service.currentText() or ""
        if "微软" in name or "Gemini" in name:
            # 重新填默认列表
            self._on_service_changed(name)
            self.log.appendPlainText(f"已恢复 {name} 默认音色列表")
            return
        if not self.store or not el_web:
            self.quota_label.setText("ElevenLabs：无 store / 模块不可用")
            return
        self.quota_label.setText("ElevenLabs 额度：刷新中…")
        try:
            candidates = self.store.candidates("ElevenLabs")
        except Exception:
            candidates = []
        if not candidates:
            self.quota_label.setText("ElevenLabs 额度：无凭证（请到密钥管理添加网页会话或 sk_）")
            return
        secret = candidates[0].get("key") or ""
        try:
            ok, msg, quota = el_web.verify_session(secret, timeout=35)
            if quota:
                self.quota_label.setText(
                    f"ElevenLabs：{quota.get('usage', '?')}/{quota.get('limit', '?')} "
                    f"剩余 {quota.get('remaining', '?')}"
                    + (" · TTS可用" if quota.get("tts_ok") else " · ⚠️TTS可能被风控")
                )
            else:
                self.quota_label.setText(msg[:120])
            voices = el_web.list_voices(secret, timeout=40)
            cur = self.voice.currentText()
            self.voice.clear()
            for v in voices:
                self.voice.addItem(v.get("display") or v.get("voice_id"), v.get("voice_id"))
            if cur:
                idx = self.voice.findText(cur)
                if idx >= 0:
                    self.voice.setCurrentIndex(idx)
            self.log.appendPlainText(f"已同步 {len(voices)} 个 ElevenLabs 音色")
        except Exception as exc:
            self.quota_label.setText(f"刷新失败：{exc}")
            self.log.appendPlainText(f"刷新音色失败：{exc}")

    def _voice_id(self) -> str:
        data = self.voice.currentData()
        if data:
            return str(data)
        text = self.voice.currentText().strip()
        return text.split("｜", 1)[0].strip()

    def _model_id(self) -> str:
        data = self.model.currentData()
        return str(data or "eleven_flash_v2_5")

    def _generate_one(self, text, service, voice, destination, model="eleven_flash_v2_5"):
        """Wrapper: app._text_to_speech 签名无 model；EL 时写入侧车后调用。"""
        if not callable(self._tts_fn):
            raise RuntimeError("未绑定 TTS 引擎")
        # 通过环境变量把 model 传给 app 层（最小侵入）
        old = os.environ.get("VIDEO_TOOLKIT_EL_MODEL")
        try:
            if service == "ElevenLabs":
                os.environ["VIDEO_TOOLKIT_EL_MODEL"] = model
            return self._tts_fn(text, service, voice, destination)
        finally:
            if old is None:
                os.environ.pop("VIDEO_TOOLKIT_EL_MODEL", None)
            else:
                os.environ["VIDEO_TOOLKIT_EL_MODEL"] = old

    def _start(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "进行中", "请等待当前任务结束。")
            return
        texts = [ta.toPlainText().strip() for ta in self._cards if ta.toPlainText().strip()]
        if not texts:
            QMessageBox.information(self, "没有文案", "请先添加至少一条文案。")
            return
        service = self.service.currentText()
        voice = self._voice_id()
        model = self._model_id()
        jobs = [{
            "text": t,
            "service": service,
            "voice": voice,
            "model": model,
            "reverb": self.reverb.isChecked(),
            "reverb_amount": self.reverb_amt.value(),
            "reverb_mode": self.reverb_mode.currentText(),
        } for t in texts]
        self.log.appendPlainText(f"开始批量：{len(jobs)} 条 · {service} · {voice}")
        self.progress.setValue(0)
        self.thread = QThread(self)
        self.worker = TtsBatchWorker(
            jobs, self._generate_one, self.output.text(), self.use_cache.isChecked(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._ended)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.thread.start()

    def _stop(self):
        if self.worker:
            self.worker.cancel()

    def _on_progress(self, done, total, msg):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        if msg:
            self.log.appendPlainText(msg)

    def _on_item(self, index, ok, path, message):
        tag = "OK" if ok else "失败"
        self.log.appendPlainText(f"[{index + 1}] {tag} {message} {path}")

    def _on_finished(self, ok, message):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "文字转语音", message)

    def _ended(self):
        self.worker = None
        self.thread = None
        if "Eleven" in self.service.currentText():
            self.refresh_voices()

    def _play_latest_for(self, ta: QPlainTextEdit):
        text = ta.toPlainText().strip()
        if not text:
            return
        out = Path(self.output.text())
        # 找最近修改、文件名含文案前缀的 mp3
        candidates = sorted(out.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
        stem = _safe_stem(text, 0)[:20]
        pick = None
        for p in candidates:
            if stem[:12] in p.stem:
                pick = p
                break
        if not pick and candidates:
            pick = candidates[0]
        if not pick:
            QMessageBox.information(self, "试听", "还没有生成文件。")
            return
        self._player.setSource(QUrl.fromLocalFile(str(pick.resolve())))
        self._audio_out.setVolume(0.9)
        self._player.play()
        self.log.appendPlainText(f"试听：{pick.name}")
