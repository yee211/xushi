"""专项验证：微信 Bot 多人并发加固测试。

覆盖核心指标：
1. ScheduleTools 支持 db 连接工厂（callable / contextmanager），查询随用随还；
2. build_agent_reply 在大模型耗时推理期间不持有数据库连接（零长事务占用）；
3. 全局 LLM 并发信号量限制生效，平滑削峰；
4. 晨推任务支持连接工厂短事务。
"""
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.agent.http_client import get_llm_semaphore  # noqa: E402
from app.agent.service import build_agent_reply  # noqa: E402
from app.agent.tools import AgentContext, ScheduleTools  # noqa: E402
from app.services.daily_push import dispatch_morning_pushes  # noqa: E402


class CountingConnectionPool:
    """模拟连接池，精确统计当前活跃（借出中）的连接数与累计借出次数。"""

    def __init__(self):
        self.active_connections = 0
        self.borrow_count = 0
        self.max_concurrent_connections = 0
        self._lock = threading.Lock()

    def connect(self):
        class _Ctx:
            def __init__(self, parent):
                self.parent = parent
                self.mock_db = MagicMock()
                # 预设常见查询返回
                self.mock_db.execute.return_value.fetchone.return_value = {"user_id": 42}
                self.mock_db.execute.return_value.fetchall.return_value = []

            def __enter__(self):
                with self.parent._lock:
                    self.parent.active_connections += 1
                    self.parent.borrow_count += 1
                    if self.parent.active_connections > self.parent.max_concurrent_connections:
                        self.parent.max_concurrent_connections = self.parent.active_connections
                return self.mock_db

            def __exit__(self, *args):
                with self.parent._lock:
                    self.parent.active_connections -= 1
                return False

        return _Ctx(self)


def test_schedule_tools_borrows_and_returns_connection_on_demand(monkeypatch):
    """验证 ScheduleTools 执行查询时才借出连接，查完立即归还。"""
    pool = CountingConnectionPool()
    context = AgentContext(user_id=42, now=datetime(2026, 9, 21, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

    monkeypatch.setattr("app.agent.tools.query_courses_by_date", lambda db, *args: {"courses": []})
    monkeypatch.setattr("app.agent.tools.find_course", lambda db, *args: {"occurrences": []})

    tools = ScheduleTools(pool.connect, context)

    # 初始化时未借用连接
    assert pool.active_connections == 0
    assert pool.borrow_count == 0

    # 查一次课
    res1 = tools.get_courses_by_date(date(2026, 9, 21))
    assert res1 == {"courses": []}
    # 查完后连接已释放
    assert pool.active_connections == 0
    assert pool.borrow_count == 1

    # 再查一次课程
    res2 = tools.find_course("高数", date(2026, 9, 21))
    assert res2 == {"occurrences": []}
    assert pool.active_connections == 0
    assert pool.borrow_count == 2


def test_build_agent_reply_does_not_hold_db_during_llm_inference(monkeypatch):
    """验证在调用大模型期间，连接已被释放，处于 0 连接占用状态。"""
    pool = CountingConnectionPool()

    active_connections_during_llm = []

    def fake_handle_message(text, tools, history=None):
        # 模拟大模型思考期间：记录此时数据库连接占用数
        active_connections_during_llm.append(pool.active_connections)
        # 模拟大模型调用工具（内部查询）
        time.sleep(0.02)
        return {"answer": "回答完毕", "intent": "QUERY_DAY"}

    monkeypatch.setattr("app.agent.service.handle_message", fake_handle_message)
    monkeypatch.setattr("app.agent.service.load_history", lambda *args: [])
    monkeypatch.setattr("app.agent.service.append_turn", lambda *args: None)

    reply = build_agent_reply(
        pool.connect,
        "今天有什么课",
        "weixin_ilink",
        "wx-sender-100",
        datetime.now(ZoneInfo("Asia/Shanghai")),
    )

    assert reply == "回答完毕"
    # 证明进入 handle_message（等待 LLM）时，没有霸占任何数据库连接！
    assert active_connections_during_llm == [0]
    # 完成后所有连接全部归还
    assert pool.active_connections == 0


def test_llm_semaphore_limits_concurrency(monkeypatch):
    """验证 LLM 信号量能够限制瞬时并发数。"""
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "2")
    # 重置模块内信号量
    import app.agent.http_client as hc
    hc._llm_semaphore = None

    sem = get_llm_semaphore()
    assert sem._value == 2

    active_workers = 0
    max_active = 0
    lock = threading.Lock()

    def task():
        nonlocal active_workers, max_active
        with sem:
            with lock:
                active_workers += 1
                if active_workers > max_active:
                    max_active = active_workers
            time.sleep(0.04)
            with lock:
                active_workers -= 1

    threads = [threading.Thread(target=task) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 最大并发数绝不超过信号量设定的 2
    assert max_active == 2


def test_dispatch_morning_pushes_with_connection_factory(monkeypatch):
    """验证晨推支持连接工厂短事务。"""
    pool = CountingConnectionPool()

    monkeypatch.setattr("app.services.daily_push.load_accounts", lambda db: [])
    sent = dispatch_morning_pushes(pool.connect, date(2026, 9, 21))
    assert sent == 0
    assert pool.active_connections == 0
