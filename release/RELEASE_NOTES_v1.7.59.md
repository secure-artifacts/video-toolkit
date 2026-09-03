## v1.7.59

### Windows
- [VideoToolkit_Setup_v1.7.59.exe](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.59/VideoToolkit_Setup_v1.7.59.exe)（安装包）
- [video-toolkit-windows-x64-v1.7.59.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.59/video-toolkit-windows-x64-v1.7.59.zip)（绿色版）

### macOS
- [video-toolkit-macos-arm64-v1.7.59.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.59/video-toolkit-macos-arm64-v1.7.59.zip)（Apple Silicon）
- [video-toolkit-macos-x64-v1.7.59.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.59/video-toolkit-macos-x64-v1.7.59.zip)（Intel）

### Linux
- [video-toolkit-linux-x64-v1.7.59.zip](https://github.com/secure-artifacts/video-toolkit/releases/download/v1.7.59/video-toolkit-linux-x64-v1.7.59.zip)

### Changes
- **换预设/改描边跟读不乱**：跟读始终锚定词级 ASR；词数不一致时按开口映射，不再句长均分。
- **已有词轴时换预设**：只换颜色/字体/效果，保留「每句词数/每行字符」，避免重切句导致跟读飞掉或不动。
- **禁止预设偷偷切到自由文案**：避免清空词级跟读时钟。
- 含 v1.7.58：Qt 烧录预览≈导出、裁剪后重提字幕、经典黄只变色不放大。
