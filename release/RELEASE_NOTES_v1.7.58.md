## v1.7.58

### Windows
- [VideoToolkit_Setup_v1.7.58.exe](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.58/VideoToolkit_Setup_v1.7.58.exe)（安装包）
- [video-toolkit-windows-x64-v1.7.58.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.58/video-toolkit-windows-x64-v1.7.58.zip)（绿色版）

### macOS
- [video-toolkit-macos-arm64-v1.7.58.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.58/video-toolkit-macos-arm64-v1.7.58.zip)（Apple Silicon）
- [video-toolkit-macos-x64-v1.7.58.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.58/video-toolkit-macos-x64-v1.7.58.zip)（Intel）

### Linux
- [video-toolkit-linux-x64-v1.7.58.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.58/video-toolkit-linux-x64-v1.7.58.zip)

### Changes
- **预览≈导出（Qt 烧录）**：字幕用与预览同一套 Qt 绘制引擎烧录，词间距与样式更一致；ASS 仅作回退。
- **裁剪后对口型**：切片后可自动/手动「按成品音轨重提字幕」；保留源轴快照与即时重映射预览。
- **跟读对口型**：恢复严格跟词级 ASR 时间戳（默认不抢拍、不做百分比拉伸）；`word_color`/经典黄只变色不放大。
- **Descript 经典黄**：描边改为深灰 `#222222`。
- 含 v1.7.57：FB Reel 黄/红预设、词间距修复、元数据旋转校正。
