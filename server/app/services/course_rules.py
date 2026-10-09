"""Course value serialization and per-week collision rules."""
import json

from ..schemas import CourseIn


def adjustment_conflicts(db, course_id: int, week: int, weekday: int, start_section: int, end_section: int) -> bool:
    owner = db.execute("SELECT schedule_id FROM courses WHERE id=%s", (course_id,)).fetchone()
    if not owner:
        return False
    rows = db.execute(
        """SELECT c.*, a.week AS adjusted_week, a.weekday AS adjusted_weekday,
                  a.start_section AS adjusted_start, a.end_section AS adjusted_end
           FROM courses c LEFT JOIN course_adjustments a
             ON a.course_id=c.id AND a.week=%s
           WHERE c.schedule_id=%s AND c.id<>%s""",
        (week, owner["schedule_id"], course_id),
    ).fetchall()
    for row in rows:
        if row["weeks"] and week not in row["weeks"]:
            continue
        other_day = row["adjusted_weekday"] if row["adjusted_week"] is not None else row["weekday"]
        other_start = row["adjusted_start"] if row["adjusted_week"] is not None else row["start_section"]
        other_end = row["adjusted_end"] if row["adjusted_week"] is not None else row["end_section"]
        if other_day == weekday and start_section <= other_end and end_section >= other_start:
            return True
    return False


def course_row_values(course: CourseIn):
    data = course.model_dump()
    return (
        data["schedule_id"],
        data["name"],
        data["teacher"],
        data["room"],
        data["weekday"],
        data["start_section"],
        data["end_section"],
        json.dumps(data["weeks"]),
        data["color"],
    )


