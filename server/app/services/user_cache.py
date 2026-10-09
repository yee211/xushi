"""Redis-first client data cache with generation-based invalidation."""
import json
import secrets

from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError

from ..redis import get_redis

PREFIX = "xushi:user-data:"
TTL_SECONDS = 300


def read(scope, user_id):
    client = get_redis()
    if client is None:
        return None, None
    generation_key = f"{PREFIX}{user_id}:generation"
    try:
        generation = client.get(generation_key)
        if not generation:
            client.set(generation_key, secrets.token_hex(16), nx=True)
            generation = client.get(generation_key)
        if not generation:
            return None, None
        if isinstance(generation, bytes):
            generation = generation.decode()
        key = f"{PREFIX}{user_id}:{generation}:{scope}"
        raw = client.get(key)
        if raw is None:
            return None, key
        return json.loads(raw), key
    except (RedisError, ValueError, TypeError, UnicodeError):
        return None, None


def store(key, payload):
    if not key:
        return
    client = get_redis()
    if client is None:
        return
    try:
        client.set(key, json.dumps(jsonable_encoder(payload), ensure_ascii=False), ex=TTL_SECONDS)
    except (RedisError, ValueError, TypeError):
        return


def invalidate_user(user_id):
    client = get_redis()
    if client is None:
        return
    try:
        # A reader begun before this write can only refill an obsolete generation.
        client.set(f"{PREFIX}{user_id}:generation", secrets.token_hex(16))
    except RedisError:
        return
