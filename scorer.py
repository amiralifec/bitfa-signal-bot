"""
BITFA Signal Scorer - Version 0.2
فیلترها بر اساس سبک واقعی کانال BITFA (واچ‌لیست‌های کم تا متوسط کپ با مومنتوم)
"""

import requests
from typing import Dict, Any, Optional, List
import time


def get_dexscreener_data(token_address: str = None, symbol: str = None) -> Optional[Dict]:
    """گرفتن داده از DexScreener (رایگان)"""
    try:
        if token_address:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        elif symbol:
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
        else:
            return None

        resp = requests.get(url, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            return data
        return None
    except Exception as e:
        print(f"DexScreener error: {e}")
        return None


def safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except:
        return default


def calculate_score(data: Dict, symbol: str = None) -> Dict[str, Any]:
    """
    امتیازدهی از ۰ تا ۱۰۰
    وزن‌ها بر اساس مشاهدات کانال BITFA تنظیم شده‌اند.
    """
    score = 0
    reasons: List[str] = []
    warnings: List[str] = []

    pairs = data.get("pairs") or []
    if not pairs:
        return {
            "score": 0,
            "reasons": ["هیچ جفت معاملاتی پیدا نشد"],
            "recommendation": "رد",
            "warnings": ["داده کافی نیست"]
        }

    # بهترین جفت را انتخاب می‌کنیم (بالاترین لیکوئیدیتی)
    pair = max(pairs, key=lambda p: safe_float(p.get("liquidity", {}).get("usd", 0)))

    liquidity = safe_float(pair.get("liquidity", {}).get("usd", 0))
    volume_24h = safe_float(pair.get("volume", {}).get("h24", 0))
    volume_6h = safe_float(pair.get("volume", {}).get("h6", 0))
    price_change_24h = safe_float(pair.get("priceChange", {}).get("h24", 0))
    price_change_6h = safe_float(pair.get("priceChange", {}).get("h6", 0))
    price_change_1h = safe_float(pair.get("priceChange", {}).get("h1", 0))
    fdv = safe_float(pair.get("fdv", 0))
    market_cap = safe_float(pair.get("marketCap", 0)) or fdv
    txns_24h = pair.get("txns", {}).get("h24", {})
    buys_24h = safe_float(txns_24h.get("buys", 0))
    sells_24h = safe_float(txns_24h.get("sells", 0))

    chain = pair.get("chainId", "unknown")
    dex = pair.get("dexId", "unknown")
    pair_address = pair.get("pairAddress", "")

    # ========== فیلتر ۱: لیکوئیدیتی (وزن ۲۵) ==========
    if liquidity >= 200000:
        score += 25
        reasons.append(f"لیکوئیدیتی عالی: ${liquidity:,.0f}")
    elif liquidity >= 50000:
        score += 18
        reasons.append(f"لیکوئیدیتی خوب: ${liquidity:,.0f}")
    elif liquidity >= 15000:
        score += 10
        reasons.append(f"لیکوئیدیتی متوسط: ${liquidity:,.0f}")
    elif liquidity >= 5000:
        score += 5
        reasons.append(f"لیکوئیدیتی کم: ${liquidity:,.0f}")
        warnings.append("لیکوئیدیتی پایین → ریسک لغزش بالا")
    else:
        reasons.append(f"لیکوئیدیتی خیلی کم: ${liquidity:,.0f}")
        warnings.append("لیکوئیدیتی خطرناک")

    # ========== فیلتر ۲: حجم معاملات (وزن ۲۵) ==========
    if volume_24h >= 500000:
        score += 25
        reasons.append(f"حجم ۲۴س عالی: ${volume_24h:,.0f}")
    elif volume_24h >= 100000:
        score += 18
        reasons.append(f"حجم ۲۴س خوب: ${volume_24h:,.0f}")
    elif volume_24h >= 30000:
        score += 10
        reasons.append(f"حجم ۲۴س متوسط: ${volume_24h:,.0f}")
    elif volume_24h >= 10000:
        score += 5
        reasons.append(f"حجم ۲۴س کم: ${volume_24h:,.0f}")
    else:
        reasons.append(f"حجم ۲۴س خیلی کم: ${volume_24h:,.0f}")

    # نسبت حجم به لیکوئیدیتی
    if liquidity > 0:
        vol_liq_ratio = volume_24h / liquidity
        if vol_liq_ratio > 3:
            score += 5
            reasons.append("نسبت حجم/لیکوئیدیتی بالا (فعالیت خوب)")
        elif vol_liq_ratio < 0.3 and volume_24h > 0:
            warnings.append("حجم نسبت به لیکوئیدیتی پایین است")

    # ========== فیلتر ۳: مارکت‌کپ / FDV (وزن ۲۰) ==========
    # سبک BITFA بیشتر روی کم تا متوسط کپ تمرکز دارد
    if 0 < market_cap < 5_000_000:
        score += 20
        reasons.append(f"مارکت‌کپ مناسب (کم‌کپ): ${market_cap:,.0f}")
    elif 5_000_000 <= market_cap < 30_000_000:
        score += 15
        reasons.append(f"مارکت‌کپ متوسط: ${market_cap:,.0f}")
    elif 30_000_000 <= market_cap < 150_000_000:
        score += 8
        reasons.append(f"مارکت‌کپ نسبتاً بالا: ${market_cap:,.0f}")
    elif market_cap >= 150_000_000:
        score += 3
        reasons.append(f"مارکت‌کپ بالا: ${market_cap:,.0f}")
        warnings.append("کپ بالا → پتانسیل رشد انفجاری کمتر")
    else:
        reasons.append("مارکت‌کپ نامشخص")

    # ========== فیلتر ۴: مومنتوم قیمت (وزن ۲۰) ==========
    # ترجیح می‌دهیم رشد معقول داشته باشد، نه پامپ دیوانه‌وار که تازه ترکیده
    if 8 <= price_change_24h <= 60:
        score += 15
        reasons.append(f"رشد ۲۴س معقول: {price_change_24h:.1f}%")
    elif 60 < price_change_24h <= 120:
        score += 10
        reasons.append(f"رشد ۲۴س قوی: {price_change_24h:.1f}%")
        warnings.append("رشد زیاد → احتمال اصلاح")
    elif price_change_24h > 120:
        score += 4
        reasons.append(f"رشد خیلی زیاد: {price_change_24h:.1f}%")
        warnings.append("احتمال بالای اصلاح یا پامپ تمام‌شده")
    elif -15 <= price_change_24h < 8:
        score += 8
        reasons.append(f"نوسان ملایم ۲۴س: {price_change_24h:.1f}%")
    else:
        reasons.append(f"ریزش یا رکود ۲۴س: {price_change_24h:.1f}%")

    # مومنتوم کوتاه‌مدت
    if price_change_1h > 5:
        score += 5
        reasons.append(f"مومنتوم ۱ ساعته مثبت: {price_change_1h:.1f}%")
    elif price_change_1h < -8:
        score -= 5
        warnings.append(f"فشار فروش ۱ ساعته: {price_change_1h:.1f}%")

    # ========== فیلتر ۵: فعالیت خرید/فروش (وزن ۱۰) ==========
    total_txns = buys_24h + sells_24h
    if total_txns > 0:
        buy_ratio = buys_24h / total_txns
        if buy_ratio >= 0.58:
            score += 10
            reasons.append(f"غلبه خریداران: {buy_ratio*100:.0f}%")
        elif buy_ratio >= 0.48:
            score += 5
            reasons.append(f"تعادل نسبی خرید/فروش")
        else:
            reasons.append(f"غلبه فروشندگان: {(1-buy_ratio)*100:.0f}%")
            warnings.append("فشار فروش بیشتر از خرید")

    # محدود کردن امتیاز
    score = max(0, min(100, int(score)))

    # ========== پیشنهاد ==========
    if score >= 75:
        recommendation = "امتیاز خوب - قابل بررسی برای ورود محدود"
        risk_level = "متوسط"
    elif score >= 55:
        recommendation = "امتیاز متوسط - فقط با مدیریت ریسک سخت"
        risk_level = "بالا"
    elif score >= 35:
        recommendation = "امتیاز ضعیف - بهتر است رد شود"
        risk_level = "خیلی بالا"
    else:
        recommendation = "رد - شرایط مناسب نیست"
        risk_level = "خطرناک"

    return {
        "score": score,
        "recommendation": recommendation,
        "risk_level": risk_level,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "liquidity_usd": round(liquidity),
            "volume_24h": round(volume_24h),
            "market_cap": round(market_cap),
            "price_change_24h": round(price_change_24h, 2),
            "price_change_1h": round(price_change_1h, 2),
            "chain": chain,
            "dex": dex
        },
        "note": "نسخه ۰.۲ - آزمایشی | توصیه مالی نیست (NFA | DYOR)"
    }


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    data = get_dexscreener_data(token_address=address, symbol=symbol)
    if not data:
        return {
            "error": "داده از DexScreener پیدا نشد",
            "score": 0,
            "recommendation": "رد"
        }

    # اگر چند نتیجه آمد، بهترین را انتخاب می‌کنیم
    return calculate_score(data, symbol=symbol)
