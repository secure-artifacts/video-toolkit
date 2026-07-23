import os
import tempfile
from pathlib import Path

root = tempfile.mkdtemp(prefix="video_toolkit_test_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = root
os.environ["LOCALAPPDATA"] = root
os.environ["VIDEO_TOOLKIT_DISABLE_STYLE_MEMORY"] = "1"

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import app as toolkit
from PySide6.QtWidgets import QMessageBox, QInputDialog
QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
QMessageBox.warning = lambda *a, **kw: QMessageBox.StandardButton.Ok
QMessageBox.information = lambda *a, **kw: QMessageBox.StandardButton.Ok
from modules.rename_page import SmartTitleWorker

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, root)

class FakeResponse:
    status_code = 200

captured_headers = {}
original_get = toolkit.requests.get
def fake_get(*args, **kwargs):
    captured_headers.update(kwargs.get("headers", {}))
    return FakeResponse()
toolkit.requests.get = fake_get
assert toolkit.check_api_key("Groq", "gsk_valid_ascii_key") == (True, "验证通过")
assert captured_headers["User-Agent"] == "VideoToolkit/1.0"
assert toolkit.check_api_key("Groq", "中文密钥")[1].startswith("密钥格式异常")
toolkit.requests.get = original_get

qt = QApplication([])
qt.setStyleSheet(toolkit.STYLE)
window = toolkit.MainWindow()
window.resize(1600, 920)

assert window.pages.count() == 11
assert len(window.pages.widget(0).findChildren(toolkit.ToolCard)) == 7
assert window.nav_buttons[-1].text() == "帮助"
assert not any(button.text() == "密钥管理" for button in window.nav_buttons)
assert window.pages.widget(3) is window.dynamic_caption_page
assert any(button.text() == "Reels 编辑器" for button in window.nav_buttons)
assert not hasattr(window, "watermark_tabs")
assert window.dynamic_caption_page.source_stack.count() == 4
assert window.dynamic_caption_page.font.currentText() == "Arial"
assert window.dynamic_caption_page.font_size.value() == 90
assert window.dynamic_caption_page.letter_spacing.value() == -4
assert window.dynamic_caption_page.line_spacing.value() == 100
assert window.dynamic_caption_page.margin_v.value() == 500
assert window.dynamic_caption_page.cloud_sync_check.isChecked() is False
assert not window.dynamic_caption_page.log.isHidden()
assert not hasattr(window.dynamic_caption_page, "view_log_btn")
assert any(button.text() == "查看软件日志" for button in window.pages.widget(9).findChildren(toolkit.QPushButton))
assert window.settings_page.count() == 4
assert window.settings_page.tabText(1) == "字体管理"
assert window.settings_page.tabText(3) == "API 密钥管理"
window._show_page(6)
assert window.pages.currentIndex() == 7
assert window.settings_page.currentWidget() is window.key_settings_page
assert window.dynamic_caption_page.videos.isHidden()
assert window.dynamic_caption_page.task_queue.parent() is not None
assert window.dynamic_caption_page.watermark_opacity.value() == 100
assert window.dynamic_caption_page.watermark_table.columnCount() == 4
assert window.dynamic_caption_page.group_burn_watermark.isChecked() is False
assert Path(window.dynamic_caption_page.output.text()).is_absolute()
assert Path(window.dynamic_caption_page.output.text()).parent != Path(Path(window.dynamic_caption_page.output.text()).anchor)
assert any(button.text() == "清空" for button in window.dynamic_caption_page.source_stack.widget(0).findChildren(toolkit.QPushButton))
assert hasattr(window.dynamic_caption_page,"preset_list_widget")
style_page=window.dynamic_caption_page
style_page.font_size.setValue(73); style_page.letter_spacing.setValue(6)
style_page.layers=[{"type":"caption","name":"字幕层"},{"type":"mask","name":"测试蒙版","x":2,"y":3,"w":90,"h":20,"opacity":50,"radius":10,"color":"#000000"}]
snapshot=style_page._style_template_snapshot()
style_page.font_size.setValue(42); style_page.letter_spacing.setValue(-2); style_page.layers=[{"type":"caption","name":"字幕层"}]
style_page._apply_style_template_data(snapshot)
assert style_page.font_size.value()==73 and style_page.letter_spacing.value()==6
assert any(layer.get("name")=="测试蒙版" for layer in style_page.layers)
from PySide6.QtWidgets import QInputDialog, QMessageBox
original_get_text = QInputDialog.getText
QInputDialog.getText = lambda *a, **kw: ("测试样式", True)
original_question = QMessageBox.question
QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
style_page._save_current_preset()
QInputDialog.getText = original_get_text
QMessageBox.question = original_question
assert any(item["name"] == "测试样式" for item in style_page.all_presets)
style_export=Path(root)/"subtitle-preset.json"
original_save_file=toolkit.QFileDialog.getSaveFileName
original_open_file=toolkit.QFileDialog.getOpenFileName
toolkit.QFileDialog.getSaveFileName=lambda *args,**kwargs:(str(style_export),"样式预设 (*.json)")
style_page.preset_buttons[0].setChecked(True)
style_page._export_selected_preset()
assert style_export.is_file()
QSettings("VideoToolkit", "DynamicReels").remove("presets_list_json")
style_page.all_presets = []
style_page._load_all_presets()
assert not any(item["name"] == "测试样式" for item in style_page.all_presets)
toolkit.QFileDialog.getOpenFileName=lambda *args,**kwargs:(str(style_export),"样式预设 (*.json)")
style_page._import_preset()
toolkit.QFileDialog.getSaveFileName=original_save_file
toolkit.QFileDialog.getOpenFileName=original_open_file
assert any(item["name"] == "测试样式" for item in style_page.all_presets) and style_page.font_size.value()==73
extract_calls=[]
style_page.extract_all_timelines=lambda:extract_calls.append("all")
style_page._load_group_merge_outputs(auto_extract=True)
qt.processEvents(); assert not extract_calls
style_page._group_auto_extract_pending=True
style_page._group_merge_ended(); qt.processEvents()
assert extract_calls==["all"]
assert window.rename_page.date_enabled.isChecked() and window.rename_page.suffix_enabled.isChecked()
assert not window.rename_page.direct_replace.isChecked()
assert not hasattr(window.rename_page,"subfolders") and not hasattr(window.rename_page,"task_name")
reels_buttons=[button.text() for button in window.dynamic_caption_page.findChildren(toolkit.QPushButton)]
assert "本地字体…" not in reels_buttons and "开源字体…" not in reels_buttons
settings_buttons=[button.text() for button in window.font_settings_page.findChildren(toolkit.QPushButton)]
assert "导入本地字体…" in settings_buttons and "下载开源字体…" in settings_buttons
assert window.dynamic_caption_page.tts_text.columnCount() == 2
assert window.dynamic_caption_page.tts_text.editTriggers() == toolkit.QAbstractItemView.EditTrigger.NoEditTriggers
assert hasattr(window.dynamic_caption_page, "source_proofread")
assert window.dynamic_caption_page.findChild(toolkit.QFrame, "reelsRunPanel") is None
pipeline_step_labels = [label.text() for label in window.pages.widget(8).findChildren(toolkit.QLabel)]
assert any("⑤ 批量上传" in text and "⑥ 批量填表" in text for text in pipeline_step_labels)
assert not any(button.text() == "开始智能提取字幕" for button in window.pages.widget(0).findChildren(toolkit.QPushButton))
assert window.subtitle_resume_check.isChecked()
assert window.pipeline_resume_check.isChecked()
assert window.provider_combo.itemText(0) == toolkit.AUTO_PROVIDER
assert window._resolve_provider() == toolkit.LOCAL_PROVIDER
assert window.key_table.columnCount() == 7
assert toolkit.is_supported_video_url("https://www.youtube.com/watch?v=test")
assert toolkit.is_supported_video_url("https://www.facebook.com/watch/?v=1")
assert toolkit.is_supported_video_url("https://www.instagram.com/reel/test/")
assert toolkit.is_supported_video_url("https://www.tiktok.com/@user/video/1")
assert not toolkit.is_supported_video_url("https://example.com/video")
assert hasattr(window, "url_input")
media_root = Path(root) / "parent" / "child"
media_root.mkdir(parents=True)
(media_root / "2.mp4").write_bytes(b"test")
(media_root / "10.mp3").write_bytes(b"test")
(media_root / "ignore.txt").write_text("skip", encoding="utf-8")
window._add_media_paths([str(media_root.parent)])
assert window.file_list.count() == 2
assert window.file_list.item(0).text().endswith("2.mp4")
assert window.file_list.item(1).text().endswith("10.mp3")

window.smartcut_page.add_paths([str(media_root.parent)])
assert window.smartcut_page.files.count() == 1
window.screenshot_page.add_local_paths([str(media_root.parent)])
assert "2.mp4" in window.screenshot_page.url_input.toPlainText()
assert "10.mp3" not in window.screenshot_page.url_input.toPlainText()
window.rename_page.set_input_folder(str(media_root))
assert window.rename_page.input.text() == str(media_root)
assert window.rename_page.smart_titles_btn.isEnabled()
window.subtitle_results["2.mp4"] = {"original":"cached original", "chinese":"缓存标题", "srt":"cached srt"}
assert window._rename_title_transcribe(str(media_root / "2.mp4"))[1] == "缓存标题"
foreign_only=[]
worker=SmartTitleWorker([media_root/"2.mp4"],lambda _path:("foreign title","", "srt"))
worker.finished.connect(lambda ok,message,titles:foreign_only.extend(titles)); worker.run()
assert foreign_only == ["2"]
chinese_only=[]
worker=SmartTitleWorker([media_root/"2.mp4"],lambda _path:("foreign title","中文标题", "srt"))
worker.finished.connect(lambda ok,message,titles:chinese_only.extend(titles)); worker.run()
assert chinese_only == ["中文标题"]
original_caption_transcribe = window._caption_transcribe
window._caption_transcribe = lambda path, provider: ("fresh original", "新识别标题", "fresh srt")
assert window._rename_title_transcribe(str(media_root / "missing.mp4"))[1] == "新识别标题"
window._caption_transcribe = original_caption_transcribe
window.subtitle_results.pop("2.mp4", None)

pipeline_output = Path(root) / "pipeline_test"
pipeline = toolkit.PipelineWorker(
    window.store, [str(media_root / "2.mp4")], str(pipeline_output), 27,
    toolkit.LOCAL_PROVIDER, "small", "auto", "ffmpeg",
    "ZB", "20260719", "FF-PT", 1, 3)
def fake_cut(clips_dir):
    clips = []
    for number in (1, 2):
        path = clips_dir / f"001_{number:03d}.mp4"
        path.write_bytes(b"mock video")
        clips.append(path)
    return clips
pipeline._cut_sources = fake_cut
pipeline.cloud_config = {"enabled": True}
original_process_one = toolkit.TranscribeWorker._process_one
original_cloud_run = toolkit.GoogleCloudSync.run
def fake_process_one(worker, source):
    name = Path(source).name
    worker.result_ready.emit(name, f"original {name}", f"字幕标题 {name}",
                             "1\n00:00:00,000 --> 00:00:01,000\ntext\n")
toolkit.TranscribeWorker._process_one = fake_process_one
pipeline_state = {}
pipeline.titles_ready.connect(lambda folder, titles: pipeline_state.update(folder=folder, titles=titles))
pipeline.cloud_failed.connect(lambda folder, error: pipeline_state.update(cloud_failed=error))
pipeline.finished.connect(lambda ok, message: pipeline_state.update(ok=ok, message=message))
toolkit.GoogleCloudSync.run = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("模拟授权失败"))
pipeline.run()
toolkit.TranscribeWorker._process_one = original_process_one
toolkit.GoogleCloudSync.run = original_cloud_run
assert pipeline_state["ok"] is True
assert "模拟授权失败" in pipeline_state["cloud_failed"]
assert len(pipeline_state["titles"]) == 2
final_files = list(pipeline_output.glob("流水线_*/03_重命名成品/*.mp4"))
assert len(final_files) == 2 and "字幕标题" in final_files[0].name
window._subtitle_result_ready("片段1.mp4", "original one", "中文一", "srt one")
window._subtitle_result_ready("片段2.mp4", "original two", "中文二", "srt two")
assert "片段1.mp4" in window.original_result.toPlainText()
assert "片段2.mp4" in window.original_result.toPlainText()
window._copy_all_original()
assert "original one" in qt.clipboard().text() and "original two" in qt.clipboard().text()
export_dir = Path(root) / "subtitle_export"; export_dir.mkdir()
original_choose_dir = toolkit.QFileDialog.getExistingDirectory
original_information = toolkit.QMessageBox.information
toolkit.QFileDialog.getExistingDirectory = lambda *args, **kwargs: str(export_dir)
toolkit.QMessageBox.information = lambda *args, **kwargs: None
window._export_all_subtitles()
toolkit.QFileDialog.getExistingDirectory = original_choose_dir
toolkit.QMessageBox.information = original_information
assert len(list(export_dir.glob("*.srt"))) == 2
assert toolkit.column_to_index("A") == 0 and toolkit.column_to_index("W") == 22
assert toolkit.index_to_column(22) == "W"
word_srt = ("1\n00:00:04,040 --> 00:00:04,440\npasse\n\n"
            "2\n00:00:04,440 --> 00:00:04,640\npor\n\n"
            "3\n00:00:04,640 --> 00:00:05,100\naí.\n")
phrase_srt = toolkit.group_word_srt(word_srt)
assert phrase_srt.count("-->") == 1 and "00:00:04,040" in phrase_srt and "passe por aí." in phrase_srt
ass_path = Path(root) / "moving_highlight.ass"
toolkit.write_ass(ass_path, phrase_srt, {"preset":"背景跟读","font":"Arial","font_size":48,
    "line_length":30,"outline_width":2,"position":"底部","margin_v":180,
    "text_color":"#FFFFFF","outline_color":"#111827","highlight_color":"#2563EB"}, word_srt)
ass_text = ass_path.read_text(encoding="utf-8-sig")
assert ass_text.count("Dialogue: 0") == 3
assert ass_text.count("Dialogue: 1") == 3 and ass_text.count("Dialogue: 2") == 3
assert "Style: HighlightBox" in ass_text and "\\p1" in ass_text
cloud_final = Path(root) / "cloud_final"; cloud_final.mkdir()
(cloud_final / "001-final.mp4").write_bytes(b"final1")
(cloud_final / "002-final.mp4").write_bytes(b"final2")
cloud_config = {"json_path": "unused.json", "parent_folder": "1234567890123456789012345",
                "folder_mode": "视频名称", "public_link": False, "write_sheet": False}
cloud = toolkit.GoogleCloudSync(cloud_config)
cloud._services = lambda: (object(), object(), "service@example.com")
folder_calls = []
cloud._find_or_create_folder = lambda drive, name, parent: folder_calls.append((name, parent)) or ("folder_" + str(len(folder_calls)))
uploaded_names = []
cloud._upload_file = lambda drive, path, parent: uploaded_names.append(path.name) or {
    "id": path.stem, "webViewLink": "https://drive.google.com/file/d/" + path.stem}
folder_url, cloud_summary = cloud.run(cloud_final, [], [str(media_root / "2.mp4")])
assert uploaded_names == ["001-final.mp4", "002-final.mp4"]
assert folder_calls[0][0].count("-") == 2 and folder_calls[1][0] == "2"
assert "新上传 2 个" in cloud_summary and "复用云端已有 0 个" in cloud_summary and "/folders/" in folder_url

class FakeCall:
    def __init__(self, payload=None): self.payload = payload or {}
    def execute(self): return self.payload
class FakeValues:
    def __init__(self): self.updated_body = None
    def get(self, **kwargs): return FakeCall({"values": []})
    def batchUpdate(self, **kwargs): return FakeCall()
    def update(self, **kwargs): self.updated_body = kwargs["body"]; return FakeCall()
class FakeSpreadsheets:
    def __init__(self): self.value_api = FakeValues()
    def values(self): return self.value_api
    def get(self, **kwargs): return FakeCall({"sheets": [{"properties": {"title": "目标Sheet", "sheetId": 7}}]})
    def batchUpdate(self, **kwargs): return FakeCall()
class FakeSheets:
    def __init__(self): self.api = FakeSpreadsheets()
    def spreadsheets(self): return self.api
mapping_config = {
    "spreadsheet_id": "1234567890123456789012345", "sheet_name": "目标Sheet", "insert_row": 4,
    "variable_fields": [{"field": "本次组别", "column": "E", "options": ["A组", "B组"], "selected": "B组"}],
    "sheet_mappings": [
        {"field": "中文", "column": "A", "source": "chinese", "value": ""},
        {"field": "组别", "column": "B", "source": "static", "value": "固定组"},
        {"field": "原文", "column": "C", "source": "original", "value": ""},
        {"field": "日期", "column": "D", "source": "date", "value": ""},
        {"field": "文件", "column": "F", "source": "file", "value": ""},
        {"field": "目录", "column": "Z", "source": "folder", "value": ""},
    ]}
mapping_cloud = toolkit.GoogleCloudSync(mapping_config)
fake_sheets = FakeSheets()
mapping_cloud._write_sheet(fake_sheets, [{"path": cloud_final / "001-final.mp4", "url": "https://file",
                                          "chinese": "中文内容", "original": "Texto"}], "https://folder")
sheet_row = fake_sheets.api.value_api.updated_body["values"][0]
assert sheet_row[0] == "中文内容" and sheet_row[1] == "固定组" and sheet_row[2] == "Texto"
assert sheet_row[4] == "B组" and "HYPERLINK" in sheet_row[5] and sheet_row[25] == "https://folder"

bad_google_json = Path(root) / "bad_google.json"
bad_google_json.write_text('{"type":"service_account"}', encoding="utf-8")
try:
    toolkit.load_google_credentials({"json_path": str(bad_google_json)}, interactive=False)
    raise AssertionError("invalid service account JSON should fail")
except RuntimeError as exc:
    assert "client_email" in str(exc) and "token_uri" in str(exc)

window.store.add_key("Groq", "gsk_test_diagnostic_key")
key_id = window.store.data["providers"]["Groq"][0]["id"]
window._key_check_result("Groq", key_id, False, "网络检测失败：连接超时")
assert window.store.data["providers"]["Groq"][0]["status"] == "异常"
assert "连接超时" in window.key_table.item(0, 5).text()
window._key_check_result("Groq", key_id, False, "HTTP 401：Unauthorized")
assert window.store.data["providers"]["Groq"][0]["status"] == "失效"

rename_intake = Path(root) / "reels_rename_intake"
rename_intake.mkdir()
(rename_intake / "001.mp4").write_bytes(b"video")
window._open_folder_in_batch_rename(str(rename_intake))
assert window.pages.currentWidget() is window.rename_page
assert Path(window.rename_page.input.text()).resolve() == rename_intake.resolve()
assert "001.mp4" in window.rename_page.preview.toPlainText()
assert hasattr(window.dynamic_caption_page, "output_to_rename")
assert not hasattr(window.dynamic_caption_page, "group_resume")
assert window.dynamic_caption_page.group_trim_mode.currentText() == "智能混合边界（推荐）"
assert window.dynamic_caption_page.group_head_padding.value() == 80
assert window.dynamic_caption_page.group_tail_padding.value() == 120
assert window.dynamic_caption_page.group_silence_threshold.value() == -35
assert window.dynamic_caption_page.group_silence_min.value() == 180
assert window.dynamic_caption_page.fix_overlap_btn.text() == "修正重叠"
assert window.dynamic_caption_page.audio_fade_mode.currentText() == "直接加入（无淡入淡出）"

# 全部最终成品成功后删除分组合成中间目录；失败时必须保留供断点续接。
group_intermediate=Path(root)/"00_分组合成"
(group_intermediate/".group_merge_cache").mkdir(parents=True)
(group_intermediate/"01_去口气音合成.mp4").write_bytes(b"source"*400)
final_product=Path(root)/"01_动态文案.mp4"; final_product.write_bytes(b"final"*500)
page=window.dynamic_caption_page
page._pending_group_cleanup_dir=group_intermediate
page._batch_expected_count=1
page.group_merge_outputs=[str(group_intermediate/"01_去口气音合成.mp4")]
page.generated_records=[{"path":str(final_product),"original":"","chinese":""}]
assert page._cleanup_completed_group_intermediates(True) is True
assert not group_intermediate.exists() and final_product.is_file()

window._show_page(5)
window.show()
qt.processEvents()
window.grab().save("subtitle_layout_preview.png")
window._show_page(8)
qt.processEvents()
window.grab().save("pipeline_layout_preview.png")
window._show_page(3)
qt.processEvents()
window.grab().save("reels_layout_preview.png")
window.pages.setCurrentWidget(window.rename_page)
qt.processEvents()
window.grab().save("rename_layout_preview.png")
print("OK pages=11 auto=enabled fallback=local key_diagnostics=passed")
