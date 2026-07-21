import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

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
        for index, color in ((1, "red"), (2, "blue")):
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color={color}:s=270x480:r=30:d=0.8",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.8",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ac", "2", str(group / f"{index}.mp4"),
            ], check=True)
        worker = GroupMergeWorker(
            discover_groups(parent), output, ffmpeg,
            lambda _path: ("Teste de voz", "", SRT),
            {"sort_mode": "natural", "head_padding_ms": 40, "tail_padding_ms": 40, "resume": True},
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
        # 第二次运行必须复用缓存，且输出仍只有一个成品。
        second = []
        worker = GroupMergeWorker(
            discover_groups(parent), output, ffmpeg,
            lambda _path: (_ for _ in ()).throw(AssertionError("resume should reuse transcript")),
            {"sort_mode": "natural", "head_padding_ms": 40, "tail_padding_ms": 40, "resume": True},
        )
        worker.item_done.connect(lambda path, *_args: second.append(path)); worker.run()
        assert second == results
    print("group merge ffmpeg + stereo + resume: OK")


if __name__ == "__main__":
    main()
