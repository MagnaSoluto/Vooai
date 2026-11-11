const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const TOKEN_KEY = "vooai_token";
const EMAIL_KEY = "vooai_email";
// refresh fica em cookie HttpOnly (vooai_rt) — não guardar em localStorage

export class ApiError extends Error {
  constructor(status, detail) {
    const msg =
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.code || (detail ? "Erro na requisição" : `HTTP ${status}`);
    super(msg);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = typeof detail === "object" && detail ? detail.code : undefined;
  }
}

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function getEmail() {
  return localStorage.getItem(EMAIL_KEY) || "";
}

export function setSession({ token, email }) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  if (email) localStorage.setItem(EMAIL_KEY, email);
  // limpa legado inseguro
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("vooai_refresh");
  window.dispatchEvent(new Event("vooai-auth"));
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("vooai_refresh");
  localStorage.removeItem(EMAIL_KEY);
  window.dispatchEvent(new Event("vooai-auth"));
}

/** Só paths relativos do app (anti open-redirect). */
export function safeNextPath(raw, fallback = "/") {
  if (!raw || typeof raw !== "string") return fallback;
  const v = raw.trim();
  if (!v.startsWith("/") || v.startsWith("//") || v.includes("://")) return fallback;
  return v;
}

function authHeaders(extra = {}) {
  const token = getToken();
  const headers = { ...extra };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function parseError(res) {
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = body.detail ?? body;
  } catch {
    try {
      detail = await res.text();
    } catch {
      /* ignore */
    }
  }
  throw new ApiError(res.status, detail);
}

let refreshPromise = null;

async function tryRefresh() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const call = () =>
        fetch(`${API}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({}),
        });
      let res = await call();
      if (res.status === 401) {
        // Outra aba pode ter acabado de rotacionar o cookie: tenta 1x com o novo.
        await new Promise((r) => setTimeout(r, 400));
        res = await call();
      }
      if (!res.ok) {
        clearSession();
        return false;
      }
      const data = await res.json();
      setSession({
        token: data.access_token || data.token,
        email: data.email,
      });
      return true;
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function request(path, { method = "GET", body, auth = true, signal } = {}) {
  const opts = {
    method,
    credentials: "include",
    headers: auth
      ? authHeaders(body !== undefined ? { "Content-Type": "application/json" } : {})
      : body !== undefined
        ? { "Content-Type": "application/json" }
        : {},
    signal,
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  let res = await fetch(`${API}${path}`, opts);
  if (res.status === 401 && auth) {
    const ok = await tryRefresh();
    if (ok) {
      opts.headers = authHeaders(body !== undefined ? { "Content-Type": "application/json" } : {});
      res = await fetch(`${API}${path}`, opts);
    }
  }
  if (!res.ok) await parseError(res);
  if (res.status === 204) return null;
  return res.json();
}

async function getJson(path, { auth = true, signal } = {}) {
  return request(path, { auth, signal });
}

async function postJson(path, body, { auth = true, signal } = {}) {
  return request(path, { method: "POST", body, auth, signal });
}

export function searchFlights({
  origin,
  dest,
  date,
  returnDate,
  tripType,
  flexDates,
  signal,
}) {
  const q = new URLSearchParams({
    origin,
    dest,
    date,
  });
  if (tripType) q.set("trip_type", tripType);
  if (returnDate) q.set("return_date", returnDate);
  if (flexDates && flexDates !== "off") q.set("flex_dates", flexDates);
  return getJson(`/search?${q}`, { signal });
}

export function fetchAirports(q, { signal } = {}) {
  return getJson(`/airports?q=${encodeURIComponent(q)}`, { auth: false, signal });
}

export function fetchPricing({ tripType, flexDates, returnDate, signal } = {}) {
  const q = new URLSearchParams({
    trip_type: tripType || "ida",
    flex_dates: flexDates || "off",
  });
  if (returnDate) q.set("return_date", returnDate);
  return getJson(`/pricing?${q}`, { auth: false, signal });
}

export function fetchFlightDetail(params, { signal } = {}) {
  const q = new URLSearchParams(params);
  return getJson(`/flights/detail?${q}`, { signal });
}

function applyAuthSession(data) {
  setSession({
    token: data.access_token || data.token,
    email: data.email,
  });
  return data;
}

/** Cadastro: o servidor envia um código; a conta só é criada ao confirmar (verifyMagicLink). */
export function register(email, password) {
  return postJson("/auth/register", { email, password }, { auth: false });
}

export function login(email, password) {
  return postJson("/auth/login", { email, password }, { auth: false }).then(applyAuthSession);
}

export function requestMagicLink(email) {
  return postJson("/auth/magic-link", { email }, { auth: false });
}

export function verifyMagicLink(email, code) {
  return postJson("/auth/magic-link/verify", { email, code }, { auth: false }).then(applyAuthSession);
}

async function postLogout(path) {
  // Sem retry de refresh: logout não deve renovar sessão. O cookie HttpOnly
  // identifica a sessão mesmo com o access expirado.
  try {
    await fetch(`${API}${path}`, {
      method: "POST",
      credentials: "include",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: "{}",
    });
  } catch {
    /* rede fora: ainda assim limpa o lado do cliente */
  }
  clearSession();
}

export function logout() {
  return postLogout("/auth/logout");
}

/** Encerra todas as sessões da conta (todos os dispositivos). */
export async function logoutAll() {
  const res = await fetch(`${API}/auth/logout-all`, {
    method: "POST",
    credentials: "include",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: "{}",
  });
  if (!res.ok && res.status !== 401) await parseError(res);
  clearSession();
}

export function fetchWallet({ signal } = {}) {
  return getJson("/wallet", { signal });
}

export function fetchMe({ signal } = {}) {
  return getJson("/auth/me", { signal });
}

export function topup(amountBrl, { customerDocument, customerName } = {}) {
  const body = { amount_brl: amountBrl };
  if (customerDocument) body.customer_document = customerDocument;
  if (customerName) body.customer_name = customerName;
  return postJson("/wallet/topup", body);
}

export function fetchLedger(limit = 20) {
  return getJson(`/wallet/ledger?limit=${limit}`);
}

export function fetchHealth({ signal } = {}) {
  return getJson("/health", { auth: false, signal });
}

export function fetchMetrics({ signal } = {}) {
  return getJson("/models/metrics", { auth: false, signal });
}

export function fetchDashboard({ limit = 10, signal } = {}) {
  return getJson(`/dashboard/summary?limit=${limit}`, { auth: false, signal });
}

export function fetchReliability({ signal } = {}) {
  return getJson("/reliability", { auth: false, signal });
}

export function humanError(err) {
  if (!(err instanceof ApiError)) return err?.message || "Falha inesperada.";
  const d = err.detail;
  if (typeof d === "object" && d?.message) {
    if (d.code === "auth_failed") return d.message;
    if (d.code === "register_failed") return d.message;
    if (d.code === "magic_invalid") return d.message;
    if (d.code === "rate_limited") return d.message;
    if (d.code === "document_required") return d.message;
    if (d.code === "billing_failed") return d.message;
    if (d.code === "topup_min") return d.message;
    if (d.code === "topup_fee_exceeds") return d.message;
  }
  if (err.status === 401) return "Entre na conta para continuar.";
  if (err.status === 402) {
    if (d?.required_saldos != null) {
      return `Saldos insuficientes — precisa de ${Number(d.required_saldos).toLocaleString("pt-BR")} (você tem ${Number(d.balance_saldos ?? 0).toLocaleString("pt-BR")}).`;
    }
    if (d?.required_brl != null) {
      return `Saldo insuficiente — precisa de ${Number(d.required_brl).toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}.`;
    }
    return "Saldos insuficientes para esta busca.";
  }
  if (err.status === 429) return "Muitas consultas agora. Aguarde um minuto e tente de novo.";
  if (typeof d === "object" && d?.code === "billing_unavailable") {
    return "Recarga PIX indisponível no momento. Tente mais tarde.";
  }
  if (err.status === 502 && typeof d === "object" && d?.code === "billing_failed" && d?.message) {
    return d.message;
  }
  if (err.status >= 500) return "Não concluímos a operação. Tente de novo em instantes.";
  return err.message || "Não foi possível concluir.";
}
