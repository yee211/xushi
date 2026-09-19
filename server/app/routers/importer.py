"""导入路由：Excel 上传（双端共用）与教务系统 HTML 导入（网页/Android 专属）。

Excel 导入兼容两侧语义：
- 网页端不传 overwrite，默认 True（与母版的幂等覆盖一致）；
- 小程序端显式传 overwrite=false 先探测，409 schedule_exists 确认后重传 true。
"""
import json
import logging
import re
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..ai import parse_html_with_ai, parse_with_ai
from ..auth import get_current_user
from ..db import DATA, connect
from ..excel import validate_excel_container
from ..html_parser import parse_html_schedule
from ..parser import normalize_courses, parse_excel_schedule
from ..services.schedule_import import write_schedule
from ..settings import settings

router = APIRouter(prefix="/api", tags=["import"])
UPLOADS = DATA / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("classschedule")


class ImportHtmlPayload(BaseModel):
    data: str
    start_date: str = ""
    end_date: str = ""


def suggest_semester_dates(term_str: str) -> tuple[date | None, date | None]:
    """根据学期标识（如 2025-2026学年第1学期）自动推算常规起止日期。"""
    match = re.search(r"(\d{4})\s*[-–—/]\s*(\d{4})[^\d]*(?:第\s*)?([12一二秋春])", term_str or "")
    if not match:
        return None, None
    year1 = int(match.group(1))
    term_type = match.group(3)
    is_first_term = term_type in ("1", "一", "秋")
    anchor = date(year1, 9, 1) if is_first_term else date(int(match.group(2) or year1 + 1), 3, 1)
    day = anchor.weekday()  # 周一为 0
    monday_offset = 0 if day == 0 else (7 - day)
    start = anchor + timedelta(days=monday_offset)
    end = start + timedelta(days=20 * 7 - 1)
    return start, end


def parse_schedule_date(value: str, label: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(400, f"{label}格式应为 YYYY-MM-DD") from error


def _persist(user, parsed, schedule_start, schedule_end, engine, started, total_bytes=0, overwrite=True):
    """落库并补齐两端前端各自依赖的响应字段。"""
    with connect() as db:
        result = write_schedule(db, user_id=user["id"], parsed=parsed, overwrite=overwrite,
                                start_date=schedule_start, end_date=schedule_end)
    duration_ms = round((time.perf_counter() - started) * 1000)
    logger.info(json.dumps({
        "event": "schedule_import",
        "user_id": user["id"],
        "engine": engine,
        "imported": result["imported"],
        "replaced": result["replaced"],
        "file_bytes": total_bytes,
        "duration_ms": duration_ms,
    }, ensure_ascii=False))
    return {
        "engine": engine,
        "imported": result["imported"],
        "schedule_id": result["schedule_id"],
        "replaced": result["replaced"],
        "term": result["term"],
        "name": result["name"],
        "duration_ms": duration_ms,
        "suggestions": [],
    }


@router.post("/import")
def import_file(
    file: UploadFile = File(...),
    term_name: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    overwrite: bool = Form(True),
    user=Depends(get_current_user),
):
    """上传 Excel 课表文件（.xlsx / .xlsm / .xls），优先由 AI 提取，失败时自动回退本地解析。"""
    term_name = (term_name or "").strip()
    if len(term_name) > 80:
        raise HTTPException(400, "学期名称不能超过 80 个字符")
    schedule_start = parse_schedule_date(start_date, "学期开始日期")
    schedule_end = parse_schedule_date(end_date, "学期结束日期")
    if schedule_start and schedule_end and schedule_end < schedule_start:
        raise HTTPException(400, "学期结束日期不能早于开始日期")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".xls"}:
        raise HTTPException(400, "仅支持 Excel 课表（.xlsx / .xlsm / .xls）")
    target = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
    started = time.perf_counter()
    try:
        with target.open("wb") as out:
            total = 0
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(413, f"文件不能超过 {settings.max_upload_bytes // 1024 // 1024} MB")
                out.write(chunk)
        try:
            validate_excel_container(target, suffix)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        parsed, engine = parse_with_ai(target)
        if not parsed:
            try:
                parsed = parse_excel_schedule(target)
            except Exception as error:
                logger.warning("本地 Excel 解析失败: %s", error.__class__.__name__)
                parsed = None
            engine = f"excel-fallback({engine})"
        if not parsed:
            raise HTTPException(422, f"AI 与本地解析均未能从该 Excel 中识别出课程（{engine}），请确认文件包含课程明细")

        courses = normalize_courses(parsed.get("courses") or [])
        if not courses:
            raise HTTPException(422, f"AI 与本地解析均未能识别出有效课程明细（{engine}）")
        parsed["courses"] = courses

        if term_name:
            parsed["name"] = term_name
            parsed["term"] = term_name

        if not schedule_start or not schedule_end:
            suggested_start, suggested_end = suggest_semester_dates(parsed.get("term", "") or parsed.get("name", ""))
            schedule_start = schedule_start or suggested_start
            schedule_end = schedule_end or suggested_end

        return _persist(user, parsed, schedule_start, schedule_end, engine, started, total, overwrite)
    finally:
        target.unlink(missing_ok=True)


@router.post("/import-html")
def import_html(
    payload: ImportHtmlPayload,
    user=Depends(get_current_user),
):
    """导入从教务系统 WebView 抓取的 HTML / 表格数据。

    优先执行确定性本地解析，若未识别到课程则自动调用 LLM 兜底。
    """
    raw_data = (payload.data or "").strip()
    if not raw_data:
        raise HTTPException(400, "未收到有效的教务课表数据")

    started = time.perf_counter()

    # 1. 优先使用确定性规则解析
    parsed = None
    engine = "deterministic-html"
    try:
        parsed = parse_html_schedule(raw_data)
    except Exception as error:
        logger.warning("确定性 HTML 解析异常: %s", error.__class__.__name__)
        parsed = None

    # 2. 确定性未能识别到课程时，调用 LLM 兜底
    if not parsed or not parsed.get("courses"):
        ai_parsed, ai_engine = parse_html_with_ai(raw_data)
        if ai_parsed and ai_parsed.get("courses"):
            parsed = ai_parsed
            engine = f"llm-fallback({ai_engine})"
        else:
            engine = f"failed(det+llm:{ai_engine})"

    if not parsed or not parsed.get("courses"):
        raise HTTPException(422, f"确定性规则与 AI 兜底均未能识别出有效课程（{engine}），请确认已进入教务系统的个人课表页面")

    courses = normalize_courses(parsed.get("courses") or [])
    if not courses:
        raise HTTPException(422, f"未能识别出规范的课程安排（{engine}）")
    parsed["courses"] = courses

    # 3. 日期推算与解析
    schedule_start = parse_schedule_date(payload.start_date, "学期开始日期")
    schedule_end = parse_schedule_date(payload.end_date, "学期结束日期")
    if not schedule_start or not schedule_end:
        suggested_start, suggested_end = suggest_semester_dates(parsed.get("term", ""))
        schedule_start = schedule_start or suggested_start
        schedule_end = schedule_end or suggested_end

    return _persist(user, parsed, schedule_start, schedule_end, engine, started,
                    len(raw_data.encode("utf-8")), overwrite=True)
