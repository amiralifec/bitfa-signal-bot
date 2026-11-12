"""
خواندن پیام‌های اخیر کانال BITFA و استخراج تیکر
"""

import os
import re
from typing import List, Dict, Any
from telethon import TelegramClient
from telethon.sessions import StringSession

from scorer import analyze_token

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or ""
SESSION = os.getenv("TELEGRAM_SESSION") or ""
CHANNEL = os.getenv("BITFA_CHANNEL") or "bitfa"

STOPWORDS = {
    "BITFA", "WATCHLIST", "NFA", "DYOR", "USDT", "USD", "BTC", "ETH",
    "LONG", "SHORT", "BUY", "SELL", "ENTRY", "EXIT", "STOP", "TARGET",
    "SUPPORT", "RESISTANCE", "BREAKOUT", "PULLBACK", "WATCH", "LIST",
    "SIGNAL", "FUTURES", "SPOT", "DEX", "CEX", "SOL", "BSC", "BASE",
    "UPDATE", "NOTE", "WARNING", "DISCLAIMER", "PDF", "HTML"
}


def extract_tickers(text: str) -> List[str]:
    if not text:
        return []
    items = []
    for m in re.finditer(r"#([A-Za-z][A-Za-z0-9]{1,14})", text):
        t = m.group(1).upper()
        if t not in STOPWORDS:
            items.append(t)
    # حذف تکراری
    seen = set()
    out = []
    for t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


async def fetch_recent_tickers(limit_messages: int = 40) -> Dict[str, Any]:
    if not SESSION or not API_ID or not API_HASH:
        return {"error": "TELEGRAM_SESSION / API_ID / API_HASH تنظیم نشده", "tickers": [], "messages_checked": 0}

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return {"error": "Session نامعتبر است. دوباره بساز.", "tickers": [], "messages_checked": 0}

    tickers = []
    samples = []
    try:
        entity = await client.get_entity(CHANNEL)
        count = 0
        async for msg in client.iter_messages(entity, limit=limit_messages):
            count += 1
            text = msg.message or ""
            found = extract_tickers(text)
            if found:
                for t in found:
                    if t not in tickers:
                        tickers.append(t)
                if len(samples) < 5:
                    samples.append({"id": msg.id, "date": str(msg.date), "tickers": found, "preview": text[:120].replace("\n", " ")})
            if len(tickers) >= 20:
                break
    except Exception as e:
        await client.disconnect()
        return {"error": f"خطا در خواندن کانال: {e}", "tickers": [], "messages_checked": 0}

    await client.disconnect()
    return {
        "tickers": tickers[:20],
        "messages_checked": count,
        "samples": samples,
        "channel": CHANNEL,
    }


async def scan_and_score(limit_messages: int = 40) -> Dict[str, Any]:
    meta = await fetch_recent_tickers(limit_messages=limit_messages)
    if meta.get("error"):
        return meta

    tickers = meta.get("tickers") or []
    results = []
    summary = {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []}

    for t in tickers[:12]:  # محدودیت برای سرعت و rate limit
        try:
            r = analyze_token(symbol=t)
            results.append({"ticker": t, "result": r})
            cat = r.get("category", "SKIP")
            if cat in summary:
                summary[cat].append(f"#{t} ({r.get('score', 0)})")
        except Exception as e:
            results.append({"ticker": t, "result": {"error": str(e)[:100], "score": 0, "category": "SKIP"}})
            summary["SKIP"].append(f"#{t}")

    return {
        "channel": meta.get("channel"),
        "messages_checked": meta.get("messages_checked"),
        "tickers_found": tickers,
        "summary": summary,
        "results": results,
        "samples": meta.get("samples", []),
    }
