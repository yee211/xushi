"""PostgreSQL 连接池与查询辅助。

网页母版与小程序版使用同一套 psycopg_pool 方案；连接池规模支持通过
环境变量调整（小程序版的能力），默认值取两者折中。
"""
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from psycopg import connect as pg_connect
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/xushi_schedule")

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        min_size = max(1, int(os.getenv("DB_POOL_MIN_SIZE", "4")))
        max_size = max(min_size, int(os.getenv("DB_POOL_MAX_SIZE", "30")))
        timeout = max(1.0, float(os.getenv("DB_POOL_TIMEOUT", "15.0")))
        _pool = ConnectionPool(DATABASE_URL, min_size=min_size, max_size=max_size, timeout=timeout,
                               open=True, kwargs={"row_factory": dict_row})
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


def is_pool_ready() -> bool:
    return _pool is not None


@contextmanager
def connect():
    """获取数据库连接上下文。优先从连接池借用，未初始化时降级为独立连接（脚本/测试）。"""
    if _pool is not None:
        with _pool.connection() as db:
            yield db
    else:
        with pg_connect(DATABASE_URL, row_factory=dict_row) as db:
            yield db


@contextmanager
def db_ctx(db_or_factory):
    """统一的数据库借还上下文适配器：
    1. 若传入为连接上下文工厂（如 connect），进入上下文并在退出时归还；
    2. 若传入为返回普通连接对象的函数，退出时自动关闭释放；
    3. 若传入为连接池对象，通过 connection() 借用并归还；
    4. 若传入为裸连接或测试 mock 对象，直接透传。
    """
    if callable(db_or_factory):
        ctx = db_or_factory()
        if hasattr(ctx, "__enter__") and hasattr(ctx, "__exit__"):
            with ctx as db:
                yield db
        elif hasattr(ctx, "close"):
            try:
                yield ctx
            finally:
                ctx.close()
        else:
            yield ctx
    elif hasattr(db_or_factory, "connection"):
        with db_or_factory.connection() as db:
            yield db
    else:
        yield db_or_factory


DATETIME_KEYS = ("start_date", "end_date", "created_at", "last_login_at", "expires_at", "updated_at")


def row_dict(row) -> dict:
    """把 dict 行拷贝出来，并将日期时间字段序列化为 ISO 字符串（对齐两版前端约定）。"""
    result = dict(row)
    for key in DATETIME_KEYS:
        val = result.get(key)
        if val is not None:
            if hasattr(val, "isoformat"):
                result[key] = val.isoformat()
            else:
                result[key] = str(val)
    return result

