## v1.7.55

### Windows
- [VideoToolkit_Setup_v1.7.55.exe](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.55/VideoToolkit_Setup_v1.7.55.exe)（安装包）
- [video-toolkit-windows-x64-v1.7.55.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.55/video-toolkit-windows-x64-v1.7.55.zip)（绿色版）

### macOS
- [video-toolkit-macos-arm64-v1.7.55.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.55/video-toolkit-macos-arm64-v1.7.55.zip)（Apple Silicon）
- [video-toolkit-macos-x64-v1.7.55.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.55/video-toolkit-macos-x64-v1.7.55.zip)（Intel）

### Linux
- [video-toolkit-linux-x64-v1.7.55.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.55/video-toolkit-linux-x64-v1.7.55.zip)

### Changes
- **Reels 语义黄字跟读**：新增预设——语义大小号 + 当前词亮黄跟读（预览/导出一致）。
- **字幕预设可改色**：改颜色/字体后实时预览生效；自定义预设保留 effect / base_preset。
- **图文成品预览**：修复 `float(None)` 导致的预览加载失败；语义比例空值兜底。
- **长配音字幕**：拒绝 Gemini/云端「整段仅 1～2 条」过稀结果；≥90s 优先本地 Whisper；过稀时文案均分保底。
- **长片预览卡顿**：按时长自动降帧（约 3 分钟以上更顺）。
- **预设点击崩溃**：修复「从当前视频移除」按钮被回收后 `QPushButton already deleted`。
- 含 v1.7.54：图文成片音轨/BGM 叠音修复。
