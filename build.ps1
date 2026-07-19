$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $root 'dist_folder'
$mediaBin = if ($env:VIDEO_TOOLKIT_MEDIA_BIN) {
  $env:VIDEO_TOOLKIT_MEDIA_BIN
} else {
  Join-Path $root 'tools\ffmpeg\bin'
}
if (-not (Test-Path (Join-Path $mediaBin 'ffmpeg.exe')) -or -not (Test-Path (Join-Path $mediaBin 'ffprobe.exe'))) {
  throw 'FFmpeg and FFprobe were not found. Set VIDEO_TOOLKIT_MEDIA_BIN or place them in tools\ffmpeg\bin.'
}
python -m PyInstaller --noconfirm --windowed --onedir --contents-directory 'internal' `
  --name 'VideoToolkit' `
  --icon (Join-Path $root 'logo.ico') `
  --add-data ((Join-Path $root 'logo.ico') + ';.') `
  --add-binary ((Join-Path $mediaBin 'ffmpeg.exe') + ';.') `
  --add-binary ((Join-Path $mediaBin 'ffprobe.exe') + ';.') `
  --collect-data 'faster_whisper' `
  --collect-binaries 'ctranslate2' `
  --hidden-import 'faster_whisper' `
  --exclude-module 'torch' `
  --exclude-module 'torchvision' `
  --exclude-module 'torchaudio' `
  --exclude-module 'tensorflow' `
  --exclude-module 'onnxruntime' `
  --exclude-module 'numba' `
  --exclude-module 'llvmlite' `
  --exclude-module 'IPython' `
  --exclude-module 'jupyter' `
  --distpath $dist `
  --workpath (Join-Path $root 'build') `
  --specpath $root `
  (Join-Path $root 'app.py')
