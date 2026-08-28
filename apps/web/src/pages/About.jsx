import { useEffect, useState } from "react";
import Nav from "../components/Nav.jsx";
import { fetchMetrics } from "../api.js";

export default function About() {
  const [metrics, setMetrics] = useState([]);

  useEffect(() => {
    fetchMetrics()
      .then(setMetrics)
      .catch(() => setMetrics([]));
  }, []);

  return (
    <>
      <Nav light />
      <main className="page about">
        <p className="kicker">Método</p>
        <h1>Como o sinal é feito.</h1>
        <p>
          Cotações periódicas entram na Bronze. A ANAC (VRA) alimenta atraso e cancelamento. Na Gold, regressão e
          séries estimam a variação do preço. A regra inicial: variação prevista ≥ +5% → COMPRAR; ≤ −5% → AGUARDAR;
          o restante → MONITORAR.
        </p>
        <p>
          A API não treina modelo. Ela lê a Gold exportada do Databricks Free (ou as amostras em{" "}
          <code>data/gold/sample</code>).
        </p>
        <div className="metrics">
          {metrics.map((m) => (
            <p key={m.model_name}>
              {m.model_name} · {m.family} · MAE {m.mae} · RMSE {m.rmse}
              {m.r2 != null ? ` · R² ${m.r2}` : ""}
            </p>
          ))}
        </div>
      </main>
    </>
  );
}
