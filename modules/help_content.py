"""帮助页正文：更新日志 + 使用说明 + 常见问题。

常见问题集中在本页；设置页与帮助页共用左侧导航布局风格。
"""

# 识别：本地 Whisper、Groq、Gemini、ElevenLabs、Gladia
# 配音：Gemini 自然语音、ElevenLabs、微软文字转语音
# 云端：Google Drive / Sheets


def _step(n, title, body):
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px 0;">'
        f"<tr>"
        f'<td width="36" valign="top">'
        f'<div style="background:#2563eb;color:#ffffff;width:28px;height:28px;'
        f"text-align:center;font-weight:800;font-size:14px;border-radius:14px;"
        f'line-height:28px;">{n}</div></td>'
        f'<td valign="top" style="padding-left:8px;color:#e2e8f0;font-size:15px;line-height:1.75;">'
        f'<span style="color:#f8fafc;font-weight:700;">{title}</span><br/>{body}</td>'
        f"</tr></table>"
    )


def _h1(text):
    return f'<p style="font-size:20px;font-weight:800;color:#f8fafc;margin:18px 0 12px 0;">{text}</p>'


def _h2(text):
    return f'<p style="font-size:16px;font-weight:700;color:#93c5fd;margin:16px 0 8px 0;">{text}</p>'


def _p(text):
    return f'<p style="color:#cbd5e1;font-size:15px;line-height:1.75;margin:0 0 12px 0;">{text}</p>'


def _tip(text):
    return (
        f'<p style="background:#0b1830;border:1px solid #1e3a5f;color:#bae6fd;'
        f'font-size:14px;line-height:1.7;padding:12px 14px;margin:14px 0;">{text}</p>'
    )


def _ul(items):
    lis = "".join(
        f'<li style="margin:6px 0;color:#cbd5e1;font-size:15px;line-height:1.7;">{x}</li>'
        for x in items
    )
    return f'<ul style="margin:6px 0 14px 22px;padding:0;">{lis}</ul>'


def _table(headers, rows):
    th = "".join(
        f'<th style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;'
        f'padding:10px 12px;text-align:left;font-size:14px;">{h}</th>'
        for h in headers
    )
    trs = []
    for row in rows:
        tds = "".join(
            f'<td style="background:#0f172a;color:#cbd5e1;border:1px solid #334155;'
            f'padding:10px 12px;font-size:14px;line-height:1.6;">{c}</td>'
            for c in row
        )
        trs.append(f"<tr>{tds}</tr>")
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:10px 0 16px 0;">'
        f"<tr>{th}</tr>{''.join(trs)}</table>"
    )


def _anchor(name):
    return f'<a name="{name}"></a>'


def _qa(question, answer_html, accent="#3b82f6"):
    return (
        f'<p style="font-size:15px;font-weight:700;color:#f1f5f9;margin:14px 0 6px 0;">'
        f"Q. {question}</p>"
        f'<p style="color:#cbd5e1;font-size:14px;line-height:1.75;margin:0 0 10px 0;'
        f"padding:10px 12px;background:#111827;border-left:4px solid {accent};"
        f'border-radius:0 8px 8px 0;">{answer_html}</p>'
    )


def _section_banner(icon, title, color="#2563eb", subtitle=""):
    """分类标题：色底标题 + 紧贴文字下方、与标题同宽的下划线。

    Qt QTextBrowser 对 CSS 支持有限：标题与色条放在同一窄表内，
    第二行仅标题单元格着色，故下划线长度≈标题宽度且紧贴文字。
    """
    light_bg = color.lower() in (
        "#fbbf24", "#fde047", "#facc15", "#a3e635", "#86efac", "#67e8f9", "#e2e8f0",
    )
    fg = "#0f172a" if light_bg else "#ffffff"
    label = f"{icon}&nbsp;{title}"
    sub_cell = ""
    under_empty = ""
    if subtitle:
        sub_cell = (
            f'<td style="padding:0 0 0 8px;vertical-align:middle;">'
            f'<span style="color:#94a3b8;font-size:12px;">{subtitle}</span></td>'
        )
        under_empty = (
            '<td style="padding:0;font-size:1px;line-height:3px;height:3px;">&nbsp;</td>'
        )
    return (
        f'<p style="margin:14px 0 6px 0;">'
        f'<table cellspacing="0" cellpadding="0" style="margin:0;border-collapse:collapse;">'
        f"<tr>"
        f'<td style="padding:0;margin:0;line-height:1.2;">'
        f'<span style="font-size:15px;font-weight:800;color:{fg};'
        f"background-color:{color};padding:3px 10px 1px 10px;\">"
        f"{label}</span></td>{sub_cell}</tr>"
        f"<tr>"
        f'<td style="padding:0;margin:0;background-color:{color};'
        f'font-size:1px;line-height:3px;height:3px;">&nbsp;</td>'
        f"{under_empty}</tr>"
        f"</table></p>"
    )


def _changelog_item(ver, date, items):
    lis = "".join(f'<li style="margin:5px 0;color:#cbd5e1;font-size:14px;line-height:1.65;">{x}</li>' for x in items)
    return (
        f'<p style="font-size:16px;font-weight:800;color:#93c5fd;margin:16px 0 6px 0;">'
        f"v{ver} <span style=\"color:#64748b;font-weight:600;font-size:13px;\">{date}</span></p>"
        f'<ul style="margin:0 0 12px 20px;padding:0;">{lis}</ul>'
    )


# 右侧顶部快速跳转（常见问题页）
FAQ_JUMP = [
    ("faq-reels", "🎬 Reels"),
    ("faq-screenshot", "📷 截图"),
    ("faq-smartcut", "✂ 剪辑"),
    ("faq-rename", "A↔ 重命名"),
    ("faq-subtitle", "CC 字幕"),
    ("faq-pipeline", "⇢ 流水线"),
    ("faq-metadata", "⌫ 元数据"),
    ("faq-settings", "⚙ 设置"),
    ("faq-lang", "🌐 语言"),
    ("faq-general", "💡 通用"),
]


def _build_changelog_html():
    return (
        _h1("📋 更新日志")
        + _p("新功能与重要改进一览。日常使用请看左侧其它章节；细节问答见「常见问题」。")
        + _changelog_item(
            "1.7.7",
            "2026-07-24",
            [
                "<b>多语言书写规范</b>：内置 en/pt/es/fr/de/it/el/ru/tr/zh/ar/he；"
                "字幕/流水线/Reels 可选书写语言；希腊 «»、西语 ¿¡、阿/希 RTL 整句烧录。",
                "<b>语言包导入</b>：设置 → 字体与语言包，可导入 JSON 扩展新语言。",
                "<b>API 密钥</b>：合并录入 + 自动识别服务（gsk_/AIza/sk_/UUID）。",
                "<b>帮助 / 设置</b>：左右分区导航；更新日志置顶；常见问题分色标题条。",
                "<b>智能剪辑 / 批量截图</b>：左配置、右日志，与流水线统一。",
                "<b>滚轮防误触</b>：下拉/数字框需点击聚焦后才响应滚轮。",
                "<b>稳定性</b>：密钥检测、检查更新/下载线程安全修复，避免检测后闪退。",
                "顶部「检查更新」与启动静默检查：从 GitHub Releases 拉取 Setup 安装包。",
            ],
        )
        + _changelog_item(
            "1.7.6",
            "2026-07-23",
            [
                "检查更新相关线程安全与死锁修复。",
            ],
        )
        + _changelog_item(
            "1.7.x",
            "既有能力",
            [
                "Reels：分组去口气、TTS、混音、字幕样式、水印、云端上传填表。",
                "字幕提取：本地 Whisper + Groq/Gemini/ElevenLabs/Gladia。",
                "自动流水线：剪辑→字幕→标题→重命名→上传→填表。",
                "批量截图 / 智能剪辑 / 重命名 / 清除元数据；组件一键检测。",
            ],
        )
        + _tip("顶部「检查更新」下载 GitHub 上的 Setup 安装包；发布新版时请同步更新本页与 VERSION 文件。")
    )


def _build_faq_html():
    parts = [
        _h1("❓ 各板块常见问题"),
        _p("按业务分类。用上方「快速跳转」一键定位；分类标题带图标与色条便于识别。"),
        _tip("排查顺序：当前页日志 → 顶部「查看软件日志」→「设置与组件」修 FFmpeg/密钥。"),
        # Reels
        _anchor("faq-reels"),
        _section_banner("🎬", "Reels 编辑器", "#059669", "去口气 · TTS · 混音 · 渲染"),
        _qa(
            "三种去口气裁剪模式怎么选？",
            "1）<b>智能混合边界（推荐）</b>：文案边界 + 声音修正口气，最稳。<br/>"
            "2）<b>仅按文案边界</b>：只按字时间戳，口气重容易漏切。<br/>"
            "3）<b>快速声音边界</b>：只看音量，速度快，适合大批量。<br/>"
            "口气不干净：静音阈值约 -29～-27 dB，最短静音 100～180 ms。",
            "#059669",
        ),
        _qa(
            "文字转音频怎么用？",
            "左侧「文转音」→ 新增/粘贴多行 → 选 <b>Gemini / ElevenLabs / 微软 TTS</b> → 批量生成并加入音频队列。",
            "#059669",
        ),
        _qa(
            "音频视频如何混合？",
            "<b>替换为添加的音频</b> 或 <b>原声＋背景音混合</b>。配音更长可开视频延长（循环/冻帧/拉伸）。",
            "#059669",
        ),
        _qa(
            "比例、编码失败？",
            "比例不一致居中裁剪。失败请改 <b>CPU 模式</b>。可用 8 秒精确预览核对字幕。",
            "#059669",
        ),
        # screenshot
        _anchor("faq-screenshot"),
        _section_banner("📷", "批量截图", "#0ea5e9", "链接 / 本地 · 间隔 · yt-dlp"),
        _qa("怎么批量截图？", "粘贴链接（每行一个）或本地视频 → 数量/间隔/前缀/目录 → 开始。", "#0ea5e9"),
        _qa("网络下不下来？", "设置里更新 yt-dlp；检查网络与完整链接。", "#0ea5e9"),
        # smartcut
        _anchor("faq-smartcut"),
        _section_banner("✂", "智能剪辑", "#a78bfa", "时长序列 · 场景识别"),
        _qa(
            "两种模式？",
            "<b>自定义时长序列</b>按秒数列表切；<b>智能画面识别</b>按场景切，阈值越大片段越长。",
            "#a78bfa",
        ),
        # rename
        _anchor("faq-rename"),
        _section_banner("A↔", "批量重命名", "#fbbf24", "规则 · 智能标题 · 预览"),
        _qa(
            "命名规则？",
            "前缀+日期+标题+编号+后缀，或标题原样替换。先看右侧预览。",
            "#fbbf24",
        ),
        # subtitle
        _anchor("faq-subtitle"),
        _section_banner("CC", "字幕提取", "#fb7185", "Whisper · 在线 API · 书写规范"),
        _qa(
            "识别服务怎么选？",
            "<b>本地 Whisper</b>免密钥；在线 Groq/Gemini/ElevenLabs/Gladia 需密钥。"
            "「语言/书写规范」可选自动或指定 el/ar 等。",
            "#fb7185",
        ),
        _qa("识别失败？", "401=密钥失效；超时=网络。链接失败更新 yt-dlp。", "#fb7185"),
        # pipeline
        _anchor("faq-pipeline"),
        _section_banner("⇢", "自动流水线", "#22d3ee", "剪辑→字幕→重命名→上传填表"),
        _qa(
            "中断了怎么办？",
            "「继续上传」「继续填表」。字幕查密钥；剪辑查 FFmpeg。",
            "#22d3ee",
        ),
        # metadata
        _anchor("faq-metadata"),
        _section_banner("⌫", "清除元数据", "#60a5fa", "隐私 · 输出副本"),
        _qa(
            "会清什么？原文件安全吗？",
            "清设备/作者/GPS/EXIF 等，输出副本，不改原文件。",
            "#60a5fa",
        ),
        # settings
        _anchor("faq-settings"),
        _section_banner("⚙", "设置与组件", "#94a3b8", "组件 · 字体语言包 · Google · 密钥"),
        _qa(
            "左侧四个入口做什么？",
            "① 组件检测与安装　② 字体与语言包　③ Google 授权与同步　④ API 密钥管理。",
            "#64748b",
        ),
        # language
        _anchor("faq-lang"),
        _section_banner("🌐", "多语言与书写规范", "#38bdf8", "语言包 · RTL · 导入扩展"),
        _qa(
            "语言包是什么？要装系统语言吗？",
            "<b>不需要系统语言包</b>。书写规则内置在软件中（引号、¿¡、RTL 等）。"
            "可在「设置 → 字体与语言包」导入 JSON 扩展新语言。",
            "#38bdf8",
        ),
        _qa(
            "阿拉伯/希伯来怎么显示？",
            "默认整句 RTL + 字间距 0。Reels 可选「RTL 逐词高亮（实验）」。请用支持该文种的字体。",
            "#38bdf8",
        ),
        _qa(
            "西语 / 希腊引号？",
            "选对应书写语言或自动检测：西语补 ¿¡；希腊等用 «…» 等规范引号。",
            "#38bdf8",
        ),
        # general
        _anchor("faq-general"),
        _section_banner("💡", "通用", "#e2e8f0", "入口 · 日志 · 更新"),
        _qa(
            "从哪开始？",
            "先看「更新日志」了解新功能 →「快速上手」5 步 → 进业务页。",
            "#94a3b8",
        ),
        _qa(
            "通用排查？",
            "当前页日志 → 顶部软件日志 → 设置修 FFmpeg/密钥 → 编码改 CPU。",
            "#94a3b8",
        ),
    ]
    return "".join(parts)


HELP_TABS = [
    {
        "key": "changelog",
        "icon": "📋",
        "title": "📋 更新日志",
        "html": _build_changelog_html(),
    },
    {
        "key": "start",
        "icon": "🚀",
        "title": "🚀 快速上手",
        "html": (
            _h1("🚀 第一次使用：按这 5 步走")
            + _step(
                1,
                "确认组件正常",
                "顶部进入「设置与组件」→ 左侧「组件检测」→「重新检测全部」。<br/>"
                "缺少 FFmpeg 时一键安装或重装媒体组件。",
            )
            + _step(
                2,
                "需要在线能力时再加密钥",
                "左侧「API 密钥管理」添加 Groq / Gemini / ElevenLabs / Gladia。<br/>"
                "只用本地 Whisper 可不加密钥。",
            )
            + _step(
                3,
                "（可选）字体与语言包",
                "「字体与语言包」导入 TTF 或下载开源字体；可导入 JSON 语言包扩展书写规范。",
            )
            + _step(
                4,
                "进入业务页处理素材",
                "截图 · 剪辑 · Reels · 重命名 · 元数据 · 字幕 · 流水线。拖入文件/文件夹即可。",
            )
            + _step(
                5,
                "出错时怎么查",
                "当前页日志 → 顶部「查看软件日志」→ 设置修组件/密钥 → 帮助「常见问题」。",
            )
            + _tip("推荐流程：清元数据（可选）→ 剪辑或 Reels → 重命名 → 流水线上传填表（可选）")
        ),
    },
    {
        "key": "reels",
        "icon": "🎬",
        "title": "🎬 Reels 编辑器",
        "html": (
            _h1("🎬 Reels：从素材到成品")
            + _p("左侧：<b>合成 · 视频 · 音频 · 文转音</b>。中间预览，右侧样式/混音/编码/书写语言。")
            + _h2("A. 分组合成（去口气）")
            + _step(1, "导入分组", "拖入父文件夹：每个子文件夹一组，点扫描。")
            + _step(2, "模式并合成", "智能混合（推荐）/ 仅文案 / 快速声音 → 合成。")
            + _table(
                ["模式", "适合", "说明"],
                [
                    ["智能混合边界", "大多数", "文案 + 声音修正"],
                    ["仅按文案边界", "口齿清晰", "口气重易漏"],
                    ["快速声音边界", "大批量", "只看音量"],
                ],
            )
            + _h2("B. 文转音 / 混音 / 渲染")
            + _ul(
                [
                    "TTS：Gemini / ElevenLabs / 微软 edge-tts。",
                    "混音：替换音频 或 原声+BGM；可视频延长。",
                    "书写语言：自动或指定；RTL 默认整句。",
                    "编码失败 → CPU 模式。",
                ]
            )
        ),
    },
    {
        "key": "subtitle",
        "icon": "CC",
        "title": "CC 字幕提取",
        "html": (
            _h1("CC 智能字幕提取")
            + _step(1, "添加素材", "本地媒体或网络链接（每行一个）。")
            + _step(
                2,
                "语言 / 书写规范",
                "自动检测或选英语/希腊/阿拉伯等；同时影响识别提示与引号规范。",
            )
            + _step(3, "服务与导出", "本地 Whisper 或在线 API → 提取 → 复制/导出 srt。")
            + _tip("加速：GPU + VAD；弱机器用较小模型。")
        ),
    },
    {
        "key": "pipeline",
        "icon": "⇢",
        "title": "⇢ 自动流水线",
        "html": (
            _h1("⇢ 剪辑 → 字幕 → 标题 → 重命名 → 上传 → 填表")
            + _step(1, "素材与参数", "输出目录、阈值、语言/书写规范、命名前后缀。")
            + _step(2, "Google（可选）", "设置里授权并保存方案后勾选上传填表。")
            + _step(3, "续传", "继续上传 / 继续填表；默认可断点续接。")
        ),
    },
    {
        "key": "tools",
        "icon": "🧰",
        "title": "🧰 其它工具",
        "html": (
            _h1("📷 批量截图")
            + _p("链接或本地视频 → 数量/间隔/目录。解析失败更新 yt-dlp。")
            + _h1("✂ 智能剪辑")
            + _p("时长序列 或 智能画面识别（调阈值）。")
            + _h1("A↔ 批量重命名")
            + _p("规则组合 + 预览；智能标题可复用字幕结果。")
            + _h1("⌫ 清除元数据")
            + _p("输出副本清隐私元数据，不改原文件。")
            + _h1("⚙ 设置与组件（左侧导航）")
            + _ul(
                [
                    "组件检测与安装",
                    "字体与语言包（导入字体 / 导入语言包 JSON）",
                    "Google 授权与同步方案",
                    "API 密钥管理",
                ]
            )
        ),
    },
    {
        "key": "troubleshoot",
        "icon": "🩹",
        "title": "🩹 问题排查",
        "html": (
            _h1("🩹 先按这个顺序查")
            + _step(1, "当前页日志", "文件名与报错。")
            + _step(2, "顶部「查看软件日志」", "全局记录。")
            + _step(3, "设置 · 组件", "FFmpeg、密钥诊断。")
            + _step(4, "编码失败", "Reels 改 CPU 模式。")
            + _h2("常见现象")
            + _table(
                ["现象", "处理"],
                [
                    ["缺 FFmpeg", "设置 → 组件一键安装"],
                    ["解析失败", "更新 yt-dlp"],
                    ["密钥 401", "诊断并换钥"],
                    ["编码花屏", "CPU 编码"],
                    ["口气不净", "调高静音阈值"],
                    ["RTL 乱序", "书写语言选阿/希；用支持字体；默认整句"],
                ],
            )
        ),
    },
    {
        "key": "common_faq",
        "icon": "❓",
        "title": "❓ 常见问题",
        "html": _build_faq_html(),
    },
]

HELP_FAQ_TAB_INDEX = next(i for i, t in enumerate(HELP_TABS) if t["key"] == "common_faq")

HELP_CSS = """
body { color: #e2e8f0; font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
       font-size: 15px; line-height: 1.75; margin: 0; padding: 8px 12px 20px 8px; }
b { color: #f1f5f9; }
"""

# 设置页左侧导航（与帮助统一风格）
SETTINGS_NAV = [
    {"key": "components", "icon": "🛠", "title": "🛠 组件检测与安装"},
    {"key": "fonts", "icon": "🔤", "title": "🔤 字体与语言包"},
    {"key": "google", "icon": "☁", "title": "☁ Google 授权与同步"},
    {"key": "keys", "icon": "🔑", "title": "🔑 API 密钥管理"},
]
