from __future__ import annotations

import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .path_picker import VIDEO_EXTENSIONS, collect_files, natural_key
from .settings_page import hidden_kwargs
from .video_encoding import ENCODER_LABELS, encoder_args, resolve_encoder


def discover_groups(parent):
    """Return one video group per direct child folder, in natural-name order."""
    root = Path(parent)
    if not root.is_dir():
        return []
    groups = []
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: natural_key(p.name)):
        clips = collect_files([str(folder)], VIDEO_EXTENSIONS)
        if clips:
            groups.append((folder, [Path(p) for p in clips]))
    if not groups:
        clips = collect_files([str(root)], VIDEO_EXTENSIONS)
        if clips:
            groups.append((root, [Path(p) for p in clips]))
    return groups


def split_group_script(text):
    value = str(text or "").strip()
    if not value:
        return []
    value = re.sub(r"(?m)^\s*---+\s*$", "\n\n", value)
    blocks = re.split(r"\r?\n\s*\r?\n", value)
    return [re.sub(r"\s+", " ", block).strip() for block in blocks if block.strip()]


def _plain_text(value):
    return re.sub(r"[^0-9a-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff\u3400-\u9fff]+", "", str(value).casefold())


def match_clips_to_script(clips, transcripts, script_text, minimum_score=0.22):
    """Greedily make a one-to-one match and return clips in script-segment order."""
    segments = split_group_script(script_text)
    clips = list(clips)
    if len(segments) != len(clips) or not clips:
        return None, "分段文案数量与视频片段数量不一致"
    candidates = []
    for clip_index, clip in enumerate(clips):
        source = _plain_text(transcripts.get(str(Path(clip).resolve()), ""))
        for segment_index, segment in enumerate(segments):
            score = SequenceMatcher(None, source, _plain_text(segment)).ratio() if source else 0.0
            candidates.append((score, clip_index, segment_index))
    assigned_clips = set(); assigned_segments = set(); mapping = {}
    for score, clip_index, segment_index in sorted(candidates, reverse=True):
        if clip_index in assigned_clips or segment_index in assigned_segments:
            continue
        assigned_clips.add(clip_index); assigned_segments.add(segment_index)
        mapping[segment_index] = (clips[clip_index], score)
    if len(mapping) != len(clips) or min(score for _clip, score in mapping.values()) < minimum_score:
        return None, "文案匹配可信度不足"
    return [mapping[index][0] for index in range(len(segments))], "已按分段文案自动匹配排序"


def speech_trim_bounds(srt, duration, head_padding_ms=80, tail_padding_ms=120):
    timing = re.compile(
        r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
    )
    spans = []
    for match in timing.finditer(str(srt or "")):
        values = [int(value) for value in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / (10 ** len(match.group(4)))
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / (10 ** len(match.group(8)))
        spans.append((start, end))
    duration = max(0.05, float(duration or 0.05))
    if not spans:
        return 0.0, duration, False
    start = max(0.0, spans[0][0] - max(0, head_padding_ms) / 1000.0)
    end = min(duration, spans[-1][1] + max(0, tail_padding_ms) / 1000.0)
    return start, max(start + 0.05, end), True


def _safe_name(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value)).strip(" .")
    return cleaned or "合成视频"


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
        self.encoder = resolve_encoder(self.ffmpeg, self.settings.get("encoder_backend", "auto"))

    def cancel(self):
        self.cancelled = True

    @property
    def ffprobe(self):
        candidate = Path(self.ffmpeg).with_name("ffprobe" + Path(self.ffmpeg).suffix)
        return str(candidate if candidate.exists() else "ffprobe")

    def _run(self, command):
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **hidden_kwargs(),
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:].strip() or "FFmpeg 处理失败")
        return result

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
        if self.settings.get("resume", True) and saved.get("signature") == signature and saved.get("srt") is not None:
            self.log.emit(f"续接：复用语音边界 {clip.name}")
            return saved
        self.log.emit(f"正在识别说话边界：{clip.name}（此阶段可能需要一些时间）")
        original, _translated, srt = self.transcribe(str(clip))
        info = {"signature": signature, "original": str(original or ""), "srt": str(srt or "")}
        cache[key] = info
        self.log.emit(f"说话边界识别完成：{clip.name}")
        return info

    def _normalize(self, clip, index, cache_dir, analysis, target_w, target_h):
        probe = self._probe(clip)
        start, end, detected = speech_trim_bounds(
            analysis.get("srt", ""), probe["duration"],
            self.settings.get("head_padding_ms", 80), self.settings.get("tail_padding_ms", 120),
        )
        if not detected:
            self.log.emit(f"提醒：{clip.name} 未识别到说话时间，保留完整片段。")
        else:
            self.log.emit(f"去口气音：{clip.name} 保留 {start:.2f}s - {end:.2f}s")
        duration = max(0.05, end - start)
        fingerprint = hashlib.sha256(json.dumps({
            "source": self._signature(clip), "start": round(start, 3), "end": round(end, 3),
            "width": target_w, "height": target_h, "version": 1,
        }, sort_keys=True).encode("utf-8")).hexdigest()[:14]
        destination = cache_dir / f"segment_{index + 1:03d}_{fingerprint}.mp4"
        if self.settings.get("resume", True) and destination.exists() and destination.stat().st_size > 1024:
            self.log.emit(f"续接：复用已处理片段 {clip.name}")
            return destination
        self.log.emit(f"正在裁剪口气音并统一音视频参数：{clip.name}")
        fade_out = max(0.0, duration - 0.018)
        video_filter = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p"
        )
        command = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}",
            "-i", str(clip), "-t", f"{duration:.3f}", "-map", "0:v:0",
        ]
        if probe["audio"]:
            command += [
                "-map", "0:a:0", "-af",
                f"aresample=48000,aformat=channel_layouts=stereo,afade=t=in:st=0:d=0.018,afade=t=out:st={fade_out:.3f}:d=0.018",
            ]
        command += [
            "-vf", video_filter, "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
        ]
        command += encoder_args(self.encoder, self.settings.get("encode_preset", "veryfast"))
        if probe["audio"]:
            command += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
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
                for clip in clips:
                    if self.cancelled:
                        raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
                    analyses[str(clip.resolve())] = self._analysis(clip, analysis_cache)
                    cache_file.write_text(json.dumps(analysis_cache, ensure_ascii=False, indent=2), encoding="utf-8")
                    completed_steps += 1
                    self.progress.emit(round(completed_steps / total_steps * 100))
                if self.settings.get("sort_mode") == "script":
                    ordered, reason = match_clips_to_script(
                        clips,
                        {key: value.get("original", "") for key, value in analyses.items()},
                        self.settings.get("scripts", {}).get(str(folder.resolve()), ""),
                    )
                    if ordered:
                        clips = ordered
                        self.log.emit(reason)
                    else:
                        self.log.emit(f"提醒：{reason}，本组自动回退为文件名自然排序。")
                first_probe = self._probe(clips[0])
                target_w, target_h = ((1920, 1080) if first_probe["width"] > first_probe["height"] else (1080, 1920))
                normalized = []
                for clip_index, clip in enumerate(clips):
                    normalized.append(self._normalize(
                        clip, clip_index, cache_dir, analyses[str(clip.resolve())], target_w, target_h,
                    ))
                    completed_steps += 1
                    self.progress.emit(round(completed_steps / total_steps * 100))
                if any(not self._probe(path)["audio"] for path in normalized):
                    raise RuntimeError(f"{folder.name} 中存在没有音轨的片段，无法保证无缝合并声音。")
                concat_file = cache_dir / "concat.txt"
                concat_file.write_text("\n".join(
                    "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'" for path in normalized
                ), encoding="utf-8")
                destination = self.output / f"{_safe_name(folder.name)}_去口气音合成.mp4"
                final_fingerprint = hashlib.sha256(json.dumps({
                    "files": [self._signature(path) for path in normalized], "version": 1,
                }, sort_keys=True).encode("utf-8")).hexdigest()
                state_file = cache_dir / "final.json"
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
                except Exception:
                    state = {}
                if not (self.settings.get("resume", True) and destination.exists() and destination.stat().st_size > 1024
                        and state.get("fingerprint") == final_fingerprint):
                    self.log.emit(f"正在合并文件夹“{folder.name}”的 {len(normalized)} 个片段，请等待…")
                    self._run([
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_file), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                        "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", str(destination),
                    ])
                    state_file.write_text(json.dumps({"fingerprint": final_fingerprint}, indent=2), encoding="utf-8")
                else:
                    self.log.emit(f"续接：复用已完成合成视频 {destination.name}")
                outputs.append(str(destination))
                completed_steps += 1
                self.progress.emit(round(completed_steps / total_steps * 100))
                self.item_done.emit(str(destination), folder.name, group_index, len(self.groups))
                self.log.emit(f"[{group_index}/{len(self.groups)}] 合成完成：{destination}")
            self.finished.emit(True, json.dumps({"outputs": outputs}, ensure_ascii=False))
        except Exception as exc:
            self.finished.emit(False, str(exc))
