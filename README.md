# 视频工具合集

同一个 PySide6 主窗口内整合以下功能：

- 视频批量截图
- 智能剪辑
- 视频 / 图片水印添加
- 动态 Reels 批量制作（视频、音频、独立文案、字幕动画与蒙版）
- 视频 / 文件批量重命名
- 智能提取视频字幕

字幕模块支持无需密钥的本地 Whisper，以及 Groq、Google Gemini、ElevenLabs、Gladia。每个在线服务可以批量添加多枚 API 密钥，软件会轮询使用；遇到无效密钥或额度限制时会自动切换，并支持主动检测。

批量截图支持 YouTube、Facebook、Instagram、TikTok 等 yt-dlp 可解析链接，也支持直接添加本地视频。

批量重命名支持保存多套“前缀＋后缀”方案并快速切换。

动态 Reels 流水线支持每个视频分别匹配音频和文案，并将同一套字幕样式、动画、蒙版及圆角参数批量应用到全部任务。界面会按序号显示“视频—音频—文案”对应关系；实时预览与最终 ASS 导出共用 1080×1920 排版坐标，便于准确调整字体、换行、行距和位置。

## 字幕结果

字幕在当前窗口中以“识别原文 / 简体中文”双栏显示，可以直接复制原文或中外文对照。程序不再自动输出 TXT/JSON 文本文件。

长视频使用 Groq 时会自动拆分为 90 秒无损音频分段，每个成功分段会立即保存进度。字幕批处理按视频保存检查点；再次执行同一批素材时自动跳过已完成项目。本地 Whisper 直接流式读取媒体，GPU 模式不可用时自动回退 CPU INT8，VAD 组件不可用时自动关闭静音过滤继续识别。

## 设置与组件

顶部“设置与组件”页面会统一检测 Python 依赖、FFmpeg 与 FFprobe；缺少的组件可以一键静默安装。FFmpeg/FFprobe 使用 FFmpeg 官方下载页列出的 gyan.dev Windows Essentials 构建。

## 密钥与隐私

密钥仅保存在本机配置目录：Windows 为 `%APPDATA%\VideoToolkit\config.json`，macOS 为 `~/Library/Application Support/VideoToolkit/config.json`。这是本机明文配置文件，请不要分享。媒体会按所选服务上传到相应 API；Gemini 上传的临时文件会在请求完成后主动删除。

## 自动流水线与云端同步

自动流水线支持“智能剪辑 → 批量提取字幕 → 引用字幕标题批量重命名”。可选开启 Google Drive/Sheets 同步，仅上传重命名成品。Google 表格 ID、Sheet、列映射、固定字段与每次上传下拉字段均可配置并保存多套方案。

流水线默认开启断点续接，并分别记录每个源视频的剪辑、每个片段的字幕和每个重命名成品。失败后使用相同素材、输出目录、剪辑阈值及命名规则重新执行，即可从失败阶段继续；取消“自动续接未完成任务”可强制创建全新任务。

## 本地运行

```powershell
python -m pip install -r requirements.txt
python app.py
```

## macOS 版本

Release 同时提供以下两个 macOS 压缩包，界面、功能和自动流水线与 Windows 版本一致：

- `macos-arm64`：Apple 芯片（M1/M2/M3/M4 及后续型号）
- `macos-x64`：Intel 芯片

解压后将“视频工具合集.app”拖入“应用程序”目录。当前公开构建使用临时本地签名，没有 Apple Developer ID 公证；首次运行如被 Gatekeeper 阻止，请在 Finder 中右键应用并选择“打开”，或到“系统设置 → 隐私与安全性”确认打开。

## 如何发布新版本

软件窗口标题和顶部工具栏会显示当前版本号。GitHub Actions 会从发布 Tag（例如
`v1.6.1`）自动把版本号写入 Windows 和 macOS 安装包；本地打包时也可以设置
`VIDEO_TOOLKIT_VERSION` 环境变量覆盖版本号。

本项目使用 GitHub Actions 自动构建和发布。发布前确保所有代码已提交并推送：

```bash
git status
git add .
git commit -m "你的改动说明"
git push origin main
```

创建并推送以 `v` 开头的版本 Tag：

```bash
git tag -a v1.0.1 -m "Release version 1.0.1"
git push origin v1.0.1
```

GitHub Actions 会自动安装依赖，同时构建 Windows 便携版、macOS Apple 芯片版和 macOS Intel 版，生成 Attestation，并由 `github-actions[bot]` 创建 Release。可在仓库的 Actions 页面查看构建进度，在 Releases 页面下载成品。

版本号规则：`vX.0.0` 表示重大版本，`vX.Y.0` 表示新增功能，`vX.Y.Z` 表示修复版本。

如果构建失败，请在 Actions 中查看日志并修复，然后删除失败的 Tag 后重新创建：

```bash
git tag -d v1.0.1
git push origin :refs/tags/v1.0.1
git tag -a v1.0.1 -m "Release version 1.0.1"
git push origin v1.0.1
```
