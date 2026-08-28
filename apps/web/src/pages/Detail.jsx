import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Nav from "../components/Nav.jsx";
import { fetchRecommendation, fetchReliability, searchQuotes } from "../api.js";

function fmt(n) {
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export default function Detail() {
  const { routeId = "GRU_SSA" } = useParams();
  const [origin, dest] = routeId.split("_");
  const [rec, setRec] = useState(null);
  const [quotes, setQuotes] = useState([]);
  const [rel, setRel] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancel = false;
    Promise.all([
      fetchRecommendation(routeId),
      searchQuotes(origin, dest),
      fetchReliability({ route: routeId }),
    ])
      .then(([r, q, reliability]) => {
        if (cancel) return;
        setRec(r);
        setQuotes(q.quotes);
        setRel(reliability);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      });
    return () => {
      cancel = true;
    };
  }, [routeId, origin, dest]);

  return (
    <>
      <Nav light />
      <main className="page">
        <p className="kicker">Detalhe</p>
        <h1>
          {origin} → {dest}
          {rec ? ` · ${rec.action.toLowerCase()}` : ""}
        </h1>
        {error && <p className="status">{error}</p>}
        {rec && (
          <p className="muted">
            Preço atual {fmt(rec.current_price_brl)} frente à média {fmt(rec.hist_avg_brl)}. Variação
            prevista {(rec.predicted_change_pct * 100).toFixed(1)}%. Confiança do modelo{" "}
            {Math.round(rec.model_confidence * 100)}%.
          </p>
        )}
        <div className="metrics">
          {rel.map((row) => (
            <p key={`${row.airline_iata}-${row.route_id}`}>
              {row.airline_iata} · atraso {(row.delay_rate * 100).toFixed(1)}% · cancelamento{" "}
              {(row.cancel_rate * 100).toFixed(1)}% · rank {row.reliability_rank} · n={row.sample_flights}
            </p>
          ))}
          {rel.length === 0 && !error && rec && (
            <p className="muted">Sem recorte ANAC por rota nesta amostra; veja ranking nacional no método.</p>
          )}
        </div>
        <div className="flight-list">
          {quotes.map((q) => (
            <div className="flight-row" key={q.quote_id}>
              <span>{q.airline_iata}</span>
              <span>
                {q.departure_at.slice(0, 16).replace("T", " ")} · {q.stops} parada(s)
              </span>
              <span className={`action ${rec?.action || ""}`}>{rec?.action}</span>
              <span className="price">{fmt(q.price_brl)}</span>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}
