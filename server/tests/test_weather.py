"""天气提醒（services/weather）测试：mock httpx，不发起真实请求。"""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.services import weather  # noqa: E402

NOW = datetime(2026, 9, 13, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
COURSES = [{"name": "计算机网络", "start_time": "14:00", "end_time": "15:40"},
           {"name": "应用程序设计", "start_time": "16:00", "end_time": "17:40"}]


class FakeResponse:
    def __init__(self, payload): self._payload = payload

    def raise_for_status(self): pass

    def json(self): return self._payload


def hourly_payload(rain_hour=14, precip=80, code=61):
    times = [f"2026-09-14T{hour:02d}:00" for hour in range(24)]
    precipitation = [0] * 24
    codes = [0] * 24
    precipitation[rain_hour], codes[rain_hour] = precip, code
    return {"hourly": {"time": times, "precipitation_probability": precipitation, "weather_code": codes}}


def configure(monkeypatch, payload=None, raises=None):
    monkeypatch.setenv("WEATHER_LATITUDE", "30.27")
    monkeypatch.setenv("WEATHER_LONGITUDE", "120.16")
    monkeypatch.setattr(weather, "_CACHE", {})

    def fake_get(url, **kwargs):
        if raises:
            raise raises("network down")
        return FakeResponse(payload if payload is not None else hourly_payload())

    monkeypatch.setattr(weather.httpx, "get", fake_get)


def test_advisory_skipped_without_config(monkeypatch):
    for name in ("WEATHER_LATITUDE", "WEATHER_LONGITUDE"):
        monkeypatch.delenv(name, raising=False)
    assert weather.rain_advisory("2026-09-14", COURSES, NOW) is None


def test_advisory_when_rain_during_class(monkeypatch):
    configure(monkeypatch)
    text = weather.rain_advisory("2026-09-14", COURSES, NOW)
    assert text and "计算机网络" in text and "降雨概率 80%" in text and "带伞" in text


def test_no_advisory_when_rain_outside_class(monkeypatch):
    configure(monkeypatch, hourly_payload(rain_hour=20, precip=90, code=61))
    assert weather.rain_advisory("2026-09-14", COURSES, NOW) is None


def test_no_advisory_when_light_rain_below_threshold(monkeypatch):
    configure(monkeypatch, hourly_payload(rain_hour=14, precip=20, code=0))
    assert weather.rain_advisory("2026-09-14", COURSES, NOW) is None


def test_advisory_by_wet_code_even_with_low_probability(monkeypatch):
    configure(monkeypatch, hourly_payload(rain_hour=14, precip=10, code=61))
    text = weather.rain_advisory("2026-09-14", COURSES, NOW)
    assert text and "预报有雨" in text and "带伞" in text


def test_failure_returns_none(monkeypatch):
    import httpx as httpx_module
    configure(monkeypatch, raises=httpx_module.ConnectError)
    assert weather.rain_advisory("2026-09-14", COURSES, NOW) is None


def test_cache_hit_avoids_second_request(monkeypatch):
    calls = []
    monkeypatch.setenv("WEATHER_LATITUDE", "30.27")
    monkeypatch.setenv("WEATHER_LONGITUDE", "120.16")
    monkeypatch.setattr(weather, "_CACHE", {})

    def fake_get(url, **kwargs):
        calls.append(1)
        return FakeResponse(hourly_payload())

    monkeypatch.setattr(weather.httpx, "get", fake_get)
    assert weather.fetch_hourly(date(2026, 9, 14), NOW)
    assert weather.fetch_hourly(date(2026, 9, 14), NOW)
    assert len(calls) == 1
