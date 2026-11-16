"""
لایه رتبه‌بندی رشد/افت ۲۴ساعته + Funding Rate
کانال پیش‌فرض: @PumpDumpRadar

Env:
  GROWTH_RANK_CHANNEL  — اختیاری؛ پیش‌فرض PumpDumpRadar
"""

import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or ""
SESSION = os.getenv("TELEGRAM_SESSION") or ""
RANK_CHANNEL = (os.getenv("GROWTH_RANK_CHANNEL") or "PumpDumpRadar").strip().lstrip("@")

LINE_RE = re.compile(
    r"#\s*([A-Za-z][A-Za-z0-9]{1,20})(?:USDT|PERP)?\s*:\s*"
    r"(-?\d+(?:\.\d+)?)\s*[⇦←]\s*(-?\d+(?:\.\d+)?)\s*[⇦←]\s*(-?\d+(?:\.\d+)?)"
    r"(?:\s*\(([^)]+)\))?",
    re.IGNORECASE,
)
FR_RE = re.compile(
    r"FR\s*\(\s*(\d+)\s*\)\s*:\s*"
    r"(-?\d+(?:\.\d+)?)\s*%?\s*[⇦←]\s*(-?\d+(?:\.\d+)?)\s*%?\s*[⇦←]\s*(-?\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)


def _parse_vol(s: Optional[str]) -> float:
    if not s:
        return 0.0
    s = s.strip().lower().replace(",", "")
    m = re.match(r"([0-9.]+)\s*(million|m|thousand|k|billion|b)?", s)
    if not m:
        return 0.0
    v = float(m.group(1))
    u = (m.group(2) or "").lower()
    if u in ("million", "m"):
        return v * 1_000_000
    if u in ("thousand", "k"):
        return v * 1_000
    if u in ("billion", "b"):
        return v * 1_000_000_000
    return v


def parse_rank_message(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    section = None
    events: List[Dict[str, Any]] = []
    pending: Optional[Dict[str, Any]] = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if "top growth" in low:
            section = "growth"
            continue
        if "top drop" in low:
            section = "drop"
            continue

        m = LINE_RE.search(line)
        if m and section:
            if pending:
                events.append(pending)
            t = m.group(1).upper()
            if t.endswith("USDT"):
                t = t[:-4]
            if t.endswith("PERP"):
                t = t[:-4]
            pending = {
                "ticker": t,
                "side": section,
                "pct_now": float(m.group(2)),
                "pct_mid": float(m.group(3)),
                "pct_old": float(m.group(4)),
                "volume": _parse_vol(m.group(5)),
                "funding": None,
                "funding_interval": None,
            }
            continue

        fm = FR_RE.search(line)
        if fm and pending:
            pending["funding_interval"] = int(fm.group(1))
            pending["funding"] = float(fm.group(2))
            pending["funding_mid"] = float(fm.group(3))
            pending["funding_old"] = float(fm.group(4))
            events.append(pending)
            pending = None
            continue

    if pending:
        events.append(pending)
    return events


async def fetch_growth_rank_index(limit_messages: int = 40, hours: int = 24) -> Dict[str, Any]:
    if not RANK_CHANNEL:
        return {"error": "GROWTH_RANK_CHANNEL not set", "index": {}, "messages_checked": 0}
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
        entity = await client.get_entity(RANK_CHANNEL)
        async for msg in client.iter_messages(entity, limit=limit_messages):
            checked += 1
            if msg.date and msg.date.replace(tzinfo=timezone.utc) < cutoff:
                break
            for e in parse_rank_message(msg.message or ""):
                e["msg_date"] = msg.date.isoformat() if msg.date else None
                index.setdefault(e["ticker"], []).append(e)
        return {
            "channel": RANK_CHANNEL,
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


def evaluate_growth_rank_for_ticker(
    ticker: str,
    index: Dict[str, List[Dict[str, Any]]],
    *,
    entry_phase: str = "",
) -> Dict[str, Any]:
    t = (ticker or "").upper().strip()
    if t.endswith("USDT"):
        t = t[:-4]
    events = list(index.get(t) or [])
    if not events:
        return {"boost": 0, "summary": None, "events": 0}

    growths = [e for e in events if e.get("side") == "growth"]
    drops = [e for e in events if e.get("side") == "drop"]
    latest = events[0]
    pcts = [float(e.get("pct_now") or 0) for e in growths]
    max_pct = max(pcts) if pcts else None
    latest_pct = float(latest.get("pct_now") or 0)
    latest_side = latest.get("side")
    max_vol = max((float(e.get("volume") or 0) for e in events), default=0)
    latest_fr = float(latest["funding"]) if latest.get("funding") is not None else None

    boost = 0
    notes = []
    severe = False

    if latest_side == "drop":
        if latest_pct <= -25:
            boost -= 8
            severe = True
            notes.append(f"Top drop شدید: {latest_pct:.0f}%")
        elif latest_pct <= -12:
            boost -= 5
            notes.append(f"Top drop: {latest_pct:.0f}%")
        else:
            boost -= 2
            notes.append(f"در لیست افت: {latest_pct:.0f}%")

    if growths:
        appearances = len(growths)
        if latest_side == "growth":
            if max_pct is not None and max_pct >= 90:
                boost -= 6
                severe = True
                notes.append(f"رشد ۲۴س اشباع در رتبه‌بندی (اوج {max_pct:.0f}%)")
            elif max_pct is not None and max_pct >= 60:
                boost -= 2
                notes.append(f"رشد بالا در رتبه‌بندی (اوج {max_pct:.0f}%)")
            elif 15 <= latest_pct <= 55 and max_vol >= 5_000_000:
                boost += 4
                notes.append(f"Top growth پایدار: {latest_pct:.0f}% / Vol~{max_vol/1e6:.1f}M")
            elif 8 <= latest_pct < 15:
                boost += 2
                notes.append(f"Top growth ملایم: {latest_pct:.0f}%")

            if max_pct is not None and max_pct >= 50 and latest_pct < max_pct * 0.4:
                boost -= 5
                severe = True
                notes.append(f"سقوط از اوج رتبه‌بندی {max_pct:.0f}% → {latest_pct:.0f}%")

        if appearances >= 4 and latest_side == "growth" and not severe and latest_pct <= 55:
            boost += 2
            notes.append(f"{appearances} بار در Top growth (تأیید مومنتوم)")

    if latest_fr is not None and latest_side == "growth":
        if latest_fr >= 0.05 and (max_pct or 0) >= 40:
            boost -= 3
            notes.append(f"Funding بالا ({latest_fr:.3f}%) + رشد = شلوغی لانگ")
        elif latest_fr <= -0.05 and latest_pct >= 10:
            boost += 1
            notes.append(f"Funding منفی ({latest_fr:.3f}%) روی رشد")

    phase = (entry_phase or "").upper()
    if severe:
        boost = min(boost, -4)
    elif phase in ("EARLY", "DEVELOPING") and boost > 0:
        boost += 1
    if phase in ("EXHAUSTED", "BEARISH") and boost > 0:
        boost = min(boost, 0)

    boost = max(-12, min(8, int(boost)))

    summary = {
        "ticker": t,
        "events": len(events),
        "growth_hits": len(growths),
        "drop_hits": len(drops),
        "max_pct": max_pct,
        "latest_pct": latest_pct,
        "latest_side": latest_side,
        "max_volume": max_vol,
        "latest_funding": latest_fr,
        "severe": severe,
        "notes": notes,
        "boost": boost,
    }
    return {"boost": boost, "summary": summary, "events": len(events)}


def apply_growth_rank_to_result(r: dict, rank_eval: Dict[str, Any]) -> dict:
    if not rank_eval or not r or r.get("error"):
        return r
    boost = int(rank_eval.get("boost") or 0)
    summary = rank_eval.get("summary")
    if not boost and not summary:
        return r
    r = dict(r)
    if summary:
        r["growth_rank_summary"] = summary
    if not boost and not (summary and summary.get("severe")):
        return r

    old = int(r.get("score") or 0)
    new_score = max(0, min(100, old + boost))
    if summary and summary.get("severe"):
        new_score = min(new_score, 50)

    r["score"] = new_score
    r["growth_rank_boost"] = boost
    reasons = list(r.get("reasons") or [])
    warnings = list(r.get("warnings") or [])
    if boost > 0:
        reasons.insert(0, f"رتبه‌بندی رشد ۲۴س: مثبت (+{boost})")
    elif boost < 0:
        warnings.insert(0, f"رتبه‌بندی رشد ۲۴س: منفی ({boost})")
    for n in (summary or {}).get("notes") or []:
        if boost > 0 and not (summary or {}).get("severe"):
            reasons.append(f"رتبه: {n}")
        else:
            warnings.append(f"رتبه: {n}")
    r["reasons"] = reasons[:10]
    r["warnings"] = warnings[:8]

    conf = int(r.get("confidence") or 0)
    if new_score >= 80 and conf >= 70:
        r["category"], r["recommendation"], r["action"] = (
            "HOT", "امتیاز عالی - قابل بررسی جدی برای ورود محدود", "اولویت بررسی",
        )
    elif new_score >= 65:
        r["category"], r["recommendation"], r["action"] = (
            "QUALIFIED", "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت", "بررسی برای ورود",
        )
    elif new_score >= 48:
        r["category"], r["recommendation"], r["action"] = (
            "WATCH", "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار", "نظارت",
        )
    else:
        r["category"], r["recommendation"], r["action"] = (
            "SKIP", "امتیاز ضعیف - رد شود", "رد",
        )
    return r
