/** Telemetria de produto VooAI — fail-open, sem PII/tokens. */

import { getToken } from "./api.js";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const ENABLED = String(import.meta.env.VITE_TELEMETRY ?? "1").toLowerCase() !== "0";
const ANON_KEY = "vooai_tel_anon";
const QUEUE_KEY = "vooai_tel_q";

const ALLOWED = new Set([
  "pageview",
  "search",
  "search_denied",
  "login",
  "register",
  "topup",
]);

function sessionAnon() {
  try {
    let id = sessionStorage.getItem(ANON_KEY);
    if (!id) {
      id =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem(ANON_KEY, id);
    }
    return id;
  } catch {
    return null;
  }
}

export function amountBucket(brl) {
  const v = Number(brl);
  if (!Number.isFinite(v)) return null;
  if (v < 5) return "0-5";
  if (v < 10) return "5-10";
  if (v < 50) return "10-50";
  if (v < 100) return "50-100";
  return "100+";
}

export function leadDaysBucket(isoDate) {
  if (!isoDate) return null;
  const d = new Date(`${String(isoDate).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const delta = Math.round((d - today) / 86400000);
  if (delta < 0) return "past";
  if (delta <= 7) return "0-7";
  if (delta <= 21) return "8-21";
  if (delta <= 60) return "22-60";
  return "60+";
}

function referrerHost() {
  try {
    if (!document.referrer) return null;
    return new URL(document.referrer).host || null;
  } catch {
    return null;
  }
}

function enqueue(event) {
  try {
    const raw = sessionStorage.getItem(QUEUE_KEY);
    const q = raw ? JSON.parse(raw) : [];
    q.push(event);
    sessionStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-40)));
  } catch {
    /* ignore */
  }
}

function drainQueue() {
  try {
    const raw = sessionStorage.getItem(QUEUE_KEY);
    if (!raw) return [];
    sessionStorage.removeItem(QUEUE_KEY);
    const q = JSON.parse(raw);
    return Array.isArray(q) ? q : [];
  } catch {
    return [];
  }
}

function send(batch) {
  if (!batch.length) return;
  const body = JSON.stringify({
    events: batch,
    session_anon: sessionAnon(),
    authenticated: Boolean(getToken()),
  });
  const url = `${API}/events`;
  try {
    if (typeof navigator !== "undefined" && navigator.sendBeacon) {
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon(url, blob)) return;
    }
  } catch {
    /* fall through */
  }
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    credentials: "omit",
    keepalive: true,
  }).catch(() => {
    batch.forEach(enqueue);
  });
}

/** Dispara evento de produto. Nunca lança. */
export function track(name, props = {}) {
  if (!ENABLED) return;
  const eventName = String(name || "")
    .trim()
    .toLowerCase()
    .slice(0, 40);
  if (!ALLOWED.has(eventName)) return;
  const clean = {};
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === "") continue;
    if (typeof v === "boolean" || typeof v === "number") clean[k] = v;
    else clean[k] = String(v).slice(0, 80);
  }
  const item = {
    name: eventName,
    props: clean,
    authenticated: Boolean(getToken()),
    session_anon: sessionAnon(),
  };
  const pending = drainQueue();
  send([...pending, item]);
}

export function trackPageview(path) {
  const p = (path || window.location.pathname || "/").split("?")[0];
  track("pageview", {
    path: p,
    referrer_host: referrerHost(),
  });
}
