"""Open-Meteo 天气查询（免费、无 key）：为当日/次日课程生成降雨带伞提醒。

配置 WEATHER_LATITUDE/WEATHER_LONGITUDE（学校坐标）后启用；任何失败都返回 None，
调用方静默跳过，绝不影响课表主链路。
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

WET_WEATHER_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}
RAIN_PROBABILITY_THRESHOLD = 50
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_DAILY_CACHE: dict[tuple, tuple[float, dict]] = {}

WMO_WEATHER_NAMES = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "大雾",
    48: "雾",
    51: "毛毛雨",
    53: "小雨",
    55: "小雨",
    56: "冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "中阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "大阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴有冰雹",
    99: "强雷阵雨",
}


def weather_settings() -> tuple[str, str] | None:
    latitude = os.getenv("WEATHER_LATITUDE", "").strip()
    longitude = os.getenv("WEATHER_LONGITUDE", "").strip()
    return (latitude, longitude) if latitude and longitude else None


def _cache_ttl_seconds() -> float:
    minutes = max(5.0, min(float(os.getenv("WEATHER_CACHE_MINUTES", "60")), 360.0))
    return minutes * 60


def fetch_hourly(target_date: date, now: datetime | None = None) -> list[dict] | None:
    """目标日期逐小时 [{"hour": 14, "precip": 80, "code": 61}, ...]；未配置或失败返回 None。"""
    settings = weather_settings()
    if not settings:
        return None
    now = now or datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai")))
    key = (settings, target_date)
    cached = _CACHE.get(key)
    if cached and now.timestamp() - cached[0] < _cache_ttl_seconds():
        return cached[1]
    try:
        response = httpx.get("https://api.open-meteo.com/v1/forecast",
                             timeout=max(2.0, min(float(os.getenv("WEATHER_TIMEOUT_SECONDS", "3")), 10.0)),
                             params={"latitude": settings[0], "longitude": settings[1],
                                     "hourly": "precipitation_probability,weather_code",
                                     "start_date": target_date.isoformat(),
                                     "end_date": target_date.isoformat(),
                                     "timezone": "Asia/Shanghai"})
        response.raise_for_status()
        hourly = response.json()["hourly"]
        hours = [{"hour": int(text[11:13]), "precip": int(value or 0), "code": int(code)}
                 for text, value, code in zip(hourly["time"], hourly["precipitation_probability"],
                                              hourly["weather_code"])]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return None
    _CACHE[key] = (now.timestamp(), hours)
    return hours


def day_rain(target_date: date, period: str = "all", now: datetime | None = None) -> dict | None:
    """某天（可限定时段）是否会下雨；天气不可用时返回 None。"""
    hours = fetch_hourly(target_date, now)
    if hours is None:
        return None
    ranges = {"all": (0, 24), "morning": (6, 12), "afternoon": (11, 18), "evening": (17, 24)}
    low, high = ranges.get(period, (0, 24))
    scoped = [hour for hour in hours if low <= hour["hour"] < high] or hours
    raining = any(hour["precip"] >= RAIN_PROBABILITY_THRESHOLD or hour["code"] in WET_WEATHER_CODES
                  for hour in scoped)
    return {"rain": raining, "peak": max((hour["precip"] for hour in scoped), default=0)}


def rain_advisory(target_date: str, courses: list[dict], now: datetime | None = None) -> str | None:
    """课程时段内降雨时返回一条带伞提醒；无雨、无课或天气不可用时返回 None。"""
    hours = fetch_hourly(date.fromisoformat(target_date), now)
    if not hours or not courses:
        return None
    worst = None
    for item in courses:
        start, end = int(item["start_time"][:2]), int(item["end_time"][:2])
        in_class = [hour for hour in hours if start <= hour["hour"] <= end]
        if not in_class:
            continue
        peak = max(in_class, key=lambda hour: hour["precip"])
        if peak["precip"] < RAIN_PROBABILITY_THRESHOLD and peak["code"] not in WET_WEATHER_CODES:
            continue
        if worst is None or peak["precip"] > worst[0]["precip"]:
            worst = (peak, item)
    if not worst:
        return None
    peak, item = worst
    reason = f"降雨概率 {peak['precip']}%" if peak["precip"] >= RAIN_PROBABILITY_THRESHOLD else "预报有雨"
    return f"☔ 提醒：{target_date} {item['start_time']}–{item['end_time']}《{item['name']}》时段{reason}，记得带伞。"


def fetch_daily_weather(target_date: date, now: datetime | None = None) -> dict | None:
    """获取目标日期的全天天气概况：气温范围、天气现象、是否降雨、降雨概率。"""
    settings = weather_settings()
    if not settings:
        return None
    now = now or datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai")))
    key = (settings, target_date)
    cached = _DAILY_CACHE.get(key)
    if cached and now.timestamp() - cached[0] < _cache_ttl_seconds():
        return cached[1]
    try:
        response = httpx.get("https://api.open-meteo.com/v1/forecast",
                             timeout=max(2.0, min(float(os.getenv("WEATHER_TIMEOUT_SECONDS", "3")), 10.0)),
                             params={"latitude": settings[0], "longitude": settings[1],
                                     "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                                     "start_date": target_date.isoformat(),
                                     "end_date": target_date.isoformat(),
                                     "timezone": "Asia/Shanghai"})
        response.raise_for_status()
        daily = response.json().get("daily") or {}
        code = int((daily.get("weather_code") or [0])[0])
        temp_max = round(float((daily.get("temperature_2m_max") or [0])[0]))
        temp_min = round(float((daily.get("temperature_2m_min") or [0])[0]))
        precip_prob = int((daily.get("precipitation_probability_max") or [0])[0] or 0)

        condition = WMO_WEATHER_NAMES.get(code, "多云")
        rain = code in WET_WEATHER_CODES or precip_prob >= 40
        result = {
            "weather_code": code,
            "condition": condition,
            "temp_min": temp_min,
            "temp_max": temp_max,
            "rain": rain,
            "rain_probability": precip_prob,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return None
    _DAILY_CACHE[key] = (now.timestamp(), result)
    return result

