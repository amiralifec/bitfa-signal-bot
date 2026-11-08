"""
ماژول امتیازدهی ارزهای BITFA
نسخه ۰.۱ - اولیه
"""

import requests
from typing import Dict, Any, Optional


def get_dexscreener_data(token_address: str = None, symbol: str = None) -> Optional[Dict]:
    """گرفتن داده از DexScreener (رایگان و بدون کلید)"""
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


def calculate_score(data: Dict) -> Dict[str, Any]:
    """
    محاسبه امتیاز از ۱۰۰
    این نسخه خیلی ساده است و فقط اسکلت کار می‌کند.
    فیلترهای واقعی در نسخه‌های بعدی اضافه می‌شوند.
    """
    score = 40
    reasons = ["نسخه اولیه - فیلترها هنوز کامل نیست"]

    pairs = data.get("pairs") or []
    if pairs:
        pair = pairs[0]
        liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
        volume_24h = pair.get("volume", {}).get("h24", 0) or 0

        if liquidity > 50000:
            score += 15
            reasons.append(f"لیکوئیدیتی مناسب: ${liquidity:,.0f}")
        elif liquidity > 10000:
            score += 8
            reasons.append(f"لیکوئیدیتی متوسط: ${liquidity:,.0f}")
        else:
            reasons.append(f"لیکوئیدیتی پایین: ${liquidity:,.0f}")

        if volume_24h > 100000:
            score += 15
            reasons.append(f"حجم ۲۴س خوب: ${volume_24h:,.0f}")
        elif volume_24h > 20000:
            score += 8
            reasons.append(f"حجم ۲۴س متوسط: ${volume_24h:,.0f}")

        price_change = pair.get("priceChange", {}).get("h24", 0) or 0
        if 5 < price_change < 80:
            score += 10
            reasons.append(f"تغییر قیمت ۲۴س معقول: {price_change:.1f}%")

    score = max(0, min(100, score))

    recommendation = "صبر کنید تا فیلترها کامل شود"
    if score >= 70:
        recommendation = "امتیاز نسبتاً خوب (نسخه اولیه)"
    elif score >= 50:
        recommendation = "متوسط"
    else:
        recommendation = "ضعیف یا داده ناکافی"

    return {
        "score": score,
        "reasons": reasons,
        "recommendation": recommendation,
        "note": "این نسخه آزمایشی است و توصیه مالی نیست"
    }


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    data = get_dexscreener_data(token_address=address, symbol=symbol)
    if not data:
        return {"error": "داده از DexScreener پیدا نشد", "score": 0}

    return calculate_score(data)
