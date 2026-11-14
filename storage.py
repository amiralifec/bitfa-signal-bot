"""
حافظه ساده اسکن‌های قبلی — فایل JSON روی دیسک
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

STORE_PATH = os.getenv("SCAN_STORE_PATH", "last_scan.json")


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
    """
    ticker_scores: { "FOOD": {"score": 76, "category": "QUALIFIED", "token": "FOOD"}, ... }
    """
    try:
        payload = {
            "updated_at": _now_iso(),
            "tickers": ticker_scores,
        }
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"save_last_scan error: {e}")


def diff_with_previous(
    current: Dict[str, Dict[str, Any]],
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    خروجی:
      new: تیکرهایی که قبلاً نبودند
      improved: امتیازشان حداقل +8 شده
      dropped: قبلاً HOT/QUALIFIED بودند و الان نیستند
      unchanged_hot: همان‌های خوب تکراری
    """
    prev = (previous or load_last_scan()).get("tickers") or {}
    new_list: List[str] = []
    improved: List[str] = []
    dropped: List[str] = []
    unchanged_hot: List[str] = []

    for t, info in current.items():
        score = int(info.get("score") or 0)
        cat = info.get("category") or "SKIP"
        old = prev.get(t) or prev.get(t.upper()) or {}
        old_score = int(old.get("score") or 0)
        old_cat = old.get("category") or ""

        if not old:
            if cat in ("HOT", "QUALIFIED", "WATCH"):
                new_list.append(t)
        elif score - old_score >= 8 and cat in ("HOT", "QUALIFIED", "WATCH"):
            improved.append(t)
        elif cat in ("HOT", "QUALIFIED") and old_cat in ("HOT", "QUALIFIED"):
            unchanged_hot.append(t)

    for t, old in prev.items():
        old_cat = old.get("category") or ""
        if old_cat in ("HOT", "QUALIFIED") and t not in current:
            dropped.append(t)
        elif old_cat in ("HOT", "QUALIFIED"):
            cur = current.get(t) or {}
            if (cur.get("category") or "SKIP") not in ("HOT", "QUALIFIED", "WATCH"):
                if t not in dropped:
                    dropped.append(t)

    return {
        "new": new_list,
        "improved": improved,
        "dropped": dropped,
        "unchanged_hot": unchanged_hot,
        "prev_updated_at": (previous or load_last_scan()).get("updated_at"),
    }
