import os
import builtins
import sys
import tempfile
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app as toolkit


class DummyStore:
    def candidates(self, provider):
        return [{"id": "local", "key": ""}]

    def mark_use(self, *args, **kwargs):
        pass


def result_for(source):
    name = Path(source).name
    return {"name": name, "original": f"original {name}", "chinese": f"中文 {name}",
            "srt": f"1\n00:00:00,000 --> 00:00:01,000\n{name}\n", "raw": {}}


root = Path(tempfile.mkdtemp(prefix="video_toolkit_resume_test_"))
files = []
for name in ("1.mp4", "2.mp4", "3.mp4"):
    path = root / name
    path.write_bytes(name.encode("ascii"))
    files.append(str(path))

# 字幕批处理：第一次在第 3 个文件失败，第二次只处理第 3 个文件。
checkpoint_dir = root / "subtitle_checkpoint"
first = toolkit.TranscribeWorker(DummyStore(), toolkit.LOCAL_PROVIDER, "small", files,
                                 str(checkpoint_dir), "auto", False, "ffmpeg", True)
first_calls = []

def first_process(source):
    first_calls.append(Path(source).name)
    if Path(source).name == "3.mp4":
        raise RuntimeError("simulated subtitle failure")
    result = result_for(source)
    first.result_ready.emit(result["name"], result["original"], result["chinese"], result["srt"])
    return result

first._process_one = first_process
first_status = {}
first.finished.connect(lambda ok, message: first_status.update(ok=ok, message=message))
first.run()
assert first_status["ok"] is False
assert first_calls == ["1.mp4", "2.mp4", "3.mp4"]

second = toolkit.TranscribeWorker(DummyStore(), toolkit.LOCAL_PROVIDER, "small", files,
                                  str(checkpoint_dir), "auto", False, "ffmpeg", True)
second_calls, emitted = [], []

def second_process(source):
    second_calls.append(Path(source).name)
    result = result_for(source)
    second.result_ready.emit(result["name"], result["original"], result["chinese"], result["srt"])
    return result

second._process_one = second_process
second.result_ready.connect(lambda name, *_: emitted.append(name))
second_status = {}
second.finished.connect(lambda ok, message: second_status.update(ok=ok, message=message))
second.run()
assert second_status["ok"] is True
assert second_calls == ["3.mp4"]
assert emitted == ["1.mp4", "2.mp4", "3.mp4"]

# Groq：第 2 段遇到额度错误后换密钥，必须复用第 1 段且不能重复创建 chunks。
groq_root = root / "groq"
groq_root.mkdir()
audio = groq_root / "audio.wav"
audio.write_bytes(b"RIFF-test")
groq_worker = toolkit.TranscribeWorker(DummyStore(), "Groq", "whisper-large-v3-turbo", [],
                                       str(groq_root / "task"), "auto", False, "ffmpeg", True)
original_run = toolkit.subprocess.run
original_post = toolkit.requests.post

class FakeProcess:
    returncode = 0
    stderr = ""
    stdout = "90.0\n"

def fake_run(command, *args, **kwargs):
    if "segment" in command:
        chunks = Path(command[-1]).parent
        (chunks / "chunk_000.wav").write_bytes(b"chunk0")
        (chunks / "chunk_001.wav").write_bytes(b"chunk1")
    return FakeProcess()

class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = "rate limited" if status >= 300 else ""
        self.headers = {}

    def json(self):
        return self._payload

post_calls = []
responses = [
    FakeResponse(200, {"text": "one", "segments": [{"start": 0, "end": 1, "text": "one"}]}),
    FakeResponse(429, {"error": {"message": "quota"}}),
    FakeResponse(200, {"text": "two", "segments": [{"start": 0, "end": 1, "text": "two"}]}),
]

def fake_post(*args, **kwargs):
    post_calls.append(kwargs.get("files", {}).get("file", ("",))[0])
    return responses.pop(0)

toolkit.subprocess.run = fake_run
toolkit.requests.post = fake_post
try:
    try:
        groq_worker._groq(audio, "key-1", groq_root)
        raise AssertionError("first Groq key should fail on the second chunk")
    except toolkit.ApiFailure as exc:
        assert exc.status == 429
    srt, plain, raw = groq_worker._groq(audio, "key-2", groq_root)
finally:
    toolkit.subprocess.run = original_run
    toolkit.requests.post = original_post
assert post_calls == ["chunk_000.wav", "chunk_001.wav", "chunk_001.wav"]
assert "one" in plain and "two" in plain and len(raw["chunks"]) == 2

# 本地模型：ONNX Runtime 缺失时必须自动关闭 VAD，而不是终止任务。
fake_faster_whisper = types.ModuleType("faster_whisper")
fake_ctranslate = types.ModuleType("ctranslate2")
fake_ctranslate.get_cuda_device_count = lambda: 0

class FakeSegment:
    start = 0.0
    end = 1.0
    text = " local result "

class FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, *args, **kwargs):
        assert kwargs["vad_filter"] is False
        return iter([FakeSegment()]), types.SimpleNamespace(language="en")

fake_faster_whisper.WhisperModel = FakeWhisperModel
saved_modules = {name: sys.modules.get(name) for name in ("faster_whisper", "ctranslate2")}
sys.modules["faster_whisper"] = fake_faster_whisper
sys.modules["ctranslate2"] = fake_ctranslate
original_import = builtins.__import__

def import_without_onnx(name, *args, **kwargs):
    if name == "onnxruntime":
        raise ImportError("simulated missing onnxruntime")
    return original_import(name, *args, **kwargs)

builtins.__import__ = import_without_onnx
local_worker = toolkit.TranscribeWorker(DummyStore(), toolkit.LOCAL_PROVIDER, "small", [],
                                        str(root / "local_task"), "auto", False, "ffmpeg", True)
try:
    local_srt, local_plain, _ = local_worker._local_whisper(Path(files[0]))
finally:
    builtins.__import__ = original_import
    for module_name, previous in saved_modules.items():
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
assert "local result" in local_plain and "00:00:00,000" in local_srt

# 流水线：字幕中途失败后，第二次不得重新剪辑，并从失败片段继续。
pipeline_output = root / "pipeline"
source = root / "source.mp4"
source.write_bytes(b"source")
first_pipeline = toolkit.PipelineWorker(
    DummyStore(), [str(source)], str(pipeline_output), 27, toolkit.LOCAL_PROVIDER,
    "small", "auto", "ffmpeg", "ZB", "20260719", "FF-PT", 1, 3, {}, True)
cut_calls = []

def fake_cut(clips_dir):
    cut_calls.append("cut")
    clips = []
    for number in (1, 2):
        path = clips_dir / f"001_{number:03d}.mp4"
        path.write_bytes(f"clip{number}".encode("ascii"))
        clips.append(path)
    return clips

first_pipeline._cut_sources = fake_cut
original_process_one = toolkit.TranscribeWorker._process_one
pipeline_calls = []

def failing_pipeline_process(worker, source_path):
    pipeline_calls.append(Path(source_path).name)
    if Path(source_path).name == "001_002.mp4":
        raise RuntimeError("simulated pipeline subtitle failure")
    return result_for(source_path)

toolkit.TranscribeWorker._process_one = failing_pipeline_process
first_pipeline_status = {}
first_pipeline.finished.connect(lambda ok, message: first_pipeline_status.update(ok=ok, message=message))
first_pipeline.run()
assert first_pipeline_status["ok"] is False
assert cut_calls == ["cut"] and pipeline_calls == ["001_001.mp4", "001_002.mp4"]

second_pipeline = toolkit.PipelineWorker(
    DummyStore(), [str(source)], str(pipeline_output), 27, toolkit.LOCAL_PROVIDER,
    "small", "auto", "ffmpeg", "ZB", "20260719", "FF-PT", 1, 3, {}, True)
second_pipeline._cut_sources = lambda *_: (_ for _ in ()).throw(AssertionError("cut stage ran again"))
pipeline_calls.clear()

def resumed_pipeline_process(worker, source_path):
    pipeline_calls.append(Path(source_path).name)
    return result_for(source_path)

toolkit.TranscribeWorker._process_one = resumed_pipeline_process
second_pipeline_status = {}
second_pipeline.finished.connect(lambda ok, message: second_pipeline_status.update(ok=ok, message=message))
try:
    second_pipeline.run()
finally:
    toolkit.TranscribeWorker._process_one = original_process_one
assert second_pipeline_status["ok"] is True
assert pipeline_calls == ["001_002.mp4"]
final_files = list(pipeline_output.glob("流水线_*/03_重命名成品/*.mp4"))
assert len(final_files) == 2

print("OK subtitle_resume=passed groq_chunk_resume=passed local_vad_fallback=passed pipeline_resume=passed")
