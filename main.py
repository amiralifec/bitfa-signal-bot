"""
BITFA Scorer + Telegram Bot
نسخه ۰.۸ - استخراج خودکار تیکر از متن واچ‌لیست‌مانند کانال BITFA
"""

import os
import re
import logging
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import requests as http_requests

from scorer import analyze_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_BASE = os.getenv("RENDER_EXTERNAL_URL") or "https://bitfa-signal-bot.onrender.com"

app = FastAPI(title="BITFA Signal Scorer", version="0.8.0")

# کلمات رایج که تیکر نیستند
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
    """
    استخراج هوشمند از متن واچ‌لیست:
    - آدرس‌های قرارداد
    - هشتگ‌ها (#PEPE)
    - تیکرهای جدا با فاصله/کاما/خط جدید
    """
    items = []

    # ۱. آدرس‌های EVM و Solana-like
    for m in re.finditer(r"0x[a-fA-F0-9]{40}", text):
        items.append(m.group(0))
    for m in re.finditer(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", text):
        cand = m.group(0)
        if not cand.isdigit() and cand not in items:
            items.append(cand)

    # ۲. هشتگ‌ها (سبک اصلی کانال BITFA)
    for m in re.finditer(r"#([A-Za-z][A-Za-z0-9]{1,14})", text):
        t = m.group(1).upper()
        if t not in STOPWORDS and t not in [x.upper() for x in items]:
            items.append(t)

    # ۳. کلمات جدا که شبیه تیکر هستند (اگر هشتگ نبود)
    # فقط اگر متن کوتاه باشد یا ساختار لیستی داشته باشد
    if len(items) < 2:
        parts = re.split(r"[,\s\n/|]+", text)
        for part in parts:
            part = part.strip().lstrip("#").strip()
            if not part:
                continue
            # تیکر خالص حروف و عدد
            if re.match(r"^[A-Za-z][A-Za-z0-9]{1,11}$", part):
                t = part.upper()
                if t not in STOPWORDS and t not in [x.upper() for x in items]:
                    items.append(t)

    # حذف تکراری با حفظ ترتیب
    seen = set()
    unique = []
    for i in items:
        key = i.lower()
        if key not in seen:
            seen.add(key)
            unique.append(i)

    return unique[:15]  # حداکثر ۱۵ مورد


def format_single(name: str, result: dict) -> str:
    if result.get("error"):
        return f"*{name}* → خطا: {result.get('error')}"

    score = result.get("score", 0)
    category = result.get("category", "-")
    action = result.get("action", "-")
    risk = result.get("risk_level", "-")
    pos = result.get("position_suggestion", "-")
    cat_emoji = {"HOT": "🔥", "QUALIFIED": "✅", "WATCH": "👀", "SKIP": "❌"}.get(category, "▪️")

    return (
        f"{cat_emoji} *{name}* | {score}/100 | {category}\n"
        f"اقدام: {action} | ریسک: {risk}\n"
        f"حجم پیشنهادی: {pos}"
    )


def format_full(result: dict) -> str:
    if result.get("error"):
        return f"❌ خطا: {result.get('error')}"

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

    cat_emoji = {"HOT": "🔥", "QUALIFIED": "✅", "WATCH": "👀", "SKIP": "❌"}.get(category, "▪️")

    lines = [
        f"{cat_emoji} *نتیجه تحلیل*",
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
        for r in reasons[:5]:
            lines.append(f"• {r}")

    if warnings:
        lines.append("\n⚠️ *هشدارها:*")
        for w in warnings[:4]:
            lines.append(f"• {w}")

    if metrics:
        lines.append("\n📈 *متریک‌ها:*")
        if metrics.get("liquidity_usd") is not None:
            lines.append(f"• لیکوئیدیتی: ${metrics['liquidity_usd']:,.0f}")
        if metrics.get("volume_24h") is not None:
            lines.append(f"• حجم ۲۴س: ${metrics['volume_24h']:,.0f}")
        if metrics.get("market_cap") is not None:
            lines.append(f"• مارکت‌کپ: ${metrics['market_cap']:,.0f}")
        if metrics.get("price_change_24h") is not None:
            lines.append(f"• تغییر ۲۴س: {metrics['price_change_24h']}%")

    lines.append("\n_NFA | DYOR_")
    return "\n".join(lines)


def send_telegram_message(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if len(text) > 4000:
        text = text[:3900] + "\n\n... (خلاصه شده)"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        http_requests.post(url, json=payload, timeout=15)
    except Exception as e:
        logger.error(f"send message failed: {e}")


@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "0.8.0",
        "message": "BITFA Scorer - extract tickers from watchlist text",
        "bot": "enabled" if BOT_TOKEN else "disabled"
    }


@app.get("/health")
def health():
    return {"status": "healthy", "version": "0.8.0"}


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

    message = data.get("message") or data.get("edited_message")
    if not message:
        return Response(status_code=200)

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if not text:
        return Response(status_code=200)

    if text.startswith("/start"):
        send_telegram_message(
            chat_id,
            "سلام 👋\nربات امتیازدهی سبک BITFA\n\n"
            "می‌توانی بفرستی:\n"
            "• یک تیکر یا آدرس\n"
            "• چند تیکر با فاصله\n"
            "• کل متن واچ‌لیست کانال (با #TICKER)\n\n"
            "ربات خودش تیکرها را استخراج می‌کند."
        )
        return Response(status_code=200)

    if text.startswith("/help"):
        send_telegram_message(
            chat_id,
            "متن واچ‌لیست یا لیست تیکر را بفرست.\n"
            "هشتگ‌ها (#PEPE) و آدرس‌ها به صورت خودکار پیدا می‌شوند."
        )
        return Response(status_code=200)

    if text.startswith("/"):
        return Response(status_code=200)

    items = extract_tickers_and_addresses(text)
    if not items:
        send_telegram_message(
            chat_id,
            "تیکر یا آدرسی پیدا نشد.\n"
            "متن واچ‌لیست را با هشتگ بفرست یا تیکرها را جدا بنویس."
        )
        return Response(status_code=200)

    send_telegram_message(chat_id, f"{len(items)} مورد پیدا شد. در حال تحلیل... ⏳")

    results = []
    summary = {"HOT": [], "QUALIFIED": [], "WATCH": [], "SKIP": []}

    for item in items:
        try:
            if is_address(item):
                result = analyze_token(address=item)
                name = item[:6] + "..." + item[-4:] if len(item) > 12 else item
            else:
                result = analyze_token(symbol=item.upper())
                name = item.upper()

            results.append((name, result))
            cat = result.get("category", "SKIP")
            if cat in summary:
                summary[cat].append(f"{name} ({result.get('score', 0)})")
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
        r = http_requests.post(api, json={"url": webhook_url}, timeout=10)
        logger.info(f"Webhook set: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
