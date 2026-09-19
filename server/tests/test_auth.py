
import jwt
import pytest
from fastapi import HTTPException

from app.auth import JWT_ALGORITHM, JWT_SECRET, create_token, get_current_user, hash_password, verify_password


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_token_contains_user_identity():
    token = create_token(42, "tester")
    assert isinstance(token, str) and token.count(".") == 2


@pytest.mark.parametrize("payload", [{"username": "tester"}, {"sub": "not-a-number"}, {"sub": "0"}])
def test_invalid_token_subject_returns_401(payload):
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(f"Bearer {token}")
    assert exc_info.value.status_code == 401
