# 视频工具合集

一站式桌面视频工作台，将批量截图、智能剪辑、Reels 编辑、批量重命名、元数据清理、字幕提取和自动上传填表集中在同一个 PySide6 界面中。

当前版本：**v1.6.3**

[查看最新版本与更新说明](https://github.com/secure-artifacts/video-toolkit/releases/latest)

## 下载

| 系统 | 安装包 |
| --- | --- |
| Windows 10/11 x64 | [video-toolkit-windows-x64-v1.6.3.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.6.3/video-toolkit-windows-x64-v1.6.3.zip) |
| macOS Apple Silicon | [video-toolkit-macos-arm64-v1.6.3.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.6.3/video-toolkit-macos-arm64-v1.6.3.zip) |
| macOS Intel | [video-toolkit-macos-x64-v1.6.3.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.6.3/video-toolkit-macos-x64-v1.6.3.zip) |

Windows 解压后运行 `VideoToolkit.exe`。macOS 解压后将“视频工具合集.app”拖入“应用程序”；首次运行如被 Gatekeeper 阻止，请在 Finder 中右键应用并选择“打开”。

## 主要功能

- **视频批量截图**：支持本地视频及 YouTube、Facebook、Instagram、TikTok 等 yt-dlp 可解析链接。
- **智能剪辑**：批量检测画面并裁剪视频，支持长任务断点续接。
- **Reels 视频编辑器**：合成、配音、字幕样式与校对、视频预览、多图水印、批量输出集中在一个工作区。
- **批量重命名**：自然排序、编号、日期、标题和前后缀组合；支持保存多套命名方案。
- **智能中文标题**：可直接识别文件夹内视频内容，生成中文标题并填入批量重命名标题列表。
- **素材元数据清理**：显示清理前后的元数据，移除 GPS、时间、设备、作者、版权及其他隐私字段。
- **字幕提取**：本地 Whisper 无需密钥，也支持 Groq、Gemini、ElevenLabs 和 Gladia。
- **自动流水线**：智能剪辑 → 字幕提取 → 字幕生成标题 → 批量重命名 → 上传 → Google Sheets 填表。

## Reels 编辑器

Reels 编辑器面向批量任务设计，每个视频、音频和文案组成一条独立任务，同一套样式可批量应用，但不会把一个音频或文案错误套用到全部视频。

### 分组合成

- 一个父目录可以包含多组子文件夹，每个子文件夹输出一个完整视频。
- 支持文件名自然排序，也支持按分段文案辅助排序。
- 可批量裁掉片头、片尾口气音后无缝合成。
- 合成结束后可自动提取字幕并继续后续字幕渲染流程。
- 已完成的分组、字幕和成品均可断点续接，失败后不会从头处理。

### 字幕与动画

- 语音同步字幕：按时间轴逐句显示并支持逐词高亮。
- 自由文案动画：适用于不要求对口型的整段固定、逐字出现、逐行出现、由下向上和淡入淡出效果。
- 自动按语义和行宽断句，不拆开完整单词；支持手动修改每句时间和文字。
- 支持源文案校对，只替换文字并保留现有时间轴。
- 字体、字号、字距、行距、描边、颜色、字幕位置和动画参数自动记忆。
- 实时预览与精确渲染尽量共用同一套 ASS 排版和字体解析逻辑。
- “重新提取选中素材”会强制重新识别并覆盖旧缓存；“批量提取全部”继续使用缓存完成断点续接。

### 音轨处理

- 保留视频原声。
- 使用与视频一一对应的外部音频替换原声。
- 保留原声并混合背景音乐，可分别调整两条音轨音量。
- 背景音乐支持选择起点，长于视频时自动裁剪，短于视频时按输出规则补齐。
- 混音模式只识别视频对白，不会把背景音乐误当作字幕音轨。
- 输出保持立体声，不会自动压缩为单声道。

### 水印、图层与蒙版

- 支持透明 PNG、WebP、JPG 水印。
- 支持添加多张图片水印，每张可独立设置位置、大小、透明度和边距。
- 9:16 公司水印可以全屏覆盖到视频图层。
- 文字图层、图片图层和蒙版可以调整上下层级，并保存后批量复用。

## 字幕识别服务

在线服务可一次粘贴多枚 API 密钥，每行一个。软件会轮询调用并检测状态；遇到无效密钥、额度不足或网络失败时会记录日志并自动尝试下一枚密钥或下一种服务，不会因为单个任务失败而终止整批处理。

本地 Whisper 支持 GPU；GPU 或 FP16 不可用时自动切换 CPU INT8。ONNX Runtime 用于 VAD 静音过滤，并已包含在正式安装包中。长音频使用 Groq 时会拆分为 90 秒无损片段，每个成功片段会立即保存进度。

## 字体管理

“设置与组件 → 字体管理”支持：

- 扫描并调用本机字体。
- 导入本地字体文件。
- 下载 Open Sans、Noto Sans、Noto Sans SC、Poppins、Libre Baskerville 等 SIL OFL 开源字体。
- 字体只需安装一次，后续可以直接从字幕字体列表调用。

## 元数据隐私清理

视频、音频和图片会显示检测到的元数据。清理时重点移除：

- GPS 经纬度和位置字段。
- 拍摄、创建、修改日期与时区信息。
- 设备品牌、型号、序列号、镜头和软件信息。
- 作者、艺术家、版权、公司和联系人信息。
- EXIF、XMP、IPTC、QuickTime location、comment、description 等可能泄露身份的信息。

视频和音频使用无损流复制并保留原声道；图片重新保存为干净副本。默认不会覆盖原文件。

## Google Drive 与 Google Sheets

- 使用服务账号或 OAuth JSON 授权 Google Drive。
- 自动按当天日期和视频名称建立云端目录。
- 只上传最终重命名成品。
- 表格 ID、写入 Sheet、列映射、固定字段和每次上传下拉字段均可自定义。
- 同步方案可以保存并在自动流水线或 Reels 编辑器中直接选择。
- 上传成功、填表失败时可只继续填表；上传失败时可从未完成文件继续上传。
- 使用云端文件链接作为唯一值判断，避免重复上传或重复写入表格。

## 断点续接

断点状态覆盖整套流程，而不仅是视频合成：

1. 分组剪辑与合成。
2. 字幕识别与翻译。
3. 字幕样式烧录和最终导出。
4. 批量重命名。
5. Google Drive 上传。
6. Google Sheets 填表。

重新运行相同素材和输出目录时，软件会验证文件指纹并跳过已完成阶段；素材、样式或音轨设置改变后，只重做受影响的阶段。

## 密钥与隐私

密钥只保存在本机配置目录：

- Windows：`%APPDATA%\VideoToolkit\config.json`
- macOS：`~/Library/Application Support/VideoToolkit/config.json`

这是本机明文配置，请勿分享。只有选择在线识别、翻译或云端同步服务时，相应媒体或文本才会发送到所选服务；本地 Whisper 不需要上传媒体。

## 本地运行

需要 Python 3.12：

```powershell
python -m pip install -r requirements.txt
python app.py
```

本地打包还需要 FFmpeg 与 FFprobe：

```powershell
$env:VIDEO_TOOLKIT_MEDIA_BIN = "C:\path\to\ffmpeg\bin"
$env:VIDEO_TOOLKIT_VERSION = "1.6.3"
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

## 自动构建与发布

推送以 `v` 开头的 Tag 后，GitHub Actions 会自动：

1. 构建 Windows x64 便携版。
2. 构建 macOS Apple Silicon 和 Intel 版本。
3. 验证 FFmpeg、FFprobe 与 ONNX Runtime。
4. 为安装包生成 Build Provenance Attestation。
5. 创建 GitHub Release 并上传三个 ZIP。

```bash
git tag -a v1.6.3 -m "Release version 1.6.3"
git push origin v1.6.3
```
