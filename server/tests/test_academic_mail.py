import smtplib
from datetime import UTC, datetime, timedelta

import pytest

from app.services import academic_mail as mail
from app.services.academic import AcademicError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(mail, "CONFIG", tmp_path / "mail-config.enc")
    monkeypatch.setattr(mail, "OUTBOX", tmp_path / "mail-outbox.json")
    monkeypatch.setattr(mail, "_key", lambda: b"a" * 32)
    monkeypatch.setattr(mail, "_thread", None)
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "unavailable")


def configured():
    mail.save_config(True, "123@qq.com", "123@qq.com", "abcdefghijklmnop")
    mail.connection_event("needs_login")


def smtp(monkeypatch, *, connect_error=None, send_error=None, quit_error=None, auth_error=None):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            assert (host, port) == ("smtp.qq.com", 465)
            if connect_error:
                raise connect_error

        def __enter__(self):
            return self

        def __exit__(self, *args):
            if quit_error:
                raise quit_error

        def login(self, sender, code):
            if auth_error:
                raise auth_error
            assert code == "abcdefghijklmnop"

        def send_message(self, message):
            calls.append(message)
            if send_error:
                raise send_error
            return {}

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    return calls


def test_config_encrypted_and_secret_never_returned():
    configured()
    assert b"abcdefghijklmnop" not in mail.CONFIG.read_bytes()
    assert "abcdefghijklmnop" not in str(mail.public_status())
    assert mail.public_status()["configured"]
    mail.save_config(True, "123@qq.com", "456@qq.com")
    assert mail.config()["authorization_code"] == "abcdefghijklmnop"
    with pytest.raises(AcademicError):
        mail.save_config(True, "456@qq.com", "456@qq.com")


def test_disabled_never_connects(monkeypatch):
    calls = smtp(monkeypatch)
    mail.connection_event("needs_login")
    mail.process_one()
    assert not calls


def test_dedup_and_new_incident_after_recovery(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    mail.process_one()
    first = mail.outbox()["incident"]
    mail.connection_event("needs_login")
    mail.process_one()
    assert len(calls) == 1
    assert mail.public_status()["status"] == "sent"
    mail.connection_event("connected")
    mail.connection_event("needs_login")
    assert mail.outbox()["incident"] != first
    mail.process_one()
    assert len(calls) == 2
    assert "Cookie" not in calls[0].get_content()


def test_network_failure_retries_only_three_times(monkeypatch):
    smtp(monkeypatch, connect_error=OSError("secret response"))
    configured()
    for attempt in range(1, 4):
        data = mail.outbox()
        data["next_attempt_at"] = 0
        mail.save_outbox(data)
        mail.process_one()
        assert mail.outbox()["attempts"] == attempt
    assert mail.outbox()["status"] == "failed"
    assert "secret response" not in str(mail.public_status())


def test_authentication_failure_is_permanent(monkeypatch):
    smtp(monkeypatch, auth_error=smtplib.SMTPAuthenticationError(535, b"secret response"))
    configured()
    mail.process_one()
    assert mail.outbox()["status"] == "failed"
    assert mail.outbox()["next_attempt_at"] is None


def test_uncertain_submission_never_resends(monkeypatch):
    calls = smtp(monkeypatch, send_error=TimeoutError())
    configured()
    mail.process_one()
    assert mail.outbox()["status"] == "unknown"
    mail.save_config(True, "123@qq.com", "123@qq.com")
    mail.process_one()
    assert len(calls) == 1


def test_quit_failure_after_success_never_resends(monkeypatch):
    calls = smtp(monkeypatch, quit_error=OSError())
    configured()
    mail.process_one()
    assert mail.outbox()["status"] == "sent"
    mail.process_one()
    assert len(calls) == 1


def test_recovery_cancels_pending(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    mail.connection_event("connected")
    mail.process_one()
    assert mail.outbox()["status"] == "cancelled"
    assert not calls


def test_restart_does_not_retry_unconfirmed_submission(monkeypatch):
    configured()
    data = mail.outbox()
    data["status"] = "sending"
    mail.save_outbox(data)

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(mail.threading, "Thread", FakeThread)
    mail.start()
    assert mail.outbox()["status"] == "unknown"


def test_damaged_dedup_record_fails_closed(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    mail.OUTBOX.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        mail.process_one()
    assert mail.public_status()["status"] == "failed"
    assert not calls


def test_available_query_defers_manual_alert(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "available")
    mail.process_one()
    assert not calls
    assert mail.outbox()["status"] == "pending"
    assert mail.outbox()["attempts"] == 0
    assert mail.outbox()["next_attempt_at"] > mail.time.time()


def test_query_failure_upgrades_once(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    data = mail.outbox()
    data["detected_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    mail.save_outbox(data)
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "available")
    mail.process_one()
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "unavailable")
    mail.connection_event("query_unavailable")
    mail.process_one()
    mail.connection_event("query_unavailable")
    mail.process_one()
    assert len(calls) == 2
    assert "查询连接不可用" in calls[-1]["Subject"]


def test_stopped_maintenance_does_not_upgrade(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    mail.process_one()
    mail.connection_event("stopped")
    mail.connection_event("query_unavailable")
    mail.process_one()
    assert len(calls) == 1


def test_unknown_query_does_not_claim_expiry(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "unknown")
    mail.process_one()
    assert not calls
    assert mail.outbox()["status"] == "pending"
    assert mail.outbox()["attempts"] == 0


def test_persistent_maintenance_alert_is_distinct_and_deduplicated(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "available")
    data = mail.outbox()
    data["detected_at"] = (datetime.now(UTC) - timedelta(seconds=1801)).isoformat()
    mail.save_outbox(data)
    mail.process_one()
    mail.connection_event("maintenance_error")
    mail.process_one()
    assert len(calls) == 1
    assert "当前查询正常" in calls[0]["Subject"]
    assert "无需重新登录" in calls[0].get_content()


def test_deferred_unknown_probe_can_later_confirm_expiry(monkeypatch):
    calls = smtp(monkeypatch)
    configured()
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "unknown")
    mail.process_one()
    data = mail.outbox()
    data["next_attempt_at"] = 0
    mail.save_outbox(data)
    monkeypatch.setattr(mail, "verify_query_connection", lambda: "unavailable")
    mail.process_one()
    assert len(calls) == 1
    assert "查询连接不可用" in calls[0]["Subject"]
    assert mail.outbox()["attempts"] == 1
