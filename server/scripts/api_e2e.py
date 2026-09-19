"""端到端自测：登录 -> 建课表/课程 -> 调课/冲突 -> drag 更新 -> 记录 -> parse 管道

运行前置：server/.env 已配置 DATABASE_URL 与 WECHAT_DEV_OPENID，且 uvicorn 已在 8010 端口运行。
"""
import os
import struct
import sys
import zlib
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

SERVER_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(SERVER_ROOT / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]

BASE = "http://127.0.0.1:8010"
c = httpx.Client(base_url=BASE, timeout=90)

def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        sys.exit(1)

# 1. dev 登录
r = c.post("/api/auth/wechat", json={"code": "dev"})
check("dev login", r.status_code == 200 and r.json().get("token"), r.text[:100])
token = r.json()["token"]
H = {"Authorization": f"Bearer {token}"}

# 2. 直接造一个 adjusted 课表 + 两门课（用 API 建原始表再 ensure）
r = c.post("/api/import", headers=H, files={"file": ("t.xlsx", b"not-a-real-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, data={"term_name": "自测学期", "start_date": "2026-09-07", "end_date": "2027-01-24"})
check("import rejects bad file", r.status_code in (400, 422), f"status={r.status_code}")

with psycopg.connect(DATABASE_URL) as db:
    with db.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE openid='local-dev-user'")
        uid = cur.fetchone()[0]
        cur.execute("""INSERT INTO schedules(user_id,name,term,start_date,end_date,variant_type)
            VALUES(%s,'自测课表','自测学期','2026-09-07','2027-01-24','original') RETURNING id""", (uid,))
        sid = cur.fetchone()[0]
        for name, wd, s, e in [("高等数学", 1, 1, 2), ("大学英语", 3, 3, 4)]:
            cur.execute("""INSERT INTO courses(schedule_id,name,teacher,room,weekday,start_section,end_section,weeks,color)
                VALUES(%s,%s,'张老师','A101',%s,%s,%s,'[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]'::jsonb,'#5B8DEF')""", (sid, name, wd, s, e))
        cur.execute("SELECT id,name FROM courses WHERE schedule_id=%s ORDER BY id", (sid,))
        courses = cur.fetchall()
math_id, eng_id = courses[0][0], courses[1][0]

# 3. ensure adjusted 副本
r = c.post(f"/api/schedules/{sid}/adjusted", headers=H)
check("ensure adjusted", r.status_code in (200, 201) and r.json()["created"] is True, r.text[:120])
adj_sid = r.json()["schedule_id"]
math_adj = r.json()["course_map"][str(math_id)]
eng_adj = r.json()["course_map"][str(eng_id)]

# 4. 单周调课成功
r = c.put(f"/api/courses/{math_adj}/adjustments/3?source=drag", headers=H,
          json={"week": 3, "weekday": 5, "start_section": 1, "end_section": 2, "room": "B202"})
check("upsert adjustment", r.status_code == 200, r.text[:150])

# 5. 冲突校验：把英语调到周五 2-3 节（与数学调课后 1-2 重叠）
r = c.put(f"/api/courses/{eng_adj}/adjustments/3", headers=H,
          json={"week": 3, "weekday": 5, "start_section": 2, "end_section": 3, "room": ""})
check("adjustment conflict rejected", r.status_code == 409, f"status={r.status_code} {r.text[:80]}")

# 6. apply 带冲突的批量调课被拒
r = c.post("/api/adjustments/apply", headers=H, json={"schedule_id": adj_sid, "items": [
    {"course_id": eng_adj, "week": 3, "weekday": 5, "start_section": 1, "end_section": 2, "room": ""}]})
check("apply conflict rejected", r.status_code == 409, f"status={r.status_code} {r.text[:80]}")

# 7. apply 正常批量调课
r = c.post("/api/adjustments/apply", headers=H, json={"schedule_id": adj_sid, "items": [
    {"course_id": eng_adj, "week": 4, "weekday": 4, "start_section": 3, "end_section": 4, "room": "C301"}]})
check("apply ok", r.status_code == 200 and r.json()["applied"] == 1, r.text[:100])

# 8. 整学期拖拽更新（source=drag）
with psycopg.connect(DATABASE_URL) as db:
    with db.cursor() as cur:
        cur.execute("SELECT weekday,start_section,end_section,weeks,color,name,teacher,room FROM courses WHERE id=%s", (eng_adj,))
        wd, s, e, weeks, color, name, teacher, room = cur.fetchone()
r = c.put(f"/api/courses/{eng_adj}?source=drag", headers=H, json={
    "schedule_id": adj_sid, "name": name, "teacher": teacher, "room": room,
    "weekday": 2, "start_section": 5, "end_section": 6, "weeks": weeks, "color": color})
check("update course drag", r.status_code == 200 and r.json()["weekday"] == 2, r.text[:150])
r = c.get("/api/adjustments/records", headers=H, params={"schedule_id": adj_sid})
drag_logs = [x for x in r.json() if x["action_type"] == "drag_move"]
check("drag_move logged", len(drag_logs) >= 1 and "所有周次" in drag_logs[0]["description"], str(len(drag_logs)))

# 9. records 详情 can_revoke
check("records can_revoke", any(d.get("can_revoke") for x in r.json() for d in (x.get("details") or [])))

# 10. parse 端点：非法类型拒绝 + 真实 PNG 走到视觉模型（1x1 PNG 应返回 422 无有效记录）
r = c.post("/api/adjustments/parse", headers=H, files={"file": ("a.txt", b"hello", "text/plain")}, data={"schedule_id": str(adj_sid)})
check("parse rejects non-image", r.status_code == 400, f"status={r.status_code}")
def tiny_png():
    def chunk(typ, data):
        c_ = struct.pack(">I", len(data)) + typ + data
        return c_ + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
r = c.post("/api/adjustments/parse", headers=H, files={"file": ("a.png", tiny_png(), "image/png")}, data={"schedule_id": str(adj_sid)})
check("parse pipeline reached vision model", r.status_code in (422, 200), f"status={r.status_code} {r.text[:120]}")

# 11. 清理
c.delete(f"/api/schedules/{adj_sid}", headers=H)
c.delete(f"/api/schedules/{sid}", headers=H)
print("ALL E2E TESTS PASSED")
