"""
استخراج تیکر از PDF واچ‌لیست BITFA - نسخه تمیزتر
"""

import re
from typing import List, Set
from io import BytesIO

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

STOPWORDS = {
    "BITFA", "WATCHLIST", "NFA", "DYOR", "USDT", "USD", "BTC", "ETH",
    "LONG", "SHORT", "BUY", "SELL", "ENTRY", "EXIT", "STOP", "TARGET",
    "SUPPORT", "RESISTANCE", "BREAKOUT", "PULLBACK", "WATCH", "LIST",
    "SIGNAL", "FUTURES", "SPOT", "DEX", "CEX", "SOL", "BSC", "BASE",
    "UPDATE", "NOTE", "WARNING", "DISCLAIMER", "PDF", "HTML",
    "NOV", "OKX", "MEXC", "GATE", "LBANK", "KUCOIN", "BITGET", "TOOBIT",
    "BITUNIX", "XT", "COM", "CPU", "GPU", "ETF", "AI", "HTTP", "HTTPS",
    "WWW", "THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT",
    "SK", "MH", "NAP", "NULL", "TRUE", "FALSE", "AMDUSDT", "PERP",
    "GRANITESHARES", "ADVANCED", "MICRO", "DEVICES"
}


def extract_text_from_pdf_bytes(data: bytes) -> str:
    if not PdfReader:
        return ""
    try:
        reader = PdfReader(BytesIO(data))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    except Exception as e:
        print(f"PDF parse error: {e}")
        return ""


def extract_tickers_from_text(text: str, strict: bool = False) -> List[str]:
    """
    strict=True: فقط نمادهای با #
    strict=False: هشتگ‌ها اول، بعد نمادهای واضح
    """
    if not text:
        return []

    hashed: List[str] = []
    seen: Set[str] = set()

    for m in re.finditer(r"#\s*([A-Za-z][A-Za-z0-9]{1,14})|([A-Za-z][A-Za-z0-9]{1,14})\s*#", text):
        t = (m.group(1) or m.group(2) or "").upper().strip()
        if not t or t in STOPWORDS:
            continue
        if not re.match(r"^[A-Z][A-Z0-9]{1,14}$", t):
            continue
        if t not in seen:
            seen.add(t)
            hashed.append(t)

    if strict or hashed:
        return hashed[:20]

    # فقط اگر هشتگ نبود، سراغ نمادهای جدا
    extra: List[str] = []
    for m in re.finditer(r"\b([A-Z]{2,10})\b", text):
        t = m.group(1).upper()
        if t in STOPWORDS or t in seen:
            continue
        if len(t) < 2:
            continue
        seen.add(t)
        extra.append(t)

    return (hashed + extra)[:20]


def parse_watchlist_pdf(data: bytes) -> dict:
    text = extract_text_from_pdf_bytes(data)
    # در PDF اولویت با هشتگ
    tickers = extract_tickers_from_text(text, strict=False)
    return {
        "tickers": tickers,
        "text_preview": (text or "")[:500],
        "chars": len(text or ""),
    }
