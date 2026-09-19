import zipfile

import pytest
from openpyxl import Workbook

from app.excel import detect_format, validate_excel_container


def test_valid_xlsx_is_accepted(tmp_path):
    path = tmp_path / "schedule.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "课程表"
    workbook.save(path)
    workbook.close()
    assert detect_format(path) == "ooxml"
    assert validate_excel_container(path, ".xlsx") == "ooxml"


def test_extension_content_mismatch_is_rejected(tmp_path):
    path = tmp_path / "fake.xlsx"
    path.write_text("not an excel file", encoding="utf-8")
    with pytest.raises(ValueError, match="扩展名不匹配"):
        validate_excel_container(path, ".xlsx")


def test_extreme_zip_ratio_is_rejected(tmp_path):
    path = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "0" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="异常压缩"):
        validate_excel_container(path, ".xlsx")
