"""Server-owned replies for saved people; model prose cannot change their facts."""
import re
from datetime import date

from .course_reply import DayCourses, render_day

OTHER_TOOLS = {"query_other_day_courses", "check_group_availability", "compare_other_week_courses"}
PERSON_FIELDS = ("name", "remark", "student_id", "class_name", "display_name", "major_name")
STRONG_OTHER = re.compile(r"他人|室友|同学|搭子|舍友|共同|谁.{0,8}(?:有空|空闲)|我和|我与|和我|与我")
WEAK_GROUP = re.compile(r"我们|咱们")
GROUP_HINT = re.compile(r"都|一起|共同|几个|大家|谁|一块")


def mentions_others(text, people=()):
    text = re.sub(r"\s+", "", text)
    return bool(STRONG_OTHER.search(text)) or any(
        str(p.get(k) or "").strip() in text for p in people for k in PERSON_FIELDS if str(p.get(k) or "").strip())


def group_request(text):
    """“我们/咱们”本身常指自己；只有带多人语义时才进入共同空闲范围。"""
    text = re.sub(r"\s+", "", text)
    return bool(WEAK_GROUP.search(text) and GROUP_HINT.search(text))


def mixed_people(text):
    return bool(re.search(r"我和|我与|和我|与我|我们|咱们", text))


def contextual_question(message, history):
    from .orchestrator import is_date_only
    if is_date_only(re.sub(r"\s+", "", message)):
        for item in reversed(history or []):
            role = item.get("role") if isinstance(item, dict) else getattr(item, "type", None)
            if role in {"user", "human"}:
                content = item.get("content", "") if isinstance(item, dict) else item.content
                return message + " " + str(content).split("[消息时间", 1)[0]
    return message


def snapshot_note(person):
    term = person.get("term") or ""
    stamp = str(person.get("updated_at") or person.get("fetched_at") or "")[:10]
    details = "，".join(s for s in (f"{term}学期" if term else "", f"{stamp}保存" if stamp else "") if s)
    return f"（{details}）" if details else ""


def render_other_facts(facts, today: date):
    if not any(f.get("skill") in OTHER_TOOLS for f in facts):
        return None
    relevant = [f for f in facts if f.get("skill") in OTHER_TOOLS | {"query_day_courses"}]
    if any(f["result"].get("error") for f in relevant):
        return None
    parts = []
    for fact in relevant:
        result = fact["result"]
        if fact["skill"] == "compare_other_week_courses":
            person = result["person"]
            name = person["display_name"]
            parts.append(f"{result['start_date']} 至 {result['end_date']}，{name}和我的不同课程："
                         + snapshot_note(person))
            parts.append("按同一天的课程名、上课时间、教师和教室比较，任一不同即列出；基于已保存课表。")
            different = False
            for day in result["days"]:
                for role, label in (("other", name), ("me", "我")):
                    if day[role]["courses"]:
                        different = True
                        parts.append(label + "：\n" + render_day(DayCourses.model_validate(day[role]), today))
            if not different:
                parts.append("这一周双方课程完全一致，没有不同的课程。")
        elif fact["skill"] == "check_group_availability":
            period = {"all": "全天", "morning": "上午", "afternoon": "下午", "evening": "晚上"}[result["period"]]
            parts.append(f"{result['date']}{period}（按已保存课表的上课节次比对）：")
            for p in result["participants"]:
                slots = "、".join(f"{s['start_time']}–{s['end_time']}" for s in p["free_slots"])
                state = "所选时段没有课" if p["completely_free"] else f"所选时段有{p['course_count']}节课"
                parts.append(f"{p['display_name']}：{state}；空闲节次：{slots or '无'}。" + snapshot_note(p))
            common = "、".join(f"{s['start_time']}–{s['end_time']}" for s in result["common_free_slots"])
            parts.append(f"共同空闲节次：{common}。" if common else "所选时段没有共同空闲节次。")
        else:
            name = (result.get("person") or {}).get("display_name") or "我"
            parts.append(name + snapshot_note(result.get("person") or {}) + "：\n" + render_day(DayCourses.model_validate(result), today))
    return "\n\n".join(dict.fromkeys(parts))
