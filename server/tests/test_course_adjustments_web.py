import pytest
from pydantic import ValidationError

from app.schemas import CourseAdjustmentIn, CourseIn


def test_course_adjustment_schema():
    payload = CourseAdjustmentIn(
        week=6,
        weekday=4,
        start_section=3,
        end_section=4,
        room="南 312",
    )
    assert payload.week == 6
    assert payload.weekday == 4
    assert payload.room == "南 312"


@pytest.mark.parametrize(
    ("field", "value"),
    [("week", 31), ("weekday", 0), ("start_section", 13), ("end_section", 0)],
)
def test_course_adjustment_rejects_out_of_range(field, value):
    data = {"week": 6, "weekday": 4, "start_section": 3, "end_section": 4}
    data[field] = value
    with pytest.raises(ValidationError):
        CourseAdjustmentIn(**data)


def test_course_input_cleans_text_and_validates_color():
    course = CourseIn(
        schedule_id=1, name="  高等数学  ", teacher=" 张老师 ", room=" 教101 ",
        weekday=1, start_section=1, end_section=2, weeks=[2, 1, 2], color="#A1b2C3",
    )
    assert (course.name, course.teacher, course.room) == ("高等数学", "张老师", "教101")
    assert course.weeks == [1, 2]

    with pytest.raises(ValidationError):
        CourseIn(schedule_id=1, name="   ", weekday=1, start_section=1, end_section=2)
    with pytest.raises(ValidationError):
        CourseIn(schedule_id=1, name="课程", weekday=1, start_section=1, end_section=2, color="red")
