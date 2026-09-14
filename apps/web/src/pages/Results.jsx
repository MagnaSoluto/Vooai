import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Nav from "../components/Nav.jsx";
import ComboOpsChart from "../components/ComboOpsChart.jsx";
import { fetchFlightDetail, searchFlights } from "../api.js";

const PAGE_SIZE = 8;

const SORT_OPTIONS = [
  { value: "recomendado", label: "Recomendado" },
  { value: "preco", label: "Preço" },
  { value: "horario", label: "Horário" },
  { value: "score", label: "Score" },
  { value: "companhia", label: "Companhia" },
];

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtMin(m) {
  if (m == null) return "—";
  const h = Math.floor(m / 60);
  const min = m % 60;
  return h ? `${h}h${String(min).padStart(2, "0")}` : `${min} min`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  return String(iso).slice(11, 16) || "—";
}

function scoreTone(score) {
  if (score == null) return "neutral";
  if (score >= 8) return "good";
  if (score >= 6) return "mid";
  return "low";
}

function LegBadge({ leg }) {
  const map = { ida: "Ida", volta: "Volta", combo: "Combo" };
  return <span className={`leg-badge leg-${leg || "ida"}`}>{map[leg] || leg || "Ida"}</span>;
}

function actionRank(action) {
  if (action === "COMPRAR") return 0;
  if (action === "MONITORAR") return 1;
  return 2;
}

function airlineKey(f) {
  return f.companhia_chave || f.companhia || "—";
}

/** Ranking: sinal → score → preço → escalas. */
function rankFlights(rows) {
  return [...rows].sort((a, b) => {
    const byAction = actionRank(a.action) - actionRank(b.action);
    if (byAction) return byAction;
    const sa = a.safety_score != null ? a.safety_score : -1;
    const sb = b.safety_score != null ? b.safety_score : -1;
    if (sb !== sa) return sb - sa;
    const pa = a.preco_brl != null ? a.preco_brl : 1e12;
    const pb = b.preco_brl != null ? b.preco_brl : 1e12;
    if (pa !== pb) return pa - pb;
    return (a.conexoes ?? 99) - (b.conexoes ?? 99);
  });
}

function sortFlights(rows, sortBy) {
  const list = [...rows];
  switch (sortBy) {
    case "preco":
      return list.sort((a, b) => (a.preco_brl ?? 1e12) - (b.preco_brl ?? 1e12));
    case "horario":
      return list.sort((a, b) =>
        String(a.departure_at || "").localeCompare(String(b.departure_at || "")),
      );
    case "score":
      return list.sort((a, b) => (b.safety_score ?? -1) - (a.safety_score ?? -1));
    case "companhia":
      return list.sort((a, b) =>
        String(a.companhia || "").localeCompare(String(b.companhia || ""), "pt-BR"),
      );
    case "recomendado":
    default:
      return rankFlights(list);
  }
}

/** Score médio da cia nos voos desta lista (rota/destino da busca). */
function groupByAirline(rows) {
  const map = new Map();
  for (const f of rows) {
    const key = airlineKey(f);
    let g = map.get(key);
    if (!g) {
      g = {
        key,
        name: f.companhia || key,
        scores: [],
        prices: [],
        count: 0,
        bestAction: f.action,
      };
      map.set(key, g);
    }
    g.count += 1;
    if (f.safety_score != null) g.scores.push(f.safety_score);
    if (f.preco_brl != null) g.prices.push(f.preco_brl);
    if (actionRank(f.action) < actionRank(g.bestAction)) g.bestAction = f.action;
  }
  return [...map.values()]
    .map((g) => ({
      ...g,
      avgScore: g.scores.length ? g.scores.reduce((a, b) => a + b, 0) / g.scores.length : null,
      minPrice: g.prices.length ? Math.min(...g.prices) : null,
    }))
    .sort((a, b) => {
      const sa = a.avgScore != null ? a.avgScore : -1;
      const sb = b.avgScore != null ? b.avgScore : -1;
      if (sb !== sa) return sb - sa;
      return (a.minPrice ?? 1e12) - (b.minPrice ?? 1e12);
    });
}

function FlightRow({ f, onOpen, showDate = false }) {
  return (
    <article className="flight-table-row">
      <div>
        <LegBadge leg={f.leg} />
        {showDate && f.data_voo && <span className="flight-date-chip mono">{f.data_voo.slice(5)}</span>}
        <strong>{f.companhia || "—"}</strong>
        <small>{f.flight_numbers || ""}</small>
      </div>
      <div className="mono">
        {fmtTime(f.departure_at)}
        <span> → </span>
        {fmtTime(f.arrival_at)}
      </div>
      <div>{fmtMin(f.duration_min)}</div>
      <div>{f.conexoes === 0 ? "Direto" : `${f.conexoes} escala(s)`}</div>
      <div className="price">{fmt(f.preco_brl)}</div>
      <div>{f.punctuality_pct != null ? `${f.punctuality_pct}%` : "—"}</div>
      <div>{f.cancel_pct != null ? `${f.cancel_pct}%` : "—"}</div>
      <div>
        <span className={`score-chip ${scoreTone(f.safety_score)}`}>
          {f.safety_score != null ? f.safety_score.toFixed(1) : "—"}
        </span>
      </div>
      <div className="row-actions">
        <span className={`action ${f.action}`}>{f.action}</span>
        <button type="button" className="btn-details" onClick={() => onOpen(f)}>
          Detalhes
        </button>
      </div>
    </article>
  );
}

function FlightTable({ rows, onOpen, empty, showDate = false }) {
  const [selectedAirline, setSelectedAirline] = useState(null);
  const [sortBy, setSortBy] = useState("recomendado");
  const [page, setPage] = useState(1);

  const groups = useMemo(() => groupByAirline(rows), [rows]);
  const maxAvg = useMemo(
    () => Math.max(1, ...groups.map((g) => g.avgScore || 0)),
    [groups],
  );

  const selectedGroup = useMemo(
    () => groups.find((g) => g.key === selectedAirline) || null,
    [groups, selectedAirline],
  );

  const airlineFlights = useMemo(() => {
    if (!selectedAirline) return [];
    return rows.filter((f) => airlineKey(f) === selectedAirline);
  }, [rows, selectedAirline]);

  const sorted = useMemo(() => sortFlights(airlineFlights, sortBy), [airlineFlights, sortBy]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE) || 1);

  useEffect(() => {
    setPage(1);
  }, [selectedAirline, sortBy, rows]);

  useEffect(() => {
    if (selectedAirline && !groups.some((g) => g.key === selectedAirline)) {
      setSelectedAirline(null);
    }
  }, [groups, selectedAirline]);

  useEffect(() => {
    setPage((p) => Math.min(p, totalPages));
  }, [totalPages]);

  const pageSafe = Math.min(page, totalPages);
  const pageRows = sorted.slice((pageSafe - 1) * PAGE_SIZE, pageSafe * PAGE_SIZE);

  if (rows.length === 0) {
    return <p className="status">{empty || "Nenhuma oferta."}</p>;
  }

  return (
    <div className="flight-board">
      <div className="airline-summary" aria-label="Companhias nesta rota">
        {groups.map((g) => {
          const active = selectedAirline === g.key;
          return (
            <button
              key={g.key}
              type="button"
              className={`airline-picker${active ? " is-selected" : ""}`}
              aria-pressed={active}
              onClick={() => setSelectedAirline((prev) => (prev === g.key ? null : g.key))}
            >
              <div className="airline-summary-head">
                <strong>{g.name}</strong>
                <span className={`score-chip ${scoreTone(g.avgScore)}`}>
                  {g.avgScore != null ? g.avgScore.toFixed(1) : "—"}
                </span>
              </div>
              <div className="bar">
                <i style={{ width: `${((g.avgScore || 0) / maxAvg) * 100}%` }} />
              </div>
              <p className="airline-summary-meta">
                {g.count} oferta{g.count === 1 ? "" : "s"}
                {g.minPrice != null ? ` · a partir de ${fmt(g.minPrice)}` : ""}
                {g.bestAction ? ` · ${g.bestAction}` : ""}
              </p>
              <span className="airline-picker-cta">{active ? "Ocultar voos" : "Ver voos →"}</span>
            </button>
          );
        })}
      </div>

      {selectedAirline && selectedGroup && (
        <div className="flight-table-wrap">
          <div className="flight-toolbar">
            <div className="flight-toolbar-meta">
              <strong>{selectedGroup.name}</strong>
              <span className="muted mono">
                {sorted.length} voo{sorted.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="flight-toolbar-controls">
              <label className="sort-label">
                <span>Ordenar</span>
                <select
                  className="sort-select"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  aria-label="Ordenar voos"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn-swap-airline"
                onClick={() => setSelectedAirline(null)}
              >
                Trocar cia
              </button>
            </div>
          </div>

          <div className="flight-table-head">
            <span>Companhia</span>
            <span>Horário</span>
            <span>Duração</span>
            <span>Escalas</span>
            <span>Preço</span>
            <span>Pontualidade</span>
            <span>Cancel.</span>
            <span>Score</span>
            <span>Ação</span>
          </div>

          {pageRows.map((f, idx) => (
            <FlightRow
              key={`${f.id || f.companhia}-${f.data_voo}-${f.departure_at}-${idx}`}
              f={f}
              onOpen={onOpen}
              showDate={showDate}
            />
          ))}

          {sorted.length > 0 && (
            <nav className="flight-pagination" aria-label="Paginação de voos">
              <button
                type="button"
                disabled={pageSafe <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Anterior
              </button>
              <span className="mono">
                Página {pageSafe} de {totalPages}
              </span>
              <button
                type="button"
                disabled={pageSafe >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Próxima
              </button>
            </nav>
          )}
        </div>
      )}

      {!selectedAirline && (
        <p className="status muted">Selecione uma companhia para ver os voos.</p>
      )}
    </div>
  );
}

function MixedBoard({ pairs, onOpen, pageSize = 6 }) {
  const [sortBy, setSortBy] = useState("preco");
  const [page, setPage] = useState(1);

  const sorted = useMemo(() => {
    const list = [...pairs];
    if (sortBy === "score") {
      return list.sort((a, b) => (b.safety_score ?? -1) - (a.safety_score ?? -1));
    }
    if (sortBy === "companhia") {
      return list.sort((a, b) =>
        String(a.outbound?.companhia || "").localeCompare(String(b.outbound?.companhia || ""), "pt-BR"),
      );
    }
    if (sortBy === "horario") {
      return list.sort((a, b) =>
        String(a.outbound?.departure_at || "").localeCompare(String(b.outbound?.departure_at || "")),
      );
    }
    return list.sort((a, b) => (a.total_price_brl ?? 1e12) - (b.total_price_brl ?? 1e12));
  }, [pairs, sortBy]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize) || 1);
  useEffect(() => {
    setPage(1);
  }, [sortBy, pairs]);
  useEffect(() => {
    setPage((p) => Math.min(p, totalPages));
  }, [totalPages]);
  const pageSafe = Math.min(page, totalPages);
  const pageRows = sorted.slice((pageSafe - 1) * pageSize, pageSafe * pageSize);

  if (pairs.length === 0) {
    return <p className="status">Sem pares ida+volta montados.</p>;
  }

  return (
    <div className="mixed-board">
      <div className="flight-toolbar">
        <span className="muted mono">
          {sorted.length} combinação{sorted.length === 1 ? "" : "ões"}
        </span>
        <label className="sort-label">
          <span>Ordenar</span>
          <select
            className="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            aria-label="Ordenar combinações"
          >
            <option value="preco">Preço</option>
            <option value="horario">Horário</option>
            <option value="score">Score</option>
            <option value="companhia">Companhia</option>
          </select>
        </label>
      </div>
      <div className="mixed-grid">
        {pageRows.map((p, i) => (
          <MixedCard
            key={`mix-${i}-${p.outbound?.id}-${p.inbound?.id}`}
            pair={p}
            onOpen={onOpen}
          />
        ))}
      </div>
      {sorted.length > pageSize && (
        <nav className="flight-pagination" aria-label="Paginação de combinações">
          <button
            type="button"
            disabled={pageSafe <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Anterior
          </button>
          <span className="mono">
            Página {pageSafe} de {totalPages}
          </span>
          <button
            type="button"
            disabled={pageSafe >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            Próxima
          </button>
        </nav>
      )}
    </div>
  );
}

function MixedCard({ pair, onOpen }) {
  const out = pair.outbound;
  const inn = pair.inbound;
  return (
    <article className="mixed-card">
      <header>
        <span className={`mix-kind ${pair.kind}`}>
          {pair.kind === "same_airline" ? "Mesma cia" : "Cia mista"}
        </span>
        <strong>{fmt(pair.total_price_brl)}</strong>
        {pair.safety_score != null && (
          <span className={`score-chip ${scoreTone(pair.safety_score)}`}>
            {pair.safety_score.toFixed(1)}
          </span>
        )}
      </header>
      <div className="mixed-legs">
        <button type="button" className="mixed-leg" onClick={() => onOpen(out)}>
          <LegBadge leg="ida" />
          <div>
            <strong>{out.companhia}</strong>
            <span className="mono">
              {fmtTime(out.departure_at)} → {fmtTime(out.arrival_at)}
            </span>
          </div>
          <em>{fmt(out.preco_brl)}</em>
        </button>
        <button type="button" className="mixed-leg" onClick={() => onOpen(inn)}>
          <LegBadge leg="volta" />
          <div>
            <strong>{inn.companhia}</strong>
            <span className="mono">
              {fmtTime(inn.departure_at)} → {fmtTime(inn.arrival_at)}
            </span>
          </div>
          <em>{fmt(inn.preco_brl)}</em>
        </button>
      </div>
      <footer className="mixed-actions">
        {pair.booking_url_out && (
          <a
            className="mixed-buy-link"
            href={pair.booking_url_out}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            Comprar ida →
          </a>
        )}
        {pair.booking_url_in && (
          <a
            className="mixed-buy-link"
            href={pair.booking_url_in}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            Comprar volta →
          </a>
        )}
      </footer>
    </article>
  );
}

function DetailModal({ flight, onClose }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!flight) return undefined;
    let cancel = false;
    setLoading(true);
    setErr("");
    setDetail(null);
    fetchFlightDetail({
      companhia: flight.companhia,
      companhia_chave: flight.companhia_chave,
      iata_origin: flight.iata_origin,
      iata_destination: flight.iata_destination,
      date: flight.data_voo || undefined,
      preco_brl: flight.preco_brl,
    })
      .then((res) => {
        if (!cancel) setDetail(res);
      })
      .catch((e) => {
        if (!cancel) setErr(e.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [flight]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!flight) return null;

  const ops = detail?.ops_combo;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="flight-detail-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <div>
            <LegBadge leg={flight.leg} />
            <h2 id="flight-detail-title">
              {flight.companhia || "Voo"} · {flight.flight_numbers || "—"}
            </h2>
            <p className="muted">
              {flight.iata_origin} → {flight.iata_destination} · {fmtTime(flight.departure_at)} →{" "}
              {fmtTime(flight.arrival_at)} · {fmt(flight.preco_brl)}
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Fechar">
            ×
          </button>
        </header>

        <div className="modal-actions-row">
          <span className={`action ${flight.action}`}>{flight.action}</span>
          {(flight.booking_url || flight.booking_url_google) && (
            <a
              className="btn-buy"
              href={flight.booking_url || flight.booking_url_google}
              target="_blank"
              rel="noreferrer"
            >
              {flight.flight_numbers
                ? `Ver oferta · ${flight.flight_numbers}`
                : "Ver oferta"}
            </a>
          )}
          {flight.booking_url_airline && (
            <a
              className="btn-buy btn-buy-secondary"
              href={flight.booking_url_airline}
              target="_blank"
              rel="noreferrer"
            >
              Buscar na companhia
            </a>
          )}
        </div>

        {loading && <p className="status">Carregando histórico da rota…</p>}
        {err && <p className="status error-box">{err}</p>}

        {detail && (
          <div className="detail-grid">
            <section>
              <h3>Indicadores</h3>
              <ul className="detail-bars">
                {(detail.bars || []).map((b) => (
                  <li key={b.label}>
                    <span>{b.label}</span>
                    <div className={`bar ${b.kind === "warn" ? "warn" : ""}`}>
                      <i style={{ width: `${Math.min(100, Number(b.value) || 0)}%` }} />
                    </div>
                    <b>{b.value != null ? `${b.value}%` : "—"}</b>
                  </li>
                ))}
                {(detail.bars || []).length === 0 && <li className="muted">Sem barras históricas.</li>}
              </ul>
            </section>

            <section>
              <h3>Insights</h3>
              <ul className="insight-list">
                {(detail.insights || []).map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </section>

            <section className="detail-full">
              <h3>
                Volume × cancelamento / atraso
                {detail.municipio_origem && detail.municipio_destino
                  ? ` · ${flight.companhia || "Companhia"} · ${detail.municipio_origem} → ${detail.municipio_destino}`
                  : ""}
              </h3>
              <p className="muted tiny">
                Histórico dos últimos 9 meses e horizonte de 3 meses para esta companhia nesta rota.
              </p>
              {ops?.series?.length ? (
                <ComboOpsChart
                  series={ops.series}
                  method={ops.method}
                  compact
                  lineLabels={ops.line_labels}
                />
              ) : (
                <p className="muted">Série histórica indisponível para este trecho.</p>
              )}
            </section>

            <section>
              <h3>Companhia</h3>
              {detail.airline ? (
                <dl className="stat-dl">
                  <div>
                    <dt>Voos na base</dt>
                    <dd>{detail.airline.voos_totais?.toLocaleString("pt-BR")}</dd>
                  </div>
                  <div>
                    <dt>Pontualidade</dt>
                    <dd>{detail.airline.pct_pontualidade}%</dd>
                  </div>
                  <div>
                    <dt>Atraso</dt>
                    <dd>{detail.airline.pct_atraso}%</dd>
                  </div>
                  <div>
                    <dt>Cancelamento</dt>
                    <dd>{detail.airline.pct_cancelamento}%</dd>
                  </div>
                </dl>
              ) : (
                <p className="muted">Sem histórico da companhia.</p>
              )}
            </section>

            <section>
              <h3>Rota {detail.municipio_origem} → {detail.municipio_destino}</h3>
              <dl className="stat-dl">
                <div>
                  <dt>Atraso rota</dt>
                  <dd>{detail.route_delay?.pct_atraso != null ? `${detail.route_delay.pct_atraso}%` : "—"}</dd>
                </div>
                <div>
                  <dt>No-show rota</dt>
                  <dd>
                    {detail.route_operations?.pct_no_show != null
                      ? `${detail.route_operations.pct_no_show}%`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Cancel. rota</dt>
                  <dd>
                    {detail.route_operations?.pct_cancelamento != null
                      ? `${detail.route_operations.pct_cancelamento}%`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Preço vs mediana histórica</dt>
                  <dd>
                    {flight.preco_historico_mediana != null
                      ? fmt(flight.preco_historico_mediana)
                      : detail.gold?.preco_historico_mediana != null
                        ? fmt(detail.gold.preco_historico_mediana)
                        : "—"}
                  </dd>
                </div>
              </dl>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Results() {
  const [params, setParams] = useSearchParams();
  const origin = params.get("origin") || "São Paulo";
  const dest = params.get("dest") || "Recife";
  const date = params.get("date") || "";
  const returnDate = params.get("return") || "";
  const tripType = params.get("trip") || (returnDate ? "ida_volta" : "ida");
  const flexDates = params.get("flex") || "off";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setError("");
    setData(null);
    searchFlights({ origin, dest, date, returnDate, tripType, flexDates })
      .then((res) => {
        if (!cancel) setData(res);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [origin, dest, date, returnDate, tripType, flexDates]);

  function enableNearbyFlex() {
    const next = new URLSearchParams(params);
    next.set("flex", data?.nearby_hint?.suggested_flex || "nearby");
    setParams(next, { replace: false });
  }

  const summary = data?.summary;
  const routeScore = data?.route_score;
  const isRT = tripType === "ida_volta" || data?.trip_type === "ida_volta";
  const flexOn = flexDates !== "off";
  const outbound = data?.outbound_flights || [];
  const inbound = data?.inbound_flights || [];
  const combo = data?.combo_flights || [];
  const mixed = data?.mixed_pairs || [];
  const oneWay = !isRT ? data?.flights || outbound : [];
  const best = data?.best_option;
  const maxAirline = Math.max(1, ...(data?.airline_scores || []).map((a) => a.avg_safety_score));
  const dateLabel = isRT
    ? `${date} → ${returnDate || data?.return_date || "—"} · ida e volta`
    : date;
  const flexLabel =
    flexDates === "nearby"
      ? "dias próximos"
      : flexDates === "weekdays"
        ? "dias úteis próximos"
        : flexDates === "weekends"
          ? "fins de semana próximos"
          : null;

  const bestFlight = best?.flight || (best?.companhia ? best : null);
  const bestPair = best?.pair;
  const hint = data?.nearby_hint;

  return (
    <>
      <Nav light />
      <main className={`page board${data ? " anim-ready" : ""}`}>
        <header className="board-head">
          <div>
            <p className="kicker">Resultado</p>
            <h1>
              {origin} → {dest}
            </h1>
            <p className="muted">
              {dateLabel}
              {flexLabel ? ` · busca estendida: ${flexLabel}` : ""}
              {data?.iatas_origin
                ? ` · ${data.iatas_origin.join(", ")} → ${data.iatas_destination.join(", ")}`
                : ""}
            </p>
          </div>
        </header>

        {!loading && hint?.active && !flexOn && (
          <button type="button" className="nearby-hint" onClick={enableNearbyFlex}>
            <span>{hint.message}</span>
            <span className="nearby-hint-meta mono">
              {hint.best_date_label}
              {hint.saving_pct != null ? ` · até −${hint.saving_pct}% vs. melhor do dia` : ""}
              {" →"}
            </span>
          </button>
        )}

        {flexOn && data?.dates_searched?.length > 1 && (
          <p className="flex-dates-chip muted">
            Datas consultadas: {data.dates_searched.map((d) => d.slice(5)).join(" · ")}
            {data.flex_best_date
              ? ` · melhor preço em ${data.flex_best_date.slice(5)}`
              : ""}
          </p>
        )}

        {loading && (
          <p className="status loading-pulse">
            {flexOn
              ? "Consultando a data pedida e datas próximas…"
              : isRT
                ? "Consultando ida, volta e combo…"
                : "Consultando ofertas e histórico da rota…"}
          </p>
        )}
        {error && <p className="status error-box">Falha na busca: {error}</p>}

        {data && (
          <>
            <section className="kpi-row" aria-label="Resumo">
              <div className="kpi">
                <span>Ofertas</span>
                <strong>{summary.flights_found}</strong>
              </div>
              <div className="kpi">
                <span>Menor preço</span>
                <strong>{fmt(summary.lowest_price_brl)}</strong>
              </div>
              {isRT && (
                <>
                  <div className="kpi">
                    <span>Menor combo</span>
                    <strong>{fmt(summary.lowest_combo_brl)}</strong>
                  </div>
                  <div className="kpi">
                    <span>Menor mix ida+volta</span>
                    <strong>{fmt(summary.lowest_mixed_brl)}</strong>
                  </div>
                </>
              )}
              {!isRT && (
                <>
                  <div className="kpi">
                    <span>Pontualidade média</span>
                    <strong>
                      {summary.avg_punctuality_pct != null ? `${summary.avg_punctuality_pct}%` : "—"}
                    </strong>
                  </div>
                  <div className="kpi">
                    <span>Score médio</span>
                    <strong>
                      {summary.avg_safety_score != null ? `${summary.avg_safety_score}/10` : "—"}
                    </strong>
                  </div>
                </>
              )}
            </section>

            <section className="score-panel">
              <div className={`score-ring ${scoreTone(routeScore.safety_score)}`}>
                <strong>
                  {routeScore.safety_score != null ? routeScore.safety_score.toFixed(1) : "—"}
                </strong>
                <span>/ 10</span>
                <em>{routeScore.label}</em>
              </div>
              <div className="score-bars">
                <div>
                  <span>Idas / voltas / combos</span>
                  <b className="mono">
                    {summary.outbound_count ?? outbound.length} / {summary.inbound_count ?? inbound.length} /{" "}
                    {summary.combo_count ?? combo.length}
                  </b>
                </div>
                <div>
                  <span>Pares mistos</span>
                  <b className="mono">{summary.mixed_count ?? mixed.length}</b>
                </div>
                <div>
                  <span>Pontualidade</span>
                  <b>
                    {summary.avg_punctuality_pct != null ? `${summary.avg_punctuality_pct}%` : "—"}
                  </b>
                </div>
                <div>
                  <span>Score médio</span>
                  <b>
                    {summary.avg_safety_score != null ? `${summary.avg_safety_score}/10` : "—"}
                  </b>
                </div>
              </div>
            </section>

            <div className="board-grid">
              <div className="results-stack">
                {isRT && (
                  <>
                    <section className="result-block">
                      <h2>Combo mesma companhia</h2>
                      <p className="muted">Selecione a cia, ordene e use a paginação.</p>
                      <FlightTable rows={combo} onOpen={setSelected} showDate={flexOn} empty="Nenhum combo retornado." />
                    </section>

                    <section className="result-block">
                      <h2>Ida numa cia + volta em outra</h2>
                      <p className="muted">
                        Combinações dos melhores trechos — ordene e paginação. Clique em ida/volta para
                        detalhes.
                      </p>
                      <MixedBoard pairs={mixed} onOpen={setSelected} />
                    </section>

                    <section className="result-block">
                      <h2>Só ida</h2>
                      <p className="muted">Selecione a cia, ordene e use a paginação.</p>
                      <FlightTable rows={outbound} onOpen={setSelected} showDate={flexOn} empty="Sem ofertas de ida." />
                    </section>

                    <section className="result-block">
                      <h2>Só volta</h2>
                      <p className="muted">Selecione a cia, ordene e use a paginação.</p>
                      <FlightTable rows={inbound} onOpen={setSelected} showDate={flexOn} empty="Sem ofertas de volta." />
                    </section>
                  </>
                )}

                {!isRT && (
                  <section className="result-block">
                    <h2>Voos de ida</h2>
                    <p className="muted">
                      Selecione a companhia para ver os voos. Use ordenação e paginação. Detalhes pelo
                      botão.
                    </p>
                    <FlightTable rows={oneWay} onOpen={setSelected} showDate={flexOn} empty="Nenhuma oferta retornada." />
                  </section>
                )}
              </div>

              <aside className="side-panel">
                <section>
                  <h2>Desempenho da rota</h2>
                  <p className="muted">
                    {data.route_performance?.sample_flights || 0} ofertas com histórico da rota · atraso médio{" "}
                    {data.route_performance?.avg_delay_pct ?? "—"}% · cancelamento{" "}
                    {data.route_performance?.avg_cancel_pct ?? "—"}%
                  </p>
                </section>

                <section>
                  <h2>Score médio por companhia</h2>
                  <ul className="airline-bars">
                    {(data.airline_scores || []).map((a) => (
                      <li key={a.airline}>
                        <span>{a.airline}</span>
                        <div className="bar">
                          <i style={{ width: `${(a.avg_safety_score / maxAirline) * 100}%` }} />
                        </div>
                        <b>{a.avg_safety_score.toFixed(1)}</b>
                      </li>
                    ))}
                    {(data.airline_scores || []).length === 0 && (
                      <li className="muted">Sem histórico da companhia nesta busca.</li>
                    )}
                  </ul>
                </section>

                {best && (
                  <section className="best-card">
                    <h2>Melhor opção</h2>
                    <p className="best-title">
                      {best.label || "Destaque"} · {fmt(best.price ?? bestFlight?.preco_brl)}
                      {best.safety_score != null ? ` · score ${best.safety_score}` : ""}
                    </p>
                    {bestFlight && (
                      <ul>
                        <li className={`action ${bestFlight.action}`}>{bestFlight.action}</li>
                        <li>
                          {bestFlight.companhia} · {bestFlight.flight_numbers || "—"}
                        </li>
                        {(bestFlight.booking_url || bestFlight.booking_url_google) && (
                          <li>
                            <a
                              href={bestFlight.booking_url || bestFlight.booking_url_google}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {bestFlight.flight_numbers
                                ? `Ver oferta · ${bestFlight.flight_numbers}`
                                : "Ver oferta"}
                            </a>
                          </li>
                        )}
                        <li>
                          <button type="button" className="linkish" onClick={() => setSelected(bestFlight)}>
                            Ver detalhes
                          </button>
                        </li>
                      </ul>
                    )}
                    {bestPair && !bestFlight && (
                      <ul>
                        <li>
                          Ida: {bestPair.outbound?.companhia} {fmt(bestPair.outbound?.preco_brl)}
                        </li>
                        <li>
                          Volta: {bestPair.inbound?.companhia} {fmt(bestPair.inbound?.preco_brl)}
                        </li>
                        <li>
                          <button
                            type="button"
                            className="linkish"
                            onClick={() => setSelected(bestPair.outbound)}
                          >
                            Detalhe da ida
                          </button>
                        </li>
                      </ul>
                    )}
                  </section>
                )}
              </aside>
            </div>
          </>
        )}
      </main>

      {selected && <DetailModal flight={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
