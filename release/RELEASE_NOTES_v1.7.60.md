## v1.7.60

### Windows
- [VideoToolkit_Setup_v1.7.60.exe](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.60/VideoToolkit_Setup_v1.7.60.exe)（安装包）
- [video-toolkit-windows-x64-v1.7.60.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.60/video-toolkit-windows-x64-v1.7.60.zip)（绿色版）

### macOS
- [video-toolkit-macos-arm64-v1.7.60.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.60/video-toolkit-macos-arm64-v1.7.60.zip)（Apple Silicon）
- [video-toolkit-macos-x64-v1.7.60.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.60/video-toolkit-macos-x64-v1.7.60.zip)（Intel）

### Linux
- [video-toolkit-linux-x64-v1.7.60.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.60/video-toolkit-linux-x64-v1.7.60.zip)

### Changes
- **安装版跟读修复**：打包强制打进 `caption_qt_burn` 跟读模块，避免安装包里跟读逻辑缺失导致卡住/飞快/对不上口型。
- **词级轴可带走**：提取后自动写 `*.words.srt`；换电脑按文件名也能找回词轴，无需每个工程单独导。
- **缺词轴会提示**：日志明确警告「未找到词级时间轴」，避免默默均分。
- 含 v1.7.59：换预设/改描边不破坏跟读。
