import os, json, uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from db import init_db, get_db
from tn_api import exchange_code_for_token, create_order
from mp_api import create_preference, get_payment

load_dotenv()

app = FastAPI(title="SplitPay MVP")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
TN_CLIENT_ID = os.environ.get("TN_CLIENT_ID", "")
TN_CLIENT_SECRET = os.environ.get("TN_CLIENT_SECRET", "")
MP_ACCESS_TOKEN_DEFAULT = os.environ.get("MP_ACCESS_TOKEN_DEFAULT", "")
APP_ADMIN_KEY = os.environ.get("APP_ADMIN_KEY", "BRKN2026")

@app.on_event("startup")
def _startup():
    init_db()

def _require_admin(admin_key: str):
    if admin_key != APP_ADMIN_KEY:
        raise HTTPException(status_code=401, detail="admin_key inválida")

def _get_store_by_tn_store_id(tn_store_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as db:
        row = db.execute("SELECT * FROM stores WHERE tn_store_id = ?", (tn_store_id,)).fetchone()
        return dict(row) if row else None

def _get_store_by_internal_id(store_id: int) -> Dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
        if not row:
            raise HTTPException(404, "store no encontrada")
        return dict(row)

def _get_active_rules(store_id: int) -> List[Dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM rules WHERE store_id = ? AND active = 1",
            (store_id,),
        ).fetchall()
        return [dict(r) for r in rows]

def _pick_rule_for_item(active_rules: List[Dict[str, Any]], item: Dict[str, Any]) -> int:
    # Prioridad: product > category > global
    product_id = str(item.get("product_id") or "")
    category_id = str(item.get("category_id") or "")

    for r in active_rules:
        if r["scope"] == "product" and (r["reference_id"] or "") == product_id:
            return int(r["max_installments"])

    for r in active_rules:
        if r["scope"] == "category" and (r["reference_id"] or "") == category_id:
            return int(r["max_installments"])

    for r in active_rules:
        if r["scope"] == "global":
            return int(r["max_installments"])

    return 6

def _group_key(max_installments: int) -> str:
    if max_installments >= 12:
        return "group_12"
    if max_installments >= 6:
        return "group_6"
    return "group_0"

def _build_groups(items: List[Dict[str, Any]], rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups = {
        "group_12": {"max_installments": 12, "items": [], "subtotal": 0},
        "group_6": {"max_installments": 6, "items": [], "subtotal": 0},
        "group_0": {"max_installments": 0, "items": [], "subtotal": 0},
    }
    for it in items:
        max_inst = _pick_rule_for_item(rules, it)
        gk = _group_key(max_inst)
        groups[gk]["items"].append(it)
        price = int(it.get("price", 0))
        qty = int(it.get("quantity", 1))
        groups[gk]["subtotal"] += price * qty
    return groups

def _shipping_cost_from_method(method: str) -> int:
    return 0 if method == "retiro" else 2500 if method == "estandar" else 4500 if method == "express" else 0

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "admin_key": APP_ADMIN_KEY})

# ----------------- OAuth Tiendanube -----------------
@app.get("/tn/install")
def tn_install():
    if not TN_CLIENT_ID:
        return PlainTextResponse("Falta TN_CLIENT_ID", status_code=500)

    redirect_uri = f"{APP_BASE_URL}/tn/callback"
    authorize_url = (
        "https://www.tiendanube.com/apps/authorize"
        f"?client_id={TN_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code"
    )
    return RedirectResponse(authorize_url)

@app.get("/tn/callback")
def tn_callback(code: str):
    token_data = exchange_code_for_token(code, TN_CLIENT_ID, TN_CLIENT_SECRET)
    access_token = token_data.get("access_token")
    user_id = token_data.get("user_id") or token_data.get("store_id") or token_data.get("uid")
    if not access_token or not user_id:
        return JSONResponse(token_data, status_code=500)

    tn_store_id = str(user_id)
    with get_db() as db:
        db.execute(
            "INSERT INTO stores (tn_store_id, tn_access_token, mp_access_token) VALUES (?,?,?) "
            "ON CONFLICT(tn_store_id) DO UPDATE SET tn_access_token=excluded.tn_access_token",
            (tn_store_id, access_token, None),
        )
    return RedirectResponse(f"/dashboard?admin_key={APP_ADMIN_KEY}")

# ----------------- Dashboard -----------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, admin_key: str):
    _require_admin(admin_key)
    with get_db() as db:
        stores = [dict(s) for s in db.execute("SELECT * FROM stores ORDER BY id DESC").fetchall()]
    return templates.TemplateResponse("dashboard.html", {"request": request, "stores": stores, "admin_key": admin_key})

@app.post("/dashboard/store/save")
def dashboard_store_save(
    admin_key: str,
    tn_store_id: str = Form(...),
    tn_access_token: str = Form(...),
    mp_access_token: str = Form(None),
):
    _require_admin(admin_key)
    with get_db() as db:
        db.execute(
            "INSERT INTO stores (tn_store_id, tn_access_token, mp_access_token) VALUES (?,?,?) "
            "ON CONFLICT(tn_store_id) DO UPDATE SET tn_access_token=excluded.tn_access_token, mp_access_token=excluded.mp_access_token",
            (tn_store_id, tn_access_token, mp_access_token),
        )
    return RedirectResponse(f"/dashboard?admin_key={admin_key}", status_code=303)

@app.get("/dashboard/{tn_store_id}/rules", response_class=HTMLResponse)
def dashboard_rules(request: Request, tn_store_id: str, admin_key: str):
    _require_admin(admin_key)
    store = _get_store_by_tn_store_id(tn_store_id)
    if not store:
        raise HTTPException(404, "store no encontrada")
    with get_db() as db:
        rules = [dict(r) for r in db.execute("SELECT * FROM rules WHERE store_id=? ORDER BY id DESC", (store["id"],)).fetchall()]
    return templates.TemplateResponse("rules.html", {"request": request, "tn_store_id": tn_store_id, "rules": rules, "admin_key": admin_key})

@app.post("/dashboard/{tn_store_id}/rules/add")
def dashboard_rules_add(
    tn_store_id: str,
    admin_key: str,
    scope: str = Form(...),
    reference_id: str = Form(""),
    max_installments: int = Form(...),
):
    _require_admin(admin_key)
    store = _get_store_by_tn_store_id(tn_store_id)
    if not store:
        raise HTTPException(404, "store no encontrada")
    reference_id = reference_id.strip() or None
    with get_db() as db:
        db.execute(
            "INSERT INTO rules (store_id, scope, reference_id, max_installments, active) VALUES (?,?,?,?,1)",
            (store["id"], scope, reference_id, int(max_installments)),
        )
    return RedirectResponse(f"/dashboard/{tn_store_id}/rules?admin_key={admin_key}", status_code=303)

@app.post("/dashboard/{tn_store_id}/rules/toggle/{rule_id}")
def dashboard_rules_toggle(tn_store_id: str, rule_id: int, admin_key: str):
    _require_admin(admin_key)
    store = _get_store_by_tn_store_id(tn_store_id)
    if not store:
        raise HTTPException(404, "store no encontrada")
    with get_db() as db:
        row = db.execute("SELECT active FROM rules WHERE id=? AND store_id=?", (rule_id, store["id"])).fetchone()
        if not row:
            raise HTTPException(404, "rule no encontrada")
        new_val = 0 if int(row["active"]) == 1 else 1
        db.execute("UPDATE rules SET active=? WHERE id=? AND store_id=?", (new_val, rule_id, store["id"]))
    return RedirectResponse(f"/dashboard/{tn_store_id}/rules?admin_key={admin_key}", status_code=303)

# ----------------- Split (comprador) -----------------
@app.post("/split/create")
async def split_create(payload: Dict[str, Any]):
    tn_store_id = str(payload.get("tn_store_id") or "")
    items = payload.get("items") or []
    buyer_email = payload.get("buyer_email") or ""

    if not tn_store_id or not isinstance(items, list) or len(items) == 0:
        raise HTTPException(400, "Faltan tn_store_id o items")

    store = _get_store_by_tn_store_id(tn_store_id)
    if not store:
        raise HTTPException(404, "Store no instalada")

    rules = _get_active_rules(store["id"])
    groups = _build_groups(items, rules)

    split_id = str(uuid.uuid4())
    with get_db() as db:
        db.execute(
            "INSERT INTO splits (id, store_id, buyer_email, status, shipping_method, shipping_cost, shipping_paid_in_group, cart_json, groups_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (split_id, store["id"], buyer_email, "created", None, 0, None, json.dumps(items, ensure_ascii=False), json.dumps(groups, ensure_ascii=False)),
        )
    return {"split_id": split_id}

@app.get("/split/{split_id}", response_class=HTMLResponse)
def split_view(request: Request, split_id: str):
    with get_db() as db:
        s = db.execute("SELECT * FROM splits WHERE id=?", (split_id,)).fetchone()
        if not s:
            raise HTTPException(404, "split no encontrado")
        payments = [dict(p) for p in db.execute("SELECT * FROM split_payments WHERE split_id=? ORDER BY id ASC", (split_id,)).fetchall()]

    s = dict(s)
    groups = json.loads(s["groups_json"])
    return templates.TemplateResponse(
        "split_checkout.html",
        {
            "request": request,
            "split_id": split_id,
            "groups": groups,
            "shipping_method": s["shipping_method"],
            "shipping_cost": s["shipping_cost"],
            "shipping_paid_in_group": s["shipping_paid_in_group"],
            "payments": payments,
        },
    )

@app.post("/split/{split_id}/shipping")
def split_set_shipping(split_id: str, shipping_method: str = Form(...), shipping_paid_in_group: str = Form(...)):
    cost = _shipping_cost_from_method(shipping_method)
    with get_db() as db:
        s = db.execute("SELECT * FROM splits WHERE id=?", (split_id,)).fetchone()
        if not s:
            raise HTTPException(404, "split no encontrado")
        db.execute(
            "UPDATE splits SET shipping_method=?, shipping_cost=?, shipping_paid_in_group=? WHERE id=?",
            (shipping_method, cost, shipping_paid_in_group, split_id),
        )
    return RedirectResponse(f"/split/{split_id}", status_code=303)

@app.get("/split/{split_id}/generate_payments")
def split_generate_payments(split_id: str):
    with get_db() as db:
        s = db.execute("SELECT * FROM splits WHERE id=?", (split_id,)).fetchone()
        if not s:
            raise HTTPException(404, "split no encontrado")
        s = dict(s)
        store = _get_store_by_internal_id(s["store_id"])
        groups = json.loads(s["groups_json"])

        mp_token = store.get("mp_access_token") or MP_ACCESS_TOKEN_DEFAULT
        if not mp_token:
            raise HTTPException(500, "Falta MP token")

        db.execute("DELETE FROM split_payments WHERE split_id=?", (split_id,))

        for group_key, g in groups.items():
            if len(g["items"]) == 0:
                continue

            max_inst = int(g["max_installments"])
            subtotal = int(g["subtotal"])

            shipping_cost = int(s["shipping_cost"] or 0)
            total = subtotal + shipping_cost if (s["shipping_paid_in_group"] == group_key) else subtotal

            # Preferencia MP: máximo de cuotas (installments) :contentReference[oaicite:5]{index=5}
            pref = {
                "items": [{"title": f"Compra {group_key} - Split {split_id}", "quantity": 1, "currency_id": "ARS", "unit_price": total}],
                "external_reference": f"{split_id}:{group_key}",
                "notification_url": f"{APP_BASE_URL}/mp/webhook",
                "payment_methods": {"installments": max_inst},
            }

            mp_resp = create_preference(mp_token, pref)
            db.execute(
                "INSERT INTO split_payments (split_id, group_key, mp_preference_id, mp_init_point, status) VALUES (?,?,?,?,?)",
                (split_id, group_key, mp_resp.get("id"), mp_resp.get("init_point"), "created"),
            )

    return RedirectResponse(f"/split/{split_id}", status_code=303)

@app.post("/mp/webhook")
async def mp_webhook(request: Request):
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    qs = dict(request.query_params)

    payment_id = qs.get("data.id") or qs.get("id") or body.get("data", {}).get("id") or body.get("id")
    if not payment_id:
        return PlainTextResponse("ok", status_code=200)

    mp_token = MP_ACCESS_TOKEN_DEFAULT
    if not mp_token:
        return PlainTextResponse("Missing MP token", status_code=200)

    pay = get_payment(mp_token, str(payment_id))
    status = pay.get("status")
    external_reference = pay.get("external_reference") or ""
    if ":" not in external_reference:
        return PlainTextResponse("ok", status_code=200)

    split_id, group_key = external_reference.split(":", 1)

    with get_db() as db:
        db.execute(
            "UPDATE split_payments SET mp_payment_id=?, status=? WHERE split_id=? AND group_key=?",
            (str(payment_id), status or "unknown", split_id, group_key),
        )

        if status == "approved":
            s = db.execute("SELECT * FROM splits WHERE id=?", (split_id,)).fetchone()
            if s:
                s = dict(s)
                store = _get_store_by_internal_id(s["store_id"])
                groups = json.loads(s["groups_json"])
                group = groups.get(group_key)
                if group and len(group["items"]) > 0:
                    _create_tn_order_for_group(store, s, group_key, group, str(payment_id))

        rows = db.execute("SELECT status FROM split_payments WHERE split_id=?", (split_id,)).fetchall()
        statuses = [r["status"] for r in rows]
        if statuses and all(st == "approved" for st in statuses):
            db.execute("UPDATE splits SET status='completed' WHERE id=?", (split_id,))

    return PlainTextResponse("ok", status_code=200)

def _create_tn_order_for_group(store: Dict[str, Any], split_row: Dict[str, Any], group_key: str, group: Dict[str, Any], mp_payment_id: str):
    tn_store_id = store["tn_store_id"]
    tn_token = store["tn_access_token"]

    shipping_cost = int(split_row.get("shipping_cost") or 0)
    shipping_paid_in_group = split_row.get("shipping_paid_in_group")
    this_shipping = shipping_cost if shipping_paid_in_group == group_key else 0

    items = []
    for it in group["items"]:
        items.append({
            "product_id": it.get("product_id"),
            "variant_id": it.get("variant_id"),
            "quantity": int(it.get("quantity", 1)),
            "price": int(it.get("price", 0)),
        })

    note = f"Split {split_row['id']} - {group_key} - MP payment_id {mp_payment_id}. "
    if this_shipping == 0 and shipping_cost > 0:
        note += f"Envío cobrado en {shipping_paid_in_group}."

    payload = {
        "note": note,
        "products": items,
        "shipping_cost": this_shipping
    }

    # En algunas tiendas el payload de order puede requerir más campos (cliente/dirección).
    # Para demo/MVP suele alcanzar, y lo ajustamos con tu tienda cuando pruebes.
    try:
        create_order(tn_store_id, tn_token, payload)
    except Exception:
        return

@app.get("/split/{split_id}/done", response_class=HTMLResponse)
def split_done(request: Request, split_id: str):
    with get_db() as db:
        s = db.execute("SELECT * FROM splits WHERE id=?", (split_id,)).fetchone()
        if not s:
            raise HTTPException(404, "split no encontrado")
        payments = [dict(p) for p in db.execute("SELECT * FROM split_payments WHERE split_id=? ORDER BY id ASC", (split_id,)).fetchall()]

    s = dict(s)
    return templates.TemplateResponse("split_done.html", {"request": request, "split_id": split_id, "status": s["status"], "payments": payments})
