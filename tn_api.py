import os
import requests
from typing import Any, Dict, List

TN_API_BASE = "https://api.tiendanube.com/v1"
TN_TOKEN_URL = "https://www.tiendanube.com/apps/authorize/token"  # :contentReference[oaicite:4]{index=4}

def tn_headers(access_token: str) -> Dict[str, str]:
    ua = os.environ.get("TN_USER_AGENT", "SplitPay (dev@example.com)")
    return {
        "Authentication": f"bearer {access_token}",
        "User-Agent": ua,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def exchange_code_for_token(code: str, client_id: str, client_secret: str) -> Dict[str, Any]:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
    }
    r = requests.post(TN_TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    return r.json()

def get_products(store_id: str, access_token: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
    url = f"{TN_API_BASE}/{store_id}/products?page={page}&per_page={per_page}"
    r = requests.get(url, headers=tn_headers(access_token), timeout=30)
    r.raise_for_status()
    return r.json()

def get_categories(store_id: str, access_token: str) -> List[Dict[str, Any]]:
    url = f"{TN_API_BASE}/{store_id}/categories"
    r = requests.get(url, headers=tn_headers(access_token), timeout=30)
    r.raise_for_status()
    return r.json()

def create_order(store_id: str, access_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{TN_API_BASE}/{store_id}/orders"
    r = requests.post(url, headers=tn_headers(access_token), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()
