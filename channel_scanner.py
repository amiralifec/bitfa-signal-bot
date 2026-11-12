"""
خواندن کانال BITFA - نسخه تمیز:
اولویت PDF واچ‌لیست، فیلتر نویز، مرتب‌سازی بر اساس امتیاز
"""

import os
import re
from typing import List, Dict, Any, Tuple
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument

from scorer import analyze_token
from pdf_parser import parse_watchlist_pdf, extract_tickers_from_text

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or ""
SESSION = os.getenv("TELEGRAM_SESSION") or ""
CHANNEL = os.getenv("BITFA_CHANNEL") or "bitfa"

WATCHLIST_HINTS = re.compile(
    r"(watch\s*list|واچ\s*لیست|واچلیست|watchlist|#watch|پرپتانسیل)",
    re.IGNORECASE,
)


def _is_pdf_document(msg) -> bool:
    try:
        if not msg.media or not isinstance(msg.media, MessageMediaDocument):
            return False
        doc = msg.media.document
        if not doc:
            return False
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


def _looks_like_watchlist_text(text: str) -> bool:
    if not text:
        return False
    if WATCHLIST_HINTS.search(text):
        return True
    # چند هشتگ در یک پیام
    tags = re.findall(r"#[A-Za-z][A-Za-z0-9]{1,14}", text)
    return len(tags) >= 2


async def fetch_recent_tickers(limit_messages: int = 40) -> Dict[str, Any]:
    if not SESSION or not API_ID or not API_HASH:
        return {"error": "TELEGRAM_SESSION / API_ID / API_HASH تنظیم نشده", "tickers": [], "messages_checked": 0}

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return {"error": "Session نامعتبر است. دوباره بساز.", "tickers": [], "messages_checked": 0}

    pdf_tickers: List[str] = []
    text_tickers: List[str] = []
    samples = []
    pdfs_parsed = 0
    count = 0

    try:
        entity = await client.get_entity(CHANNEL)
        async for msg in client.iter_messages(entity, limit=limit_messages):
            count += 1
            text = msg.message or ""

            # ۱) PDFها اول و مهم‌تر
            if _is_pdf_document(msg):
                try:
                    data = await client.download_media(msg, file=bytes)
                    if data:
                        parsed = parse_watchlist_pdf(data)
                        pdfs_parsed += 1
                        for t in parsed.get("tickers") or []:
                            if t not in pdf_tickers:
                                pdf_tickers.append(t)
                        if len(samples) < 4:
                            samples.append({
                                "type": "pdf",
                                "id": msg.id,
                                "tickers": (parsed.get("tickers") or [])[:12],
                                "chars": parsed.get("chars", 0),
                            })
                except Exception as e:
                    print(f"PDF download/parse error: {e}")

            # ۲) فقط متن‌هایی که شبیه واچ‌لیست‌اند
            elif _looks_like_watchlist_text(text):
                found = extract_tickers_from_text(text, strict=True)
                for t in found:
                    if t not in text_tickers and t not in pdf_tickers:
                        text_tickers.append(t)
                if found and len(samples) < 6:
                    samples.append({
                        "type": "text",
                        "id": msg.id,
                        "date": str(msg.date),
                        "tickers": found,
                        "preview": text[:100].replace("\n", " "),
                    })

            # اگر از PDF به اندازه کافی تیکر داریم، کافی است
            if len(pdf_tickers) >= 15:
                break

    except Exception as e:
        await client.disconnect()
        return {"error": f"خطا در خواندن کانال: {e}", "tickers": [], "messages_checked": 0}

    await client.disconnect()

    # اولویت: PDF سپس متن واچ‌لیست
    merged: List[str] = []
    for t in pdf_tickers + text_tickers:
        if t not in merged:
            merged.append(t)

    return {
        "tickers": merged[:20],
        "pdf_tickers": pdf_tickers,
        "text_tickers": text_tickers,
        "messages_checked": count,
        "pdfs_parsed": pdfs_parsed,
        "samples": samples,
        "channel": CHANNEL,
    }


async def scan_and_score(limit_messages: int = 40) -> Dict[str, Any]:
    meta = await fetch_recent_tickers(limit_messages=limit_messages)
    if meta.get("error"):
        return meta

    tickers = meta.get("tickers") or []
    scored_rows: List[Tuple[int, str, dict]] = []

    for t in tickers[:15]:
        try:
            r = analyze_token(symbol=t)
            score = int(r.get("score") or 0)
            scored_rows.append((score, t, r))
        except Exception as e:
            scored_rows.append((0, t, {"error": str(e)[:100], "score": 0, "category": "SKIP", "token": t}))

    # مرتب‌سازی از امتیاز بالا به پایین
    scored_rows.sort(key=lambda x: x[0], reverse=True)

    summary = {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []}
    results = []
    for score, t, r in scored_rows:
        cat = r.get("category", "SKIP")
        if cat not in summary:
            cat = "SKIP"
        label = f"#{r.get('token') or t} ({score})"
        summary[cat].append(label)
        results.append({"ticker": t, "result": r})

    # برای خروجی تمیز: اول غیر-SKIPها، بعد حداکثر چند SKIP
    focus = [x for x in results if (x["result"].get("category") in ("HOT", "QUALIFIED", "WATCH"))]
    skips = [x for x in results if x["result"].get("category") == "SKIP"][:4]
    display = focus + skips

    return {
        "channel": meta.get("channel"),
        "messages_checked": meta.get("messages_checked"),
        "pdfs_parsed": meta.get("pdfs_parsed", 0),
        "tickers_found": tickers,
        "pdf_tickers": meta.get("pdf_tickers", []),
        "text_tickers": meta.get("text_tickers", []),
        "summary": summary,
        "results": display,
        "samples": meta.get("samples", []),
    }
