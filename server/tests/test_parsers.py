"""本地 Excel 解析器回归：ooxml 明细表 / 网格表 / 表头映射 / .xls(biff) / 假 xls(html, csv)。"""
import sys
from pathlib import Path

from openpyxl import Workbook

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.excel import read_sheets  # noqa: E402
from app.parser import parse_detail_schedule, parse_grid_schedule  # noqa: E402


def read_html_table(path):
    """等价旧接口：取第一张表的二维文本网格。"""
    sheet = read_sheets(path)[0]
    max_col = max((max(cells) for _, cells in sheet.rows), default=0)
    return [[cells.get(col, "") for col in range(1, max_col + 1)] for _, cells in sheet.rows]


def read_csv_rows(path):
    sheet = read_sheets(path)[0]
    max_col = max((max(cells) for _, cells in sheet.rows), default=0)
    return [[cells.get(col, "") for col in range(1, max_col + 1)] for _, cells in sheet.rows]


def build_detail_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "2026-2027学年第1学期课程明细"
    headers = ["星期", "节次", "课程名称", "教师", "周次", "教室"]
    for col, title in enumerate(headers, 1):
        ws.cell(row=2, column=col, value=title)
    rows = [
        ("星期一", "1-2", "高等数学", "张三", "1-16周", "A101"),
        ("星期一", "3-4", "高等数学", "张三", "1-16周", "A101"),
        ("星期三", "5", "数字逻辑", "李四", "2-9(单)", "B202"),
        ("星期五", "7-8", "大学英语", "王五", "4-15周", "C303"),
    ]
    for index, row in enumerate(rows, 3):
        for col, value in enumerate(row, 1):
            ws.cell(row=index, column=col, value=value)
    wb.save(path)


def test_parse_detail_sheet_with_header_mapping(tmp_path):
    target = tmp_path / "detail.xlsx"
    build_detail_xlsx(target)
    parsed = parse_detail_schedule(target)
    assert parsed, "表头映射路径应能解析"
    assert parsed["term"] == "2026-2027学年第1学期"
    merged = {(c["weekday"], c["start_section"], c["end_section"]): c for c in parsed["courses"]}
    # 连堂 1-2 + 3-4 合并为 1-4
    assert (1, 1, 4) in merged
    assert merged[(1, 1, 4)]["name"] == "高等数学"
    # 合并语义取自网页母版：孤立单节自动扩展为两节连堂块（5 -> 5-6）
    assert merged[(3, 5, 6)]["weeks"] == [3, 5, 7, 9]
    assert merged[(5, 7, 8)]["name"] == "大学英语"


def test_parse_detail_sheet_legacy_layout(tmp_path):
    """旧版固定列位（A=课程明细标题行）也应解析。"""
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "课程明细"
    for col, title in enumerate(["星期", "节次", "课程", "教师", "周次", "教室"], 1):
        ws.cell(row=2, column=col, value=title)
    ws["A3"], ws["B3"], ws["C3"], ws["D3"], ws["E3"], ws["F3"] = "星期二", "3-4", "操作系统", "赵六", "2-13周", "D404"
    target = tmp_path / "legacy.xlsx"
    wb.save(target)
    parsed = parse_detail_schedule(target)
    assert parsed and len(parsed["courses"]) == 1
    course = parsed["courses"][0]
    assert (course["weekday"], course["start_section"], course["end_section"]) == (2, 3, 4)
    assert course["teacher"] == "赵六" and course["room"] == "D404"


def test_parse_grid_xlsx(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "2026-2027学年第1学期"
    for col, title in enumerate(["节次", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"], 1):
        ws.cell(row=2, column=col, value=title)
    ws["A3"] = "第1节"
    ws["B3"] = "物理\n钱七\nB101\n1-16周"
    ws["C3"] = "化学\n孙八\nB102\n1-8周"
    ws["A4"] = "第2节"
    ws["B4"] = "物理\n钱七\nB101\n1-16周"
    target = tmp_path / "grid.xlsx"
    wb.save(target)
    parsed = parse_grid_schedule(target)
    assert parsed and len(parsed["courses"]) == 2
    physics = next(c for c in parsed["courses"] if c["name"] == "物理")
    assert (physics["start_section"], physics["end_section"]) == (1, 2)


def test_fake_xls_html(tmp_path):
    target = tmp_path / "export.xls"
    target.write_bytes(
        "<html><body><table><tr><td>星期</td><td>节次</td><td>课程</td></tr>"
        "<tr><td>星期四</td><td>1-2</td><td>体育</td></tr></table></body></html>".encode())
    rows = read_html_table(target)
    assert rows[1] == ["星期四", "1-2", "体育"]
    parsed = parse_detail_schedule(target)
    assert parsed and parsed["courses"][0]["name"] == "体育"
    assert parsed["courses"][0]["weekday"] == 4


def test_fake_xls_csv_gb18030(tmp_path):
    target = tmp_path / "export.xls"
    target.write_bytes("星期,节次,课程,教师,周次,教室\n星期五,1-2,网络安全,周九,1-16周,E501\n".encode("gb18030"))
    rows = read_csv_rows(target)
    assert rows[1][2] == "网络安全"
    parsed = parse_detail_schedule(target)
    assert parsed and parsed["courses"][0]["name"] == "网络安全"
    assert parsed["courses"][0]["weeks"] == list(range(1, 17))


def test_fake_xls_multi_table_with_rowspan(tmp_path):
    """高校正方教务系统导出常见结构：表1为学生信息表，表2为课程网格并包含 rowspan/colspan。"""
    target = tmp_path / "xskb.xls"
    html = """
    <html>
    <body>
    <table id="table1">
      <tr><td>学号：20230001</td><td>姓名：李雷</td><td>院系：计算机系</td></tr>
    </table>
    <table id="Table6" class="blacktab">
      <tr><td>时间</td><td>星期一</td><td>星期二</td><td>星期三</td><td>星期四</td><td>星期五</td></tr>
      <tr>
        <td rowspan="2">1-2节</td>
        <td>【离散数学】<br>教师: 王老师<br>周次: 1-16周<br>地点: 7-南312</td>
        <td></td>
        <td></td>
        <td></td>
        <td></td>
      </tr>
      <tr>
        <td></td>
        <td></td>
        <td></td>
        <td></td>
      </tr>
    </table>
    </body>
    </html>
    """
    target.write_bytes(html.encode("utf-8"))
    parsed = parse_grid_schedule(target)
    assert parsed is not None
    assert len(parsed["courses"]) >= 1
    c = parsed["courses"][0]
    assert c["name"] == "离散数学"
    assert c["weekday"] == 1
    assert c["room"] == "7-南312"
    assert c["teacher"] == "王老师"


def test_serialize_workbook_universal(tmp_path):
    """测试通用序列化函数：支持 .xls (HTML 伪装表格) 提取单元格给大模型。"""
    from app.ai import serialize_workbook
    target = tmp_path / "xskb.xls"
    target.write_bytes(
        "<html><body><table><tr><td>星期</td><td>节次</td><td>课程</td></tr>"
        "<tr><td>星期一</td><td>1-2</td><td>高等数学</td></tr></table></body></html>".encode()
    )
    serialized = serialize_workbook(target)
    assert "=== SHEET 1:" in serialized
    assert "ROW 1:" in serialized
    assert 'A1="星期"' in serialized
    assert 'C2="高等数学"' in serialized

