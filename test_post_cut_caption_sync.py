# -*- coding: utf-8 -*-
"""Smoke: cut → remapped captions + bake finished A/V for post-cut ASR."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from modules.dynamic_caption_page import (  # noqa: E402
    parse_srt,
    render_timeline_edits,
    retime_srt_for_video_segments,
    should_retime_captions_for_segments,
    video_segments_need_caption_retime,
)

FFMPEG = str(ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe")
SRC = ROOT / "_smoke_post_cut" / "src6s.mp4"
OUT = ROOT / "_smoke_post_cut"


def _approx(a, b, tol=0.08):
    return abs(float(a) - float(b)) <= tol


def test_retime_drops_deleted_middle():
    # Source 0–6s with cues at 0.5, 2.5, 4.5
    srt = (
        "1\n00:00:00,500 --> 00:00:01,200\nAAA\n\n"
        "2\n00:00:02,500 --> 00:00:03,200\nBBB\n\n"
        "3\n00:00:04,500 --> 00:00:05,200\nCCC\n"
    )
    # Keep 0–2s and 4–6s → timeline 0–2 then 2–4 (delete middle 2–4)
    segs = [
        {"start": 0, "end": 2000, "source_start": 0, "source_end": 2000, "media_type": "video"},
        {"start": 2000, "end": 4000, "source_start": 4000, "source_end": 6000, "media_type": "video"},
    ]
    assert video_segments_need_caption_retime(segs)
    out = retime_srt_for_video_segments(srt, segs)
    cues = parse_srt(out)
    texts = [c[2].strip() for c in cues]
    assert texts == ["AAA", "CCC"], texts
    # AAA stays near 0.5; CCC was 4.5 on source → timeline 2.5
    assert _approx(cues[0][0], 0.5), cues[0]
    assert _approx(cues[1][0], 2.5), cues[1]
    assert should_retime_captions_for_segments(srt, "", segs, captions_timeline_aligned=False)
    assert not should_retime_captions_for_segments(out, "", segs, captions_timeline_aligned=True)
    print("PASS retime_drops_deleted_middle")


def test_bake_cut_media():
    assert SRC.is_file(), f"missing {SRC}"
    assert Path(FFMPEG).is_file(), f"missing {FFMPEG}"
    # Delete 2–4s on 6s source → ~4s output
    state = {
        "tracks": {
            "video": [
                {
                    "start": 0,
                    "end": 2000,
                    "source_start": 0,
                    "source_end": 2000,
                    "media_type": "video",
                    "speed": 1.0,
                },
                {
                    "start": 2000,
                    "end": 4000,
                    "source_start": 4000,
                    "source_end": 6000,
                    "media_type": "video",
                    "speed": 1.0,
                },
            ],
            "original_audio": [
                {"start": 0, "end": 2000, "source_start": 0, "source_end": 2000},
                {"start": 2000, "end": 4000, "source_start": 4000, "source_end": 6000},
            ],
        },
        "transitions": [],
        "original_audio_enabled": True,
    }
    baked = Path(render_timeline_edits(FFMPEG, str(SRC), state, OUT))
    assert baked.is_file(), baked
    assert baked.stat().st_size > 1024, baked.stat().st_size
    # Duration should be ~4s
    from modules.dynamic_caption_page import media_duration, media_has_audio

    dur = media_duration(FFMPEG, baked)
    assert 3.5 <= dur <= 4.5, dur
    assert media_has_audio(FFMPEG, baked), "baked media must keep audio for ASR"
    print(f"PASS bake_cut_media -> {baked.name} dur={dur:.2f}s")
    return baked


def test_page_methods_exist():
    import ast

    src = (ROOT / "modules" / "dynamic_caption_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    needed = {
        "_schedule_post_cut_asr",
        "_run_post_cut_asr",
        "reextract_captions_from_edited_timeline",
        "_post_cut_asr_done",
        "_sync_captions_after_video_edit",
        "_ensure_caption_source_snapshot",
    }
    found = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in needed:
                    found.add(item.name)
    missing = needed - found
    assert not missing, missing
    # UI wiring markers
    assert "切片后自动按成品音轨重提字幕" in src
    assert "裁剪后重提" in src
    assert "self._schedule_post_cut_asr" in src
    print("PASS page_methods_exist")


if __name__ == "__main__":
    test_retime_drops_deleted_middle()
    test_bake_cut_media()
    test_page_methods_exist()
    print("ALL SMOKE OK")
