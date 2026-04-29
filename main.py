"""
AMS FF Like — Full Stack
একটাই URL → API + Admin + User Panel

Like API:
  GET /like100?uid=XXX&api_key=YYY
  GET /like200?uid=XXX&api_key=YYY
  POST /like100  {"uid":"X","api_key":"Y"}
  POST /like200  {"uid":"X","api_key":"Y"}

Website:
  GET /       → User Panel
  GET /admin  → Admin Panel

Auth:
  POST /auth/login   → session token
  POST /auth/logout
  GET  /auth/me

Admin:
  GET    /admin/keys
  POST   /admin/genkey
  PATCH  /admin/key/{k}
  DELETE /admin/key/{k}
  GET    /admin/logs
  POST   /admin/reset
  GET    /admin/config        → API URL গুলো দেখো
  POST   /admin/config        → API URL চেঞ্জ করো
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Header, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
from db import gen_key
from utils import call_like_api, calc_cut_100, calc_cut_200
from config import cfg

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ams")

BASE_DIR   = Path(__file__).parent
ADMIN_HTML = (BASE_DIR / "static" / "admin.html").read_text(encoding="utf-8")
USER_HTML  = (BASE_DIR / "static" / "user.html").read_text(encoding="utf-8")

app = FastAPI(
    title="AMS FF Like API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_ip(req: Request) -> str:
    fwd = req.headers.get("X-Forwarded-For", "")
    if fwd: return fwd.split(",")[0].strip()
    return req.client.host if req.client else "unknown"

def check_admin(token: str):
    if token != cfg.ADMIN_TOKEN:
        raise HTTPException(403, "Invalid admin token.")


# ── Models ────────────────────────────────────────────────────────────────────
class LikeBody(BaseModel):
    uid: str
    api_key: str

class LoginRequest(BaseModel):
    api_key: str

class GenKeyRequest(BaseModel):
    name: str
    nick: str = ""
    daily_limit: int = 10
    total_limit: int = 300

class UpdateKeyRequest(BaseModel):
    nick: Optional[str]        = None
    daily_limit: Optional[int] = None
    total_limit: Optional[int] = None
    used_today: Optional[int]  = None
    total_used: Optional[int]  = None
    is_active: Optional[bool]  = None

class ApiConfigRequest(BaseModel):
    like100_url: str
    like200_url: str


# ── Website ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def user_panel():
    return HTMLResponse(USER_HTML)

@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_panel():
    return HTMLResponse(ADMIN_HTML)


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/auth/login", tags=["Auth"])
async def login(body: LoginRequest, req: Request):
    rec = db.get_key_with_reset(body.api_key)
    if not rec:
        raise HTTPException(401, "Invalid API key.")
    if not rec.get("is_active", True):
        raise HTTPException(403, "This key is disabled.")
    token = db.create_session(body.api_key, get_ip(req))
    return {
        "status": "logged_in",
        "session_token": token,
        "user": {
            "name":        rec.get("name"),
            "nick":        rec.get("nick"),
            "daily_limit": rec.get("daily_limit"),
            "used_today":  rec.get("used_today"),
            "total_limit": rec.get("total_limit"),
            "total_used":  rec.get("total_used"),
            "created_at":  rec.get("created_at"),
        }
    }

@app.post("/auth/logout", tags=["Auth"])
async def logout(x_session_token: str = Header(...)):
    db.delete_session(x_session_token)
    return {"status": "logged_out"}

@app.get("/auth/me", tags=["Auth"])
async def me(x_session_token: str = Header(...)):
    session = db.validate_session(x_session_token)
    if not session:
        raise HTTPException(401, "Session expired. Please login again.")
    rec = db.get_key_with_reset(session["api_key"])
    if not rec:
        raise HTTPException(401, "Key not found.")
    return {
        "name":        rec.get("name"),
        "nick":        rec.get("nick"),
        "daily_limit": rec.get("daily_limit"),
        "used_today":  rec.get("used_today"),
        "total_limit": rec.get("total_limit"),
        "total_used":  rec.get("total_used"),
        "is_active":   rec.get("is_active"),
    }


# ── Like handler ──────────────────────────────────────────────────────────────
async def handle_like(uid: str, api_key: str,
                      endpoint: str, calc_cut):
    # 1. Key validate
    rec = db.get_key_with_reset(api_key)
    if not rec:
        raise HTTPException(401, "Invalid API key.")
    if not rec.get("is_active", True):
        raise HTTPException(403, "API key is disabled.")

    # 2. Limit check
    daily      = rec.get("daily_limit", 10)
    today_used = rec.get("used_today", 0)
    total_lim  = rec.get("total_limit", 300)
    total_used = rec.get("total_used", 0)
    remain     = daily - today_used

    if remain <= 0:
        raise HTTPException(429, f"Daily limit ({daily}/day) reached. Resets at 4AM.")
    if total_used >= total_lim:
        raise HTTPException(429, f"Total limit ({total_lim}) reached.")

    # 3. Get current API URL (admin পরে change করতে পারে)
    api_cfg = db.get_api_config()
    if endpoint == "like100":
        api_url = api_cfg.get("like100_url", cfg.LIKE_API_100)
    else:
        api_url = api_cfg.get("like200_url", cfg.LIKE_API_200)

    requested = int(endpoint.replace("like", ""))

    # 4. Call like API
    try:
        result = await call_like_api(api_url, uid)
    except httpx.HTTPStatusError as e:
        db.write_log({"api_key": api_key, "uid": uid, "endpoint": endpoint,
                      "requested": requested, "success": 0, "limit_cut": 0,
                      "error": f"upstream {e.response.status_code}"})
        raise HTTPException(502, f"Like API error: {e.response.status_code}")
    except httpx.RequestError as e:
        db.write_log({"api_key": api_key, "uid": uid, "endpoint": endpoint,
                      "requested": requested, "success": 0, "limit_cut": 0,
                      "error": "network"})
        raise HTTPException(502, "Cannot reach like API.")

    success = result["success"]
    cut     = calc_cut(success)

    # 5. Usage update
    if cut > 0:
        db.increment_usage(api_key, cut)
        remain -= cut

    # 6. Log
    db.write_log({
        "api_key":   api_key,
        "uid":       uid,
        "endpoint":  endpoint,
        "requested": requested,
        "success":   success,
        "limit_cut": cut,
        "key_name":  rec.get("name"),
    })

    return {
        "status":          "success",
        "endpoint":        endpoint,
        "uid":             uid,
        "likes_sent":      success,
        "limit_cut":       cut,
        "remaining_today": max(remain, 0),
        "raw_response":    result["raw"],
    }


# ── Like 100 ──────────────────────────────────────────────────────────────────
@app.get("/like100", tags=["Like API"])
async def like100_get(
    uid:     str = Query(..., description="Free Fire UID"),
    api_key: str = Query(..., description="তোমার API Key"),
):
    """Browser থেকে: /like100?uid=123456&api_key=your_key"""
    return await handle_like(uid, api_key, "like100", calc_cut_100)

@app.post("/like100", tags=["Like API"])
async def like100_post(body: LikeBody):
    """POST: {"uid":"123456","api_key":"your_key"}"""
    return await handle_like(body.uid, body.api_key, "like100", calc_cut_100)


# ── Like 200 ──────────────────────────────────────────────────────────────────
@app.get("/like200", tags=["Like API"])
async def like200_get(
    uid:     str = Query(..., description="Free Fire UID"),
    api_key: str = Query(..., description="তোমার API Key"),
):
    """Browser থেকে: /like200?uid=123456&api_key=your_key"""
    return await handle_like(uid, api_key, "like200", calc_cut_200)

@app.post("/like200", tags=["Like API"])
async def like200_post(body: LikeBody):
    """POST: {"uid":"123456","api_key":"your_key"}"""
    return await handle_like(body.uid, body.api_key, "like200", calc_cut_200)


# ── Admin: API Config (URL change) ────────────────────────────────────────────
@app.get("/admin/config", tags=["Admin"])
async def get_config(x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    return db.get_api_config()

@app.post("/admin/config", tags=["Admin"])
async def update_config(body: ApiConfigRequest,
                        x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    db.save_api_config(body.like100_url, body.like200_url)
    return {"status": "saved", "like100_url": body.like100_url,
            "like200_url": body.like200_url}


# ── Admin: Keys ───────────────────────────────────────────────────────────────
@app.get("/admin/keys", tags=["Admin"])
async def admin_keys(x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    return {"keys": db.get_all_keys()}

@app.post("/admin/genkey", tags=["Admin"])
async def admin_genkey(body: GenKeyRequest,
                       x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    key = gen_key(body.name)
    rec = db.create_key(key, name=body.name, nick=body.nick,
                        daily_limit=body.daily_limit,
                        total_limit=body.total_limit)
    return {"api_key": key, **rec}

@app.patch("/admin/key/{api_key}", tags=["Admin"])
async def admin_update(api_key: str, body: UpdateKeyRequest,
                       x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields.")
    if not db.update_key(api_key, **fields):
        raise HTTPException(404, "Key not found.")
    return {"status": "updated"}

@app.delete("/admin/key/{api_key}", tags=["Admin"])
async def admin_delete(api_key: str, x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    if not db.delete_key(api_key):
        raise HTTPException(404, "Key not found.")
    return {"status": "deleted"}


# ── Admin: Logs ───────────────────────────────────────────────────────────────
@app.get("/admin/logs", tags=["Admin"])
async def admin_logs(limit: int = 50,
                     x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    return {"logs": db.get_logs(limit)}


# ── Admin: Reset ──────────────────────────────────────────────────────────────
@app.post("/admin/reset", tags=["Admin"])
async def admin_reset(x_admin_token: str = Header(...)):
    check_admin(x_admin_token)
    db.reset_daily_all()
    return {"status": "reset done"}


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health():
    api_cfg = db.get_api_config()
    return {
        "status": "ok",
        "time":   datetime.utcnow().isoformat(),
        "apis": {
            "like100": api_cfg.get("like100_url","")[:40]+"...",
            "like200": api_cfg.get("like200_url","")[:40]+"...",
        }
    }


# ── Error handler ─────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_err(req: Request, exc: Exception):
    logger.error(f"Error: {exc}")
    return JSONResponse(500, {"status": "error", "detail": str(exc)})
