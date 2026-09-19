"""合并后的生产契约：生产环境同时要求微信凭证与强 JWT 密钥。"""
import pytest

from app.settings import Settings


def _wechat_ready(monkeypatch):
    monkeypatch.setenv("WECHAT_APP_ID", "wx-test")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    monkeypatch.delenv("WECHAT_DEV_OPENID", raising=False)


def test_production_rejects_insecure_secret(monkeypatch):
    _wechat_ready(monkeypatch)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret="dev-insecure-secret-change-me").validate()


def test_development_accepts_local_defaults():
    Settings(environment="development").validate()


def test_production_rejects_implicit_demo_password(monkeypatch):
    _wechat_ready(monkeypatch)
    monkeypatch.delenv("DEFAULT_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="默认演示账号密码"):
        Settings(environment="production", jwt_secret="x" * 32).validate()


def test_production_requires_wechat_credentials(monkeypatch):
    monkeypatch.delenv("WECHAT_DEV_OPENID", raising=False)
    monkeypatch.delenv("WECHAT_APP_ID", raising=False)
    monkeypatch.delenv("WECHAT_APP_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="WECHAT_APP_ID"):
        Settings(environment="production", jwt_secret="x" * 32).validate()


def test_unknown_environment_is_rejected():
    with pytest.raises(RuntimeError, match="APP_ENV"):
        Settings(environment="prod", jwt_secret="x" * 32).validate()
