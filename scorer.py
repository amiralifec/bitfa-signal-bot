"""
BITFA Signal Scorer - Version 1.0.0
تگ سهام/پرپ + لایه Price Action سبک (الهام از stolgo / Al Brooks style)
"""

import os
import requests
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

COINGECKO_KEY = os.getenv("COINGECKO_API_KEY", "")
CG_BASE = "https://api.coingecko.com/api/v3"

# نمادهایی که در واچ‌لیست بیتفا بیشتر سهام/پرپ هستند تا آلت‌کوین
STOCK_LIKE = {
    "AMD", "SKDD", "HANMI", "ZHONGJI", "TSLA", "AAPL", "NVDA", "META", "GOOGL",
    "AMZN", "MSFT", "COIN", "MSTR", "HOOD", "PLTR", "NFLX", "BABA", "INTC"
}


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def cg_headers():
    h = {"accept": "application/json"}
    if COINGECKO_KEY:
        h["x-cg-demo-api-key"] = COINGECKO_KEY
    return h


def get_dexscreener_data(token_address: str = None, symbol: str = None) -> Optional[Dict]:
    try:
        if token_address:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        elif symbol:
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
        else:
            return None
        resp = requests.get(url, timeout=12)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"DexScreener error: {e}")
        return None


def coingecko_search(symbol: str) -> Optional[Dict]:
    try:
        r = requests.get(f"{CG_BASE}/search", params={"query": symbol}, headers=cg_headers(), timeout=12)
        if r.status_code != 200:
            return None
        coins = (r.json() or {}).get("coins") or []
        symbol_u = symbol.upper()
        exact = [c for c in coins if (c.get("symbol") or "").upper() == symbol_u]
        pool = exact if exact else coins
        if not pool:
            return None
        pool = sorted(pool, key=lambda c: c.get("market_cap_rank") or 999999)
        return pool[0]
    except Exception as e:
        print(f"CG search error: {e}")
        return None


def coingecko_market(coin_id: str) -> Optional[Dict]:
    try:
        r = requests.get(
            f"{CG_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": coin_id,
                "price_change_percentage": "1h,24h,7d"
            },
            headers=cg_headers(),
            timeout=12
        )
        if r.status_code != 200:
            return None
        arr = r.json() or []
        return arr[0] if arr else None
    except Exception as e:
        print(f"CG market error: {e}")
        return None


def pair_age_hours(pair: Dict) -> Optional[float]:
    created = pair.get("pairCreatedAt")
    if not created:
        return None
    try:
        if created > 1e12:
            created = created / 1000
        created_dt = datetime.fromtimestamp(created, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - created_dt).total_seconds() / 3600
    except Exception:
        return None


def select_best_pair(pairs: List[Dict], query_symbol: str = None) -> Optional[Dict]:
    if not pairs:
        return None
    candidates = pairs
    if query_symbol:
        q = query_symbol.strip().upper()
        exact = [p for p in pairs if ((p.get("baseToken") or {}).get("symbol") or "").upper() == q]
        if exact:
            candidates = exact
    scored = []
    for p in candidates:
        liq = safe_float((p.get("liquidity") or {}).get("usd", 0))
        vol = safe_float((p.get("volume") or {}).get("h24", 0))
        chg = (p.get("priceChange") or {}).get("h24")
        if liq < 1500 and vol < 300:
            continue
        pair_score = liq * 0.4 + vol * 0.6
        if chg is not None:
            pair_score *= 1.15
        if liq > 0 and vol / liq < 0.05 and vol < 15000:
            pair_score *= 0.5
        scored.append((pair_score, p))
    if not scored:
        return max(candidates, key=lambda p: safe_float((p.get("liquidity") or {}).get("usd", 0)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def format_price(price_usd: Optional[float]) -> Optional[str]:
    if price_usd is None:
        return None
    if price_usd >= 1:
        return f"${price_usd:,.4f}"
    if price_usd >= 0.01:
        return f"${price_usd:.6f}"
    return f"${price_usd:.8f}"


def detect_asset_kind(symbol: str, name: str, price_usd: Optional[float]) -> str:
    sym = (symbol or "").upper()
    name_l = (name or "").lower()
    if sym in STOCK_LIKE:
        return "stock_perp"
    if any(k in name_l for k in ["inc.", "corp", "semiconductor", "etf", "shares", "nasdaq", "equity"]):
        return "stock_perp"
    if price_usd is not None and price_usd >= 50 and sym in STOCK_LIKE:
        return "stock_perp"
    if price_usd is not None and price_usd >= 100 and len(sym) <= 5:
        if sym not in {"BTC", "ETH", "BNB", "SOL"}:
            return "stock_perp_candidate"
    return "crypto"


def calculate_price_action_score(
    *,
    price_change_24h: Optional[float],
    price_change_1h: Optional[float],
    volume_24h: float,
    liquidity: float,
    buys: float,
    sells: float,
) -> Tuple[int, List[str], List[str], List[str]]:
    """
    لایه سبک Price Action (الهام از مفاهیم stolgo / Al Brooks):
    - مومنتوم + تأیید حجم
    - غلبه خرید/فروش
    - تشخیص فشار یا شکست ساختار ساده
    امتیاز ۰ تا ۲۰ که به امتیاز اصلی اضافه می‌شود.
    """
    pa = 0
    tags: List[str] = []
    reasons: List[str] = []
    warnings: List[str] = []

    ch24 = price_change_24h
    ch1 = price_change_1h

    # نسبت حجم به لیکوئیدیتی (قدرت حرکت)
    vol_liq = (volume_24h / liquidity) if liquidity > 0 else 0.0

    # ۱) مومنتوم ۲۴ساعته با تأیید حجم
    if ch24 is not None:
        if 12 <= ch24 <= 45 and vol_liq >= 0.8:
            pa += 8
            tags.append("MomentumUp")
            reasons.append(f"PA: مومنتوم صعودی با حجم ({ch24:.1f}%)")
        elif 45 < ch24 <= 90 and vol_liq >= 1.2:
            pa += 6
            tags.append("StrongTrend")
            reasons.append(f"PA: روند قوی ۲۴س ({ch24:.1f}%)")
            warnings.append("رشد تند → احتمال پولبک")
        elif ch24 > 90:
            pa += 2
            tags.append("Parabolic")
            reasons.append(f"PA: حرکت پارابولیک ({ch24:.1f}%)")
            warnings.append("ریسک برگشت بالا")
        elif -8 <= ch24 < 0 and vol_liq >= 0.6:
            pa += 3
            tags.append("HealthyPullback")
            reasons.append(f"PA: پولبک سالم ({ch24:.1f}%)")
        elif ch24 < -20:
            pa -= 4
            tags.append("SellingPressure")
            warnings.append(f"PA: فشار فروش قوی ({ch24:.1f}%)")

    # ۲) مومنتوم کوتاه‌مدت ۱ساعته
    if ch1 is not None:
        if ch1 >= 4 and (ch24 is None or ch24 > 0):
            pa += 4
            tags.append("ShortMomentum")
            reasons.append(f"PA: مومنتوم ۱س مثبت ({ch1:.1f}%)")
        elif ch1 <= -5:
            pa -= 3
            tags.append("ShortWeakness")
            warnings.append(f"PA: ضعف ۱س ({ch1:.1f}%)")

    # ۳) ساختار خرید/فروش (order flow ساده)
    total_tx = buys + sells
    if total_tx >= 25:
        buy_ratio = buys / total_tx
        if buy_ratio >= 0.62:
            pa += 5
            tags.append("BuyerDominance")
            reasons.append(f"PA: غلبه خریداران ({buy_ratio*100:.0f}%)")
        elif buy_ratio <= 0.40:
            pa -= 3
            tags.append("SellerDominance")
            warnings.append(f"PA: غلبه فروشندگان ({(1-buy_ratio)*100:.0f}%)")

    # ۴) قدرت نسبی حجم (breakout-like)
    if vol_liq >= 2.0 and ch24 is not None and ch24 > 5:
        pa += 4
        tags.append("VolumeBreak")
        reasons.append("PA: شکست حجمی / فعالیت بالا")
    elif vol_liq < 0.15 and volume_24h > 0:
        pa -= 2
        tags.append("LowActivity")
        warnings.append("PA: فعالیت حجمی ضعیف")

    # نرمال‌سازی
    pa = max(0, min(20, int(pa)))
    # تگ‌های تکراری را حذف کن
    tags = list(dict.fromkeys(tags))
    return pa, tags, reasons, warnings


def calculate_score_from_metrics(
    *,
    liquidity: float,
    volume_24h: float,
    market_cap: float,
    price_change_24h: Optional[float],
    price_change_1h: Optional[float],
    buys: float,
    sells: float,
    age_h: Optional[float],
    has_rank: bool,
    rank: Optional[int],
) -> Tuple[int, List[str], List[str], str, int]:
    score = 0
    reasons = []
    warnings = []
    confidence = 40
    risk_base = "متوسط"

    if liquidity > 0:
        confidence += 12
    if volume_24h > 0:
        confidence += 10
    if market_cap > 0:
        confidence += 10
    if price_change_24h is not None:
        confidence += 8
    if has_rank:
        confidence += 12
    if age_h is not None:
        confidence += 8
    confidence = min(100, confidence)

    if liquidity >= 400000:
        score += 22
        reasons.append(f"لیکوئیدیتی عالی: ${liquidity:,.0f}")
    elif liquidity >= 150000:
        score += 17
        reasons.append(f"لیکوئیدیتی خوب: ${liquidity:,.0f}")
    elif liquidity >= 50000:
        score += 12
        reasons.append(f"لیکوئیدیتی قابل قبول: ${liquidity:,.0f}")
    elif liquidity >= 15000:
        score += 6
        reasons.append(f"لیکوئیدیتی متوسط: ${liquidity:,.0f}")
        warnings.append("لغزش متوسط ممکن است")
    elif liquidity >= 5000:
        score += 2
        reasons.append(f"لیکوئیدیتی کم: ${liquidity:,.0f}")
        warnings.append("لغزش بالا")
    elif liquidity > 0:
        reasons.append(f"لیکوئیدیتی خیلی کم: ${liquidity:,.0f}")
        warnings.append("ریسک نقدشوندگی")
        score -= 5
    else:
        reasons.append("لیکوئیدیتی دکس نامشخص (ممکن است بیشتر CEX باشد)")

    if volume_24h >= 800000:
        score += 16
        reasons.append(f"حجم بسیار بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 200000:
        score += 12
        reasons.append(f"حجم خوب: ${volume_24h:,.0f}")
    elif volume_24h >= 60000:
        score += 8
        reasons.append(f"حجم متوسط رو به بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 20000:
        score += 4
        reasons.append(f"حجم متوسط: ${volume_24h:,.0f}")
    elif volume_24h > 0:
        score += 1
        reasons.append(f"حجم کم: ${volume_24h:,.0f}")
    else:
        reasons.append("حجم دکس کم/نامشخص")

    if liquidity > 0 and volume_24h > 0:
        vol_liq = volume_24h / liquidity
        if vol_liq >= 2.0:
            score += 5
            reasons.append("نسبت حجم/لیکوئیدیتی قوی")
        elif vol_liq >= 0.7:
            score += 2
        elif vol_liq < 0.12:
            score -= 8
            warnings.append("حجم نسبت به لیکوئیدیتی ضعیف")

    if rank and rank <= 300:
        score += 14
        reasons.append(f"رتبه مارکت‌کپ خوب: #{rank}")
        risk_base = "کم تا متوسط"
    elif rank and rank <= 800:
        score += 11
        reasons.append(f"رتبه مارکت‌کپ متوسط: #{rank}")
        risk_base = "متوسط"
    elif rank and rank <= 2000:
        score += 8
        reasons.append(f"رتبه مارکت‌کپ: #{rank}")
        risk_base = "متوسط تا بالا"
    elif 0 < market_cap < 2_500_000:
        score += 10
        reasons.append(f"مارکت‌کپ خیلی کم: ${market_cap:,.0f}")
        risk_base = "بالا"
    elif 2_500_000 <= market_cap < 25_000_000:
        score += 15
        reasons.append(f"مارکت‌کپ مناسب (کم‌کپ): ${market_cap:,.0f}")
        risk_base = "متوسط تا بالا"
    elif 25_000_000 <= market_cap < 150_000_000:
        score += 12
        reasons.append(f"مارکت‌کپ متوسط: ${market_cap:,.0f}")
        risk_base = "متوسط"
    elif market_cap >= 150_000_000:
        score += 7
        reasons.append(f"مارکت‌کپ نسبتاً بالا: ${market_cap:,.0f}")
        risk_base = "کم تا متوسط"
    else:
        reasons.append("مارکت‌کپ نامشخص")

    if price_change_24h is None:
        reasons.append("تغییر ۲۴س نامشخص")
        score += 3
    elif 8 <= price_change_24h <= 55:
        score += 14
        reasons.append(f"رشد ۲۴س معقول: {price_change_24h:.1f}%")
    elif 55 < price_change_24h <= 120:
        score += 9
        reasons.append(f"رشد ۲۴س قوی: {price_change_24h:.1f}%")
        warnings.append("رشد زیاد → احتمال پولبک")
    elif price_change_24h > 120:
        score += 3
        reasons.append(f"رشد بسیار زیاد: {price_change_24h:.1f}%")
        warnings.append("احتمال FOMO")
    elif 0 <= price_change_24h < 8:
        score += 7
        reasons.append(f"نوسان ملایم: {price_change_24h:.1f}%")
    elif -15 <= price_change_24h < 0:
        score += 4
        reasons.append(f"اصلاح خفیف: {price_change_24h:.1f}%")
    else:
        reasons.append(f"ریزش: {price_change_24h:.1f}%")
        warnings.append("فشار فروش")

    if price_change_1h is not None:
        if price_change_1h > 3:
            score += 3
            reasons.append(f"مومنتوم ۱س مثبت: {price_change_1h:.1f}%")
        elif price_change_1h < -6:
            score -= 4
            warnings.append(f"فشار فروش ۱س: {price_change_1h:.1f}%")

    total_tx = buys + sells
    if total_tx > 20:
        buy_ratio = buys / total_tx
        if buy_ratio >= 0.58:
            score += 8
            reasons.append(f"غلبه خریداران: {buy_ratio*100:.0f}%")
        elif buy_ratio < 0.42:
            score -= 3
            warnings.append("غلبه فروشندگان")

    if age_h is not None:
        if age_h >= 24 * 30:
            score += 4
            reasons.append(f"جفت/بازار بالغ ({age_h/24:.0f} روز)")
        elif age_h < 4:
            score -= 3
            warnings.append(f"بسیار جدید ({age_h:.1f} ساعت)")

    score = max(0, min(100, int(score)))
    return score, reasons, warnings, risk_base, confidence


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    dex_data = get_dexscreener_data(token_address=address, symbol=symbol)
    pair = None
    if dex_data and dex_data.get("pairs"):
        pair = select_best_pair(dex_data.get("pairs") or [], query_symbol=symbol)

    liquidity = volume_24h = market_cap = buys = sells = 0.0
    price_change_24h = price_change_1h = price_usd = age_h = None
    chain = dex = base_sym = base_name = token_address = ""
    pair_url = None

    if pair:
        liquidity = safe_float((pair.get("liquidity") or {}).get("usd", 0))
        volume_24h = safe_float((pair.get("volume") or {}).get("h24", 0))
        raw24 = (pair.get("priceChange") or {}).get("h24")
        raw1 = (pair.get("priceChange") or {}).get("h1")
        price_change_24h = safe_float(raw24, None) if raw24 is not None else None
        price_change_1h = safe_float(raw1, None) if raw1 is not None else None
        price_usd = safe_float(pair.get("priceUsd"), None)
        fdv = safe_float(pair.get("fdv", 0))
        market_cap = safe_float(pair.get("marketCap", 0)) or fdv
        txns = (pair.get("txns") or {}).get("h24", {}) or {}
        buys = safe_float(txns.get("buys", 0))
        sells = safe_float(txns.get("sells", 0))
        chain = pair.get("chainId") or ""
        dex = pair.get("dexId") or ""
        base = pair.get("baseToken") or {}
        base_sym = (base.get("symbol") or symbol or "?").upper()
        base_name = base.get("name") or ""
        token_address = base.get("address") or address or ""
        age_h = pair_age_hours(pair)
        pair_addr = pair.get("pairAddress")
        if chain and pair_addr:
            pair_url = f"https://dexscreener.com/{chain}/{pair_addr}"

    cg_hit = None
    cg_mkt = None
    rank = None
    cg_url = None
    search_sym = (base_sym if base_sym and base_sym != "?" else symbol) or None
    if search_sym:
        cg_hit = coingecko_search(search_sym)
        if cg_hit:
            cg_mkt = coingecko_market(cg_hit.get("id"))
            if cg_mkt:
                rank = cg_mkt.get("market_cap_rank")
                if price_usd is None:
                    price_usd = safe_float(cg_mkt.get("current_price"), None)
                if market_cap <= 0:
                    market_cap = safe_float(cg_mkt.get("market_cap"), 0)
                if price_change_24h is None:
                    price_change_24h = safe_float(cg_mkt.get("price_change_percentage_24h"), None)
                if price_change_1h is None:
                    price_change_1h = safe_float(cg_mkt.get("price_change_percentage_1h_in_currency"), None)
                if not base_name:
                    base_name = cg_mkt.get("name") or cg_hit.get("name") or ""
                if not base_sym or base_sym == "?":
                    base_sym = (cg_mkt.get("symbol") or search_sym or "?").upper()
                cg_vol = safe_float(cg_mkt.get("total_volume"), 0)
                if cg_vol > volume_24h:
                    volume_24h = max(volume_24h, cg_vol * 0.15)
                cg_url = f"https://www.coingecko.com/en/coins/{cg_hit.get('id')}"

    if not pair and not cg_mkt:
        return {
            "error": "داده پیدا نشد (نه در دکس و نه در CoinGecko)",
            "score": 0,
            "category": "SKIP",
            "recommendation": "رد",
            "confidence": 0,
            "position_suggestion": "هیچ",
            "asset_kind": "unknown",
            "pa_score": 0,
            "pa_tags": [],
        }

    score, reasons, warnings, risk_base, confidence = calculate_score_from_metrics(
        liquidity=liquidity,
        volume_24h=volume_24h,
        market_cap=market_cap,
        price_change_24h=price_change_24h,
        price_change_1h=price_change_1h,
        buys=buys,
        sells=sells,
        age_h=age_h,
        has_rank=rank is not None,
        rank=rank,
    )

    # لایه Price Action
    pa_score, pa_tags, pa_reasons, pa_warnings = calculate_price_action_score(
        price_change_24h=price_change_24h,
        price_change_1h=price_change_1h,
        volume_24h=volume_24h,
        liquidity=liquidity,
        buys=buys,
        sells=sells,
    )
    # حداکثر ۲۰ امتیاز از PA به امتیاز اصلی اضافه می‌شود (با سقف ۱۰۰)
    score = max(0, min(100, score + pa_score))
    reasons = pa_reasons + reasons
    warnings = pa_warnings + warnings

    asset_kind = detect_asset_kind(base_sym or (symbol or ""), base_name, price_usd)
    if asset_kind.startswith("stock"):
        reasons.insert(0, "نوع دارایی: سهام/پرپ (نه آلت‌کوین معمولی)")
        warnings.append("این مورد را با توکن‌های کریپتو قاطی نکن")
    elif rank:
        reasons.insert(0, f"منبع بازار: CoinGecko + Dex" if pair else "منبع بازار: CoinGecko")
    elif pair:
        reasons.insert(0, "منبع بازار: عمدتاً DexScreener")

    if score >= 80 and confidence >= 70:
        category, recommendation, action = "HOT", "امتیاز عالی - قابل بررسی جدی برای ورود محدود", "اولویت بررسی"
    elif score >= 65:
        category, recommendation, action = "QUALIFIED", "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت", "بررسی برای ورود"
    elif score >= 48:
        category, recommendation, action = "WATCH", "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار", "نظارت"
    else:
        category, recommendation, action = "SKIP", "امتیاز ضعیف - رد شود", "رد"

    if risk_base == "بالا" or (liquidity > 0 and liquidity < 10000 and not rank):
        risk_level = "بالا"
    elif risk_base in ["متوسط تا بالا", "متوسط"]:
        risk_level = "متوسط"
    else:
        risk_level = "کم تا متوسط"

    if category == "SKIP" or score < 45:
        position_suggestion = "۰٪ از سرمایه (ورود نکن)"
    elif risk_level == "بالا":
        position_suggestion = "حداکثر ۱٪ تا ۱.۵٪ از کل سرمایه"
    elif risk_level == "متوسط":
        position_suggestion = "حداکثر ۲٪ تا ۳٪ از کل سرمایه"
    else:
        position_suggestion = "حداکثر ۳٪ تا ۴٪ از کل سرمایه"

    return {
        "score": score,
        "category": category,
        "recommendation": recommendation,
        "action": action,
        "risk_level": risk_level,
        "confidence": confidence,
        "position_suggestion": position_suggestion,
        "token": base_sym or (symbol or "?").upper(),
        "token_name": base_name,
        "token_address": token_address or address or "",
        "price_usd": price_usd,
        "price_str": format_price(price_usd),
        "rank": rank,
        "asset_kind": asset_kind,
        "pa_score": pa_score,
        "pa_tags": pa_tags,
        "links": {
            "dexscreener": pair_url,
            "coingecko": cg_url,
        },
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "liquidity_usd": round(liquidity) if liquidity else 0,
            "volume_24h": round(volume_24h) if volume_24h else 0,
            "market_cap": round(market_cap) if market_cap else 0,
            "price_change_24h": round(price_change_24h, 2) if price_change_24h is not None else None,
            "price_change_1h": round(price_change_1h, 2) if price_change_1h is not None else None,
            "chain": chain or None,
            "dex": dex or None,
        },
        "note": "نسخه ۱.۰.۰ | Dex + CoinGecko + PA لایه سبک | NFA | DYOR"
    }
