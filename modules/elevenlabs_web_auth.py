"""ElevenLabs 网页会话（Cookie / Authorization / 网页侧 xi-api-key）多账户支持。

与 VideoKit 思路一致：
- 用户用浏览器登录自己的账号后，把 Cookie（及可选 Authorization / xi-api-key）粘贴进本软件；
- 凭证加密存入密钥库，之后在软件内 TTS，直接扣该账号角色点数，不必每次开浏览器；
- 可添加多个网页会话 + 多个 sk_ API Key，统一轮询。

注意：使用的是你自己账号的登录态/免费点数，请遵守 ElevenLabs 服务条款；
会话过期后需重新粘贴 Cookie。
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

WEB_KIND = "web"
API_KIND = "api"
WEB_KEY_PREFIX = "ELWEB1:"

# 与 VideoKit electron/services/elevenlabs.js 对齐的浏览器头
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 网页 Network 里常见 api.us.elevenlabs.io；VideoKit 默认 api.elevenlabs.io
API_HOSTS = (
    "https://api.us.elevenlabs.io",
    "https://api.elevenlabs.io",
)

# VideoKit 默认模型；免费档探测时也会尝试更轻量模型
DEFAULT_TTS_MODELS = (
    "eleven_multilingual_v2",
    "eleven_turbo_v2_5",
    "eleven_flash_v2_5",
)


def _api_url(path: str, host: str | None = None) -> str:
    path = path if str(path).startswith("/") else f"/{path}"
    base = (host or API_HOSTS[0]).rstrip("/")
    return f"{base}{path}"


def _friendly_api_error(status: int, body: str) -> str:
    text = (body or "")[:400]
    lower = text.lower()
    if "detected_unusual_activity" in lower or "free tier access has been disabled" in lower:
        return (
            f"HTTP {status}: ElevenLabs 判定该凭证对应账号「异常活动」，已禁用免费档 API。\n"
            "注意：网页 Balance 仍可能显示 10000 credits，但 TTS API 会被拒绝。\n"
            "处理：\n"
            "1) 密钥管理里删除旧会话，重新从浏览器 Network 复制当前登录账号的 xi-api-key\n"
            "2) 确认浏览器与软件是同一 Workspace（Free plan）\n"
            "3) 关闭 VPN/代理后换干净网络再登录\n"
            "4) 或升级付费 / 换一个未触发风控的账号\n"
            f"原始信息：{text}"
        )
    if status in (401, 403):
        return (
            f"HTTP {status}: 鉴权失败。\n"
            "请确认粘贴的是 api.us.elevenlabs.io / api.elevenlabs.io 请求头里的 "
            "xi-api-key 或 Authorization，且与当前网页登录账号一致。\n"
            f"详情：{text}"
        )
    return f"HTTP {status}: {text}"


def _request_json(method: str, path: str, headers: dict, *,
                  json_body=None, timeout: float = 40.0) -> tuple[int, Any, str]:
    """依次尝试 API_HOSTS，返回 (status, json_or_none, raw_text, host_used) 的前三项 + host。"""
    last_status, last_text, last_host = 0, "", API_HOSTS[0]
    for host in API_HOSTS:
        url = _api_url(path, host)
        try:
            resp = requests.request(
                method, url, headers=headers, json=json_body, timeout=timeout,
            )
            last_status, last_text, last_host = resp.status_code, (resp.text or ""), host
            # 区域不对时可能 404，继续试下一 host
            if resp.status_code == 404 and host != API_HOSTS[-1]:
                continue
            data = None
            if resp.content:
                try:
                    data = resp.json()
                except Exception:
                    data = None
            return resp.status_code, data, resp.text or "", host
        except requests.RequestException as exc:
            last_status, last_text = 0, str(exc)
            continue
    return last_status, None, last_text, last_host


def is_web_secret(secret: str) -> bool:
    value = str(secret or "").strip()
    if value.startswith(WEB_KEY_PREFIX):
        return True
    if value.startswith("{") and '"kind"' in value and WEB_KIND in value:
        return True
    return False


def pack_web_session(
    *,
    cookie: str,
    authorization: str = "",
    xi_api_key: str = "",
    label: str = "",
) -> str:
    """整理用户粘贴内容。支持：

    1) 标准 Cookie 头：``a=1; b=2``
    2) Chrome Application 导出的「JSON 对象用分号拼接」
    3) 粘贴整段 Network 请求头文本（自动抽出 Cookie / Authorization / xi-api-key）
    """
    parsed = parse_user_paste(
        cookie_text=cookie,
        authorization=authorization,
        xi_api_key=xi_api_key,
    )
    if not parsed["cookie"] and not parsed["authorization"] and not parsed["xiApiKey"]:
        raise ValueError(
            "未能识别可用凭证。\n"
            "请不要只导出 Application→Cookies 的 JSON 列表（多数是统计 Cookie）。\n"
            "推荐：F12→Network→点开任意 api.elevenlabs.io 请求→Request Headers，复制：\n"
            "• xi-api-key（最稳），或\n"
            "• Authorization: Bearer …，或\n"
            "• Cookie 整行（需含 fern_token 等登录态）"
        )
    # API 至少需要 Authorization 或 xi-api-key；仅有分析类 Cookie 会 401
    if not parsed["authorization"] and not parsed["xiApiKey"]:
        # 尝试从 cookie 字符串再抽一次 fern_token
        auto_auth = _auth_from_cookie_header(parsed["cookie"])
        if auto_auth:
            parsed["authorization"] = auto_auth
    if not parsed["authorization"] and not parsed["xiApiKey"]:
        raise ValueError(
            "Cookie 里没有登录凭证（缺少 fern_token / Authorization / xi-api-key）。\n"
            "请先在浏览器登录 elevenlabs.io，然后到 Network 复制带鉴权的请求头，\n"
            "不要只复制统计类 Cookie（_ga、CookieConsent 等）。"
        )
    payload = {
        "kind": WEB_KIND,
        "cookie": parsed["cookie"],
        "authorization": parsed["authorization"],
        "xiApiKey": parsed["xiApiKey"],
        "label": (label or "").strip() or "网页会话",
    }
    return WEB_KEY_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def unpack_secret(secret: str) -> dict[str, Any]:
    """解析密钥库中的 ElevenLabs 凭证。

    返回：
      kind: api | web
      api_key / cookie / authorization / xiApiKey / label
    """
    value = str(secret or "").strip()
    if not value:
        return {"kind": API_KIND, "api_key": "", "label": ""}
    if value.startswith(WEB_KEY_PREFIX):
        raw = value[len(WEB_KEY_PREFIX) :]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"网页会话数据损坏：{exc}") from exc
        return {
            "kind": WEB_KIND,
            "cookie": str(data.get("cookie") or ""),
            "authorization": str(data.get("authorization") or ""),
            "xiApiKey": str(data.get("xiApiKey") or data.get("xi_api_key") or ""),
            "label": str(data.get("label") or "网页会话"),
            "api_key": "",
        }
    if value.startswith("{") and "kind" in value:
        try:
            data = json.loads(value)
            if data.get("kind") == WEB_KIND:
                return {
                    "kind": WEB_KIND,
                    "cookie": str(data.get("cookie") or ""),
                    "authorization": str(data.get("authorization") or ""),
                    "xiApiKey": str(data.get("xiApiKey") or ""),
                    "label": str(data.get("label") or "网页会话"),
                    "api_key": "",
                }
        except json.JSONDecodeError:
            pass
    return {"kind": API_KIND, "api_key": value, "label": "", "cookie": "",
            "authorization": "", "xiApiKey": ""}


def display_secret(secret: str) -> str:
    info = unpack_secret(secret)
    if info["kind"] == WEB_KIND:
        label = info.get("label") or "网页会话"
        cookie = info.get("cookie") or ""
        tail = ""
        if cookie:
            # 只显示尾部片段，不泄露完整 Cookie
            parts = [p for p in cookie.split(";") if "=" in p]
            tail = (parts[-1].split("=", 1)[-1][-6:] if parts else cookie[-6:])
        return f"网页·{label}" + (f"…{tail}" if tail else "")
    key = info.get("api_key") or ""
    if len(key) <= 9:
        return key
    return f"{key[:4]}…{key[-4:]}"


def parse_user_paste(
    *,
    cookie_text: str = "",
    authorization: str = "",
    xi_api_key: str = "",
) -> dict[str, str]:
    """从用户粘贴内容提取 cookie / authorization / xiApiKey。"""
    raw = str(cookie_text or "").strip()
    auth = (authorization or "").strip()
    xi = (xi_api_key or "").strip()

    # 整段请求头粘贴
    if raw and ("\n" in raw or "cookie:" in raw.lower() or "authorization:" in raw.lower()
                or "xi-api-key:" in raw.lower()):
        for line in raw.replace("\r", "").split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            key = name.strip().lower()
            value = value.strip()
            if key == "cookie" and not raw.startswith("{"):
                # 下面再用 _normalize_cookie 处理 value
                raw = value
            elif key == "authorization" and not auth:
                auth = value
            elif key in ("xi-api-key", "x-api-key") and not xi:
                xi = value

    cookie_header = _normalize_cookie(raw)

    # 从 cookie 名值中再抽鉴权
    if not auth:
        auth = _auth_from_cookie_header(cookie_header)
    if not xi:
        xi = _xi_from_cookie_header(cookie_header)

    # Authorization 规范化
    if auth and not auth.lower().startswith("bearer ") and auth.count(".") >= 2:
        # JWT 裸值 → Bearer
        auth = f"Bearer {auth}"
    if auth.lower().startswith("bearer bearer "):
        auth = "Bearer " + auth[14:].strip()

    # xi-api-key 有时用户粘了整行
    xi = re.sub(r"^(xi-api-key\s*:)\s*", "", xi, flags=re.I).strip()

    return {
        "cookie": cookie_header,
        "authorization": auth,
        "xiApiKey": xi,
    }


def _normalize_cookie(cookie: str) -> str:
    """把各种粘贴格式统一成 HTTP Cookie 头：name=value; name2=value2"""
    text = str(cookie or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(cookie\s*:)\s*", "", text, flags=re.I)
    text = re.sub(r"[\r\n]+", " ", text).strip()

    # Chrome Application 导出：{...json...};{...json...} 或 [{...},{...}]
    if '"name"' in text and '"value"' in text and ("{" in text):
        pairs = _cookie_pairs_from_devtools_json(text)
        if pairs:
            return "; ".join(f"{n}={v}" for n, v in pairs)

    # 已是 name=value; ...
    if "=" in text and not text.lstrip().startswith("{"):
        return text
    return text


def _cookie_pairs_from_devtools_json(text: str) -> list[tuple[str, str]]:
    """解析 DevTools 导出的 Cookie JSON（数组或分号拼接的对象）。"""
    text = text.strip()
    objects: list[dict] = []
    # 数组
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                objects = [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            objects = []
    if not objects:
        # 分号拼接的多个 JSON 对象
        chunks = re.split(r"\}\s*;\s*\{", text)
        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk.startswith("{"):
                chunk = "{" + chunk
            if not chunk.endswith("}"):
                chunk = chunk + "}"
            try:
                obj = json.loads(chunk)
                if isinstance(obj, dict):
                    objects.append(obj)
            except json.JSONDecodeError:
                continue
    pairs: list[tuple[str, str]] = []
    for obj in objects:
        name = str(obj.get("name") or "").strip()
        value = obj.get("value")
        if name and value is not None:
            pairs.append((name, str(value)))
    return pairs


def _cookie_map(cookie_header: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in (cookie_header or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        result[name.strip()] = value.strip()
    return result


def _auth_from_cookie_header(cookie_header: str) -> str:
    """从 Cookie 中提取可用的 Authorization。"""
    cmap = _cookie_map(cookie_header)
    # ElevenLabs 网页登录常见：fern_token = JWT
    for name in ("fern_token", "token", "access_token", "id_token", "session_token"):
        value = cmap.get(name) or ""
        if value.count(".") >= 2 and len(value) >= 36:
            return f"Bearer {value}"
    return ""


def _xi_from_cookie_header(cookie_header: str) -> str:
    cmap = _cookie_map(cookie_header)
    for name in ("xi-api-key", "xi_api_key", "api_key"):
        value = cmap.get(name) or ""
        if value.startswith("sk_") or len(value) > 20:
            return value
    return ""


def build_auth_headers(secret: str) -> dict[str, str]:
    info = unpack_secret(secret)
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json",
    }
    if info["kind"] == WEB_KIND:
        cookie = info.get("cookie") or ""
        auth = (info.get("authorization") or "").strip()
        xi = (info.get("xiApiKey") or "").strip()
        if not auth:
            auth = _auth_from_cookie_header(cookie)
        if not xi:
            xi = _xi_from_cookie_header(cookie)
        if xi:
            headers["xi-api-key"] = xi
        if auth:
            if not auth.lower().startswith("bearer ") and auth.count(".") >= 2:
                auth = f"Bearer {auth}"
            headers["Authorization"] = auth
        if cookie:
            headers["Cookie"] = cookie
        # 与 VideoKit 完全一致（Referer 为站点根路径）
        headers["Origin"] = "https://elevenlabs.io"
        headers["Referer"] = "https://elevenlabs.io/"
        if "xi-api-key" not in headers and "Authorization" not in headers:
            raise ValueError(
                "会话里没有 xi-api-key / Authorization（API 拒绝仅 Cookie）。\n"
                "请从 Network 请求头复制 xi-api-key 或 Authorization: Bearer …"
            )
        return headers
    headers["xi-api-key"] = info.get("api_key") or secret
    return headers


def verify_session(secret: str, timeout: float = 25.0) -> tuple[bool, str, dict]:
    """验证凭证并返回额度摘要。

    成功：(True, 说明, {usage, limit, remaining, email?})
    """
    try:
        headers = build_auth_headers(secret)
    except ValueError as exc:
        return False, str(exc), {}
    try:
        status, data, raw, host = _request_json(
            "GET", "/v1/user/subscription", headers, timeout=timeout,
        )
        if status >= 400 or not isinstance(data, dict):
            status2, data2, raw2, host2 = _request_json(
                "GET", "/v1/user", headers, timeout=timeout,
            )
            if status2 >= 400:
                return False, _friendly_api_error(status or status2, raw or raw2), {}
            email = ""
            if isinstance(data2, dict):
                email = str(data2.get("email") or "")
            return True, f"凭证有效（主机 {host2}，未能读到额度明细）" + (
                f" · {email}" if email else ""
            ), {"usage": 0, "limit": 0, "remaining": 0, "email": email, "host": host2}

        usage = int(data.get("character_count") or data.get("characterCount") or 0)
        limit = int(data.get("character_limit") or data.get("characterLimit") or 0)
        # 新 UI credits 字段兼容
        if limit <= 0:
            limit = int(data.get("credits") or data.get("credit_limit") or 0)
        remaining = max(0, limit - usage)
        if "remaining" in data:
            try:
                remaining = max(0, int(data.get("remaining") or remaining))
            except Exception:
                pass
        tier = str(data.get("tier") or data.get("status") or data.get("plan") or "")
        msg = f"有效 · 点数 {usage}/{limit}（剩余 {remaining}）· {host.replace('https://', '')}"
        if tier:
            msg += f" · {tier}"
        # 订阅接口成功 ≠ TTS 可用：免费档可能被 unusual_activity 关掉 API
        tts_ok, tts_detail = probe_tts_allowed(secret, timeout=min(45.0, timeout + 20))
        quota = {
            "usage": usage, "limit": limit, "remaining": remaining,
            "tier": tier, "host": host, "tts_ok": tts_ok, "tts_detail": tts_detail,
        }
        if tts_ok:
            msg += " · TTS可用"
            return True, msg, quota
        # 查询成功但 TTS 被拒：仍标有效（能登录），但状态里写清
        msg += " · ⚠️TTS不可用(免费API被风控)"
        return True, msg, quota
    except requests.RequestException as exc:
        return False, f"网络失败：{exc}", {}


def probe_tts_allowed(secret: str, timeout: float = 40.0) -> tuple[bool, str]:
    """用极短文本探测 TTS 是否被免费档风控拦截。

    不下载完整长音频；失败时返回对方 status 文案。
    """
    try:
        headers = build_auth_headers(secret)
    except ValueError as exc:
        return False, str(exc)
    # 先取一个本账号音色，避免硬编码 ID 在某些 workspace 不可用
    voice_id = ""
    try:
        status, data, raw, _host = _request_json(
            "GET", "/v1/voices", headers, timeout=min(25.0, timeout),
        )
        if status < 400 and isinstance(data, dict):
            for item in (data.get("voices") or []):
                if isinstance(item, dict) and item.get("voice_id"):
                    voice_id = str(item["voice_id"])
                    break
    except Exception:
        pass
    if not voice_id:
        # 官方预置示例 ID（Rachel）；仅作探测
        voice_id = "21m00Tcm4TlvDq8ikWAM"
    payload = {
        "text": "Hi",
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    last = ""
    for host in API_HOSTS:
        try:
            h = dict(headers)
            h["Content-Type"] = "application/json"
            h["Accept"] = "audio/mpeg"
            resp = requests.post(
                _api_url(f"/v1/text-to-speech/{voice_id}", host),
                headers=h, json=payload, timeout=timeout,
            )
            if resp.status_code < 400 and len(resp.content) >= 256:
                return True, f"TTS探测成功（{host.replace('https://', '')}）"
            last = (resp.text or "")[:280]
            if "detected_unusual_activity" in last or "Free Tier access has been disabled" in last.lower():
                return False, last
            if resp.status_code in (401, 403) and host != API_HOSTS[-1]:
                continue
        except requests.RequestException as exc:
            last = str(exc)
            continue
    return False, last or "TTS 探测失败"


def list_voices(secret: str, timeout: float = 40.0) -> list[dict]:
    """GET /v1/voices → [{voice_id, name, category, labels}, ...]"""
    headers = build_auth_headers(secret)
    headers["Accept"] = "application/json"
    status, data, raw, host = _request_json(
        "GET", "/v1/voices", headers, timeout=timeout,
    )
    if status >= 400 or not isinstance(data, dict):
        raise RuntimeError(_friendly_api_error(status, raw or f"host={host}"))
    voices = data.get("voices") or []
    result = []
    for item in voices:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("voice_id") or item.get("voiceId") or "").strip()
        if not vid:
            continue
        name = str(item.get("name") or vid).strip()
        category = str(item.get("category") or item.get("voice_category") or "").strip()
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        desc_bits = []
        if category:
            desc_bits.append(category)
        for key in ("accent", "gender", "age", "use_case", "description"):
            val = labels.get(key) if labels else None
            if val:
                desc_bits.append(str(val))
        result.append({
            "voice_id": vid,
            "name": name,
            "category": category,
            "label": "｜".join(desc_bits),
            "display": f"{vid}｜{name}" + (f"（{' · '.join(desc_bits)}）" if desc_bits else ""),
        })
    result.sort(key=lambda x: (x.get("name") or "").casefold())
    return result


def tts_request(
    secret: str,
    voice_id: str,
    text: str,
    *,
    model_id: str = "eleven_multilingual_v2",
    timeout: float = 180.0,
) -> tuple[bytes, dict | None]:
    """发起 TTS；返回 (audio_bytes, alignment_or_None)。

    与 VideoKit 相同：
    - 网页会话 = Cookie + Authorization +（常有）网页注入的 xi-api-key
    - 仍请求官方 /v1/text-to-speech（会扣账号 character credits）
    - 并不是「绕过 Key、只在浏览器扣点数」的另一条通道

    自动尝试 api.us / api 主机，以及多种 model。
    """
    headers = build_auth_headers(secret)
    models = [model_id] + [m for m in DEFAULT_TTS_MODELS if m != model_id]
    last_err = ""
    unusual = False

    for host in API_HOSTS:
        for mid in models:
            payload = {
                "text": text,
                "model_id": mid,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            # 1) with-timestamps（我们多这一步，方便字幕）
            ts_headers = dict(headers)
            ts_headers["Content-Type"] = "application/json"
            ts_headers["Accept"] = "application/json"
            try:
                resp = requests.post(
                    _api_url(f"/v1/text-to-speech/{voice_id}/with-timestamps", host),
                    headers=ts_headers, json=payload, timeout=timeout,
                )
            except requests.RequestException as exc:
                last_err = str(exc)
                continue
            if resp.status_code < 400:
                try:
                    data = resp.json()
                    b64 = data.get("audio_base64") or data.get("audio")
                    if b64:
                        import base64
                        audio = base64.b64decode(b64)
                        if len(audio) >= 256:
                            alignment = data.get("alignment") or data.get("normalized_alignment")
                            return audio, alignment if isinstance(alignment, dict) else None
                except (ValueError, TypeError, KeyError):
                    pass
            body_text = resp.text or ""
            if "detected_unusual_activity" in body_text or "Free Tier access has been disabled" in body_text:
                unusual = True
                last_err = _friendly_api_error(resp.status_code, body_text)
                # 风控是账号级，换 host/model 通常无效，仍试一轮后统一抛出
                continue

            # 2) VideoKit 同款：plain TTS + output_format 查询参数
            plain_headers = dict(headers)
            plain_headers["Content-Type"] = "application/json"
            plain_headers["Accept"] = "audio/mpeg"
            try:
                plain = requests.post(
                    _api_url(
                        f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                        host,
                    ),
                    headers=plain_headers, json=payload, timeout=timeout,
                )
            except requests.RequestException as exc:
                last_err = str(exc)
                continue
            if plain.status_code < 400 and len(plain.content) >= 256:
                return plain.content, None
            last_err = _friendly_api_error(plain.status_code, plain.text or "")
            if "detected_unusual_activity" in (plain.text or "") or (
                "Free Tier access has been disabled" in (plain.text or "")
            ):
                unusual = True

    if unusual:
        raise RuntimeError(
            (last_err or "免费档 API 被风控")
            + "\n\n说明：开源 VideoKit 也是调同一套官方 TTS API 扣点数，"
            "并不是「不用 Key、只靠网页点数」的另一条通道。"
            "它同样需要 Cookie/Authorization/网页 xi-api-key。"
            "若同一账号在 VideoKit 能转、这里不能：请把 VideoKit 或浏览器"
            "成功 TTS 那次请求的 xi-api-key 原样贴进本软件（删掉旧会话后重加）。"
            "若两边都 401 unusual_activity：只能换号/升级/关 VPN 后重新注册绑定。"
        )
    raise RuntimeError(last_err or "TTS 请求失败（所有区域主机/模型均不可用）")
