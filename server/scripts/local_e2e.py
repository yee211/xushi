"""本地端到端演练：真实 PG + 真实 HTTP 回调链路。

替代腾讯的部分只有两处：加密回调由本脚本用同一套密钥构造，
response_url 指向本脚本起的一个本地接收器。其余全部走真实服务。

用法：先启动 uvicorn（127.0.0.1:8010），再运行本脚本。
"""
import json
import os
import sys
import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))
load_dotenv(SERVER_ROOT / ".env")

from app.wecom import encrypt_message, message_signature  # noqa: E402

BASE = "http://127.0.0.1:8010"
RECEIVER_PORT = 9753
RECEIVER_URL = f"http://127.0.0.1:{RECEIVER_PORT}/reply"
TOKEN = os.environ["WECOM_CALLBACK_TOKEN"]
AES_KEY = __import__("base64").b64decode(os.environ["WECOM_ENCODING_AES_KEY"] + "=")
DB_URL = os.environ["DATABASE_URL"]

replies = []
passed, failed = [], []


def check(name, condition, detail=""):
    (passed if condition else failed).append(f"{name}{'' if condition else '：' + str(detail)}")
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  [{detail}]"))


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        replies.append(json.loads(body))
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"errcode":0}')

    def log_message(self, *args): pass


def wait_reply(index, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(replies) > index:
            return replies[index]
        time.sleep(0.1)
    return None


def send_callback(content, sender, msg_id, response_url=RECEIVER_URL, chat_type="single"):
    payload = {"msgid": msg_id, "aibotid": "local-test-bot", "chattype": chat_type,
               "from": {"userid": sender}, "msgtype": "text", "response_url": response_url,
               "text": {"content": content}}
    encrypt = encrypt_message(json.dumps(payload, ensure_ascii=False), AES_KEY)
    timestamp, nonce = str(int(time.time())), "nonce123"
    signature = message_signature(TOKEN, timestamp, nonce, encrypt)
    return httpx.post(f"{BASE}/api/integrations/wecom/callback",
                      params={"msg_signature": signature, "timestamp": timestamp, "nonce": nonce},
                      content=json.dumps({"encrypt": encrypt}).encode(), timeout=10)


def main():
    server = HTTPServer(("127.0.0.1", RECEIVER_PORT), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # 1. 健康检查 + 专用 E2E 用户（与本地开发账号的旧课表隔离，避免多课表歧义）
    health = httpx.get(f"{BASE}/api/health", timeout=5)
    check("健康检查", health.status_code == 200)
    import secrets

    import psycopg
    e2e_token = "e2e-" + secrets.token_hex(24)
    token_hash = sha256(e2e_token.encode()).hexdigest()
    with psycopg.connect(DB_URL) as db:
        user_id = db.execute("""INSERT INTO users(openid) VALUES('local-e2e-user')
            ON CONFLICT(openid) DO UPDATE SET last_login_at=CURRENT_TIMESTAMP RETURNING id""").fetchone()[0]
        db.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)",
                   (token_hash, user_id, datetime.now(UTC) + timedelta(days=1)))
        db.commit()
    token = e2e_token
    check("专用 E2E 用户就绪", bool(token), user_id)
    auth = {"Authorization": f"Bearer {token}"}
    print(f"  测试用户 user_id={user_id}")

    # 2. 直插一套覆盖本周的课表与周三课程（周次留空=全学期有效）
    import psycopg
    monday = date.today() - timedelta(days=date.today().isoweekday() - 1)
    with psycopg.connect(DB_URL) as db:
        db.execute("DELETE FROM schedules WHERE user_id=%s AND name='本地联调课表'", (user_id,))
        schedule_id = db.execute("""INSERT INTO schedules(user_id,name,term,start_date,end_date,variant_type)
            VALUES(%s,'本地联调课表','2026-2027-1',%s,%s,'original') RETURNING id""",
            (user_id, monday - timedelta(days=30), monday + timedelta(days=60))).fetchone()[0]
        db.execute("""INSERT INTO courses(schedule_id,name,teacher,room,weekday,start_section,end_section,weeks)
            VALUES(%s,'高等数学','张老师','A101',3,5,6,'[]'::jsonb)""", (schedule_id,))
        db.commit()
    print(f"  已插入课表 schedule_id={schedule_id}（周三 5-6 节 高等数学）")

    # 3. 小程序侧生成绑定码
    code_resp = httpx.post(f"{BASE}/api/agent-bindings/code", headers=auth, timeout=5)
    bind_code = code_resp.json().get("code", "")
    check("生成绑定码", len(bind_code) == 6, code_resp.text)
    status0 = httpx.get(f"{BASE}/api/agent-bindings", headers=auth, timeout=5)
    check("绑定前状态为未绑定", status0.json().get("bound") is False)

    # 4. 企业微信侧发绑定命令 → 期望回复"绑定成功"（sender/msgid 每轮唯一，避免撞上前一轮的去重表）
    run_id = uuid.uuid4().hex[:8]
    sender = f"wecom-e2e-{run_id}"

    def mid(tag):
        return f"{run_id}-{tag}"

    send_callback(f"绑定 {bind_code}", sender, msg_id=mid("bind"))
    reply = wait_reply(0)
    check("绑定回复包含成功", reply and "绑定成功" in reply.get("markdown", {}).get("content", ""), reply)
    status1 = httpx.get(f"{BASE}/api/agent-bindings", headers=auth, timeout=5)
    check("绑定后状态为已绑定", status1.json().get("bound") is True)

    # 5. 已绑定用户查课 → 期望回复包含课程
    send_callback("这周有什么课", sender, msg_id=mid("query1"))
    reply = wait_reply(1)
    content = (reply or {}).get("markdown", {}).get("content", "")
    check("查询回复包含课程", "高等数学" in content, content[:80])

    # 6. 同一 msgid 重推 → 幂等，不产生第二条回复
    send_callback("这周有什么课", sender, msg_id=mid("query1"))
    time.sleep(1.5)
    check("重复消息幂等", len(replies) == 2, f"当前回复数 {len(replies)}")

    # 7. 未绑定的其他用户 → 引导文案
    send_callback("今天有什么课", sender="wecom-other-user", msg_id=mid("other"))
    reply = wait_reply(2)
    content = (reply or {}).get("markdown", {}).get("content", "")
    check("未绑定用户收到引导", "绑定" in content, content[:60])

    # 8. 群聊消息忽略
    send_callback("今天有什么课", sender, msg_id=mid("group"), chat_type="group")
    time.sleep(1.2)
    check("群聊消息被忽略", len(replies) == 3, f"当前回复数 {len(replies)}")

    # 9. 解绑
    send_callback("解绑", sender, msg_id=mid("unbind"))
    reply = wait_reply(3)
    check("解绑回复", reply and "已解绑" in reply.get("markdown", {}).get("content", ""), reply)
    status2 = httpx.get(f"{BASE}/api/agent-bindings", headers=auth, timeout=5)
    check("解绑后状态为未绑定", status2.json().get("bound") is False)

    # 10. debug 接口（仅 development 开放）
    debug = httpx.post(f"{BASE}/api/agent/debug/message", headers=auth,
                       json={"message": "下周三下午有什么课"}, timeout=5)
    check("debug 接口应答", debug.status_code == 200 and debug.json().get("intent") == "QUERY_DAY",
          debug.text[:100])

    print(f"\n结果：{len(passed)} 通过 / {len(failed)} 失败")
    if failed:
        for item in failed:
            print("  FAIL:", item)
        sys.exit(1)


if __name__ == "__main__":
    main()
