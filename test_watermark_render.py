import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from modules.dynamic_caption_page import PreviewWorker


def tools():
    ffmpeg=shutil.which("ffmpeg"); ffprobe=shutil.which("ffprobe")
    if ffmpeg and ffprobe: return ffmpeg,ffprobe
    root=Path(__file__).parent
    bundled=next((p for p in root.glob("dist_*/VideoToolkit/internal/ffmpeg.exe") if p.with_name("ffprobe.exe").is_file()),None)
    return ((str(bundled.resolve()),str(bundled.with_name("ffprobe.exe").resolve())) if bundled else (None,None))


def main():
    app=QApplication.instance() or QApplication([])
    ffmpeg,ffprobe=tools()
    if not ffmpeg:
        print("watermark render: SKIPPED")
        return
    with TemporaryDirectory() as temp:
        root=Path(temp); source=root/"source.mp4"; watermark=root/"logo.png"; output=root/"preview.mp4"; external=root/"voice.m4a"
        subprocess.run([
            ffmpeg,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","color=blue:s=270x480:r=30:d=1.2",
            "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=1.2","-map","0:v:0","-map","1:a:0",
            "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-ac","2",str(source),
        ],check=True)
        image=QImage(160,60,QImage.Format.Format_ARGB32); image.fill(QColor("#80FF3366")); assert image.save(str(watermark))
        subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=660:sample_rate=48000:duration=1.2","-c:a","aac","-ac","2",str(external)],check=True)
        settings={
            "preset":"Descript 经典黄","font":"Arial","font_size":58,"caption_mode":"语音同步字幕",
            "free_animation":"淡入淡出","free_page_seconds":3,"line_length":18,"outline_width":3,"line_width":86,
            "letter_spacing":0,"line_spacing":116,"max_words":7,"highlight_padding":18,"animation_speed":150,
            "position":"底部","margin_v":250,"layers":[
                {"type":"text","name":"公司文字","text":"TEST BRAND","font":"Arial","size":48,"color":"#FFFFFF","outline":"#111111","outline_width":2,"opacity":90,"x":50,"y":12},
                {"type":"caption","name":"字幕层"},
                {"type":"mask","name":"底部蒙版","x":10,"y":82,"w":80,"h":10,"color":"#000000","opacity":40,"radius":20},
            ],
            "text_color":"#FFFFFF","outline_color":"#111827","highlight_color":"#8B5CF6","preview_word_srt":"",
            "watermark_path":str(watermark),"watermark_position":"右上角","watermark_width":18,"watermark_opacity":75,"watermark_margin":20,
        }
        results=[]; worker=PreviewWorker(ffmpeg,source,output,"字幕效果",settings)
        worker.finished.connect(lambda ok,message:results.append((ok,message))); worker.run()
        assert results and results[0][0],results
        probe=subprocess.run([ffprobe,"-v","error","-show_entries","stream=codec_type,channels","-of","json",str(output)],capture_output=True,text=True,encoding="utf-8",check=True)
        streams=json.loads(probe.stdout)["streams"]; assert any(s["codec_type"]=="video" for s in streams)
        assert next(s for s in streams if s["codec_type"]=="audio")["channels"]==2
        settings["preview_audio"]=str(external); second=root/"preview_external.mp4"; results.clear()
        worker=PreviewWorker(ffmpeg,source,second,"字幕效果",settings); worker.finished.connect(lambda ok,message:results.append((ok,message))); worker.run()
        assert results and results[0][0],results
    print("watermark preview + stereo render: OK")


if __name__=="__main__":
    main()
