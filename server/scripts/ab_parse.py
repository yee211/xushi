"""对比不同 AI_MODEL 对同一份教务课表 Excel 的解析质量。

用法：
    AI_MODEL=qwen3.7-flash-2026-07-15 python scripts/ab_parse.py
    AI_MODEL=qwen3.8-flash python scripts/ab_parse.py
"""
import os
import sys
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ai import parse_with_ai  # noqa: E402


# 典型教务系统导出布局：行=节次，列=星期；单元格内 换行 分隔 课程/教师/教室/周次
def build_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "课表"
    ws["A1"] = "2026-2027学年第一学期"
    headers = ["节次", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    for col, title in enumerate(headers, 1):
        ws.cell(row=2, column=col, value=title)
    section_rows = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 8: 10, 9: 11, 10: 12}
    for section, row in section_rows.items():
        ws.cell(row=row, column=1, value=f"第{section}节")

    def put(weekday: int, section: int, text: str) -> None:
        ws.cell(row=section_rows[section], column=weekday + 1, value=text)

    # 先铺整周课程设计（第18周全天 1-8 节，周一至周五），再让常规课覆盖个别单元格
    design = "操作系统课程设计\n邓佳\n4-南509\n第18周"
    design2 = "数字逻辑课程设计\n谭鹏程\n4-北404\n第19周"
    for weekday in range(1, 6):
        for section in range(1, 9):
            put(weekday, section, design if weekday % 2 == 1 or section != 5 else design2)
    # 单双周异教室
    put(6, 3, "操作系统\n邓佳\n7-南313\n2-13周(单)")
    put(6, 4, "操作系统\n邓佳\n7-南313\n2-13周(单)")
    put(6, 5, "操作系统\n邓佳\n4-南403\n3-13周(双)")
    put(6, 6, "操作系统\n邓佳\n4-南403\n3-13周(双)")
    # 普通两周一次课
    put(4, 3, "离散数学\n吴艳辉\n7-南402\n2-17周")
    put(4, 4, "离散数学\n吴艳辉\n7-南402\n2-17周")
    put(4, 5, "体育4\n陈瑞宁\n足球场\n2-17周")
    put(4, 6, "体育4\n陈瑞宁\n足球场\n2-17周")
    put(5, 3, "大学英语A4\n鲁琦\n7-南210\n4-15周")
    put(5, 4, "大学英语A4\n鲁琦\n7-南210\n4-15周")
    put(3, 1, "数字逻辑\n谭鹏程\n7-南405\n2-9周(单)")
    put(3, 2, "数字逻辑\n谭鹏程\n7-南405\n2-9周(单)")
    put(1, 7, "毛泽东思想和中国特色社会主义理论体系概论\n康文艳\n7-中301\n2-13周")
    put(1, 8, "毛泽东思想和中国特色社会主义理论体系概论\n康文艳\n7-中301\n2-13周")
    wb.save(path)


def main() -> None:
    path = Path(__file__).resolve().parent.parent / "data" / "ab_test_schedule.xlsx"
    build_workbook(path)
    print("model:", os.getenv("AI_MODEL"))
    parsed, engine = parse_with_ai(path)
    print("engine:", engine)
    if not parsed:
        print("PARSE FAILED")
        return
    print("name:", parsed["name"], "| term:", parsed["term"], "| courses:", len(parsed["courses"]))
    for course in sorted(parsed["courses"], key=lambda c: (c["weekday"], c["start_section"])):
        weeks = ",".join(str(w) for w in course["weeks"])
        print(f"  周{course['weekday']} {course['start_section']}-{course['end_section']}节 "
              f"{course['name']} / {course['teacher']} / {course['room']} / [{weeks}]")


if __name__ == "__main__":
    main()
