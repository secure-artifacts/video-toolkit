import os
import tempfile
from pathlib import Path

root = tempfile.mkdtemp(prefix="video_toolkit_test_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = root
os.environ["LOCALAPPDATA"] = root

from PySide6.QtWidgets import QApplication
import app as toolkit

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

assert window.pages.count() == 9
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
assert window.subfolder_combo is not None
window.smartcut_page.add_paths([str(media_root.parent)])
assert window.smartcut_page.files.count() == 1
window.screenshot_page.add_local_paths([str(media_root.parent)])
assert "2.mp4" in window.screenshot_page.url_input.toPlainText()
assert "10.mp3" not in window.screenshot_page.url_input.toPlainText()
window.watermark_page.add_dropped_paths([str(media_root.parent)])
assert len(window.watermark_page.files) == 1
window.rename_page.set_input_folder(str(media_root))
assert window.rename_page.input.text() == str(media_root)

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
assert "上传 2 个重命名成品" in cloud_summary and "/folders/" in folder_url

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

window._show_page(5)
window.show()
qt.processEvents()
window.grab().save("subtitle_layout_preview.png")
window._show_page(8)
qt.processEvents()
window.grab().save("pipeline_layout_preview.png")
print("OK pages=9 auto=enabled fallback=local key_diagnostics=passed")
