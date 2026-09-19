"""教务系统网页（HTML）课表确定性解析器。

支持从各类高校教务系统（正方、强智、青果、URP 等）的网页课表中确定性提取课程：
1. 课程明细表（Detail Table）：每行为一门课程，包含星期、节次、课程名、教师、周次、教室等列。
2. 课程矩阵表（Grid Table）：行表示节次（1-12 节），列表示星期（周一至周日），单元格内包含课程信息。

若本模块未能识别出课程，会由调用方无缝回退至大模型（DeepSeek）进行 AI 兜底解析。
"""
import json
import re
from html.parser import HTMLParser

from .parser import (
    _find_detail_header,
    _find_term,
    _grid_weekday_columns,
    _is_campus_or_meta,
    _parse_grid_course_block,
    _split_grid_cell,
    normalize_courses,
    parse_weeks,
)


class MatrixTableExtractor(HTMLParser):
    """从 HTML 中提取所有表格结构，支持 rowspan 和 colspan，生成对齐的 2D 单元格矩阵。"""

    def __init__(self):
        super().__init__()
        self.tables = []  # list of list of dicts: [table][row][col] -> cell
        self._current_table_rows = None
        self._current_row_cells = None
        self._current_cell_attrs = {}
        self._cell_lines = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._current_table_rows = []
        elif tag == "tr":
            if self._current_table_rows is not None:
                self._current_row_cells = []
        elif tag in ("td", "th"):
            if self._current_row_cells is not None:
                self._in_cell = True
                self._cell_lines = []
                self._current_cell_attrs = dict(attrs)
        elif tag == "br":
            if self._in_cell:
                self._cell_lines.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th"):
            if self._in_cell and self._current_row_cells is not None:
                text = "".join(self._cell_lines).strip()
                try:
                    rowspan = int(self._current_cell_attrs.get("rowspan", 1))
                except (ValueError, TypeError):
                    rowspan = 1
                try:
                    colspan = int(self._current_cell_attrs.get("colspan", 1))
                except (ValueError, TypeError):
                    colspan = 1
                self._current_row_cells.append({
                    "text": text,
                    "rowspan": max(1, rowspan),
                    "colspan": max(1, colspan),
                })
                self._in_cell = False
                self._cell_lines = []
        elif tag == "tr":
            if self._current_table_rows is not None and self._current_row_cells is not None:
                if self._current_row_cells:
                    self._current_table_rows.append(self._current_row_cells)
                self._current_row_cells = None
        elif tag == "table":
            if self._current_table_rows is not None:
                matrix = self._build_matrix(self._current_table_rows)
                if matrix:
                    self.tables.append(matrix)
                self._current_table_rows = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell_lines.append(data)

    def _build_matrix(self, raw_rows: list[list[dict]]) -> list[list[dict]]:
        if not raw_rows:
            return []
        grid = {}
        for r, row in enumerate(raw_rows):
            c = 0
            for cell in row:
                while (r, c) in grid:
                    c += 1
                rowspan = cell["rowspan"]
                colspan = cell["colspan"]
                for dr in range(rowspan):
                    for dc in range(colspan):
                        target_pos = (r + dr, c + dc)
                        if target_pos not in grid:
                            grid[target_pos] = {
                                "text": cell["text"],
                                "rowspan": rowspan,
                                "colspan": colspan,
                                "is_origin": (dr == 0 and dc == 0),
                            }
                c += colspan

        if not grid:
            return []
        total_rows = max(pos[0] for pos in grid.keys()) + 1
        total_cols = max(pos[1] for pos in grid.keys()) + 1
        res = []
        for r in range(total_rows):
            row_list = []
            for col in range(total_cols):
                row_list.append(grid.get((r, col), {
                    "text": "",
                    "rowspan": 1,
                    "colspan": 1,
                    "is_origin": True,
                }))
            res.append(row_list)
        return res


SimpleHTMLTableExtractor = MatrixTableExtractor


def extract_raw_html_payload(payload_str: str) -> list[dict]:
    """处理前端回传的 payload（可能是单个 HTML 字符串，也可能是 JSON 数组包含多个 frame）。"""
    payload_str = (payload_str or "").strip()
    if not payload_str:
        return []

    # 优先尝试作为 JSON 解析（WebView 遍历多 frame 时回传）
    if payload_str.startswith("[") or payload_str.startswith("{"):
        try:
            parsed = json.loads(payload_str)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass

    return [{"url": "", "title": "", "html": payload_str}]


def _parse_html_detail_table(rows: list) -> list[dict]:
    """解析明细型课表（如 URP、强智明细清单）。"""
    if not rows or len(rows) < 2:
        return []

    # 兼容 list of list of dict (来自 MatrixTableExtractor) 或 list of list of str
    first_cell = rows[0][0] if rows[0] else ""
    if isinstance(first_cell, dict):
        dict_rows = [{idx + 1: cell.get("text", "") for idx, cell in enumerate(row)} for row in rows]
    else:
        dict_rows = [{idx + 1: cell for idx, cell in enumerate(row)} for row in rows]

    header_idx, cols = _find_detail_header(dict_rows)
    if header_idx is None or not cols.get("name") or not cols.get("weekday"):
        return []

    from .parser import _detail_courses

    raw_courses = _detail_courses(dict_rows, header_idx, cols)
    return normalize_courses(raw_courses)


def parse_qiangzhi_json(raw_data) -> dict | None:
    """解析强智等高校教务系统（如长沙工业学院 tls.ccsut.cn）返回的原生课表 JSON 数据。"""
    if isinstance(raw_data, str):
        raw_data = raw_data.strip()
        if not (raw_data.startswith("{") or raw_data.startswith("[")):
            return None
        try:
            data = json.loads(raw_data)
        except Exception:
            return None
    elif isinstance(raw_data, dict | list):
        data = raw_data
    else:
        return None

    items = None
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            items = data["data"]
        elif isinstance(data.get("courses"), list):
            items = data["courses"]
        elif isinstance(data.get("rows"), list):
            items = data["rows"]
    elif isinstance(data, list):
        items = data

    if not items or not isinstance(items, list):
        return None

    first_few = [it for it in items[:10] if isinstance(it, dict)]
    if not any("kcmc" in it or "jxbmc" in it for it in first_few):
        return None

    courses = []
    term_candidates = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kcmc_raw = it.get("kcmc") or it.get("jxbmc") or it.get("name") or ""
        name = re.sub(r"<[^>]+>", "", str(kcmc_raw)).strip()
        if not name or _is_campus_or_meta(name):
            continue

        tmc_raw = it.get("tmc") or it.get("jsxm") or it.get("teacher") or ""
        teacher = re.sub(r"<[^>]+>", "", str(tmc_raw)).strip()

        croom_raw = it.get("croommc") or it.get("jsmc") or it.get("room") or it.get("jxlmc") or ""
        room = re.sub(r"<[^>]+>", "", str(croom_raw)).strip()
        if _is_campus_or_meta(room) and it.get("jxlmc"):
            room = re.sub(r"<[^>]+>", "", str(it.get("jxlmc"))).strip()

        try:
            weekday = int(it.get("xingqi") or it.get("xq") or it.get("weekday") or 1)
            djc = int(it.get("djc") or it.get("jc") or it.get("section") or 1)
        except (ValueError, TypeError):
            continue

        zcstr = it.get("zcstr") or it.get("zc") or it.get("weeks") or ""
        if isinstance(zcstr, list):
            weeks = [int(w) for w in zcstr if isinstance(w, int) or str(w).isdigit()]
        else:
            weeks = parse_weeks(str(zcstr))

        xnxq = str(it.get("xnxq") or "").strip()
        if xnxq:
            term_candidates.append(xnxq)

        courses.append({
            "name": name,
            "teacher": teacher,
            "room": room,
            "weekday": weekday,
            "start_section": djc,
            "end_section": djc,
            "weeks": weeks,
        })

    normalized = normalize_courses(courses)
    if not normalized:
        return None

    term = "2026-2027学年第1学期"
    if term_candidates:
        first_term = term_candidates[0]
        m = re.match(r"(\d{4}-\d{4})-(\d)", first_term)
        if m:
            term = f"{m.group(1)}学年第{m.group(2)}学期"
        else:
            found = _find_term(first_term)
            if found:
                term = found

    return {
        "name": "长沙工业学院教务课表",
        "term": term,
        "courses": normalized,
    }


def _parse_html_grid_course_block(block: str, weekday: int, start: int, end: int) -> dict | None:
    return _parse_grid_course_block(block, weekday, start, end)


def _parse_html_grid_table(matrix: list) -> list[dict]:
    """解析网格型课表（行=节次，列=星期），支持单元格 rowspan 连堂与列对齐。"""
    if not matrix or len(matrix) < 2:
        return []

    first_cell = matrix[0][0] if matrix[0] else ""
    if isinstance(first_cell, dict):
        text_rows = [{idx + 1: cell.get("text", "") for idx, cell in enumerate(row)} for row in matrix]
    else:
        text_rows = [{idx + 1: str(cell) for idx, cell in enumerate(row)} for row in matrix]
        matrix = [[{"text": str(c), "rowspan": 1, "colspan": 1, "is_origin": True} for c in row] for row in matrix]

    # 寻找包含“星期一/周一”等表头的行
    weekday_cols = {}
    header_row_idx = None
    for r_idx, row in enumerate(text_rows):
        mapping = _grid_weekday_columns([row])
        if len(mapping) >= 3:
            weekday_cols = mapping
            header_row_idx = r_idx
            break

    if not weekday_cols or header_row_idx is None:
        return []

    courses = []
    section_pattern = re.compile(r"(?:第\s*)?(\d+)\s*(?:[-–~到]\s*(\d+))?\s*节?")

    # 从表头之后的每一行寻找节次与课程单元格
    current_start_sec = 1
    for r_idx in range(header_row_idx + 1, len(matrix)):
        row_cells = matrix[r_idx]
        text_row = text_rows[r_idx]

        # 尝试推断当前行的节次
        start_sec = None
        end_sec = None
        for col_idx in (1, 2):
            val = str(text_row.get(col_idx, "")).strip()
            m = section_pattern.search(val)
            if m and m.group(1):
                start_sec = int(m.group(1))
                end_sec = int(m.group(2)) if m.group(2) else start_sec
                break

        if start_sec is None:
            start_sec = current_start_sec
            end_sec = current_start_sec + 1
            current_start_sec += 2
        else:
            current_start_sec = max(end_sec + 1, current_start_sec)

        # 遍历每个星期的列
        for col_idx, weekday in weekday_cols.items():
            if col_idx - 1 >= len(row_cells):
                continue
            cell = row_cells[col_idx - 1]
            if not cell.get("is_origin", True):
                continue

            cell_text = str(cell.get("text", "")).strip()
            if not cell_text or cell_text in ("-", "/", "无", "休"):
                continue

            # 若单元格设置了 rowspan >= 2，直接使用跨度计算 end_sec（例如 1 节 + rowspan 2 -> 1-2 节）
            span = cell.get("rowspan", 1)
            if span >= 2:
                c_start = start_sec
                c_end = start_sec + span - 1
            else:
                c_start = start_sec
                c_end = end_sec

            blocks = _split_grid_cell(cell_text)
            for block in blocks:
                course = _parse_grid_course_block(block, weekday, c_start, c_end)
                if course:
                    courses.append(course)

    return normalize_courses(courses)


def parse_html_schedule(payload_str: str) -> dict | None:
    """确定性解析教务系统导出的网页、DOM 结构或原生 JSON 响应。

    返回字典结构：
    {
        "name": "课表名称",
        "term": "2026-2027学年第1学期",
        "courses": [...]
    }
    如果确定性规则未匹配到任何课程，返回 None。
    """
    # 0. 优先尝试解析原生教务系统 REST JSON 响应（如长沙工业学院 强智教务）
    json_res = parse_qiangzhi_json(payload_str)
    if json_res:
        return json_res

    frames = extract_raw_html_payload(payload_str)
    if not frames:
        return None

    # 0.1 检查多 frame payload 中是否有 frame 携带 JSON
    for frame in frames:
        for candidate in (frame.get("text"), frame.get("html")):
            if candidate:
                sub_res = parse_qiangzhi_json(candidate)
                if sub_res:
                    return sub_res

    all_titles = []
    all_courses = []

    for frame in frames:
        raw_html = frame.get("html") or frame.get("tablesHtml") or ""
        title = frame.get("title") or ""
        text = frame.get("text") or ""
        if title:
            all_titles.append(title)

        if not raw_html and text:
            continue

        extractor = SimpleHTMLTableExtractor()
        try:
            extractor.feed(raw_html)
        except Exception:
            continue

        for table in extractor.tables:
            # 1. 尝试按明细表解析
            detail_res = _parse_html_detail_table(table)
            if detail_res:
                all_courses.extend(detail_res)
                continue

            # 2. 尝试按网格表解析
            grid_res = _parse_html_grid_table(table)
            if grid_res:
                all_courses.extend(grid_res)

    if not all_courses:
        return None

    courses = normalize_courses(all_courses)
    if not courses:
        return None

    # 从所有标题与文本中推算学期标识
    combined_meta = " ".join(all_titles) + " " + payload_str[:2000]
    term = _find_term(combined_meta) or "2026-2027学年第1学期"

    return {
        "name": "长沙工业学院教务课表",
        "term": term,
        "courses": courses,
    }
