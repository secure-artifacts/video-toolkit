#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_BIN="${VIDEO_TOOLKIT_MEDIA_BIN:-}"

if [[ -z "$MEDIA_BIN" || ! -x "$MEDIA_BIN/ffmpeg" || ! -x "$MEDIA_BIN/ffprobe" ]]; then
  echo "VIDEO_TOOLKIT_MEDIA_BIN must contain executable ffmpeg and ffprobe files." >&2
  exit 1
fi

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name VideoToolkit \
  --osx-bundle-identifier com.secureartifacts.videotoolkit \
  --icon "$ROOT_DIR/logo.icns" \
  --add-data "$ROOT_DIR/logo.ico:." \
  --add-binary "$MEDIA_BIN/ffmpeg:." \
  --add-binary "$MEDIA_BIN/ffprobe:." \
  --collect-data faster_whisper \
  --collect-binaries ctranslate2 \
  --hidden-import faster_whisper \
  --hidden-import google_auth_oauthlib \
  --hidden-import googleapiclient.discovery \
  --exclude-module torch \
  --exclude-module tensorflow \
  --exclude-module matplotlib \
  --noupx \
  --distpath "$ROOT_DIR/dist_macos" \
  --workpath "$ROOT_DIR/build_macos" \
  --specpath "$ROOT_DIR" \
  "$ROOT_DIR/app.py"
