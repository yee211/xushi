"""确定性 Excel 课表解析：直接读取工作簿，不依赖 Excel 本体。

AI 解析（app/ai.py）不可用或识别失败时，本模块作为兜底链路保证导入功能不中断。
"""
import re
from pathlib import Path

from .excel import read_sheets

COLORS = ["#5579E8", "#EF5B78", "#F18745", "#8B6AD8", "#42A5C9", "#55AD72", "#D79D39"]


def course_color(weekday: int, start_section: int) -> str:
    """按星期与起始节次确定性取色，保证同一时段每次导入颜色一致。"""
    return COLORS[(weekday + start_section - 2) % len(COLORS)]


def _find_term(*candidates: str) -> str | None:
    """Return the first 'YYYY-YYYY学年第N学期' match among the candidates."""
    for text in candidates:
        match = re.search(r"\d{4}-\d{4}学年第\d学期", text or "")
        if match:
            return match.group(0)
    return None


def _detail_columns(header_row: dict) -> dict:
    """Map logical course fields to sheet column indexes using header text."""
    columns = {}
    for index, value in header_row.items():
        text = str(value or "").strip()
        if not text:
            continue
        if "星期" in text:
            columns.setdefault("weekday", index)
        elif "节次" in text:
            columns.setdefault("section", index)
        elif "课程" in text:
            columns.setdefault("name", index)
        elif "教师" in text or "授课" in text:
            columns.setdefault("teacher", index)
        elif "周次" in text:
            columns.setdefault("weeks", index)
        elif "教室" in text or "地点" in text:
            columns.setdefault("room", index)
    return columns


def _find_detail_header(rows: list[dict]) -> tuple[int | None, dict]:
    """Locate the header row of a course-detail table, skipping title rows that merely mention keywords."""
    for index, row in enumerate(rows):
        joined = "".join(str(value or "") for value in row.values())
        if "星期" in joined and ("节次" in joined or "课程" in joined):
            # 标题行也可能含“星期/节次”字样，需用列映射确认该行确实是表头
            candidate = _detail_columns(row)
            if candidate.get("weekday") and candidate.get("name"):
                return index, candidate
    return None, {}


def _detail_courses(rows: list[dict], header_index: int, columns: dict) -> list[dict]:
    """Turn detail-table rows below the header into course records."""
    courses = []
    for row in rows[header_index + 1:]:
        weekday_text = str(row.get(columns.get("weekday", 1)) or "")
        day_match = re.search(r"星期([一二三四五六日])", weekday_text) or re.search(r"([一二三四五六日])", weekday_text)
        # 节次兼容区间 "3-4" 与单节 "5"（合并自小程序版的单节次兼容）
        section_text = str(row.get(columns.get("section", 2)) or "")
        section_match = re.search(r"(\d+)\s*-\s*(\d+)", section_text)
        single_section = re.search(r"\d+", section_text)
        name = str(row.get(columns.get("name", 3)) or "").strip()
        if not day_match or not (section_match or single_section) or not name:
            continue
        weeks = parse_weeks(str(row.get(columns.get("weeks", 5)) or ""))
        weekday = "一二三四五六日".index(day_match.group(1)) + 1
        if section_match:
            start, end = int(section_match.group(1)), int(section_match.group(2))
        else:
            start = end = int(single_section.group(0))
        courses.append({
            "name": name, "teacher": str(row.get(columns.get("teacher", 4)) or "").strip(),
            "room": str(row.get(columns.get("room", 6)) or "").strip(), "weekday": weekday,
            "start_section": start, "end_section": end, "weeks": weeks,
            "color": course_color(weekday, start),
        })
    return courses


def parse_weeks(expression: str) -> list[int]:
    """解析周次表达式，兼容以下形态：
    - '1-5(单),9-16(双),18'（逗号分隔 + 括号单双周）
    - '1,7-9,11-12周'（教务 zcstr 逗号列举）
    - '1-5(单)9-15(单)周'（强智网页把多个单周区间直接相连、无逗号）
    - '4,7,10-16(双)周' / '3,7-11(单)周' / '18周'
    单/双后缀只作用于紧邻其前的那个数字或区间。
    """
    weeks: set[int] = set()
    text = re.sub(r"[周第\s]", "", str(expression or ""))
    for match in re.finditer(r"(\d+)(?:[-–~到](\d+))?([（(][单双][）)])?", text):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        parity = match.group(3) or ""
        for week in range(min(start, end), max(start, end) + 1):
            if "单" in parity and week % 2 == 0:
                continue
            if "双" in parity and week % 2 == 1:
                continue
            weeks.add(week)
    return sorted(weeks)


CAMPUS_AND_META_NAMES = {
    "本校区", "校本部", "新校区", "老校区", "东校区", "西校区", "南校区", "北校区", "校区",
    "长沙工业学院", "长春大学旅游学院",
    "理论", "实践", "考查", "考试", "必修", "选修",
    "通识教育课程", "专业教育课程", "专业核心课程", "专业选修课程",
    "无", "休", "暂无", "课程", "教师", "地点", "教室", "节次", "时间",
    "每周", "全周", "单周", "双周",
}


def _is_campus_or_meta(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    if t in CAMPUS_AND_META_NAMES:
        return True
    if t.endswith("校区") and len(t) <= 6:
        return True
    return False


def _is_classroom_like(text: str) -> bool:
    t = str(text or "").strip()
    if re.search(r"^\d+[-号楼/南北中栋]+\d*", t):
        return True
    if any(k in t for k in ["教室", "机房", "操场", "足球场", "实验室", "实训楼", "多媒体", "语音室", "报告厅", "网络中心"]):
        return True
    if re.match(r"^[A-Za-z]?\d{3,4}$", t):
        return True
    if re.match(r"^\d+-\d+$", t):
        return True
    return False


def merge_section_courses(courses: list[dict]) -> list[dict]:
    """Merge identical courses sitting in consecutive section slots (e.g. 1-2 + 3-4, or 1 + 2).
    Also auto-expand isolated odd single sections to 2-period lecture blocks (1-2, 3-4, 5-6, 7-8, 9-10)."""
    merged = []
    for course in sorted(courses, key=lambda item: (item["weekday"], item["start_section"], item["end_section"], item["name"])):
        previous = next((item for item in reversed(merged)
                         if item["end_section"] + 1 == course["start_section"]
                         and item["weekday"] == course["weekday"]
                         and item["name"] == course["name"]
                         and (not item["teacher"] or not course["teacher"] or item["teacher"] == course["teacher"])
                         and (not item["room"] or not course["room"] or item["room"] == course["room"])
                         and (not item["weeks"] or not course["weeks"] or item["weeks"] == course["weeks"])), None)
        if previous:
            previous["end_section"] = course["end_section"]
            if not previous["teacher"] and course["teacher"]:
                previous["teacher"] = course["teacher"]
            if not previous["room"] and course["room"]:
                previous["room"] = course["room"]
            if not previous["weeks"] and course["weeks"]:
                previous["weeks"] = course["weeks"]
        else:
            merged.append(dict(course))

    # Auto-expand isolated odd single sections (1, 3, 5, 7, 9) into standard 2-period university blocks (1-2, 3-4, 5-6, 7-8, 9-10)
    for course in merged:
        if course["start_section"] == course["end_section"] and course["start_section"] in (1, 3, 5, 7, 9):
            target_end = course["start_section"] + 1
            has_conflict = False
            for other in merged:
                if other is course or other["weekday"] != course["weekday"]:
                    continue
                if other["start_section"] <= target_end <= other["end_section"]:
                    c_weeks = set(course.get("weeks") or [])
                    o_weeks = set(other.get("weeks") or [])
                    if not c_weeks or not o_weeks or (c_weeks & o_weeks):
                        has_conflict = True
                        break
            if not has_conflict:
                course["end_section"] = target_end

    return merged


def normalize_courses(raw_courses: list) -> list[dict]:
    """对课表课程进行确定性规范化与校验：
    - 课程名非空且不超过 80 字，过滤校区与教务元数据干扰
    - 教师与教室不超过 40 字
    - 星期为 1～7
    - 节次为 1～12，start_section <= end_section
    - 周次只保留 1～30 的有效正整数，排序并去重
    - AI 和本地解析使用相同去重键 (name, weekday, start_section, end_section, tuple(weeks))
    - 合并同星期同名同教师同教室同周次的相邻节次
    """
    if not isinstance(raw_courses, list):
        return []
    normalized = []
    seen = set()
    for raw in raw_courses:
        if not isinstance(raw, dict):
            continue
        name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()[:80]
        if not name or _is_campus_or_meta(name):
            continue
        try:
            weekday = int(raw.get("weekday"))
            start_section = int(raw.get("start_section"))
            end_section = int(raw.get("end_section"))
        except (ValueError, TypeError):
            continue
        if not (1 <= weekday <= 7):
            continue
        if not (1 <= start_section <= 12 and 1 <= end_section <= 12):
            continue
        if end_section < start_section:
            start_section, end_section = end_section, start_section

        raw_weeks = raw.get("weeks")
        if isinstance(raw_weeks, str):
            weeks = parse_weeks(raw_weeks)
        elif isinstance(raw_weeks, list | tuple | set):
            weeks = [w for w in raw_weeks if isinstance(w, int) and 1 <= w <= 30]
        else:
            weeks = []
        weeks = sorted(set(weeks))

        key = (name, weekday, start_section, end_section, tuple(weeks))
        if key in seen:
            continue
        seen.add(key)

        teacher = re.sub(r"\s+", " ", str(raw.get("teacher") or "")).strip()[:40]
        room = re.sub(r"\s+", " ", str(raw.get("room") or "")).strip()[:40]
        color = str(raw.get("color") or "").strip()
        if not (color.startswith("#") and len(color) in {4, 7, 9}):
            color = course_color(weekday, start_section)

        normalized.append({
            "name": name,
            "teacher": teacher,
            "room": room,
            "weekday": weekday,
            "start_section": start_section,
            "end_section": end_section,
            "weeks": weeks,
            "color": color,
        })

    return merge_section_courses(normalized)


GRID_HEADER_PATTERN = re.compile(r"^(?:星期|周)([一二三四五六日天])$")
SECTION_ROW_PATTERN = re.compile(
    r"^(?:第\s*)?(\d+)(?:\.0)?\s*(?:[-–~到/]\s*(\d+)(?:\.0)?)?\s*节?(?:\s*\(?[\d:：\-–~到]+\)?)?$"
)


def _grid_weekday_columns(rows: list[dict]) -> dict[int, int]:
    """Find the header row of a grid timetable; return {column_index: weekday}."""
    for row in rows:
        mapping = {}
        for column, value in row.items():
            match = GRID_HEADER_PATTERN.match(str(value or "").strip())
            if match:
                day = "日" if match.group(1) == "天" else match.group(1)
                mapping[column] = "一二三四五六日".index(day) + 1
        if len(mapping) >= 3:
            return mapping
    return {}


# 周次串核心形态：'1,7-9,11-12周' / '1-15(单)周' / '1-5(单)9-15(单)周' /
# '1-5(单),9-15(单)周'（区间之间可有逗号/空格等分隔符）/ '4,7,10-16(双)周'
# 关键点：(单)/(双) 括号后允许分隔符再接下一段区间，最终以“周”字收尾。
WEEK_SPEC_CORE = r"\d[\d\-–~到,，、\s]*(?:[（(][单双][）)][\d\-–~到,，、\s]*)*周"

WEEK_RE = re.compile(
    r"(?:【[^】]*周[^】]*】|\[[^\]]*周[^\]]*\]|\([^)]*周[^)]*\)|（[^）]*周[^）]*）|"
    + WEEK_SPEC_CORE
    + r")"
)


def _clean_cell_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _split_grid_cell(text: str) -> list[str]:
    """Split one grid cell into course blocks; supports delimiter lines, bracketed courses,
    and multi-course cells where course names and week/teacher/room lines are grouped."""
    text = text.strip()
    if not text:
        return []

    # 1. Delimiter lines (like ---------------------)
    if re.search(r"(?m)^\s*[-=—_]{3,}\s*$", text):
        return [p.strip() for p in re.split(r"(?m)^\s*[-=—_]{3,}\s*$", text) if p.strip()]

    # 2. Bracketed course names like 【课程名】 (not containing 周)
    bracket_splits = [p.strip() for p in re.split(r"(?m)^(?=\s*【[^】\n]+】(?!\s*周))", text) if p.strip()]
    if len(bracket_splits) > 1:
        return bracket_splits

    # 3. Check for lines containing week specs (e.g. 杨玉霜【1-4周】)
    all_lines = [line.strip() for line in text.splitlines() if line.strip()]
    week_indices = [i for i, line in enumerate(all_lines) if WEEK_RE.search(line)]

    if len(week_indices) > 1:
        blocks = []
        for i, w_idx in enumerate(week_indices):
            # Start index:
            if i == 0:
                start_idx = 0
            else:
                prev_w = week_indices[i - 1]
                between = all_lines[prev_w + 1 : w_idx]
                if len(between) <= 1:
                    start_idx = prev_w + 1
                else:
                    # Previous course's room is between[0..-2], current course name is between[-1]
                    start_idx = w_idx - 1

            # End index:
            if i == len(week_indices) - 1:
                end_idx = len(all_lines)
            else:
                next_w = week_indices[i + 1]
                between = all_lines[w_idx + 1 : next_w]
                if len(between) <= 1:
                    end_idx = w_idx + 1
                else:
                    # Leave the last line of `between` for the next course's name
                    end_idx = next_w - 1

            block_lines = all_lines[start_idx:end_idx]
            if block_lines:
                blocks.append("\n".join(block_lines))
        if len(blocks) > 1:
            return blocks

    # 4. Double newline splits
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1 and all(bool(WEEK_RE.search(p)) for p in paragraphs):
        return paragraphs

    return [text]


def _extract_weeks_text(text: str) -> tuple[str, str]:
    """Split trailing week expression from text like '肖裕【11-15周】' or '肖裕 1-15(单)周'."""
    bracket = re.search(r"【([^】]*周[^】]*)】", text)
    if bracket:
        return text[:bracket.start()].strip(" -·、，,"), bracket.group(1)
    inline = re.search(
        r"(\d+\s*[-–~到]\s*\d+(?:\s*[（(][单双][）)])*\s*周?|" + WEEK_SPEC_CORE + r")\s*$",
        text,
    )
    if inline:
        return text[:inline.start()].strip(" -·、，,"), inline.group(1)
    return text.strip(" -·、，,"), ""


def _parse_grid_course_block(block: str, weekday: int, start: int, end: int) -> dict | None:
    lines = [line.strip().lstrip("·•-— ") for line in block.splitlines() if line.strip()]
    if not lines:
        return None

    name = teacher = room = ""
    week_texts = []

    for line in lines:
        if _is_campus_or_meta(line):
            continue

        if not name:
            marked = re.match(r"^[【\[(（](.+?)[】\])）]\s*(.*)$", line)
            if marked and not re.search(r"^\d+.*周", marked.group(1)):
                candidate = marked.group(1).strip()
                if _is_campus_or_meta(candidate):
                    if marked.group(2):
                        line = marked.group(2).strip()
                    else:
                        continue
                elif _is_classroom_like(candidate):
                    if not room:
                        room = _clean_cell_text(candidate, 40)
                    if marked.group(2):
                        line = marked.group(2).strip()
                    else:
                        continue
                else:
                    name = candidate
                    if marked.group(2):
                        line = marked.group(2).strip()
                    else:
                        continue
            elif _is_classroom_like(line):
                if not room:
                    room = _clean_cell_text(line, 40)
                continue
            elif not WEEK_RE.search(line) and not ("教师" in line or "老师" in line or "地点" in line or "教室" in line):
                name = line
                continue

        # Compound line: e.g. 肖裕【11-15周】  4-南210 / 杨文【2-16(双)周】  4-南209 /
        # 龙艳军 1-5(单)9-15(单)周（强智网页：教师与周次同行的无括号形态）
        m_compound = re.search(
            r"^(.*?)(?:【([^】]*周[^】]*)】|\[([^\]]*周[^\]]*)\]|\(([^)]*周[^)]*)\)|（([^）]*周[^）]*)）|("
            + WEEK_SPEC_CORE
            + r"))\s*(.*)$",
            line,
        )
        if m_compound:
            t = m_compound.group(1).strip()
            w = (
                m_compound.group(2)
                or m_compound.group(3)
                or m_compound.group(4)
                or m_compound.group(5)
                or m_compound.group(6)
                or ""
            ).strip()
            r = m_compound.group(7).strip()
            if t and not teacher:
                teacher = _clean_cell_text(t, 40)
            if w:
                week_texts.append(w)
            if r and not room:
                room = _clean_cell_text(r, 40)
            continue

        if "教师" in line or "老师" in line:
            tail = re.split(r"[:：]", line, maxsplit=1)[-1].strip()
            wm = WEEK_RE.search(tail)
            if wm:
                week_texts.append(wm.group(0))
                tail = tail[:wm.start()].strip(" -·、，,")
            if tail and not teacher:
                teacher = _clean_cell_text(tail, 40)
        elif "地点" in line or "教室" in line:
            room = _clean_cell_text(re.split(r"[:：]", line, maxsplit=1)[-1], 40)
        elif "周次" in line or WEEK_RE.search(line):
            wm = WEEK_RE.search(line)
            if wm:
                week_texts.append(wm.group(0))
                before = line[:wm.start()].strip(" :：【[（(-·、，,")
                after = line[wm.end():].strip(" 】]）)-·、，,")
                if before and not teacher and len(before) <= 6 and not re.search(r"\d", before):
                    teacher = _clean_cell_text(before, 40)
                if after and not room:
                    room = _clean_cell_text(after, 40)
            else:
                week_texts.append(re.split(r"[:：]", line, maxsplit=1)[-1])
        elif not room and (re.search(r"\d", line) or any(k in line for k in ["楼", "室", "馆", "场", "区", "排", "房", "多媒体", "机房", "操场", "阶", "实验室"])):
            room = _clean_cell_text(line, 40)
        elif not teacher and len(line) <= 6 and not re.search(r"\d", line):
            teacher = _clean_cell_text(line, 40)
        elif not room:
            room = _clean_cell_text(line, 40)

    name = _clean_cell_text(name, 80)
    if not name:
        return None

    weeks = []
    for text in week_texts:
        found = parse_weeks(text)
        if found:
            weeks.extend(found)

    return {
        "name": name,
        "teacher": _clean_cell_text(teacher, 40),
        "room": room,
        "weekday": weekday,
        "start_section": start,
        "end_section": end,
        "weeks": sorted(set(weeks)),
        "color": course_color(weekday, start),
    }


def parse_grid_schedule(path: Path) -> dict | None:
    """Parse the grid-style personal timetable (rows=sections, columns=weekdays)."""
    sheets = read_sheets(path)
    if not sheets:
        return None
    for sheet in sheets:
        dict_rows = [cells for _, cells in sheet.rows]
        columns = _grid_weekday_columns(dict_rows)
        if not columns:
            continue
        term = ""
        courses = []
        for row in dict_rows:
            first = str(row.get(1) or "")
            if not term:
                found = re.search(r"\d{4}-\d{4}学年第\d学期", first)
                if found:
                    term = found.group(0)
            section_match = SECTION_ROW_PATTERN.search(first)
            if not section_match:
                if not term:
                    for value in row.values():
                        found = re.search(r"\d{4}-\d{4}学年第\d学期", str(value or ""))
                        if found:
                            term = found.group(0)
                            break
                continue
            start = int(section_match.group(1))
            end = int(section_match.group(2) or start)
            for column, weekday in columns.items():
                cell = str(row.get(column) or "").strip()
                for block in _split_grid_cell(cell):
                    course = _parse_grid_course_block(block, weekday, start, end)
                    if course:
                        courses.append(course)
        if courses:
            return {
                "name": "我的课表",
                "term": term or _find_term(sheet.title, path.stem) or "导入课表",
                "courses": normalize_courses(courses),
            }
    return None


def parse_detail_schedule(path: Path) -> dict | None:
    """Read the course-detail sheet from Excel/HTML/CSV without requiring Excel itself."""
    sheets = read_sheets(path)
    if not sheets:
        return None

    target_rows = None
    sheet_titles = [sheet.title for sheet in sheets]

    # 优先找明确标明“课程明细”或“明细”的工作表
    for sheet in sheets:
        dict_rows = [cells for _, cells in sheet.rows]
        if any("明细" in str(row.get(1, "")) for row in dict_rows):
            target_rows = dict_rows
            break

    # 若无专门标明“明细”的表，则按表头特征匹配（必须包含“星期”和“课程”列）
    if not target_rows:
        for sheet in sheets:
            dict_rows = [cells for _, cells in sheet.rows]
            header_idx, cols = _find_detail_header(dict_rows)
            if header_idx is not None and cols.get("name"):
                target_rows = dict_rows
                break

    if not target_rows:
        return None

    title = str(target_rows[0].get(1) or "")
    term = _find_term(title, *sheet_titles, path.stem) or "导入课表"
    header_index, columns = _find_detail_header(target_rows)
    if header_index is None or not columns.get("name"):
        header_index, columns = 1, {"weekday": 1, "section": 2, "name": 3, "teacher": 4, "weeks": 5, "room": 6}
    # 明细表里连堂课是拆成多行的（1-2 节与 3-4 节各一行），需合并后才与 AI 结果同形
    courses = normalize_courses(_detail_courses(target_rows, header_index, columns))
    # 标题只是明细表自己的 sheet 名（如“课程明细速查表(某某)”），模板差异大无法可靠剥出姓名，
    # 因此兜底路径统一用“我的课表”；真实课表名交由 AI 主链路从首页大标题提取
    return {"name": "我的课表", "term": term, "courses": courses} if courses else None


def parse_excel_schedule(path: Path) -> dict | None:
    """按明细表优先、网格表兜底的顺序解析课表文件。"""
    return parse_detail_schedule(path) or parse_grid_schedule(path)


parse_xlsx_schedule = parse_excel_schedule

