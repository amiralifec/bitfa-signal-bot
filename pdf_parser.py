"""
استخراج تیکر + یادداشت تحلیلگر + درباره پروژه از PDF واچ‌لیست BITFA
نسخه سخت‌گیرانه‌تر: صرافی/سرمایه‌گذار را تیکر حساب نکن
"""

import re
from typing import List, Set, Dict, Any
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
    "NOV", "COM", "CPU", "GPU", "ETF", "AI", "HTTP", "HTTPS", "WWW",
    "THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT",
    "SK", "MH", "NAP", "NULL", "TRUE", "FALSE", "AMDUSDT", "PERP",
    "GRANITESHARES", "ADVANCED", "MICRO", "DEVICES",
    "OKX", "MEXC", "GATE", "LBANK", "KUCOIN", "BITGET", "TOOBIT",
    "BITUNIX", "XT", "BINGX", "BINANCE", "BYBIT", "BTCC", "ORBIT",
    "TOKCRYPTO", "TOKOCRYPTO", "COINBASE", "KRAKEN",
    "CMS", "HOLDINGS", "FRAMEWORK", "VENTURES", "GALAXY", "PANTERA",
    "DISTRIBUTED", "GLOBAL", "DEFIANCE", "IOSG", "SEVENX", "YZI",
    "LABS", "PREV", "BINANCE", "CAPITAL",
    "DLMM", "PMM", "TVL", "APR", "APY", "FDV", "ATH", "ATL",
    "SV", "TR", "MH", "SK", "NAP",
    "ریسک", "بالا", "متوسط", "کم", "درباره", "پروژه", "یادداشت", "تحلیلگر",
    "واچ", "لیست", "بیتفا", "آپدیت", "نمودار", "قیمت", "وبسایت",
    "صرافی", "سرمایه", "گذاران",
}

BULLISH_HINTS = re.compile(
    r"(شکست|صعود|مقاومت|پشت\s*سر|تثبیت|ساختار\s*صعود|روند\s*صعود|حمایت|ورود|پتانسیل|آماده|"
    r"بالای\s*این\s*سطح|هدف\s*(اولیه|قیمت)?|حفظ\s*کرده|رشد\s*داشته|محدوده\s*\d|"
    r"breakout|bullish|uptrend|support\s*hold)",
    re.IGNORECASE,
)
BEARISH_HINTS = re.compile(
    r"(ریزش|نزول|فشار\s*فروش|ساختار\s*نزولی|روند\s*نزولی|ضعیف|رد\s*شده|خطر|"
    r"احتیاط\s*بالا|خروج|stop\s*out|bearish|breakdown)",
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
        if len(t) < 2:
            continue
        if t not in seen:
            seen.add(t)
            hashed.append(t)

    if strict or hashed:
        return hashed[:15]

    extra: List[str] = []
    for m in re.finditer(r"\b([A-Z]{3,10})\b\s*(?:ریسک\s*(?:بالا|متوسط|کم))?", text):
        t = m.group(1).upper()
        if t in STOPWORDS or t in seen:
            continue
        seen.add(t)
        extra.append(t)

    return (hashed + extra)[:15]


def _clean_block(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s or "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _note_sentiment_boost(note: str) -> int:
    """وزن قوی‌تر برای یادداشت‌های ساختاری صعودی BITFA."""
    if not note:
        return 0
    bull = len(BULLISH_HINTS.findall(note))
    bear = len(BEARISH_HINTS.findall(note))
    score = bull * 3 - bear * 3
    if re.search(r"ساختار\s*صعود", note) and re.search(r"هدف", note):
        score += 3
    if re.search(r"حفظ\s*کرده|رشد\s*داشته", note):
        score += 2
    return max(-6, min(12, score))


def extract_entries_from_text(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []

    raw = text.replace("\r", "\n")
    entries: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    hash_hits = list(re.finditer(r"#\s*([A-Za-z][A-Za-z0-9]{1,14})", raw))

    if not hash_hits:
        hash_hits = list(
            re.finditer(
                r"\b([A-Z]{2,12})\b\s*(?:\n|\s)*(?:ریسک\s*(?:بالا|متوسط|کم))",
                raw,
            )
        )

    for i, m in enumerate(hash_hits):
        ticker = (m.group(1) or "").upper().strip()
        if not ticker or ticker in STOPWORDS or ticker in seen:
            continue
        if not re.match(r"^[A-Z][A-Z0-9]{1,14}$", ticker):
            continue
        if len(ticker) < 2:
            continue

        start = max(0, m.start() - 80)
        end = hash_hits[i + 1].start() if i + 1 < len(hash_hits) else min(len(raw), m.start() + 2800)
        block = raw[start:end]

        risk = None
        rm = re.search(r"ریسک\s*(بالا|متوسط|کم)", block)
        if rm:
            risk = rm.group(1)

        analyst_note = ""
        nm = re.search(
            r"یادداشت\s*تحلیلگر\s*[:\-]?\s*(.+?)(?=سرمایه‌گذاران|صرافی|وبسایت|نمودار\s*قیمت|درباره\s*پروژه|آپدیت\s*واچ|این\s*واچ‌لیست|$)",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if nm:
            analyst_note = _clean_block(nm.group(1))
            if len(analyst_note) > 600:
                analyst_note = analyst_note[:600].rsplit(" ", 1)[0] + "…"

        if not analyst_note:
            nm2 = re.search(
                rf"#\s*{re.escape(ticker)}\s*(.+?)(?=سرمایه‌گذاران|صرافی|وبسایت|نمودار|$)",
                block,
                re.DOTALL | re.IGNORECASE,
            )
            if nm2:
                candidate = _clean_block(nm2.group(1))
                if 25 < len(candidate) < 700 and "درباره" not in candidate[:25]:
                    analyst_note = candidate

        about = ""
        am = re.search(
            r"درباره\s*پروژه\s*[:\-]?\s*(.+?)(?=یادداشت\s*تحلیلگر|سرمایه‌گذاران|صرافی|وبسایت|نمودار|$)",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if am:
            about = _clean_block(am.group(1))[:350]

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


def parse_watchlist_pdf(data: bytes) -> Dict[str, Any]:
    text = extract_text_from_pdf_bytes(data)
    tickers = extract_tickers_from_text(text, strict=True)
    entries = extract_entries_from_text(text)
    notes_map: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        notes_map[e["ticker"]] = e
    for t in tickers:
        notes_map.setdefault(t, {"ticker": t, "analyst_note": "", "about": "", "note_boost": 0, "risk_label": None})
    return {
        "text_len": len(text or ""),
        "tickers": tickers or [e["ticker"] for e in entries],
        "entries": entries,
        "notes_map": notes_map,
    }
