"""Regressions for the confirmed audit findings; no real network requests."""
import json
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import deps
from app.main import app
from app.parser import normalize_courses, parse_weeks
from app.routers import admin
from app.schemas import CourseIn
from app.services import academic, llm_config
from app.services.schedule_query import materialize_courses, teaching_week


@pytest.mark.parametrize('weeks', ['31-40', '0', [31, 40], []])
def test_invalid_weeks_do_not_create_weekly_ghosts(weeks):
    raw = {'name': 'test', 'weekday': 1, 'start_section': 1, 'end_section': 2, 'weeks': weeks}
    assert normalize_courses([raw]) == []
    assert materialize_courses([dict(raw, id=1, weeks=[])], [], 1, 1) == []


def test_week_parser_bounds_ranges_and_empty_api_weeks_rejected():
    assert parse_weeks('0-999999999') == list(range(1, 31))
    with pytest.raises(ValidationError):
        CourseIn(schedule_id=1, name='test', weekday=1, start_section=1, end_section=2, weeks=[])


def test_non_monday_start_uses_natural_week_boundary():
    schedule = {'start_date': date(2026, 9, 9)}
    assert teaching_week(schedule, date(2026, 9, 13)) == 1
    assert teaching_week(schedule, date(2026, 9, 14)) == 2


def test_static_path_traversal_rejected():
    response = TestClient(app).get('/%2e%2e%2f%2e%2e%2fserver%2fapp%2fsettings.py')
    assert response.status_code == 404


def test_saved_api_key_never_sent_to_changed_endpoint():
    with pytest.raises(ValueError, match='explicitly'):
        llm_config.validate_test_target('https://attacker.example/v1', 'https://model.example/v1', True)


def test_private_endpoint_requires_explicit_allowlist(monkeypatch):
    monkeypatch.delenv('LLM_ALLOWED_BASE_URLS', raising=False)
    monkeypatch.setattr(llm_config.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('127.0.0.1', 80))])
    with pytest.raises(ValueError, match='Private'):
        llm_config.validate_test_target('http://localhost/v1', 'http://localhost/v1', True)


def test_rate_limit_clear_never_matches_session_or_school_keys(monkeypatch):
    from contextlib import nullcontext
    class Redis:
        patterns = []
        def scan_iter(self, match, count):
            self.patterns.append(match)
            return []
    class DB:
        def execute(self, *args):
            pass
    redis = Redis()
    monkeypatch.setattr('app.redis.get_redis', lambda: redis)
    monkeypatch.setattr(admin, 'connect', lambda: nullcontext(DB()))
    admin.clear_ratelimit(admin.ClearRateLimitIn(key='*'), admin='root')
    assert redis.patterns == ['xushi:ratelimit:*']
    with pytest.raises(HTTPException):
        admin.clear_ratelimit(admin.ClearRateLimitIn(key='*session*'), admin='root')


def test_admin_sensitive_endpoints_require_superadmin():
    paths = {'/api/admin/llm-configs/{scope}/test', '/api/admin/system/redis/clear-ratelimit',
             '/api/admin/system/redis/clear-session'}
    for route in app.routes:
        if getattr(route, 'path', None) in paths:
            assert any(dep.call is admin.require_superadmin for dep in route.dependant.dependencies)


def test_class_search_does_not_filter_school_tree_by_class_name():
    import httpx
    bodies = []
    def handler(request):
        bodies.append(request.content.decode())
        return httpx.Response(200, json=[])
    with academic.CcsutClient({'Cookie': 'test'}, transport=httpx.MockTransport(handler)) as client:
        client.search(grade='2024', class_name='test-class')
    assert bodies == ['sznj=2024&xm=']


def test_racing_old_session_fill_is_unreachable_after_invalidation(monkeypatch):
    values = {}
    token = 'session-test'
    digest = deps.token_hash(token)
    old_key = f'xushi:session:{digest}:initial'
    monkeypatch.setattr(deps, 'redis_get', values.get)
    monkeypatch.setattr(deps, 'redis_set', lambda key, value, ex=None: values.update({key: value}) or True)
    monkeypatch.setattr(deps, 'redis_delete', lambda key: values.pop(key, None))
    deps.invalidate_session_cache(token=token)
    # A read that began before commit fills the obsolete generation late.
    values[old_key] = json.dumps({'id': 99})
    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def fetchone(self): return None
    monkeypatch.setattr(deps, 'connect', DB)
    assert deps._user_from_session(token) is None


def test_aborted_half_open_probe_records_failure(monkeypatch):
    from types import SimpleNamespace

    from app.agent import loop
    from app.agent.circuit_breaker import CircuitBreaker, CircuitState
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
    breaker.record_failure('initial')
    assert breaker.allow_request()
    monkeypatch.setattr(loop, 'llm_circuit_breaker', breaker)
    monkeypatch.setattr(loop, 'agent_config', lambda: ('', '', ''))
    assert loop.run(SimpleNamespace(), 'test') is None
    assert breaker.state == CircuitState.OPEN


def test_memory_auth_limit_accumulates_across_requests(monkeypatch):
    from starlette.requests import Request

    from app import rate_limit
    limiter = rate_limit.SlidingWindowLimiter(2, 60)
    monkeypatch.setattr(rate_limit, 'get_redis', lambda: None)
    monkeypatch.setitem(rate_limit._auth_limiters, 'login', limiter)
    request = Request({'type': 'http', 'headers': [], 'client': ('127.0.0.1', 1)})
    rate_limit.enforce_auth_rate_limit(request, 'login')
    rate_limit.enforce_auth_rate_limit(request, 'login')
    with pytest.raises(HTTPException) as error:
        rate_limit.enforce_auth_rate_limit(request, 'login')
    assert error.value.status_code == 429


def test_admin_secret_rotation_preserves_legacy_school_encryption(monkeypatch):
    import hashlib
    monkeypatch.setenv('ADMIN_SESSION_SECRET', 'x' * 40)
    legacy = hashlib.sha256(('ccsut:' + 'x' * 40).encode()).digest()
    assert academic._key() == legacy
    monkeypatch.setenv('ADMIN_SESSION_SECRET', 'y' * 40)
    assert academic._key() == legacy
    assert academic.KEY_FILE.read_bytes() == legacy
