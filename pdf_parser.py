"""
استخراج تیکر + یادداشت تحلیلگر + درباره پروژه از PDF واچ‌لیست BITFA
"""

import re
from typing import List, Set, Dict, Any, Optional
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
    "GRANITESHARES", "ADVANCED", "MICRO", "DEVICES", "DODO",
    "ریسک", "بالا", "متوسط", "کم", "درباره", "پروژه", "یادداشت", "تحلیلگر",
}

# کلمات مثبت/منفی برای امتیازدهی سبک از روی یادداشت
BULLISH_HINTS = re.compile(
    r"(شکست|صعود|مقاومت|پشت\s*سر|تثبیت|ساختار\s*صعود|روند\s*صعود|حمایت|ورود|پتانسیل|آماده|بالای\s*این\s*سطح)",
    re.IGNORECASE,
)
BEARISH_HINTS = re.compile(
    r"(ریزش|نزول|فشار\s*فروش|ساختار\s*نزولی|روند\s*نزولی|ضعیف|رد\s*شده|خطر)",
    re.IGNORECASE,
)


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


def _clean_block(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s or "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _note_sentiment_boost(note: str) -> int:
    """امتیاز کوچک از روی لحن یادداشت تحلیلگر (−5 تا +8)."""
    if not note:
        return 0
    bull = len(BULLISH_HINTS.findall(note))
    bear = len(BEARISH_HINTS.findall(note))
    score = bull * 2 - bear * 2
    return max(-5, min(8, score))


def extract_entries_from_text(text: str) -> List[Dict[str, Any]]:
    """
    هر صفحه/بخش معمولاً یک نماد دارد با:
    - عنوان نماد / ریسک
    - درباره پروژه
    - یادداشت تحلیلگر
    """
    if not text:
        return []

    # نرمال‌سازی فاصله‌ها برای regex بهتر
    raw = text.replace("\r", "\n")
    entries: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    # الگوهای هدر نماد: DODO / #DODO / نماد در کنار «ریسک»
    # بخش‌ها را با جداکننده‌های رایج BITFA می‌شکنیم
    chunks = re.split(
        r"(?=(?:یادداشت\s*تحلیلگر|درباره\s*پروژه|واچ\s*لیست\s*بیتفا|NOV\s*\d{4}))",
        raw,
        flags=re.IGNORECASE,
    )

    # روش مکمل: پیدا کردن همه #TICKER و برش متن اطراف
    hash_hits = list(re.finditer(r"#\s*([A-Za-z][A-Za-z0-9]{1,14})", raw))
    if not hash_hits:
        # بعضی PDFها بدون # فقط نام بزرگ می‌نویسند
        hash_hits = list(re.finditer(r"\b([A-Z]{2,12})\b\s*(?:ریسک\s*(?:بالا|متوسط|کم))?", raw))

    for i, m in enumerate(hash_hits):
        ticker = (m.group(1) or "").upper().strip()
        if not ticker or ticker in STOPWORDS or ticker in seen:
            continue
        if not re.match(r"^[A-Z][A-Z0-9]{1,14}$", ticker):
            continue

        start = m.start()
        end = hash_hits[i + 1].start() if i + 1 < len(hash_hits) else min(len(raw), start + 2500)
        block = raw[start:end]

        # ریسک
        risk = None
        rm = re.search(r"ریسک\s*(بالا|متوسط|کم)", block)
        if rm:
            risk = rm.group(1)

        # یادداشت تحلیلگر
        analyst_note = ""
        nm = re.search(
            r"یادداشت\s*تحلیلگر\s*[:\-]?\s*(.+?)(?=سرمایه‌گذاران|صرافی|وبسایت|نمودار|درباره\s*پروژه|آپدیت|$)",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if nm:
            analyst_note = _clean_block(nm.group(1))
            # کوتاه کردن
            if len(analyst_note) > 600:
                analyst_note = analyst_note[:600].rsplit(" ", 1)[0] + "…"

        # اگر الگوی بالا چیزی نداد، دنبال جمله بعد از هشتگ نماد در یادداشت
        if not analyst_note:
            nm2 = re.search(
                rf"#\s*{re.escape(ticker)}\s*(.+?)(?=سرمایه‌گذاران|صرافی|وبسایت|نمودار|$)",
                block,
                re.DOTALL | re.IGNORECASE,
            )
            if nm2:
                candidate = _clean_block(nm2.group(1))
                if 30 < len(candidate) < 700 and "درباره" not in candidate[:20]:
                    analyst_note = candidate

        # درباره پروژه
        about = ""
        am = re.search(
            r"درباره\s*پروژه\s*[:\-]?\s*(.+?)(?=یادداشت\s*تحلیلگر|سرمایه‌گذاران|صرافی|وبسایت|$)",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if am:
            about = _clean_block(am.group(1))
            if len(about) > 500:
                about = about[:500].rsplit(" ", 1)[0] + "…"

        boost = _note_sentiment_boost(analyst_note)

        seen.add(ticker)
        entries.append({
            "ticker": ticker,
            "risk_label": risk,
            "analyst_note": analyst_note,
            "about": about,
            "note_boost": boost,
        })

    return entries[:20]


def parse_watchlist_pdf(data: bytes) -> dict:
    text = extract_text_from_pdf_bytes(data)
    entries = extract_entries_from_text(text)
    tickers = [e["ticker"] for e in entries] if entries else extract_tickers_from_text(text, strict=False)

    # دیکشنری سریع برای lookup
    notes_map: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        notes_map[e["ticker"]] = e

    return {
        "tickers": tickers,
        "entries": entries,
        "notes_map": notes_map,
        "text_preview": (text or "")[:800],
        "chars": len(text or ""),
    }
