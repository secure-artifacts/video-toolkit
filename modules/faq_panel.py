"""各功能页共用的「常见问题」折叠面板。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


class CollapsibleSection(QWidget):
    """单条可折叠问答，默认收起。"""

    def __init__(self, icon, title, body, parent=None, expanded=False):
        super().__init__(parent)
        self.icon = icon
        self.title = title
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.btn = QPushButton(f"▶  {self.icon}  {self.title}")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn_style(False)
        self.btn.clicked.connect(self.toggle)

        self.body_widget = QWidget()
        body_layout = QVBoxLayout(self.body_widget)
        body_layout.setContentsMargins(18, 12, 18, 14)
        body_text = QLabel(body)
        body_text.setWordWrap(True)
        body_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_text.setStyleSheet("color:#dbe4f0; font-size:13px; line-height:1.7;")
        body_layout.addWidget(body_text)
        self.body_widget.setStyleSheet(
            "QWidget{background:#0c1424;border-left:1px solid #30445f;"
            "border-right:1px solid #30445f;border-bottom:1px solid #30445f;"
            "border-bottom-left-radius:6px;border-bottom-right-radius:6px;}"
        )
        self.body_widget.setVisible(False)

        root.addWidget(self.btn)
        root.addWidget(self.body_widget)
        if expanded:
            self.toggle()

    def _apply_btn_style(self, open_state: bool):
        if open_state:
            self.btn.setStyleSheet(
                "QPushButton{background:#1e293b;border:1px solid #3b82f6;border-bottom:none;"
                "border-top-left-radius:6px;border-top-right-radius:6px;"
                "border-bottom-left-radius:0;border-bottom-right-radius:0;"
                "padding:11px 14px;text-align:left;font-weight:700;font-size:13px;color:#f8fafc;}"
                "QPushButton:hover{background:#334155;}"
            )
        else:
            self.btn.setStyleSheet(
                "QPushButton{background:#17243a;border:1px solid #30445f;border-radius:6px;"
                "padding:11px 14px;text-align:left;font-weight:700;font-size:13px;color:#e5edf9;}"
                "QPushButton:hover{background:#223654;border-color:#3b82f6;}"
            )

    def toggle(self):
        visible = not self.body_widget.isVisible()
        self.body_widget.setVisible(visible)
        self.btn.setText(f"{'▼' if visible else '▶'}  {self.icon}  {self.title}")
        self._apply_btn_style(visible)


class FaqPanel(QFrame):
    """页面底部常见问题区域：外层可折叠，内层多条问答。"""

    def __init__(self, items, title="常见问题（点击展开）", parent=None, max_height=300):
        super().__init__(parent)
        self.setObjectName("faqPanel")
        self.setStyleSheet(
            "#faqPanel{background:#0b1424;border:1px solid #30445f;border-radius:8px;}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)

        header = QHBoxLayout()
        self.toggle_btn = QPushButton(f"▶  ❓  {title}")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;text-align:left;"
            "font-weight:800;font-size:14px;color:#93c5fd;padding:6px 2px;}"
            "QPushButton:hover{color:#bfdbfe;}"
        )
        self.toggle_btn.clicked.connect(self._toggle_body)
        header.addWidget(self.toggle_btn, 1)
        hint = QLabel("先查这里 · 再看顶部「查看软件日志」")
        hint.setStyleSheet("color:#64748b;font-size:12px;")
        header.addWidget(hint)
        outer.addLayout(header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(2, 0, 2, 0)
        body_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if max_height:
            scroll.setMaximumHeight(max_height)
        scroll.setStyleSheet("background:transparent;")
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        for icon, q_title, body in items:
            content_layout.addWidget(CollapsibleSection(icon, q_title, body))
        content_layout.addStretch(1)
        scroll.setWidget(content)
        body_layout.addWidget(scroll)
        outer.addWidget(self.body)
        self.body.setVisible(False)

    def _toggle_body(self):
        visible = not self.body.isVisible()
        self.body.setVisible(visible)
        text = self.toggle_btn.text()
        if text.startswith("▶"):
            self.toggle_btn.setText("▼" + text[1:])
        elif text.startswith("▼"):
            self.toggle_btn.setText("▶" + text[1:])


def make_faq_panel(page_key: str, parent=None, max_height=300) -> FaqPanel:
    items = FAQ_BY_PAGE.get(page_key) or FAQ_BY_PAGE["general"]
    return FaqPanel(items, parent=parent, max_height=max_height)


# 仅描述软件已有能力：识别 Whisper/Groq/Gemini/ElevenLabs/Gladia；
# 配音 Gemini / ElevenLabs / 微软 edge-tts；云端 Google Drive/Sheets。

FAQ_BY_PAGE = {
    "reels": [
        ("🎬", "三种去口气裁剪模式怎么选？",
         "1）智能混合边界（推荐）：文案边界 + 声音修正口气，最稳。\n"
         "2）仅按文案边界：只按字时间戳，口气重容易漏切。\n"
         "3）快速声音边界：只看音量，速度快，适合大批量。\n"
         "口气不干净时：静音阈值调高到约 -29～-27 dB，最短静音 100～180 ms。"),
        ("🔊", "文字转音频怎么用？（仅现有服务）",
         "1）左侧「文转音」→ 新增/粘贴多行（一行一条）。\n"
         "2）服务：Gemini 自然语音（需 Gemini 密钥）· ElevenLabs（密钥 + Voice ID）· 微软文字转语音（edge-tts）。\n"
         "3）「批量生成并加入音频队列」→「音频」试听。\n"
         "密钥在「设置与组件 → API 密钥管理」添加并诊断。"),
        ("🎧", "音频和视频如何混合？",
         "替换为添加的音频：静音原片，只留配音/BGM。\n"
         "原声＋背景音混合：原声与 BGM 叠加，音量可调。\n"
         "配音更长时：开视频延长（循环 / 冻结尾帧 / 速度拉伸）。\n"
         "列表顺序：视频、音频、文案一一对应。"),
        ("🖥", "比例、分辨率、编码失败？",
         "比例不一致时居中裁剪不拉伸。编码器 auto 会用显卡加速。\n"
         "失败或花屏：改 CPU 模式再导出。预览可用「8 秒精确预览」核对字幕。"),
        ("🩹", "Reels 出问题先做什么？",
         "缺 FFmpeg → 设置与组件修复。\n"
         "配音失败 → 查 Gemini/ElevenLabs 密钥，或微软 TTS 组件。\n"
         "导出失败 → CPU 编码重试。详情看本页日志或顶部「查看软件日志」。"),
    ],
    "screenshot": [
        ("📷", "怎么批量截图？",
         "粘贴链接（每行一个）或添加本地视频 → 设数量、间隔、前缀、目录 → 开始执行。"),
        ("🌐", "网络视频下不下来？",
         "设置与组件更新 yt-dlp；检查网络与完整链接。看本页日志或顶部「查看软件日志」。"),
        ("🩹", "截图失败？",
         "确认 FFmpeg 正常；路径尽量短；先用少量张数试跑。"),
    ],
    "smartcut": [
        ("✂", "两种模式区别？",
         "自定义时长序列：按秒数列表切，可循环。\n"
         "智能画面识别：按场景变化切，阈值越大片段越长。"),
        ("🩹", "剪辑失败？",
         "设置与组件确认 FFmpeg；看日志中的文件名；输出目录需可写。"),
    ],
    "rename": [
        ("A↔", "命名规则？",
         "可组合：前缀 + 日期 + 标题 + 编号 + 后缀；也可标题原样替换。\n"
         "先看右侧预览再执行。智能标题可复用字幕提取结果。"),
        ("🩹", "重命名报错？",
         "建议勾选复制到输出目录；过长路径或非法字符会自动清理，仍失败看执行日志。"),
    ],
    "subtitle": [
        ("CC", "识别服务怎么选？",
         "本地 Whisper：免密钥，推荐先用。\n"
         "在线：Groq / Gemini / ElevenLabs / Gladia（密钥管理添加并诊断）。\n"
         "可开自动续接；结果可复制、导出 .srt。"),
        ("🩹", "识别失败？",
         "401=密钥失效；超时=网络。链接失败更新 yt-dlp。看顶部「查看软件日志」。"),
    ],
    "pipeline": [
        ("⇢", "流水线步骤？",
         "剪辑 → 字幕 → 标题 → 重命名 → 上传 Drive → 填 Google 表。\n"
         "先配好 Google 方案再勾选上传。默认自动续接。"),
        ("🩹", "中断了怎么办？",
         "继续上传 / 继续填表。字幕问题查密钥；剪辑问题查 FFmpeg。"),
    ],
    "metadata": [
        ("⌫", "会清什么？原文件安全吗？",
         "清设备/作者/GPS/EXIF 等，输出副本，不改原文件。\n"
         "文件名、画面里直接出现的隐私需另行处理。"),
    ],
    "settings": [
        ("🛠", "组件与密钥",
         "一键检测/安装 FFmpeg 与依赖；更新 yt-dlp。\n"
         "密钥：Groq、Gemini、ElevenLabs、Gladia。\n"
         "Google 授权与字体管理也在本页各标签中。"),
    ],
    "home": [
        ("🏠", "从哪开始？",
         "顶部导航进功能页。建议：设置检测组件 →（可选）加密钥 → 选业务处理。\n"
         "帮助页有完整步骤；出问题点顶部「查看软件日志」。"),
    ],
    "general": [
        ("🩹", "通用排查",
         "本页日志 → 顶部软件日志 → 设置修 FFmpeg/密钥 → 编码改 CPU 重试。"),
    ],
}
