import base64
import os
import time

import httpx
from Crypto.Cipher import AES

from ..db import connect

SCOPES = {
    "schedule_import": {"label": "课表 Excel 解析", "prefix": "AI", "fallback": None,
                        "timeout": 75, "max_tokens": 4000, "thinking": False},
    "adjustment_vision": {"label": "调课通知视觉识别", "prefix": "VISION", "fallback": "schedule_import",
                          "timeout": 45, "max_tokens": 2000, "thinking": False},
    "agent": {"label": "课表助手主模型", "prefix": "AGENT", "fallback": "schedule_import",
              "timeout": 15, "max_tokens": 300, "thinking": False},
    "polish": {"label": "回答润色与闲聊", "prefix": "POLISH", "fallback": "agent",
               "timeout": 6, "max_tokens": 400, "thinking": False},
}


def _key() -> bytes:
    raw = os.getenv("LLM_CONFIG_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError("缺少 LLM_CONFIG_ENCRYPTION_KEY")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError as error:
        raise RuntimeError("LLM_CONFIG_ENCRYPTION_KEY 不是合法 Base64") from error
    if len(key) != 32:
        raise RuntimeError("LLM_CONFIG_ENCRYPTION_KEY 解码后必须为 32 字节")
    return key


def encrypt_key(value: str) -> str:
    if not value:
        return ""
    cipher = AES.new(_key(), AES.MODE_GCM)
    encrypted, tag = cipher.encrypt_and_digest(value.encode())
    return base64.urlsafe_b64encode(cipher.nonce + tag + encrypted).decode()


def decrypt_key(value: str) -> str:
    if not value:
        return ""
    try:
        payload = base64.urlsafe_b64decode(value)
        return AES.new(_key(), AES.MODE_GCM, nonce=payload[:16]).decrypt_and_verify(payload[32:], payload[16:32]).decode()
    except (ValueError, UnicodeDecodeError) as error:
        raise RuntimeError("LLM API Key 无法解密") from error


def _env_config(scope: str) -> dict:
    meta = SCOPES[scope]
    prefix = meta["prefix"]
    fallback = _env_config(meta["fallback"]) if meta["fallback"] else {}
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip().rstrip("/") or fallback.get("base_url", "")
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip().strip('"').strip("'") or fallback.get("api_key", "")
    model = os.getenv(f"{prefix}_MODEL", "").strip() or fallback.get("model", "")
    timeout = float(os.getenv(f"{prefix}_TIMEOUT_SECONDS", str(meta["timeout"])))
    max_tokens = int(os.getenv(f"{prefix}_MAX_OUTPUT_TOKENS", str(meta["max_tokens"])))
    thinking = os.getenv(f"{prefix}_ENABLE_THINKING", str(meta["thinking"])).lower() == "true"
    return {"scope": scope, "label": meta["label"], "base_url": base_url, "api_key": api_key,
            "model": model, "timeout_seconds": timeout, "max_tokens": max_tokens,
            "enable_thinking": thinking, "source": "environment"}


def get_llm_config(scope: str) -> dict:
    if scope not in SCOPES:
        raise ValueError("未知 LLM 配置分组")
    fallback = _env_config(scope)
    try:
        with connect() as db:
            row = db.execute("SELECT * FROM llm_configs WHERE scope=%s", (scope,)).fetchone()
    except Exception:
        row = None
    if not row:
        return fallback
    return {"scope": scope, "label": SCOPES[scope]["label"], "base_url": row["base_url"].rstrip("/"),
            "api_key": decrypt_key(row["api_key_encrypted"]), "model": row["model"],
            "timeout_seconds": float(row["timeout_seconds"]), "max_tokens": int(row["max_tokens"]),
            "enable_thinking": bool(row["enable_thinking"]), "source": "database"}


def public_config(scope: str) -> dict:
    value = get_llm_config(scope)
    key = value.pop("api_key", "")
    value["api_key_configured"] = bool(key)
    value["api_key_hint"] = f"••••{key[-4:]}" if len(key) >= 4 else ("••••" if key else "")
    return value


def save_llm_config(scope: str, values: dict, api_key: str | None, clear_api_key: bool = False) -> dict:
    current = get_llm_config(scope)
    key = "" if clear_api_key else (api_key.strip() if api_key is not None else current["api_key"])
    encrypted = encrypt_key(key)
    with connect() as db:
        db.execute("""INSERT INTO llm_configs(scope,base_url,api_key_encrypted,model,timeout_seconds,max_tokens,enable_thinking)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scope) DO UPDATE SET base_url=EXCLUDED.base_url,
            api_key_encrypted=EXCLUDED.api_key_encrypted,model=EXCLUDED.model,
            timeout_seconds=EXCLUDED.timeout_seconds,max_tokens=EXCLUDED.max_tokens,
            enable_thinking=EXCLUDED.enable_thinking,updated_at=CURRENT_TIMESTAMP""",
            (scope, values["base_url"].strip().rstrip("/"), encrypted, values["model"].strip(),
             values["timeout_seconds"], values["max_tokens"], values["enable_thinking"]))
    return public_config(scope)


def reset_llm_config(scope: str) -> dict:
    if scope not in SCOPES:
        raise ValueError("未知 LLM 配置分组")
    with connect() as db:
        db.execute("DELETE FROM llm_configs WHERE scope=%s", (scope,))
    return public_config(scope)


def test_llm_connection(scope: str, base_url: str = "", api_key: str | None = None,
                        model: str = "", timeout_seconds: float = 10.0,
                        enable_thinking: bool = False) -> dict:
    if scope not in SCOPES:
        raise ValueError("未知 LLM 配置分组")
    current = get_llm_config(scope)
    url = (base_url or current.get("base_url", "")).strip().rstrip("/")
    key = api_key if api_key is not None else current.get("api_key", "")
    key = str(key or "").strip()
    target_model = (model or current.get("model", "")).strip()

    if not url:
        return {"ok": False, "error": "未配置接口地址 (base_url)"}
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "接口地址必须以 http:// 或 https:// 开头"}
    if not key:
        return {"ok": False, "error": "未配置 API Key"}
    if not target_model:
        return {"ok": False, "error": "未指定模型名称 (model)"}

    timeout = min(max(float(timeout_seconds), 2.0), 15.0)
    started = time.perf_counter()
    endpoint = f"{url}/chat/completions"
    payload = {
        "model": target_model,
        "max_tokens": 10,
        "temperature": 0,
        "messages": [{"role": "user", "content": "ping"}],
    }
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(endpoint, headers={"Authorization": f"Bearer {key}"}, json=payload)
        latency_ms = round((time.perf_counter() - started) * 1000)
        if response.status_code == 200:
            return {"ok": True, "latency_ms": latency_ms, "model": target_model}
        else:
            try:
                err_data = response.json()
                err_msg = err_data.get("error", {}).get("message") or response.text[:200]
            except Exception:
                err_msg = response.text[:200]
            return {"ok": False, "status_code": response.status_code, "latency_ms": latency_ms,
                    "error": f"HTTP {response.status_code}: {err_msg}"}
    except httpx.TimeoutException:
        return {"ok": False, "error": f"请求超时（超过 {timeout} 秒）"}
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"网络请求失败: {str(exc)}"}
    except Exception as exc:
        return {"ok": False, "error": f"调用异常: {str(exc)}"}
