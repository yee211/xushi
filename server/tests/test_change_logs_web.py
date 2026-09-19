import pytest
from fastapi.testclient import TestClient
from psycopg import connect as pg_connect

from app.auth import get_current_user
from app.db import DATABASE_URL, connect
from app.main import app

client = TestClient(app)


def _is_db_available() -> bool:
    try:
        with pg_connect(DATABASE_URL, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
    except Exception:
        return False


def test_parse_text_endpoint_removed():
    """验证自然语言文本识别接口已彻底移除，请求返回 404/405。"""
    response = client.post("/api/adjustments/parse-text", json={"schedule_id": 1, "text": "调课测试"})
    assert response.status_code in (404, 405)


@pytest.mark.skipif(not _is_db_available(), reason="PostgreSQL not reachable in test environment")
def test_course_change_logs_flow():
    """验证批量调课、拖拽移动与主动编辑在 course_change_logs 中的记录与查询。"""
    app.dependency_overrides[get_current_user] = lambda: {"id": 9999, "username": "log_test_user"}

    try:
        with connect() as db:
            # 清理历史可能存在的测试数据
            db.execute("DELETE FROM users WHERE id=9999")
            db.execute("INSERT INTO users(id, username, email, password_hash) VALUES(9999, 'log_test_user', 'log_test@example.com', 'hash')")
            db.execute(
                "INSERT INTO schedules(id, user_id, name, term, start_date) VALUES(9999, 9999, '测试课表', '2026-秋', '2026-09-01')"
            )
            db.execute(
                """INSERT INTO courses(id, schedule_id, name, teacher, room, weekday, start_section, end_section, weeks, color)
                   VALUES(99991, 9999, '高等数学', '张老师', '教101', 1, 1, 2, '[1,2,3,4,5]'::jsonb, '#ff0000')"""
            )

        # 1. 测试主动编辑课程（修改教室和时间）
        edit_payload = {
            "schedule_id": 9999,
            "name": "高等数学",
            "teacher": "张老师",
            "room": "教202",  # 教室修改
            "weekday": 2,     # 星期修改
            "start_section": 3,
            "end_section": 4,
            "weeks": [1, 2, 3, 4, 5],
            "color": "#ff0000",
        }
        res_edit = client.put("/api/courses/99991?source=manual", json=edit_payload)
        assert res_edit.status_code == 200

        # 2. 测试拖拽移动全学期课程（source=drag）
        drag_all_payload = {
            "schedule_id": 9999,
            "name": "高等数学",
            "teacher": "张老师",
            "room": "教202",
            "weekday": 3,
            "start_section": 5,
            "end_section": 6,
            "weeks": [1, 2, 3, 4, 5],
            "color": "#ff0000",
        }
        res_drag = client.put("/api/courses/99991?source=drag", json=drag_all_payload)
        assert res_drag.status_code == 200

        # 3. 测试拖拽移动单周调课（upsert_adjustment）
        drag_week_payload = {
            "week": 3,
            "weekday": 4,
            "start_section": 7,
            "end_section": 8,
            "room": "教303",
        }
        res_week_drag = client.put("/api/courses/99991/adjustments/3", json=drag_week_payload)
        assert res_week_drag.status_code == 200

        # 4. 测试批量调课应用（apply_notice）
        apply_payload = {
            "schedule_id": 9999,
            "items": [
                {
                    "course_id": 99991,
                    "week": 2,
                    "weekday": 5,
                    "start_section": 1,
                    "end_section": 2,
                    "room": "教404",
                }
            ],
        }
        res_apply = client.post("/api/adjustments/apply", json=apply_payload)
        assert res_apply.status_code == 200

        # 5. 查询 records
        res_records = client.get("/api/adjustments/records?schedule_id=9999")
        assert res_records.status_code == 200
        records = res_records.json()
        assert len(records) >= 4

        # 检查记录类型
        action_types = [r["action_type"] for r in records]
        assert "batch_import" in action_types
        assert "drag_move" in action_types
        assert "manual_edit" in action_types

        # 批量调课记录应包含汇总和详情
        batch_rec = next(r for r in records if r["action_type"] == "batch_import")
        assert "图片识别调课" in batch_rec["title"]
        assert len(batch_rec["details"]) == 1
        assert batch_rec["details"][0]["course_name"] == "高等数学"
        assert batch_rec["details"][0]["can_revoke"] is True

        # 主动编辑记录（验证上课时间和教室地点 diff 均被正确记录）
        edit_rec = next(r for r in records if r["action_type"] == "manual_edit")
        assert edit_rec["title"] == "主动编辑课程"
        assert any(d["label"] == "教室地点" for d in edit_rec["details"])
        assert any(d["label"] == "上课时间" for d in edit_rec["details"])

        # 拖拽移动记录
        drag_recs = [r for r in records if r["action_type"] == "drag_move"]
        assert len(drag_recs) >= 2

        # 6. 测试删除记录（左滑删除/点击删除）
        target_rec_id = edit_rec["id"]
        res_del = client.delete(f"/api/adjustments/records/{target_rec_id}")
        assert res_del.status_code == 204

        # 再次获取列表，已删除记录不应出现
        res_records_after = client.get("/api/adjustments/records?schedule_id=9999")
        assert res_records_after.status_code == 200
        records_after_ids = [r["id"] for r in res_records_after.json()]
        assert target_rec_id not in records_after_ids

        # 删除不存在的记录返回 404
        res_del_404 = client.delete("/api/adjustments/records/999999")
        assert res_del_404.status_code == 404
    finally:
        app.dependency_overrides.clear()
        if _is_db_available():
            with connect() as db:
                db.execute("DELETE FROM users WHERE id=9999")
