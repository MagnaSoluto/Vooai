import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Mark from "../components/Mark.jsx";
import Nav from "../components/Nav.jsx";
import AirportField from "../components/AirportField.jsx";
import Runway from "../components/Runway.jsx";

const FLEX_OPTIONS = [
  { value: "off", label: "Só a data pedida" },
  { value: "nearby", label: "Dias próximos (±3)" },
  { value: "weekdays", label: "Dias úteis próximos" },
  { value: "weekends", label: "Finais de semana próximos" },
];

export default function Home() {
  const navigate = useNavigate();
  const [origin, setOrigin] = useState("São Paulo");
  const [dest, setDest] = useState("Recife");
  const [tripType, setTripType] = useState("ida");
  const [date, setDate] = useState("2026-10-15");
  const [returnDate, setReturnDate] = useState("2026-10-22");
  const [flexDates, setFlexDates] = useState("off");
  const [extendOpen, setExtendOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  function onSubmit(e) {
    e.preventDefault();
    const o = origin.trim();
    const d = dest.trim();
    if (!o || !d || !date) return;
    if (tripType === "ida_volta" && !returnDate) return;
    setSubmitting(true);
    const q = new URLSearchParams({
      origin: o,
      dest: d,
      date,
      trip: tripType,
    });
    if (tripType === "ida_volta") q.set("return", returnDate);
    if (flexDates && flexDates !== "off") q.set("flex", flexDates);
    navigate(`/resultado?${q}`);
  }

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
          </form>
        </div>
      </section>
    </>
  );
}
