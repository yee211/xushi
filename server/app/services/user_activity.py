"""Record real activity, limiting each user's database writes to once per minute."""


def touch(db, user_id):
    db.execute("""UPDATE users SET last_active_at = CURRENT_TIMESTAMP
        WHERE id = %s AND (last_active_at IS NULL
            OR last_active_at < CURRENT_TIMESTAMP - INTERVAL '1 minute')""", (user_id,))
