"""
BITFA Signal Scorer - Version 0.3
طراحی‌شده بر اساس سبک واقعی کانال BITFA
الگوهای اصلی: شکست روند نزولی + پولبک | حمایت عمیق | شکست مقاومت افقی
"""

import requests
from typing import Dict, Any, Optional, List


def safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except:
        return default


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


def calculate_score(data: Dict, symbol: str = None) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    warnings: List[str] = []
    pattern_hints: List[str] = []

    pairs = data.get("pairs") or []
    if not pairs:
        return {
            "score": 0,
            "recommendation": "رد - داده کافی نیست",
            "risk_level": "نامشخص",
            "pattern": "نامشخص",
            "reasons": ["هیچ جفت معاملاتی پیدا نشد"],
            "warnings": [],
            "metrics": {}
        }

    pair = max(pairs, key=lambda p: safe_float(p.get("liquidity", {}).get("usd", 0)))

    liquidity = safe_float(pair.get("liquidity", {}).get("usd", 0))
    volume_24h = safe_float(pair.get("volume", {}).get("h24", 0))
    price_change_24h = safe_float(pair.get("priceChange", {}).get("h24", 0))
    price_change_1h = safe_float(pair.get("priceChange", {}).get("h1", 0))
    fdv = safe_float(pair.get("fdv", 0))
    market_cap = safe_float(pair.get("marketCap", 0)) or fdv
    txns = pair.get("txns", {}).get("h24", {})
    buys = safe_float(txns.get("buys", 0))
    sells = safe_float(txns.get("sells", 0))
    chain = pair.get("chainId", "unknown")
    dex = pair.get("dexId", "unknown")

    # 1. Liquidity (18)
    if liquidity >= 300000:
        score += 18
        reasons.append(f"لیکوئیدیتی عالی: ${liquidity:,.0f}")
    elif liquidity >= 80000:
        score += 14
        reasons.append(f"لیکوئیدیتی خوب: ${liquidity:,.0f}")
    elif liquidity >= 25000:
        score += 9
        reasons.append(f"لیکوئیدیتی متوسط: ${liquidity:,.0f}")
    elif liquidity >= 8000:
        score += 5
        reasons.append(f"لیکوئیدیتی کم: ${liquidity:,.0f}")
        warnings.append("لغزش احتمالی بالا")
    else:
        reasons.append(f"لیکوئیدیتی خیلی کم: ${liquidity:,.0f}")
        warnings.append("ریسک نقدشوندگی خطرناک")

    # 2. Volume (18)
    if volume_24h >= 800000:
        score += 18
        reasons.append(f"حجم ۲۴س بسیار بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 200000:
        score += 14
        reasons.append(f"حجم ۲۴س خوب: ${volume_24h:,.0f}")
    elif volume_24h >= 50000:
        score += 9
        reasons.append(f"حجم ۲۴س متوسط: ${volume_24h:,.0f}")
    elif volume_24h >= 15000:
        score += 5
        reasons.append(f"حجم ۲۴س کم: ${volume_24h:,.0f}")
    else:
        reasons.append(f"حجم پایین: ${volume_24h:,.0f}")

    if liquidity > 0 and volume_24h / liquidity > 2.5:
        score += 4
        reasons.append("نسبت حجم به لیکوئیدیتی قوی")

    # 3. Market Cap & Risk Profile (20)
    if 0 < market_cap < 3_000_000:
        score += 12
        reasons.append(f"مارکت‌کپ خیلی کم: ${market_cap:,.0f}")
        risk_base = "بالا"
        pattern_hints.append("پتانسیل انفجاری + ریسک بالا")
    elif 3_000_000 <= market_cap < 25_000_000:
        score += 18
        reasons.append(f"مارکت‌کپ مناسب: ${market_cap:,.0f}")
        risk_base = "متوسط تا بالا"
    elif 25_000_000 <= market_cap < 150_000_000:
        score += 14
        reasons.append(f"مارکت‌کپ متوسط: ${market_cap:,.0f}")
        risk_base = "متوسط"
    elif 150_000_000 <= market_cap < 800_000_000:
        score += 8
        reasons.append(f"مارکت‌کپ نسبتاً بالا: ${market_cap:,.0f}")
        risk_base = "کم تا متوسط"
    else:
        score += 3
        reasons.append(f"مارکت‌کپ بالا: ${market_cap:,.0f}")
        risk_base = "کم"
        warnings.append("پتانسیل رشد انفجاری محدودتر")

    # 4. Momentum (25) - aligned with BITFA style
    if 12 <= price_change_24h <= 70:
        score += 18
        reasons.append(f"رشد ۲۴س معقول: {price_change_24h:.1f}%")
        pattern_hints.append("مومنتوم مثبت")
    elif 70 < price_change_24h <= 150:
        score += 12
        reasons.append(f"رشد ۲۴س قوی: {price_change_24h:.1f}%")
        warnings.append("رشد زیاد → احتمال نیاز به پولبک")
    elif price_change_24h > 150:
        score += 5
        reasons.append(f"رشد بسیار زیاد: {price_change_24h:.1f}%")
        warnings.append("احتمال FOMO و اصلاح")
        pattern_hints.append("ورود دیرهنگام پرریسک")
    elif 0 <= price_change_24h < 12:
        score += 10
        reasons.append(f"نوسان ملایم: {price_change_24h:.1f}%")
    elif -20 <= price_change_24h < 0:
        score += 7
        reasons.append(f"اصلاح خفیف: {price_change_24h:.1f}% (ممکن است پولبک باشد)")
        pattern_hints.append("احتمال پولبک")
    else:
        score += 2
        reasons.append(f"ریزش: {price_change_24h:.1f}%")
        warnings.append("فشار فروش")

    if price_change_1h > 4:
        score += 5
        reasons.append(f"مومنتوم ۱س مثبت: {price_change_1h:.1f}%")
    elif price_change_1h < -6:
        score -= 4
        warnings.append(f"فشار فروش ۱س: {price_change_1h:.1f}%")

    # 5. Buy/Sell ratio (10)
    total_tx = buys + sells
    if total_tx > 10:
        buy_ratio = buys / total_tx
        if buy_ratio >= 0.60:
            score += 10
            reasons.append(f"غلبه خریداران: {buy_ratio*100:.0f}%")
        elif buy_ratio >= 0.52:
            score += 6
            reasons.append(f"تعادل متمایل به خرید")
        elif buy_ratio < 0.42:
            score -= 3
            warnings.append("غلبه فروشندگان")

    score = max(0, min(100, int(score)))

    pattern = " | ".join(pattern_hints[:2]) if pattern_hints else "نامشخص"

    if risk_base == "بالا" or liquidity < 15000 or market_cap < 2_000_000:
        risk_level = "بالا"
    elif risk_base in ["متوسط تا بالا", "متوسط"]:
        risk_level = "متوسط"
    else:
        risk_level = "کم تا متوسط"

    if score >= 78:
        recommendation = "امتیاز خوب - قابل بررسی برای ورود محدود با مدیریت ریسک"
        action = "بررسی برای ورود"
    elif score >= 62:
        recommendation = "امتیاز متوسط رو به بالا - صبر برای تأیید بیشتر (بدنه کندل / پولبک)"
        action = "نظارت + انتظار تأیید"
    elif score >= 45:
        recommendation = "امتیاز متوسط - فقط در صورت ساختار واضح"
        action = "نظارت"
    else:
        recommendation = "امتیاز ضعیف - بهتر است رد شود"
        action = "رد یا صبر"

    return {
        "score": score,
        "recommendation": recommendation,
        "action": action,
        "risk_level": risk_level,
        "pattern": pattern,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "liquidity_usd": round(liquidity),
            "volume_24h": round(volume_24h),
            "market_cap": round(market_cap),
            "price_change_24h": round(price_change_24h, 2),
            "price_change_1h": round(price_change_1h, 2),
            "buy_ratio": round(buys / total_tx, 2) if total_tx > 0 else None,
            "chain": chain,
            "dex": dex
        },
        "note": "نسخه ۰.۳ | بر اساس سبک BITFA | NFA | DYOR"
    }


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    data = get_dexscreener_data(token_address=address, symbol=symbol)
    if not data:
        return {"error": "داده پیدا نشد", "score": 0, "recommendation": "رد"}
    return calculate_score(data, symbol=symbol)
