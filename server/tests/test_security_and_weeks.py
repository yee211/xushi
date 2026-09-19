"""纯单元测试：周次解析与文件安全校验（合并自小程序版，适配统一读取层）。"""
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app import excel  # noqa: E402
from app.parser import parse_weeks  # noqa: E402


def test_parse_weeks_ranges_and_parity():
    assert parse_weeks("1-16周") == list(range(1, 17))
    assert parse_weeks("1-9(单)") == [1, 3, 5, 7, 9]
    assert parse_weeks("2-10(双)") == [2, 4, 6, 8, 10]
    assert parse_weeks("1-5,8,10-12周") == [1, 2, 3, 4, 5, 8, 10, 11, 12]
    assert parse_weeks("18") == [18]
    assert parse_weeks("") == []


def test_detect_format(make_file):
    assert excel.detect_format(make_file("a.xlsx", b"PK\x03\x04rest")) == "ooxml"
    assert excel.detect_format(make_file("a.xls", b"\xd0\xcf\x11\xe0rest")) == "biff"
    assert excel.detect_format(make_file("a.xls", b"<html><body><table><tr><td>x</td></tr></table>")) == "html"
    assert excel.detect_format(make_file("a.xls", "课程,教师\n高数,张三\n".encode("gb18030"))) == "csv"
    assert excel.detect_format(make_file("empty.xlsx", b"   \n")) == "empty"


def test_validate_excel_container_rejects_spoofed_extension(make_file):
    html_bytes = b"<html><body><table><tr><td>x</td></tr></table></body></html>"
    spoofed = make_file("fake.xlsx", html_bytes)
    with pytest.raises(ValueError):
        excel.validate_excel_container(spoofed, ".xlsx")


def test_validate_excel_container_allows_real_ooxml(make_file):
    import zipfile
    target = tmp_zip(make_file, "real.xlsx")
    with zipfile.ZipFile(target) as archive:  # 确认确实是合法 ooxml 容器
        assert archive.testzip() is None
    excel.validate_excel_container(target, ".xlsx")


def tmp_zip(make_file, name: str) -> Path:
    import zipfile
    target = make_file(name, b"")
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return target


def test_validate_excel_container_rejects_zip_bomb(tmp_path):
    import zipfile
    target = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (8 * 1024 * 1024))
    with pytest.raises(ValueError):
        excel.validate_excel_container(target, ".xlsx")


def test_validate_excel_container_entry_limit(tmp_path):
    import zipfile
    target = tmp_path / "many.xlsx"
    with zipfile.ZipFile(target, "w") as archive:
        for index in range(2100):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", "<x/>")
    with pytest.raises(ValueError):
        excel.validate_excel_container(target, ".xlsx")
