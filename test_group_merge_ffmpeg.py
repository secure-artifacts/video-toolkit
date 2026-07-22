import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from modules.group_merge import GroupMergeWorker, discover_groups


SRT = "1\n00:00:00,120 --> 00:00:00,680\nTeste de voz"


def main():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        bundled = next((path for path in Path(__file__).parent.glob("dist_*/VideoToolkit/internal/ffmpeg.exe")
                        if path.is_file() and path.with_name("ffprobe.exe").is_file()), None)
        ffmpeg = str(bundled.resolve()) if bundled else None
        ffprobe = str(bundled.with_name("ffprobe.exe").resolve()) if bundled else None
    if not ffmpeg or not ffprobe:
        print("group merge ffmpeg: SKIPPED (FFmpeg unavailable)")
        return
    with TemporaryDirectory() as temp:
        root = Path(temp); parent = root / "批次"; group = parent / "01组"; output = root / "输出"
        group.mkdir(parents=True)
        watermark=root/"watermark.png"; Image.new("RGBA",(270,480),(255,0,0,48)).save(watermark)
        for index, color in ((1, "red"), (2, "blue")):
            size = "270x480" if index == 1 else "280x480"
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color={color}:s={size}:r=30:d=0.8",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.8",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ac", "2", str(group / f"{index}.mp4"),
            ], check=True)
        worker = GroupMergeWorker(
            discover_groups(parent), output, ffmpeg,
            lambda _path: (_ for _ in ()).throw(AssertionError("natural mode must not transcribe")),
            {"sort_mode": "natural", "trim_mode": "fast", "head_padding_ms": 40, "tail_padding_ms": 40, "resume": True,
             "burn_watermark":True,"watermark_prepare":lambda _video,_cache:str(watermark)},
        )
        results = []
        worker.item_done.connect(lambda path, *_args: results.append(path))
        worker.run()
        assert len(results) == 1 and Path(results[0]).stat().st_size > 1024
        probe = subprocess.run([
            ffprobe, "-v", "error", "-show_entries", "stream=codec_type,channels:format=duration",
            "-of", "json", results[0],
        ], check=True, capture_output=True, text=True, encoding="utf-8")
        data = json.loads(probe.stdout)
        audio = next(stream for stream in data["streams"] if stream["codec_type"] == "audio")
        assert audio["channels"] == 2
        assert 1.0 < float(data["format"]["duration"]) < 1.7
        # 第二段故意使用非 9:16 比例。成品应居中裁剪铺满，不应用黑色 pad 补边。
        corner = subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", "1.1", "-i", results[0],
            "-vf", "crop=24:24:0:0,scale=1:1", "-frames:v", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "pipe:1",
        ], check=True, capture_output=True).stdout
        assert len(corner) == 3 and max(corner) > 100, f"unexpected black padded corner: {list(corner)}"
        # 第二次运行必须复用缓存，且输出仍只有一个成品。
        second = []
        worker = GroupMergeWorker(
            discover_groups(parent), output, ffmpeg,
            lambda _path: (_ for _ in ()).throw(AssertionError("natural mode must not transcribe")),
            {"sort_mode": "natural", "trim_mode": "fast", "head_padding_ms": 40, "tail_padding_ms": 40, "resume": True,
             "burn_watermark":True,"watermark_prepare":lambda _video,_cache:str(watermark)},
        )
        worker.item_done.connect(lambda path, *_args: second.append(path)); worker.run()
        assert second == results

        # 停止必须能立即中断当前子进程；界面随后会创建新 worker 继续运行。
        stopper = GroupMergeWorker(
            discover_groups(parent), output, ffmpeg,
            lambda _path: (_ for _ in ()).throw(AssertionError("natural mode must not transcribe")),
            {"sort_mode": "natural", "trim_mode": "fast", "resume": True},
        )
        stopped = []
        thread = threading.Thread(
            target=lambda: stopped.append(_run_until_stopped(stopper, [
                sys.executable, "-c", "import time; time.sleep(10)",
            ])), daemon=True,
        )
        thread.start(); time.sleep(0.25); stopper.cancel(); thread.join(3)
        assert not thread.is_alive() and stopped == [True]
    print("group merge ffmpeg + stereo + resume: OK")


def _run_until_stopped(worker, command):
    try:
        worker._run(command)
    except RuntimeError as exc:
        return "已停止" in str(exc)
    return False


if __name__ == "__main__":
    main()
