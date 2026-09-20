"""统一后端配置：合并网页/Android 母版与小程序版的环境变量契约。

网页端依赖 JWT_SECRET / CORS_ORIGINS / AUTH_RATE_LIMIT 等；
小程序端依赖 WECHAT_* / SESSION_DAYS / DB_POOL_* 等；
AI 解析与视觉识别共用 AI_* / VISION_* 前缀，并支持管理后台的
llm_configs 数据库级覆盖（见 services/llm_config.py）。

`Settings` 提供进程内只读快照；`validate_settings()` 每次调用实时读取
环境变量做启动校验（lifespan 与单元测试共用）。
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

INSECURE_SECRETS = {"", "dev-insecure-secret-change-me", "please-change-this-to-a-long-random-string"}

ENV_CHOICES = {"development", "test", "production"}


def _environment() -> str:
    return os.getenv("APP_ENV", "production").strip().lower()


def _upload_bytes() -> int:
    """MAX_UPLOAD_BYTES（字节）优先；兼容小程序版的 MAX_UPLOAD_MB（兆）。"""
    raw_bytes = os.getenv("MAX_UPLOAD_BYTES", "").strip()
    if raw_bytes:
        return int(raw_bytes)
    return int(float(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024)


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("APP_ENV", "production").strip().lower()
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
    max_upload_bytes: int = _upload_bytes()
    auth_rate_limit: int = int(os.getenv("AUTH_RATE_LIMIT", "10"))
    auth_rate_window_seconds: int = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", "300"))
    trust_proxy_headers: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "https://localhost,http://localhost,capacitor://localhost,http://localhost:5173",
        ).split(",")
        if origin.strip()
    )
    session_days: int = max(1, min(90, int(os.getenv("SESSION_DAYS", "30"))))
    redis_url: str = os.getenv("REDIS_URL", os.getenv("AGENT_REDIS_URL", "")).strip()

    def validate(self) -> None:
        validate_settings(environment=self.environment, jwt_secret=self.jwt_secret)


def validate_settings(environment: str | None = None, jwt_secret: str | None = None) -> None:
    """启动/测试共用的强校验；未显式传参时实时读取环境变量。"""
    app_env = (environment if environment is not None else os.getenv("APP_ENV", "production")).strip().lower()
    if app_env not in ENV_CHOICES:
        raise RuntimeError("APP_ENV 只能是 development、test 或 production")
    if not 1024 <= _upload_bytes() <= 50 * 1024 * 1024:
        raise RuntimeError("MAX_UPLOAD_BYTES 必须在 1KB 到 50MB 之间")
    # 企业微信智能机器人（URL 回调模式）：Token 与 EncodingAESKey 必须成对配置。
    wecom_token = os.getenv("WECOM_CALLBACK_TOKEN", "").strip()
    wecom_aes = os.getenv("WECOM_ENCODING_AES_KEY", "").strip()
    if bool(wecom_token) != bool(wecom_aes):
        raise RuntimeError("企业微信渠道配置不完整：WECOM_CALLBACK_TOKEN 与 WECOM_ENCODING_AES_KEY 必须同时配置")
    if app_env == "production":
        # 小程序侧生产强校验：dev 后门必须关闭，微信凭证必须配置
        if os.getenv("WECHAT_DEV_OPENID", "").strip():
            raise RuntimeError("生产环境禁止配置 WECHAT_DEV_OPENID，请删除后再启动")
        if not os.getenv("WECHAT_APP_ID", "").strip() or not os.getenv("WECHAT_APP_SECRET", "").strip():
            raise RuntimeError("生产环境必须配置 WECHAT_APP_ID 与 WECHAT_APP_SECRET")
        effective_secret = jwt_secret if jwt_secret is not None else os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
        if effective_secret in INSECURE_SECRETS or len(effective_secret) < 32:
            raise RuntimeError("生产环境必须配置至少 32 字符的随机 JWT_SECRET")
        if os.getenv("DEFAULT_PASSWORD", "demo1234") == "demo1234":
            raise RuntimeError("生产环境禁止使用默认演示账号密码")


settings = Settings()
