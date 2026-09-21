"""Morning daily schedule and weather push notifications for WeChat users."""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..channels.weixin.client import ILinkClient, ILinkError
from ..channels.weixin.store import load_accounts
from ..db import db_ctx
from .schedule_query import ScheduleQueryError, query_courses_by_date, query_courses_by_week
from .weather import fetch_daily_weather

logger = logging.getLogger("daily-push")

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
SHORT_WEEKDAY_NAMES = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}


def _is_early_course(course: dict) -> bool:
    """判断课程是否属于早八（第 1 节或 08:xx 开始）。"""
    start_sec = course.get("start_section")
    if start_sec is not None:
        try:
            if int(start_sec) == 1:
                return True
        except (ValueError, TypeError):
            pass
    start_time = str(course.get("start_time") or "").strip()
    if start_time.startswith("08:") or start_time.startswith("8:"):
        return True
    return False


def build_weekly_early_class_notice(db, user_id: int, target_date: date) -> str:
    """统计目标日期所在周（周一至周日）有早八的天数，并生成温馨提示文案。"""
    try:
        week_data = query_courses_by_week(db, user_id, target_date)
    except Exception as err:
        logger.warning(
            "failed to query weekly courses for user_id=%s date=%s: %s",
            user_id, target_date, err,
        )
        return ""

    days = week_data.get("days", [])
    if not days:
        return ""

    early_days = []
    for day_info in days:
        courses = day_info.get("courses", [])
        if any(_is_early_course(c) for c in courses):
            w = day_info.get("weekday")
            if w in SHORT_WEEKDAY_NAMES:
                early_days.append(SHORT_WEEKDAY_NAMES[w])

    count = len(early_days)
    if count == 0:
        return "🎉 本周福利：全周无早八，每天都可以多睡一会儿！"

    days_str = "、".join(early_days)
    if count == 1:
        return f"☕ 本周早八：仅 1 天（{days_str}），节奏很轻松~"
    elif count == 2:
        return f"☕ 本周早八：共 2 天（{days_str}），节奏很轻松~"
    elif count in (3, 4):
        return f"⏰ 本周早八预警：共 {count} 天（{days_str}），注意保持规律作息！"
    else:
        if count == 5 and set(early_days) == {"周一", "周二", "周三", "周四", "周五"}:
            return "🔋 本周高能：周一至周五全满早八（5天），上好闹钟，今晚早点睡！"
        return f"🔋 本周高能：共 {count} 天早八（{days_str}），上好闹钟，今晚早点睡！"


def build_morning_brief(db, user_id: int, target_date: date) -> str:
    """构建每日 07:30 晨报文案：课表 + 天气 + 仅下雨时提醒带伞。克制无废话。"""
    schedule_notice = ""
    try:
        query_result = query_courses_by_date(db, user_id, target_date)
    except ScheduleQueryError as err:
        # 假期/学期外无课表覆盖、或存在多张可用课表：降级为「今日无课」，
        # 绝不能抛出去中断整批推送（收件人按 user_id 串行，一个异常会挡死后面所有人）。
        logger.warning("morning brief without courses user_id=%s date=%s code=%s",
                       user_id, target_date, err.code)
        query_result = {"courses": [], "week": None}
        if err.code == "AMBIGUOUS_SCHEDULE":
            schedule_notice = "⚠️ 你有多张生效中的课表，请在小程序里选定默认课表后查看今日安排。"
    courses = query_result.get("courses", [])
    week = query_result.get("week")

    weekday_idx = target_date.weekday()
    weekday_str = WEEKDAY_NAMES[weekday_idx] if 0 <= weekday_idx < len(WEEKDAY_NAMES) else ""
    week_suffix = f"（第{week}周）" if week else ""
    date_header = f"📅 {target_date.year}年{target_date.month}月{target_date.day}日 {weekday_str}{week_suffix}"

    weather = fetch_daily_weather(target_date)
    weather_line = ""
    rain_notice = ""
    if weather:
        cond = weather.get("condition", "多云")
        t_min = weather.get("temp_min")
        t_max = weather.get("temp_max")
        temp_str = f"，{t_min}℃ ~ {t_max}℃" if t_min is not None and t_max is not None else ""
        icon = "🌧" if weather.get("rain") else ("⛅" if "云" in cond or "阴" in cond else "☀️")
        weather_line = f"{icon} 天气：{cond}{temp_str}"

        if weather.get("rain"):
            prob = weather.get("rain_probability", 0)
            prob_str = f"（概率 {prob}%）" if prob > 0 else ""
            rain_notice = f"☔ 提醒：今天有降雨{prob_str}，出门记得带伞！"

    early_notice = ""
    if weekday_idx == 0 and week is not None:
        early_notice = build_weekly_early_class_notice(db, user_id, target_date)

    parts = ["【今日课表与天气】", date_header]
    if weather_line:
        parts.append(weather_line)
    if rain_notice:
        parts.append(rain_notice)
    if early_notice:
        parts.append("")
        parts.append(early_notice)
    parts.append("")

    if courses:
        parts.append(f"📚 今日课程（共 {len(courses)} 门）：")
        for idx, item in enumerate(courses, 1):
            start, end = item.get("start_time") or "", item.get("end_time") or ""
            span = f"{start}-{end} " if start and end else ""
            line = f"{idx}. {span}{item.get('name') or '未命名课程'}"
            room = item.get("room")
            if room:
                line += f" @ {room}"
            teacher = item.get("teacher")
            if teacher:
                line += f" · {teacher}"
            parts.append(line)
    elif schedule_notice:
        parts.append(schedule_notice)
    else:
        parts.append("🎉 今日无课，好好休息！")

    return "\n".join(parts).strip()


def _record_push_result(db, user_id: int, target_date: date, status: str, error: str = "") -> None:
    """写入/覆盖当天晨报结果。status: done=已送达, failed=可重试, skipped=当天不再重试。"""
    db.execute("""INSERT INTO daily_push_logs(user_id, push_date, push_type, status, pushed_at, error)
        VALUES(%s, %s, 'morning_brief', %s, CURRENT_TIMESTAMP, %s)
        ON CONFLICT (user_id, push_date, push_type) DO UPDATE SET
        status=EXCLUDED.status, pushed_at=EXCLUDED.pushed_at, error=EXCLUDED.error""",
        (user_id, target_date, status, str(error)[:500]))


def send_morning_push_to_user(db, client: ILinkClient, user_id: int, provider_user_id: str,
                              context_token: str, target_date: date) -> bool:
    """向指定微信用户发送晨报，并在数据库记录防重日志。"""
    brief = build_morning_brief(db, user_id, target_date)
    client_id = f"morning_{user_id}_{target_date.isoformat().replace('-', '')}"
    try:
        client.send_text(provider_user_id, brief, context_token=context_token or "", client_id=client_id)
    except ILinkError as err:
        # iLink 业务拒绝（典型是 -2 prepare failed：用户超过约 24 小时没跟 bot 说话，
        # 会话已失效）当天重试也不会成功，记为 skipped 让重试查询跳过，
        # 否则会每 10 秒轰炸腾讯接口一整天（实测单用户单日 5000+ 次）。
        logger.warning("morning push skipped user_id=%s to=%s date=%s error=%s",
                       user_id, provider_user_id, target_date, err)
        _record_push_result(db, user_id, target_date, "skipped", err)
        return False
    _record_push_result(db, user_id, target_date, "done")
    logger.info("morning push sent user_id=%s to=%s date=%s", user_id, provider_user_id, target_date)
    return True


def _record_failure_safely(db, user_id: int, target_date: date, error: str) -> None:
    try:
        with db_ctx(db) as conn:
            _record_push_result(conn, user_id, target_date, "failed", error)
    except Exception:
        logger.exception("could not record morning push failure user_id=%s", user_id)


def dispatch_morning_pushes(db, target_date: date | None = None,
                            timezone_name: str = "Asia/Shanghai") -> int:
    """找出今天尚未推送晨报的绑定用户，执行推送。短事务分段处理，避免长任务霸占连接。"""
    tz = ZoneInfo(timezone_name)
    target_date = target_date or datetime.now(tz).date()

    with db_ctx(db) as conn:
        rows = conn.execute("""
            SELECT u.user_id, u.provider_user_id, COALESCE(u.context_token, '') AS context_token,
                   c.account_id
            FROM user_identities u
            JOIN channel_accounts c
              ON c.provider = u.provider AND c.account_id = u.account_id AND c.status = 'active'
            LEFT JOIN daily_push_logs l
              ON l.user_id = u.user_id AND l.push_date = %s AND l.push_type = 'morning_brief'
            WHERE u.provider = 'weixin_ilink'
              AND (l.user_id IS NULL OR l.status = 'failed')
            ORDER BY u.user_id
        """, (target_date,)).fetchall()
        credentials_by_account = {item[0].account_id: item[0] for item in load_accounts(conn)}

    if not rows:
        return 0

    sent_count = 0
    clients: dict[str, ILinkClient] = {}
    try:
        for row in rows:
            account_id = row["account_id"]
            client = clients.get(account_id)
            if client is None:
                credentials = credentials_by_account.get(account_id)
                if credentials is None:
                    logger.warning("active credentials missing for account=%s user_id=%s",
                                   account_id, row["user_id"])
                    with db_ctx(db) as conn:
                        _record_push_result(conn, row["user_id"], target_date, "skipped",
                                            "active credentials missing")
                    continue
                client = clients[account_id] = ILinkClient(credentials)
            try:
                with db_ctx(db) as conn:
                    ok = send_morning_push_to_user(conn, client, row["user_id"],
                                                   row["provider_user_id"],
                                                   row["context_token"],
                                                   target_date)
            except Exception as err:
                # 收件人按 user_id 串行处理：任何一个用户抛出的非 ILinkError（数据库抖动、
                # httpx 超时、意外课表数据）都会中断整批，导致排在其后的用户当天全部收不到。
                logger.warning("morning push errored user_id=%s date=%s error=%s",
                               row["user_id"], target_date, err)
                _record_failure_safely(db, row["user_id"], target_date, str(err))
                continue
            if ok:
                sent_count += 1
    finally:
        for client in clients.values():
            client.close()

    return sent_count


def pending_morning_push_count(db, target_date: date) -> int:
    """Return recipients that still need a successful morning push."""
    row = db.execute("""SELECT COUNT(*) AS count FROM user_identities u
        JOIN channel_accounts c
          ON c.provider=u.provider AND c.account_id=u.account_id AND c.status='active'
        LEFT JOIN daily_push_logs l
          ON l.user_id=u.user_id AND l.push_date=%s AND l.push_type='morning_brief'
        WHERE u.provider='weixin_ilink' AND (l.user_id IS NULL OR l.status='failed')""",
        (target_date,)).fetchone()
    return int(row["count"] if row else 0)
