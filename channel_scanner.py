"""
خواندن کانال BITFA - timeout + یادداشت تحلیلگر + حافظه اسکن
"""

import os
import re
import asyncio
from typing import List, Dict, Any, Tuple
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument

from scorer import analyze_token
from pdf_parser import parse_watchlist_pdf, extract_tickers_from_text
from storage import load_last_scan, save_last_scan, diff_with_previous

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
    tags = re.findall(r"#[A-Za-z][A-Za-z0-9]{1,14}", text)
    return len(tags) >= 2


async def fetch_recent_tickers(limit_messages: int = 30) -> Dict[str, Any]:
    if not SESSION or not API_ID or not API_HASH:
        return {"error": "TELEGRAM_SESSION / API_ID / API_HASH تنظیم نشده", "tickers": [], "messages_checked": 0}

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
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return {"error": f"اتصال تلگرام ناموفق: {e}", "tickers": [], "messages_checked": 0}

    try:
        if not await asyncio.wait_for(client.is_user_authorized(), timeout=15):
            await client.disconnect()
            return {"error": "Session نامعتبر است. دوباره بساز.", "tickers": [], "messages_checked": 0}
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return {"error": f"بررسی Session ناموفق: {e}", "tickers": [], "messages_checked": 0}

    pdf_tickers: List[str] = []
    text_tickers: List[str] = []
    notes_map: Dict[str, Dict[str, Any]] = {}
    samples = []
    pdfs_parsed = 0
    count = 0

    try:
        entity = await asyncio.wait_for(client.get_entity(CHANNEL), timeout=25)
        async for msg in client.iter_messages(entity, limit=limit_messages):
            count += 1
            text = msg.message or ""

            if _is_pdf_document(msg) and pdfs_parsed < 3:
                try:
                    data = await asyncio.wait_for(client.download_media(msg, file=bytes), timeout=45)
                    if data:
                        parsed = parse_watchlist_pdf(data)
                        pdfs_parsed += 1
                        for t in parsed.get("tickers") or []:
                            if t not in pdf_tickers:
                                pdf_tickers.append(t)
                        for k, v in (parsed.get("notes_map") or {}).items():
                            if k not in notes_map or (v.get("analyst_note") and not notes_map[k].get("analyst_note")):
                                notes_map[k] = v
                        if len(samples) < 4:
                            samples.append({
                                "type": "pdf",
                                "id": msg.id,
                                "tickers": (parsed.get("tickers") or [])[:12],
                                "chars": parsed.get("chars", 0),
                                "notes_count": len(parsed.get("notes_map") or {}),
                            })
                except Exception as e:
                    print(f"PDF download/parse error: {e}")

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

            if len(pdf_tickers) >= 12:
                break

    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return {"error": f"خطا در خواندن کانال: {e}", "tickers": [], "messages_checked": count}

    try:
        await client.disconnect()
    except Exception:
        pass

    merged: List[str] = []
    for t in pdf_tickers + text_tickers:
        if t not in merged:
            merged.append(t)

    return {
        "tickers": merged[:18],
        "pdf_tickers": pdf_tickers,
        "text_tickers": text_tickers,
        "notes_map": notes_map,
        "messages_checked": count,
        "pdfs_parsed": pdfs_parsed,
        "samples": samples,
        "channel": CHANNEL,
    }


def _apply_note_to_result(r: dict, note_info: dict) -> dict:
    if not note_info:
        return r
    r = dict(r)
    note = note_info.get("analyst_note") or ""
    about = note_info.get("about") or ""
    risk_label = note_info.get("risk_label")
    boost = int(note_info.get("note_boost") or 0)

    if note:
        r["analyst_note"] = note
    if about:
        r["about_project"] = about
    if risk_label:
        r["bitfa_risk_label"] = risk_label

    if boost and not r.get("error"):
        old = int(r.get("score") or 0)
        new_score = max(0, min(100, old + boost))
        r["score"] = new_score
        r["note_boost"] = boost
        reasons = list(r.get("reasons") or [])
        if boost > 0:
            reasons.insert(0, f"یادداشت تحلیلگر BITFA: مثبت (+{boost})")
        elif boost < 0:
            reasons.insert(0, f"یادداشت تحلیلگر BITFA: محتاطانه ({boost})")
        r["reasons"] = reasons

        conf = int(r.get("confidence") or 0)
        if new_score >= 80 and conf >= 70:
            r["category"], r["recommendation"], r["action"] = "HOT", "امتیاز عالی - قابل بررسی جدی برای ورود محدود", "اولویت بررسی"
        elif new_score >= 65:
            r["category"], r["recommendation"], r["action"] = "QUALIFIED", "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت", "بررسی برای ورود"
        elif new_score >= 48:
            r["category"], r["recommendation"], r["action"] = "WATCH", "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار", "نظارت"
        else:
            r["category"], r["recommendation"], r["action"] = "SKIP", "امتیاز ضعیف - رد شود", "رد"

    return r


async def scan_and_score(limit_messages: int = 30, persist: bool = True) -> Dict[str, Any]:
    meta = await fetch_recent_tickers(limit_messages=limit_messages)
    if meta.get("error"):
        return meta

    tickers = meta.get("tickers") or []
    notes_map = meta.get("notes_map") or {}
    if not tickers:
        return {
            "channel": meta.get("channel"),
            "messages_checked": meta.get("messages_checked"),
            "pdfs_parsed": meta.get("pdfs_parsed", 0),
            "tickers_found": [],
            "summary": {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []},
            "results": [],
            "error": None,
            "note": "تیکری پیدا نشد",
            "diff": {"new": [], "improved": [], "dropped": [], "unchanged_hot": []},
        }

    scored_rows: List[Tuple[int, str, dict]] = []

    for t in tickers[:10]:
        try:
            r = analyze_token(symbol=t)
            r = _apply_note_to_result(r, notes_map.get(t.upper()) or notes_map.get(t))
            score = int(r.get("score") or 0)
            scored_rows.append((score, t, r))
        except Exception as e:
            scored_rows.append((0, t, {"error": str(e)[:100], "score": 0, "category": "SKIP", "token": t}))

    scored_rows.sort(key=lambda x: x[0], reverse=True)

    summary = {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []}
    results = []
    current_map: Dict[str, Dict[str, Any]] = {}

    for score, t, r in scored_rows:
        cat = r.get("category", "SKIP")
        if cat not in summary:
            cat = "SKIP"
        token = (r.get("token") or t).upper()
        label = f"#{token} ({score})"
        summary[cat].append(label)
        results.append({"ticker": t, "result": r})
        current_map[token] = {
            "score": score,
            "category": cat,
            "token": token,
            "pa_score": r.get("pa_score"),
        }

    prev = load_last_scan()
    diff = diff_with_previous(current_map, prev)

    if persist:
        save_last_scan(current_map)

    focus = [x for x in results if (x["result"].get("category") in ("HOT", "QUALIFIED", "WATCH"))]
    skips = [x for x in results if x["result"].get("category") == "SKIP"][:4]

    return {
        "channel": meta.get("channel"),
        "messages_checked": meta.get("messages_checked"),
        "pdfs_parsed": meta.get("pdfs_parsed", 0),
        "tickers_found": tickers,
        "pdf_tickers": meta.get("pdf_tickers", []),
        "text_tickers": meta.get("text_tickers", []),
        "notes_map": notes_map,
        "summary": summary,
        "results": focus + skips,
        "samples": meta.get("samples", []),
        "diff": diff,
    }
