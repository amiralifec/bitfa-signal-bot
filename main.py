"""
FastAPI + Telegram Bot
ربات در پس‌زمینه اجرا می‌شود و سرویس وب هم برای health check فعال است
"""

import os
import asyncio
import threading
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn

from scorer import analyze_token

app = FastAPI(
    title="BITFA Signal Scorer",
    description="امتیازدهی ارزهای BITFA + ربات تلگرام",
    version="0.6.1"
)

class AnalyzeRequest(BaseModel):
    symbol: Optional[str] = None
    address: Optional[str] = None

@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "0.6.1",
        "message": "BITFA Signal Scorer + Telegram Bot is running",
        "categories": ["HOT", "QUALIFIED", "WATCH", "SKIP"],
        "usage": "POST /analyze or send symbol/address to the Telegram bot"
    }

@app.get("/health")
def health():
    return {"status": "healthy", "version": "0.6.1"}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.symbol and not req.address:
        return {"error": "symbol یا address الزامی است", "score": 0}
    return analyze_token(symbol=req.symbol, address=req.address)


def run_telegram_bot():
    """اجرای ربات در ترد جدا"""
    try:
        from bot import build_app
        bot_app = build_app()
        print("Telegram bot starting...")
        bot_app.run_polling(drop_pending_updates=True, close_loop=False)
    except Exception as e:
        print(f"Telegram bot error: {e}")


@app.on_event("startup")
def startup_event():
    # ربات را در ترد پس‌زمینه اجرا کن
    if os.getenv("BOT_TOKEN"):
        t = threading.Thread(target=run_telegram_bot, daemon=True)
        t.start()
        print("Telegram bot thread started")
    else:
        print("BOT_TOKEN not set - bot disabled")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
