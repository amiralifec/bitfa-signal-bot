"""
استخراج تیکر از PDF واچ‌لیست BITFA
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
    "NOV", "OKX", "MEXC", "GATE", "LBank", "KuCoin", "Bitget", "Toobit",
    "Bitunix", "XT", "COM", "CPU", "GPU", "ETF", "AI", "HTTP", "HTTPS"
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


def extract_tickers_from_text(text: str) -> List[str]:
    if not text:
        return []

    found: List[str] = []
    seen: Set[str] = set()

    # الگوهای رایج در PDF بیتفا: #AMD  یا  AMD#  یا نماد داخل باکس
    patterns = [
        r"#\s*([A-Za-z][A-Za-z0-9]{1,14})",
        r"([A-Za-z][A-Za-z0-9]{1,14})\s*#",
        r"\b([A-Z]{2,12})\b",
    ]

    for pat in patterns:
        for m in re.finditer(pat, text):
            t = m.group(1).upper().strip()
            if not t or t in STOPWORDS:
                continue
            if len(t) < 2 or len(t) > 15:
                continue
            # فیلتر کلمات فارسی‌مانند / اعداد خالص
            if not re.match(r"^[A-Z][A-Z0-9]*$", t):
                continue
            if t not in seen:
                seen.add(t)
                found.append(t)

    # اولویت به مواردی که با # آمده‌اند
    hashed = []
    for m in re.finditer(r"#\s*([A-Za-z][A-Za-z0-9]{1,14})|([A-Za-z][A-Za-z0-9]{1,14})\s*#", text):
        t = (m.group(1) or m.group(2) or "").upper()
        if t and t not in STOPWORDS and t not in hashed:
            hashed.append(t)

    if hashed:
        # ابتدا هشتگ‌دارها، بعد بقیه
        rest = [t for t in found if t not in hashed]
        return (hashed + rest)[:20]

    return found[:20]


def parse_watchlist_pdf(data: bytes) -> dict:
    text = extract_text_from_pdf_bytes(data)
    tickers = extract_tickers_from_text(text)
    return {
        "tickers": tickers,
        "text_preview": (text or "")[:500],
        "chars": len(text or ""),
    }
