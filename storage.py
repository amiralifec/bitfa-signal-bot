"""
حافظه اسکن قبلی + کش قرارداد/جفت درست توکن‌ها
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

STORE_PATH = os.getenv("SCAN_STORE_PATH", "last_scan.json")
TOKEN_CACHE_PATH = os.getenv("TOKEN_CACHE_PATH", "token_cache.json")

CAT_RANK = {"SKIP": 0, "WATCH": 1, "QUALIFIED": 2, "HOT": 3}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_last_scan() -> Dict[str, Any]:
    try:
        if not os.path.exists(STORE_PATH):
            return {"tickers": {}, "updated_at": None}
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"tickers": {}, "updated_at": None}
        data.setdefault("tickers", {})
        return data
    except Exception as e:
        print(f"load_last_scan error: {e}")
        return {"tickers": {}, "updated_at": None}


def save_last_scan(ticker_scores: Dict[str, Dict[str, Any]]) -> None:
    try:
        payload = {
            "updated_at": _now_iso(),
            "tickers": ticker_scores,
        }
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"save_last_scan error: {e}")


def load_token_cache() -> Dict[str, Any]:
    try:
        if not os.path.exists(TOKEN_CACHE_PATH):
            return {"tokens": {}, "updated_at": None}
        with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"tokens": {}, "updated_at": None}
        data.setdefault("tokens", {})
        return data
    except Exception as e:
        print(f"load_token_cache error: {e}")
        return {"tokens": {}, "updated_at": None}


def save_token_cache(tokens: Dict[str, Dict[str, Any]]) -> None:
    try:
        payload = {"updated_at": _now_iso(), "tokens": tokens}
        with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"save_token_cache error: {e}")


def get_cached_token(symbol: str) -> Optional[Dict[str, Any]]:
    if not symbol:
        return None
    key = symbol.strip().upper()
    data = load_token_cache()
    hit = (data.get("tokens") or {}).get(key)
    if not hit:
        return None
    if not hit.get("address"):
        return None
    return hit


def set_cached_token(
    symbol: str,
    *,
    address: str,
    chain: str = "",
    pair_address: str = "",
    name: str = "",
    price_usd: Optional[float] = None,
) -> None:
    if not symbol or not address:
        return
    key = symbol.strip().upper()
    data = load_token_cache()
    tokens = data.get("tokens") or {}
    prev = tokens.get(key) or {}
    tokens[key] = {
        "address": address,
        "chain": chain or prev.get("chain") or "",
        "pair_address": pair_address or prev.get("pair_address") or "",
        "name": name or prev.get("name") or "",
        "price_usd": price_usd if price_usd is not None else prev.get("price_usd"),
        "updated_at": _now_iso(),
    }
    save_token_cache(tokens)


def diff_with_previous(
    current: Dict[str, Dict[str, Any]],
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prev_full = previous if previous is not None else load_last_scan()
    prev = (prev_full or {}).get("tickers") or {}

    new_list: List[str] = []
    improved: List[str] = []
    declined: List[str] = []
    upgraded: List[str] = []
    dropped: List[str] = []
    unchanged_hot: List[str] = []
    deltas: Dict[str, int] = {}

    for t, info in current.items():
        score = int(info.get("score") or 0)
        cat = info.get("category") or "SKIP"
        old = prev.get(t) or prev.get(str(t).upper()) or {}
        old_score = int(old.get("score") or 0)
        old_cat = old.get("category") or ""

        if old:
            delta = score - old_score
            if delta != 0:
                deltas[t] = delta

        if not old:
            if cat in ("HOT", "QUALIFIED", "WATCH"):
                new_list.append(t)
            continue

        if CAT_RANK.get(cat, 0) > CAT_RANK.get(old_cat, 0) and cat in ("HOT", "QUALIFIED", "WATCH"):
            upgraded.append(t)

        if score - old_score >= 8 and cat in ("HOT", "QUALIFIED", "WATCH"):
            if t not in improved:
                improved.append(t)
        elif old_score - score >= 8:
            declined.append(t)

        if cat in ("HOT", "QUALIFIED") and old_cat in ("HOT", "QUALIFIED") and abs(score - old_score) < 8:
            unchanged_hot.append(t)

    for t, old in prev.items():
        old_cat = old.get("category") or ""
        if old_cat in ("HOT", "QUALIFIED") and t not in current:
            if t not in dropped:
                dropped.append(t)
        elif old_cat in ("HOT", "QUALIFIED"):
            cur = current.get(t) or {}
            if (cur.get("category") or "SKIP") not in ("HOT", "QUALIFIED", "WATCH"):
                if t not in dropped:
                    dropped.append(t)

    return {
        "new": new_list,
        "improved": improved,
        "declined": declined,
        "upgraded": upgraded,
        "dropped": dropped,
        "unchanged_hot": unchanged_hot,
        "deltas": deltas,
        "prev_updated_at": (prev_full or {}).get("updated_at"),
    }
