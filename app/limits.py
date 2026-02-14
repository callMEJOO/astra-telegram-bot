import time, os
USER_DAILY_LIMIT = int(os.getenv("USER_DAILY_LIMIT", "2"))
_store = {}

def allow(user_id: int):
    now = int(time.time())
    day = now // 86400
    key = (user_id, day)
    _store[key] = _store.get(key, 0) + 1
    return _store[key] <= USER_DAILY_LIMIT
