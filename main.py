"""
BITFA Scorer + Telegram Bot (Webhook mode - مناسب Render)
"""

import os
import re
import logging
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from typing import Optional
import uvicorn

from scorer import analyze_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_BASE = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE") or "https://bitfa-signal-bot.onrender.com"

app = FastAPI(title="BITFA Signal Scorer", version="0.6.2")


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


def format_result(result: dict) -> str:
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
        f"",
        f"📊 *امتیاز:* {score}/100",
        f"🏷 *دسته:* {category}",
        f"⚡ *اقدام:* {action}",
        f"⚠️ *ریسک:* {risk}",
        f"🎯 *اعتماد:* {conf}%",
        f"💰 *پیشنهاد حجم:* {pos}",
        f"",
        f"📝 *توصیه:*\n{rec}",
    ]

    if reasons:
        lines.append("\n✅ *نکات:*")
        for r in reasons[:6]:
            lines.append(f"• {r}")

    if warnings:
        lines.append("\n⚠️ *هشدارها:*")
        for w in warnings[:5]:
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
        if metrics.get("chain"):
            lines.append(f"• زنجیره: {metrics['chain']}")

    lines.append("\n_NFA | DYOR | فقط آموزشی_")
    return "\n".join(lines)


def send_telegram_message(chat_id: int, text: str):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send message: {e}")


@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "0.6.2",
        "message": "BITFA Scorer + Telegram Webhook",
        "bot": "enabled" if BOT_TOKEN else "disabled"
    }


@app.get("/health")
def health():
    return {"status": "healthy", "version": "0.6.2"}


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
            "سلام 👋\nمن ربات امتیازدهی سبک BITFA هستم.\n\n"
            "تیکر یا آدرس قرارداد را بفرست.\n"
            "مثال: `PEPE` یا `0x...`"
        )
        return Response(status_code=200)

    if text.startswith("/help"):
        send_telegram_message(chat_id, "فقط تیکر یا آدرس قرارداد را بفرست.")
        return Response(status_code=200)

    if text.startswith("/"):
        return Response(status_code=200)

    # در حال تحلیل
    send_telegram_message(chat_id, "در حال تحلیل... ⏳")

    try:
        if is_address(text):
            result = analyze_token(address=text)
        else:
            symbol = text.replace("#", "").upper()
            result = analyze_token(symbol=symbol)

        reply = format_result(result)
        send_telegram_message(chat_id, reply)
    except Exception as e:
        logger.exception("analyze error")
        send_telegram_message(chat_id, f"خطا در تحلیل: {str(e)[:150]}")

    return Response(status_code=200)


@app.on_event("startup")
def set_webhook():
    """ست کردن وب‌هوک موقع استارت"""
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN not set")
        return
    import requests
    webhook_url = f"{WEBHOOK_BASE.rstrip('/')}/telegram-webhook"
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    try:
        r = requests.post(api, json={"url": webhook_url}, timeout=10)
        logger.info(f"Webhook set result: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
