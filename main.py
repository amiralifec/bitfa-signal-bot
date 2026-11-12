"""
BITFA Scorer + Telegram Bot
نسخه ۱.۱.۱ - جلوگیری از پاسخ‌های تکراری /scan
"""

import os
import re
import logging
import asyncio
import time
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from typing import Optional, List, Set
import uvicorn
import requests as http_requests

from scorer import analyze_token
from pdf_parser import parse_watchlist_pdf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_BASE = os.getenv("RENDER_EXTERNAL_URL") or "https://bitfa-signal-bot.onrender.com"

app = FastAPI(title="BITFA Signal Scorer", version="1.1.1")

# جلوگیری از اسکن همزمان و پردازش تکراری آپدیت
_scan_locks: Set[int] = set()
_processed_updates: Set[int] = set()
_processed_max = 500

STOPWORDS = {
    "BITFA", "WATCHLIST", "NFA", "DYOR", "USDT", "USD", "BTC", "ETH",
    "THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "HTTP", "HTTPS",
    "COM", "WWW", "PDF", "IMG", "PNG", "JPG", "HTML", "NULL", "TRUE", "FALSE",
    "LONG", "SHORT", "BUY", "SELL", "ENTRY", "EXIT", "STOP", "TARGET",
    "SUPPORT", "RESISTANCE", "BREAKOUT", "PULLBACK", "WATCH", "LIST",
    "SIGNAL", "FUTURES", "SPOT", "DEX", "CEX", "SOL", "BSC", "BASE",
    "ARIA", "UPDATE", "NOTE", "WARNING", "DISCLAIMER"
}


class AnalyzeRequest(BaseModel):
    symbol: Optional[str] = None
    address: Optional[str] = None


def is_address(text: str) -> bool:
    text = text.strip()
    if re.match(r"^0x[a-fA-F0-9]{40}$", text):
        return True
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", text):
        return True
    return False


def extract_tickers_and_addresses(text: str) -> List[str]:
    items = []
    for m in re.finditer(r"0x[a-fA-F0-9]{40}", text):
        items.append(m.group(0))
    for m in re.finditer(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", text):
        cand = m.group(0)
        if not cand.isdigit() and cand not in items:
            items.append(cand)
    for m in re.finditer(r"#([A-Za-z][A-Za-z0-9]{1,14})", text):
        t = m.group(1).upper()
        if t not in STOPWORDS and t not in [x.upper() for x in items]:
            items.append(t)
    if len(items) < 2:
        parts = re.split(r"[,\s\n/|]+", text)
        for part in parts:
            part = part.strip().lstrip("#").strip()
            if not part:
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9]{1,11}$", part):
                t = part.upper()
                if t not in STOPWORDS and t not in [x.upper() for x in items]:
                    items.append(t)
    seen = set()
    unique = []
    for i in items:
        key = i.lower()
        if key not in seen:
            seen.add(key)
            unique.append(i)
    return unique[:12]


def format_single(name: str, result: dict) -> str:
    if result.get("error"):
        return f"*{name}* → خطا: {result.get('error')}"
    token = result.get("token") or name
    price_str = result.get("price_str") or "-"
    score = result.get("score", 0)
    category = result.get("category", "-")
    action = result.get("action", "-")
    risk = result.get("risk_level", "-")
    rank = result.get("rank")
    cat_emoji = {"HOT": "🔥", "QUALIFIED": "✅", "WATCH": "👀", "SKIP": "❌"}.get(category, "▪️")
    rank_txt = f" | رتبه #{rank}" if rank else ""
    return (
        f"{cat_emoji} *#{token}* | {price_str}{rank_txt}\n"
        f"{score}/100 | {category} | {action} | ریسک: {risk}"
    )


def format_full(result: dict) -> str:
    if result.get("error"):
        return f"❌ خطا: {result.get('error')}"

    token = result.get("token") or "?"
    token_name = result.get("token_name") or ""
    price_str = result.get("price_str") or "-"
    rank = result.get("rank")
    score = result.get("score", 0)
    category = result.get("category", "-")
    rec = result.get("recommendation", "-")
    action = result.get("action", "-")
    risk = result.get("risk_level", "-")
    conf = result.get("confidence", 0)
    pos = result.get("position_suggestion", "-")
    reasons = result.get("reasons", [])
    warnings = result.get("warnings", [])
    metrics = result.get("metrics", {})
    links = result.get("links") or {}

    cat_emoji = {"HOT": "🔥", "QUALIFIED": "✅", "WATCH": "👀", "SKIP": "❌"}.get(category, "▪️")
    title = f"#{token}"
    if token_name:
        title += f" ({token_name})"

    lines = [
        f"{cat_emoji} *نتیجه تحلیل*",
        "",
        f"🪙 *ارز:* {title}",
        f"💵 *قیمت لحظه‌ای:* {price_str}",
    ]
    if rank:
        lines.append(f"🏅 *رتبه مارکت‌کپ:* #{rank}")

    lines += [
        "",
        f"📊 *امتیاز:* {score}/100",
        f"🏷 *دسته:* {category}",
        f"⚡ *اقدام:* {action}",
        f"⚠️ *ریسک:* {risk}",
        f"🎯 *اعتماد:* {conf}%",
        f"💰 *پیشنهاد حجم:* {pos}",
        "",
        f"📝 *توصیه:*\n{rec}",
    ]

    if reasons:
        lines.append("\n✅ *نکات:*")
        for r in reasons[:6]:
            lines.append(f"• {r}")

    if warnings:
        lines.append("\n⚠️ *هشدارها:*")
        for w in warnings[:4]:
            lines.append(f"• {w}")

    if metrics:
        lines.append("\n📈 *متریک‌ها:*")
        if metrics.get("liquidity_usd"):
            lines.append(f"• لیکوئیدیتی دکس: ${metrics['liquidity_usd']:,.0f}")
        if metrics.get("volume_24h"):
            lines.append(f"• حجم (تقریبی): ${metrics['volume_24h']:,.0f}")
        if metrics.get("market_cap"):
            lines.append(f"• مارکت‌کپ: ${metrics['market_cap']:,.0f}")
        if metrics.get("price_change_24h") is not None:
            lines.append(f"• تغییر ۲۴س: {metrics['price_change_24h']}%")
        if metrics.get("chain"):
            lines.append(f"• زنجیره دکس: {metrics['chain']}")

    if links.get("coingecko") or links.get("dexscreener"):
        lines.append("\n🔗 *لینک بررسی:*")
        if links.get("coingecko"):
            lines.append(f"• CoinGecko: {links['coingecko']}")
        if links.get("dexscreener"):
            lines.append(f"• DexScreener: {links['dexscreener']}")

    lines.append("\n_NFA | DYOR_")
    return "\n".join(lines)


def format_scan(data: dict) -> str:
    if data.get("error"):
        return f"❌ خطا در اسکن کانال:\n{data.get('error')}"

    lines = [
        "📡 *اسکن کانال BITFA*",
        f"پیام‌های بررسی‌شده: {data.get('messages_checked', 0)}",
        f"PDFهای خوانده‌شده: {data.get('pdfs_parsed', 0)}",
        f"تیکرهای پیدا شده: {len(data.get('tickers_found') or [])}",
        "",
    ]
    summary = data.get("summary") or {}
    if summary.get("HOT"):
        lines.append("🔥 *HOT:* " + ", ".join(summary["HOT"]))
    if summary.get("QUALIFIED"):
        lines.append("✅ *QUALIFIED:* " + ", ".join(summary["QUALIFIED"]))
    if summary.get("WATCH"):
        lines.append("👀 *WATCH:* " + ", ".join(summary["WATCH"]))
    if summary.get("SKIP"):
        lines.append("❌ *SKIP:* " + ", ".join(summary["SKIP"]))

    lines.append("\n────────────\n*جزئیات (حداکثر ۱۲ تا):*\n")
    for item in (data.get("results") or []):
        t = item.get("ticker")
        r = item.get("result") or {}
        lines.append(format_single(t, r))
        lines.append("")

    lines.append("_دستور: /scan_\n_NFA | DYOR_")
    return "\n".join(lines)


def score_ticker_list(tickers: List[str]) -> dict:
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
        "messages_checked": 0,
        "pdfs_parsed": 1,
        "tickers_found": tickers,
        "summary": summary,
        "results": results,
    }


def send_telegram_message(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if len(text) > 4000:
        text = text[:3900] + "\n\n... (خلاصه شده)"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        http_requests.post(url, json=payload, timeout=20)
    except Exception as e:
        logger.error(f"send message failed: {e}")


def download_telegram_file(file_id: str) -> bytes:
    r = http_requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=20,
    )
    r.raise_for_status()
    path = (r.json().get("result") or {}).get("file_path")
    if not path:
        raise RuntimeError("file_path خالی است")
    fr = http_requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=60)
    fr.raise_for_status()
    return fr.content


async def run_scan_job(chat_id: int):
    """اجرای اسکن در پس‌زمینه تا وب‌هوک سریع ۲۰۰ برگرداند"""
    if chat_id in _scan_locks:
        send_telegram_message(chat_id, "یک اسکن در حال اجراست. لطفاً صبر کن.")
        return
    _scan_locks.add(chat_id)
    try:
        from channel_scanner import scan_and_score
        result = await scan_and_score(limit_messages=40)
        send_telegram_message(chat_id, format_scan(result))
    except Exception as e:
        logger.exception("scan failed")
        send_telegram_message(chat_id, f"خطا در /scan:\n{str(e)[:300]}")
    finally:
        _scan_locks.discard(chat_id)


@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "1.1.1",
        "message": "BITFA Scorer + /scan + PDF (no duplicate replies)",
        "bot": "enabled" if BOT_TOKEN else "disabled"
    }


@app.get("/health")
def health():
    return {"status": "healthy", "version": "1.1.1"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.symbol and not req.address:
        return {"error": "symbol یا address الزامی است", "score": 0}
    return analyze_token(symbol=req.symbol, address=req.address)


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    if not BOT_TOKEN:
        return Response(status_code=200)

    try:
        data = await request.json()
    except Exception:
        return Response(status_code=200)

    # جلوگیری از پردازش تکراری همان update_id (retry تلگرام)
    update_id = data.get("update_id")
    if update_id is not None:
        if update_id in _processed_updates:
            return Response(status_code=200)
        _processed_updates.add(update_id)
        if len(_processed_updates) > _processed_max:
            # پاکسازی ساده
            for _ in range(100):
                try:
                    _processed_updates.pop()
                except KeyError:
                    break

    message = data.get("message") or data.get("edited_message")
    if not message:
        return Response(status_code=200)

    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    # آپلود PDF
    doc = message.get("document")
    if doc:
        file_name = (doc.get("file_name") or "").lower()
        mime = (doc.get("mime_type") or "").lower()
        if file_name.endswith(".pdf") or "pdf" in mime:
            send_telegram_message(chat_id, "PDF دریافت شد. در حال استخراج تیکر... ⏳")
            try:
                content = download_telegram_file(doc["file_id"])
                parsed = parse_watchlist_pdf(content)
                tickers = parsed.get("tickers") or []
                if not tickers:
                    send_telegram_message(chat_id, "در این PDF تیکری پیدا نشد.")
                else:
                    scored = score_ticker_list(tickers)
                    send_telegram_message(chat_id, format_scan(scored))
            except Exception as e:
                logger.exception("pdf upload failed")
                send_telegram_message(chat_id, f"خطا در خواندن PDF:\n{str(e)[:250]}")
            return Response(status_code=200)

    if not text:
        return Response(status_code=200)

    if text.startswith("/start"):
        send_telegram_message(
            chat_id,
            "سلام 👋\nربات امتیازدهی سبک BITFA\n\n"
            "• تیکر / آدرس / متن واچ‌لیست بفرست\n"
            "• PDF واچ‌لیست را مستقیم بفرست\n"
            "• /scan برای اسکن کانال @bitfa (متن + PDF)"
        )
        return Response(status_code=200)

    if text.startswith("/help"):
        send_telegram_message(
            chat_id,
            "دستورات:\n"
            "/scan — خواندن پیام و PDFهای اخیر کانال BITFA\n"
            "یا تیکر/آدرس/متن/فایل PDF بفرست."
        )
        return Response(status_code=200)

    if text.startswith("/scan"):
        if chat_id in _scan_locks:
            send_telegram_message(chat_id, "یک اسکن در حال اجراست. لطفاً صبر کن.")
            return Response(status_code=200)

        send_telegram_message(chat_id, "در حال اسکن کانال @bitfa (متن + PDF)... ⏳\nممکن است تا ۲ دقیقه طول بکشد.")
        # پردازش در پس‌زمینه — فوراً ۲۰۰ برمی‌گردانیم تا تلگرام retry نکند
        asyncio.create_task(run_scan_job(chat_id))
        return Response(status_code=200)

    if text.startswith("/"):
        return Response(status_code=200)

    items = extract_tickers_and_addresses(text)
    if not items:
        send_telegram_message(chat_id, "تیکر یا آدرسی پیدا نشد.")
        return Response(status_code=200)

    send_telegram_message(chat_id, f"{len(items)} مورد پیدا شد. در حال تحلیل... ⏳")

    results = []
    summary = {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []}

    for item in items:
        try:
            if is_address(item):
                result = analyze_token(address=item)
            else:
                result = analyze_token(symbol=item.upper())
            name = result.get("token") or item
            results.append((name, result))
            cat = result.get("category", "SKIP")
            if cat in summary:
                summary[cat].append(f"#{name} ({result.get('score', 0)})")
        except Exception as e:
            results.append((item, {"error": str(e)[:80], "score": 0, "category": "SKIP"}))
            summary["SKIP"].append(str(item))

    if len(results) == 1:
        _, result = results[0]
        send_telegram_message(chat_id, format_full(result))
        return Response(status_code=200)

    lines = ["📋 *خلاصه نتایج*\n"]
    if summary["HOT"]:
        lines.append("🔥 *HOT:* " + ", ".join(summary["HOT"]))
    if summary["QUALIFIED"]:
        lines.append("✅ *QUALIFIED:* " + ", ".join(summary["QUALIFIED"]))
    if summary["WATCH"]:
        lines.append("👀 *WATCH:* " + ", ".join(summary["WATCH"]))
    if summary["SKIP"]:
        lines.append("❌ *SKIP:* " + ", ".join(summary["SKIP"]))
    lines.append("\n────────────\n*جزئیات:*\n")
    for name, result in results:
        lines.append(format_single(name, result))
        lines.append("")
    lines.append("_NFA | DYOR_")
    send_telegram_message(chat_id, "\n".join(lines))
    return Response(status_code=200)


@app.on_event("startup")
def set_webhook():
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN not set")
        return
    webhook_url = f"{WEBHOOK_BASE.rstrip('/')}/telegram-webhook"
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    try:
        # drop_pending_updates کمک می‌کند صف قدیمی تکرار نشود
        r = http_requests.post(
            api,
            json={"url": webhook_url, "drop_pending_updates": True},
            timeout=10,
        )
        logger.info(f"Webhook set: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
