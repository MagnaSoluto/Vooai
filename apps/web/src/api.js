const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function getJson(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail || res.statusText);
  }
  return res.json();
}

export function searchFlights({
  origin,
  dest,
  date,
  returnDate,
  tripType = "ida",
  flexDates = "off",
}) {
  const q = new URLSearchParams({ origin, dest, date, trip_type: tripType });
  if (tripType === "ida_volta" && returnDate) q.set("return_date", returnDate);
  if (flexDates && flexDates !== "off") q.set("flex_dates", flexDates);
  return getJson(`/search?${q}`);
}

export function fetchAirports(q) {
  return getJson(`/airports?q=${encodeURIComponent(q)}`);
}

export function fetchReliability() {
  return getJson("/reliability");
}

export function fetchMetrics() {
  return getJson("/models/metrics");
}

export function fetchHealth() {
  return getJson("/health");
}

export function fetchDashboard({ limit = 10 } = {}) {
  const q = new URLSearchParams({ limit: String(limit) });
  return getJson(`/dashboard/summary?${q}`);
}

export function fetchFlightDetail({
  companhia,
  companhia_chave,
  iata_origin,
  iata_destination,
  date,
  preco_brl,
}) {
  const q = new URLSearchParams();
  if (companhia) q.set("companhia", companhia);
  if (companhia_chave) q.set("companhia_chave", companhia_chave);
  if (iata_origin) q.set("iata_origin", iata_origin);
  if (iata_destination) q.set("iata_destination", iata_destination);
  if (date) q.set("date", String(date).slice(0, 10));
  if (preco_brl != null) q.set("preco_brl", String(preco_brl));
  return getJson(`/flights/detail?${q}`);
}
