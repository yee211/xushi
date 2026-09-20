"""渠道绑定码消费：尝试次数计数与锁定。"""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from fakes import FakeAgentDb  # noqa: E402

from app.services.binding import BindingError, consume_binding_code  # noqa: E402


class RecordingDb(FakeAgentDb):
    """在 FakeAgentDb 之上额外记录 identity_binding_codes 的更新语句。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.updates = []

    def execute(self, sql, params=None):
        if sql.lstrip().startswith("UPDATE identity_binding_codes"):
            self.updates.append((" ".join(sql.split()), params))
        return super().execute(sql, params)


def binding_row(user_id=7, attempt_count=0):
    return {"id": 1, "user_id": user_id, "consumed_at": None,
            "expires_at": datetime.now(UTC) + timedelta(seconds=300),
            "attempt_count": attempt_count}


def test_conflict_rebinds_and_deletes_old_identity():
    """渠道身份已绑到其他账号：提交新绑定码时支持直接授权切换，覆盖旧绑定。"""
    db = RecordingDb(binding_row=binding_row(user_id=7), identity_user_id=99)
    user_id = consume_binding_code(db, "ABC123", "wecom", "sender-1")
    assert user_id == 7
    # 应成功消费并标记
    assert any("consumed_at=CURRENT_TIMESTAMP" in sql for sql, _ in db.updates)


def test_success_does_not_count_an_attempt():
    db = RecordingDb(binding_row=binding_row(), identity_user_id=7)
    user_id = consume_binding_code(db, "ABC123", "wecom", "sender-1")
    assert user_id == 7
    assert not any("attempt_count" in sql for sql, _ in db.updates)


def test_code_locks_after_too_many_attempts():
    db = RecordingDb(binding_row=binding_row(attempt_count=5))
    with pytest.raises(BindingError) as error:
        consume_binding_code(db, "ABC123", "wecom", "sender-1")
    assert "尝试次数过多" in str(error.value)
    assert db.updates == []
