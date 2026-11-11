"""
ربات تلگرام BITFA Scorer
کاربر تیکر یا آدرس می‌فرستد و امتیاز دریافت می‌کند
"""

import os
import re
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from scorer import analyze_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")


def is_address(text: str) -> bool:
    text = text.strip()
    # EVM
    if re.match(r"^0x[a-fA-F0-9]{40}$", text):
        return True
    # Solana-like (base58, 32-44 chars)
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

    # ایموجی دسته
    cat_emoji = {
        "HOT": "🔥",
        "QUALIFIED": "✅",
        "WATCH": "👀",
        "SKIP": "❌"
    }.get(category, "▪️")

    lines = [
        f"{cat_emoji} <b>نتیجه تحلیل</b>",
        f"",
        f"📊 <b>امتیاز:</b> {score}/100",
        f"🏷 <b>دسته:</b> {category}",
        f"⚡ <b>اقدام:</b> {action}",
        f"⚠️ <b>ریسک:</b> {risk}",
        f"🎯 <b>اعتماد:</b> {conf}%",
        f"💰 <b>پیشنهاد حجم:</b> {pos}",
        f"",
        f"📝 <b>توصیه:</b>\n{rec}",
    ]

    if reasons:
        lines.append("\n✅ <b>نکات مثبت / مشاهدات:</b>")
        for r in reasons[:6]:
            lines.append(f"• {r}")

    if warnings:
        lines.append("\n⚠️ <b>هشدارها:</b>")
        for w in warnings[:5]:
            lines.append(f"• {w}")

    if metrics:
        lines.append("\n📈 <b>متریک‌ها:</b>")
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

    lines.append("\n<i>NFA | DYOR | فقط جنبه آموزشی</i>")
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "سلام 👋\n"
        "من ربات امتیازدهی ارزهای سبک BITFA هستم.\n\n"
        "فقط یکی از این‌ها را بفرست:\n"
        "• تیکر ارز (مثال: <code>BTC</code> یا <code>PEPE</code>)\n"
        "• آدرس قرارداد (۰x... یا آدرس سولانا)\n\n"
        "دستورات:\n"
        "/start - شروع\n"
        "/help - راهنما"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "کافی است تیکر یا آدرس قرارداد را بفرستی.\n"
        "مثال:\n<code>0x55ad16bd573b3365f43a9daeb0cc66a73821b4a5</code>\n"
        "یا\n<code>PEPE</code>",
        parse_mode="HTML"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # نادیده گرفتن دستورات
    if text.startswith("/"):
        return

    await update.message.reply_text("در حال تحلیل... ⏳")

    try:
        if is_address(text):
            result = analyze_token(address=text)
        else:
            # فرض می‌کنیم تیکر است
            symbol = text.replace("#", "").upper()
            result = analyze_token(symbol=symbol)

        reply = format_result(result)
        await update.message.reply_text(reply, parse_mode="HTML")
    except Exception as e:
        logger.exception("Error analyzing")
        await update.message.reply_text(f"خطا در تحلیل: {str(e)[:200]}")


def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
