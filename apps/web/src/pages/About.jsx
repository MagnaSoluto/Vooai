import { useEffect, useState } from "react";
import Nav from "../components/Nav.jsx";
import AdSlot from "../components/AdSlot.jsx";
import { fetchHealth, fetchMetrics } from "../api.js";

export default function About() {
  const [health, setHealth] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    Promise.all([
      fetchHealth().catch(() => null),
      fetchMetrics().catch(() => []),
    ]).then(([h, m]) => {
      if (cancel) return;
      setHealth(h);
      setMetrics(Array.isArray(m) ? m : []);
      setLoading(false);
    });
    return () => {
      cancel = true;
    };
  }, []);

  return (
    <>
      <Nav light />
      <main className="page about anim-fade-in-bottom">
        <p className="kicker">Método</p>
        <h1>Como o sinal é feito.</h1>
        <div className="about-grid">
          <section className="about-block">
            <h2>Cotação</h2>
            <p>
              A busca consulta ofertas ao vivo: companhia, horário, preço e trecho — na hora da
              consulta.
            </p>
          </section>
          <section className="about-block">
            <h2>Histórico</h2>
            <p>
              Cada oferta é cruzada com o histórico operacional e de preços da malha doméstica:
              cancelamento, atraso e referência de tarifa da rota e da companhia.
            </p>
          </section>
          <section className="about-block">
            <h2>Sinal</h2>
            <p>
              Score 0–10 resume o risco. A ação usa ±5% entre preço observado e referência:{" "}
              <strong className="action COMPRAR">COMPRAR</strong>,{" "}
              <strong className="action AGUARDAR">AGUARDAR</strong> ou{" "}
              <strong className="action MONITORAR">MONITORAR</strong>.
            </p>
          </section>
          <section className="about-block">
            <h2>Fontes</h2>
            <p>
              Cotação ao vivo na hora da busca, combinada com bases históricas de operação e preço já
              processadas. A experiência só consulta — não treina modelo na hora.
            </p>
          </section>
        </div>

        {loading && <p className="status">Carregando status…</p>}

        {health && (
          <dl className="health-strip">
            <div>
              <dt>Janela de dados</dt>
              <dd className="mono">
                {health.gold_date_min && health.gold_date_max
                  ? `${health.gold_date_min} → ${health.gold_date_max}`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Cotação ao vivo</dt>
              <dd className="mono">{health.serpapi_configured ? "disponível" : "indisponível"}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd className="mono">{health.status || "—"}</dd>
            </div>
          </dl>
        )}

        {metrics.length > 0 && (
          <section className="metrics-block">
            <h2>Métricas do modelo</h2>
            <ul className="metrics-list">
              {metrics.slice(0, 8).map((m, i) => {
                const label = m.modelo || m.model || m.nome || m.metric || `métrica ${i + 1}`;
                const split = m.split ? ` · ${m.split}` : "";
                const fmt = (v, digits = 3) =>
                  v == null || Number.isNaN(Number(v)) ? null : Number(v).toFixed(digits);
                const parts = [
                  m.mae != null || m.MAE != null ? `MAE ${fmt(m.mae ?? m.MAE)}` : null,
                  m.rmse != null || m.RMSE != null ? `RMSE ${fmt(m.rmse ?? m.RMSE)}` : null,
                  m.roc_auc != null ? `ROC-AUC ${fmt(m.roc_auc)}` : null,
                  m.pr_auc != null ? `PR-AUC ${fmt(m.pr_auc)}` : null,
                  m.brier_score != null ? `Brier ${fmt(m.brier_score)}` : null,
                  m.valor != null || m.value != null
                    ? String(m.valor ?? m.value)
                    : null,
                ].filter(Boolean);
                const value =
                  parts.length > 0
                    ? parts.join(" · ")
                    : m.prevalencia != null
                      ? `prevalência ${fmt(m.prevalencia, 4)}`
                      : "—";
                return (
                  <li key={i}>
                    <span>
                      {String(label)}
                      {split}
                    </span>
                    <strong className="mono">{value}</strong>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        <AdSlot />
      </main>
    </>
  );
}
