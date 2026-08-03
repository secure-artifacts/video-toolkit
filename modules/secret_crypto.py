"""At-rest protection for API keys.

Disk layout:
  - config.json  : never contains API key material (empty placeholder only)
  - secrets.vault: Fernet ciphertext of {provider:id -> key}

Windows: Fernet master key is wrapped with DPAPI (current user).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .platform_utils import app_data_dir

_FERNET = None
_VAULT_NAME = "secrets.vault"
_KEY_BLOB_NAME = ".config_secret.key"


def vault_path() -> Path:
    return app_data_dir() / _VAULT_NAME


def _key_blob_path() -> Path:
    return app_data_dir() / _KEY_BLOB_NAME


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
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
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
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


def _vault_key(provider: str, key_id: str) -> str:
    return f"{provider}:{key_id}"


def extract_and_strip_keys(data: dict) -> dict:
    """Return {vault_key: plaintext} and blank every providers[*].key in a deep copy.

    The returned config copy is safe for JSON disk write (no secret values).
    """
    import copy

    payload = copy.deepcopy(data)
    vault: dict[str, str] = {}
    providers = payload.get("providers") or {}
    if isinstance(providers, dict):
        for provider, items in providers.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                kid = str(item.get("id") or "")
                secret = str(item.get("key") or "")
                if kid and secret:
                    vault[_vault_key(str(provider), kid)] = secret
                # Clear before any file write so clear-text never hits the disk path.
                item["key"] = ""
    # Legacy inline ciphertext (vtenc1:...) if any — drop from config JSON entirely
    payload.pop("_secrets_sealed", None)
    return payload, vault


def restore_keys_from_vault(data: dict, vault: dict[str, str] | None = None) -> dict:
    """Fill providers[*].key from vault (or legacy inline sealed/plain values)."""
    if vault is None:
        vault = load_vault()
    providers = data.get("providers") or {}
    if not isinstance(providers, dict):
        return data
    for provider, items in providers.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            kid = str(item.get("id") or "")
            current = str(item.get("key") or "")
            if kid:
                from_vault = vault.get(_vault_key(str(provider), kid), "")
                if from_vault:
                    item["key"] = from_vault
                    continue
            # Legacy: key still embedded (plain or old vtenc1:)
            if current.startswith("vtenc1:"):
                item["key"] = _unseal_legacy(current)
            # else keep current (plain legacy) until next save migrates to vault
    return data


def _unseal_legacy(value: str) -> str:
    prefix = "vtenc1:"
    if not value.startswith(prefix):
        return value
    try:
        return _fernet().decrypt(value[len(prefix) :].encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def save_vault(vault: dict[str, str]) -> None:
    """Encrypt and write the secret vault (binary). No clear-text on disk."""
    path = vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(vault, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Cryptographic sealing — ciphertext only is written.
    blob = _fernet().encrypt(raw)
    path.write_bytes(blob)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_vault() -> dict[str, str]:
    path = vault_path()
    if not path.is_file():
        return {}
    try:
        plain = _fernet().decrypt(path.read_bytes())
        data = json.loads(plain.decode("utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except Exception:
        return {}
    return {}


def migrate_inline_secrets_to_vault(data: dict) -> dict:
    """If config still has inline keys, rebuild vault and strip them from the dict."""
    payload, vault = extract_and_strip_keys(data)
    # Also pull any values already restored in memory that extract saw
    if vault:
        # Merge with existing vault so we do not drop other providers
        existing = load_vault()
        existing.update(vault)
        save_vault(existing)
    # Restore into memory copy for the running process
    return restore_keys_from_vault(payload, load_vault() if vault else load_vault())
