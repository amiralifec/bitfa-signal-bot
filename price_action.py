"""Multi-timeframe Price Action + entry-phase classification for BITFA."""
from typing import Optional, List, Tuple


def classify_entry_phase(
    *,
    price_change_m5: Optional[float] = None,
    price_change_1h: Optional[float] = None,
    price_change_6h: Optional[float] = None,
    price_change_24h: Optional[float] = None,
    volume_24h: float = 0.0,
    liquidity: float = 0.0,
    pa_tags: Optional[List[str]] = None,
) -> Tuple[str, str]:
    tags = set(pa_tags or [])
    ch5, ch1, ch6, ch24 = price_change_m5, price_change_1h, price_change_6h, price_change_24h
    vol_liq = (volume_24h / liquidity) if liquidity > 0 else 0.0

    if "MTFAlignedDown" in tags or "SellingPressure" in tags or (
        ch24 is not None and ch24 <= -12 and (ch1 is not None and ch1 < 0)
    ):
        return "BEARISH", "نزولی / فشار فروش"

    if ch24 is not None and ch24 > 100:
        return "EXHAUSTED", "اشباع پارابولیک — chase نکن"
    if ch24 is not None and ch24 > 70 and (
        (ch1 is not None and ch1 < -3)
        or (ch5 is not None and ch5 < -2)
        or "ShortWeakness" in tags
        or "SellerDominance" in tags
    ):
        return "EXHAUSTED", "پامپ + ضعف کوتاه‌مدت — دیر شده"

    if ch24 is not None and 45 < ch24 <= 100:
        if "MTFAlignedUp" in tags and ch1 is not None and ch1 > 2 and vol_liq >= 0.8:
            return "EXTENDED", "روند قوی ولی کش‌آمده"
        return "EXTENDED", "رشد زیاد — ورود فقط با تأیید جدید"

    if (
        "MTFAlignedUp" in tags
        or ("MomentumUp" in tags and "VolumeBreak" in tags)
        or ("BiasUp" in tags and "VolAcceleration" in tags)
    ):
        if ch24 is not None and 8 <= ch24 <= 45:
            return "DEVELOPING", "مومنتوم در حال توسعه — پنجره مناسب"
        if ch24 is not None and 0 <= ch24 < 8:
            return "EARLY", "شروع حرکت — نیاز به تأیید حجم"
        return "DEVELOPING", "ساختار صعودی در حال شکل‌گیری"

    if "HealthyPullback" in tags or (
        ch24 is not None and -12 <= ch24 < -2 and (ch1 is not None and ch1 >= 0)
    ):
        return "EARLY", "پولبک سالم — زیر نظر برای برگشت"

    if "BiasUp" in tags or "VolumeSupport" in tags:
        return "EARLY", "بایاس مثبت اولیه"

    return "NEUTRAL", "بدون سیگنال واضح"


def calculate_price_action_score(
    *,
    price_change_m5: Optional[float] = None,
    price_change_1h: Optional[float] = None,
    price_change_6h: Optional[float] = None,
    price_change_24h: Optional[float] = None,
    volume_m5: float = 0.0,
    volume_1h: float = 0.0,
    volume_6h: float = 0.0,
    volume_24h: float = 0.0,
    liquidity: float = 0.0,
    buys: float = 0.0,
    sells: float = 0.0,
) -> Tuple[int, List[str], List[str], List[str], str, str]:
    pa = 0
    tags: List[str] = []
    reasons: List[str] = []
    warnings: List[str] = []

    ch5 = price_change_m5
    ch1 = price_change_1h
    ch6 = price_change_6h
    ch24 = price_change_24h

    vol_liq = (volume_24h / liquidity) if liquidity > 0 else 0.0
    vol_1h_share = (volume_1h / volume_24h) if volume_24h > 0 else 0.0
    vol_6h_share = (volume_6h / volume_24h) if volume_24h > 0 else 0.0

    ups = 0
    downs = 0
    for ch in (ch5, ch1, ch6, ch24):
        if ch is None:
            continue
        if ch > 1.5:
            ups += 1
        elif ch < -1.5:
            downs += 1

    if ups >= 3 and downs == 0:
        pa += 7
        tags.append("MTFAlignedUp")
        reasons.append("PA: مومنتوم صعودی در چند تایم‌فریم هم‌راستا")
    elif downs >= 3 and ups == 0:
        pa -= 5
        tags.append("MTFAlignedDown")
        warnings.append("PA: فشار فروش چندتایم‌فریمی")
    elif ups >= 2 and downs <= 1:
        pa += 3
        tags.append("BiasUp")
        reasons.append("PA: بایاس صعودی کوتاه/میان‌مدت")

    if ch24 is not None:
        if 8 <= ch24 <= 40 and vol_liq >= 0.5:
            pa += 6
            tags.append("MomentumUp")
            reasons.append(f"PA: مومنتوم ۲۴س سالم ({ch24:.1f}%) با حجم")
        elif 40 < ch24 <= 80 and vol_liq >= 0.8:
            pa += 4
            tags.append("StrongTrend")
            reasons.append(f"PA: روند قوی ۲۴س ({ch24:.1f}%)")
            warnings.append("رشد تند → مراقب پولبک باش")
        elif ch24 > 80:
            pa += 1
            tags.append("Parabolic")
            reasons.append(f"PA: حرکت پارابولیک ({ch24:.1f}%)")
            warnings.append("ریسک برگشت بالا (اشباع)")
        elif -12 <= ch24 < -2 and vol_liq >= 0.4:
            if ch1 is not None and ch1 >= 0:
                pa += 3
                tags.append("HealthyPullback")
                reasons.append(f"PA: پولبک سالم ({ch24:.1f}%)")
            else:
                pa += 1
                tags.append("Pullback")
                reasons.append(f"PA: اصلاح ({ch24:.1f}%)")
        elif ch24 < -12:
            pa -= 4
            tags.append("SellingPressure")
            warnings.append(f"PA: فشار فروش ۲۴س ({ch24:.1f}%)")

    if ch1 is not None:
        if ch1 >= 6 and (ch24 is None or ch24 > 0):
            pa += 4
            tags.append("ShortMomentum")
            reasons.append(f"PA: مومنتوم ۱س قوی ({ch1:.1f}%)")
        elif ch1 <= -6:
            pa -= 3
            tags.append("ShortWeakness")
            warnings.append(f"PA: ضعف ۱س ({ch1:.1f}%)")

    if ch5 is not None:
        if ch5 >= 3 and (ch1 is None or ch1 >= 0):
            pa += 2
            tags.append("MicroPush")
            reasons.append(f"PA: فشار خرید ۵د ({ch5:.1f}%)")
        elif ch5 <= -4:
            pa -= 2
            tags.append("MicroSell")
            warnings.append(f"PA: فشار فروش ۵د ({ch5:.1f}%)")

    if volume_24h > 0 and liquidity > 0:
        if vol_liq >= 1.5 and ch24 is not None and ch24 > 3:
            pa += 4
            tags.append("VolumeBreak")
            reasons.append("PA: شکست حجمی / فعالیت بالا نسبت به لیکوئیدیتی")
        elif vol_liq >= 0.7 and ch24 is not None and ch24 > 0:
            pa += 2
            tags.append("VolumeSupport")
            reasons.append("PA: حجم پشتیبان روند")
        elif vol_liq < 0.12:
            pa -= 2
            tags.append("LowActivity")
            warnings.append("PA: فعالیت حجمی ضعیف")

    if vol_1h_share >= 0.20 and volume_1h > 5000:
        if ch1 is not None and ch1 > 2:
            pa += 3
            tags.append("VolAcceleration")
            reasons.append("PA: شتاب حجم در ۱ ساعت اخیر")
        elif ch1 is not None and ch1 < -3:
            pa -= 2
            tags.append("VolDump")
            warnings.append("PA: حجم بالا با ریزش ۱س")

    if vol_6h_share >= 0.55 and volume_6h > 10000 and ch6 is not None and ch6 > 5:
        pa += 2
        tags.append("SessionStrength")
        reasons.append("PA: قدرت جلسه ۶ساعته با حجم متمرکز")

    total_tx = buys + sells
    if total_tx >= 20:
        buy_ratio = buys / total_tx
        if buy_ratio >= 0.62:
            pa += 4
            tags.append("BuyerDominance")
            reasons.append(f"PA: غلبه خریداران ({buy_ratio*100:.0f}%)")
        elif buy_ratio <= 0.38:
            pa -= 3
            tags.append("SellerDominance")
            warnings.append(f"PA: غلبه فروشندگان ({(1-buy_ratio)*100:.0f}%)")

    if ch24 is not None and ch24 > 15 and vol_liq < 0.25 and volume_24h > 0:
        pa -= 3
        tags.append("ThinRally")
        warnings.append("PA: رشد بدون پشتیبانی حجم کافی")

    tags = list(dict.fromkeys(tags))
    phase, phase_label = classify_entry_phase(
        price_change_m5=ch5,
        price_change_1h=ch1,
        price_change_6h=ch6,
        price_change_24h=ch24,
        volume_24h=volume_24h,
        liquidity=liquidity,
        pa_tags=tags,
    )

    if phase == "EXHAUSTED":
        pa = min(pa, 4)
        warnings.append("سیگنال: ورود تهاجمی بعد از پامپ توصیه نمی‌شود")
        tags.append("ChaseRisk")
    elif phase == "EXTENDED":
        pa = min(pa, 12)
        warnings.append("سیگنال: ورود فقط با تأیید پولبک/ساختار جدید")

    if phase == "DEVELOPING":
        pa = min(20, pa + 2)
        reasons.append("سیگنال: پنجره ورود مناسب (در حال توسعه)")
    elif phase == "EARLY":
        pa = min(20, pa + 1)

    pa = max(0, min(20, int(pa)))
    tags = list(dict.fromkeys(tags))
    if not tags and pa == 0:
        tags.append("Neutral")
    return pa, tags, reasons, warnings, phase, phase_label
