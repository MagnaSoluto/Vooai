import { useEffect, useMemo, useState } from "react";
import Nav from "../components/Nav.jsx";
import ComboOpsChart from "../components/ComboOpsChart.jsx";
import { fetchDashboard } from "../api.js";

function fmtInt(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("pt-BR");
}

function fmtPct(n, digits = 1) {
  if (n == null) return "—";
  return `${Number(n).toFixed(digits)}%`;
}

function fmtMoney(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  });
}

/** Horizonte de preço: linhas = tarifa (eixo esq. R$) · barras = atraso % (eixo dir.). */
function HorizonCombo({ rows }) {
  const data = rows || [];
  if (!data.length) return <p className="muted">Sem horizonte de preço.</p>;

  const w = 720;
  const h = 260;
  const pad = { t: 20, r: 44, b: 36, l: 52 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const prices = data.flatMap((r) => [r.price_forecast, r.price_median]).filter((x) => x != null);
  const minP = Math.min(...prices) * 0.9;
  const maxP = Math.max(...prices) * 1.06;
  const maxD = Math.max(1, ...data.map((r) => r.delay_pct || 0)) * 1.1;
  const n = data.length;
  const band = innerW / n;
  const barW = Math.min(18, band * 0.4);
  const x = (i) => pad.l + band * i + band / 2;
  const yP = (v) => pad.t + innerH - ((v - minP) / (maxP - minP || 1)) * innerH;
  const yD = (v) => pad.t + innerH - ((v || 0) / maxD) * innerH;

  const path = (key) =>
    data
      .map((r, i) => {
        const v = r[key];
        if (v == null) return null;
        const cmd = i === 0 || data[i - 1]?.[key] == null ? "M" : "L";
        return `${cmd}${x(i).toFixed(1)},${yP(v).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  return (
    <div className="dash-combo">
      <svg
        className="dash-combo-svg"
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label="Tarifa prevista, mediana e atraso por mês"
      >
        {[0, 0.5, 1].map((t) => (
          <line
            key={t}
            x1={pad.l}
            x2={w - pad.r}
            y1={pad.t + innerH * (1 - t)}
            y2={pad.t + innerH * (1 - t)}
            className="dash-grid"
          />
        ))}
        {data.map((r, i) => (
          <rect
            key={`d-${r.month}`}
            x={x(i) - barW / 2}
            y={yD(r.delay_pct)}
            width={barW}
            height={Math.max(1, pad.t + innerH - yD(r.delay_pct))}
            className="dash-bar-delay"
          />
        ))}
        <path d={path("price_median")} className="dash-line median" fill="none" />
        <path d={path("price_forecast")} className="dash-line forecast" fill="none" />
        {data.map((r, i) =>
          r.price_forecast != null ? (
            <circle key={`c-${r.month}`} cx={x(i)} cy={yP(r.price_forecast)} r="2.8" className="dash-dot forecast" />
          ) : null,
        )}
        {data.map((r, i) =>
          i % 2 === 0 || i === n - 1 ? (
            <text key={`l-${r.month}`} x={x(i)} y={h - 10} textAnchor="middle" className="dash-axis">
              {r.label}
            </text>
          ) : null,
        )}
        <text x={pad.l - 6} y={pad.t + 4} textAnchor="end" className="dash-axis">
          R$ {Math.round(maxP)}
        </text>
        <text x={pad.l - 6} y={pad.t + innerH} textAnchor="end" className="dash-axis">
          R$ {Math.round(minP)}
        </text>
        <text x={w - pad.r + 6} y={pad.t + 4} textAnchor="start" className="dash-axis">
          {maxD.toFixed(0)}% atr.
        </text>
        <text x={w - pad.r + 6} y={pad.t + innerH} textAnchor="start" className="dash-axis">
          0%
        </text>
      </svg>
      <div className="dash-legend">
        <span>
          <i className="lg-line-forecast" /> Tarifa prevista (linha)
        </span>
        <span>
          <i className="lg-line-median" /> Mediana histórica (tracejada)
        </span>
        <span>
          <i className="lg-delay-bar" /> % atraso (barras)
        </span>
      </div>
      <p className="tiny muted dash-chart-note">
        Eixo esquerdo = R$. Eixo direito = atraso histórico do mês. Sem misturar com o volume
        operacional do bloco 01.
      </p>
    </div>
  );
}

/** Comparativo horizontal cias. */
function AirlineCompare({ rows }) {
  const max = Math.max(1, ...rows.map((r) => r.delay_pct || 0));
  return (
    <ul className="dash-compare">
      {rows.map((r) => (
        <li key={r.airline}>
          <div className="dash-compare-head">
            <strong>{r.airline}</strong>
            <span className="mono">{fmtPct(r.delay_pct)} atraso · {fmtPct(r.cancel_pct)} cancel.</span>
          </div>
          <div className="bar">
            <i style={{ width: `${((r.delay_pct || 0) / max) * 100}%` }} />
          </div>
          <small className="muted">{fmtInt(r.flights)} voos</small>
        </li>
      ))}
    </ul>
  );
}

function MetricRows({ title, rows, keys }) {
  if (!rows?.length) return null;
  return (
    <div className="dash-metrics-group">
      <h3>{title}</h3>
      <ul className="metrics-list">
        {rows.map((row, i) => (
          <li key={`${title}-${i}`}>
            <span>
              {row.modelo || "modelo"}
              {row.split ? ` · ${row.split}` : ""}
            </span>
            <span className="mono">
              {keys
                .filter((k) => row[k] != null)
                .map((k) => `${k} ${Number(row[k]).toFixed(3)}`)
                .join(" · ")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState("delay_pct");

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    fetchDashboard({ limit: 8 })
      .then((d) => {
        if (cancel) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (cancel) return;
        setError(e.message || String(e));
        setData(null);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, []);

  const airlines = useMemo(() => {
    const rows = [...(data?.top_airlines || [])];
    rows.sort((a, b) => {
      if (sortKey === "flights") return (b.flights ?? 0) - (a.flights ?? 0);
      if (sortKey === "cancel_pct") return (b.cancel_pct ?? -1) - (a.cancel_pct ?? -1);
      return (b.delay_pct ?? -1) - (a.delay_pct ?? -1);
    });
    return rows;
  }, [data, sortKey]);

  const corridors = data?.top_corridors_delay || [];
  const maxDelay = Math.max(1, ...corridors.map((c) => c.delay_pct || 0));
  const kpis = data?.kpis;
  const story = data?.story;
  const outlook = data?.outlook || [];
  const ops = data?.ops_combo;
  const opsSeries = ops?.series || [];

  const nextMom = outlook.find((o) => o.price_mom_pct != null);

  return (
    <>
      <Nav light />
      <main className="page dashboard anim-fade-in-bottom">
        <p className="kicker">Dashboard · malha doméstica</p>
        <h1>{story?.headline || "Leitura gerencial da malha."}</h1>
        <p className="lead muted">{story?.lede}</p>

        {loading && <p className="status">Carregando painel…</p>}
        {error && <p className="status error">Falha ao carregar dashboard: {error}</p>}

        {!loading && !error && data && (
          <>
            <section className="dash-story" aria-label="Síntese executiva">
              <ul className="dash-bullets">
                {(story?.bullets || []).map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
              <div className="dash-callouts">
                <div className="dash-callout">
                  <span>Tarifa prevista mais baixa</span>
                  <strong>{story?.cheapest_month || "—"}</strong>
                </div>
                <div className="dash-callout warn">
                  <span>Mês com mais atraso</span>
                  <strong>{story?.riskiest_month || "—"}</strong>
                </div>
                {nextMom && (
                  <div className="dash-callout">
                    <span>Variação mês a mês (1º salto)</span>
                    <strong className="mono">
                      {nextMom.label} · {nextMom.price_mom_pct > 0 ? "+" : ""}
                      {fmtPct(nextMom.price_mom_pct)}
                    </strong>
                  </div>
                )}
              </div>
            </section>

            <section className="kpi-row" aria-label="Indicadores da malha">
              <div className="kpi">
                <span>Voos na base</span>
                <strong>{fmtInt(kpis?.flights_spec)}</strong>
              </div>
              <div className="kpi">
                <span>Atraso méd.</span>
                <strong>{fmtPct(kpis?.avg_delay_pct)}</strong>
              </div>
              <div className="kpi">
                <span>Cancel. méd.</span>
                <strong>{fmtPct(kpis?.avg_cancel_pct)}</strong>
              </div>
              <div className="kpi">
                <span>Janela de dados</span>
                <strong className="kpi-window">
                  {kpis?.gold_date_min && kpis?.gold_date_max
                    ? `${kpis.gold_date_min.slice(0, 7)} → ${kpis.gold_date_max.slice(0, 7)}`
                    : "—"}
                </strong>
              </div>
            </section>

            <section className="dash-chapter">
              <div className="dash-chapter-head">
                <p className="kicker">01 · Operação</p>
                <h2>Volume × cancelamento / no-show</h2>
                <p className="muted">
                  Barras = voos (eixo esquerdo). Linhas = % cancelamento e no-show (eixo direito).
                  Histórico recente e horizonte de três meses à frente.
                </p>
              </div>
              <ComboOpsChart series={opsSeries} method={ops?.method} />
            </section>

            <section className="dash-chapter">
              <div className="dash-chapter-head">
                <p className="kicker">02 · Horizonte de preço</p>
                <h2>Tarifa prevista × mediana · atraso</h2>
                <p className="muted">
                  Um gráfico, dois eixos: linhas em R$ (tarifa prevista vs mediana histórica) e barras
                  em % de atraso do mês — sem misturar com o volume do bloco 01.
                </p>
              </div>
              <HorizonCombo rows={outlook} />
            </section>

            <section className="dash-split dash-chapter">
              <div className="dash-block">
                <div className="dash-block-head">
                  <div>
                    <p className="kicker">03 · Comparativo</p>
                    <h2>Companhias</h2>
                  </div>
                  <label className="dash-sort">
                    Ordenar
                    <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                      <option value="delay_pct">% atraso</option>
                      <option value="cancel_pct">% cancel.</option>
                      <option value="flights">Voos</option>
                    </select>
                  </label>
                </div>
                <AirlineCompare rows={airlines} />
              </div>

              <div className="dash-block">
                <p className="kicker">04 · Corredores</p>
                <h2>Maior atraso histórico</h2>
                <p className="tiny muted">Mín. 50 voos · top {corridors.length}</p>
                <ul className="score-bars dash-corridors">
                  {corridors.map((c) => (
                    <li key={`${c.origin}-${c.destination}`}>
                      <div className="dash-corridor-label">
                        <span>
                          {c.origin} → {c.destination}
                        </span>
                        <span className="mono">{fmtPct(c.delay_pct)}</span>
                      </div>
                      <div className={`bar${(c.delay_pct || 0) >= 40 ? " warn" : ""}`}>
                        <i style={{ width: `${((c.delay_pct || 0) / maxDelay) * 100}%` }} />
                      </div>
                      <small className="muted">{fmtInt(c.flights)} voos</small>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section className="metrics-block dash-models dash-chapter">
              <p className="kicker">05 · Confiança</p>
              <h2>Qualidade do modelo</h2>
              <p className="tiny muted">
                Erro mensurável — o storytelling de preço e risco acima depende destes números.
              </p>
              <div className="dash-metrics-grid">
                <MetricRows
                  title="Classificação / risco"
                  rows={data.model_metrics?.classification}
                  keys={["roc_auc", "pr_auc", "brier_score", "log_loss"]}
                />
                <MetricRows
                  title="Preço"
                  rows={data.model_metrics?.price}
                  keys={["mae", "rmse", "mape", "r2"]}
                />
              </div>
            </section>

            <p className="tiny muted dash-footnote">
              Malha doméstica brasileira. Horizonte de tarifa:{" "}
              {fmtMoney(outlook[0]?.price_forecast)} → {fmtMoney(outlook.at(-1)?.price_forecast)}.
            </p>
          </>
        )}
      </main>
    </>
  );
}
