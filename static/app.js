// MVP: este archivo lo vas a adaptar al tema del carrito.
// Debe armar items con este formato:
// [{product_id, variant_id, name, quantity, price, category_id, sku}]

async function sendCartToSplitPay(appBaseUrl, tnStoreId) {
  const items = await getCartItemsFallback();
  if (!items || items.length === 0) {
    alert("No pude leer el carrito. Hay que adaptar getCartItemsFallback() al tema.");
    return;
  }

  const payload = { tn_store_id: tnStoreId, buyer_email: "", items };

  const res = await fetch(`${appBaseUrl}/split/create`, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const txt = await res.text();
    alert("Error creando split: " + txt);
    return;
  }

  const data = await res.json();
  window.location.href = `${appBaseUrl}/split/${data.split_id}`;
}

async function getCartItemsFallback() {
  // Opción fácil: vos definís window.__CART__ desde tu tema.
  if (window.__CART__ && Array.isArray(window.__CART__.items)) {
    return window.__CART__.items;
  }
  return [];
}
