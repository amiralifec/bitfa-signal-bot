"""
ماژول امتیازدهی ارزهای BITFA
نسخه اولیه - بر اساس داده‌های تاریخی کانال
"""

import requests
from typing import Dict, Any, Optional
import time


def get_dexscreener_data(token_address: str = None, symbol: str = None) -> Optional[Dict]:
    """
    گرفتن داده از DexScreener (رایگان و بدون کلید)
    اولویت با آدرس کانترکت است.
    """
    try:
        if token_address:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        elif symbol:
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
        else:
            return None

        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"DexScreener error: {e}")
        return None


def calculate_score(data: Dict) -> Dict[str, Any]:
    """
    محاسبه امتیاز از ۱۰۰ بر اساس فیلترهای تعریف‌شده
    این نسخه اولیه است و بعداً دقیق‌تر می‌شود.
    """
    score = 50  # پایه
    reasons = []

    # TODO: فیلترهای واقعی اینجا پیاده‌سازی می‌شوند
    # 1. امنیت
    # 2. لیکوئیدیتی و حجم
    # 3. مارکت‌کپ
    # 4. مومنتوم

    return {
        "score": score,
        "reasons": reasons,
        "recommendation": "در حال توسعه",
        "raw_data": data
    }


def analyze_token(symbol: str = None, address: str = None) -> Dict[str, Any]:
    """
    تابع اصلی تحلیل یک ارز
    """
    data = get_dexscreener_data(token_address=address, symbol=symbol)
    if not data:
        return {"error": "داده پیدا نشد", "score": 0}

    result = calculate_score(data)
    return result


if __name__ == "__main__":
    # تست ساده
    print(analyze_token(symbol="BTC"))
