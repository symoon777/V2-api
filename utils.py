import httpx
from config import cfg


def calc_cut_100(success: int) -> int:
    """100 like: >=70 → cut 1, else 0"""
    return 1 if success >= 70 else 0


def calc_cut_200(success: int) -> int:
    """200 like: >=150 → cut 2, >=70 → cut 1, else 0"""
    if success >= 150: return 2
    if success >= 70:  return 1
    return 0


async def call_like_api(url: str, uid: str) -> dict:
    """
    GET request করে like API তে।
    URL এ {UID} থাকলে replace করে।
    """
    final_url = url.replace("{UID}", str(uid)).replace("{uid}", str(uid))

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            final_url,
            headers={"User-Agent": "AMS-FF-Like/2.0"},
            follow_redirects=True,
        )
        resp.raise_for_status()

        # Try JSON parse
        try:
            data = resp.json()
        except Exception:
            # If not JSON, treat text as success indicator
            data = {"raw_text": resp.text}

        # Different APIs return different field names
        success = (
            data.get("success") or
            data.get("likes_sent") or
            data.get("count") or
            data.get("sent") or
            data.get("total") or
            data.get("like") or
            data.get("likes") or
            data.get("amount") or
            0
        )
        return {"success": int(success), "raw": data}
