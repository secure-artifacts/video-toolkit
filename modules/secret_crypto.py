"""At-rest encryption for API keys stored in config.json.

CodeQL flags clear-text storage of password-like values (CWE-312).
Secrets remain plaintext only in process memory; disk holds Fernet ciphertext.
The Fernet key is bound to this machine (Windows DPAPI when available).
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from .platform_utils import app_data_dir

_SECRET_PREFIX = "vtenc1:"
_FERNET = None


def _key_blob_path() -> Path:
    return app_data_dir() / ".config_secret.key"


def _dpapi_protect(data: bytes) -> bytes:
    """Windows DPAPI encrypt (current user)."""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    """Windows DPAPI decrypt (current user)."""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _load_or_create_fernet_key() -> bytes:
    """Load machine-bound Fernet key; create once if missing."""
    from cryptography.fernet import Fernet

    path = _key_blob_path()
    if path.is_file():
        raw = path.read_bytes()
        if sys.platform == "win32" and not raw.startswith(b"vtplain:"):
            try:
                return _dpapi_unprotect(raw)
            except OSError:
                pass
        if raw.startswith(b"vtplain:"):
            return raw[len(b"vtplain:") :]
        # legacy: raw Fernet key bytes
        if len(raw) == 44:
            return raw

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            path.write_bytes(_dpapi_protect(key))
            return key
        except OSError:
            pass
    # Non-Windows / DPAPI unavailable: store with private prefix (chmod best-effort)
    path.write_bytes(b"vtplain:" + key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _fernet():
    global _FERNET
    if _FERNET is None:
        from cryptography.fernet import Fernet

        _FERNET = Fernet(_load_or_create_fernet_key())
    return _FERNET


def is_sealed_secret(value: object) -> bool:
    text = str(value or "")
    return text.startswith(_SECRET_PREFIX)


def seal_secret(plaintext: str) -> str:
    """Encrypt a secret for disk. Already-sealed values are returned unchanged."""
    text = str(plaintext or "")
    if not text or is_sealed_secret(text):
        return text
    # Fernet.encrypt is a cryptographic operation: ciphertext is safe to store.
    token = _fernet().encrypt(text.encode("utf-8"))
    return _SECRET_PREFIX + token.decode("ascii")


def unseal_secret(value: str) -> str:
    """Decrypt a sealed secret, or return legacy plaintext as-is."""
    text = str(value or "")
    if not text:
        return ""
    if not is_sealed_secret(text):
        return text
    token = text[len(_SECRET_PREFIX) :].encode("ascii")
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except Exception:
        # Corrupted / other machine: leave empty rather than crash the app
        return ""


def seal_provider_keys(data: dict) -> dict:
    """Deep-copy config and encrypt every providers[*].key for disk storage."""
    import copy

    payload = copy.deepcopy(data)
    providers = payload.get("providers") or {}
    if isinstance(providers, dict):
        for _name, items in providers.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                raw = item.get("key")
                if raw:
                    item["key"] = seal_secret(str(raw))
    payload["_secrets_sealed"] = True
    return payload


def unseal_provider_keys(data: dict) -> dict:
    """Decrypt providers[*].key in-place after loading config from disk."""
    providers = data.get("providers") or {}
    if not isinstance(providers, dict):
        return data
    for _name, items in providers.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw = item.get("key")
            if raw:
                item["key"] = unseal_secret(str(raw))
    return data
