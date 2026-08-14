from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path

from PIL import ExifTags, Image
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .path_picker import (AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
                          DropListWidget, collect_files, default_output_path)
from .settings_page import find_media_tool, hidden_kwargs
from .video_encoding import encoder_args, resolve_encoder

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
_META_STRIP = [
    "-map_metadata", "-1", "-map_metadata:s", "-1", "-map_metadata:p", "-1",
    "-map_metadata:c", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
    "-metadata", "creation_time=", "-metadata", "date=", "-metadata", "location=",
    "-metadata", "title=", "-metadata", "artist=", "-metadata", "author=",
    "-metadata", "copyright=", "-metadata", "comment=", "-metadata", "description=",
    "-metadata", "encoder=",
]
# 9:16 竖屏；表达式保证偶数宽高（yuv420p 兼容）
_CROP_916_VF = (
    "crop="
    "trunc(min(iw\\,ih*9/16)/2)*2:"
    "trunc(min(ih\\,iw*16/9)/2)*2:"
    "(iw-ow)/2:(ih-oh)/2"
)
_CROP_916_MODES = {
    "keep": None,  # 仅居中裁切，不缩放
    "1080x1920": (1080, 1920),
    "720x1280": (720, 1280),
    "1440x2560": (1440, 2560),
}


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复的输出文件名：{path.name}")


def _prepare_logo_rgba(logo_path: Path, opacity: float = 1.0) -> Image.Image:
    """Load logo as RGBA and apply opacity; soft-knockout near-black/white solid backgrounds."""
    with Image.open(logo_path) as im:
        logo = im.convert("RGBA")
    pixels = logo.load()
    w, h = logo.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < 8:
                continue
            if max(r, g, b) <= 18 or min(r, g, b) >= 248:
                if abs(r - g) < 12 and abs(g - b) < 12:
                    pixels[x, y] = (r, g, b, 0)
    if opacity < 0.999:
        r, g, b, a = logo.split()
        a = a.point(lambda v: int(v * max(0.0, min(1.0, opacity))))
        logo = Image.merge("RGBA", (r, g, b, a))
    return logo


def _corner_xy(position: str, base_w: int, base_h: int, mark_w: int, mark_h: int, margin: int):
    m = max(0, int(margin))
    mapping = {
        "左上": (m, m),
        "顶部居中": ((base_w - mark_w) // 2, m),
        "右上": (base_w - mark_w - m, m),
        "居中": ((base_w - mark_w) // 2, (base_h - mark_h) // 2),
        "左下": (m, base_h - mark_h - m),
        "底部居中": ((base_w - mark_w) // 2, base_h - mark_h - m),
        "右下": (base_w - mark_w - m, base_h - mark_h - m),
    }
    return mapping.get(position, mapping["右下"])


def _overlay_logo_on_image(base: Image.Image, logo_path: Path, cfg: dict) -> Image.Image:
    canvas = base.convert("RGBA")
    opacity = max(0.05, min(1.0, float(cfg.get("opacity", 100)) / 100.0))
    logo = _prepare_logo_rgba(logo_path, opacity)
    mode = str(cfg.get("mode") or "小 Logo 角标")
    if "全屏" in mode:
        logo = logo.resize(canvas.size, Image.Resampling.LANCZOS)
        x, y = 0, 0
    else:
        width_pct = max(4.0, min(80.0, float(cfg.get("width_pct", 18))))
        target_w = max(16, int(canvas.width * width_pct / 100.0))
        scale = target_w / max(1, logo.width)
        target_h = max(16, int(logo.height * scale))
        logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
        x, y = _corner_xy(
            str(cfg.get("position") or "右下"),
            canvas.width, canvas.height, logo.width, logo.height,
            int(cfg.get("margin", 28) or 28),
        )
    canvas.alpha_composite(logo, (max(0, x), max(0, y)))
    return canvas


def crop_image_to_916(image: Image.Image, target_size=None) -> Image.Image:
    """Center-crop to 9:16 without stretching. Optional high-quality resize after crop."""
    w, h = image.size
    if w < 2 or h < 2:
        return image
    target_ratio = 9.0 / 16.0
    current = w / float(h)
    if abs(current - target_ratio) > 0.004:
        if current > target_ratio:
            new_w = max(2, int(round(h * target_ratio)))
            left = max(0, (w - new_w) // 2)
            image = image.crop((left, 0, min(w, left + new_w), h))
        else:
            new_h = max(2, int(round(w / target_ratio)))
            top = max(0, (h - new_h) // 2)
            image = image.crop((0, top, w, min(h, top + new_h)))
    if target_size and len(target_size) == 2:
        tw, th = int(target_size[0]), int(target_size[1])
        if tw > 0 and th > 0 and (image.width != tw or image.height != th):
            image = image.resize((tw, th), Image.Resampling.LANCZOS)
    return image


def _probe_video_meta(ffmpeg, path: Path):
    """Return width, height, fps, video_bit_rate (bps, 0 if unknown)."""
    ffprobe = find_media_tool("ffprobe")
    if not ffprobe:
        return 0, 0, 0.0, 0
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,bit_rate",
        "-show_entries", "format=bit_rate",
        "-of", "json", str(path),
    ]
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
    if result.returncode:
        return 0, 0, 0.0, 0
    try:
        payload = json.loads(result.stdout or "{}")
        stream = (payload.get("streams") or [{}])[0]
        fmt = payload.get("format") or {}
        w = int(stream.get("width") or 0)
        h = int(stream.get("height") or 0)
        rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
        fps = 0.0
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den) if float(den) else 1.0
            fps = float(num) / den_f if den_f else 0.0
        else:
            fps = float(rate or 0)
        br = 0
        try:
            br = int(stream.get("bit_rate") or 0)
        except (TypeError, ValueError):
            br = 0
        if br <= 0:
            try:
                br = int(fmt.get("bit_rate") or 0)
            except (TypeError, ValueError):
                br = 0
        return w, h, fps, max(0, br)
    except Exception:
        return 0, 0, 0.0, 0


def _probe_video_size(ffmpeg, path: Path):
    w, h, fps, _br = _probe_video_meta(ffmpeg, path)
    return w, h, fps


def _bitrate_floor_for_size(width: int, height: int) -> int:
    """Minimum video bitrate (bps) for clean 9:16 delivery at given pixels."""
    pixels = max(1, int(width) * int(height))
    # ~0.12 bit/pixel/frame @ 30fps ≈ 3.6 bpp-ish overall; clamp to sensible range
    # 1080x1920 → ~8 Mbps floor; 720x1280 → ~4.5; tiny 270x480 → ~1.2
    floor = int(pixels * 30 * 0.12)
    return max(1_200_000, min(16_000_000, floor))


def _hq_video_encode_args(ffmpeg, width: int = 0, height: int = 0, source_bitrate: int = 0) -> list:
    """成品级 H.264：优先画质，不用 intermediate/预览档。

    - 不用 encoder_args 的 medium→faster 改写（那是中间缓存用的）
    - 硬编给更高 CQ/质量；CPU 用 slow + 低 CRF
    - 按分辨率设码率下限，避免小分辨率被压糊、大分辨率码率不够
    """
    encoder = resolve_encoder(ffmpeg, "auto")
    w = max(0, int(width or 0))
    h = max(0, int(height or 0))
    floor = _bitrate_floor_for_size(w or 1080, h or 1920)
    # 源码率更高时尽量贴近源，减少二次压缩损失
    target_br = max(floor, int(source_bitrate * 0.95) if source_bitrate > 500_000 else floor)
    maxrate = int(target_br * 1.5)
    bufsize = int(target_br * 2)

    if encoder == "nvenc":
        return [
            "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", "15", "-b:v", str(target_br),
            "-maxrate", str(maxrate), "-bufsize", str(bufsize),
            "-profile:v", "high", "-bf", "0", "-pix_fmt", "yuv420p",
        ]
    if encoder == "qsv":
        return [
            "-c:v", "h264_qsv", "-preset", "slow", "-global_quality", "16",
            "-look_ahead", "1", "-b:v", str(target_br),
            "-maxrate", str(maxrate), "-bufsize", str(bufsize),
            "-bf", "0", "-pix_fmt", "nv12",
        ]
    if encoder == "mf":
        # Windows MF：质量档尽量拉满，并给码率下限
        return [
            "-c:v", "h264_mf", "-rate_control", "quality", "-quality", "100",
            "-b:v", str(target_br), "-maxrate", str(maxrate),
            "-pix_fmt", "yuv420p",
        ]
    if encoder == "amf":
        return [
            "-c:v", "h264_amf", "-quality", "quality",
            "-rc", "vbr_peak", "-b:v", str(target_br),
            "-maxrate", str(maxrate),
            "-qp_i", "15", "-qp_p", "17", "-bf_delta_qp", "0",
            "-pix_fmt", "yuv420p",
        ]
    # CPU libx264：成品 slow + CRF 14（明显优于原先 faster/CRF20）
    return [
        "-c:v", "libx264", "-preset", "slow", "-crf", "14",
        "-profile:v", "high", "-level", "4.2",
        "-bf", "0", "-pix_fmt", "yuv420p", "-threads", "0",
        # 防止极低码率场景：仍给一个温和上限参考
        "-maxrate", str(maxrate), "-bufsize", str(bufsize),
    ]


def _effective_crop_target(source_w: int, source_h: int, mode_key: str):
    """计算裁切后是否缩放，以及目标尺寸。

    规则（避免糊）：
    - keep：只居中裁 9:16，绝不缩放
    - 指定 720/1080/1440：仅当裁后像素 **大于** 目标时缩小；源更小则保持源像素（绝不放大）
    返回 (target_wh_or_None, note)
    """
    mode = str(mode_key or "keep")
    wanted = _CROP_916_MODES.get(mode)
    if not wanted:
        return None, "仅居中裁切（不缩放，画质最佳）"
    tw, th = int(wanted[0]), int(wanted[1])
    # 裁后近似尺寸（与 FFmpeg crop 表达式一致）
    if source_w > 0 and source_h > 0:
        crop_w = min(source_w, int(source_h * 9 / 16))
        crop_h = min(source_h, int(source_w * 16 / 9))
        crop_w = max(2, (crop_w // 2) * 2)
        crop_h = max(2, (crop_h // 2) * 2)
    else:
        crop_w, crop_h = tw, th
    # 源/裁后任一边小于目标 → 放大会糊，跳过缩放
    if crop_w < tw or crop_h < th:
        return None, (
            f"目标 {tw}×{th} 大于裁后约 {crop_w}×{crop_h}，"
            f"已禁止放大（保持源像素，避免发糊）"
        )
    return (tw, th), f"缩小到 {tw}×{th}（Lanczos，不变形）"


def _is_nearly_916(width: int, height: int, tol: float = 0.012) -> bool:
    if width < 2 or height < 2:
        return False
    return abs((width / float(height)) - (9.0 / 16.0)) <= tol


class MetadataWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    file_done = Signal(str, str)

    def __init__(
        self,
        files,
        output,
        keep_structure=True,
        preserve_time=False,
        watermark=None,
        crop_916=False,
        crop_916_mode="keep",
    ):
        super().__init__()
        self.files = [Path(value) for value in files]
        self.output = Path(output)
        self.keep_structure = keep_structure
        self.preserve_time = preserve_time
        self.watermark = watermark if isinstance(watermark, dict) else None
        self.crop_916 = bool(crop_916)
        self.crop_916_mode = str(crop_916_mode or "keep")
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def _wm_enabled(self) -> bool:
        if not self.watermark or not self.watermark.get("enabled"):
            return False
        path = Path(str(self.watermark.get("path") or ""))
        return path.is_file()

    def _crop_target_size(self, source_w: int = 0, source_h: int = 0):
        """兼容旧调用；真正策略见 _effective_crop_target。"""
        if not self.crop_916:
            return None
        target, _note = _effective_crop_target(source_w, source_h, self.crop_916_mode)
        return target

    def _image(self, source: Path, destination: Path):
        with Image.open(source) as image:
            clean = Image.new(image.mode, image.size)
            clean.putdata(list(image.getdata()))
            if self.crop_916:
                before = (clean.width, clean.height)
                target, note = _effective_crop_target(before[0], before[1], self.crop_916_mode)
                clean = crop_image_to_916(clean, target)
                self.log.emit(
                    f"  · 9:16 居中裁切：{before[0]}×{before[1]} → {clean.width}×{clean.height}"
                    f"（不拉伸；{note}）"
                )
            if self._wm_enabled():
                self.log.emit(f"  · 叠加水印：{Path(self.watermark['path']).name}")
                composed = _overlay_logo_on_image(
                    clean.convert("RGBA"), Path(self.watermark["path"]), self.watermark)
                if source.suffix.lower() in {".jpg", ".jpeg"}:
                    clean = composed.convert("RGB")
                else:
                    clean = composed
            options = {}
            suffix = source.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                if clean.mode not in {"RGB", "L"}:
                    clean = clean.convert("RGB")
                options = {"quality": 95, "optimize": True, "subsampling": 0}
            elif suffix == ".png":
                if clean.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                    clean = clean.convert("RGBA")
                options = {"optimize": True}
            clean.save(destination, **options)

    def _av(self, source: Path, destination: Path):
        ffmpeg = find_media_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 FFmpeg，请先到“设置与组件”一键安装。")
        # 纯音频：只清元数据
        if source.suffix.lower() in AUDIO_EXTENSIONS:
            self._av_copy_clean(ffmpeg, source, destination)
            return
        need_reencode = self._wm_enabled() or self.crop_916
        if not need_reencode:
            self._av_copy_clean(ffmpeg, source, destination)
            return
        # 已是 9:16 且仅裁切、无水印：可走流复制
        if self.crop_916 and not self._wm_enabled() and self.crop_916_mode == "keep":
            w, h, _fps = _probe_video_size(ffmpeg, source)
            if _is_nearly_916(w, h):
                self.log.emit(
                    f"  · 画面已是 9:16（{w}×{h}），跳过裁切，仅清除元数据（流复制、零画质损失）。"
                )
                self._av_copy_clean(ffmpeg, source, destination)
                return
        self._av_reencode(ffmpeg, source, destination)

    def _av_copy_clean(self, ffmpeg, source: Path, destination: Path):
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                   "-map", "0:V?", "-map", "0:a?", "-map", "0:s?",
                   *_META_STRIP, "-c", "copy", str(destination)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())

        if result.returncode:
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                       "-map", "0:V?", "-map", "0:a?",
                       *_META_STRIP, "-c", "copy", str(destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())

        if result.returncode:
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                       "-map", "0:V?", "-map", "0:a?", "-map_metadata", "-1",
                       "-map_metadata:s", "-1", "-map_chapters", "-1", "-metadata", "creation_time=",
                       "-metadata", "location=", "-metadata", "title=", "-metadata", "artist=",
                       "-metadata", "copyright=", "-metadata", "comment=", "-c", "copy", str(destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())

        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "FFmpeg 清除元数据失败")

    def _build_video_chain(self, source_w: int = 0, source_h: int = 0) -> tuple[str, tuple | None, str]:
        """Build video filter chain. Returns (vf, out_size_or_None, scale_note).

        - 居中裁 9:16，不拉伸
        - 目标分辨率仅允许缩小，禁止放大（小图强制 1080p 会发糊）
        - 不改 fps
        """
        parts = ["setpts=PTS-STARTPTS", "format=yuv420p"]
        out_w, out_h = int(source_w or 0), int(source_h or 0)
        scale_note = ""
        if self.crop_916:
            parts.append(_CROP_916_VF)
            # 估算裁后尺寸
            if source_w > 0 and source_h > 0:
                out_w = min(source_w, int(source_h * 9 / 16))
                out_h = min(source_h, int(source_w * 16 / 9))
                out_w = max(2, (out_w // 2) * 2)
                out_h = max(2, (out_h // 2) * 2)
            target, scale_note = _effective_crop_target(source_w, source_h, self.crop_916_mode)
            if target:
                tw, th = int(target[0]), int(target[1])
                # Lanczos 缩小；accurate_rnd + full_chroma 更锐利
                parts.append(
                    f"scale={tw}:{th}:flags=lanczos+accurate_rnd+full_chroma_int"
                )
                parts.append("setsar=1")
                out_w, out_h = tw, th
        # yuv420p 偶数边（裁切表达式已保证偶数，这里兜底）
        parts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        return ",".join(parts), ((out_w, out_h) if out_w and out_h else None), scale_note

    def _av_reencode(self, ffmpeg, source: Path, destination: Path):
        """Re-encode with optional 9:16 crop and/or watermark; strip metadata.

        Quality rules:
        - Center crop only (no stretch)
        - Never upscale to “1080×1920” when source is smaller (that causes blur)
        - No fps filter (preserve source frame rate)
        - Delivery-grade H.264 (slow/CRF14 or HW high quality + bitrate floor)
        """
        w, h, fps, src_br = _probe_video_meta(ffmpeg, source)
        notes = []
        v_prep, out_size, scale_note = self._build_video_chain(w, h)
        if self.crop_916:
            if w and h:
                notes.append(f"源 {w}×{h}")
            if scale_note:
                notes.append(scale_note)
            else:
                notes.append("9:16 居中裁切（不缩放）")
            if out_size:
                notes.append(f"输出约 {out_size[0]}×{out_size[1]}")
        if self._wm_enabled():
            notes.append(f"水印 {Path(self.watermark['path']).name}")
        if fps > 0.1:
            notes.append(f"保留约 {fps:.3g} fps")
        if src_br > 0:
            notes.append(f"源码率约 {src_br / 1_000_000:.2f} Mbps")
        self.log.emit("  · " + "；".join(notes) + "（高质量重编码，不变形、不放大）")

        ow = int(out_size[0]) if out_size else w
        oh = int(out_size[1]) if out_size else h
        encode = _hq_video_encode_args(ffmpeg, ow, oh, src_br)
        # 不强制 -r，避免改帧率导致重复/丢帧；passthrough 尽量按源包时间戳
        rate_args = ["-fps_mode", "passthrough"]

        if self._wm_enabled():
            logo = Path(self.watermark["path"])
            mode = str(self.watermark.get("mode") or "小 Logo 角标")
            opacity = max(0.05, min(1.0, float(self.watermark.get("opacity", 100)) / 100.0))
            width_pct = max(0.04, min(0.80, float(self.watermark.get("width_pct", 18)) / 100.0))
            margin = max(0, int(self.watermark.get("margin", 28) or 28))
            position = str(self.watermark.get("position") or "右下")
            pos_map = {
                "左上": (str(margin), str(margin)),
                "顶部居中": ("(main_w-overlay_w)/2", str(margin)),
                "右上": (f"main_w-overlay_w-{margin}", str(margin)),
                "居中": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
                "左下": (str(margin), f"main_h-overlay_h-{margin}"),
                "底部居中": ("(main_w-overlay_w)/2", f"main_h-overlay_h-{margin}"),
                "右下": (f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"),
            }
            ox, oy = pos_map.get(position, pos_map["右下"])

            cache = self.output / ".watermark_cache"
            cache.mkdir(parents=True, exist_ok=True)
            prepared = cache / f"{logo.stem}_o{int(opacity * 100)}.png"
            try:
                _prepare_logo_rgba(logo, opacity).save(prepared, "PNG")
                logo_input = prepared
            except Exception:
                logo_input = logo

            if "全屏" in mode:
                fc = (
                    f"[0:v]{v_prep}[base];"
                    f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[wmraw];"
                    f"[wmraw][base]scale2ref=w=iw:h=ih[wm][base2];"
                    f"[base2][wm]overlay=0:0:format=auto:eof_action=repeat[vout]"
                )
            else:
                fc = (
                    f"[0:v]{v_prep}[base];"
                    f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[wmraw];"
                    f"[wmraw][base]scale2ref=w=main_w*{width_pct:.4f}:h=ow/mdar[wm][base2];"
                    f"[base2][wm]overlay={ox}:{oy}:format=auto:eof_action=repeat[vout]"
                )

            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                "-loop", "1", "-i", str(logo_input),
                "-filter_complex", fc,
                "-map", "[vout]", "-map", "0:a?",
                *encode,
                "-c:a", "copy",
                *rate_args,
                *_META_STRIP,
                "-shortest", "-movflags", "+faststart",
                str(destination),
            ]
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
            # 音频 copy 失败时回退 AAC
            if result.returncode:
                command = [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source),
                    "-loop", "1", "-i", str(logo_input),
                    "-filter_complex", fc,
                    "-map", "[vout]", "-map", "0:a?",
                    *encode,
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    *rate_args,
                    *_META_STRIP,
                    "-shortest", "-movflags", "+faststart",
                    str(destination),
                ]
                result = subprocess.run(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
            if result.returncode or not destination.is_file() or destination.stat().st_size < 1024:
                raise RuntimeError(
                    (result.stderr or "").strip() or "FFmpeg 处理失败（9:16/水印）")
            return

        # 仅裁切 + 清元数据
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-vf", v_prep,
            "-map", "0:v:0", "-map", "0:a?",
            *encode,
            "-c:a", "copy",
            *rate_args,
            *_META_STRIP,
            "-movflags", "+faststart",
            str(destination),
        ]
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            # 部分容器/编码无法 copy 音轨：重编码音频
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                "-vf", v_prep,
                "-map", "0:v:0", "-map", "0:a?",
                *encode,
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                *rate_args,
                *_META_STRIP,
                "-movflags", "+faststart",
                str(destination),
            ]
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        # 旧版 FFmpeg 可能不认 fps_mode=passthrough
        if result.returncode and "fps_mode" in (result.stderr or ""):
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                "-vf", v_prep,
                "-map", "0:v:0", "-map", "0:a?",
                *encode,
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                *_META_STRIP,
                "-movflags", "+faststart",
                str(destination),
            ]
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode or not destination.is_file() or destination.stat().st_size < 1024:
            raise RuntimeError(
                (result.stderr or "").strip() or "FFmpeg 9:16 裁切失败")

    def run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            common = None
            if self.keep_structure and self.files:
                try:
                    common = Path(os.path.commonpath([str(path.parent) for path in self.files]))
                except ValueError:
                    common = None
            completed = 0
            extras = []
            if self.crop_916:
                extras.append("9:16裁切")
            if self._wm_enabled():
                extras.append("水印")
            note = f"（清理+{'+'.join(extras)}）" if extras else "（清理元数据）"
            for source in self.files:
                if self.cancelled:
                    raise RuntimeError("任务已停止；已完成的文件仍保留在输出目录。")
                relative_parent = Path()
                if common:
                    try:
                        relative_parent = source.parent.relative_to(common)
                    except ValueError:
                        pass
                destination_dir = self.output / relative_parent
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = unique_path(destination_dir / source.name)
                self.log.emit(f"正在处理{note}：{source.name}")
                if source.suffix.lower() in IMAGE_EXTENSIONS:
                    self._image(source, destination)
                else:
                    self._av(source, destination)
                if self.preserve_time:
                    stat = source.stat()
                    os.utime(destination, (stat.st_atime, stat.st_mtime))
                completed += 1
                self.progress.emit(round(completed / len(self.files) * 100))
                self.log.emit(f"完成：{destination}")
                self.file_done.emit(str(source), str(destination))
            msg = f"已处理 {completed} 个素材（清除元数据"
            if self.crop_916:
                msg += " + 9:16 居中裁切"
            if self._wm_enabled():
                msg += " + 水印合成"
            msg += f"）。\n{self.output}"
            self.finished.emit(True, msg)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class MetadataPage(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.files = []
        self.cleaned_files = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)
        title = QLabel("批量清除素材元数据")
        title.setObjectName("heading")
        root.addWidget(title)
        note = QLabel(
            "隐私清理会强制删除 GPS、拍摄时间、设备/序列号、作者版权、唯一标识、标题描述、软件来源、"
            "章节、附件和封面图；图片重建像素并清除 EXIF/XMP/IPTC。原文件不会被修改。"
            "可选「9:16 裁切」：所有视频/图片居中裁成竖屏，不拉伸变形，不强制改帧率，高质量编码。"
            "可选「水印合成」：清理同时把 Logo 烧进画面（视频会重编码）。"
            "注意：文件名以及画面、声音中直接出现的隐私内容需要另行处理。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#94a3b8;")
        root.addWidget(note)
        split = QSplitter()
        source = QGroupBox("素材队列（支持拖入文件或文件夹）")
        source_layout = QVBoxLayout(source)
        self.list = DropListWidget()
        self.list.paths_dropped.connect(self.add_paths)
        self.list.currentTextChanged.connect(self.inspect_selected)
        source_layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        add_files = QPushButton("添加文件")
        add_files.clicked.connect(self.choose_files)
        add_folder = QPushButton("添加文件夹")
        add_folder.clicked.connect(self.choose_folder)
        remove = QPushButton("移除选中")
        remove.clicked.connect(lambda: [self.list.takeItem(i.row()) for i in reversed(self.list.selectedIndexes())])
        clear = QPushButton("清空")
        clear.clicked.connect(self.list.clear)
        for button in (add_files, add_folder, remove, clear):
            buttons.addWidget(button)
        source_layout.addLayout(buttons)

        # 右侧：内容固定最小宽度 + 纵向滚动。
        # 禁止把表单压成「一字竖排」（窄宽度时 QGrid 双列会把中文挤成竖排乱码）。
        LABEL_W = 88
        CTRL_H = 34
        CONTENT_MIN_W = 400

        def _row_label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setFixedWidth(LABEL_W)
            lab.setMinimumHeight(CTRL_H)
            lab.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            lab.setStyleSheet(
                "QLabel{font-size:13px;font-weight:600;color:#e2e8f0;"
                "padding-right:8px;background:transparent;}"
            )
            # 禁止在极窄宽度下自动换行成竖排
            lab.setWordWrap(False)
            lab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            return lab

        def _labeled_row(label: str, *widgets) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(_row_label(label), 0)
            for i, w in enumerate(widgets):
                if hasattr(w, "setMinimumHeight"):
                    w.setMinimumHeight(CTRL_H)
                stretch = 1 if i == 0 and len(widgets) == 1 else (1 if i == 0 else 0)
                row.addWidget(w, stretch)
            return row

        options_host = QWidget()
        options_host.setMinimumWidth(CONTENT_MIN_W)
        options_host.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred
        )
        options_layout = QVBoxLayout(options_host)
        options_layout.setContentsMargins(10, 8, 14, 12)
        options_layout.setSpacing(12)

        out_box = QGroupBox("输出与执行")
        out_box_layout = QVBoxLayout(out_box)
        out_box_layout.setSpacing(10)
        self.output = QLineEdit(str(default_output_path("metadata_clean_outputs")))
        self.output.setMinimumHeight(CTRL_H)
        self.output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        choose = QPushButton("选择…")
        choose.setFixedWidth(84)
        choose.setMinimumHeight(CTRL_H)
        choose.clicked.connect(self.choose_output)
        out_dir_row = _labeled_row("输出目录", self.output, choose)
        out_box_layout.addLayout(out_dir_row)
        self.keep_structure = QCheckBox("保留输入文件夹层级")
        self.keep_structure.setChecked(True)
        self.keep_structure.setMinimumHeight(28)
        self.preserve_time = QCheckBox("保留文件系统修改时间（隐私清理模式下禁用）")
        self.preserve_time.setChecked(False)
        self.preserve_time.setEnabled(False)
        self.preserve_time.setToolTip("拍摄/修改时间可能用于推断活动轨迹，因此隐私清理固定使用新的输出时间。")
        self.preserve_time.setWordWrap(True)
        self.preserve_time.setMinimumHeight(28)
        out_box_layout.addWidget(self.keep_structure)
        out_box_layout.addWidget(self.preserve_time)
        options_layout.addWidget(out_box)

        # —— 9:16 竖屏裁切（可选）——
        crop_box = QGroupBox("9:16 竖屏裁切（可选）")
        crop_layout = QVBoxLayout(crop_box)
        crop_layout.setSpacing(10)
        self.crop_916 = QCheckBox("所有视频/图片裁剪为 9:16")
        self.crop_916.setMinimumHeight(28)
        self.crop_916.setToolTip(
            "居中裁切为竖屏 9:16：\n"
            "· 不拉伸、不变形（只裁掉左右或上下多余部分）\n"
            "· 绝不把小分辨率强行放大到 1080p（会发糊）\n"
            "· 不强制改帧率；高质量重编码（slow/低 CRF 或硬编高画质）\n"
            "· 已是 9:16 且选「仅裁切」时走流复制\n"
            "· 可与水印同时开启（先裁切再叠水印）"
        )
        self.crop_916_mode = QComboBox()
        self.crop_916_mode.addItem("仅居中裁切（推荐，不缩放）", "keep")
        self.crop_916_mode.addItem("裁切后缩小到 1080×1920（不放大）", "1080x1920")
        self.crop_916_mode.addItem("裁切后缩小到 720×1280（不放大）", "720x1280")
        self.crop_916_mode.addItem("裁切后缩小到 1440×2560（不放大）", "1440x2560")
        self.crop_916_mode.setMinimumHeight(CTRL_H)
        self.crop_916_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.crop_916_mode.setToolTip(
            "「仅居中裁切」：只裁 9:16，不做缩放，画质最佳。\n"
            "「缩小到 xxx」：源比目标大时才缩小；源更小则保持源像素，"
            "绝不上采样放大（例如 270×480 不会被拉成 1080×1920 变糊）。"
        )
        crop_layout.addWidget(self.crop_916)
        crop_layout.addLayout(_labeled_row("输出尺寸", self.crop_916_mode))

        def _sync_crop_enabled(on: bool):
            self.crop_916_mode.setEnabled(bool(on))

        self.crop_916.toggled.connect(_sync_crop_enabled)
        _sync_crop_enabled(False)
        options_layout.addWidget(crop_box)

        # —— 水印合成：严格单列（标签在左固定宽，控件在右），永不挤成竖排 ——
        wm_box = QGroupBox("水印合成（可选）")
        wm_outer = QVBoxLayout(wm_box)
        wm_outer.setSpacing(10)
        self.wm_enable = QCheckBox("清理时同时烧录水印")
        self.wm_enable.setToolTip("开启后图片用 PIL 叠图；视频重编码并 overlay Logo，同时清除元数据。")
        self.wm_enable.setMinimumHeight(28)
        wm_outer.addWidget(self.wm_enable)

        self.wm_path = QLineEdit()
        self.wm_path.setPlaceholderText("选择 PNG / JPG Logo（推荐透明 PNG）")
        self.wm_path.setMinimumHeight(CTRL_H)
        self.wm_path.setMinimumWidth(160)
        self.wm_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wm_path.textChanged.connect(
            lambda t: self.wm_path.setToolTip(
                t if t.strip() else "选择 PNG / JPG Logo（推荐透明 PNG）"
            )
        )
        wm_browse = QPushButton("选择…")
        wm_browse.setFixedWidth(84)
        wm_browse.setMinimumHeight(CTRL_H)
        wm_browse.clicked.connect(self.choose_watermark)
        wm_outer.addLayout(_labeled_row("Logo 文件", self.wm_path, wm_browse))

        self.wm_mode = QComboBox()
        self.wm_mode.addItems(["小 Logo 角标", "9:16 全屏覆盖"])
        self.wm_mode.setMinimumHeight(CTRL_H)
        self.wm_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wm_position = QComboBox()
        self.wm_position.addItems(["右下", "右上", "左下", "左上", "顶部居中", "底部居中", "居中"])
        self.wm_position.setMinimumHeight(CTRL_H)
        self.wm_position.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wm_width = QSpinBox()
        self.wm_width.setRange(4, 80)
        self.wm_width.setValue(18)
        self.wm_width.setSuffix(" %")
        self.wm_width.setMinimumHeight(CTRL_H)
        self.wm_width.setMinimumWidth(100)
        self.wm_width.setToolTip("角标模式：相对画面宽度的 Logo 宽度")
        self.wm_opacity = QSpinBox()
        self.wm_opacity.setRange(5, 100)
        self.wm_opacity.setValue(90)
        self.wm_opacity.setSuffix(" %")
        self.wm_opacity.setMinimumHeight(CTRL_H)
        self.wm_opacity.setMinimumWidth(100)
        self.wm_margin = QSpinBox()
        self.wm_margin.setRange(0, 200)
        self.wm_margin.setValue(28)
        self.wm_margin.setSuffix(" px")
        self.wm_margin.setMinimumHeight(CTRL_H)
        self.wm_margin.setMinimumWidth(100)

        # 每一项独占一行 → 小屏也不会把「模式/位置」挤成竖排
        wm_outer.addLayout(_labeled_row("模式", self.wm_mode))
        wm_outer.addLayout(_labeled_row("位置", self.wm_position))
        wm_outer.addLayout(_labeled_row("宽度", self.wm_width))
        wm_outer.addLayout(_labeled_row("不透明度", self.wm_opacity))
        wm_outer.addLayout(_labeled_row("边距", self.wm_margin))

        wm_hint = QLabel("角标模式可调位置 / 宽度 / 边距；全屏覆盖只使用不透明度。")
        wm_hint.setWordWrap(True)
        wm_hint.setStyleSheet("color:#94a3b8;font-size:12px;padding:2px 0 0 0;")
        wm_outer.addWidget(wm_hint)

        def _sync_wm_enabled(on: bool):
            corner = bool(on) and "全屏" not in self.wm_mode.currentText()
            for w in (self.wm_path, wm_browse, self.wm_mode, self.wm_opacity):
                w.setEnabled(bool(on))
            for w in (self.wm_position, self.wm_width, self.wm_margin):
                w.setEnabled(corner)

        self.wm_enable.toggled.connect(_sync_wm_enabled)
        self.wm_mode.currentTextChanged.connect(
            lambda _t: _sync_wm_enabled(self.wm_enable.isChecked()))
        _sync_wm_enabled(False)
        options_layout.addWidget(wm_box)

        inspection = QGroupBox("元数据检查（选中左侧素材自动读取）")
        inspection_layout = QVBoxLayout(inspection)
        inspection_layout.setSpacing(8)
        self.inspect_status = QLabel(
            "请选择一个素材查看清理前信息；完成清理后会自动显示前后对比。"
        )
        self.inspect_status.setWordWrap(True)
        self.inspect_status.setStyleSheet("color:#7dd3fc;font-size:13px;")
        inspection_layout.addWidget(self.inspect_status)
        compare = QHBoxLayout()
        compare.setSpacing(10)
        before_box = QVBoxLayout()
        after_box = QVBoxLayout()
        before_box.addWidget(QLabel("清理前 · 原素材"))
        after_box.addWidget(QLabel("清理后 · 输出成品"))
        self.before_metadata = QPlainTextEdit()
        self.before_metadata.setReadOnly(True)
        self.before_metadata.setMinimumHeight(140)
        self.after_metadata = QPlainTextEdit()
        self.after_metadata.setReadOnly(True)
        self.after_metadata.setMinimumHeight(140)
        metadata_style = "font-family:Consolas,'Microsoft YaHei UI';font-size:12px;"
        self.before_metadata.setStyleSheet(metadata_style)
        self.after_metadata.setStyleSheet(metadata_style)
        before_box.addWidget(self.before_metadata)
        after_box.addWidget(self.after_metadata)
        compare.addLayout(before_box, 1)
        compare.addLayout(after_box, 1)
        inspection_layout.addLayout(compare)
        options_layout.addWidget(inspection)
        self.progress = QProgressBar()
        self.progress.setMinimumHeight(18)
        options_layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(100)
        options_layout.addWidget(self.log, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        self.stop = QPushButton("停止")
        self.stop.setEnabled(False)
        self.stop.setMinimumHeight(36)
        self.stop.setMinimumWidth(88)
        self.stop.clicked.connect(self.cancel)
        self.start = QPushButton("开始批量清除")
        self.start.setObjectName("primary")
        self.start.setMinimumHeight(36)
        self.start.setMinimumWidth(120)
        self.start.clicked.connect(self.run)
        actions.addWidget(self.stop)
        actions.addWidget(self.start)
        options_layout.addLayout(actions)
        options_layout.addStretch(0)

        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        options_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        options_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        options_scroll.setWidget(options_host)
        options_scroll.setMinimumWidth(360)
        options_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:12px;background:#0f172a;margin:0;}"
            "QScrollBar::handle:vertical{background:#334155;border-radius:5px;min-height:28px;}"
            "QScrollBar:horizontal{height:12px;background:#0f172a;margin:0;}"
            "QScrollBar::handle:horizontal{background:#334155;border-radius:5px;min-width:28px;}"
        )

        split.addWidget(source)
        split.addWidget(options_scroll)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([320, 680])
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

    def add_paths(self, paths):
        found = collect_files(paths, MEDIA_EXTENSIONS)
        existing = {self.list.item(i).text() for i in range(self.list.count())}
        for path in found:
            if path not in existing:
                self.list.addItem(path)
                existing.add(path)
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    @staticmethod
    def _privacy_risks(tag_items):
        rules = [
            ("位置/GPS（必须清理）", ("gps", "location", "latitude", "longitude", "altitude", "iso6709", "geotag")),
            ("拍摄与创建时间（必须清理）", ("datetime", "creation_time", "creationdate", "createdate", "modifydate", "timestamp", "date_time")),
            ("设备与序列号（必须清理）", ("make", "model", "serial", "cameraowner", "lensmake", "lensmodel", "hostcomputer", "device")),
            ("作者/版权/联系方式（必须清理）", ("artist", "author", "copyright", "creator", "owner", "byline", "credit", "contact", "email", "publisher", "rights")),
            ("唯一标识符（必须清理）", ("documentid", "instanceid", "uniqueid", "uuid", "identifier", "assetid", "contentid", "mediaid")),
            ("标题/描述/关键词（建议清理）", ("title", "comment", "description", "subject", "keyword", "category", "caption", "synopsis", "lyrics")),
            ("软件与处理来源（建议清理）", ("software", "encoder", "encoded_by", "application", "processingsoftware", "tool")),
            ("人物/人脸区域信息（必须清理）", ("personinimage", "mwg-rs", "regioninfo", "faceregion", "people")),
        ]
        found = {}
        for key, value in tag_items:
            haystack = (str(key) + " " + str(value)[:300]).casefold().replace(" ", "").replace("_", "").replace("-", "")
            for category, patterns in rules:
                if any(pattern.replace("_", "").replace("-", "") in haystack for pattern in patterns):
                    found.setdefault(category, []).append(str(key))
                    break
        return found

    def _append_risk_scan(self, lines, tag_items):
        risks = self._privacy_risks(tag_items)
        lines += ["", "【隐私风险扫描】"]
        if risks:
            for category, keys in risks.items():
                lines.append(f"⚠ {category}：{', '.join(dict.fromkeys(keys))}")
        else:
            lines.append("✓ 未检测到已知的高风险隐私字段")
        return sum(len(values) for values in risks.values())

    def _metadata_details(self, value):
        path = Path(value)
        if not path.is_file():
            return "文件不存在。", 0
        lines = [f"文件：{path.name}", f"大小：{path.stat().st_size:,} 字节", f"扩展名：{path.suffix.lower()}"]
        metadata_count = 0
        tag_items = []
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                with Image.open(path) as image:
                    lines += [f"格式：{image.format}", f"尺寸：{image.width} × {image.height}",
                              f"色彩模式：{image.mode}", "", "【EXIF / 图片元数据】"]
                    exif = image.getexif()
                    for key, val in exif.items():
                        name = ExifTags.TAGS.get(key, str(key))
                        lines.append(f"{name}: {str(val)[:500]}")
                        tag_items.append((name, val))
                        metadata_count += 1
                    for key, val in image.info.items():
                        if key.lower() not in {"exif"}:
                            lines.append(f"{key}: {str(val)[:500]}")
                            tag_items.append((key, val))
                            metadata_count += 1
                    if metadata_count == 0:
                        lines.append("未检测到 EXIF/XMP 等附加信息")
            except Exception as exc:
                lines.append(f"读取图片信息失败：{exc}")
            self._append_risk_scan(lines, tag_items)
            return "\n".join(lines), metadata_count
        ffprobe = find_media_tool("ffprobe")
        if not ffprobe:
            return "\n".join(lines + ["", "未找到 FFprobe，无法读取音视频元数据。"]), 0
        command = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            return "\n".join(lines + ["", result.stderr.strip() or "FFprobe 读取失败"]), 0
        payload = json.loads(result.stdout or "{}")
        fmt = payload.get("format", {})
        lines += [f"容器：{fmt.get('format_long_name') or fmt.get('format_name', '')}",
                  f"时长：{fmt.get('duration', '')} 秒", f"码率：{fmt.get('bit_rate', '')}", "", "【容器元数据】"]
        tags = fmt.get("tags", {}) or {}
        for key, val in tags.items():
            lines.append(f"{key}: {val}")
            tag_items.append((key, val))
            metadata_count += 1
        if not tags:
            lines.append("未检测到容器附加信息")
        for index, stream in enumerate(payload.get("streams", []), 1):
            lines += ["", f"【轨道 {index} · {stream.get('codec_type', 'unknown')}】",
                      f"编码：{stream.get('codec_long_name') or stream.get('codec_name', '')}"]
            for key in ("profile", "width", "height", "r_frame_rate", "sample_rate", "channels",
                        "channel_layout", "bit_rate"):
                if stream.get(key) not in (None, ""):
                    lines.append(f"{key}: {stream[key]}")
            stream_tags = stream.get("tags", {}) or {}
            for key, val in stream_tags.items():
                lines.append(f"tag.{key}: {val}")
                tag_items.append((key, val))
                metadata_count += 1
        self._append_risk_scan(lines, tag_items)
        return "\n".join(lines), metadata_count

    def inspect_selected(self, path):
        if not path:
            self.before_metadata.clear()
            self.after_metadata.clear()
            return
        before, before_count = self._metadata_details(path)
        self.before_metadata.setPlainText(before)
        cleaned = self.cleaned_files.get(str(Path(path)))
        if cleaned and Path(cleaned).is_file():
            after, after_count = self._metadata_details(cleaned)
            self.after_metadata.setPlainText(after)
            removed = max(0, before_count - after_count)
            self.inspect_status.setText(
                f"检测完成：清理前 {before_count} 项附加信息，清理后 {after_count} 项，已减少 {removed} 项。"
                "编码、尺寸、时长等技术参数会保留。")
            self.inspect_status.setStyleSheet("color:#86efac;")
        else:
            self.after_metadata.setPlainText("尚未生成对应的清理成品。")
            self.inspect_status.setText(
                f"原素材检测到 {before_count} 项附加信息；执行清理后将在右侧自动显示结果。")
            self.inspect_status.setStyleSheet("color:#7dd3fc;")

    def _file_cleaned(self, source, destination):
        self.cleaned_files[str(Path(source))] = destination
        if self.list.currentItem() and self.list.currentItem().text() == source:
            self.inspect_selected(source)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择素材", "",
            "媒体文件 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.flac *.aac "
            "*.ogg *.opus *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff)")
        self.add_paths(files)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if folder:
            self.add_paths([folder])

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if folder:
            self.output.setText(folder)

    def choose_watermark(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择水印图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if path:
            self.wm_path.setText(path)
            self.wm_enable.setChecked(True)

    def _watermark_cfg(self):
        if not self.wm_enable.isChecked():
            return None
        path = self.wm_path.text().strip()
        if not path or not Path(path).is_file():
            return None
        return {
            "enabled": True,
            "path": path,
            "mode": self.wm_mode.currentText(),
            "position": self.wm_position.currentText(),
            "width_pct": int(self.wm_width.value()),
            "opacity": int(self.wm_opacity.value()),
            "margin": int(self.wm_margin.value()),
        }

    def _crop_916_mode_key(self) -> str:
        if not hasattr(self, "crop_916_mode"):
            return "keep"
        data = self.crop_916_mode.currentData()
        if data:
            return str(data)
        text = self.crop_916_mode.currentText()
        if "1080" in text:
            return "1080x1920"
        if "720" in text:
            return "720x1280"
        if "1440" in text:
            return "1440x2560"
        return "keep"

    def run(self):
        files = [self.list.item(i).text() for i in range(self.list.count())]
        if not files:
            QMessageBox.information(self, "没有素材", "请先添加视频、音频或图片。")
            return
        if self.wm_enable.isChecked() and not (self.wm_path.text().strip() and Path(self.wm_path.text().strip()).is_file()):
            QMessageBox.warning(self, "水印", "已勾选水印合成，请先选择有效的 Logo 图片。")
            return
        if getattr(self, "thread", None):
            try:
                if self.thread.isRunning():
                    QMessageBox.information(self, "任务进行中", "请等待当前清理结束。")
                    return
            except RuntimeError:
                self.thread = None
        self.log.clear()
        self.progress.setValue(0)
        self.thread = QThread(self)
        crop_on = bool(getattr(self, "crop_916", None) and self.crop_916.isChecked())
        self.worker = MetadataWorker(
            files, self.output.text(), self.keep_structure.isChecked(),
            self.preserve_time.isChecked(),
            watermark=self._watermark_cfg(),
            crop_916=crop_on,
            crop_916_mode=self._crop_916_mode_key() if crop_on else "keep",
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.file_done.connect(self._file_cleaned)
        self.worker.finished.connect(self.done)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._ended)
        self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        if crop_on:
            self.log.appendPlainText(
                f"已开启 9:16 居中裁切（模式：{self.crop_916_mode.currentText()}）；"
                "不拉伸、不强制改帧率，使用高质量编码。"
            )
        self.thread.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()

    def done(self, ok, message):
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(
            self, "元数据清除" if ok else "处理失败", message)

    def _ended(self):
        self.worker = None
        self.thread = None
