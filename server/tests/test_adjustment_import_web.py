from app.adjustment_ai import VisionAdjustment, _extract_json
from app.routers.adjustments import match_course, normalized, valid_image_signature


def test_extract_fenced_json():
    assert _extract_json('```json\n{"adjustments": []}\n```') == '{"adjustments": []}'


def test_vision_adjustment_validation():
    row = VisionAdjustment(
        course_name="  高等数学  ", teacher="张老师", week=3,
        old_weekday=1, old_start_section=1, old_end_section=2, old_room="北201",
        new_weekday=4, new_start_section=5, new_end_section=6, new_room="南204",
    )
    assert row.course_name == "高等数学"
    assert row.new_weekday == 4


def test_match_course_uses_original_occurrence():
    courses = [{"id": 9, "name": "习近平新时代中国特色社会主义思想概论（思想政治类）-理论031",
                "teacher": "杨玉霜", "weekday": 1, "start_section": 1, "end_section": 2,
                "weeks": [2, 3, 4, 5, 6]}]
    item = {"course_name": "习近平新时代中国特色社会主义思想概论(思想政治类)-理论031",
            "teacher": "杨玉霜", "week": 2, "old_weekday": 1,
            "old_start_section": 1, "old_end_section": 2}
    course, count = match_course(courses, item)
    assert count == 1
    assert course["id"] == 9
    assert normalized("课程（理论）") == normalized("课程-理论")


def test_image_signatures():
    assert valid_image_signature(b"\xff\xd8\xffdata", "image/jpeg")
    assert valid_image_signature(b"\x89PNG\r\n\x1a\ndata", "image/png")
    assert valid_image_signature(b"RIFF1234WEBPdata", "image/webp")
    assert not valid_image_signature(b"not an image", "image/png")
