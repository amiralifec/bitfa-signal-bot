"""
BITFA Signal Scorer - Version 0.4
ترکیب سبک واقعی BITFA + ایده‌های پروژه‌های متن‌باز موفق (buzz-token-scanner و فیلترهای DexScreener)
"""

import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone


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


def pair_age_hours(pair: Dict) -> Optional[float]:
    """محاسبه سن تقریبی جفت به ساعت"""
    created = pair.get("pairCreatedAt")
    if not created:
        return None
    try:
        # DexScreener معمولاً میلی‌ثانیه برمی‌گرداند
        if created > 1e12:
            created = created / 1000
        created_dt = datetime.fromtimestamp(created, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - created_dt).total_seconds() / 3600
    except:
        return None


def calculate_score(data: Dict, symbol: str = None) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    warnings: List[str] = []

    pairs = data.get("pairs") or []
    if not pairs:
        return {
            "score": 0,
            "category": "SKIP",
            "recommendation": "رد - داده کافی نیست",
            "risk_level": "نامشخص",
            "reasons": ["هیچ جفت معاملاتی پیدا نشد"],
            "warnings": [],
            "metrics": {}
        }

    # بهترین جفت بر اساس لیکوئیدیتی
    pair = max(pairs, key=lambda p: safe_float(p.get("liquidity", {}).get("usd", 0)))

    liquidity = safe_float(pair.get("liquidity", {}).get("usd", 0))
    volume_24h = safe_float(pair.get("volume", {}).get("h24", 0))
    volume_6h = safe_float(pair.get("volume", {}).get("h6", 0))
    price_change_24h = safe_float(pair.get("priceChange", {}).get("h24", 0))
    price_change_6h = safe_float(pair.get("priceChange", {}).get("h6", 0))
    price_change_1h = safe_float(pair.get("priceChange", {}).get("h1", 0))
    fdv = safe_float(pair.get("fdv", 0))
    market_cap = safe_float(pair.get("marketCap", 0)) or fdv
    txns = pair.get("txns", {}).get("h24", {})
    buys = safe_float(txns.get("buys", 0))
    sells = safe_float(txns.get("sells", 0))
    chain = pair.get("chainId", "unknown")
    dex = pair.get("dexId", "unknown")
    age_h = pair_age_hours(pair)

    # ========== ۱. لیکوئیدیتی (۲۵ امتیاز) - الهام از buzz ==========
    if liquidity >= 500000:
        score += 25
        reasons.append(f"لیکوئیدیتی عالی: ${liquidity:,.0f}")
    elif liquidity >= 200000:
        score += 20
        reasons.append(f"لیکوئیدیتی خوب: ${liquidity:,.0f}")
    elif liquidity >= 80000:
        score += 14
        reasons.append(f"لیکوئیدیتی قابل قبول: ${liquidity:,.0f}")
    elif liquidity >= 25000:
        score += 8
        reasons.append(f"لیکوئیدیتی متوسط: ${liquidity:,.0f}")
        warnings.append("لغزش متوسط")
    elif liquidity >= 10000:
        score += 4
        reasons.append(f"لیکوئیدیتی کم: ${liquidity:,.0f}")
        warnings.append("لغزش بالا")
    else:
        reasons.append(f"لیکوئیدیتی خیلی کم: ${liquidity:,.0f}")
        warnings.append("ریسک نقدشوندگی خطرناک")

    # ========== ۲. حجم ۲۴ ساعته (۲۰ امتیاز) ==========
    if volume_24h >= 1000000:
        score += 20
        reasons.append(f"حجم بسیار بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 400000:
        score += 16
        reasons.append(f"حجم خوب: ${volume_24h:,.0f}")
    elif volume_24h >= 100000:
        score += 11
        reasons.append(f"حجم متوسط رو به بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 30000:
        score += 6
        reasons.append(f"حجم متوسط: ${volume_24h:,.0f}")
    elif volume_24h >= 10000:
        score += 3
        reasons.append(f"حجم کم: ${volume_24h:,.0f}")
    else:
        reasons.append(f"حجم خیلی کم: ${volume_24h:,.0f}")

    # نسبت حجم به لیکوئیدیتی
    if liquidity > 0:
        vol_liq = volume_24h / liquidity
        if vol_liq >= 3:
            score += 5
            reasons.append("نسبت حجم/لیکوئیدیتی عالی")
        elif vol_liq >= 1.2:
            score += 3
            reasons.append("نسبت حجم/لیکوئیدیتی خوب")
        elif vol_liq < 0.2 and volume_24h > 0:
            warnings.append("حجم نسبت به لیکوئیدیتی ضعیف است")

    # ========== ۳. مارکت‌کپ (۲۰ امتیاز) - مناسب سبک BITFA ==========
    if 0 < market_cap < 2_000_000:
        score += 12
        reasons.append(f"مارکت‌کپ خیلی کم: ${market_cap:,.0f}")
        risk_base = "بالا"
    elif 2_000_000 <= market_cap < 15_000_000:
        score += 18
        reasons.append(f"مارکت‌کپ مناسب (کم‌کپ): ${market_cap:,.0f}")
        risk_base = "متوسط تا بالا"
    elif 15_000_000 <= market_cap < 80_000_000:
        score += 15
        reasons.append(f"مارکت‌کپ متوسط: ${market_cap:,.0f}")
        risk_base = "متوسط"
    elif 80_000_000 <= market_cap < 400_000_000:
        score += 9
        reasons.append(f"مارکت‌کپ نسبتاً بالا: ${market_cap:,.0f}")
        risk_base = "کم تا متوسط"
    else:
        score += 4
        reasons.append(f"مارکت‌کپ بالا: ${market_cap:,.0f}")
        risk_base = "کم"
        warnings.append("پتانسیل رشد انفجاری محدود")

    # هشدار لیکوئیدیتی نسبت به کپ
    if market_cap > 0 and liquidity > 0:
        liq_mc_ratio = liquidity / market_cap
        if liq_mc_ratio < 0.03 and market_cap > 5_000_000:
            warnings.append("لیکوئیدیتی نسبت به مارکت‌کپ پایین است")
            score -= 3

    # ========== ۴. مومنتوم (۲۰ امتیاز) ==========
    if 10 <= price_change_24h <= 55:
        score += 16
        reasons.append(f"رشد ۲۴س معقول و جذاب: {price_change_24h:.1f}%")
    elif 55 < price_change_24h <= 120:
        score += 11
        reasons.append(f"رشد ۲۴س قوی: {price_change_24h:.1f}%")
        warnings.append("رشد زیاد → احتمال نیاز به پولبک")
    elif price_change_24h > 120:
        score += 4
        reasons.append(f"رشد بسیار زیاد: {price_change_24h:.1f}%")
        warnings.append("احتمال FOMO و اصلاح")
    elif 0 <= price_change_24h < 10:
        score += 9
        reasons.append(f"نوسان ملایم: {price_change_24h:.1f}%")
    elif -18 <= price_change_24h < 0:
        score += 6
        reasons.append(f"اصلاح خفیف (ممکن است پولبک): {price_change_24h:.1f}%")
    else:
        score += 1
        reasons.append(f"ریزش قابل توجه: {price_change_24h:.1f}%")
        warnings.append("فشار فروش")

    if price_change_1h > 3.5:
        score += 4
        reasons.append(f"مومنتوم ۱س مثبت: {price_change_1h:.1f}%")
    elif price_change_1h < -7:
        score -= 4
        warnings.append(f"فشار فروش ۱ ساعته: {price_change_1h:.1f}%")

    # ========== ۵. نسبت خرید/فروش + سن (۱۵ امتیاز) ==========
    total_tx = buys + sells
    if total_tx > 15:
        buy_ratio = buys / total_tx
        if buy_ratio >= 0.62:
            score += 10
            reasons.append(f"غلبه قوی خریداران: {buy_ratio*100:.0f}%")
        elif buy_ratio >= 0.53:
            score += 6
            reasons.append(f"تعادل متمایل به خرید")
        elif buy_ratio < 0.40:
            score -= 4
            warnings.append("غلبه فروشندگان")

    if age_h is not None:
        if age_h >= 24 * 30:  # > 30 روز
            score += 5
            reasons.append(f"جفت نسبتاً بالغ ({age_h/24:.0f} روز)")
        elif age_h >= 24 * 7:
            score += 3
            reasons.append(f"جفت چندروزه ({age_h/24:.1f} روز)")
        elif age_h < 6:
            warnings.append(f"جفت بسیار جدید ({age_h:.1f} ساعت)")
            score -= 2

    score = max(0, min(100, int(score)))

    # ========== دسته‌بندی اقدام (الهام از buzz) ==========
    if score >= 82:
        category = "HOT"
        recommendation = "امتیاز عالی - قابل بررسی جدی برای ورود محدود"
        action = "اولویت بررسی"
    elif score >= 68:
        category = "QUALIFIED"
        recommendation = "امتیاز خوب - مناسب بررسی با مدیریت ریسک"
        action = "بررسی برای ورود"
    elif score >= 50:
        category = "WATCH"
        recommendation = "امتیاز متوسط - نظارت و انتظار تأیید ساختار"
        action = "نظارت"
    else:
        category = "SKIP"
        recommendation = "امتیاز ضعیف - بهتر است رد شود"
        action = "رد"

    # سطح ریسک نهایی
    if risk_base == "بالا" or liquidity < 15000 or (market_cap > 0 and liquidity / market_cap < 0.02):
        risk_level = "بالا"
    elif risk_base in ["متوسط تا بالا", "متوسط"]:
        risk_level = "متوسط"
    else:
        risk_level = "کم تا متوسط"

    return {
        "score": score,
        "category": category,
        "recommendation": recommendation,
        "action": action,
        "risk_level": risk_level,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "liquidity_usd": round(liquidity),
            "volume_24h": round(volume_24h),
            "market_cap": round(market_cap),
            "price_change_24h": round(price_change_24h, 2),
            "price_change_1h": round(price_change_1h, 2),
            "buy_ratio": round(buys / total_tx, 2) if total_tx > 0 else None,
            "pair_age_hours": round(age_h, 1) if age_h is not None else None,
            "chain": chain,
            "dex": dex
        },
        "note": "نسخه ۰.۴ | ترکیب سبک BITFA + ایده‌های پروژه‌های متن‌باز | NFA | DYOR"
    }


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    data = get_dexscreener_data(token_address=address, symbol=symbol)
    if not data:
        return {"error": "داده پیدا نشد", "score": 0, "category": "SKIP", "recommendation": "رد"}
    return calculate_score(data, symbol=symbol)
