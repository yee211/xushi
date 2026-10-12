"""共享 fixture。"""
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))


@pytest.fixture(autouse=True)
def llm_off_by_default(monkeypatch):
    """单元测试默认关闭 agent 的 LLM 能力（本机 .env 可能注入真实配置导致联网）。

    需要验证 LLM 路径的测试自行 monkeypatch orchestrator.llm_configured / polish_answer / small_talk。
    """
    monkeypatch.setattr("app.agent.orchestrator.llm_configured", lambda: False)
    monkeypatch.setattr("app.agent.orchestrator.run_agent", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.agent.orchestrator.extract_intent", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.agent.orchestrator.polish_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.agent.orchestrator.small_talk", lambda *args, **kwargs: None)

    class _NoDb:
        def __enter__(self):
            raise RuntimeError("DB disabled by default in tests")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.services.llm_config.connect", lambda: _NoDb())


@pytest.fixture
def make_file(tmp_path):
    def _make(name: str, content: bytes) -> Path:
        target = tmp_path / name
        target.write_bytes(content)
        return target
    return _make


@pytest.fixture(autouse=True)
def isolate_user_data_cache(monkeypatch):
    """Local request tests must never populate the developer's real Redis."""
    monkeypatch.setattr("app.services.user_cache.get_redis", lambda: None)


@pytest.fixture(autouse=True)
def isolate_school_worker(monkeypatch):
    """Unit tests must not start real school fetches or touch durable job tables."""
    monkeypatch.setattr("app.services.academic_directory.start", lambda: None)
    monkeypatch.setattr("app.services.academic_directory.stop", lambda: None)
    monkeypatch.setattr("app.services.academic_directory.grades", lambda: None)
    monkeypatch.setattr("app.services.academic_directory.search", lambda **kwargs: None)
    monkeypatch.setattr("app.services.academic_directory.student", lambda sid: None)
    monkeypatch.setattr("app.services.academic_jobs.start", lambda: None)
    monkeypatch.setattr("app.services.academic_jobs.stop", lambda: None)
    monkeypatch.setattr("app.services.academic_rate_limit.acquire", lambda deadline: None)


@pytest.fixture(autouse=True)
def isolate_school_encryption_key(monkeypatch, tmp_path):
    monkeypatch.delenv('ACADEMIC_CREDENTIAL_SECRET', raising=False)
    monkeypatch.setattr('app.services.academic.KEY_FILE', tmp_path / 'credential.key')


@pytest.fixture(autouse=True)
def isolate_school_maintenance_and_mail(monkeypatch, tmp_path):
    """Application lifespan tests must not resume real login or send real mail."""
    from app.services import academic_login, academic_mail

    monkeypatch.setattr(academic_login, "MAINTENANCE", tmp_path / "maintenance.json")
    monkeypatch.setattr(academic_mail, "CONFIG", tmp_path / "mail-config.enc")
    monkeypatch.setattr(academic_mail, "OUTBOX", tmp_path / "mail-outbox.json")


@pytest.fixture(autouse=True)
def isolate_redis_configuration(monkeypatch):
    """Default tests must never consume the developer's real Redis rate limits."""
    from dataclasses import replace

    from app import redis as redis_module

    monkeypatch.setattr(redis_module, "settings", replace(redis_module.settings, redis_url=""))
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("AGENT_REDIS_URL", raising=False)
    redis_module.reset_redis_client()
    yield
    redis_module.reset_redis_client()


@pytest.fixture(autouse=True)
def isolate_in_memory_rate_limits():
    from app import rate_limit
    from app.routers import admin, feedback
    from app.services import binding

    for module in (rate_limit, admin, feedback, binding):
        for value in vars(module).values():
            if isinstance(value, rate_limit.SlidingWindowLimiter):
                with value._lock:
                    value._hits.clear()
