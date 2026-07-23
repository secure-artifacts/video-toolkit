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
        return tuple(audio_bounds) if audio_bounds else (0.0, duration, False)
    if not audio_bounds or not bool(audio_bounds[2]):
        return text_start, text_end, True
    audio_start, audio_end, _detected = audio_bounds
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

    def _normalize(self, clip, index, cache_dir, analysis, target_w, target_h, watermark=None):
        probe = self._probe(clip)
        if analysis.get("hybrid_bounds"):
            start, end, detected = analysis["hybrid_bounds"]
        elif analysis.get("bounds"):
            start, end, detected = analysis["bounds"]
        else:
            start, end, detected = speech_trim_bounds(
                analysis.get("srt", ""), probe["duration"],
                self.settings.get("head_padding_ms", 80), self.settings.get("tail_padding_ms", 120),
            )
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
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}",
            "-i", str(clip),
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
                script_mode = self.settings.get("sort_mode") == "script"
                trim_mode = self.settings.get("trim_mode", "hybrid")
                for clip in clips:
                    if self.cancelled:
                        raise RuntimeError("分组合成已停止；已经处理的片段会保留，下一次可断点续接。")
                    if script_mode or trim_mode in ("hybrid", "text"):
                        try:
                            analysis = self._analysis(clip, analysis_cache)
                            if trim_mode == "hybrid":
                                analysis = self._fast_analysis(clip, analysis_cache)
                                media_duration = float(analysis.get("duration") or self._probe(clip)["duration"])
                                analysis["hybrid_bounds"] = list(hybrid_trim_bounds(
                                    analysis.get("srt", ""), media_duration, analysis.get("bounds"),
                                    self.settings.get("head_padding_ms", 80),
                                    self.settings.get("tail_padding_ms", 120),
                                ))
                                analysis_cache[str(clip.resolve())] = analysis
                                self.log.emit(f"智能混合边界：文案时间轴 + 首尾声音检测已完成 {clip.name}")
                            elif not script_mode:
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
                        analyses[str(clip.resolve())] = self._fast_analysis(clip, analysis_cache)
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
                    clip, clip_index = args
                    return self._normalize(
                        clip, clip_index, cache_dir, analyses[str(clip.resolve())], target_w, target_h, watermark
                    )
                tasks = [(clip, clip_index) for clip_index, clip in enumerate(clips)]
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
                final_fingerprint = hashlib.sha256(json.dumps({
                    "files": [self._signature(path) for path in normalized],
                    "clean_metadata": bool(self.settings.get("clean_metadata", True)), "version": 2,
                }, sort_keys=True).encode("utf-8")).hexdigest()
                state_file = cache_dir / "final.json"
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
                except Exception:
                    state = {}
                if not (self.settings.get("resume", True) and destination.exists() and destination.stat().st_size > 1024
                        and state.get("fingerprint") == final_fingerprint):
                    self.log.emit(f"正在合并文件夹“{folder.name}”的 {len(normalized)} 个片段，请等待…")
                    concat_command = [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_file), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                    ]
                    if self.settings.get("clean_metadata", True):
                        concat_command += ["-map_metadata", "-1", "-map_metadata:s", "-1",
                                           "-map_metadata:p", "-1", "-map_metadata:c", "-1",
                                           "-map_chapters", "-1"]
                    concat_command += ["-movflags", "+faststart", str(destination)]
                    self._run(concat_command)
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
