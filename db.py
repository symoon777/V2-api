import json, os, threading, secrets, string
from datetime import datetime, date
from typing import Optional

_lock    = threading.Lock()
DB_PATH  = "/tmp/ams_db.json"
LOG_PATH = "/tmp/ams_logs.json"
SES_PATH = "/tmp/ams_sessions.json"
CFG_PATH = "/tmp/ams_config.json"  # Admin panel থেকে API URL change করার জন্য


# ── File helpers ──────────────────────────────────────────────────────────────

def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        try:    return json.load(f)
        except: return default

def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ── Key generator ─────────────────────────────────────────────────────────────

def gen_key(name: str) -> str:
    rand = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    return f"{name.lower().replace(' ','_')[:20]}_{rand}"


# ── API Config (changeable from admin panel) ──────────────────────────────────

def get_api_config() -> dict:
    from config import cfg
    default = {
        "like100_url":    cfg.LIKE_API_100,
        "like200_url":    cfg.LIKE_API_200,
    }
    saved = _load(CFG_PATH, {})
    default.update(saved)  # saved values override defaults
    return default

def save_api_config(like100_url: str, like200_url: str):
    with _lock:
        _save(CFG_PATH, {
            "like100_url": like100_url,
            "like200_url": like200_url,
        })


# ── Keys ──────────────────────────────────────────────────────────────────────

def get_all_keys() -> dict:
    with _lock:
        return _load(DB_PATH, {}).get("keys", {})

def get_key_with_reset(api_key: str) -> Optional[dict]:
    with _lock:
        data = _load(DB_PATH, {})
        keys = data.get("keys", {})
        rec  = keys.get(api_key)
        if not rec: return None
        today = str(date.today())
        if rec.get("last_reset") != today:
            rec["used_today"] = 0
            rec["last_reset"] = today
            data["keys"] = keys
            _save(DB_PATH, data)
        return rec

def create_key(api_key, name, nick="", daily_limit=10, total_limit=300) -> dict:
    with _lock:
        data = _load(DB_PATH, {})
        keys = data.get("keys", {})
        rec  = {
            "name": name, "nick": nick or name,
            "daily_limit": daily_limit,
            "total_limit": total_limit,
            "total_used": 0, "used_today": 0,
            "last_reset": str(date.today()),
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
        }
        keys[api_key] = rec
        data["keys"]  = keys
        _save(DB_PATH, data)
        return rec

def update_key(api_key: str, **fields) -> bool:
    with _lock:
        data = _load(DB_PATH, {})
        keys = data.get("keys", {})
        if api_key not in keys: return False
        keys[api_key].update(fields)
        data["keys"] = keys
        _save(DB_PATH, data)
        return True

def delete_key(api_key: str) -> bool:
    with _lock:
        data = _load(DB_PATH, {})
        keys = data.get("keys", {})
        if api_key not in keys: return False
        del keys[api_key]
        data["keys"] = keys
        _save(DB_PATH, data)
        _remove_session_by_key(api_key)
        return True

def increment_usage(api_key: str, cut: int):
    with _lock:
        data = _load(DB_PATH, {})
        keys = data.get("keys", {})
        if api_key not in keys: return
        keys[api_key]["used_today"] = keys[api_key].get("used_today", 0) + cut
        keys[api_key]["total_used"] = keys[api_key].get("total_used", 0) + cut
        data["keys"] = keys
        _save(DB_PATH, data)

def reset_daily_all():
    with _lock:
        data  = _load(DB_PATH, {})
        keys  = data.get("keys", {})
        today = str(date.today())
        for rec in keys.values():
            rec["used_today"] = 0
            rec["last_reset"] = today
        data["keys"] = keys
        _save(DB_PATH, data)


# ── Sessions (1 device) ───────────────────────────────────────────────────────

def _remove_session_by_key(api_key: str):
    sessions = _load(SES_PATH, {})
    to_del = [t for t, i in sessions.items() if i.get("api_key") == api_key]
    for t in to_del: del sessions[t]
    _save(SES_PATH, sessions)

def create_session(api_key: str, ip: str) -> str:
    with _lock:
        sessions = _load(SES_PATH, {})
        # Remove old sessions for this key (1 device rule)
        to_del = [t for t, i in sessions.items() if i.get("api_key") == api_key]
        for t in to_del: del sessions[t]
        # New token
        token = secrets.token_urlsafe(32)
        sessions[token] = {
            "api_key":    api_key,
            "ip":         ip,
            "created_at": datetime.utcnow().isoformat(),
        }
        _save(SES_PATH, sessions)
        return token

def validate_session(token: str) -> Optional[dict]:
    with _lock:
        sessions = _load(SES_PATH, {})
        return sessions.get(token)

def delete_session(token: str):
    with _lock:
        sessions = _load(SES_PATH, {})
        sessions.pop(token, None)
        _save(SES_PATH, sessions)


# ── Logs ──────────────────────────────────────────────────────────────────────

def write_log(entry: dict):
    with _lock:
        logs = _load(LOG_PATH, [])
        if not isinstance(logs, list): logs = []
        entry["timestamp"] = datetime.utcnow().isoformat()
        logs.append(entry)
        if len(logs) > 500: logs = logs[-500:]
        _save(LOG_PATH, logs)

def get_logs(limit: int = 50) -> list:
    with _lock:
        logs = _load(LOG_PATH, [])
        if not isinstance(logs, list): return []
        return list(reversed(logs))[:limit]
