"""
لایه مومنتوم از @binance_futures_5m_pump
برای هر تیکر واچ‌لیست BITFA، پیام‌های اخیر همان نماد را جمع می‌کند
و روی امتیاز نهایی بوست/جریمه می‌گذارد (نه دستور جدا).
"""

import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or ""
SESSION = os.getenv("TELEGRAM_SESSION") or ""
PUMP_CHANNEL = os.getenv("PUMP_CHANNEL") or "binance_futures_5m_pump"

MSG_RE = re.compile(
    r"#\s*([A-Za-z][A-Za-z0-9]{1,20})\s*(?:USDT)?\s*"
    r"price\s+(UP|DOWN)\s+on\s+([0-9.]+)\s*%",
    re.IGNORECASE,
)
VOL_RE = re.compile(r"Volume\s+up\s+on\s+([0-9.]+)\s*%", re.IGNORECASE)
PRICE_RE = re.compile(
    r"Price:\s*([0-9.]+)\s*(?:\(\+?(-?[0-9.]+)%\s*in\s*24h\))?",
    re.IGNORECASE,
)
VOL24_RE = re.compile(r"24h\s*Volume:\s*([0-9.]+)\s*([KMB])?", re.IGNORECASE)


def _parse_vol24(num: str, unit: Optional[str]) -> float:
    try:
        v = float(num)
    except Exception:
        return 0.0
    u = (unit or "").upper()
    if u == "K":
        return v * 1_000
    if u == "M":
        return v * 1_000_000
    if u == "B":
        return v * 1_000_000_000
    return v


def parse_pump_message(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = MSG_RE.search(text)
    if not m:
        return None
    raw = m.group(1).upper()
    if raw.endswith("USDT"):
        raw = raw[:-4]
    direction = m.group(2).upper()
    move_pct = float(m.group(3))
    vm = VOL_RE.search(text)
    vol_up = float(vm.group(1)) if vm else 0.0
    pm = PRICE_RE.search(text)
    price = float(pm.group(1)) if pm else None
    ch24 = float(pm.group(2)) if pm and pm.group(2) else None
    v24m = VOL24_RE.search(text)
    vol24 = _parse_vol24(v24m.group(1), v24m.group(2)) if v24m else 0.0
    return {
        "ticker": raw,
        "direction": direction,
        "move_pct": move_pct,
        "vol_up_pct": vol_up,
        "price": price,
        "change_24h": ch24,
        "volume_24h": vol24,
    }


async def fetch_pump_index(limit_messages: int = 80, hours: int = 24) -> Dict[str, Any]:
    """
    همه پیام‌های قابل‌پارس ~۲۴ساعت اخیر را به صورت
    {TICKER: [events newest-first]} برمی‌گرداند.
    """
    if not SESSION or not API_ID or not API_HASH:
        return {"error": "session missing", "index": {}, "messages_checked": 0}

    client = TelegramClient(
        StringSession(SESSION),
        API_ID,
        API_HASH,
        connection_retries=2,
        request_retries=2,
        retry_delay=1,
        timeout=18,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    index: Dict[str, List[Dict[str, Any]]] = {}
    checked = 0
    try:
        await asyncio.wait_for(client.connect(), timeout=25)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=12):
            return {"error": "not authorized", "index": {}, "messages_checked": 0}
        entity = await client.get_entity(PUMP_CHANNEL)
        async for msg in client.iter_messages(entity, limit=limit_messages):
            checked += 1
            if msg.date and msg.date.replace(tzinfo=timezone.utc) < cutoff:
                break
            p = parse_pump_message(msg.message or "")
            if not p:
                continue
            p["msg_date"] = msg.date.isoformat() if msg.date else None
            index.setdefault(p["ticker"], []).append(p)
        return {
            "channel": PUMP_CHANNEL,
            "messages_checked": checked,
            "index": index,
            "tickers": list(index.keys()),
        }
    except Exception as e:
        return {"error": str(e)[:250], "index": {}, "messages_checked": checked}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def evaluate_pump_for_ticker(
    ticker: str,
    index: Dict[str, List[Dict[str, Any]]],
    *,
    entry_phase: str = "",
) -> Dict[str, Any]:
    """
    برای یک نماد از روی ایندکس پامپ، بوست امتیاز و خلاصه برمی‌گرداند.

    منطق (نسخه EVAA):
    - چند UP با حجم بالا در شروع موج → بوست مثبت
    - آخرین‌ها DOWN یا رشد ۲۴س خیلی بالا بعد از موج → جریمه / بدون بوست
    """
    t = (ticker or "").upper().strip()
    if t.endswith("USDT"):
        t = t[:-4]
    events = list(index.get(t) or [])
    if not events:
        return {"boost": 0, "summary": None, "events": 0}

    ups = [e for e in events if e.get("direction") == "UP"]
    downs = [e for e in events if e.get("direction") == "DOWN"]
    latest = events[0]
    max_vol = max((float(e.get("vol_up_pct") or 0) for e in events), default=0)
    max_up_move = max((float(e.get("move_pct") or 0) for e in ups), default=0) if ups else 0
    ch24s = [float(e["change_24h"]) for e in events if e.get("change_24h") is not None]
    max_ch24 = max(ch24s) if ch24s else None
    min_ch24 = min(ch24s) if ch24s else None
    prices = [float(e["price"]) for e in events if e.get("price") is not None]
    price_first = prices[-1] if prices else None  # oldest in list order newest-first
    price_last = prices[0] if prices else None

    boost = 0
    notes = []

    # جریمه اگر آخرین سیگنال DOWN با حجم باشد
    if latest.get("direction") == "DOWN" and float(latest.get("vol_up_pct") or 0) >= 100:
        boost -= 4
        notes.append(f"آخرین هشدار پامپ: DOWN ({latest.get('move_pct')}%)")
    elif latest.get("direction") == "UP" and float(latest.get("vol_up_pct") or 0) >= 150:
        boost += 3
        notes.append(f"هشدار پامپ اخیر: UP +{latest.get('move_pct')}% / Vol+{latest.get('vol_up_pct')}%")

    # تعداد UPهای قوی در ۲۴س
    strong_ups = [e for e in ups if float(e.get("vol_up_pct") or 0) >= 150 and float(e.get("move_pct") or 0) >= 3]
    if len(strong_ups) >= 3:
        boost += 4
        notes.append(f"{len(strong_ups)} سیگنال UP قوی در ۲۴س")
    elif len(strong_ups) >= 1:
        boost += 2
        notes.append(f"{len(strong_ups)} سیگنال UP با حجم")

    if max_vol >= 300:
        boost += 2
        notes.append(f"اوج Volume up: +{max_vol:.0f}%")

    # اگر موج خیلی جلو رفته (chase)
    if max_ch24 is not None and max_ch24 >= 90:
        boost -= 5
        notes.append(f"رشد ۲۴س در کانال پامپ تا +{max_ch24:.0f}% (ریسک chase)")
    elif max_ch24 is not None and max_ch24 >= 55:
        boost -= 2
        notes.append(f"رشد ۲۴س بالا در پامپ (+{max_ch24:.0f}%)")

    # هم‌راستایی با فاز ورود سیستم خودمان
    phase = (entry_phase or "").upper()
    if phase in ("EARLY", "DEVELOPING") and boost > 0:
        boost += 2
        notes.append(f"هم‌راستا با فاز {phase}")
    if phase in ("EXHAUSTED", "BEARISH") and boost > 0:
        boost = min(boost, 1)
        notes.append(f"فاز {phase}: بوست پامپ محدود شد")
    if phase == "EXHAUSTED":
        boost = min(boost, 0)

    boost = max(-8, min(10, int(boost)))

    summary = {
        "ticker": t,
        "events": len(events),
        "ups": len(ups),
        "downs": len(downs),
        "max_vol_up": max_vol,
        "max_up_move": max_up_move,
        "max_change_24h": max_ch24,
        "price_first": price_first,
        "price_last": price_last,
        "latest_direction": latest.get("direction"),
        "notes": notes,
        "boost": boost,
    }
    return {"boost": boost, "summary": summary, "events": len(events)}


def apply_pump_to_result(r: dict, pump_eval: Dict[str, Any]) -> dict:
    if not pump_eval or not r or r.get("error"):
        return r
    boost = int(pump_eval.get("boost") or 0)
    summary = pump_eval.get("summary")
    if not boost and not summary:
        return r
    r = dict(r)
    if summary:
        r["pump_summary"] = summary
    if boost:
        old = int(r.get("score") or 0)
        new_score = max(0, min(100, old + boost))
        r["score"] = new_score
        r["pump_boost"] = boost
        reasons = list(r.get("reasons") or [])
        warnings = list(r.get("warnings") or [])
        if boost > 0:
            reasons.insert(0, f"مومنتوم کانال پامپ: مثبت (+{boost})")
        else:
            warnings.insert(0, f"مومنتوم کانال پامپ: منفی ({boost})")
        for n in (summary or {}).get("notes") or []:
            if boost > 0:
                reasons.append(f"پامپ: {n}")
            else:
                warnings.append(f"پامپ: {n}")
        r["reasons"] = reasons[:10]
        r["warnings"] = warnings[:8]
        conf = int(r.get("confidence") or 0)
        if new_score >= 80 and conf >= 70:
            r["category"], r["recommendation"], r["action"] = (
                "HOT",
                "امتیاز عالی - قابل بررسی جدی برای ورود محدود",
                "اولویت بررسی",
            )
        elif new_score >= 65:
            r["category"], r["recommendation"], r["action"] = (
                "QUALIFIED",
                "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت",
                "بررسی برای ورود",
            )
        elif new_score >= 48:
            r["category"], r["recommendation"], r["action"] = (
                "WATCH",
                "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار",
                "نظارت",
            )
        else:
            r["category"], r["recommendation"], r["action"] = (
                "SKIP",
                "امتیاز ضعیف - رد شود",
                "رد",
            )
    return r
