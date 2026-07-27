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
from .video_encoding import ENCODER_LABELS, encoder_args, resolve_encoder, calculate_target_size


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
    "淡入淡出": {"xfade": "fade", "duration": 0.50},
    "溶解": {"xfade": "dissolve", "duration": 0.55},
    "淡入黑场": {"xfade": "fadeblack", "duration": 0.55},
    "淡入白场": {"xfade": "fadewhite", "duration": 0.55},
    "向左滑动": {"xfade": "slideleft", "duration": 0.50},
    "向右滑动": {"xfade": "slideright", "duration": 0.50},
    "向上滑动": {"xfade": "slideup", "duration": 0.50},
    "向下滑动": {"xfade": "slidedown", "duration": 0.50},
    "直线向左擦除": {"xfade": "wipeleft", "duration": 0.45},
    "直线向右擦除": {"xfade": "wiperight", "duration": 0.45},
    "直线向上擦除": {"xfade": "wipeup", "duration": 0.45},
    "直线向下擦除": {"xfade": "wipedown", "duration": 0.45},
    "圆形打开": {"xfade": "circleopen", "duration": 0.50},
    "圆形关闭": {"xfade": "circleclose", "duration": 0.50},
    "水平打开": {"xfade": "horzopen", "duration": 0.45},
    "垂直打开": {"xfade": "vertopen", "duration": 0.45},
    "像素化": {"xfade": "pixelize", "duration": 0.50},
    "径向模糊": {"xfade": "radial", "duration": 0.50},
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


def speech_trim_bounds(srt, duration, head_padding_ms=80, tail_padding_ms=120):
    spans = _speech_spans(srt)
    duration = max(0.05, float(duration or 0.05))
    if not spans:
        return 0.0, duration, False
    start = max(0.0, spans[0][0] - max(0, head_padding_ms) / 1000.0)
    end = min(duration, spans[-1][1] + max(0, tail_padding_ms) / 1000.0)
    return start, max(start + 0.05, end), True


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
            subset_text = "".join(entry[2] for entry in entries[i:j+1])
            clean_subset = _plain_text(subset_text)
            score = SequenceMatcher(None, clean_subset, clean_target).ratio()
            if score > best_score:
                best_score = score
                best_range = (i, j)
                
    if best_score > 0.3:
        i, j = best_range
        start = max(0.0, entries[i][0] - max(0, head_padding_ms) / 1000.0)
        end = min(duration, entries[j][1] + max(0, tail_padding_ms) / 1000.0)
        return start, max(start + 0.05, end), True
        
    return speech_trim_bounds(srt, duration, head_padding_ms, tail_padding_ms)


def hybrid_trim_bounds(srt, duration, audio_bounds, head_padding_ms=80, tail_padding_ms=120,
                       word_guard_ms=40):
    """Combine transcript and audio boundaries without ever cutting into a timed word.

    Audio detection is only allowed to refine the leading/trailing edge.  Internal
    pauses remain untouched, which avoids the unnatural jump cuts produced by a
    global silence remover.
    """
    duration = max(0.05, float(duration or 0.05))
    spans = _speech_spans(srt)
    text_start, text_end, text_detected = speech_trim_bounds(
        srt, duration, head_padding_ms, tail_padding_ms,
    )
    if not text_detected:
        if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
            return float(audio_bounds[0]), float(audio_bounds[1]), True
        return 0.0, duration, False
    if not audio_bounds or len(audio_bounds) < 3 or not bool(audio_bounds[2]):
        return text_start, text_end, True
    audio_start, audio_end, _detected = audio_bounds[0], audio_bounds[1], audio_bounds[2]
    guard = max(0, int(word_guard_ms)) / 1000.0
    # Never move the start past the first timed word (minus a small consonant guard),
    # nor the end before the last timed word (plus the same guard).
    latest_safe_start = max(0.0, spans[0][0] - guard)
    earliest_safe_end = min(duration, spans[-1][1] + guard)
    start = min(latest_safe_start, max(text_start, float(audio_start)))
    end = max(earliest_safe_end, min(text_end, float(audio_end)))
    if end <= start + 0.05:
        return text_start, text_end, True
    return max(0.0, start), min(duration, end), True


def refine_text_window_with_audio(text_start, text_end, text_ok, audio_bounds, duration,
                                  edge_slack_ms=100):
    """Tighten an already-chosen text window with leading/trailing silence bounds.

    Used when the text window comes from script-segment matching (not the full SRT span),
    so hybrid_trim_bounds' full-timeline word guards would be wrong.

    Audio may only nibble the outer padding (about edge_slack_ms); it must not carve
    into the middle of the matched phrase.
    """
    duration = max(0.05, float(duration or 0.05))
    if not text_ok:
        if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
            return float(audio_bounds[0]), float(audio_bounds[1]), True
        return 0.0, duration, False
    text_start = max(0.0, float(text_start))
    text_end = max(text_start + 0.05, min(duration, float(text_end)))
    if not audio_bounds or len(audio_bounds) < 3 or not bool(audio_bounds[2]):
        return text_start, text_end, True
    audio_start, audio_end = float(audio_bounds[0]), float(audio_bounds[1])
    slack = max(0, int(edge_slack_ms)) / 1000.0
    # Same structure as hybrid_trim_bounds: audio can pull edges inward, but only within slack.
    latest_safe_start = min(duration, text_start + slack)
    earliest_safe_end = max(0.0, text_end - slack)
    start = min(latest_safe_start, max(text_start, audio_start))
    end = max(earliest_safe_end, min(text_end, audio_end))
    if end <= start + 0.05:
        return text_start, text_end, True
    return max(0.0, start), min(duration, end), True


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

    def _run(self, command):
        if self.cancelled:
            raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **hidden_kwargs(),
        )
        with self._lock:
            self._active_processes.add(process)
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
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
            raise RuntimeError(stderr[-1200:].strip() or "FFmpeg 处理失败")
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
        saved = cache.get(key, {})
        if (self.settings.get("resume", True) and saved.get("signature") == signature
                and str(saved.get("srt") or "").strip()):
            self.log.emit(f"续接：复用语音边界 {clip.name}")
            return saved
        self.log.emit(f"正在识别说话边界：{clip.name}（此阶段可能需要一些时间）")
        original, _translated, srt = self.transcribe(str(clip))
        if not str(srt or "").strip():
            raise RuntimeError("没有识别到带时间轴的有效文案")
        info = {**saved, "signature": signature, "original": str(original or ""), "srt": str(srt or "")}
        cache[key] = info
        self.log.emit(f"说话边界识别完成：{clip.name}")
        return info

    def _fast_analysis(self, clip, cache):
        """Find leading/trailing quiet sections locally, without ASR or subtitle matching."""
        signature = self._signature(clip)
        key = str(Path(clip).resolve())
        saved = cache.get(key, {})
        threshold = int(self.settings.get("silence_threshold_db", -35))
        minimum = max(0.06, float(self.settings.get("silence_min_ms", 180)) / 1000.0)
        params = {"threshold": threshold, "minimum": round(minimum, 3),
                  "head": int(self.settings.get("head_padding_ms", 80)),
                  "tail": int(self.settings.get("tail_padding_ms", 120))}
        if (self.settings.get("resume", True) and saved.get("signature") == signature
                and saved.get("fast_bounds_version") == 2 and saved.get("fast_params") == params
                and saved.get("bounds")):
            self.log.emit(f"续接：复用本地声音边界 {clip.name}")
            return saved
        probe = self._probe(clip)
        duration = max(0.05, probe["duration"])
        if not probe["audio"]:
            info = {**saved, "signature": signature, "fast_bounds_version": 2,
                    "fast_params": params, "duration": duration, "bounds": [0.0, duration, False]}
            cache[key] = info
            return info
        self.log.emit(f"快速检测首尾声音：{clip.name}（本地处理，不识别字幕）")
        result = self._run([
            self.ffmpeg, "-hide_banner", "-nostats", "-i", str(clip),
            "-map", "0:a:0", "-af",
            f"silencedetect=noise={threshold}dB:d={minimum:.3f}", "-f", "null", "-",
        ])
        events = []
        for kind, value in re.findall(r"silence_(start|end):\s*([0-9.]+)", result.stderr or ""):
            events.append((kind, float(value)))
        start = 0.0
        end = duration
        detected = False
        if events and events[0][0] == "start" and events[0][1] <= 0.08:
            first_end = next((value for kind, value in events if kind == "end"), None)
            if first_end is not None:
                start = min(duration, first_end)
                detected = True
        trailing_start = None
        for index, (kind, value) in enumerate(events):
            if kind == "start" and not any(next_kind == "end" for next_kind, _ in events[index + 1:]):
                trailing_start = value
        if trailing_start is not None and trailing_start < duration:
            end = trailing_start
            detected = True
        if detected:
            start = max(0.0, start - max(0, self.settings.get("head_padding_ms", 80)) / 1000.0)
            end = min(duration, end + max(0, self.settings.get("tail_padding_ms", 120)) / 1000.0)
        if end <= start + 0.05:
            start, end, detected = 0.0, duration, False
        info = {**saved, "signature": signature, "fast_bounds_version": 2,
                "fast_params": params, "duration": duration, "bounds": [start, end, detected]}
        cache[key] = info
        return info

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
        head_ms = self.settings.get("head_padding_ms", 80)
        tail_ms = self.settings.get("tail_padding_ms", 120)
        srt = str(analysis.get("srt") or "")
        media_duration = probe["duration"]

        if manual_bounds is not None:
            start = max(0.0, min(media_duration, manual_bounds[0]))
            end = max(start + 0.05, min(media_duration, manual_bounds[1]))
            detected = True
            self.log.emit(f"切片功能：{clip.name} 已应用手动切片区间 {start:.2f}s - {end:.2f}s")
        elif trim_mode == "none":
            start, end, detected = 0.0, media_duration, True
            self.log.emit(f"不裁剪：{clip.name} 保留完整片段。")
        else:
            # Text window: prefer user-segment match when a clip_script is available,
            # otherwise first/last spoken word from the full transcript.
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

            audio_bounds = analysis.get("bounds")
            hybrid_bounds = analysis.get("hybrid_bounds")

            if trim_mode == "fast":
                # 快速声音边界：以本地静音检测为准；没有 bounds 时再退回文案时间轴。
                if audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
                    start, end, detected = float(audio_bounds[0]), float(audio_bounds[1]), True
                elif text_ok:
                    start, end, detected = text_start, text_end, True
                    self.log.emit(f"提醒：{clip.name} 未得到静音边界，已改用文案时间轴裁剪。")
                else:
                    start, end, detected = 0.0, media_duration, False
            elif trim_mode == "text":
                # 仅按文案边界：字幕/分段匹配时间轴；识别失败时再退回声音边界。
                if text_ok:
                    start, end, detected = text_start, text_end, True
                elif audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
                    start, end, detected = float(audio_bounds[0]), float(audio_bounds[1]), True
                    self.log.emit(f"提醒：{clip.name} 文案边界不可用，已改用本地声音边界。")
                else:
                    start, end, detected = 0.0, media_duration, False
            else:
                # 智能混合边界：文案窗口 + 首尾声音修正。
                # 有分段文案时，按该段匹配窗口再与声音混合，避免被“整段 ASR”hybrid 覆盖。
                if clip_script and text_ok:
                    start, end, detected = refine_text_window_with_audio(
                        text_start, text_end, text_ok, audio_bounds, media_duration,
                    )
                elif hybrid_bounds and len(hybrid_bounds) >= 3:
                    start, end, detected = (
                        float(hybrid_bounds[0]), float(hybrid_bounds[1]), bool(hybrid_bounds[2]),
                    )
                elif text_ok:
                    start, end, detected = refine_text_window_with_audio(
                        text_start, text_end, text_ok, audio_bounds, media_duration,
                    )
                elif audio_bounds and len(audio_bounds) >= 3 and bool(audio_bounds[2]):
                    start, end, detected = float(audio_bounds[0]), float(audio_bounds[1]), True
                else:
                    start, end, detected = 0.0, media_duration, False
        if not detected:
            self.log.emit(f"提醒：{clip.name} 未识别到说话时间，保留完整片段。")
        else:
            self.log.emit(f"去口气音：{clip.name} 保留 {start:.2f}s - {end:.2f}s")
        duration = max(0.05, end - start)
        removed = max(0.0, probe["duration"] - duration)
        ratio = (removed / probe["duration"] * 100.0) if probe["duration"] > 0 else 0.0
        self.log.emit(
            f"时长：{clip.name} 原始 {probe['duration']:.2f}s → 保留 {duration:.2f}s，删减 {removed:.2f}s（{ratio:.1f}%）"
        )
        if ratio > 40:
            self.log.emit(f"提醒：{clip.name} 删减超过 40%，请检查文案时间轴或适当调低静音阈值。")
        watermark = Path(watermark) if watermark and Path(watermark).is_file() else None
        fingerprint = hashlib.sha256(json.dumps({
            "source": self._signature(clip), "start": round(start, 3), "end": round(end, 3),
            "width": target_w, "height": target_h,
            "watermark": self._signature(watermark) if watermark else None,
            "clean_metadata": bool(self.settings.get("clean_metadata", True)), "version": 5,
        }, sort_keys=True).encode("utf-8")).hexdigest()[:14]
        destination = cache_dir / f"segment_{index + 1:03d}_{fingerprint}.mp4"
        if self.settings.get("resume", True) and destination.exists() and destination.stat().st_size > 1024:
            self.log.emit(f"续接：复用已处理片段 {clip.name}")
            return destination
        self.log.emit(f"正在裁剪口气音并统一音视频参数：{clip.name}")
        fade_out = max(0.0, duration - 0.018)
        # Flow 等服务输出的竖屏素材宽高比常有少量偏差。缩小后 pad 会在
        # 成品周围留下黑边；改为等比放大铺满并居中裁剪，不拉伸画面。
        video_filter = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}:(iw-ow)/2:(ih-oh)/2,setsar=1,fps=30,format=yuv420p"
        )
        command = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(clip), "-ss", f"{start:.3f}",
        ]
        if watermark:
            command += ["-loop", "1", "-i", str(watermark)]
        command += ["-t", f"{duration:.3f}"]
        if watermark:
            command += [
                "-filter_complex",
                f"[0:v]{video_filter}[base];[1:v]scale={target_w}:{target_h},format=rgba[wm];"
                "[base][wm]overlay=0:0:eof_action=repeat,format=yuv420p[outv]",
                "-map", "[outv]",
            ]
        else:
            command += ["-map", "0:v:0", "-vf", video_filter]
        if probe["audio"]:
            command += [
                "-map", "0:a:0", "-af",
                f"aresample=48000,aformat=channel_layouts=stereo,afade=t=in:st=0:d=0.018,afade=t=out:st={fade_out:.3f}:d=0.018",
            ]
        if self.settings.get("clean_metadata", True):
            command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                        "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                        "-map_chapters", "-1"]
        command += ["-sn", "-dn"]
        command += encoder_args(self.encoder, self.settings.get("encode_preset", "veryfast"))
        if probe["audio"]:
            command += ["-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000"]
        else:
            command += ["-an"]
        command += ["-movflags", "+faststart", str(destination)]
        self._run(command)
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
                for clip in clips:
                    if self.cancelled:
                        raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
                    # 裁剪模式需要的分析数据：
                    # - none: 不需要（但文案排序仍要 ASR）
                    # - text/hybrid: 需要 ASR 时间轴
                    # - fast: 需要本地静音边界
                    # - 文案排序: 无论裁剪模式都要 ASR（用于 match_clips_to_script）
                    need_asr = script_mode or trim_mode in ("hybrid", "text")
                    need_fast = trim_mode in ("hybrid", "fast")
                    if trim_mode == "none" and not script_mode:
                        analyses[str(clip.resolve())] = {}
                    elif need_asr:
                        try:
                            analysis = self._analysis(clip, analysis_cache)
                            if need_fast:
                                analysis = self._fast_analysis(clip, analysis_cache)
                            if trim_mode == "hybrid":
                                media_duration = float(analysis.get("duration") or self._probe(clip)["duration"])
                                analysis["hybrid_bounds"] = list(hybrid_trim_bounds(
                                    analysis.get("srt", ""), media_duration, analysis.get("bounds"),
                                    self.settings.get("head_padding_ms", 80),
                                    self.settings.get("tail_padding_ms", 120),
                                ))
                                analysis_cache[str(clip.resolve())] = analysis
                                self.log.emit(f"智能混合边界：文案时间轴 + 首尾声音检测已完成 {clip.name}")
                            elif trim_mode == "fast":
                                self.log.emit(f"快速声音边界：已完成本地首尾检测 {clip.name}")
                            elif trim_mode == "none" and script_mode:
                                self.log.emit(f"文案识别完成（不裁剪，仅用于按分段文案排序）：{clip.name}")
                            else:
                                self.log.emit(f"智能文案边界：已按首词/末词时间定位 {clip.name}")
                            analyses[str(clip.resolve())] = analysis
                        except Exception as exc:
                            if script_mode:
                                raise
                            self.log.emit(
                                f"智能文案边界识别失败，自动改用本地声音边界继续处理：{clip.name}（{exc}）"
                            )
                            analyses[str(clip.resolve())] = self._fast_analysis(clip, analysis_cache)
                    else:
                        # 纯快速声音边界（文件名排序）：不调用 ASR
                        analyses[str(clip.resolve())] = self._fast_analysis(clip, analysis_cache)
                    cache_file.write_text(json.dumps(analysis_cache, ensure_ascii=False, indent=2), encoding="utf-8")
                    completed_steps += 1
                    self.progress.emit(round(completed_steps / total_steps * 100))
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
                from concurrent.futures import ThreadPoolExecutor
                import os
                max_workers = min(4, os.cpu_count() or 4)
                self.log.emit(f"正在启动多线程并行编码加速（最大并行线程数：{max_workers}）...")
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
                    for future in futures:
                        i = futures[future]
                        normalized[i] = future.result()
                        completed_steps += 1
                        self.progress.emit(round(completed_steps / total_steps * 100))
                if any(not self._probe(path)["audio"] for path in normalized):
                    raise RuntimeError(f"{folder.name} 中存在没有音轨的片段，无法保证无缝合并声音。")
                concat_file = cache_dir / "concat.txt"
                concat_file.write_text("\n".join(
                    "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'" for path in normalized
                ), encoding="utf-8")
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
                        preset_dur = float((transition_cfg or {}).get("duration") or 0.5)
                        transition_duration = user_dur if user_dur >= 0.10 else preset_dur
                        transition_duration = max(0.10, min(2.50, transition_duration))
                        segment_infos = [self._probe(path) for path in normalized]
                        min_segment_dur = min(info["duration"] for info in segment_infos)
                        # 转场不得超过最短片段的 45%，避免过短素材 xfade 失败
                        actual_transition_duration = min(transition_duration, max(0.12, min_segment_dur * 0.45))
                        self.log.emit(
                            f"应用合并转场「{transition_name}」→ xfade={transition_key}，"
                            f"时长 {actual_transition_duration:.2f}s（设定 {transition_duration:.2f}s），共 {len(normalized)} 段。"
                        )
                        
                        concat_command = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"
                        ]
                        for path in normalized:
                            concat_command += ["-i", str(path)]
                            
                        # Build filter complex
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
                                f"{v_in}{next_v}xfade=transition={transition_key}:duration={actual_transition_duration}:offset={current_offset:.3f}{out_v}"
                            )
                            filter_parts.append(
                                f"{a_in}{next_a}acrossfade=d={actual_transition_duration}:c1=tri:c2=tri{out_a}"
                            )
                            
                            v_in = out_v
                            a_in = out_a
                            current_offset = current_offset + segment_infos[i]["duration"] - actual_transition_duration
                            
                        filter_complex_str = ";".join(filter_parts)
                        concat_command += [
                            "-filter_complex", filter_complex_str,
                            "-map", v_in,
                            "-map", a_in
                        ]
                        concat_command += encoder_args(self.encoder, self.settings.get("encode_preset", "veryfast"))
                        concat_command += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
                        if self.settings.get("clean_metadata", True):
                            concat_command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                               "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                               "-map_chapters", "-1"]
                        concat_command += ["-movflags", "+faststart", str(destination)]
                    else:
                        if transition_name and transition_name != "无转场" and len(normalized) <= 1:
                            self.log.emit(f"本组仅 1 个片段，跳过转场「{transition_name}」。")
                        concat_command = [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(concat_file), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                        ]
                        if self.settings.get("clean_metadata", True):
                            concat_command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                               "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                               "-map_chapters", "-1"]
                        concat_command += ["-movflags", "+faststart", str(destination)]
                        
                    destination = self._write_final_output(concat_command, destination)
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
