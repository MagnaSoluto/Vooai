import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Mark from "../components/Mark.jsx";
import Nav from "../components/Nav.jsx";

export default function Home() {
  const navigate = useNavigate();
  const [origin, setOrigin] = useState("GRU");
  const [dest, setDest] = useState("SSA");
  const [date, setDate] = useState("2026-09-12");

  function onSubmit(e) {
    e.preventDefault();
    const o = origin.trim().toUpperCase();
    const d = dest.trim().toUpperCase();
    navigate(`/resultado?origin=${o}&dest=${d}&date=${date}`);
  }

  return (
    <>
      <Nav />
      <section className="hero">
        <div className="runway" aria-hidden="true">
          <span className="runway-edge l" />
          <span className="runway-center" />
          <span className="runway-edge r" />
        </div>
        <div className="hero-copy">
          <div className="wordmark">
            <Mark size={72} />
            VooAI
          </div>
          <h1>Sinal claro para comprar ou esperar.</h1>
          <p className="lead">
            Busque um trecho nacional. O veredito junta preço, tendência e reputação.
          </p>
          <form className="search" onSubmit={onSubmit}>
            <label className="field">
              <span>Origem</span>
              <input value={origin} maxLength={3} onChange={(e) => setOrigin(e.target.value)} />
            </label>
            <label className="field">
              <span>Destino</span>
              <input value={dest} maxLength={3} onChange={(e) => setDest(e.target.value)} />
            </label>
            <label className="field">
              <span>Data</span>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <button className="btn" type="submit">
              Ver sinal
            </button>
          </form>
        </div>
      </section>
    </>
  );
}
