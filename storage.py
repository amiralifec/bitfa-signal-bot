"""
حافظه اسکن قبلی + کش قرارداد/جفت + کول‌داون دامپ
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
    payload = {
        "updated_at": _now_iso(),
        "tickers": ticker_scores,
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
    """ثبت کول‌داون بعد از دامپ/فاز نزولی."""
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
    # اگر کول‌داون قبلی طولانی‌تر است، کوتاه نکن
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
    """
    اگر تیکر در کول‌داون دامپ باشد:
      - سقف دسته = WATCH
      - سقف امتیاز = ۵۸
    مگر تأیید تازه: فاز EARLY/DEVELOPING + بوست پامپ مثبت + بدون severe_dump این اسکن.
    """
    if not result or result.get("error"):
        return result
    token = (result.get("token") or "").upper()
    if not token:
        return result

    phase = (result.get("entry_phase") or "").upper()
    pump_sum = result.get("pump_summary") or {}
    severe_now = bool(pump_sum.get("severe_dump"))

    # ثبت کول‌داون تازه
    if severe_now or phase in ("BEARISH", "EXHAUSTED"):
        reason = "severe_dump" if severe_now else f"phase_{phase.lower()}"
        try:
            mark_dump_cooldown(token, reason=reason)
        except Exception as e:
            print(f"mark_dump_cooldown: {e}")

    cd = get_active_dump_cooldown(token)
    if not cd:
        return result

    # تأیید خروج از کول‌داون
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

    # اعمال سقف
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
        warnings.insert(
            0,
            f"کول‌داون دامپ ({reason}) ~{rem}س مانده — QUALIFIED مسدود",
        )
        r["warnings"] = warnings[:8]
        r["dump_cooldown"] = cd
    else:
        r["dump_cooldown"] = cd
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
