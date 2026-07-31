from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .path_picker import VIDEO_EXTENSIONS, collect_files, natural_key
from .settings_page import hidden_kwargs
from .video_encoding import (
    ENCODER_LABELS, encoder_args, resolve_encoder, calculate_target_size,
    davinci_safe_mux_args, remux_zero_start,
)


# 合并转场预设：UI 显示名 → FFmpeg xfade 参数。
# 达芬奇「平滑剪接」依赖光流，此处用 hblur 短过渡近似；Crash Zoom 用 zoomin 近似。
MERGE_TRANSITION_PRESETS = {
    "无转场": None,
    # —— 达芬奇风格（与 Resolve 转场库对应）——
    "交叉叠化": {"xfade": "dissolve", "duration": 0.65},
    "Cross Dissolve": {"xfade": "dissolve", "duration": 0.65},
    "Crash Zoom": {"xfade": "zoomin", "duration": 0.42},
    "平滑剪接": {"xfade": "hblur", "duration": 0.28},
    # —— 常用 xfade ——
    # 口播成片默认偏短转场，避免长叠化像“卡一下再说话”
    "淡入淡出": {"xfade": "fade", "duration": 0.22},
    "溶解": {"xfade": "dissolve", "duration": 0.28},
    "淡入黑场": {"xfade": "fadeblack", "duration": 0.28},
    "淡入白场": {"xfade": "fadewhite", "duration": 0.28},
    "向左滑动": {"xfade": "slideleft", "duration": 0.28},
    "向右滑动": {"xfade": "slideright", "duration": 0.28},
    "向上滑动": {"xfade": "slideup", "duration": 0.28},
    "向下滑动": {"xfade": "slidedown", "duration": 0.28},
    "直线向左擦除": {"xfade": "wipeleft", "duration": 0.25},
    "直线向右擦除": {"xfade": "wiperight", "duration": 0.25},
    "直线向上擦除": {"xfade": "wipeup", "duration": 0.25},
    "直线向下擦除": {"xfade": "wipedown", "duration": 0.25},
    "圆形打开": {"xfade": "circleopen", "duration": 0.28},
    "圆形关闭": {"xfade": "circleclose", "duration": 0.28},
    "水平打开": {"xfade": "horzopen", "duration": 0.25},
    "垂直打开": {"xfade": "vertopen", "duration": 0.25},
    "像素化": {"xfade": "pixelize", "duration": 0.28},
    "径向模糊": {"xfade": "radial", "duration": 0.28},
}


def merge_transition_labels():
    """Ordered labels for the Reels transition combo box."""
    return list(MERGE_TRANSITION_PRESETS.keys())


def resolve_merge_transition(name):
    """Return {xfade, duration} or None for hard cut."""
    return MERGE_TRANSITION_PRESETS.get(str(name or "").strip())


def discover_groups(parent):
    """Discover groups by child folder, or by a shared filename prefix plus numeric suffix."""
    root = Path(parent)
    if not root.is_dir():
        return []
    groups = []
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: natural_key(p.name)):
        clips = collect_files([str(folder)], VIDEO_EXTENSIONS)
        if clips:
            groups.append((folder, [Path(p) for p in clips]))
    direct_clips=sorted(
        (path for path in root.iterdir() if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS),
        key=lambda path:natural_key(path.name),
    )
    if direct_clips:
        buckets={}
        for clip in direct_clips:
            # Flow 等工具常见命名：11-1.mp4、11-2.mp4，或
            # 2-1_202607211405.mp4、2-2_202607211405.mp4。前一段是组号，
            # 后一段是片段号；其后的时间戳/描述不参与分组。
            numbered = re.match(r"^(?P<group>\d+)[-_](?P<part>\d+)(?:[_\s-].*)?$", clip.stem)
            if numbered:
                key = numbered.group("group")
            else:
                key=re.sub(r"(?:[\s_.-]*(?:part|segment|clip|片段)?[\s_.-]*\d+|[\s_.-]*\(\d+\))$","",clip.stem,flags=re.I).strip(" ._-")
            buckets.setdefault(key or clip.stem,[]).append(clip)
        useful=[(name,clips) for name,clips in buckets.items() if clips]
        if len(useful)>1 and any(len(clips)>1 for _name,clips in useful):
            for name,clips in sorted(useful,key=lambda item:natural_key(item[0])):
                groups.append((root/name,sorted(clips,key=lambda path:natural_key(path.name))))
        else:
            groups.append((root,direct_clips))
    return groups


def split_group_script(text, expected_count=None):
    value = str(text or "").strip()
    if not value:
        return []
    if expected_count is not None:
        lines = [line.strip() for line in value.splitlines() if line.strip() and line.strip() != "---"]
        if len(lines) == expected_count:
            return lines
    value = re.sub(r"(?m)^\s*---+\s*$", "\n\n", value)
    blocks = re.split(r"\r?\n\s*\r?\n", value)
    return [re.sub(r"\s+", " ", block).strip() for block in blocks if block.strip()]


def _script_key(folder):
    """Stable key for scripts dict (resolve path)."""
    try:
        return str(Path(folder).resolve())
    except Exception:
        return str(folder)


def lookup_group_script(scripts, folder):
    """Find pasted group script even when path separators/casing differ."""
    scripts = scripts or {}
    if not scripts:
        return ""
    folder = Path(folder)
    candidates = []
    try:
        resolved = folder.resolve()
        candidates.extend([str(resolved), str(resolved).replace("\\", "/"), str(resolved).replace("/", "\\")])
    except Exception:
        resolved = folder
    candidates.extend([str(folder), str(folder).replace("\\", "/"), folder.name])
    for key in candidates:
        value = scripts.get(key)
        if str(value or "").strip():
            return str(value)
    # Path-equality scan (handles soft links / case differences on Windows)
    try:
        target = folder.resolve()
    except Exception:
        target = folder
    for key, value in scripts.items():
        if not str(value or "").strip():
            continue
        try:
            if Path(key).resolve() == target:
                return str(value)
        except Exception:
            if Path(key).name == folder.name:
                return str(value)
    return ""


def _plain_text(value):
    # Include Greek Extended (U+1F00–U+1FFF) used by polytonic / some ASR outputs.
    return re.sub(
        r"[^0-9a-z\u00c0-\u024f\u0370-\u03ff\u1f00-\u1fff\u0400-\u04ff\u3400-\u9fff]+",
        "",
        str(value).casefold(),
    )


def _word_tokens(value):
    return set(re.findall(r"[0-9a-z\u00c0-\u024f\u0370-\u03ff\u1f00-\u1fff\u0400-\u04ff\u3400-\u9fff]+", str(value).casefold()))


def _text_similarity(source, target):
    """Multi-signal similarity robust to ASR noise and long script vs short clip text."""
    s_raw, t_raw = str(source or "").strip(), str(target or "").strip()
    s, t = _plain_text(s_raw), _plain_text(t_raw)
    if not s or not t:
        return 0.0
    full = SequenceMatcher(None, s, t).ratio()
    # Opening words are often the most distinctive per segment.
    plen = min(56, len(s), len(t))
    prefix = SequenceMatcher(None, s[:plen], t[:plen]).ratio() if plen >= 6 else 0.0
    # Partial / containment: shorter spoken text inside longer pasted script (or vice versa).
    shorter, longer = (s, t) if len(s) <= len(t) else (t, s)
    contain = 0.0
    if len(shorter) >= 8 and shorter in longer:
        contain = 0.95
    elif len(shorter) >= 10 and len(longer) >= len(shorter):
        best = 0.0
        window = len(shorter)
        step = max(1, window // 5)
        for i in range(0, len(longer) - window + 1, step):
            best = max(best, SequenceMatcher(None, shorter, longer[i:i + window]).ratio())
            if best >= 0.92:
                break
        contain = best
    ws, wt = _word_tokens(s_raw), _word_tokens(t_raw)
    jacc = (len(ws & wt) / len(ws | wt)) if ws and wt else 0.0
    # Weight distinctive signals higher than full-string ratio (length mismatch hurts full ratio).
    return max(full, 0.94 * prefix, 0.92 * contain, 0.88 * jacc)


def _transcript_variants(analysis_or_text):
    """Collect all usable transcript strings for a clip (SRT preferred, then original)."""
    if analysis_or_text is None:
        return []
    if isinstance(analysis_or_text, str):
        text = analysis_or_text.strip()
        return [text] if text else []
    variants = []
    entries = parse_srt_with_text(analysis_or_text.get("srt", ""))
    srt_text = " ".join(text for _start, _end, text in entries).strip()
    if srt_text:
        variants.append(srt_text)
    original = str(analysis_or_text.get("original") or "").strip()
    if original and original not in variants:
        variants.append(original)
    return variants


def _transcript_for_match(analysis_or_text):
    """Best single transcript string (SRT first, then original)."""
    variants = _transcript_variants(analysis_or_text)
    return variants[0] if variants else ""


def _resolve_transcript(transcripts, clip):
    """Look up transcript by resolved path with a few fallback key forms."""
    path = Path(clip)
    keys = [str(path.resolve()), str(path), str(path.resolve()).replace("\\", "/")]
    for key in keys:
        if key in transcripts:
            return transcripts[key]
    try:
        target = path.resolve()
        for key, value in transcripts.items():
            try:
                if Path(key).resolve() == target:
                    return value
            except Exception:
                continue
    except Exception:
        pass
    return ""


def match_clips_to_script(clips, transcripts, script_text, minimum_score=0.12):
    """One-to-one match clips to script segments; return clips in script-segment order.

    Final list order follows the pasted script segments (line/block 1 → first clip,
    line 2 → second, …), not the original filename order.
    """
    segments = split_group_script(script_text, len(clips))
    clips = list(clips)
    if len(segments) != len(clips) or not clips:
        return None, "分段文案数量与视频片段数量不一致", []
    candidates = []
    empty_sources = 0
    source_previews = {}
    for clip_index, clip in enumerate(clips):
        raw = _resolve_transcript(transcripts, clip)
        variants = _transcript_variants(raw)
        if not variants:
            empty_sources += 1
            source_previews[clip_index] = ""
            for segment_index, _segment in enumerate(segments):
                candidates.append((0.0, clip_index, segment_index))
            continue
        source_previews[clip_index] = variants[0][:80]
        for segment_index, segment in enumerate(segments):
            score = max(_text_similarity(variant, segment) for variant in variants)
            candidates.append((score, clip_index, segment_index))
    if empty_sources == len(clips):
        return None, "片段识别文案为空，无法按分段文案匹配排序", []
    assigned_clips = set()
    assigned_segments = set()
    mapping = {}
    for score, clip_index, segment_index in sorted(candidates, reverse=True):
        if clip_index in assigned_clips or segment_index in assigned_segments:
            continue
        assigned_clips.add(clip_index)
        assigned_segments.add(segment_index)
        mapping[segment_index] = (clips[clip_index], score, source_previews.get(clip_index, ""))
    details = []
    for index in range(len(segments)):
        if index not in mapping:
            continue
        clip, score, preview = mapping[index]
        details.append({
            "segment_index": index,
            "clip": clip,
            "score": score,
            "script_preview": segments[index][:60],
            "transcript_preview": preview,
        })
    if len(mapping) != len(clips):
        return None, "文案匹配未能建立一一对应", details
    scores = [item["score"] for item in details]
    if min(scores) < minimum_score:
        weak = ", ".join(
            f"第{item['segment_index'] + 1}段↔{item['clip'].name}({item['score']:.2f})"
            for item in details if item["score"] < minimum_score
        )
        return None, f"文案匹配可信度不足（{weak}）", details
    ordered = [mapping[index][0] for index in range(len(segments))]
    return ordered, "已按分段文案自动匹配排序", details


def _speech_spans(srt):
    timing = re.compile(
        r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
    )
    spans = []
    for match in timing.finditer(str(srt or "")):
        values = [int(value) for value in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / (10 ** len(match.group(4)))
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / (10 ** len(match.group(8)))
        spans.append((start, end))
    return spans


def speech_trim_bounds(srt, duration, head_padding_ms=80, tail_padding_ms=280,
                       tail_safety_ms=280):
    """ASR 词界：从首词前 padding 到末词后 padding。

    尾部额外 +tail_safety_ms：ASR 词尾时间常偏早，防止吞掉尾音/气声。
    若末词后剩余不足 ~0.8s，直接保留到片尾。
    """
    spans = _speech_spans(srt)
    duration = max(0.05, float(duration or 0.05))
    if not spans:
        return 0.0, duration, False
    start = max(0.0, spans[0][0] - max(0, head_padding_ms) / 1000.0)
    # 用户尾保护至少 280ms；再加 safety（ASR 常切在音节中间）
    tail = max(280, int(tail_padding_ms or 0)) + max(0, int(tail_safety_ms))
    end = min(duration, spans[-1][1] + tail / 1000.0)
    # 末词结束后不远：整段留到文件尾，宁可多留气口
    if duration - spans[-1][1] <= 0.85:
        end = duration
    return start, max(start + 0.05, end), True


def _last_voice_in_probe(events, probe_len: float) -> float:
    """在 [0, probe_len] 探针窗口内，估计最后仍有声音的相对时刻。"""
    probe_len = max(0.05, float(probe_len))
    if not events:
        return probe_len  # 未检出静音 → 可能全程有声
    voice_end = 0.0
    if events[0][0] == "start" and events[0][1] > 0.05:
        voice_end = float(events[0][1])
    for i, (kind, value) in enumerate(events):
        value = float(value)
        if kind != "end":
            continue
        next_start = None
        for j in range(i + 1, len(events)):
            if events[j][0] == "start":
                next_start = float(events[j][1])
                break
        if next_start is not None:
            voice_end = max(voice_end, next_start)
        else:
            voice_end = probe_len
    if events[-1][0] == "start":
        voice_end = max(voice_end, float(events[-1][1]))
    return min(probe_len, voice_end)


def energy_extend_end(ffmpeg, clip_path, end, duration, max_extend=1.5, threshold_db=-40):
    """ASR/静音给出 end 后，探测其后是否还有说话能量，只扩展不回缩。"""
    duration = max(0.05, float(duration or 0.05))
    end = max(0.0, min(duration, float(end)))
    remain = duration - end
    if remain < 0.10:
        return duration
    probe_len = min(max_extend, remain)
    cmd = [
        str(ffmpeg), "-hide_banner", "-nostats",
        "-ss", f"{end:.3f}", "-t", f"{probe_len:.3f}",
        "-i", str(clip_path),
        "-map", "0:a:0",
        "-af", f"silencedetect=noise={int(threshold_db)}dB:d=0.05",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", **hidden_kwargs(),
        )
        text = result.stdout or ""
    except Exception:
        return end
    events = [
        (kind, float(value))
        for kind, value in re.findall(r"silence_(start|end):\s*([0-9.]+)", text)
    ]
    voice_rel = _last_voice_in_probe(events, probe_len)
    if voice_rel < 0.07:
        return end
    return min(duration, end + voice_rel + 0.15)


def parse_srt_with_text(srt):
    blocks = re.split(r"\r?\n\s*\r?\n", str(srt or "").strip())
    result = []
    timing_re = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        match = timing_re.match(lines[timing_index])
        if not match:
            continue
        raw_values = match.groups()
        values = [int(value) for value in raw_values]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / (10 ** len(raw_values[3]))
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / (10 ** len(raw_values[7]))
        text = " ".join(lines[timing_index + 1:]).strip()
        if text:
            result.append((start, max(start + 0.05, end), text))
    return result


def find_matching_srt_bounds(srt, clip_script, duration, head_padding_ms=80, tail_padding_ms=120):
    """按分段文案在本片段 SRT 中找最相似连续句，返回该句时间窗。

    匹配失败时回退到「整段 ASR 首尾词」，宁多留不漏字。
    """
    entries = parse_srt_with_text(srt)
    duration = max(0.05, float(duration or 0.05))
    if not entries:
        return 0.0, duration, False

    clean_target = _plain_text(clip_script)
    if not clean_target:
        return speech_trim_bounds(srt, duration, head_padding_ms, tail_padding_ms)

    best_score = -1.0
    best_range = (0, len(entries) - 1)

    for i in range(len(entries)):
        for j in range(i, len(entries)):
            subset_text = "".join(entry[2] for entry in entries[i:j + 1])
            clean_subset = _plain_text(subset_text)
            score = SequenceMatcher(None, clean_subset, clean_target).ratio()
            if score > best_score:
                best_score = score
                best_range = (i, j)

    if best_score > 0.3:
        i, j = best_range
        tail = max(200, int(tail_padding_ms or 0)) + 220
        start = max(0.0, entries[i][0] - max(0, head_padding_ms) / 1000.0)
        end = min(duration, entries[j][1] + tail / 1000.0)
        if duration - entries[j][1] <= 0.55:
            end = duration
        return start, max(start + 0.05, end), True

    return speech_trim_bounds(srt, duration, head_padding_ms, tail_padding_ms)


def pair_silence_events(events):
    """silencedetect 事件 → [(start, end), ...]；无 end 的尾段用 None 表示。"""
    intervals = []
    open_start = None
    for kind, value in events or []:
        if kind == "start":
            if open_start is not None:
                intervals.append((open_start, None))
            open_start = float(value)
        elif kind == "end" and open_start is not None:
            intervals.append((open_start, float(value)))
            open_start = None
    if open_start is not None:
        intervals.append((open_start, None))
    return intervals


def safe_silence_bounds(duration, events, head_padding_ms=80, tail_padding_ms=120):
    """只裁「真·片头静音」和「真·片尾静音」。

    核心原则（高于 v1.7.17 旧逻辑）：
    - 中间停顿绝不当成片尾（旧逻辑会把 last silence_start 当 end，后半句全没）。
    - 片头 silence_end 若过晚（轻声被当成静音），宁可不裁。
    - 不确定 → (0, duration, False) 保留完整片段。
    """
    duration = max(0.05, float(duration or 0.05))
    intervals = pair_silence_events(events)
    start = 0.0
    end = duration
    detected = False

    # —— 片头：第一条从 ~0 开始的静音，且结束点不能太靠后 ——
    max_head = min(2.8, duration * 0.40)
    for s0, s1 in intervals:
        if s0 > 0.15:
            break
        if s1 is None:
            break
        if 0.02 < s1 <= max_head:
            start = s1
            detected = True
        break

    # —— 片尾：静音必须「贴片尾」：无 end 或 end 很接近 duration，且起点足够靠后 ——
    min_tail_from = max(duration * 0.50, duration - 5.0)
    for s0, s1 in reversed(intervals):
        touches_end = s1 is None or s1 >= duration - 0.08
        if not touches_end:
            continue
        if s0 < min_tail_from:
            continue
        if s0 >= duration - 0.05:
            continue
        end = s0
        detected = True
        break

    if detected:
        start = max(0.0, start - max(0, int(head_padding_ms)) / 1000.0)
        # 片尾多留：静音起点后再加 tail padding，减轻尾音被切
        end = min(duration, end + max(0, int(tail_padding_ms)) / 1000.0 + 0.12)
    if end <= start + 0.08:
        return 0.0, duration, False
    # 裁掉大半 → 不可信（轻声/阈值不当）
    if (end - start) < duration * 0.50:
        return 0.0, duration, False
    return start, end, True


def hybrid_trim_bounds(srt, duration, audio_bounds, head_padding_ms=80, tail_padding_ms=280,
                       word_guard_ms=120):
    """智能混合：ASR 词界为硬护栏；静音只收片头，片尾不因静音提前结束（防吞尾音）。

    绝不：用中间静音切掉后半句；绝不：静音越过首/末识别词。
    """
    duration = max(0.05, float(duration or 0.05))
    spans = _speech_spans(srt)
    text_start, text_end, text_detected = speech_trim_bounds(
        srt, duration, head_padding_ms, tail_padding_ms,
    )
    if not text_detected or not spans:
        if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
            return float(audio_bounds[0]), float(audio_bounds[1]), True
        return 0.0, duration, False
    if not audio_bounds or len(audio_bounds) < 3 or not bool(audio_bounds[2]):
        return text_start, text_end, True

    audio_start = float(audio_bounds[0])
    guard = max(0, int(word_guard_ms)) / 1000.0
    hard_latest_start = max(0.0, spans[0][0] - guard)
    # 片尾硬底：末词结束 + 护栏，且不低于文案窗 end（已含 tail padding + safety）
    hard_earliest_end = min(duration, max(text_end, spans[-1][1] + guard + 0.15))

    start = text_start
    # 片头：静音可收，但不得越过首词护栏；过晚静音（轻声）忽略
    if audio_start <= spans[0][0] + 0.35:
        start = min(hard_latest_start, max(text_start, audio_start))
        start = min(start, hard_latest_start)
    # 片尾：不使用 audio_end 缩短！静音收尾极易吞掉尾音/气声
    end = max(text_end, hard_earliest_end)
    end = min(duration, end)

    start = max(0.0, min(start, hard_latest_start))
    if end <= start + 0.08:
        return text_start, text_end, True
    return start, end, True


def refine_text_window_with_audio(text_start, text_end, text_ok, audio_bounds, duration,
                                  edge_slack_ms=150):
    """分段文案窗 + 静音：只允许收片头；片尾保持文案窗（防吞尾）。"""
    duration = max(0.05, float(duration or 0.05))
    if not text_ok:
        if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
            return float(audio_bounds[0]), float(audio_bounds[1]), True
        return 0.0, duration, False
    text_start = max(0.0, float(text_start))
    text_end = max(text_start + 0.05, min(duration, float(text_end)))
    if not audio_bounds or len(audio_bounds) < 3 or not bool(audio_bounds[2]):
        return text_start, text_end, True
    audio_start = float(audio_bounds[0])
    slack = max(0, int(edge_slack_ms)) / 1000.0
    latest_safe_start = min(duration, text_start + slack)
    start = text_start
    if audio_start <= text_start + slack + 0.25:
        start = min(latest_safe_start, max(text_start, audio_start))
    # 尾部不收：保持 text_end（已含尾保护）
    end = text_end
    if end <= start + 0.08:
        return text_start, text_end, True
    return max(0.0, start), min(duration, end), True


def resolve_trim_bounds(trim_mode, srt, clip_script, audio_bounds, hybrid_bounds,
                        media_duration, head_ms, tail_ms):
    """统一三种模式的最终起止点。返回 (start, end, detected, reason)。

    优先级：宁多留气口，不丢字。
    """
    media_duration = max(0.05, float(media_duration or 0.05))
    head_ms = int(head_ms or 0)
    tail_ms = int(tail_ms or 0)
    srt = str(srt or "")
    clip_script = str(clip_script or "").strip()

    if clip_script and srt:
        text_start, text_end, text_ok = find_matching_srt_bounds(
            srt, clip_script, media_duration, head_ms, tail_ms,
        )
    elif srt:
        text_start, text_end, text_ok = speech_trim_bounds(
            srt, media_duration, head_ms, tail_ms,
        )
    else:
        text_start, text_end, text_ok = 0.0, media_duration, False

    mode = str(trim_mode or "hybrid").lower()
    if mode == "fast":
        if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
            return float(audio_bounds[0]), float(audio_bounds[1]), True, "快速声音边界"
        if text_ok:
            return text_start, text_end, True, "快速模式无静音边界→文案时间轴"
        return 0.0, media_duration, False, "快速模式无可用边界→完整片段"

    if mode == "text":
        if text_ok:
            return text_start, text_end, True, "文案边界"
        if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
            return float(audio_bounds[0]), float(audio_bounds[1]), True, "文案不可用→声音边界"
        return 0.0, media_duration, False, "文案边界失败→完整片段"

    # hybrid（默认）
    if clip_script and text_ok:
        s, e, ok = refine_text_window_with_audio(
            text_start, text_end, text_ok, audio_bounds, media_duration,
        )
        return s, e, ok, "智能混合（分段文案+声音）"
    if text_ok:
        s, e, ok = hybrid_trim_bounds(
            srt, media_duration, audio_bounds, head_ms, tail_ms,
        )
        return s, e, ok, "智能混合（ASR词界+声音）"
    if hybrid_bounds and len(hybrid_bounds) >= 3 and bool(hybrid_bounds[2]):
        return (
            float(hybrid_bounds[0]), float(hybrid_bounds[1]), True,
            "智能混合（缓存hybrid）",
        )
    if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
        return float(audio_bounds[0]), float(audio_bounds[1]), True, "智能混合无ASR→声音边界"
    return 0.0, media_duration, False, "智能混合无边界→完整片段"


def _safe_name(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value)).strip(" .")
    return cleaned or "合成视频"


def group_segments_sidecar_path(output_path) -> Path:
    """Sidecar next to a group-merge product: stem.segments.json"""
    path = Path(output_path)
    return path.with_name(path.stem + ".segments.json")


def write_group_segments_map(output_path, segments, transition_ms=0):
    """Write per-segment timing so the timeline can show split video/audio bars.

    segments: list of dicts with keys name, duration_ms, optional original/normalized paths.
    """
    output_path = Path(output_path)
    rows = []
    for index, item in enumerate(segments or [], 1):
        if not isinstance(item, dict):
            continue
        rows.append({
            "index": index,
            "name": str(item.get("name") or f"段{index:02d}"),
            "duration_ms": max(80, int(item.get("duration_ms") or 0)),
            "original": str(item.get("original") or ""),
            "normalized": str(item.get("normalized") or ""),
        })
    if not rows:
        return None
    payload = {
        "version": 1,
        "output": output_path.name,
        "transition_ms": max(0, int(transition_ms or 0)),
        "segments": rows,
    }
    sidecar = group_segments_sidecar_path(output_path)
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar


def load_group_segments_map(output_path):
    """Load segment map if present; return dict or None."""
    sidecar = group_segments_sidecar_path(output_path)
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None
    segments = data.get("segments") or []
    if len(segments) < 2:
        return None
    return data


def _ffprobe_candidates(ffmpeg=None):
    """Yield possible ffprobe executables (bundled + PATH)."""
    seen = set()
    candidates = []
    if ffmpeg:
        fp = Path(ffmpeg)
        candidates.append(fp.with_name("ffprobe" + fp.suffix))
        candidates.append(fp.with_name("ffprobe.exe"))
    # Project-relative common locations (dev + packaged)
    here = Path(__file__).resolve()
    roots = [here.parents[1], Path.cwd()]
    for root in roots:
        candidates.extend([
            root / ".build_media" / "ffprobe.exe",
            root / "internal" / "ffprobe.exe",
            root / "dist_folder" / "VideoToolkit" / "internal" / "ffprobe.exe",
        ])
    candidates.extend([Path("ffprobe"), Path("ffprobe.exe")])
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        if item.name in {"ffprobe", "ffprobe.exe"} or item.is_file():
            yield str(item)


def _probe_media_duration_ms(path, ffmpeg=None) -> int:
    """Best-effort duration in ms via ffprobe; 0 on failure."""
    path = Path(path)
    if not path.is_file():
        return 0
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for tool in _ffprobe_candidates(ffmpeg):
        try:
            res = subprocess.run(
                [tool, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=creation, timeout=30,
            )
            text = (res.stdout or b"").decode("utf-8", errors="replace").strip().splitlines()
            text = (text[0] if text else "").strip()
            if text and text.upper() != "N/A":
                return max(0, int(round(float(text) * 1000)))
        except Exception:
            continue
    # Fallback: ffmpeg -i header
    ffmpeg_tools = []
    if ffmpeg:
        ffmpeg_tools.append(str(ffmpeg))
    ffmpeg_tools.extend(["ffmpeg", "ffmpeg.exe"])
    for tool in ffmpeg_tools:
        try:
            res = subprocess.run(
                [tool, "-hide_banner", "-i", str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=creation, timeout=30,
            )
            text = (res.stdout or b"").decode("utf-8", errors="replace")
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
            if m:
                h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return max(0, int(round((h * 3600 + mi * 60 + s) * 1000)))
        except Exception:
            continue
    return 0


def _parse_concat_segment_paths(concat_file: Path):
    """Parse FFmpeg concat demuxer list → absolute Paths that still exist."""
    if not concat_file.is_file():
        return []
    rows = []
    try:
        text = concat_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line.lower().startswith("file "):
            continue
        raw = line[5:].strip()
        if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
            raw = raw[1:-1].replace("'\\''", "'")
        elif raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        candidate = Path(raw)
        if candidate.is_file():
            rows.append(candidate)
    return rows


def _original_names_from_analysis(analysis_file: Path, count: int):
    """Return up to count original clip basenames from analysis.json (insertion order)."""
    if not analysis_file.is_file() or count <= 0:
        return []
    try:
        data = json.loads(analysis_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    names = []
    for key in data.keys():
        name = Path(str(key)).name
        if name:
            names.append(name)
        if len(names) >= count:
            break
    return names


def try_rebuild_segments_sidecar(output_path, ffmpeg=None):
    """Rebuild stem.segments.json from .group_merge_cache when missing.

    Used for products merged before segmented timeline support. Returns sidecar
    Path on success, else None.
    """
    output_path = Path(output_path)
    if not output_path.is_file():
        return None
    existing = load_group_segments_map(output_path)
    if existing:
        return group_segments_sidecar_path(output_path)

    cache_root = output_path.parent / ".group_merge_cache"
    if not cache_root.is_dir():
        return None

    # Stem like "12_去口气音合成" → group token "12"
    stem = output_path.stem
    group_token = stem
    for suffix in ("_去口气音合成", "去口气音合成", "_合成"):
        if group_token.endswith(suffix):
            group_token = group_token[: -len(suffix)]
            break
    group_token = group_token.strip("_- ")

    out_dur = _probe_media_duration_ms(output_path, ffmpeg=ffmpeg)
    best = None  # (score, rows, transition_ms)  lower score is better
    for cache_dir in sorted(cache_root.iterdir()):
        if not cache_dir.is_dir():
            continue
        final_file = cache_dir / "final.json"
        final_data = {}
        try:
            if final_file.is_file():
                final_data = json.loads(final_file.read_text(encoding="utf-8")) or {}
        except Exception:
            final_data = {}
        # Prefer exact output name match written by newer merges
        name_hit = (
            str(final_data.get("output_name") or final_data.get("output") or "")
            == output_path.name
            or str(final_data.get("group_name") or "") == group_token
        )
        segment_paths = _parse_concat_segment_paths(cache_dir / "concat.txt")
        if len(segment_paths) < 2:
            # Fall back to newest segment_NNN_* files by index
            by_index = {}
            for child in cache_dir.glob("segment_*.mp4"):
                m = re.match(r"segment_(\d+)_", child.name)
                if not m:
                    continue
                idx = int(m.group(1))
                prev = by_index.get(idx)
                if prev is None or child.stat().st_mtime >= prev.stat().st_mtime:
                    by_index[idx] = child
            segment_paths = [by_index[i] for i in sorted(by_index)]
        if len(segment_paths) < 2:
            continue

        names = _original_names_from_analysis(cache_dir / "analysis.json", len(segment_paths))
        # Strong match: originals look like 12-1.mp4 / 12_1.mp4 for product 12_去口气音合成
        prefix_hit = False
        if group_token and names:
            hits = 0
            for n in names:
                stem_n = Path(n).stem
                if (
                    stem_n == group_token
                    or stem_n.startswith(f"{group_token}-")
                    or stem_n.startswith(f"{group_token}_")
                ):
                    hits += 1
            prefix_hit = hits >= max(2, (len(names) + 1) // 2)

        durs = [_probe_media_duration_ms(p, ffmpeg=ffmpeg) for p in segment_paths]
        known = [d for d in durs if d > 0]
        if len(known) < 2 and not (name_hit or prefix_hit):
            continue
        if known:
            avg = int(round(sum(known) / len(known)))
        elif out_dur > 0:
            avg = max(80, int(round(out_dur / len(segment_paths))))
        else:
            avg = 2000
        durs = [d if d > 0 else avg for d in durs]
        total = sum(durs) or 1
        rows = []
        for i, (seg_path, dur) in enumerate(zip(segment_paths, durs)):
            rows.append({
                "name": names[i] if i < len(names) else seg_path.name,
                "duration_ms": max(80, dur),
                "original": "",
                "normalized": str(seg_path.resolve()),
            })
        transition_ms = int(final_data.get("transition_ms") or 0)
        if name_hit:
            best = (0.0, rows, transition_ms)
            break
        if prefix_hit:
            score = 0.01
            if out_dur > 0:
                score = min(0.05, abs(total - out_dur) / max(out_dur, 1))
            if best is None or score < best[0]:
                best = (score, rows, transition_ms)
            continue
        if out_dur > 0:
            score = abs(total - out_dur) / max(out_dur, 1)
            if best is None or score < best[0]:
                best = (score, rows, transition_ms)

    if not best:
        return None
    score, rows, transition_ms = best
    # Reject very poor duration matches (likely wrong cache group)
    if score > 0.22:
        return None
    return write_group_segments_map(output_path, rows, transition_ms=transition_ms)


def build_segmented_edit_state(output_path, duration_ms, original_audio_enabled=True):
    """Build timeline edit_state with one bar per merged segment (video + original_audio).

    Source ranges map into the **concatenated output file** (not originals), so edge
    drag adjusts which part of the finished file is used. Segment names help find
    the bad take; re-merge with milder trim if content was permanently cut by 去口气.

    Final export is still one continuous file; segments are timeline edit aids only.
    """
    data = load_group_segments_map(output_path)
    if not data:
        try:
            try_rebuild_segments_sidecar(output_path)
        except Exception:
            pass
        data = load_group_segments_map(output_path)
    if not data:
        return None
    segments = data.get("segments") or []
    if len(segments) < 2:
        return None
    duration_ms = max(1000, int(duration_ms or 0))
    raw = [max(80, int(s.get("duration_ms") or 0)) for s in segments]
    total_raw = sum(raw) or 1
    # Fit to real file duration (hard-cut ≈ 1.0; xfade slightly shorter)
    scale = duration_ms / total_raw
    t = 0
    video_tracks = []
    audio_tracks = []
    for i, seg in enumerate(segments):
        if i < len(segments) - 1:
            dur = max(80, int(round(raw[i] * scale)))
        else:
            dur = max(80, duration_ms - t)
        name = str(seg.get("name") or f"段{i + 1:02d}")
        label = f"{i + 1:02d}.{name}"
        video_tracks.append({
            "start": t,
            "end": t + dur,
            "source_start": t,
            "source_end": t + dur,
            "source_duration": duration_ms,
            "name": label,
        })
        audio_tracks.append({
            "start": t,
            "end": t + dur,
            "source_start": t,
            "source_end": t + dur,
            "source_duration": duration_ms,
            "name": f"{label}·音",
        })
        t += dur
    return {
        "duration_ms": duration_ms,
        "original_audio_enabled": bool(original_audio_enabled),
        "segmented": True,
        "tracks": {
            "video": video_tracks,
            "original_audio": audio_tracks,
            "bgm": [],
            "tts": [],
        },
    }


class GroupMergeWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    item_done = Signal(str, str, int, int)
    finished = Signal(bool, str)

    def __init__(self, groups, output, ffmpeg, transcribe, settings):
        super().__init__()
        self.groups = [(Path(folder), [Path(p) for p in clips]) for folder, clips in groups]
        self.output = Path(output)
        self.ffmpeg = str(ffmpeg)
        self.transcribe = transcribe
        self.settings = dict(settings)
        self.cancelled = False
        import threading
        self._active_processes = set()
        self._lock = threading.Lock()
        # 本地 Whisper 模型非线程安全；API 也可串行化避免打爆限流。
        # 分析阶段并行时：多路静音检测可重叠，ASR 经此锁排队。
        self._asr_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        # Windows MF 编码器多路并行易 “Could not open encoder before EOF”
        self._mf_encode_lock = threading.Lock()
        self.encoder = resolve_encoder(self.ffmpeg, self.settings.get("encoder_backend", "auto"))

    def cancel(self):
        self.cancelled = True
        with self._lock:
            for process in list(self._active_processes):
                if process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass

    @property
    def ffprobe(self):
        candidate = Path(self.ffmpeg).with_name("ffprobe" + Path(self.ffmpeg).suffix)
        return str(candidate if candidate.exists() else "ffprobe")

    def _run(self, command, timeout=None, heartbeat_label=None, heartbeat_sec=8.0):
        """Run FFmpeg/ffprobe. timeout=None means no hard limit (still cancellable).
        heartbeat_label: emit a log line every heartbeat_sec while still running
        so the UI does not look frozen on long QSV/filter encodes.
        """
        if self.cancelled:
            raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **hidden_kwargs(),
        )
        with self._lock:
            self._active_processes.add(process)
        started = time.monotonic()
        last_beat = started
        stdout = stderr = ""
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    now = time.monotonic()
                    if timeout is not None and (now - started) >= float(timeout):
                        try:
                            process.kill()
                            stdout, stderr = process.communicate(timeout=2.0)
                        except Exception:
                            try:
                                process.kill()
                            except Exception:
                                pass
                            stdout, stderr = "", ""
                        raise RuntimeError(
                            f"FFmpeg 超时（>{float(timeout):.0f}s）"
                            + (f"：{heartbeat_label}" if heartbeat_label else "")
                            + "。常见原因：Intel QSV 多路并行卡死，或滤镜图未结束。"
                            "请停止后重试（已改为硬件编码串行）。"
                        )
                    if heartbeat_label and (now - last_beat) >= float(heartbeat_sec):
                        last_beat = now
                        try:
                            self.log.emit(
                                f"编码进行中：{heartbeat_label}（已 {now - started:.0f}s，请稍候…）"
                            )
                        except Exception:
                            pass
                    if not self.cancelled:
                        continue
                    try:
                        process.terminate()
                        stdout, stderr = process.communicate(timeout=1.5)
                    except Exception:
                        process.kill()
                        stdout, stderr = process.communicate()
                    raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
        finally:
            with self._lock:
                self._active_processes.discard(process)
        if self.cancelled:
            raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
        if process.returncode:
            raise RuntimeError((stderr or "")[-1200:].strip() or "FFmpeg 处理失败")
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def _write_final_output(self, command, destination: Path):
        """Write via a temp file then atomically replace, so a locked/in-use final
        path (preview player still open from a previous run) cannot leave a
        half-written mp4 that Qt later rejects as “Invalid data…”."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.stem + f".tmp_{os.getpid()}.mp4")
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        # Point FFmpeg output at the temp path (last arg is always destination)
        if not command:
            raise RuntimeError("内部错误：空的合成命令")
        command = list(command[:-1]) + [str(temporary)]
        try:
            self._run(command)
            if not temporary.is_file() or temporary.stat().st_size < 1024:
                raise RuntimeError(f"合成输出无效或过小：{temporary.name}")
            # Replace may fail if the destination is still open; retry briefly.
            last_error = None
            for attempt in range(8):
                try:
                    os.replace(str(temporary), str(destination))
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.12 * (attempt + 1))
            if last_error is not None:
                # Fall back to a unique name rather than leave a broken final file
                alt = destination.with_name(
                    f"{destination.stem}_{int(time.time())}{destination.suffix}"
                )
                try:
                    os.replace(str(temporary), str(alt))
                    self.log.emit(
                        f"提醒：原成品文件被占用无法覆盖，已改存为 {alt.name}。"
                        "请先停止预览后再合成，以便覆盖同名文件。"
                    )
                    return alt
                except OSError:
                    raise RuntimeError(
                        f"无法写入成品（文件可能被播放器占用）：{destination.name}\n"
                        f"请先停止预览/关闭占用该文件的程序后重试。\n{last_error}"
                    ) from last_error
            return destination
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def _probe(self, path):
        result = self._run([
            self.ffprobe, "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height", "-of", "json", str(path),
        ])
        data = json.loads(result.stdout or "{}")
        video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
        return {
            "duration": float(data.get("format", {}).get("duration") or 0),
            "width": int(video.get("width") or 1080),
            "height": int(video.get("height") or 1920),
            "audio": any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])),
        }

    @staticmethod
    def _signature(path):
        stat = Path(path).stat()
        return {"path": str(Path(path).resolve()), "size": stat.st_size, "mtime": stat.st_mtime_ns}

    def _analysis(self, clip, cache):
        signature = self._signature(clip)
        key = str(Path(clip).resolve())
        with self._cache_lock:
            saved = dict(cache.get(key, {}) or {})
        if (self.settings.get("resume", True) and saved.get("signature") == signature
                and str(saved.get("srt") or "").strip()):
            self.log.emit(f"续接：复用语音边界 {clip.name}")
            return saved
        self.log.emit(f"正在识别说话边界：{clip.name}（此阶段可能需要一些时间）")
        # ASR 串行：本地 Whisper 同模型不可并发；API 亦避免瞬间打满配额
        with self._asr_lock:
            if self.cancelled:
                raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
            original, _translated, srt = self.transcribe(str(clip))
        if not str(srt or "").strip():
            raise RuntimeError("没有识别到带时间轴的有效文案")
        with self._cache_lock:
            saved = dict(cache.get(key, {}) or {})
            info = {**saved, "signature": signature, "original": str(original or ""), "srt": str(srt or "")}
            cache[key] = info
        self.log.emit(f"说话边界识别完成：{clip.name}")
        return info

    def _silence_events_head_tail(self, clip, duration, threshold, minimum):
        """只解码片头/片尾做 silencedetect，避免整段 8s×N 全文件扫（智能混合时显著加速）。"""
        duration = max(0.05, float(duration or 0.05))
        threshold = int(threshold)
        minimum = max(0.06, float(minimum))
        af = f"silencedetect=noise={threshold}dB:d={minimum:.3f}"
        events = []

        def collect(stderr, offset=0.0):
            for kind, value in re.findall(r"silence_(start|end):\s*([0-9.]+)", stderr or ""):
                events.append((kind, float(value) + float(offset)))

        # 短片：一次全扫更省事
        if duration <= 6.5:
            result = self._run([
                self.ffmpeg, "-hide_banner", "-nostats", "-i", str(clip),
                "-map", "0:a:0", "-af", af, "-f", "null", "-",
            ])
            collect(result.stderr, 0.0)
            return events

        head_win = min(3.2, max(1.2, duration * 0.42))
        tail_win = min(5.5, max(1.5, duration * 0.55))
        # 片头窗口
        result = self._run([
            self.ffmpeg, "-hide_banner", "-nostats",
            "-t", f"{head_win:.3f}", "-i", str(clip),
            "-map", "0:a:0", "-af", af, "-f", "null", "-",
        ])
        collect(result.stderr, 0.0)
        # 片尾窗口（-ss 在 -i 前：时间戳从 0 起，需加 offset）
        tail_ss = max(0.0, duration - tail_win)
        if tail_ss > head_win * 0.85:
            result = self._run([
                self.ffmpeg, "-hide_banner", "-nostats",
                "-ss", f"{tail_ss:.3f}", "-i", str(clip),
                "-map", "0:a:0", "-af", af, "-f", "null", "-",
            ])
            collect(result.stderr, tail_ss)
        return events

    def _fast_analysis(self, clip, cache):
        """本地片头/片尾静音（安全版）：中间停顿绝不裁切。"""
        signature = self._signature(clip)
        key = str(Path(clip).resolve())
        threshold = int(self.settings.get("silence_threshold_db", -35))
        minimum = max(0.06, float(self.settings.get("silence_min_ms", 180)) / 1000.0)
        params = {"threshold": threshold, "minimum": round(minimum, 3),
                  "head": int(self.settings.get("head_padding_ms", 80)),
                  "tail": int(self.settings.get("tail_padding_ms", 120)),
                  "scan": "head_tail_v5"}
        with self._cache_lock:
            saved = dict(cache.get(key, {}) or {})
        # v5 = 首尾窗口 silencedetect + safe_silence_bounds；旧 v4 全片扫仍可续接
        if (self.settings.get("resume", True) and saved.get("signature") == signature
                and saved.get("fast_bounds_version") in (4, 5)
                and saved.get("fast_params") == params
                and saved.get("bounds")):
            self.log.emit(f"续接：复用本地声音边界 {clip.name}")
            return saved
        # 兼容旧缓存：同签名且已有 bounds，参数仅 scan 字段不同时仍可复用
        if (self.settings.get("resume", True) and saved.get("signature") == signature
                and saved.get("fast_bounds_version") in (4, 5) and saved.get("bounds")
                and isinstance(saved.get("fast_params"), dict)
                and saved["fast_params"].get("threshold") == params["threshold"]
                and saved["fast_params"].get("minimum") == params["minimum"]
                and saved["fast_params"].get("head") == params["head"]
                and saved["fast_params"].get("tail") == params["tail"]):
            self.log.emit(f"续接：复用本地声音边界 {clip.name}")
            return saved
        probe = self._probe(clip)
        duration = max(0.05, probe["duration"])
        if not probe["audio"]:
            info = {**saved, "signature": signature, "fast_bounds_version": 5,
                    "fast_params": params, "duration": duration, "bounds": [0.0, duration, False]}
            with self._cache_lock:
                prev = dict(cache.get(key, {}) or {})
                info = {**prev, **info}
                cache[key] = info
            return info
        self.log.emit(f"快速检测首尾声音：{clip.name}（仅片头/片尾，保护说话内容）")
        events = self._silence_events_head_tail(clip, duration, threshold, minimum)
        start, end, detected = safe_silence_bounds(
            duration, events,
            self.settings.get("head_padding_ms", 80),
            self.settings.get("tail_padding_ms", 120),
        )
        with self._cache_lock:
            prev = dict(cache.get(key, {}) or {})
            info = {**prev, "signature": signature, "fast_bounds_version": 5,
                    "fast_params": params, "duration": duration, "bounds": [start, end, detected]}
            cache[key] = info
        return info

    def _persist_analysis_cache(self, cache_file, analysis_cache):
        try:
            with self._cache_lock:
                payload = json.dumps(analysis_cache, ensure_ascii=False, indent=2)
            cache_file.write_text(payload, encoding="utf-8")
        except Exception:
            pass

    def _analyze_clip(self, clip, analysis_cache, *, need_asr, need_fast, trim_mode, script_mode):
        """单片段分析（可并行）：先静音后 ASR，便于多路静音与一路 ASR 重叠。"""
        if self.cancelled:
            raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
        key = str(clip.resolve())
        if trim_mode == "none" and not script_mode:
            return key, {}
        if not need_asr and not need_fast:
            return key, {}
        analysis = {}
        try:
            # 静音检测无 GPU/模型，优先跑完，再进 ASR 锁 —— 并行收益最大
            if need_fast:
                analysis = self._fast_analysis(clip, analysis_cache)
            if need_asr:
                analysis = self._analysis(clip, analysis_cache)
            if trim_mode == "hybrid":
                media_duration = float(analysis.get("duration") or self._probe(clip)["duration"])
                analysis["hybrid_bounds"] = list(hybrid_trim_bounds(
                    analysis.get("srt", ""), media_duration, analysis.get("bounds"),
                    self.settings.get("head_padding_ms", 80),
                    self.settings.get("tail_padding_ms", 120),
                ))
                with self._cache_lock:
                    prev = dict(analysis_cache.get(key, {}) or {})
                    analysis = {**prev, **analysis}
                    analysis_cache[key] = analysis
                hb = analysis["hybrid_bounds"]
                self.log.emit(
                    f"智能混合边界：{clip.name} → "
                    f"{float(hb[0]):.2f}s–{float(hb[1]):.2f}s"
                    f"{'' if hb[2] else '（回退完整）'}"
                )
            elif trim_mode == "fast":
                self.log.emit(f"快速声音边界：已完成本地首尾检测 {clip.name}")
            elif trim_mode == "none" and script_mode:
                self.log.emit(f"文案识别完成（不裁剪，仅用于按分段文案排序）：{clip.name}")
            elif need_asr:
                self.log.emit(f"智能文案边界：已按首词/末词时间定位 {clip.name}")
            return key, analysis
        except Exception as exc:
            if script_mode and need_asr:
                raise
            if need_asr:
                self.log.emit(
                    f"智能文案边界识别失败，自动改用本地声音边界继续处理：{clip.name}（{exc}）"
                )
                return key, self._fast_analysis(clip, analysis_cache)
            raise

    def _normalize(self, clip, index, total_count, cache_dir, analysis, target_w, target_h, watermark=None, group_script=""):
        probe = self._probe(clip)
        # Prefer the group-level script (virtual groups like 2-1/2-2 live under parent dir,
        # so clip.parent is NOT the group key used when saving 分段文案).
        if not str(group_script or "").strip():
            group_script = lookup_group_script(self.settings.get("scripts", {}), clip.parent)
        segments = split_group_script(group_script, total_count)
        clip_script = segments[index] if index < len(segments) else ""
        
        manual_bounds = None
        if clip_script:
            match = re.search(r'\[\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*\]', clip_script)
            if match:
                val1, val2 = float(match.group(1)), float(match.group(2))
                if val2 <= probe["duration"]:
                    manual_bounds = (val1, val2)
                clip_script = re.sub(r'\[\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*\]', '', clip_script).strip()

        trim_mode = self.settings.get("trim_mode", "hybrid")
        head_ms = int(self.settings.get("head_padding_ms", 100) or 100)
        tail_ms = int(self.settings.get("tail_padding_ms", 280) or 280)
        srt = str(analysis.get("srt") or "")
        media_duration = probe["duration"]

        reason = ""
        if manual_bounds is not None:
            start = max(0.0, min(media_duration, manual_bounds[0]))
            end = max(start + 0.05, min(media_duration, manual_bounds[1]))
            detected = True
            reason = "手动切片"
            self.log.emit(f"切片功能：{clip.name} 已应用手动切片区间 {start:.2f}s - {end:.2f}s")
        elif trim_mode == "none":
            start, end, detected = 0.0, media_duration, True
            reason = "不裁剪"
            self.log.emit(f"不裁剪：{clip.name} 保留完整片段。")
        else:
            start, end, detected, reason = resolve_trim_bounds(
                trim_mode, srt, clip_script,
                analysis.get("bounds"), analysis.get("hybrid_bounds"),
                media_duration, head_ms, tail_ms,
            )
        if not detected:
            self.log.emit(f"提醒：{clip.name} {reason or '未识别边界'}，保留完整片段。")
            start, end = 0.0, media_duration
        else:
            spans = _speech_spans(srt)
            if spans and trim_mode != "none":
                # 尾底线：末词 + max(尾保护, 450ms)
                floor_end = min(media_duration, spans[-1][1] + max(0.45, tail_ms / 1000.0))
                if end < floor_end:
                    end = floor_end
                    reason = f"{reason}+尾底线"
                # 末词距片尾 ≤1.2s：直接用到文件尾（如 14-5 的 preocupa 贴尾）
                if media_duration - spans[-1][1] <= 1.20:
                    if end < media_duration - 0.02:
                        end = media_duration
                        reason = f"{reason}+贴尾整段"
            # 能量续尾：ASR 结束后若仍有声，继续延长
            if trim_mode != "none" and end < media_duration - 0.08:
                try:
                    extended = energy_extend_end(
                        self.ffmpeg, clip, end, media_duration, max_extend=1.8,
                    )
                    if extended > end + 0.04:
                        self.log.emit(
                            f"能量续尾：{clip.name} {end:.2f}s → {extended:.2f}s"
                            f"（+{extended - end:.2f}s 补 ASR 未标出的尾音）"
                        )
                        end = extended
                        reason = f"{reason}+能量续尾"
                except Exception as exc:
                    self.log.emit(f"提醒：能量续尾跳过 {clip.name}：{exc}")
            # 片头：start 不得晚于「首词前 120ms」，避免切掉词头辅音
            if spans and trim_mode != "none":
                first = spans[0][0]
                start = min(start, max(0.0, first - 0.12))
            self.log.emit(
                f"去口气音：{clip.name} 保留 {start:.2f}s - {end:.2f}s"
                f"（{reason}｜首保护{head_ms}ms 尾保护{tail_ms}ms）"
            )

        # 转场预留（v14 自然接缝）：
        # 旧方案在片头/片尾「垫静音」再 acrossfade → 听感是「停一下再说话」。
        # 新方案：只在源文件里还有真实余量时多取一点（多为句末静音/气口），
        # 绝不人工垫静音；合并时用短音频交叉淡化，画面可稍长叠化。
        transition_pad = 0.0
        start_silence_pad = 0.0  # 保留字段兼容指纹/日志，v14 恒为 0
        end_silence_pad = 0.0
        if total_count > 1:
            tname = str(self.settings.get("transition_name") or "无转场")
            if tname and tname != "无转场":
                try:
                    td = float(self.settings.get("transition_duration") or 0.22)
                except (TypeError, ValueError):
                    td = 0.22
                # 接缝缓冲不必等于转场全长；0.12~0.28 足够给画面叠化
                transition_pad = max(0.12, min(0.35, td if td >= 0.10 else 0.22))
                if index < total_count - 1:
                    room = media_duration - end
                    if room > 0.02:
                        # 只吃真实片尾余量，不造静音
                        end = min(media_duration, end + min(transition_pad, room))
                if index > 0:
                    room = start
                    if room > 0.02:
                        start = max(0.0, start - min(transition_pad, room))
                if transition_pad > 0:
                    self.log.emit(
                        f"转场预留：{clip.name} 段{index + 1}/{total_count} "
                        f"真实余量缓冲≤{transition_pad:.2f}s（不垫静音，避免接缝停顿）"
                    )

        # 硬性校验：无效裁切会导致 0 帧 → “Could not open encoder before EOF / nothing written”
        media_duration = max(0.08, float(media_duration or probe.get("duration") or 0.08))
        if start >= media_duration - 0.04 or end <= start + 0.04:
            self.log.emit(
                f"提醒：{clip.name} 裁切区间无效（{float(start):.2f}–{float(end):.2f}s / 片长 {media_duration:.2f}s），"
                f"改用整段，避免空帧编码失败。"
            )
            start, end = 0.0, media_duration
            reason = f"{reason or '边界'}→整段回退"
        start = max(0.0, min(float(start), media_duration - 0.08))
        end = max(start + 0.08, min(float(end), media_duration))
        duration = max(0.08, end - start)
        # H.264/yuv420p 要求偶数分辨率
        target_w = max(2, int(target_w) // 2 * 2)
        target_h = max(2, int(target_h) // 2 * 2)
        if int(probe.get("width") or 0) < 2 or int(probe.get("height") or 0) < 2:
            raise RuntimeError(
                f"{clip.name} 没有有效视频流（{probe.get('width')}×{probe.get('height')}），无法编码。"
            )
        removed = max(0.0, float(probe.get("duration") or 0) - duration)
        ratio = (removed / probe["duration"] * 100.0) if probe.get("duration") else 0.0
        self.log.emit(
            f"时长：{clip.name} 原始 {probe['duration']:.2f}s → 取源 {duration:.2f}s"
            f"，删减 {removed:.2f}s（{ratio:.1f}%）"
        )
        if ratio > 40:
            self.log.emit(f"提醒：{clip.name} 删减超过 40%，请检查文案时间轴或适当调低静音阈值。")
        watermark = Path(watermark) if watermark and Path(watermark).is_file() else None
        # version 11：片尾不够转场时垫静音/定格，避免 acrossfade 吃真词
        fingerprint = hashlib.sha256(json.dumps({
            "source": self._signature(clip), "start": round(start, 3), "end": round(end, 3),
            "width": target_w, "height": target_h,
            "watermark": self._signature(watermark) if watermark else None,
            "clean_metadata": bool(self.settings.get("clean_metadata", True)),
            "trim_mode": str(trim_mode),
            "tail_ms": int(tail_ms),
            "tpad": round(transition_pad, 3),
            "spad": round(start_silence_pad, 3),
            "epad": round(end_silence_pad, 3),
            "index": int(index),
            "version": 15,  # clamp empty trim + accurate -ss after -i
        }, sort_keys=True).encode("utf-8")).hexdigest()[:14]
        destination = cache_dir / f"segment_{index + 1:03d}_{fingerprint}.mp4"
        if self.settings.get("resume", True) and destination.exists() and destination.stat().st_size > 1024:
            self.log.emit(f"续接：复用已处理片段 {clip.name}")
            return destination
        sp = float(start_silence_pad or 0.0)
        ep = float(end_silence_pad or 0.0)
        expect_out = duration + sp + ep
        self.log.emit(
            f"正在裁剪口气音并统一音视频参数：{clip.name}"
            f"（约 {expect_out:.1f}s，编码器 {ENCODER_LABELS.get(self.encoder, self.encoder)}）"
        )
        # 画面核心：分辨率已一致时跳过 scale/crop。
        # 时间戳归零 + 关 B 帧：避免达芬奇看到 video start_time≈1 帧的片头黑帧。
        # 中间段不强行 fps=30（源多为 24/25/30，重采样贵）；最终成片字幕烧录再统一 30fps。
        same_geometry = (
            int(probe.get("width") or 0) == int(target_w)
            and int(probe.get("height") or 0) == int(target_h)
        )
        if same_geometry:
            video_core = "setsar=1,format=yuv420p,setpts=PTS-STARTPTS"
        else:
            video_core = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h}:(iw-ow)/2:(ih-oh)/2,"
                f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS"
            )
        has_pad = sp > 0.01 or ep > 0.01
        need_complex = bool(watermark) or has_pad
        # 默认 -ss 在 -i 前（关键帧快进，快很多）。start≈0 时省略 -ss。
        # 若出现 0 帧再回退到 -ss 在 -i 后 / 整段（见下方重试逻辑）。
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if start > 0.02:
            command += ["-ss", f"{start:.3f}"]
        command += ["-t", f"{duration:.3f}", "-i", str(clip)]
        # —— 快路径：无水印、无垫片 → 简单 -vf/-af，比 filter_complex 轻很多 ——
        if not need_complex:
            command += ["-vf", video_core, "-map", "0:v:0"]
            if probe["audio"]:
                command += [
                    "-af",
                    "aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
                    "asetpts=PTS-STARTPTS",
                    "-map", "0:a:0",
                ]
            else:
                command += ["-an"]
            if self.settings.get("clean_metadata", True):
                command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                            "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                            "-map_chapters", "-1"]
            command += ["-sn", "-dn"]
            command += encoder_args(
                self.encoder, self.settings.get("encode_preset", "veryfast"), intermediate=True,
            )
            if probe["audio"]:
                command += ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000"]
            command += [
                "-t", f"{expect_out:.3f}",
                "-fps_mode", "cfr",
                "-muxdelay", "0", "-muxpreload", "0",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(destination),
            ]
        else:
            # 滤镜图：源 → 水印 → 头/尾定格；输出强制 -t 防止 loop 水印挂死
            wm_idx = None
            if watermark:
                command += [
                    "-loop", "1", "-framerate", "30",
                    "-t", f"{max(0.25, expect_out):.3f}",
                    "-i", str(watermark),
                ]
                wm_idx = 1

            fc_parts = []
            if watermark and wm_idx is not None:
                fc_parts.append(
                    f"[0:v]{video_core}[base];[{wm_idx}:v]scale={target_w}:{target_h},format=rgba[wm];"
                    f"[base][wm]overlay=0:0:shortest=1,format=yuv420p,setpts=PTS-STARTPTS[vcore]"
                )
            else:
                fc_parts.append(f"[0:v]{video_core}[vcore]")
            v_label = "vcore"
            if sp > 0.01:
                fc_parts.append(f"[{v_label}]tpad=start_mode=clone:start_duration={sp:.3f}[v1]")
                v_label = "v1"
            if ep > 0.01:
                fc_parts.append(f"[{v_label}]tpad=stop_mode=clone:stop_duration={ep:.3f}[v2]")
                v_label = "v2"
            # 垫片后再次归零，保证输出从 t=0 起
            fc_parts.append(f"[{v_label}]setpts=PTS-STARTPTS[vout]")
            v_label = "vout"

            a_label = None
            if probe["audio"]:
                fc_parts.append(
                    f"[0:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[acore]"
                )
                a_label = "acore"
                if sp > 0.01:
                    fc_parts.append(
                        f"aevalsrc=0|0:d={sp:.3f}:s=48000,"
                        f"aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[ah];"
                        f"[ah][{a_label}]concat=n=2:v=0:a=1[a1]"
                    )
                    a_label = "a1"
                if ep > 0.01:
                    fc_parts.append(
                        f"aevalsrc=0|0:d={ep:.3f}:s=48000,"
                        f"aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[at];"
                        f"[{a_label}][at]concat=n=2:v=0:a=1[a2]"
                    )
                    a_label = "a2"
                fc_parts.append(
                    f"[{a_label}]apad=whole_dur={expect_out:.3f},"
                    f"atrim=0:{expect_out:.3f},asetpts=PTS-STARTPTS[aout]"
                )
                a_label = "aout"

            fc = ";".join(fc_parts)
            command += ["-filter_complex", fc, "-map", f"[{v_label}]"]
            if a_label:
                command += ["-map", f"[{a_label}]"]
            else:
                command += ["-an"]
            if self.settings.get("clean_metadata", True):
                command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                            "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                            "-map_chapters", "-1"]
            command += ["-sn", "-dn"]
            command += encoder_args(
                self.encoder, self.settings.get("encode_preset", "veryfast"), intermediate=True,
            )
            if a_label:
                command += ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000"]
            command += [
                "-t", f"{expect_out:.3f}",
                "-fps_mode", "cfr",
                "-muxdelay", "0", "-muxpreload", "0",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(destination),
            ]
        # 8s 片段正常应 <15s；给硬件/水印余量。超时即杀，避免「一直卡在这里」
        encode_timeout = max(90.0, min(600.0, expect_out * 25.0 + 45.0))
        t0 = time.monotonic()

        def _to_cpu_command(cmd):
            """Replace hardware encoder flags with libx264."""
            retry = list(cmd)
            for i, tok in enumerate(retry):
                if tok == "-c:v" and i + 1 < len(retry):
                    retry[i + 1] = "libx264"
                    break
            drop_keys = {
                "-rate_control", "-quality", "-cq", "-b:v", "-rc",
                "-look_ahead", "-tune", "-qp_i", "-qp_p", "-bf_delta_qp",
                "-global_quality", "-preset", "-crf", "-bf",
            }
            cleaned = []
            skip_next = False
            for i, tok in enumerate(retry):
                if skip_next:
                    skip_next = False
                    continue
                if tok in drop_keys:
                    skip_next = True
                    continue
                cleaned.append(tok)
                if tok == "libx264" and i > 0 and retry[i - 1] == "-c:v":
                    cleaned.extend(["-preset", "veryfast", "-crf", "23", "-bf", "0"])
            if "-pix_fmt" not in cleaned:
                cleaned = cleaned[:-1] + ["-pix_fmt", "yuv420p"] + cleaned[-1:]
            return cleaned

        def _full_clip_command(cmd):
            """去掉裁切，整段编码（空帧/越界 seek 的最后手段）。"""
            out = list(cmd)
            # 删除 -ss / -t 参数对（紧跟在 -i 后或前）
            cleaned = []
            i = 0
            while i < len(out):
                if out[i] in ("-ss", "-t") and i + 1 < len(out):
                    i += 2
                    continue
                cleaned.append(out[i])
                i += 1
            return cleaned

        def _run_encode(cmd, label):
            self._run(cmd, timeout=encode_timeout, heartbeat_label=label, heartbeat_sec=6.0)

        def _accurate_ss_command(cmd):
            """把 -ss 移到 -i 之后（精确裁切，略慢；仅作空帧失败后的回退）。"""
            out = list(cmd)
            ss_val = None
            cleaned = []
            i = 0
            while i < len(out):
                if out[i] == "-ss" and i + 1 < len(out):
                    ss_val = out[i + 1]
                    i += 2
                    continue
                cleaned.append(out[i])
                i += 1
            if not ss_val:
                return cleaned
            # 在 -i <path> 之后插入 -ss
            result = []
            i = 0
            while i < len(cleaned):
                result.append(cleaned[i])
                if cleaned[i] == "-i" and i + 1 < len(cleaned):
                    result.append(cleaned[i + 1])
                    result.extend(["-ss", ss_val])
                    i += 2
                    continue
                i += 1
            return result

        def _empty_output_error(err: str) -> bool:
            low = err.lower()
            return any(
                token in low
                for token in (
                    "could not open encoder",
                    "nothing was written",
                    "received no packets",
                    "error code: -22",
                    "invalid argument",
                )
            )

        try:
            _run_encode(command, clip.name)
        except Exception as exc:
            err = str(exc)
            empty = _empty_output_error(err)
            hw = self.encoder in ("mf", "nvenc", "qsv", "amf")
            try:
                if destination.exists():
                    destination.unlink()
            except OSError:
                pass
            # 1) 空帧：先试精确 -ss（-i 后），仍失败再整段
            # 2) 硬件失败：改 CPU
            if not (hw or empty):
                raise
            retry_cmd = command
            if empty and start > 0.02:
                self.log.emit(
                    f"提醒：{clip.name} 可能关键帧 seek 空帧，改用精确裁切重试…"
                )
                retry_cmd = _accurate_ss_command(command)
            if hw:
                self.log.emit(
                    f"提醒：{clip.name} 编码失败（{self.encoder}），"
                    f"{'空帧/无效参数，' if empty else ''}"
                    f"自动改用 CPU 重试本段…"
                )
                retry_cmd = _to_cpu_command(retry_cmd)
            try:
                _run_encode(retry_cmd, f"{clip.name}·重试")
            except Exception as exc2:
                err2 = str(exc2)
                if _empty_output_error(err2) or empty:
                    self.log.emit(
                        f"提醒：{clip.name} 裁切后仍无帧，改用整段 0–{media_duration:.2f}s 再试…"
                    )
                    try:
                        if destination.exists():
                            destination.unlink()
                    except OSError:
                        pass
                    full_cmd = _full_clip_command(_to_cpu_command(command))
                    full_cmd = full_cmd[:-1] + [
                        "-t", f"{media_duration:.3f}",
                        full_cmd[-1],
                    ]
                    _run_encode(full_cmd, f"{clip.name}·整段")
                    expect_out = media_duration
                else:
                    raise RuntimeError(
                        f"片段编码失败：{clip.name} — {err2}"
                    ) from exc2
        elapsed = time.monotonic() - t0
        # 校验垫片后时长
        try:
            out_dur = float(self._probe(destination)["duration"])
            if abs(out_dur - expect_out) > 0.35:
                self.log.emit(
                    f"提醒：{clip.name} 输出时长 {out_dur:.2f}s 与预期 {expect_out:.2f}s 偏差较大，请检查垫片。"
                )
            else:
                self.log.emit(
                    f"片段校验：{clip.name} 输出 {out_dur:.2f}s（含垫片，预期≈{expect_out:.2f}s，耗时 {elapsed:.1f}s）"
                )
        except Exception:
            self.log.emit(f"片段处理完成：{clip.name}（耗时 {elapsed:.1f}s）")
        else:
            self.log.emit(f"片段处理完成：{clip.name}")
        return destination

    def run(self):
        outputs = []
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            self.log.emit(f"分段统一编码：{ENCODER_LABELS[self.encoder]}")
            cache_root = self.output / ".group_merge_cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            total_steps = max(1, sum(len(clips) * 2 + 1 for _folder, clips in self.groups))
            completed_steps = 0
            for group_index, (folder, incoming_clips) in enumerate(self.groups, 1):
                if self.cancelled:
                    raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
                clips = sorted(incoming_clips, key=lambda p: natural_key(p.name))
                group_id = hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:12]
                cache_dir = cache_root / group_id
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = cache_dir / "analysis.json"
                try:
                    analysis_cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
                except Exception:
                    analysis_cache = {}
                analyses = {}
                self.log.emit(f"[{group_index}/{len(self.groups)}] 开始处理文件夹：{folder.name}（{len(clips)} 段）")
                script_mode = self.settings.get("sort_mode") == "script"
                trim_mode = self.settings.get("trim_mode", "hybrid")
                group_script = lookup_group_script(self.settings.get("scripts", {}), folder)
                if script_mode and not group_script:
                    self.log.emit(
                        f"提醒：未在 scripts 中找到「{folder}」的分段文案"
                        f"（已登记 {len(self.settings.get('scripts') or {})} 组键）。"
                    )
                group_manual_bounds = None
                if group_script:
                    match = re.search(r'\[\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*\]', group_script)
                    if match:
                        val1, val2 = float(match.group(1)), float(match.group(2))
                        first_probe = self._probe(clips[0])
                        if val2 > first_probe["duration"]:
                            group_manual_bounds = (val1, val2)
                # 裁剪模式需要的分析数据：
                # - none: 不需要（但文案排序仍要 ASR）
                # - text/hybrid: 需要 ASR 时间轴
                # - fast: 需要本地静音边界
                # - 文案排序: 无论裁剪模式都要 ASR（用于 match_clips_to_script）
                need_asr = script_mode or trim_mode in ("hybrid", "text")
                need_fast = trim_mode in ("hybrid", "fast")
                from concurrent.futures import ThreadPoolExecutor, as_completed
                # 静音检测可多路并行；ASR 在内部加锁串行 → 工人数略大于 1 即可重叠「静音||ASR」
                if need_fast and not need_asr:
                    analysis_workers = min(4, max(1, len(clips)))
                elif need_asr and need_fast:
                    analysis_workers = min(3, max(1, len(clips)))
                elif need_asr:
                    analysis_workers = min(2, max(1, len(clips)))
                else:
                    analysis_workers = 1
                if len(clips) > 1 and (need_asr or need_fast):
                    self.log.emit(
                        f"边界分析并行：{analysis_workers} 路"
                        f"（{'静音可重叠 + ASR 排队' if need_asr and need_fast else '静音并行' if need_fast else 'ASR'}）"
                        f" · 本组 {len(clips)} 段"
                    )
                if trim_mode == "none" and not script_mode:
                    for clip in clips:
                        analyses[str(clip.resolve())] = {}
                        completed_steps += 1
                        self.progress.emit(round(completed_steps / total_steps * 100))
                else:
                    def _job(c):
                        return self._analyze_clip(
                            c, analysis_cache,
                            need_asr=need_asr, need_fast=need_fast,
                            trim_mode=trim_mode, script_mode=script_mode,
                        )
                    with ThreadPoolExecutor(max_workers=analysis_workers) as executor:
                        futures = {executor.submit(_job, clip): clip for clip in clips}
                        for future in as_completed(futures):
                            if self.cancelled:
                                for other in futures:
                                    other.cancel()
                                raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
                            clip = futures[future]
                            try:
                                key, analysis = future.result()
                            except Exception as exc:
                                for other in futures:
                                    other.cancel()
                                raise RuntimeError(f"边界分析失败：{clip.name} — {exc}") from exc
                            analyses[key] = analysis
                            self._persist_analysis_cache(cache_file, analysis_cache)
                            completed_steps += 1
                            self.progress.emit(round(completed_steps / total_steps * 100))
                self._persist_analysis_cache(cache_file, analysis_cache)
                if self.settings.get("sort_mode") == "script":
                    if not str(group_script or "").strip():
                        self.log.emit("提醒：本组未找到分段文案，自动回退为文件名自然排序。")
                    else:
                        # Pass full analysis dicts so matching can use SRT + original variants.
                        ordered, reason, details = match_clips_to_script(
                            clips,
                            analyses,
                            group_script,
                        )
                        if ordered:
                            clips = ordered
                            self.log.emit(reason)
                            for item in details:
                                self.log.emit(
                                    f"  文案第{item['segment_index'] + 1}段 ↔ {item['clip'].name}"
                                    f" (相似度 {item['score']:.2f})｜文案: {item['script_preview']!s}"
                                    f"｜识别: {item['transcript_preview']!s}"
                                )
                            order_desc = " → ".join(f"{i + 1}.{path.name}" for i, path in enumerate(clips))
                            self.log.emit(f"合成顺序（按分段文案）：{order_desc}")
                        else:
                            if details:
                                for item in details:
                                    self.log.emit(
                                        f"  候选 文案第{item['segment_index'] + 1}段 ↔ {item['clip'].name}"
                                        f" (相似度 {item['score']:.2f})"
                                    )
                            self.log.emit(f"提醒：{reason}，本组自动回退为文件名自然排序。")
                first_probe = self._probe(clips[0])
                target_w, target_h = calculate_target_size(
                    first_probe["width"], first_probe["height"],
                    self.settings.get("aspect_ratio", "原始比例"),
                    self.settings.get("resolution", "默认最高")
                )
                watermark = None
                prepare_watermark = self.settings.get("watermark_prepare")
                if self.settings.get("burn_watermark") and callable(prepare_watermark):
                    watermark = Path(prepare_watermark(str(clips[0]), str(cache_dir)))
                    if watermark.is_file():
                        self.log.emit("已启用合成时烧录水印：水印将在片段统一编码时一次完成，后续导出不重复烧录。")
                    else:
                        watermark = None
                from concurrent.futures import ThreadPoolExecutor, as_completed
                import os
                # QSV 多开易死锁；MF/NVENC/AMF 双路（失败单段会 CPU 回退）；CPU 最多 4 路。
                if self.encoder == "qsv":
                    max_workers = 1
                    self.log.emit(
                        "编码策略：Intel Quick Sync 串行（避免多路会话互锁）。"
                    )
                elif self.encoder in ("nvenc", "mf", "amf"):
                    max_workers = min(2, len(clips), os.cpu_count() or 2)
                    self.log.emit(
                        f"编码策略：硬件编码并行 {max_workers}"
                        f"（{ENCODER_LABELS.get(self.encoder, self.encoder)}；"
                        f"单段失败自动 CPU 重试）。"
                    )
                else:
                    max_workers = min(4, len(clips), os.cpu_count() or 4)
                    self.log.emit(
                        f"编码策略：CPU 并行 {max_workers} 路。"
                        f" 提示：片段多时建议改「自动硬件加速」可明显提速。"
                    )
                def run_norm(args):
                    clip, clip_index, total_count = args
                    return self._normalize(
                        clip, clip_index, total_count, cache_dir, analyses[str(clip.resolve())],
                        target_w, target_h, watermark, group_script=group_script,
                    )
                tasks = [(clip, clip_index, len(clips)) for clip_index, clip in enumerate(clips)]
                normalized = [None] * len(clips)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(run_norm, task): i for i, task in enumerate(tasks)}
                    for future in as_completed(futures):
                        i = futures[future]
                        try:
                            normalized[i] = future.result()
                        except Exception as exc:
                            # 取消其余任务，避免超时后仍占 QSV
                            for other in futures:
                                other.cancel()
                            raise RuntimeError(
                                f"片段编码失败：{tasks[i][0].name} — {exc}"
                            ) from exc
                        completed_steps += 1
                        self.progress.emit(round(completed_steps / total_steps * 100))
                if any(path is None or not Path(path).is_file() for path in normalized):
                    raise RuntimeError(f"{folder.name} 有片段编码失败，无法合成。")
                if any(not self._probe(path)["audio"] for path in normalized):
                    raise RuntimeError(f"{folder.name} 中存在没有音轨的片段，无法保证无缝合并声音。")
                # 明确记录拼接顺序：源文件名 → 缓存段文件（便于核对「名字对、内容错」）
                order_lines = []
                for i, (src, norm) in enumerate(zip(clips, normalized), 1):
                    order_lines.append(f"{i:02d}. {Path(src).name} → {Path(norm).name}")
                self.log.emit("拼接顺序（必须与听感一致）：\n  " + "\n  ".join(order_lines))
                concat_file = cache_dir / "concat.txt"
                concat_file.write_text("\n".join(
                    "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'" for path in normalized
                ), encoding="utf-8")
                # 旁路清单，方便人工打开核对
                try:
                    (cache_dir / "concat_order.txt").write_text(
                        "\n".join(order_lines) + "\n", encoding="utf-8"
                    )
                except Exception:
                    pass
                destination = self.output / f"{_safe_name(folder.name)}_去口气音合成.mp4"
                # Resolve group-specific transition name
                group_key = folder.resolve().as_posix().lower()
                custom_trans = self.settings.get("group_custom_transitions", {}).get(group_key, "跟随全局")
                if custom_trans != "跟随全局":
                    transition_name = custom_trans
                else:
                    transition_name = self.settings.get("transition_name", "无转场")

                final_fingerprint = hashlib.sha256(json.dumps({
                    "files": [self._signature(path) for path in normalized],
                    "clean_metadata": bool(self.settings.get("clean_metadata", True)),
                    "transition_name": transition_name,
                    "transition_duration": float(self.settings.get("transition_duration") or 0),
                    "aspect_ratio": self.settings.get("aspect_ratio", "原始比例"),
                    "resolution": self.settings.get("resolution", "默认最高"),
                    "group_script": group_script,
                    "version": 6,
                }, sort_keys=True).encode("utf-8")).hexdigest()
                state_file = cache_dir / "final.json"
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
                except Exception:
                    state = {}
                transition_cfg = resolve_merge_transition(transition_name)
                transition_key = (transition_cfg or {}).get("xfade") if transition_cfg else None
                actual_transition_duration = 0.0
                if not (self.settings.get("resume", True) and destination.exists() and destination.stat().st_size > 1024
                        and state.get("fingerprint") == final_fingerprint):
                    self.log.emit(f"正在合并文件夹“{folder.name}”的 {len(normalized)} 个片段，请等待…")
                    
                    if transition_key and len(normalized) > 1:
                        # 优先用户在 UI 设置的时长；未设置时用该转场类型的推荐默认值
                        user_dur = self.settings.get("transition_duration")
                        try:
                            user_dur = float(user_dur) if user_dur is not None else 0.0
                        except (TypeError, ValueError):
                            user_dur = 0.0
                        preset_dur = float((transition_cfg or {}).get("duration") or 0.22)
                        transition_duration = user_dur if user_dur >= 0.10 else preset_dur
                        # 口播默认偏短：画面最长 0.35s，避免长叠化造成「停一下」感
                        transition_duration = max(0.10, min(0.35, transition_duration))
                        segment_infos = [self._probe(path) for path in normalized]
                        min_segment_dur = min(info["duration"] for info in segment_infos)
                        actual_transition_duration = min(
                            transition_duration, max(0.10, min_segment_dur * 0.35)
                        )
                        # 音画必须同长叠化，否则 A/V 漂移；但不垫静音，叠的是真实句末/句首
                        self.log.emit(
                            f"应用合并转场「{transition_name}」→ xfade={transition_key}，"
                            f"时长 {actual_transition_duration:.2f}s（设定 {transition_duration:.2f}s），"
                            f"共 {len(normalized)} 段｜自然接缝（无静音垫）。"
                        )
                        
                        concat_command = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"
                        ]
                        for path in normalized:
                            concat_command += ["-i", str(path)]
                            
                        self.log.emit(
                            f"合并转场画面/声音同步 {actual_transition_duration:.2f}s；"
                            f"三角淡化，依赖尾保护气口而非垫静音。"
                        )
                        v_in = "[0:v]"
                        a_in = "[0:a]"
                        current_offset = segment_infos[0]["duration"] - actual_transition_duration
                        filter_parts = []
                        for i in range(1, len(normalized)):
                            next_v = f"[{i}:v]"
                            next_a = f"[{i}:a]"
                            out_v = f"[v_out_{i}]"
                            out_a = f"[a_out_{i}]"
                            filter_parts.append(
                                f"{v_in}{next_v}xfade=transition={transition_key}:"
                                f"duration={actual_transition_duration:.3f}:offset={current_offset:.3f}{out_v}"
                            )
                            # tri 比 exp 更干净；同长保证音画同步
                            filter_parts.append(
                                f"{a_in}{next_a}acrossfade=d={actual_transition_duration:.3f}:"
                                f"c1=tri:c2=tri{out_a}"
                            )
                            v_in = out_v
                            a_in = out_a
                            current_offset = (
                                current_offset + segment_infos[i]["duration"]
                                - actual_transition_duration
                            )
                        # 最终再归零时间戳，避免 xfade 链残留 start delay
                        filter_parts.append(f"{v_in}setpts=PTS-STARTPTS[vfinal]")
                        filter_parts.append(f"{a_in}asetpts=PTS-STARTPTS[afinal]")
                        filter_complex_str = ";".join(filter_parts)
                        concat_command += [
                            "-filter_complex", filter_complex_str,
                            "-map", "[vfinal]",
                            "-map", "[afinal]",
                        ]
                        concat_command += encoder_args(
                            self.encoder, self.settings.get("encode_preset", "veryfast"),
                            intermediate=True,
                        )
                        concat_command += ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000"]
                        if self.settings.get("clean_metadata", True):
                            concat_command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                               "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                               "-map_chapters", "-1"]
                        concat_command += [
                            "-fps_mode", "cfr",
                            "-muxdelay", "0", "-muxpreload", "0",
                            "-avoid_negative_ts", "make_zero",
                            "-movflags", "+faststart",
                            str(destination),
                        ]
                    else:
                        if transition_name and transition_name != "无转场" and len(normalized) <= 1:
                            self.log.emit(f"本组仅 1 个片段，跳过转场「{transition_name}」。")
                        # 轻量重封装（不重编码）归零时间戳，避免 stream copy 保留负 DTS/start delay
                        concat_command = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(concat_file), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                            "-muxdelay", "0", "-muxpreload", "0",
                            "-avoid_negative_ts", "make_zero",
                        ]
                        if self.settings.get("clean_metadata", True):
                            concat_command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                               "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                               "-map_chapters", "-1"]
                        concat_command += ["-movflags", "+faststart", str(destination)]
                        
                    destination = self._write_final_output(concat_command, destination)
                    if remux_zero_start(self.ffmpeg, destination):
                        self.log.emit("已归零成品时间戳（避免达芬奇/Resolve 片头黑帧）。")
                    # 已对齐则静默跳过，不刷日志（避免误以为又慢了一遍）
                    if group_manual_bounds:
                        self.log.emit(f"群组切片功能：正在对合并后的成品视频应用手动切片 {group_manual_bounds[0]:.2f}s - {group_manual_bounds[1]:.2f}s...")
                        trimmed_dest = destination.with_name(destination.stem + "_trimmed.mp4")
                        
                        total_dur = self._probe(destination)["duration"]
                        start = max(0.0, min(total_dur, group_manual_bounds[0]))
                        end = max(start + 0.05, min(total_dur, group_manual_bounds[1]))
                        dur = end - start
                        
                        trim_cmd = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", f"{start:.3f}", "-i", str(destination),
                            "-t", f"{dur:.3f}", "-c", "copy"
                        ]
                        if self.settings.get("clean_metadata", True):
                            trim_cmd += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                         "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                         "-map_chapters", "-1"]
                        trim_cmd += ["-movflags", "+faststart", str(trimmed_dest)]
                        
                        creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        res = subprocess.run(trim_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creation)
                        if res.returncode == 0:
                            try:
                                destination.unlink()
                                trimmed_dest.rename(destination)
                                self.log.emit(f"群组切片完成：已剪切保留 {start:.2f}s - {end:.2f}s 段。")
                            except Exception as e:
                                self.log.emit(f"群组切片重命名失败：{e}，保留未切片版本。")
                        else:
                            err = (res.stdout or b"").decode("utf-8", errors="replace")
                            self.log.emit(f"群组切片失败：{err}，保留未切片版本。")
                    used_transition_ms = 0
                    if transition_key and len(normalized) > 1 and actual_transition_duration:
                        used_transition_ms = int(round(float(actual_transition_duration) * 1000))
                    state_file.write_text(json.dumps({
                        "fingerprint": final_fingerprint,
                        "output_name": destination.name,
                        "group_name": folder.name,
                        "transition_ms": used_transition_ms,
                        "segment_count": len(normalized),
                    }, ensure_ascii=False, indent=2), encoding="utf-8")
                else:
                    self.log.emit(f"续接：复用已完成合成视频 {destination.name}")
                    used_transition_ms = 0
                    if transition_key and len(normalized) > 1 and actual_transition_duration:
                        used_transition_ms = int(round(float(actual_transition_duration) * 1000))
                # Sidecar: keep per-segment bars on the timeline for fine re-timing
                try:
                    seg_rows = []
                    for orig, norm in zip(clips, normalized):
                        try:
                            dur_ms = int(round(float(self._probe(norm)["duration"]) * 1000))
                        except Exception:
                            dur_ms = 0
                        seg_rows.append({
                            "name": Path(orig).name,
                            "duration_ms": max(80, dur_ms),
                            "original": str(Path(orig).resolve()),
                            "normalized": str(Path(norm).resolve()),
                        })
                    if not used_transition_ms:
                        if transition_key and len(normalized) > 1 and actual_transition_duration:
                            used_transition_ms = int(round(float(actual_transition_duration) * 1000))
                    sidecar = write_group_segments_map(
                        destination, seg_rows, transition_ms=used_transition_ms,
                    )
                    # Keep final.json aligned even on resume path
                    try:
                        prev = {}
                        if state_file.is_file():
                            prev = json.loads(state_file.read_text(encoding="utf-8")) or {}
                        prev.update({
                            "output_name": destination.name,
                            "group_name": folder.name,
                            "transition_ms": used_transition_ms,
                            "segment_count": len(seg_rows),
                        })
                        if "fingerprint" not in prev:
                            prev["fingerprint"] = final_fingerprint
                        state_file.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    if sidecar:
                        self.log.emit(
                            f"已写入分段轨道元数据（{len(seg_rows)} 段）：{sidecar.name}，"
                            "时间轴按段落显示便于微调；最终导出仍是一个完整视频。"
                        )
                except Exception as exc:
                    self.log.emit(f"提醒：分段轨道元数据写入失败（不影响成品）：{exc}")
                outputs.append(str(destination))
                completed_steps += 1
                self.progress.emit(round(completed_steps / total_steps * 100))
                self.item_done.emit(str(destination), folder.name, group_index, len(self.groups))
                self.log.emit(f"[{group_index}/{len(self.groups)}] 合成完成：{destination}")
            self.finished.emit(True, json.dumps({"outputs": outputs}, ensure_ascii=False))
        except Exception as exc:
            self.finished.emit(False, str(exc))
