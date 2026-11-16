"""
مانیتور کانال binance_futures_5m_pump
فقط سیگنال‌های UP + حجم بالا، بعد فیلتر فاز ورود BITFA
"""

import os
import re
import asyncio
from typing import List, Dict, Any, Optional
from telethon import TelegramClient
from telethon.sessions import StringSession

from scorer import analyze_token

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or ""
SESSION = os.getenv("TELEGRAM_SESSION") or ""
PUMP_CHANNEL = os.getenv("PUMP_CHANNEL") or "binance_futures_5m_pump"

# آستانه‌ها
MIN_VOL_UP_PCT = float(os.getenv("PUMP_MIN_VOL_PCT") or "120")
MIN_PRICE_UP_PCT = float(os.getenv("PUMP_MIN_PRICE_PCT") or "2.0")
MAX_24H_CHANGE = float(os.getenv("PUMP_MAX_24H") or "55")  # بالاتر = احتمال chase
ALLOWED_PHASES = {"EARLY", "DEVELOPING"}

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
        "raw": text[:300],
    }


def _passes_raw_filter(p: Dict[str, Any]) -> bool:
    if p.get("direction") != "UP":
        return False
    if float(p.get("vol_up_pct") or 0) < MIN_VOL_UP_PCT:
        return False
    if float(p.get("move_pct") or 0) < MIN_PRICE_UP_PCT:
        return False
    ch24 = p.get("change_24h")
    if ch24 is not None and float(ch24) > MAX_24H_CHANGE:
        # هنوز می‌تونه DEVELOPING باشه؛ سخت رد نکن — فقط علامت بزن
        p["late_risk"] = True
    return True


async def fetch_recent_pumps(limit_messages: int = 40) -> Dict[str, Any]:
    if not SESSION or not API_ID or not API_HASH:
        return {"error": "TELEGRAM_SESSION / API_ID / API_HASH تنظیم نشده", "alerts": []}

    client = TelegramClient(
        StringSession(SESSION),
        API_ID,
        API_HASH,
        connection_retries=3,
        request_retries=3,
        retry_delay=1,
        timeout=20,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=30)
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=15):
            return {"error": "سشن تلگرام authorize نیست", "alerts": []}

        entity = await client.get_entity(PUMP_CHANNEL)
        parsed: List[Dict[str, Any]] = []
        seen = set()
        checked = 0
        async for msg in client.iter_messages(entity, limit=limit_messages):
            checked += 1
            text = msg.message or ""
            p = parse_pump_message(text)
            if not p or not _passes_raw_filter(p):
                continue
            key = p["ticker"]
            if key in seen:
                continue
            seen.add(key)
            p["msg_date"] = msg.date.isoformat() if msg.date else None
            parsed.append(p)
            if len(parsed) >= 12:
                break

        return {
            "channel": PUMP_CHANNEL,
            "messages_checked": checked,
            "candidates": parsed,
        }
    except Exception as e:
        return {"error": str(e)[:300], "alerts": []}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def score_pump_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """روی هر کاندید analyze_token بزن و فقط فاز EARLY/DEVELOPING را نگه دار."""
    kept = []
    skipped = []
    for p in candidates[:10]:
        ticker = p["ticker"]
        try:
            r = analyze_token(symbol=ticker)
            if r.get("error"):
                skipped.append({"ticker": ticker, "reason": r.get("error"), "pump": p})
                continue
            phase = (r.get("entry_phase") or "NEUTRAL").upper()
            score = int(r.get("score") or 0)
            ch24 = r.get("metrics", {}).get("price_change_24h")
            if ch24 is None:
                ch24 = p.get("change_24h")

            reject = None
            if phase not in ALLOWED_PHASES and phase not in ("", "NEUTRAL"):
                # NEUTRAL با امتیاز خوب هنوز قابل‌بررسی است اگر vol خیلی بالا باشد
                if phase in ("EXHAUSTED", "EXTENDED", "BEARISH"):
                    reject = f"فاز {phase}"
            if phase == "EXHAUSTED":
                reject = "EXHAUSTED / chase"
            if ch24 is not None and float(ch24) > 90:
                reject = f"رشد ۲۴س بیش از حد ({ch24}%)"
            if score < 45 and phase not in ALLOWED_PHASES:
                reject = f"امتیاز پایین ({score})"

            item = {
                "ticker": ticker,
                "pump": p,
                "result": r,
                "phase": phase,
                "score": score,
            }
            if reject:
                item["reject"] = reject
                skipped.append(item)
            else:
                kept.append(item)
        except Exception as e:
            skipped.append({"ticker": ticker, "reason": str(e)[:120], "pump": p})

    kept.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return {"kept": kept, "skipped": skipped}


async def scan_pumps(limit_messages: int = 40) -> Dict[str, Any]:
    meta = await fetch_recent_pumps(limit_messages=limit_messages)
    if meta.get("error"):
        return meta
    scored = score_pump_candidates(meta.get("candidates") or [])
    return {
        "channel": meta.get("channel"),
        "messages_checked": meta.get("messages_checked", 0),
        "candidates_raw": len(meta.get("candidates") or []),
        "kept": scored["kept"],
        "skipped": scored["skipped"],
    }


def format_pump_report(data: Dict[str, Any]) -> str:
    if data.get("error"):
        return f"❌ خطا در مانیتور پامپ:\n{data['error']}"
    lines = [
        "⚡ *هشدار مومنتوم زودهنگام*",
        f"منبع: @{data.get('channel') or PUMP_CHANNEL}",
        f"پیام: {data.get('messages_checked', 0)} | کاندید خام: {data.get('candidates_raw', 0)}",
        "",
    ]
    kept = data.get("kept") or []
    if not kept:
        lines.append("مورد قابل‌اتکا با فاز EARLY/DEVELOPING پیدا نشد.")
        skipped = data.get("skipped") or []
        if skipped:
            lines.append("\nردشده‌ها (نمونه):")
            for s in skipped[:5]:
                t = s.get("ticker")
                why = s.get("reject") or s.get("reason") or "-"
                lines.append(f"• #{t}: {why}")
        lines.append("\n_فیلتر: UP + حجم بالا + فاز ورود_")
        lines.append("_NFA | DYOR_")
        return "\n".join(lines)

    lines.append(f"✅ تاییدشده: {len(kept)}\n")
    for item in kept[:8]:
        r = item.get("result") or {}
        p = item.get("pump") or {}
        t = item.get("ticker")
        phase = item.get("phase")
        score = item.get("score")
        cat = r.get("category") or "-"
        price = r.get("price_str") or p.get("price") or "-"
        vol_up = p.get("vol_up_pct")
        move = p.get("move_pct")
        pa = r.get("pa_score")
        phase_map = {
            "EARLY": "🌱EARLY",
            "DEVELOPING": "🟢DEV",
            "EXTENDED": "🟡EXT",
            "EXHAUSTED": "🔴EXH",
            "BEARISH": "⬇️BEAR",
        }
        ph = phase_map.get(phase, phase)
        lines.append(
            f"*{ph}* #{t} | {price} | {score}/100 {cat}\n"
            f"پامپ: UP {move}% | Vol+{vol_up}% | PA:{pa}/20\n"
            f"#{t}   #{t}USDT   ${t}   ${t}USDT\n"
        )
    lines.append("_فقط EARLY/DEVELOPING بعد از فیلتر فاز_")
    lines.append("_NFA | DYOR_")
    return "\n".join(lines)
