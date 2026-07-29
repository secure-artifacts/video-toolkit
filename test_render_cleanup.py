import tempfile
from pathlib import Path

from modules.dynamic_caption_page import (
    RENDER_CACHE_DIR_NAMES,
    cleanup_successful_render_artifacts,
)


with tempfile.TemporaryDirectory(prefix="video_toolkit_cleanup_") as raw:
    output = Path(raw)
    product = output / "最终成品.mp4"
    product.write_bytes(b"final" * 400)
    for name in RENDER_CACHE_DIR_NAMES:
        cache = output / name
        cache.mkdir()
        (cache / "cached.bin").write_bytes(b"cache")
    for name in ("reels_checkpoint.json", "成品.mp4.segments.json", "render.tmp", "caption.ass"):
        (output / name).write_text("generated", encoding="utf-8")
    user_folder = output / "用户资料"
    user_folder.mkdir()
    user_json = user_folder / "不要删除.json"
    user_json.write_text("user", encoding="utf-8")

    result = cleanup_successful_render_artifacts(output, [product])
    assert result["errors"] == []
    assert result["directories"] == len(RENDER_CACHE_DIR_NAMES)
    assert result["files"] == 4
    assert product.is_file()
    assert user_json.is_file()
    assert not any((output / name).exists() for name in RENDER_CACHE_DIR_NAMES)
    assert not list(output.glob("*.json"))

with tempfile.TemporaryDirectory(prefix="video_toolkit_cleanup_guard_") as raw:
    output = Path(raw)
    incomplete = output / "损坏成品.mp4"
    incomplete.write_bytes(b"small")
    checkpoint = output / "reels_checkpoint.json"
    checkpoint.write_text("keep for resume", encoding="utf-8")
    result = cleanup_successful_render_artifacts(output, [incomplete])
    assert result["errors"]
    assert checkpoint.is_file()

print("OK render cleanup")
