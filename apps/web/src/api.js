const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function getJson(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json();
}

export function fetchRoutes() {
  return getJson("/routes");
}

export function searchQuotes(origin, dest, date) {
  const q = new URLSearchParams({ origin, dest });
  if (date) q.set("date", date);
  return getJson(`/quotes/search?${q}`);
}

export function fetchRecommendation(routeId) {
  return getJson(`/recommendations/${routeId}`);
}

export function fetchReliability(params = {}) {
  const q = new URLSearchParams();
  if (params.airline) q.set("airline", params.airline);
  if (params.route) q.set("route", params.route);
  const suffix = q.toString() ? `?${q}` : "";
  return getJson(`/reliability${suffix}`);
}

export function fetchMetrics() {
  return getJson("/models/metrics");
}
