import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Nav from "../components/Nav.jsx";
import { fetchRecommendation, fetchRoutes, searchQuotes } from "../api.js";

function fmt(n) {
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export default function Results() {
  const [params] = useSearchParams();
  const origin = (params.get("origin") || "GRU").toUpperCase();
  const dest = (params.get("dest") || "SSA").toUpperCase();
  const date = params.get("date") || "";
  const [quotes, setQuotes] = useState(null);
  const [rec, setRec] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancel = false;
    setError("");
    Promise.all([
      searchQuotes(origin, dest, date),
      fetchRecommendation(`${origin}_${dest}`).catch(() => null),
      fetchRoutes(),
    ])
      .then(([q, r, list]) => {
        if (cancel) return;
        setQuotes(q);
        setRec(r);
        setRoutes(list);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      });
    return () => {
      cancel = true;
    };
  }, [origin, dest, date]);

  const ranked = useMemo(() => {
    if (!quotes) return [];
    const actionOrder = { COMPRAR: 0, MONITORAR: 1, AGUARDAR: 2 };
    const action = rec?.action || "MONITORAR";
    return [...quotes.quotes].sort((a, b) => {
      const byStops = a.stops - b.stops;
      if (byStops) return byStops;
      return a.price_brl - b.price_brl || actionOrder[action];
    });
  }, [quotes, rec]);

  return (
    <>
      <Nav light />
      <main className="page">
        <p className="kicker">Resultado</p>
        <h1>
          {origin} → {dest}
        </h1>
        {rec ? (
          <p className="muted">
            <span className={`action ${rec.action}`}>{rec.action}</span>
            {" · "}
            variação prevista {(rec.predicted_change_pct * 100).toFixed(1)}% · média histórica{" "}
            {fmt(rec.hist_avg_brl)}
          </p>
        ) : (
          <p className="muted">Sem recomendação Gold para este trecho. Cotações abaixo, se houver.</p>
        )}
        {error && <p className="status">API indisponível ({error}). Suba o FastAPI na porta 8000.</p>}
        {!quotes && !error && <p className="status">Carregando…</p>}
        {quotes && ranked.length === 0 && <p className="status">Nenhuma cotação nesta data nas amostras Gold.</p>}
        <div className="flight-list">
          {ranked.map((q) => (
            <Link key={q.quote_id} className="flight-row" to={`/rota/${q.route_id}`}>
              <span className="chip">{q.airline_iata}</span>
              <span>
                {q.stops === 0 ? "Direto" : `${q.stops} escala(s)`} · {q.duration_min} min · lead {q.lead_days}d
              </span>
              <span className={`action ${rec?.action || "MONITORAR"}`}>{rec?.action || "—"}</span>
              <span className="price">{fmt(q.price_brl)}</span>
            </Link>
          ))}
        </div>
        {routes.length > 0 && ranked.length === 0 && (
          <p className="muted" style={{ marginTop: "2rem" }}>
            Rotas com sinal no MVP:{" "}
            {routes.map((r) => (
              <Link key={r.route_id} to={`/rota/${r.route_id}`} style={{ marginRight: "0.8rem" }}>
                {r.origin}→{r.destination}
              </Link>
            ))}
          </p>
        )}
      </main>
    </>
  );
}
