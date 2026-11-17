// Customer: pick a product and a table, place the order (POST /api/orders).
import { FormEvent, useEffect, useState } from "react";
import { getJson, localTime, postJson } from "../api/http";
import type { Catalog, Order, OrderCreate } from "../types";

export default function CustomerPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [product, setProduct] = useState<string | null>(null);
  const [table, setTable] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placed, setPlaced] = useState<Order | null>(null);

  useEffect(() => {
    getJson<Catalog>("/catalog").then(setCatalog).catch((e: Error) => setError(e.message));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!product || table === null) return;
    setSending(true);
    setError(null);
    const body: OrderCreate = { product_code: product, table_number: table, customer_name: name, notes };
    try {
      setPlaced(await postJson<Order>("/orders", body));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  function reset() {
    setPlaced(null);
    setProduct(null);
    setTable(null);
    setName("");
    setNotes("");
  }

  if (placed) {
    const productName = catalog?.products.find((p) => p.code === placed.product_code)?.name;
    return (
      <main>
        <div className="card">
          <p className="sub" style={{ marginBottom: 4 }}>Order received</p>
          <div className="folio">{placed.folio}</div>
          <table className="kv" style={{ margin: "16px 0 24px" }}>
            <tbody>
              <tr><td>Product</td><td>{placed.product_code} · {productName}</td></tr>
              <tr><td>Table</td><td>{placed.table_number}</td></tr>
              {placed.customer_name && <tr><td>Name</td><td>{placed.customer_name}</td></tr>}
              <tr><td>Status</td><td>{placed.status}</td></tr>
              <tr><td>Ordered at</td><td>{localTime(placed.created_at)}</td></tr>
            </tbody>
          </table>
          <button className="primary" onClick={reset}>Place another order</button>
        </div>
      </main>
    );
  }

  return (
    <main>
      <h1>Order your coffee</h1>
      <p className="sub">Choose a drink and your table. The robot brings it to you.</p>

      {!catalog && !error && <p>Loading menu…</p>}

      {catalog && (
        <form onSubmit={submit}>
          <fieldset>
            <legend>Drink</legend>
            <div className="choices">
              {catalog.products.map((p) => (
                <button type="button" key={p.code} className="choice"
                        aria-pressed={product === p.code} onClick={() => setProduct(p.code)}>
                  {p.name}<small>{p.code}</small>
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Table</legend>
            <div className="choices">
              {catalog.tables.map((t) => (
                <button type="button" key={t.number} className="choice"
                        aria-pressed={table === t.number} onClick={() => setTable(t.number)}>
                  Table {t.number}<small>{t.distance_m} m</small>
                </button>
              ))}
            </div>
          </fieldset>

          <div className="field">
            <label htmlFor="name">Name (optional)</label>
            <input id="name" type="text" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="notes">Notes (optional)</label>
            <input id="notes" type="text" maxLength={200} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <button className="primary" type="submit" disabled={!product || table === null || sending}>
            {sending ? "Sending…" : "Place order"}
          </button>
        </form>
      )}

      {error && <p className="error">{error}</p>}
    </main>
  );
}
