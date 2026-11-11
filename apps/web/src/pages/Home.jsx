import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Mark from "../components/Mark.jsx";
import Nav from "../components/Nav.jsx";
import AirportField from "../components/AirportField.jsx";
import Runway from "../components/Runway.jsx";
import { fetchPricing, getToken } from "../api.js";

const FLEX_OPTIONS = [
  { value: "off", label: "Só a data pedida" },
  { value: "nearby", label: "Dias próximos (±3)" },
  { value: "weekdays", label: "Dias úteis próximos" },
  { value: "weekends", label: "Finais de semana próximos" },
];

function fmtBrl(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function isoPlusDays(days) {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function Home() {
  const navigate = useNavigate();
  const [origin, setOrigin] = useState("São Paulo");
  const [dest, setDest] = useState("Recife");
  const [tripType, setTripType] = useState("ida");
  // Datas futuras (antes ficavam fixas em out/2026 e já passaram).
  const [date, setDate] = useState(() => isoPlusDays(21));
  const [returnDate, setReturnDate] = useState(() => isoPlusDays(28));
  const [flexDates, setFlexDates] = useState("off");
  const [extendOpen, setExtendOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [quotePrice, setQuotePrice] = useState(null);
  const [needAuth, setNeedAuth] = useState(false);
  const [debitConfirmOpen, setDebitConfirmOpen] = useState(false);

  useEffect(() => {
    let cancel = false;
    const ac = new AbortController();
    fetchPricing({
      tripType,
      flexDates,
      returnDate: tripType === "ida_volta" ? returnDate : null,
      signal: ac.signal,
    })
      .then((p) => {
        if (cancel) return;
        setNeedAuth(Boolean(p.billing_enabled || p.search_require_auth));
        setQuotePrice(p.quote || null);
      })
      .catch(() => {
        if (!cancel) setQuotePrice(null);
      });
    return () => {
      cancel = true;
      ac.abort();
    };
  }, [tripType, flexDates, returnDate]);

  useEffect(() => {
    if (!debitConfirmOpen) return undefined;
    function onKey(e) {
      if (e.key === "Escape" && !submitting) setDebitConfirmOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [debitConfirmOpen, submitting]);

  function buildQuery() {
    const q = new URLSearchParams({
      origin: origin.trim(),
      dest: dest.trim(),
      date,
      trip: tripType,
    });
    if (tripType === "ida_volta") q.set("return", returnDate);
    if (flexDates && flexDates !== "off") q.set("flex", flexDates);
    return q;
  }

  function onSubmit(e) {
    e.preventDefault();
    const o = origin.trim();
    const d = dest.trim();
    if (!o || !d || !date) return;
    if (tripType === "ida_volta" && !returnDate) return;
    setDebitConfirmOpen(true);
  }

  function goSearch() {
    const q = buildQuery();
    if (needAuth && !getToken()) {
      setDebitConfirmOpen(false);
      navigate(`/conta?next=${encodeURIComponent(`/resultado?${q}`)}`);
      return;
    }
    setSubmitting(true);
    setDebitConfirmOpen(false);
    navigate(`/resultado?${q}`);
  }

  const saldosCost = quotePrice?.saldos ?? quotePrice?.credits ?? null;
  const priceLabel =
    saldosCost != null
      ? `${Number(saldosCost).toLocaleString("pt-BR")} ${saldosCost === 1 ? "saldo" : "saldos"}`
      : quotePrice
        ? fmtBrl(quotePrice.price_brl)
        : null;

  return (
    <>
      <Nav />
      <section className="hero">
        <Runway />
        <div className="hero-copy">
          <div className="wordmark anim-tracking-in">
            <Mark size={40} />
            <span>VooAI</span>
          </div>
          <h1 className="anim-fade-in-bottom">Sinal claro para comprar ou esperar.</h1>
          <p className="lead anim-fade-in-bottom anim-delay-1">
            Preço ao vivo cruzado com histórico de risco e tarifa da rota.
          </p>
          <form className="search" onSubmit={onSubmit}>
            <div className="trip-toggle" role="group" aria-label="Tipo de viagem">
              <button
                type="button"
                className={tripType === "ida" ? "active" : ""}
                onClick={() => setTripType("ida")}
              >
                Só ida
              </button>
              <button
                type="button"
                className={tripType === "ida_volta" ? "active" : ""}
                onClick={() => setTripType("ida_volta")}
              >
                Ida e volta
              </button>
            </div>
            <div className="search-row">
              <AirportField label="Origem" value={origin} onChange={(v) => setOrigin(v)} />
              <AirportField label="Destino" value={dest} onChange={(v) => setDest(v)} />
              <label className="field date-field">
                <span>{tripType === "ida_volta" ? "Ida" : "Data"}</span>
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
              </label>
              {tripType === "ida_volta" && (
                <label className="field date-field anim-scale-in">
                  <span>Volta</span>
                  <input
                    type="date"
                    value={returnDate}
                    min={date}
                    onChange={(e) => setReturnDate(e.target.value)}
                    required
                  />
                </label>
              )}
              <button className="btn" type="submit" disabled={submitting}>
                {submitting ? "Abrindo…" : "Ver sinal"}
              </button>
            </div>
            <div className="flex-dates">
              <label className="flex-dates-toggle">
                <input
                  type="checkbox"
                  checked={extendOpen || flexDates !== "off"}
                  onChange={(e) => {
                    const on = e.target.checked;
                    setExtendOpen(on);
                    setFlexDates(on ? (flexDates === "off" ? "nearby" : flexDates) : "off");
                  }}
                />
                <span>Estender busca a datas próximas</span>
              </label>
              {(extendOpen || flexDates !== "off") && (
                <label className="flex-dates-select">
                  <span className="sr-only">Modo de datas próximas</span>
                  <select
                    value={flexDates === "off" ? "nearby" : flexDates}
                    onChange={(e) => {
                      setFlexDates(e.target.value);
                      setExtendOpen(true);
                    }}
                  >
                    {FLEX_OPTIONS.filter((o) => o.value !== "off").map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            {quotePrice && (
              <p className="search-price-hint muted">
                Esta busca custará <strong>{priceLabel}</strong>
              </p>
            )}
          </form>
        </div>
      </section>

      {debitConfirmOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => {
            if (!submitting) setDebitConfirmOpen(false);
          }}
        >
          <div
            className="modal-sheet debit-confirm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="debit-confirm-title"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="modal-head">
              <div>
                <p className="kicker">Débito do saldo</p>
                <h2 id="debit-confirm-title">Confirmar consulta</h2>
              </div>
              <button
                type="button"
                className="modal-close"
                onClick={() => setDebitConfirmOpen(false)}
                aria-label="Fechar"
                disabled={submitting}
              >
                ×
              </button>
            </header>
            <p className="debit-confirm-lead">
              Ao continuar, esta busca debitará{" "}
              <strong>{priceLabel || "os saldos desta consulta"}</strong> da sua conta.
            </p>
            <p className="muted debit-confirm-meta">
              {origin.trim()} → {dest.trim()}
              {" · "}
              {tripType === "ida_volta" ? `${date} → ${returnDate}` : date}
              {flexDates !== "off" ? " · datas próximas" : ""}
            </p>
            <p className="muted">
              Se a busca não for concluída, os saldos voltam para a sua conta.
            </p>
            <div className="debit-confirm-actions">
              <button
                type="button"
                className="btn-ghost"
                disabled={submitting}
                onClick={() => setDebitConfirmOpen(false)}
              >
                Cancelar
              </button>
              <button type="button" className="btn" disabled={submitting} onClick={goSearch}>
                {submitting ? "Abrindo…" : `Continuar · ${priceLabel || "debitar"}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
