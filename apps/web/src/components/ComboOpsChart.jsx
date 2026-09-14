/** Combo: barras = volume (eixo esq.) · linhas = taxas % (eixo dir.). */

function fmtInt(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("pt-BR");
}

const DEFAULT_LINES = [
  { key: "cancel_pct", className: "cancel", label: "% cancelamento" },
  { key: "no_show_pct", className: "noshow", label: "% no-show" },
];

export default function ComboOpsChart({
  series,
  method,
  compact = false,
  lines,
  lineLabels,
}) {
  const rows = series || [];
  if (!rows.length) return <p className="muted">Sem série operacional.</p>;

  const lineDefs =
    lines ||
    (lineLabels
      ? [
          {
            key: "cancel_pct",
            className: "cancel",
            label: lineLabels.cancel_pct || "% cancelamento",
          },
          {
            key: lineLabels.delay_pct ? "delay_pct" : "no_show_pct",
            className: "noshow",
            label: lineLabels.delay_pct || lineLabels.no_show_pct || "% no-show",
          },
        ]
      : DEFAULT_LINES);

  const w = compact ? 640 : 720;
  const h = compact ? 220 : 260;
  const pad = { t: 18, r: 48, b: 36, l: 52 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const maxF = Math.max(1, ...rows.map((r) => r.flights || 0));
  const rates = rows.flatMap((r) => lineDefs.map((l) => r[l.key] || 0));
  const maxR = Math.max(3.5, ...rates) * 1.15;
  const n = rows.length;
  const band = innerW / n;
  const barW = Math.min(compact ? 22 : 28, band * 0.45);
  const xCenter = (i) => pad.l + band * i + band / 2;
  const yF = (v) => pad.t + innerH - ((v || 0) / maxF) * innerH;
  const yR = (v) => pad.t + innerH - ((v || 0) / maxR) * innerH;

  const linePath = (key) =>
    rows
      .map((r, i) => {
        const v = r[key];
        if (v == null) return null;
        const cmd = i === 0 || rows[i - 1]?.[key] == null ? "M" : "L";
        return `${cmd}${xCenter(i).toFixed(1)},${yR(v).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  const splitAt = rows.findIndex((r) => r.kind === "forecast");

  return (
    <div className={`dash-combo${compact ? " compact" : ""}`}>
      <svg
        className="dash-combo-svg"
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label="Volume e taxas operacionais"
      >
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <line
            key={t}
            x1={pad.l}
            x2={w - pad.r}
            y1={pad.t + innerH * (1 - t)}
            y2={pad.t + innerH * (1 - t)}
            className="dash-grid"
          />
        ))}
        {splitAt > 0 && (
          <line
            x1={pad.l + band * splitAt}
            x2={pad.l + band * splitAt}
            y1={pad.t}
            y2={pad.t + innerH}
            className="dash-split-line"
          />
        )}
        {rows.map((r, i) => (
          <rect
            key={`b-${r.month}`}
            x={xCenter(i) - barW / 2}
            y={yF(r.flights)}
            width={barW}
            height={Math.max(1, pad.t + innerH - yF(r.flights))}
            className={r.kind === "forecast" ? "dash-bar-f forecast" : "dash-bar-f"}
          />
        ))}
        {lineDefs.map((l) => (
          <path
            key={`p-${l.key}`}
            d={linePath(l.key)}
            className={`dash-line ${l.className}`}
            fill="none"
          />
        ))}
        {rows.map((r, i) => (
          <g key={`d-${r.month}`}>
            {lineDefs.map((l) =>
              r[l.key] != null ? (
                <circle
                  key={l.key}
                  cx={xCenter(i)}
                  cy={yR(r[l.key])}
                  r="3"
                  className={`dash-dot ${l.className}`}
                />
              ) : null,
            )}
            <text x={xCenter(i)} y={h - 10} textAnchor="middle" className="dash-axis">
              {r.label}
            </text>
          </g>
        ))}
        <text x={pad.l - 8} y={pad.t + 4} textAnchor="end" className="dash-axis">
          {fmtInt(maxF)}
        </text>
        <text x={pad.l - 8} y={pad.t + innerH} textAnchor="end" className="dash-axis">
          0
        </text>
        <text x={w - pad.r + 8} y={pad.t + 4} textAnchor="start" className="dash-axis">
          {maxR.toFixed(1)}%
        </text>
        <text x={w - pad.r + 8} y={pad.t + innerH} textAnchor="start" className="dash-axis">
          0%
        </text>
        {splitAt > 0 && (
          <text
            x={pad.l + band * splitAt + 4}
            y={pad.t + 12}
            className="dash-axis dash-forecast-tag"
          >
            previsão →
          </text>
        )}
      </svg>
      <div className="dash-legend">
        <span>
          <i className="lg-amber" /> Volume (barras)
        </span>
        {lineDefs.map((l) => (
          <span key={l.key}>
            <i className={l.className === "cancel" ? "lg-line-cancel" : "lg-line-noshow"} />{" "}
            {l.label}
          </span>
        ))}
        <span className="muted">sólidas = histórico · claras = previsão</span>
      </div>
      {method && <p className="tiny muted dash-chart-note">{method}</p>}
    </div>
  );
}
