import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter

from modules.dynamic_caption_page import (
    PRESETS,
    DynamicCaptionPage,
    caption_uses_bold_face,
    caption_layout_context,
    caption_page_geometry,
    caption_wrapped_lines,
    ass_filter_expression,
    escape_ffmpeg_filter_path,
    temporary_ass_path,
    write_ass,
)


app = QApplication.instance() or QApplication([])
settings = {
    "preset": next(iter(PRESETS)),
    "font": "Noto Sans",
    "font_size": 90,
    "letter_spacing": -4,
    "word_spacing": -12,
    "line_spacing": 100,
    "line_width": 61,
    "line_length": 26,
    "outline_width": 5,
    "position": "底部",
    "margin_v": 500,
    "highlight_padding": 16,
    "highlight_padding_y": 9,
    "animation_speed": 90,
    "caption_mode": "语音同步字幕",
    "text_color": "#FFFFFF",
    "outline_color": "#111111",
    "highlight_color": "#FACC15",
    "layers": [{"type": "caption", "name": "字幕层"}],
}
text = "τους απο τυχερούς ανθρώπους"
context = caption_layout_context(settings)
natural_context = caption_layout_context({**settings, "word_spacing": 0})
assert 0 <= context[2] < natural_context[2], (context[2], natural_context[2])
compressed_context = caption_layout_context({**settings, "word_spacing": -100})
assert compressed_context[2] < 0, compressed_context[2]
lines = caption_wrapped_lines(text, settings, False, context)
pages=[lines[index:index+2] for index in range(0,len(lines),2)]
expected=[]
for page in pages:
    geometry=caption_page_geometry(page,settings,context)
    expected.extend((round(item["x"],1),round(item["y"],1)) for line in geometry for item in line)

target = Path(tempfile.mkdtemp(prefix="caption_layout_")) / "layout.ass"
srt = f"1\n00:00:00,000 --> 00:00:03,000\n{text}\n"
write_ass(target, srt, settings, "")
ass = target.read_text(encoding="utf-8-sig")
base_style=next(line for line in ass.splitlines() if line.startswith("Style: Base,"))
assert base_style.split(",")[7] == ("-1" if caption_uses_bold_face(settings) else "0")
base_positions = []
for line in ass.splitlines():
    if ",Base,," not in line:
        continue
    match = re.search(r"\\pos\(([0-9.]+),([0-9.]+)\)", line)
    if match:
        base_positions.append((float(match.group(1)), float(match.group(2))))

assert base_positions == expected, (base_positions, expected)

# Regression: live painting must consume the same spacing/padding settings and
# must not reference the old, removed local ``gap`` variable.
class LivePaintHarness:
    _paint_live_caption = DynamicCaptionPage._paint_live_caption
    _live_caption_style_cache = None

    def _current_settings(self):
        return settings

    def _live_caption_data(self, _seconds):
        return text, text.split()[1]

canvas = QImage(1080, 1920, QImage.Format.Format_ARGB32_Premultiplied)
canvas.fill(0)
painter = QPainter(canvas)
LivePaintHarness()._paint_live_caption(painter, canvas, 0.5)
painter.end()
problem_path = "/Users/test/Downloads/7月,22日/[成品]/.caption_test.ass"
escaped = escape_ffmpeg_filter_path(problem_path)
assert r"\," in escaped and r"\[" in escaped and r"\]" in escaped
expression = ass_filter_expression(problem_path, settings)
assert "ass=filename='" in expression
temporary = temporary_ass_path("mac_export")
try:
    assert temporary.parent == Path(tempfile.gettempdir()) / "video_toolkit_ass"
    assert temporary.suffix == ".ass" and temporary.is_file()
finally:
    temporary.unlink(missing_ok=True)
print("caption live/ASS layout coordinates: OK")
