"""
حافظه اسکن قبلی + کش قرارداد/جفت + کول‌داون دامپ + streak + رژیم BTC
پایداری اختیاری روی GitHub Gist

Env:
  PERSIST_GIST_ID
  GITHUB_TOKEN / PERSIST_GITHUB_TOKEN
  DUMP_COOLDOWN_HOURS (پیش‌فرض ۶)
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

try:
    import requests
except Exception:
    requests = None

STORE_PATH = os.getenv("SCAN_STORE_PATH", "last_scan.json")
TOKEN_CACHE_PATH = os.getenv("TOKEN_CACHE_PATH", "token_cache.json")
DUMP_PATH = os.getenv("DUMP_COOLDOWN_PATH", "dump_cooldowns.json")
GIST_ID = (os.getenv("PERSIST_GIST_ID") or "").strip()
GITHUB_TOKEN = (os.getenv("PERSIST_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
GIST_FILENAME = os.getenv("PERSIST_GIST_FILE", "bitfa_state.json")
DUMP_COOLDOWN_HOURS = float(os.getenv("DUMP_COOLDOWN_HOURS") or "6")

CAT_RANK = {"SKIP": 0, "WATCH": 1, "QUALIFIED": 2, "HOT": 3}

_gist_loaded = False
_btc_cache: Dict[str, Any] = {"ts": 0.0, "change_24h": None, "price": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _gist_enabled() -> bool:
    return bool(GIST_ID and GITHUB_TOKEN and requests is not None)


def _gist_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _read_local(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not os.path.exists(path):
            return dict(default)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(default)
        return data
    except Exception as e:
        print(f"read_local {path}: {e}")
        return dict(default)


def _write_local(path: str, payload: Dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"write_local {path}: {e}")


def _fetch_gist_state() -> Optional[Dict[str, Any]]:
    if not _gist_enabled():
        return None
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gist_headers(),
            timeout=12,
        )
        if r.status_code != 200:
            print(f"gist fetch status {r.status_code}")
            return None
        files = (r.json() or {}).get("files") or {}
        node = files.get(GIST_FILENAME) or next(iter(files.values()), None)
        if not node:
            return None
        raw = node.get("content")
        if not raw and node.get("raw_url"):
            rr = requests.get(node["raw_url"], timeout=12)
            if rr.status_code == 200:
                raw = rr.text
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        print(f"gist fetch error: {e}")
        return None


def _push_gist_state(state: Dict[str, Any]) -> None:
    if not _gist_enabled():
        return
    try:
        body = {
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps(state, ensure_ascii=False, indent=2),
                }
            }
        }
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gist_headers(),
            json=body,
            timeout=15,
        )
        if r.status_code not in (200, 201):
            print(f"gist push status {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"gist push error: {e}")


def _ensure_remote_hydrated() -> None:
    global _gist_loaded
    if _gist_loaded or not _gist_enabled():
        return
    _gist_loaded = True
    remote = _fetch_gist_state()
    if not remote:
        return
    local_scan = _read_local(STORE_PATH, {"tickers": {}, "updated_at": None})
    local_tok = _read_local(TOKEN_CACHE_PATH, {"tokens": {}, "updated_at": None})
    local_dump = _read_local(DUMP_PATH, {"items": {}, "updated_at": None})
    remote_scan = remote.get("last_scan") or {}
    remote_tok = remote.get("token_cache") or {}
    remote_dump = remote.get("dump_cooldowns") or {}
    if not (local_scan.get("tickers") or {}) and (remote_scan.get("tickers") or {}):
        _write_local(STORE_PATH, remote_scan)
        print("hydrated last_scan from gist")
    if not (local_tok.get("tokens") or {}) and (remote_tok.get("tokens") or {}):
        _write_local(TOKEN_CACHE_PATH, remote_tok)
        print("hydrated token_cache from gist")
    if not (local_dump.get("items") or {}) and (remote_dump.get("items") or {}):
        _write_local(DUMP_PATH, remote_dump)
        print("hydrated dump_cooldowns from gist")


def _sync_out() -> None:
    if not _gist_enabled():
        return
    state = {
        "updated_at": _now_iso(),
        "last_scan": _read_local(STORE_PATH, {"tickers": {}, "updated_at": None}),
        "token_cache": _read_local(TOKEN_CACHE_PATH, {"tokens": {}, "updated_at": None}),
        "dump_cooldowns": _read_local(DUMP_PATH, {"items": {}, "updated_at": None}),
    }
    _push_gist_state(state)


def load_last_scan() -> Dict[str, Any]:
    _ensure_remote_hydrated()
    data = _read_local(STORE_PATH, {"tickers": {}, "updated_at": None})
    data.setdefault("tickers", {})
    return data


def save_last_scan(ticker_scores: Dict[str, Dict[str, Any]]) -> None:
    prev = _read_local(STORE_PATH, {"tickers": {}, "updated_at": None})
    prev_t = (prev or {}).get("tickers") or {}
    enriched: Dict[str, Dict[str, Any]] = {}
    for t, info in (ticker_scores or {}).items():
        row = dict(info or {})
        score = int(row.get("score") or 0)
        old = prev_t.get(t) or prev_t.get(str(t).upper()) or {}
        old_score = int(old.get("score") or 0)
        old_streak = int(old.get("streak") or 0)
        if old and score - old_score >= 5:
            streak = (old_streak + 1) if old_streak > 0 else 1
        elif old and old_score - score >= 5:
            streak = (old_streak - 1) if old_streak < 0 else -1
        elif old:
            streak = 0
        else:
            streak = 0
        row["streak"] = streak
        row["prev_score"] = old_score if old else None
        enriched[t] = row
    payload = {
        "updated_at": _now_iso(),
        "tickers": enriched,
    }
    _write_local(STORE_PATH, payload)
    _sync_out()


def load_token_cache() -> Dict[str, Any]:
    _ensure_remote_hydrated()
    data = _read_local(TOKEN_CACHE_PATH, {"tokens": {}, "updated_at": None})
    data.setdefault("tokens", {})
    return data


def save_token_cache(tokens: Dict[str, Dict[str, Any]]) -> None:
    payload = {"updated_at": _now_iso(), "tokens": tokens}
    _write_local(TOKEN_CACHE_PATH, payload)
    _sync_out()


def get_cached_token(symbol: str) -> Optional[Dict[str, Any]]:
    if not symbol:
        return None
    key = symbol.strip().upper()
    data = load_token_cache()
    hit = (data.get("tokens") or {}).get(key)
    if not hit or not hit.get("address"):
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


def mark_dump_cooldown(
    ticker: str,
    *,
    reason: str = "severe_dump",
    hours: Optional[float] = None,
) -> None:
    if not ticker:
        return
    key = ticker.strip().upper()
    if key.endswith("USDT"):
        key = key[:-4]
    hrs = float(hours if hours is not None else DUMP_COOLDOWN_HOURS)
    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=hrs)
    _ensure_remote_hydrated()
    data = _read_local(DUMP_PATH, {"items": {}, "updated_at": None})
    items = data.get("items") or {}
    prev = items.get(key) or {}
    prev_until = _parse_iso(prev.get("until") or "")
    if prev_until and prev_until > until:
        until = prev_until
    items[key] = {
        "until": until.isoformat(),
        "set_at": _now_iso(),
        "reason": reason,
        "hours": hrs,
    }
    _write_local(DUMP_PATH, {"items": items, "updated_at": _now_iso()})
    _sync_out()


def get_active_dump_cooldown(ticker: str) -> Optional[Dict[str, Any]]:
    if not ticker:
        return None
    key = ticker.strip().upper()
    if key.endswith("USDT"):
        key = key[:-4]
    _ensure_remote_hydrated()
    data = _read_local(DUMP_PATH, {"items": {}, "updated_at": None})
    hit = (data.get("items") or {}).get(key)
    if not hit:
        return None
    until = _parse_iso(hit.get("until") or "")
    if not until:
        return None
    now = datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if now >= until:
        return None
    remaining_h = (until - now).total_seconds() / 3600.0
    out = dict(hit)
    out["remaining_hours"] = round(remaining_h, 2)
    return out


def clear_dump_cooldown(ticker: str) -> None:
    if not ticker:
        return
    key = ticker.strip().upper()
    if key.endswith("USDT"):
        key = key[:-4]
    data = _read_local(DUMP_PATH, {"items": {}, "updated_at": None})
    items = data.get("items") or {}
    if key in items:
        del items[key]
        _write_local(DUMP_PATH, {"items": items, "updated_at": _now_iso()})
        _sync_out()


def apply_dump_cooldown_guard(result: dict) -> dict:
    if not result or result.get("error"):
        return result
    token = (result.get("token") or "").upper()
    if not token:
        return result

    phase = (result.get("entry_phase") or "").upper()
    pump_sum = result.get("pump_summary") or {}
    severe_now = bool(pump_sum.get("severe_dump"))

    if severe_now or phase in ("BEARISH", "EXHAUSTED"):
        reason = "severe_dump" if severe_now else f"phase_{phase.lower()}"
        try:
            mark_dump_cooldown(token, reason=reason)
        except Exception as e:
            print(f"mark_dump_cooldown: {e}")

    cd = get_active_dump_cooldown(token)
    if not cd:
        return result

    pump_boost = int(result.get("pump_boost") or 0)
    confirmed = (
        phase in ("EARLY", "DEVELOPING")
        and pump_boost >= 3
        and not severe_now
        and pump_sum.get("latest_direction") == "UP"
    )
    if confirmed:
        try:
            clear_dump_cooldown(token)
        except Exception as e:
            print(f"clear_dump_cooldown: {e}")
        r = dict(result)
        warnings = list(r.get("warnings") or [])
        warnings.insert(0, "کول‌داون دامپ با تأیید UP تازه پاک شد")
        r["warnings"] = warnings[:8]
        r["dump_cooldown_cleared"] = True
        return r

    r = dict(result)
    score = int(r.get("score") or 0)
    cat = r.get("category") or "SKIP"
    if cat in ("HOT", "QUALIFIED") or score >= 65:
        score = min(score, 58)
        r["score"] = score
        r["category"] = "WATCH"
        r["recommendation"] = "کول‌داون دامپ فعال — فقط نظارت تا تأیید ساختار تازه"
        r["action"] = "نظارت"
        warnings = list(r.get("warnings") or [])
        rem = cd.get("remaining_hours")
        reason = cd.get("reason") or "dump"
        warnings.insert(0, f"کول‌داون دامپ ({reason}) ~{rem}س مانده — QUALIFIED مسدود")
        r["warnings"] = warnings[:8]
        r["dump_cooldown"] = cd
    else:
        r["dump_cooldown"] = cd
    return r


def get_btc_regime() -> Dict[str, Any]:
    import time
    now = time.time()
    if _btc_cache.get("ts") and now - float(_btc_cache["ts"]) < 600 and _btc_cache.get("change_24h") is not None:
        return {
            "change_24h": _btc_cache["change_24h"],
            "price": _btc_cache.get("price"),
            "regime": _btc_cache.get("regime") or "neutral",
            "cached": True,
        }
    ch = None
    price = None
    try:
        if requests is not None:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd", "include_24hr_change": "true"},
                timeout=10,
            )
            if r.status_code == 200:
                node = (r.json() or {}).get("bitcoin") or {}
                ch = node.get("usd_24h_change")
                price = node.get("usd")
                if ch is not None:
                    ch = float(ch)
                if price is not None:
                    price = float(price)
    except Exception as e:
        print(f"btc regime fetch: {e}")
    if ch is None:
        return {"change_24h": None, "price": None, "regime": "unknown", "cached": False}
    if ch <= -3.0:
        regime = "risk_off"
    elif ch >= 3.0:
        regime = "risk_on"
    else:
        regime = "neutral"
    _btc_cache["ts"] = now
    _btc_cache["change_24h"] = ch
    _btc_cache["price"] = price
    _btc_cache["regime"] = regime
    return {"change_24h": ch, "price": price, "regime": regime, "cached": False}


def apply_btc_regime_guard(result: dict, btc: Optional[Dict[str, Any]] = None) -> dict:
    if not result or result.get("error"):
        return result
    kind = str(result.get("asset_kind") or "crypto")
    if kind.startswith("stock"):
        return result
    if btc is None:
        btc = get_btc_regime()
    ch = btc.get("change_24h")
    regime = btc.get("regime") or "unknown"
    if ch is None or regime != "risk_off":
        r = dict(result)
        r["btc_regime"] = regime
        r["btc_change_24h"] = ch
        return r

    r = dict(result)
    r["btc_regime"] = regime
    r["btc_change_24h"] = ch
    phase = (r.get("entry_phase") or "").upper()
    if phase == "DEVELOPING" and int(r.get("pump_boost") or 0) >= 4:
        warnings = list(r.get("warnings") or [])
        warnings.append(f"BTC {ch:.1f}% (risk-off) ولی DEVELOPING قوی — فیلتر نرم")
        r["warnings"] = warnings[:8]
        return r

    score = int(r.get("score") or 0)
    cat = r.get("category") or "SKIP"
    changed = False
    if cat == "HOT":
        score = min(score, 74)
        cat = "QUALIFIED"
        r["recommendation"] = "رژیم BTC منفی — از HOT به QUALIFIED محدود شد"
        r["action"] = "بررسی برای ورود"
        changed = True
    elif cat == "QUALIFIED":
        score = min(score, 58)
        cat = "WATCH"
        r["recommendation"] = "رژیم BTC منفی (risk-off) — فقط نظارت"
        r["action"] = "نظارت"
        changed = True
    if changed:
        r["score"] = score
        r["category"] = cat
        warnings = list(r.get("warnings") or [])
        warnings.insert(0, f"رژیم BTC: risk-off ({ch:.1f}% در ۲۴س) — سقف دسته محدود شد")
        r["warnings"] = warnings[:8]
    return r


def apply_streak_boost(result: dict, previous_scan: Optional[Dict[str, Any]] = None) -> dict:
    if not result or result.get("error"):
        return result
    token = (result.get("token") or "").upper()
    if not token:
        return result
    prev_full = previous_scan if previous_scan is not None else load_last_scan()
    prev = (prev_full or {}).get("tickers") or {}
    old = prev.get(token) or {}
    old_streak = int(old.get("streak") or 0)
    old_score = int(old.get("score") or 0)
    cur_score = int(result.get("score") or 0)

    if old:
        if cur_score - old_score >= 5:
            streak = (old_streak + 1) if old_streak > 0 else 1
        elif old_score - cur_score >= 5:
            streak = (old_streak - 1) if old_streak < 0 else -1
        else:
            streak = 0
    else:
        streak = 0

    r = dict(result)
    r["streak"] = streak
    if streak >= 2:
        new_score = min(100, cur_score + 3)
        r["score"] = new_score
        reasons = list(r.get("reasons") or [])
        reasons.insert(0, f"بهبود متوالی {streak} اسکن (MomentumConfirmed)")
        r["reasons"] = reasons[:10]
        conf = int(r.get("confidence") or 0)
        r["confidence"] = min(100, conf + 5)
        if new_score >= 80 and int(r.get("confidence") or 0) >= 70:
            r["category"], r["recommendation"], r["action"] = "HOT", "امتیاز عالی - قابل بررسی جدی برای ورود محدود", "اولویت بررسی"
        elif new_score >= 65:
            r["category"], r["recommendation"], r["action"] = "QUALIFIED", "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت", "بررسی برای ورود"
        elif new_score >= 48:
            r["category"], r["recommendation"], r["action"] = "WATCH", "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار", "نظارت"
    elif streak <= -2:
        new_score = max(0, cur_score - 3)
        r["score"] = new_score
        warnings = list(r.get("warnings") or [])
        warnings.insert(0, f"افت متوالی {abs(streak)} اسکن")
        r["warnings"] = warnings[:8]
        if new_score >= 65:
            r["category"], r["recommendation"], r["action"] = "QUALIFIED", "امتیاز خوب - مناسب بررسی با مدیریت ریسک سخت", "بررسی برای ورود"
        elif new_score >= 48:
            r["category"], r["recommendation"], r["action"] = "WATCH", "امتیاز متوسط - فقط نظارت و انتظار تأیید ساختار", "نظارت"
        else:
            r["category"], r["recommendation"], r["action"] = "SKIP", "امتیاز ضعیف - رد شود", "رد"
    return r


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
