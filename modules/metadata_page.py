from __future__ import annotations

import os
import json
import shutil
import subprocess
from pathlib import Path

from PIL import ExifTags, Image
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from .path_picker import (AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
                          DropListWidget, collect_files, default_output_path, load_subfolders, natural_key)
from .settings_page import find_media_tool, hidden_kwargs


MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复的输出文件名：{path.name}")


class MetadataWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    file_done = Signal(str, str)

    def __init__(self, files, output, keep_structure=True, preserve_time=False):
        super().__init__()
        self.files = [Path(value) for value in files]
        self.output = Path(output)
        self.keep_structure = keep_structure
        self.preserve_time = preserve_time
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def _image(self, source: Path, destination: Path):
        with Image.open(source) as image:
            clean = Image.new(image.mode, image.size)
            clean.putdata(list(image.getdata()))
            options = {}
            suffix = source.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                if clean.mode not in {"RGB", "L"}:
                    clean = clean.convert("RGB")
                options = {"quality": 95, "optimize": True, "subsampling": 0}
            elif suffix == ".png":
                options = {"optimize": True}
            clean.save(destination, **options)

    def _av(self, source: Path, destination: Path):
        ffmpeg = find_media_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 FFmpeg，请先到“设置与组件”一键安装。")
        # 只保留正常画面、音频和字幕。大写 V 会排除 attached_pic（音频封面图）；
        # 附件、数据轨、章节、全局/轨道/节目元数据全部不复制。
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                   "-map", "0:V?", "-map", "0:a?", "-map", "0:s?",
                   "-map_metadata", "-1", "-map_metadata:s", "-1", "-map_metadata:p", "-1",
                   "-map_metadata:c", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
                   "-metadata", "creation_time=", "-metadata", "date=", "-metadata", "location=",
                   "-metadata", "title=", "-metadata", "artist=", "-metadata", "author=",
                   "-metadata", "copyright=", "-metadata", "comment=", "-metadata", "description=",
                   "-metadata", "encoder=", "-c", "copy", str(destination)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            # 个别容器不接受部分高级映射参数时仍只保留标准音视频/字幕流。
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                       "-map", "0:V?", "-map", "0:a?", "-map", "0:s?", "-map_metadata", "-1",
                       "-map_metadata:s", "-1", "-map_chapters", "-1", "-metadata", "creation_time=",
                       "-metadata", "location=", "-metadata", "title=", "-metadata", "artist=",
                       "-metadata", "copyright=", "-metadata", "comment=", "-c", "copy", str(destination)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", **hidden_kwargs())
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "FFmpeg 清除元数据失败")

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
                self.log.emit(f"正在处理：{source.name}")
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
            self.finished.emit(True, f"已清除 {completed} 个素材文件的内嵌元数据。\n{self.output}")
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
        root = QVBoxLayout(self); root.setContentsMargins(18, 14, 18, 14); root.setSpacing(8)
        title = QLabel("批量清除素材元数据"); title.setObjectName("heading"); root.addWidget(title)
        note = QLabel("隐私清理会强制删除 GPS、拍摄时间、设备/序列号、作者版权、唯一标识、标题描述、软件来源、章节、附件和封面图；图片重建像素并清除 EXIF/XMP/IPTC。原文件不会被修改。注意：文件名以及画面、声音中直接出现的隐私内容需要另行处理。")
        note.setWordWrap(True); note.setStyleSheet("color:#94a3b8;"); root.addWidget(note)
        split = QSplitter()
        source = QGroupBox("素材队列（支持拖入文件或文件夹）"); source_layout = QVBoxLayout(source)
        self.list = DropListWidget(); self.list.paths_dropped.connect(self.add_paths); self.list.currentTextChanged.connect(self.inspect_selected); source_layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        add_files = QPushButton("添加文件"); add_files.clicked.connect(self.choose_files)
        add_folder = QPushButton("添加文件夹"); add_folder.clicked.connect(self.choose_folder)
        remove = QPushButton("移除选中"); remove.clicked.connect(lambda: [self.list.takeItem(i.row()) for i in reversed(self.list.selectedIndexes())])
        clear = QPushButton("清空"); clear.clicked.connect(self.list.clear)
        for button in (add_files, add_folder, remove, clear): buttons.addWidget(button)
        source_layout.addLayout(buttons)

        options = QGroupBox("输出与执行"); options_layout = QVBoxLayout(options)
        form = QFormLayout()
        self.output = QLineEdit(str(default_output_path("metadata_clean_outputs")))
        out_row = QHBoxLayout(); out_row.addWidget(self.output); choose = QPushButton("选择…"); choose.clicked.connect(self.choose_output); out_row.addWidget(choose)
        form.addRow("输出目录", out_row)
        self.keep_structure = QCheckBox("保留输入文件夹层级"); self.keep_structure.setChecked(True)
        self.preserve_time = QCheckBox("保留文件系统修改时间（隐私清理模式下禁用）")
        self.preserve_time.setChecked(False); self.preserve_time.setEnabled(False)
        self.preserve_time.setToolTip("拍摄/修改时间可能用于推断活动轨迹，因此隐私清理固定使用新的输出时间。")
        form.addRow("目录结构", self.keep_structure); form.addRow("文件时间", self.preserve_time)
        options_layout.addLayout(form)
        inspection = QGroupBox("元数据检查（选中左侧素材自动读取）"); inspection_layout = QVBoxLayout(inspection)
        self.inspect_status = QLabel("请选择一个素材查看清理前信息；完成清理后会自动显示前后对比。")
        self.inspect_status.setWordWrap(True); self.inspect_status.setStyleSheet("color:#7dd3fc;"); inspection_layout.addWidget(self.inspect_status)
        compare = QHBoxLayout(); before_box = QVBoxLayout(); after_box = QVBoxLayout()
        before_box.addWidget(QLabel("清理前 · 原素材")); after_box.addWidget(QLabel("清理后 · 输出成品"))
        self.before_metadata = QPlainTextEdit(); self.before_metadata.setReadOnly(True); self.before_metadata.setMinimumHeight(190)
        self.after_metadata = QPlainTextEdit(); self.after_metadata.setReadOnly(True); self.after_metadata.setMinimumHeight(190)
        metadata_style="font-family:Consolas,'Microsoft YaHei UI';font-size:12px;"
        self.before_metadata.setStyleSheet(metadata_style); self.after_metadata.setStyleSheet(metadata_style)
        before_box.addWidget(self.before_metadata); after_box.addWidget(self.after_metadata)
        compare.addLayout(before_box,1); compare.addLayout(after_box,1); inspection_layout.addLayout(compare)
        options_layout.addWidget(inspection)
        self.progress = QProgressBar(); options_layout.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); options_layout.addWidget(self.log, 1)
        actions = QHBoxLayout(); actions.addStretch()
        self.stop = QPushButton("停止"); self.stop.setEnabled(False); self.stop.clicked.connect(self.cancel)
        self.start = QPushButton("开始批量清除"); self.start.setObjectName("primary"); self.start.clicked.connect(self.run)
        actions.addWidget(self.stop); actions.addWidget(self.start); options_layout.addLayout(actions)
        split.addWidget(source); split.addWidget(options); split.setSizes([560, 720]); root.addWidget(split, 1)

    def add_paths(self, paths):
        found = collect_files(paths, MEDIA_EXTENSIONS)
        existing = {self.list.item(i).text() for i in range(self.list.count())}
        for path in found:
            if path not in existing: self.list.addItem(path); existing.add(path)
        if self.list.count() and self.list.currentRow()<0: self.list.setCurrentRow(0)

    @staticmethod
    def _privacy_risks(tag_items):
        rules = [
            ("位置/GPS（必须清理）", ("gps","location","latitude","longitude","altitude","iso6709","geotag")),
            ("拍摄与创建时间（必须清理）", ("datetime","creation_time","creationdate","createdate","modifydate","timestamp","date_time")),
            ("设备与序列号（必须清理）", ("make","model","serial","cameraowner","lensmake","lensmodel","hostcomputer","device")),
            ("作者/版权/联系方式（必须清理）", ("artist","author","copyright","creator","owner","byline","credit","contact","email","publisher","rights")),
            ("唯一标识符（必须清理）", ("documentid","instanceid","uniqueid","uuid","identifier","assetid","contentid","mediaid")),
            ("标题/描述/关键词（建议清理）", ("title","comment","description","subject","keyword","category","caption","synopsis","lyrics")),
            ("软件与处理来源（建议清理）", ("software","encoder","encoded_by","application","processingsoftware","tool")),
            ("人物/人脸区域信息（必须清理）", ("personinimage","mwg-rs","regioninfo","faceregion","people")),
        ]
        found={}
        for key,value in tag_items:
            haystack=(str(key)+" "+str(value)[:300]).casefold().replace(" ","").replace("_","").replace("-","")
            for category,patterns in rules:
                if any(pattern.replace("_","").replace("-","") in haystack for pattern in patterns):
                    found.setdefault(category,[]).append(str(key)); break
        return found

    def _append_risk_scan(self, lines, tag_items):
        risks=self._privacy_risks(tag_items)
        lines += ["", "【隐私风险扫描】"]
        if risks:
            for category,keys in risks.items(): lines.append(f"⚠ {category}：{', '.join(dict.fromkeys(keys))}")
        else:
            lines.append("✓ 未检测到已知的高风险隐私字段")
        return sum(len(values) for values in risks.values())

    def _metadata_details(self, value):
        path=Path(value)
        if not path.is_file(): return "文件不存在。",0
        lines=[f"文件：{path.name}",f"大小：{path.stat().st_size:,} 字节",f"扩展名：{path.suffix.lower()}"]
        metadata_count=0; tag_items=[]
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                with Image.open(path) as image:
                    lines += [f"格式：{image.format}",f"尺寸：{image.width} × {image.height}",f"色彩模式：{image.mode}","", "【EXIF / 图片元数据】"]
                    exif=image.getexif()
                    for key,val in exif.items():
                        name=ExifTags.TAGS.get(key,str(key)); lines.append(f"{name}: {str(val)[:500]}"); tag_items.append((name,val)); metadata_count+=1
                    for key,val in image.info.items():
                        if key.lower() not in {"exif"}:
                            lines.append(f"{key}: {str(val)[:500]}"); tag_items.append((key,val)); metadata_count+=1
                    if metadata_count==0: lines.append("未检测到 EXIF/XMP 等附加信息")
            except Exception as exc: lines.append(f"读取图片信息失败：{exc}")
            self._append_risk_scan(lines,tag_items)
            return "\n".join(lines),metadata_count
        ffprobe=find_media_tool("ffprobe")
        if not ffprobe: return "\n".join(lines+["","未找到 FFprobe，无法读取音视频元数据。"]),0
        command=[ffprobe,"-v","error","-print_format","json","-show_format","-show_streams",str(path)]
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",**hidden_kwargs())
        if result.returncode: return "\n".join(lines+["",result.stderr.strip() or "FFprobe 读取失败"]),0
        payload=json.loads(result.stdout or "{}")
        fmt=payload.get("format",{}); lines += [f"容器：{fmt.get('format_long_name') or fmt.get('format_name','')}",f"时长：{fmt.get('duration','')} 秒",f"码率：{fmt.get('bit_rate','')}","","【容器元数据】"]
        tags=fmt.get("tags",{}) or {}
        for key,val in tags.items(): lines.append(f"{key}: {val}"); tag_items.append((key,val)); metadata_count+=1
        if not tags: lines.append("未检测到容器附加信息")
        for index,stream in enumerate(payload.get("streams",[]),1):
            lines += ["",f"【轨道 {index} · {stream.get('codec_type','unknown')}】",f"编码：{stream.get('codec_long_name') or stream.get('codec_name','')}"]
            for key in ("profile","width","height","r_frame_rate","sample_rate","channels","channel_layout","bit_rate"):
                if stream.get(key) not in (None,""): lines.append(f"{key}: {stream[key]}")
            stream_tags=stream.get("tags",{}) or {}
            for key,val in stream_tags.items(): lines.append(f"tag.{key}: {val}"); tag_items.append((key,val)); metadata_count+=1
        self._append_risk_scan(lines,tag_items)
        return "\n".join(lines),metadata_count

    def inspect_selected(self, path):
        if not path: self.before_metadata.clear(); self.after_metadata.clear(); return
        before,before_count=self._metadata_details(path); self.before_metadata.setPlainText(before)
        cleaned=self.cleaned_files.get(str(Path(path)))
        if cleaned and Path(cleaned).is_file():
            after,after_count=self._metadata_details(cleaned); self.after_metadata.setPlainText(after)
            removed=max(0,before_count-after_count)
            self.inspect_status.setText(f"检测完成：清理前 {before_count} 项附加信息，清理后 {after_count} 项，已减少 {removed} 项。编码、尺寸、时长等技术参数会保留。")
            self.inspect_status.setStyleSheet("color:#86efac;")
        else:
            self.after_metadata.setPlainText("尚未生成对应的清理成品。")
            self.inspect_status.setText(f"原素材检测到 {before_count} 项附加信息；执行清理后将在右侧自动显示结果。")
            self.inspect_status.setStyleSheet("color:#7dd3fc;")

    def _file_cleaned(self, source, destination):
        self.cleaned_files[str(Path(source))]=destination
        if self.list.currentItem() and self.list.currentItem().text()==source: self.inspect_selected(source)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择素材", "", "媒体文件 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.flac *.aac *.ogg *.opus *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff)")
        self.add_paths(files)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if folder: self.add_paths([folder])



    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if folder: self.output.setText(folder)

    def run(self):
        files = [self.list.item(i).text() for i in range(self.list.count())]
        if not files:
            QMessageBox.information(self, "没有素材", "请先添加视频、音频或图片。")
            return
        self.log.clear(); self.progress.setValue(0)
        self.thread = QThread(self)
        self.worker = MetadataWorker(files, self.output.text(), self.keep_structure.isChecked(), self.preserve_time.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log.appendPlainText); self.worker.progress.connect(self.progress.setValue)
        self.worker.file_done.connect(self._file_cleaned)
        self.worker.finished.connect(self.done); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self._ended); self.thread.finished.connect(self.thread.deleteLater)
        self.start.setEnabled(False); self.stop.setEnabled(True); self.thread.start()

    def cancel(self):
        if self.worker: self.worker.cancel()

    def done(self, ok, message):
        self.start.setEnabled(True); self.stop.setEnabled(False); self.log.appendPlainText(message)
        (QMessageBox.information if ok else QMessageBox.critical)(self, "元数据清除" if ok else "处理失败", message)

    def _ended(self):
        self.worker = None; self.thread = None
