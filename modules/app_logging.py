from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path

from .platform_utils import app_data_dir, instance_id


_LOCK = threading.Lock()

# 日志落盘前脱敏，避免密钥/Token 明文写入磁盘（CodeQL py/clear-text-storage-sensitive-data）
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: <entire remainder>
    (re.compile(r"(?i)\b(authorization)\s*:\s*\S.*"), r"\1: ***"),
    # Bearer <token>
    (re.compile(r"(?i)\bbearer\s+[^\s,;\"']+"), "Bearer ***"),
    # api_key=xxx / password: xxx / token=xxx
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|"
            r"secret|password|passwd|pwd|x-api-key|x-goog-api-key|x-gladia-key|"
            r"xi-api-key)\b(\s*[:=]\s*)([^\s,;\"']+)"
        ),
        r"\1\2***",
    ),
    # JSON-ish "password": "..."
    (
        re.compile(
            r'(?i)("?(?:password|passwd|secret|token|api[_-]?key|access_token)"?\s*:\s*")'
            r'([^"]{4,})(")'
        ),
        r"\1***\3",
    ),
    # Common API key prefixes
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\bgsk_[A-Za-z0-9_\-]{8,}"), "gsk_***"),
    (re.compile(r"\bxai-[A-Za-z0-9_\-]{8,}"), "xai-***"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "AIza***"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "jwt-***"),
]


def redact_sensitive_text(message: object) -> str:
    """返回脱敏后的日志文本（不保留原始密钥内容）。"""
    text = str(message or "")
    if not text:
        return ""
    redacted = text
    for pattern, repl in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


def app_log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_log_path() -> Path:
    """Per-instance log so multi-open windows do not fight over one file."""
    return app_log_dir() / f"video_toolkit_{instance_id()}.log"


def write_app_log(message: object, level: str = "INFO", source: str = "应用") -> None:
    # 仅落盘脱敏后的副本，不把原始 message 写入文件
    safe_text = redact_sensitive_text(message).strip()
    if not safe_text:
        return
    try:
        path = app_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] [{source}] {safe_text}\n"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def read_app_log() -> str:
    path = app_log_path()
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else "当前还没有软件运行日志。"
    except OSError as exc:
        return f"无法读取软件日志：{exc}"
