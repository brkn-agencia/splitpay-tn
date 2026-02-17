import requests
from typing import Any, Dict

MP_PREF_URL = "https://api.mercadopago.com/checkout/preferences"

def create_preference(access_token: str, preference: Dict[str, Any]) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    r = requests.post(MP_PREF_URL, headers=headers, json=preference, timeout=30)
    r.raise_for_status()
    return r.json()

def get_payment(access_token: str, payment_id: str) -> Dict[str, Any]:
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()
