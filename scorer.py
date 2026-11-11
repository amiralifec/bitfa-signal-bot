"""
BITFA Signal Scorer - Version 0.8.1
رفع انتخاب جفت اشتباه + اولویت جفت فعال با تغییر قیمت واقعی
"""

import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
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
    created = pair.get("pairCreatedAt")
    if not created:
        return None
    try:
        if created > 1e12:
            created = created / 1000
        created_dt = datetime.fromtimestamp(created, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - created_dt).total_seconds() / 3600
    except:
        return None


def select_best_pair(pairs: List[Dict], query_symbol: str = None) -> Optional[Dict]:
    """
    انتخاب هوشمند:
    1. اگر تیکر داده شده، فقط جفت‌هایی که baseToken.symbol دقیقاً مطابقت دارد
    2. اولویت با جفت دارای حجم واقعی + لیکوئیدیتی
    3. جفت‌های مرده را حذف کن
    """
    if not pairs:
        return None

    candidates = pairs

    # فیلتر نماد دقیق
    if query_symbol:
        q = query_symbol.strip().upper()
        exact = []
        for p in pairs:
            base = p.get("baseToken") or {}
            sym = (base.get("symbol") or "").upper()
            if sym == q:
                exact.append(p)
        if exact:
            candidates = exact

    scored = []
    for p in candidates:
        liq = safe_float((p.get("liquidity") or {}).get("usd", 0))
        vol = safe_float((p.get("volume") or {}).get("h24", 0))
        chg = (p.get("priceChange") or {}).get("h24")

        # جفت تقریباً مرده
        if liq < 2000 and vol < 500:
            continue

        # امتیاز ترکیبی
        pair_score = liq * 0.4 + vol * 0.6

        # اگر تغییر قیمت معتبر دارد کمی پاداش بده
        if chg is not None:
            pair_score *= 1.15

        # جفت با حجم خیلی کم نسبت به لیکوئیدیتی تنزل
        if liq > 0 and vol / liq < 0.05 and vol < 20000:
            pair_score *= 0.5

        scored.append((pair_score, p))

    if not scored:
        # اگر همه فیلتر شدند، از بین همان candidates بالاترین لیکوئیدیتی
        return max(candidates, key=lambda p: safe_float((p.get("liquidity") or {}).get("usd", 0)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def calculate_score(data: Dict, symbol: str = None) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    warnings: List[str] = []
    confidence = 45
    risk_base = "متوسط"

    pairs = data.get("pairs") or []
    if not pairs:
        return {
            "score": 0,
            "category": "SKIP",
            "recommendation": "رد - داده کافی نیست",
            "action": "رد",
            "risk_level": "نامشخص",
            "confidence": 0,
            "position_suggestion": "هیچ",
            "reasons": ["هیچ جفت معاملاتی پیدا نشد"],
            "warnings": [],
            "metrics": {}
        }

    pair = select_best_pair(pairs, query_symbol=symbol)
    if not pair:
        return {
            "score": 0,
            "category": "SKIP",
            "recommendation": "رد",
            "action": "رد",
            "risk_level": "نامشخص",
            "confidence": 0,
            "position_suggestion": "هیچ",
            "reasons": ["جفت مناسب پیدا نشد"],
            "warnings": [],
            "metrics": {}
        }

    liquidity = safe_float((pair.get("liquidity") or {}).get("usd", 0))
    volume_24h = safe_float((pair.get("volume") or {}).get("h24", 0))

    # تغییر قیمت: اگر None بود، ننویس 0 گمراه‌کننده
    raw_chg_24h = (pair.get("priceChange") or {}).get("h24")
    raw_chg_1h = (pair.get("priceChange") or {}).get("h1")
    price_change_24h = safe_float(raw_chg_24h, default=None) if raw_chg_24h is not None else None
    price_change_1h = safe_float(raw_chg_1h, default=None) if raw_chg_1h is not None else None

    fdv = safe_float(pair.get("fdv", 0))
    market_cap = safe_float(pair.get("marketCap", 0)) or fdv
    txns = (pair.get("txns") or {}).get("h24", {}) or {}
    buys = safe_float(txns.get("buys", 0))
    sells = safe_float(txns.get("sells", 0))
    chain = pair.get("chainId", "unknown")
    dex = pair.get("dexId", "unknown")
    base_sym = ((pair.get("baseToken") or {}).get("symbol") or symbol or "?").upper()
    age_h = pair_age_hours(pair)

    if liquidity > 0: confidence += 15
    if volume_24h > 0: confidence += 12
    if market_cap > 0: confidence += 10
    if age_h is not None: confidence += 10
    if buys + sells > 8: confidence += 8
    if price_change_24h is not None: confidence += 5
    confidence = min(100, confidence)

    # Liquidity (24)
    if liquidity >= 400000:
        score += 24
        reasons.append(f"لیکوئیدیتی عالی: ${liquidity:,.0f}")
    elif liquidity >= 150000:
        score += 19
        reasons.append(f"لیکوئیدیتی خوب: ${liquidity:,.0f}")
    elif liquidity >= 60000:
        score += 13
        reasons.append(f"لیکوئیدیتی قابل قبول: ${liquidity:,.0f}")
    elif liquidity >= 20000:
        score += 7
        reasons.append(f"لیکوئیدیتی متوسط: ${liquidity:,.0f}")
        warnings.append("لغزش متوسط ممکن است")
    elif liquidity >= 8000:
        score += 3
        reasons.append(f"لیکوئیدیتی کم: ${liquidity:,.0f}")
        warnings.append("لغزش بالا")
    else:
        reasons.append(f"لیکوئیدیتی خیلی کم: ${liquidity:,.0f}")
        warnings.append("ریسک نقدشوندگی خطرناک")
        score -= 6

    # Volume (22)
    if volume_24h >= 800000:
        score += 18
        reasons.append(f"حجم بسیار بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 250000:
        score += 14
        reasons.append(f"حجم خوب: ${volume_24h:,.0f}")
    elif volume_24h >= 80000:
        score += 9
        reasons.append(f"حجم متوسط رو به بالا: ${volume_24h:,.0f}")
    elif volume_24h >= 25000:
        score += 5
        reasons.append(f"حجم متوسط: ${volume_24h:,.0f}")
    elif volume_24h >= 8000:
        score += 2
        reasons.append(f"حجم کم: ${volume_24h:,.0f}")
    else:
        reasons.append(f"حجم خیلی کم: ${volume_24h:,.0f}")
        score -= 5

    if liquidity > 0:
        vol_liq = volume_24h / liquidity
        if vol_liq >= 2.5:
            score += 6
            reasons.append("نسبت حجم/لیکوئیدیتی قوی")
        elif vol_liq >= 0.8:
            score += 3
            reasons.append("نسبت حجم/لیکوئیدیتی قابل قبول")
        elif vol_liq < 0.12:
            score -= 10
            warnings.append("حجم نسبت به لیکوئیدیتی بسیار ضعیف (جفت کم‌فعال)")
        elif vol_liq < 0.30:
            score -= 5
            warnings.append("حجم نسبت به لیکوئیدیتی ضعیف است")

    # Market Cap (18)
    if 0 < market_cap < 2_500_000:
        score += 11
        reasons.append(f"مارکت‌کپ خیلی کم: ${market_cap:,.0f}")
        risk_base = "بالا"
    elif 2_500_000 <= market_cap < 20_000_000:
        score += 17
        reasons.append(f"مارکت‌کپ مناسب (کم‌کپ): ${market_cap:,.0f}")
        risk_base = "متوسط تا بالا"
    elif 20_000_000 <= market_cap < 100_000_000:
        score += 13
        reasons.append(f"مارکت‌کپ متوسط: ${market_cap:,.0f}")
        risk_base = "متوسط"
    elif 100_000_000 <= market_cap < 500_000_000:
        score += 7
        reasons.append(f"مارکت‌کپ نسبتاً بالا: ${market_cap:,.0f}")
        risk_base = "کم تا متوسط"
    else:
        score += 2
        reasons.append(f"مارکت‌کپ بالا: ${market_cap:,.0f}")
        risk_base = "کم"
        warnings.append("پتانسیل رشد انفجاری محدود")

    if market_cap > 0 and liquidity > 0 and liquidity / market_cap < 0.025 and market_cap > 8_000_000:
        score -= 5
        warnings.append("لیکوئیدیتی نسبت به مارکت‌کپ پایین است")

    # Momentum (20)
    if price_change_24h is None:
        reasons.append("داده تغییر ۲۴ ساعته نامشخص")
        score += 4
    elif 8 <= price_change_24h <= 50:
        score += 15
        reasons.append(f"رشد ۲۴س معقول: {price_change_24h:.1f}%")
    elif 50 < price_change_24h <= 110:
        score += 10
        reasons.append(f"رشد ۲۴س قوی: {price_change_24h:.1f}%")
        warnings.append("رشد زیاد → احتمال نیاز به پولبک")
    elif price_change_24h > 110:
        score += 3
        reasons.append(f"رشد بسیار زیاد: {price_change_24h:.1f}%")
        warnings.append("احتمال FOMO و اصلاح")
    elif 0 <= price_change_24h < 8:
        score += 8
        reasons.append(f"نوسان ملایم: {price_change_24h:.1f}%")
    elif -15 <= price_change_24h < 0:
        score += 5
        reasons.append(f"اصلاح خفیف (ممکن است پولبک): {price_change_24h:.1f}%")
    else:
        reasons.append(f"ریزش: {price_change_24h:.1f}%")
        warnings.append("فشار فروش")

    if price_change_1h is not None:
        if price_change_1h > 3:
            score += 4
            reasons.append(f"مومنتوم ۱س مثبت: {price_change_1h:.1f}%")
        elif price_change_1h < -6:
            score -= 5
            warnings.append(f"فشار فروش ۱ ساعته: {price_change_1h:.1f}%")

    # Buy pressure + age (16)
    total_tx = buys + sells
    if total_tx > 20:
        buy_ratio = buys / total_tx
        if buy_ratio >= 0.60:
            score += 10
            reasons.append(f"غلبه قوی خریداران: {buy_ratio*100:.0f}%")
        elif buy_ratio >= 0.52:
            score += 5
            reasons.append("تعادل متمایل به خرید")
        elif buy_ratio < 0.40:
            score -= 5
            warnings.append("غلبه فروشندگان")
    elif total_tx > 0:
        score += 2

    if age_h is not None:
        if age_h >= 24 * 45:
            score += 5
            reasons.append(f"جفت بالغ ({age_h/24:.0f} روز)")
        elif age_h >= 24 * 7:
            score += 3
            reasons.append(f"جفت چندروزه ({age_h/24:.1f} روز)")
        elif age_h < 4:
            score -= 4
            warnings.append(f"جفت بسیار جدید ({age_h:.1f} ساعت)")

    score = max(0, min(100, int(score)))

    if score >= 80 and confidence >= 70:
        category = "HOT"
        recommendation = "امتیاز عالی - قابل بررسی جدی برای ورود محدود"
        action = "اولویت بررسی"
    elif score >= 65:
        category = "QUALIFIED"
        recommendation = "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت"
        action = "بررسی برای ورود"
    elif score >= 48:
        category = "WATCH"
        recommendation = "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار"
        action = "نظارت"
    else:
        category = "SKIP"
        recommendation = "امتیاز ضعیف - رد شود"
        action = "رد"

    if risk_base == "بالا" or liquidity < 12000:
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
        "token": base_sym,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "liquidity_usd": round(liquidity),
            "volume_24h": round(volume_24h),
            "market_cap": round(market_cap),
            "price_change_24h": round(price_change_24h, 2) if price_change_24h is not None else None,
            "price_change_1h": round(price_change_1h, 2) if price_change_1h is not None else None,
            "buy_ratio": round(buys / total_tx, 2) if total_tx > 0 else None,
            "pair_age_hours": round(age_h, 1) if age_h is not None else None,
            "chain": chain,
            "dex": dex
        },
        "note": "نسخه ۰.۸.۱ | انتخاب جفت اصلاح‌شده | NFA | DYOR"
    }


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    data = get_dexscreener_data(token_address=address, symbol=symbol)
    if not data:
        return {
            "error": "داده پیدا نشد",
            "score": 0,
            "category": "SKIP",
            "recommendation": "رد",
            "confidence": 0,
            "position_suggestion": "هیچ"
        }
    return calculate_score(data, symbol=symbol)
