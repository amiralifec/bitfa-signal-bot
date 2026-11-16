"""
BITFA Signal Scorer - Version 1.3.1
token-cache + pair-fix + Multi-TF PA + CoinGecko + phase guard
"""

import os
import requests
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from price_action import calculate_price_action_score

COINGECKO_KEY = os.getenv("COINGECKO_API_KEY", "")
CG_BASE = "https://api.coingecko.com/api/v3"

CG_PLATFORMS = [
    "ethereum", "binance-smart-chain", "polygon-pos", "arbitrum-one", "base",
    "optimistic-ethereum", "avalanche", "fantom", "plume-network", "solana",
    "sui", "ton", "tron",
]

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


def coingecko_by_contract(address: str) -> Optional[Dict]:
    if not address:
        return None
    addr = address.strip()
    for platform in CG_PLATFORMS:
        try:
            r = requests.get(
                f"{CG_BASE}/coins/{platform}/contract/{addr}",
                headers=cg_headers(),
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json() or {}
                if data.get("id"):
                    return data
        except Exception as e:
            print(f"CG contract {platform} error: {e}")
            continue
    return None


def coingecko_market(coin_id: str) -> Optional[Dict]:
    try:
        r = requests.get(
            f"{CG_BASE}/coins/markets",
            params={"vs_currency": "usd", "ids": coin_id, "price_change_percentage": "1h,24h,7d"},
            headers=cg_headers(),
            timeout=12,
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


def select_best_pair(
    pairs: List[Dict],
    query_symbol: str = None,
    prefer_price: Optional[float] = None,
) -> Optional[Dict]:
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
        price = safe_float(p.get("priceUsd"), None)
        chg = (p.get("priceChange") or {}).get("h24")
        if liq < 1500 and vol < 300:
            continue
        pair_score = vol * 1.0 + min(liq, vol * 3) * 0.25
        if chg is not None:
            pair_score *= 1.1
        if liq > 0:
            ratio = vol / liq
            if ratio < 0.02:
                pair_score *= 0.15
            elif ratio < 0.08:
                pair_score *= 0.45
            elif ratio < 0.2:
                pair_score *= 0.75
        if price is not None and price < 1e-6 and vol < 50000:
            pair_score *= 0.3
        if prefer_price and prefer_price > 0 and price and price > 0:
            rel = abs(price - prefer_price) / prefer_price
            if rel <= 0.12:
                pair_score *= 1.8
            elif rel <= 0.30:
                pair_score *= 1.25
            elif rel >= 0.55:
                pair_score *= 0.35
        scored.append((pair_score, p))
    if not scored:
        return max(
            candidates,
            key=lambda p: safe_float((p.get("volume") or {}).get("h24", 0)),
        )
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


def detect_asset_kind(
    symbol: str,
    name: str,
    price_usd: Optional[float],
    *,
    liquidity: float = 0.0,
    market_cap: float = 0.0,
    rank: Optional[int] = None,
    has_dex_pair: bool = False,
) -> str:
    sym = (symbol or "").upper()
    name_l = (name or "").lower()
    stock_name_hint = any(
        k in name_l
        for k in (
            "inc.", "inc ", "corp", "corporation", "semiconductor", "etf",
            "shares", "nasdaq", "nyse", "equity", "holdings plc", "class a",
        )
    )
    if stock_name_hint and sym in STOCK_LIKE:
        return "stock_perp"
    if sym in STOCK_LIKE:
        realistic_stock_price = price_usd is not None and price_usd >= 5.0
        big_cap_no_meme = (
            (market_cap >= 1_000_000_000 or (rank is not None and rank <= 50))
            and liquidity < 50_000
        )
        looks_like_spoof = (
            has_dex_pair
            and price_usd is not None
            and price_usd < 1.0
            and (market_cap < 50_000_000 or market_cap == 0)
        )
        if looks_like_spoof:
            return "crypto"
        if realistic_stock_price or big_cap_no_meme:
            return "stock_perp"
        if price_usd is not None and price_usd >= 1.0:
            return "stock_perp_candidate"
        return "crypto"
    if stock_name_hint:
        return "stock_perp"
    if price_usd is not None and price_usd >= 100 and len(sym) <= 5:
        if sym not in {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "TON", "AVAX"}:
            return "stock_perp_candidate"
    return "crypto"


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
    if symbol and not address:
        try:
            from storage import get_cached_token
            cached = get_cached_token(symbol)
            if cached and cached.get("address"):
                address = cached.get("address")
        except Exception as e:
            print(f"token cache read: {e}")

    prefer_price = None
    if symbol and not address:
        early_cg = coingecko_search(symbol)
        if early_cg and early_cg.get("id"):
            early_mkt = coingecko_market(early_cg.get("id"))
            if early_mkt:
                prefer_price = safe_float(early_mkt.get("current_price"), None)

    dex_data = get_dexscreener_data(token_address=address, symbol=symbol if not address else None)
    pair = None
    if dex_data and dex_data.get("pairs"):
        pair = select_best_pair(
            dex_data.get("pairs") or [],
            query_symbol=symbol,
            prefer_price=prefer_price,
        )

    liquidity = volume_24h = volume_6h = volume_1h = volume_m5 = market_cap = buys = sells = 0.0
    price_change_24h = price_change_6h = price_change_1h = price_change_m5 = price_usd = age_h = None
    chain = dex = base_sym = base_name = token_address = ""
    pair_url = None

    if pair:
        liquidity = safe_float((pair.get("liquidity") or {}).get("usd", 0))
        pc = pair.get("priceChange") or {}
        vol = pair.get("volume") or {}
        price_change_24h = safe_float(pc.get("h24"), None) if pc.get("h24") is not None else None
        price_change_6h = safe_float(pc.get("h6"), None) if pc.get("h6") is not None else None
        price_change_1h = safe_float(pc.get("h1"), None) if pc.get("h1") is not None else None
        price_change_m5 = safe_float(pc.get("m5"), None) if pc.get("m5") is not None else None
        volume_24h = safe_float(vol.get("h24", 0))
        volume_6h = safe_float(vol.get("h6", 0))
        volume_1h = safe_float(vol.get("h1", 0))
        volume_m5 = safe_float(vol.get("m5", 0))
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
    cg_coin_id = None

    search_sym = (base_sym if base_sym and base_sym != "?" else symbol) or None
    if search_sym:
        cg_hit = coingecko_search(search_sym)
        if cg_hit:
            cg_coin_id = cg_hit.get("id")

    if not cg_coin_id and address:
        cg_contract = coingecko_by_contract(address)
        if cg_contract:
            cg_coin_id = cg_contract.get("id")
            if not base_name:
                base_name = cg_contract.get("name") or ""
            if not base_sym or base_sym == "?":
                base_sym = (cg_contract.get("symbol") or "?").upper()
            token_address = token_address or address
            md = (cg_contract.get("market_data") or {})
            if price_usd is None and md.get("current_price"):
                price_usd = safe_float((md.get("current_price") or {}).get("usd"), None)
            if market_cap <= 0 and md.get("market_cap"):
                market_cap = safe_float((md.get("market_cap") or {}).get("usd"), 0)
            if price_change_24h is None and md.get("price_change_percentage_24h") is not None:
                price_change_24h = safe_float(md.get("price_change_percentage_24h"), None)

    if cg_coin_id:
        cg_mkt = coingecko_market(cg_coin_id)
        if cg_mkt:
            rank = cg_mkt.get("market_cap_rank")
            cg_price = safe_float(cg_mkt.get("current_price"), None)
            if cg_price and cg_price > 0 and price_usd and price_usd > 0:
                rel = abs(price_usd - cg_price) / cg_price
                if rel >= 0.35 and dex_data and dex_data.get("pairs"):
                    better = select_best_pair(
                        dex_data.get("pairs") or [],
                        query_symbol=symbol or base_sym,
                        prefer_price=cg_price,
                    )
                    if better and better is not pair:
                        pair = better
                        liquidity = safe_float((pair.get("liquidity") or {}).get("usd", 0))
                        vol = pair.get("volume") or {}
                        pc = pair.get("priceChange") or {}
                        volume_24h = safe_float(vol.get("h24", 0))
                        volume_6h = safe_float(vol.get("h6", 0))
                        volume_1h = safe_float(vol.get("h1", 0))
                        volume_m5 = safe_float(vol.get("m5", 0))
                        if pc.get("h24") is not None:
                            price_change_24h = safe_float(pc.get("h24"), None)
                        if pc.get("h6") is not None:
                            price_change_6h = safe_float(pc.get("h6"), None)
                        if pc.get("h1") is not None:
                            price_change_1h = safe_float(pc.get("h1"), None)
                        if pc.get("m5") is not None:
                            price_change_m5 = safe_float(pc.get("m5"), None)
                        price_usd = safe_float(pair.get("priceUsd"), None) or cg_price
                        fdv = safe_float(pair.get("fdv", 0))
                        market_cap = safe_float(pair.get("marketCap", 0)) or fdv or market_cap
                        txns = (pair.get("txns") or {}).get("h24", {}) or {}
                        buys = safe_float(txns.get("buys", 0))
                        sells = safe_float(txns.get("sells", 0))
                        chain = pair.get("chainId") or chain
                        dex = pair.get("dexId") or dex
                        base = pair.get("baseToken") or {}
                        if base.get("symbol"):
                            base_sym = (base.get("symbol") or base_sym).upper()
                        if base.get("name"):
                            base_name = base.get("name") or base_name
                        token_address = base.get("address") or token_address
                        age_h = pair_age_hours(pair)
                        pair_addr = pair.get("pairAddress")
                        if chain and pair_addr:
                            pair_url = f"https://dexscreener.com/{chain}/{pair_addr}"
                if price_usd and cg_price and abs(price_usd - cg_price) / cg_price >= 0.35:
                    price_usd = cg_price
            if price_usd is None:
                price_usd = cg_price
            if market_cap <= 0:
                market_cap = safe_float(cg_mkt.get("market_cap"), 0)
            if price_change_24h is None:
                price_change_24h = safe_float(cg_mkt.get("price_change_percentage_24h"), None)
            if price_change_1h is None:
                price_change_1h = safe_float(cg_mkt.get("price_change_percentage_1h_in_currency"), None)
            if not base_name:
                base_name = cg_mkt.get("name") or ""
            if not base_sym or base_sym == "?":
                base_sym = (cg_mkt.get("symbol") or "?").upper()
            cg_vol = safe_float(cg_mkt.get("total_volume"), 0)
            if cg_vol > volume_24h:
                volume_24h = max(volume_24h, cg_vol * 0.15)
            cg_url = f"https://www.coingecko.com/en/coins/{cg_coin_id}"

    if not pair and not cg_mkt and not cg_coin_id:
        return {
            "error": "داده پیدا نشد (نه در دکس و نه در CoinGecko). ممکن است زنجیره پشتیبانی‌نشده باشد.",
            "score": 0,
            "category": "SKIP",
            "recommendation": "رد",
            "confidence": 0,
            "position_suggestion": "هیچ",
            "asset_kind": "unknown",
            "pa_score": 0,
            "pa_tags": [],
            "entry_phase": "NEUTRAL",
            "phase_label": "بدون سیگنال",
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

    _pa = calculate_price_action_score(
        price_change_m5=price_change_m5,
        price_change_1h=price_change_1h,
        price_change_6h=price_change_6h,
        price_change_24h=price_change_24h,
        volume_m5=volume_m5,
        volume_1h=volume_1h,
        volume_6h=volume_6h,
        volume_24h=volume_24h,
        liquidity=liquidity,
        buys=buys,
        sells=sells,
    )
    pa_score, pa_tags, pa_reasons, pa_warnings = _pa[0], _pa[1], _pa[2], _pa[3]
    entry_phase = _pa[4] if len(_pa) > 4 else "NEUTRAL"
    phase_label = _pa[5] if len(_pa) > 5 else ""
    score = max(0, min(100, score + pa_score))
    reasons = pa_reasons + reasons
    warnings = pa_warnings + warnings
    if entry_phase == "EXHAUSTED" and score >= 65:
        score = min(score, 58)
        warnings.append("فاز ورود: EXHAUSTED — امتیاز برای جلوگیری از chase محدود شد")

    asset_kind = detect_asset_kind(
        base_sym or (symbol or ""),
        base_name,
        price_usd,
        liquidity=liquidity,
        market_cap=market_cap,
        rank=rank,
        has_dex_pair=bool(pair),
    )
    if (base_sym or (symbol or "")).upper() in STOCK_LIKE and asset_kind == "crypto":
        warnings.append("نماد هم‌نام با سهام/پرپ معروف — این داده بیشتر شبیه توکن کریپتو است، با سهام واقعی قاطی نکن")
    if asset_kind.startswith("stock"):
        reasons.insert(0, "نوع دارایی: سهام/پرپ (نه آلت‌کوین معمولی)")
        warnings.append("این مورد را با توکن‌های کریپتو قاطی نکن")
    elif rank or cg_coin_id:
        reasons.insert(0, "منبع بازار: CoinGecko + Dex" if pair else "منبع بازار: CoinGecko")
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

    # فاز نزولی/اشباع نباید HOT یا QUALIFIED بماند
    if entry_phase in ("BEARISH", "EXHAUSTED") and category in ("HOT", "QUALIFIED"):
        score = min(int(score), 58)
        category, recommendation, action = "WATCH", "فاز نزولی/اشباع — فقط نظارت، ورود تهاجمی نکن", "نظارت"
        warnings = list(warnings) + [f"فاز {entry_phase}: دسته از QUALIFIED به WATCH محدود شد"]

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

    try:
        if (base_sym or symbol) and token_address:
            from storage import set_cached_token
            pair_addr = ""
            if pair_url and "/" in pair_url:
                pair_addr = pair_url.rstrip("/").split("/")[-1]
            set_cached_token(
                (base_sym or symbol or "").upper(),
                address=token_address,
                chain=chain or "",
                pair_address=pair_addr,
                name=base_name or "",
                price_usd=price_usd,
            )
    except Exception as e:
        print(f"token cache write: {e}")

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
        "entry_phase": entry_phase,
        "phase_label": phase_label,
        "links": {"dexscreener": pair_url, "coingecko": cg_url},
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "liquidity_usd": round(liquidity) if liquidity else 0,
            "volume_24h": round(volume_24h) if volume_24h else 0,
            "volume_6h": round(volume_6h) if volume_6h else 0,
            "volume_1h": round(volume_1h) if volume_1h else 0,
            "market_cap": round(market_cap) if market_cap else 0,
            "price_change_24h": round(price_change_24h, 2) if price_change_24h is not None else None,
            "price_change_6h": round(price_change_6h, 2) if price_change_6h is not None else None,
            "price_change_1h": round(price_change_1h, 2) if price_change_1h is not None else None,
            "price_change_m5": round(price_change_m5, 2) if price_change_m5 is not None else None,
            "chain": chain or None,
            "dex": dex or None,
        },
        "note": "نسخه ۱.۳.۱ | phase-guard + token-cache + PA | NFA | DYOR",
    }
