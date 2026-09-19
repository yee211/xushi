"""Unit tests for deterministic HTML schedule parsing."""
from app.html_parser import parse_html_schedule


def test_parse_html_detail_table():
    html_content = """
    <html>
    <head><title>2025-2026学年第1学期学生课表</title></head>
    <body>
        <h2>长沙工业学院 学生个人课表</h2>
        <table border="1">
            <thead>
                <tr>
                    <th>序号</th>
                    <th>课程名称</th>
                    <th>授课教师</th>
                    <th>星期</th>
                    <th>节次</th>
                    <th>周次</th>
                    <th>上课地点</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>1</td>
                    <td>旅游规划与开发</td>
                    <td>王教授</td>
                    <td>星期一</td>
                    <td>1-2节</td>
                    <td>1-16周</td>
                    <td>7-南302</td>
                </tr>
                <tr>
                    <td>2</td>
                    <td>大学英语(3)</td>
                    <td>李老师</td>
                    <td>星期三</td>
                    <td>3-4节</td>
                    <td>2-16周(双)</td>
                    <td>4-北105</td>
                </tr>
            </tbody>
        </table>
    </body>
    </html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    assert "2025-2026学年第1学期" in res["term"]
    courses = res["courses"]
    assert len(courses) == 2

    c1 = next(c for c in courses if c["name"] == "旅游规划与开发")
    assert c1["teacher"] == "王教授"
    assert c1["room"] == "7-南302"
    assert c1["weekday"] == 1
    assert c1["start_section"] == 1
    assert c1["end_section"] == 2
    assert c1["weeks"] == list(range(1, 17))

    c2 = next(c for c in courses if c["name"] == "大学英语(3)")
    assert c2["teacher"] == "李老师"
    assert c2["room"] == "4-北105"
    assert c2["weekday"] == 3
    assert c2["start_section"] == 3
    assert c2["end_section"] == 4
    assert c2["weeks"] == [2, 4, 6, 8, 10, 12, 14, 16]


def test_parse_html_grid_table():
    html_content = """
    <html>
    <head><title>2025-2026学年第2学期课表</title></head>
    <body>
        <table>
            <tr>
                <td>节次</td>
                <td>星期一</td>
                <td>星期二</td>
                <td>星期三</td>
                <td>星期四</td>
                <td>星期五</td>
                <td>星期六</td>
                <td>星期日</td>
            </tr>
            <tr>
                <td>1-2节</td>
                <td>饭店管理概论<br>赵老师<br>1-16周<br>实训楼201</td>
                <td></td>
                <td>导游业务<br>陈老师<br>1-8周<br>主楼102</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
        </table>
    </body>
    </html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    assert "2025-2026学年第2学期" in res["term"]
    courses = res["courses"]
    assert len(courses) == 2

    hotel = next(c for c in courses if c["name"] == "饭店管理概论")
    assert hotel["weekday"] == 1
    assert hotel["start_section"] == 1
    assert hotel["end_section"] == 2
    assert hotel["teacher"] == "赵老师"
    assert hotel["room"] == "实训楼201"
    assert hotel["weeks"] == list(range(1, 17))


def test_import_html_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    import app.routers.importer as importer_module
    from app.auth import get_current_user
    from app.main import app

    class Result:
        def __init__(self, row=None):
            self.row = row
        def fetchone(self):
            return self.row

    class MockDb:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def execute(self, sql, params=None):
            if "pg_advisory_xact_lock" in sql:
                return Result()
            if "SELECT * FROM schedules" in sql:
                return Result(None)
            if "INSERT INTO schedules" in sql:
                return Result({"id": 99, "name": "教务在线课表", "term": "2025-2026学年第1学期"})
            raise AssertionError(f"Unexpected SQL: {sql}")
        def cursor(self):
            class MockCursor:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def executemany(self, sql, rows):
                    pass
            return MockCursor()

    monkeypatch.setattr(importer_module, "connect", lambda: MockDb())
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "tester"}

    client = TestClient(app)
    html_payload = """
    <table>
        <tr><th>星期</th><th>节次</th><th>课程名称</th><th>教师</th><th>周次</th><th>地点</th></tr>
        <tr><td>星期一</td><td>1-2</td><td>大数据分析</td><td>钱老师</td><td>1-16周</td><td>机房3</td></tr>
    </table>
    """
    resp = client.post("/api/import-html", json={"data": html_payload})
    assert resp.status_code == 200
    data = resp.json()
    assert data["schedule_id"] == 99
    assert data["imported"] == 1
    assert "deterministic" in data["engine"]


def test_parse_qiangzhi_json():
    import json


    sample = {
        "ret": 0,
        "msg": "操作成功",
        "data": [
            {
                "xnxq": "2026-2027-1",
                "kcmc": '<a href="javascript:void(0);" style="color: red">习近平新时代中国特色社会主义思想概论</a>',
                "zc": "1-1,7-9,11-12",
                "zcstr": "1,7,8,9,11,12",
                "croommc": '<a href="javascript:void(0);">7-北201</a>',
                "tmc": '<a href="javascript:void(0);">杨玉霜</a>',
                "xingqi": 1,
                "djc": 1,
            },
            {
                "xnxq": "2026-2027-1",
                "kcmc": '<a href="javascript:void(0);" style="color: red">习近平新时代中国特色社会主义思想概论</a>',
                "zc": "1-1,7-9,11-12",
                "zcstr": "1,7,8,9,11,12",
                "croommc": '<a href="javascript:void(0);">7-北201</a>',
                "tmc": '<a href="javascript:void(0);">杨玉霜</a>',
                "xingqi": 1,
                "djc": 2,
            },
            {
                "xnxq": "2026-2027-1",
                "kcmc": '<a href="javascript:void(0);">数据采集与预处理</a>',
                "zc": "4-4,8-8,12-12,16-16",
                "zcstr": "4,8,12,16",
                "croommc": '<a href="javascript:void(0);">4-南407</a>',
                "tmc": '<a href="javascript:void(0);">李家瑶</a>',
                "xingqi": 2,
                "djc": 1,
            },
            {
                "xnxq": "2026-2027-1",
                "kcmc": '<a href="javascript:void(0);">数据采集与预处理</a>',
                "zc": "4-4,8-8,12-12,16-16",
                "zcstr": "4,8,12,16",
                "croommc": '<a href="javascript:void(0);">4-南407</a>',
                "tmc": '<a href="javascript:void(0);">李家瑶</a>',
                "xingqi": 2,
                "djc": 2,
            },
        ],
    }
    raw_str = json.dumps(sample)
    res = parse_html_schedule(raw_str)
    assert res is not None
    assert "长沙工业学院" in res["name"]
    assert "2026-2027学年第1学期" in res["term"]
    courses = res["courses"]
    # djc 1 and 2 should be merged into start_section=1, end_section=2
    assert len(courses) == 2

    c1 = next(c for c in courses if c["name"] == "习近平新时代中国特色社会主义思想概论")
    assert c1["teacher"] == "杨玉霜"
    assert c1["room"] == "7-北201"
    assert c1["weekday"] == 1
    assert c1["start_section"] == 1
    assert c1["end_section"] == 2
    assert c1["weeks"] == [1, 7, 8, 9, 11, 12]

    c2 = next(c for c in courses if c["name"] == "数据采集与预处理")
    assert c2["teacher"] == "李家瑶"
    assert c2["room"] == "4-南407"
    assert c2["weekday"] == 2
    assert c2["start_section"] == 1
    assert c2["end_section"] == 2
    assert c2["weeks"] == [4, 8, 12, 16]


def test_html_table_rowspan_and_campus_filter():
    """测试带有 rowspan 跨度和校区名称干扰的网页矩阵课表。"""
    html_content = """
    <table>
        <tr>
            <th>节次</th>
            <th>星期一</th>
            <th>星期二</th>
            <th>星期三</th>
        </tr>
        <tr>
            <td>1</td>
            <td rowspan="2">
                本校区<br>
                大学英语A3<br>
                4-南308<br>
                鲁玲<br>
                3-15周
            </td>
            <td rowspan="2">
                数据库原理与应用<br>
                7-南314<br>
                李锡辉<br>
                1-16周
            </td>
            <td rowspan="2">
                面向对象程序设计<br>
                7-南314<br>
                唐婷<br>
                1-16周
            </td>
        </tr>
        <tr>
            <td>2</td>
        </tr>
        <tr>
            <td>3</td>
            <td rowspan="2">
                数据库原理与应用<br>
                7-南405<br>
                李锡辉<br>
                3-16周
            </td>
            <td></td>
            <td rowspan="2">
                电路与电子技术<br>
                7-南314<br>
                陈奕辰<br>
                1-16周
            </td>
        </tr>
        <tr>
            <td>4</td>
            <td></td>
        </tr>
    </table>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    courses = res["courses"]
    assert len(courses) == 5

    # 1. 验证“本校区”未被误识别为课程名，课程名正确提取为“大学英语A3”
    eng = next(c for c in courses if c["weekday"] == 1 and c["start_section"] == 1)
    assert eng["name"] == "大学英语A3"
    assert eng["room"] == "4-南308"
    assert eng["teacher"] == "鲁玲"
    # 2. 验证连堂跨度：由 rowspan="2" 自动展开为 1-2 节（高度占2节课位置）
    assert eng["start_section"] == 1
    assert eng["end_section"] == 2

    # 3. 验证周二 1-2 节数据库
    db_tue = next(c for c in courses if c["weekday"] == 2 and c["start_section"] == 1)
    assert db_tue["name"] == "数据库原理与应用"
    assert db_tue["room"] == "7-南314"
    assert db_tue["teacher"] == "李锡辉"
    assert db_tue["start_section"] == 1
    assert db_tue["end_section"] == 2

    # 4. 验证周三 3-4 节电路未因前面行的 rowspan 导致列偏移
    circuit = next(c for c in courses if c["weekday"] == 3 and c["start_section"] == 3)
    assert circuit["name"] == "电路与电子技术"
    assert circuit["room"] == "7-南314"
    assert circuit["teacher"] == "陈奕辰"
    assert circuit["start_section"] == 3
    assert circuit["end_section"] == 4


def test_full_user_payload():
    """测试用户提供的真实 76 条教务系统数据原生 JSON 响应。"""
    from pathlib import Path
    clean_file = Path("user_payload_clean.json")
    if not clean_file.exists():
        return
    raw_str = clean_file.read_text(encoding="utf-8")
    res = parse_html_schedule(raw_str)
    assert res is not None
    assert "长沙工业学院" in res["name"]
    assert "2026-2027学年第1学期" in res["term"]
    courses = res["courses"]
    assert len(courses) == 33

    # 验证全部 33 门课程中无一门为单节课（全部为2节或4节连堂大课）
    single_sections = [c for c in courses if c["start_section"] == c["end_section"]]
    assert len(single_sections) == 0

    # 验证课程设计占 4 节连堂 (5-8节)
    design_courses = [c for c in courses if "课程设计" in c["name"]]
    assert len(design_courses) > 0
    for dc in design_courses:
        assert dc["start_section"] == 5
        assert dc["end_section"] == 8
        assert dc["room"] == "4-北403"
        assert dc["teacher"] == "李俊峰"

    # 验证绝无任何课程名为“本校区”
    assert all(c["name"] != "本校区" for c in courses)



def test_grid_weeks_with_inline_parity_no_comma():
    """强智网页单元格中教师与周次同一行、(单)/(双) 后无逗号直连下一区间的形态。

    回归背景：旧版 WEEK_RE 匹配不到 '1-15(单)周'，导致教师串进教室字段
    ('教室=李俊峰 1-15(单)周')、周次全部丢失（界面显示"每周"）。
    """
    html_content = """
    <html><body><table>
        <tr><td>节次</td><td>星期一</td><td>星期三</td><td>星期五</td></tr>
        <tr><td>1</td>
            <td></td><td></td>
            <td>计算机组成原理<br>李俊峰 1-15(单)周<br>7-南407<br></td></tr>
        <tr><td>2</td>
            <td></td><td></td>
            <td>计算机组成原理<br>李俊峰 1-15(单)周<br>7-南407<br></td></tr>
    </table></body></html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    courses = [c for c in res["courses"] if c["name"] == "计算机组成原理"]
    assert len(courses) == 1
    c = courses[0]
    assert c["teacher"] == "李俊峰"
    assert c["room"] == "7-南407"
    assert c["weekday"] == 5
    assert c["start_section"] == 1 and c["end_section"] == 2
    assert c["weeks"] == [1, 3, 5, 7, 9, 11, 13, 15]


def test_grid_multi_course_cell_with_parity_weeks():
    """同一单元格内理论(单)+实践(双)两门课：块需正确拆分，字段不串位。

    回归背景：旧版把单元格解析成一门课——教师=课程名、教室='龙艳军 1-5(单)9-15(单)周'、
    实践课与全部周次丢失。
    """
    html_content = """
    <html><body><table>
        <tr><td>节次</td><td>星期一</td><td>星期四</td><td>星期五</td></tr>
        <tr><td>3</td>
            <td></td>
            <td>计算机网络<br>龙艳军 1-5(单)9-15(单)周<br>7-南312<br>计算机网络<br>龙艳军 4,7,10-16(双)周<br>4-北404<br></td>
            <td></td></tr>
        <tr><td>4</td>
            <td></td>
            <td>计算机网络<br>龙艳军 1-5(单)9-15(单)周<br>7-南312<br>计算机网络<br>龙艳军 4,7,10-16(双)周<br>4-北404<br></td>
            <td></td></tr>
    </table></body></html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    courses = [c for c in res["courses"] if c["name"] == "计算机网络"]
    assert len(courses) == 2
    by_room = {c["room"]: c for c in courses}
    theory = by_room["7-南312"]
    practice = by_room["4-北404"]
    assert all(c["teacher"] == "龙艳军" for c in courses)
    assert theory["weeks"] == [1, 3, 5, 9, 11, 13, 15]
    assert practice["weeks"] == [4, 7, 10, 12, 14, 16]
    assert theory["start_section"] == 3 and theory["end_section"] == 4


def test_grid_mixed_parity_and_plain_weeks():
    """混合形态：'4,7,10-16(双)周'（单双仅修饰尾段区间）与 '3,7-11(单)周'。"""
    from app.parser import parse_weeks

    assert parse_weeks("1-5(单)9-15(单)周") == [1, 3, 5, 9, 11, 13, 15]
    assert parse_weeks("4,7,10-16(双)周") == [4, 7, 10, 12, 14, 16]
    assert parse_weeks("3,7-11(单)周") == [3, 7, 9, 11]
    assert parse_weeks("1-15(单)周") == [1, 3, 5, 7, 9, 11, 13, 15]
    assert parse_weeks("1,7-9,11-12周") == [1, 7, 8, 9, 11, 12]
    assert parse_weeks("1-5(单),9-16(双),18") == [1, 3, 5, 10, 12, 14, 16, 18]

    html_content = """
    <html><body><table>
        <tr><td>节次</td><td>星期一</td><td>星期三</td><td>星期五</td></tr>
        <tr><td>7</td>
            <td></td><td>软件工程<br>杨丽 3,7-11(单)周<br>4-南503<br></td>
            <td>计算机组成原理<br>李俊峰 4,7,10-16(双)周<br>4-南407<br></td></tr>
        <tr><td>8</td>
            <td></td><td>软件工程<br>杨丽 3,7-11(单)周<br>4-南503<br></td>
            <td>计算机组成原理<br>李俊峰 4,7,10-16(双)周<br>4-南407<br></td></tr>
    </table></body></html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    by_name = {c["name"]: c for c in res["courses"]}
    assert by_name["软件工程"]["weeks"] == [3, 7, 9, 11]
    assert by_name["软件工程"]["room"] == "4-南503"
    assert by_name["计算机组成原理"]["weeks"] == [4, 7, 10, 12, 14, 16]
    assert by_name["计算机组成原理"]["room"] == "4-南407"


def test_grid_cell_with_meta_week_line():
    """单元格中的 '每周'/'全周' 等元数据行不应被误认为教师或教室。"""
    html_content = """
    <html><body><table>
        <tr><td>节次</td><td>星期一</td><td>星期二</td><td>星期三</td></tr>
        <tr><td>1</td><td></td><td>大学英语<br>王老师<br>每周<br>7-北102<br></td><td></td></tr>
        <tr><td>2</td><td></td><td>大学英语<br>王老师<br>每周<br>7-北102<br></td><td></td></tr>
    </table></body></html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    courses = [c for c in res["courses"] if c["name"] == "大学英语"]
    assert len(courses) == 1
    c = courses[0]
    assert c["teacher"] == "王老师"
    assert c["room"] == "7-北102"


def test_grid_weeks_parity_with_separator_between_ranges():
    """真实强智网页中两个单周区间之间带逗号/空格分隔符的形态。

    回归背景：线上手机端实测（2026-09）发现 '龙艳军 1-5(单),9-15(单)周' 会被解析成
    教师='龙艳军 1-5(单),' 且丢失周次 1,3,5——(单) 括号后的分隔符曾导致正则
    从第二个区间才开始匹配。
    """
    from app.parser import parse_weeks

    assert parse_weeks("1-5(单),9-15(单)周") == [1, 3, 5, 9, 11, 13, 15]
    assert parse_weeks("1-5(单) 9-15(单)周") == [1, 3, 5, 9, 11, 13, 15]

    html_content = """
    <html><body><table>
        <tr><td>节次</td><td>星期一</td><td>星期四</td><td>星期五</td></tr>
        <tr><td>3</td>
            <td></td>
            <td>计算机网络<br>龙艳军 1-5(单),9-15(单)周<br>7-南312<br></td>
            <td></td></tr>
        <tr><td>4</td>
            <td></td>
            <td>计算机网络<br>龙艳军 1-5(单),9-15(单)周<br>7-南312<br></td>
            <td></td></tr>
    </table></body></html>
    """
    res = parse_html_schedule(html_content)
    assert res is not None
    courses = [c for c in res["courses"] if c["name"] == "计算机网络"]
    assert len(courses) == 1
    c = courses[0]
    assert c["teacher"] == "龙艳军"
    assert c["room"] == "7-南312"
    assert c["weeks"] == [1, 3, 5, 9, 11, 13, 15]
