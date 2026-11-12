"""
خواندن پیام‌ها و PDFهای کانال BITFA + امتیازدهی
"""

import os
import re
from typing import List, Dict, Any
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument

from scorer import analyze_token
from pdf_parser import parse_watchlist_pdf, extract_tickers_from_text

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
    return extract_tickers_from_text(text or "")


def _is_pdf_document(msg) -> bool:
    try:
        if not msg.media or not isinstance(msg.media, MessageMediaDocument):
            return False
        doc = msg.media.document
        if not doc:
            return False
        # mime یا نام فایل
        mime = getattr(doc, "mime_type", "") or ""
        if "pdf" in mime.lower():
            return True
        for attr in (doc.attributes or []):
            fn = getattr(attr, "file_name", "") or ""
            if fn.lower().endswith(".pdf"):
                return True
        return False
    except Exception:
        return False


async def fetch_recent_tickers(limit_messages: int = 50) -> Dict[str, Any]:
    if not SESSION or not API_ID or not API_HASH:
        return {"error": "TELEGRAM_SESSION / API_ID / API_HASH تنظیم نشده", "tickers": [], "messages_checked": 0}

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return {"error": "Session نامعتبر است. دوباره بساز.", "tickers": [], "messages_checked": 0}

    tickers: List[str] = []
    sources: List[str] = []
    samples = []
    pdfs_parsed = 0

    try:
        entity = await client.get_entity(CHANNEL)
        count = 0
        async for msg in client.iter_messages(entity, limit=limit_messages):
            count += 1
            text = msg.message or ""

            # متن پیام
            found = extract_tickers(text)
            for t in found:
                if t not in tickers:
                    tickers.append(t)
                    sources.append("text")

            # PDF پیوست
            if _is_pdf_document(msg):
                try:
                    data = await client.download_media(msg, file=bytes)
                    if data:
                        parsed = parse_watchlist_pdf(data)
                        pdfs_parsed += 1
                        for t in parsed.get("tickers") or []:
                            if t not in tickers:
                                tickers.append(t)
                                sources.append("pdf")
                        if len(samples) < 3:
                            samples.append({
                                "type": "pdf",
                                "id": msg.id,
                                "tickers": parsed.get("tickers", [])[:10],
                                "chars": parsed.get("chars", 0),
                            })
                except Exception as e:
                    print(f"PDF download/parse error: {e}")

            if found and len(samples) < 5:
                samples.append({
                    "type": "text",
                    "id": msg.id,
                    "date": str(msg.date),
                    "tickers": found,
                    "preview": text[:120].replace("\n", " "),
                })

            if len(tickers) >= 25:
                break
    except Exception as e:
        await client.disconnect()
        return {"error": f"خطا در خواندن کانال: {e}", "tickers": [], "messages_checked": 0}

    await client.disconnect()
    return {
        "tickers": tickers[:25],
        "messages_checked": count,
        "pdfs_parsed": pdfs_parsed,
        "samples": samples,
        "channel": CHANNEL,
    }


async def scan_and_score(limit_messages: int = 50) -> Dict[str, Any]:
    meta = await fetch_recent_tickers(limit_messages=limit_messages)
    if meta.get("error"):
        return meta

    tickers = meta.get("tickers") or []
    results = []
    summary = {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []}

    for t in tickers[:12]:
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
        "pdfs_parsed": meta.get("pdfs_parsed", 0),
        "tickers_found": tickers,
        "summary": summary,
        "results": results,
        "samples": meta.get("samples", []),
    }
