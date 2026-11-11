import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Nav from "../components/Nav.jsx";
import AdSlot from "../components/AdSlot.jsx";
import {
  ApiError,
  fetchLedger,
  fetchPricing,
  fetchWallet,
  getEmail,
  getToken,
  humanError,
  login,
  logout,
  logoutAll,
  register,
  requestMagicLink,
  safeNextPath,
  topup,
  verifyMagicLink,
} from "../api.js";
import { amountBucket, track } from "../telemetry.js";

/** Espelha MIN_TOPUP_BRL da API / MinRechargeBrl do Leads. */
const MIN_TOPUP = 5;
/** Custo fixo do PIX (espelha a API) — usado só na prévia de saldos, nunca exibido. */
const PIX_FEE = 1.99;
const SALDO_UNIT = 0.12;

const LEDGER_LABEL = {
  debit: "Busca",
  credit: "Recarga",
  refund: "Estorno",
};

function formatDateTime(value) {
  if (!value) return "";
  const d = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function formatBrl(value) {
  return Number(value).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatSaldos(n) {
  const v = Number(n) || 0;
  return `${v.toLocaleString("pt-BR")} ${v === 1 ? "saldo" : "saldos"}`;
}

function previewTopup(amountBrl) {
  const bruto = Number(amountBrl) || 0;
  const fee = Math.min(PIX_FEE, Math.max(0, bruto));
  const net = Math.round((bruto - fee) * 100) / 100;
  const saldos = net > 0 ? Math.floor(net / SALDO_UNIT + 1e-9) : 0;
  return { bruto, fee, net, saldos };
}

export default function Conta() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"), "/");
  const [mode, setMode] = useState("password"); // password | signup | magic
  const [email, setEmail] = useState(getEmail() || "");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [magicSent, setMagicSent] = useState(false);
  const [devCode, setDevCode] = useState("");
  const [amount, setAmount] = useState(String(MIN_TOPUP));
  const [document, setDocument] = useState("");
  const [wallet, setWallet] = useState(null);
  const [ledger, setLedger] = useState([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [pix, setPix] = useState(null);
  const [paidNotice, setPaidNotice] = useState(null);
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const [magicAvailable, setMagicAvailable] = useState(false);

  useEffect(() => {
    let cancel = false;
    fetchPricing({})
      .then((p) => {
        if (cancel) return;
        const on = Boolean(p.magic_link_available);
        setMagicAvailable(on);
        if (!on) setMode((m) => (m === "magic" ? "password" : m));
      })
      .catch(() => {
        if (!cancel) {
          setMagicAvailable(false);
          setMode((m) => (m === "magic" ? "password" : m));
        }
      });
    return () => {
      cancel = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setWallet(null);
      setLedger([]);
      setAuthed(false);
      return null;
    }
    try {
      const [w, l] = await Promise.all([fetchWallet(), fetchLedger(20)]);
      const entries = l.entries || [];
      setWallet(w);
      setLedger(entries);
      setAuthed(true);
      return { wallet: w, ledger: entries };
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setWallet(null);
        setAuthed(false);
      }
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
    const onAuth = () => {
      setAuthed(Boolean(getToken()));
      refresh();
    };
    window.addEventListener("vooai-auth", onAuth);
    return () => window.removeEventListener("vooai-auth", onAuth);
  }, [refresh]);

  // Poll lento do saldo (igual ContaPage Leads — 15s).
  useEffect(() => {
    if (!authed) return undefined;
    const t = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(t);
  }, [authed, refresh]);

  // Com PIX aberto: poll rápido e fecha quando o webhook creditar.
  useEffect(() => {
    if (!pix?.cobranca_id) return undefined;
    let stopped = false;
    const chargeRef = `recharge:${pix.cobranca_id}`;

    const tick = async () => {
      try {
        const data = await refresh();
        if (stopped || !data) return;
        const paidRow = data.ledger.find((row) => row.search_ref === chargeRef);
        if (!paidRow) return;
        // `topup` paid vem do webhook (API); aqui só fecha o PIX na UI.
        setPaidNotice({
          amountBrl: Number(pix.valor) || 0,
          saldos: paidRow.amount_saldos ?? pix.expected_saldos ?? null,
        });
        setPix(null);
        setErr("");
        setMsg("");
      } catch {
        // mantém aguardando
      }
    };

    tick();
    const t = window.setInterval(tick, 3000);
    return () => {
      stopped = true;
      window.clearInterval(t);
    };
  }, [pix, refresh]);

  async function onPassword(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await login(email.trim(), password);
      track("login", { method: "password" });
      setMsg("Sessão ativa — saldo pronto para consultar.");
      setPassword("");
      await refresh();
      if (params.get("next")) navigate(next);
    } catch (ex) {
      // Mensagem única: não revela se o e-mail tem conta.
      setErr(humanError(ex));
    } finally {
      setBusy(false);
    }
  }

  async function onSignup(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setMsg("");
    setDevCode("");
    try {
      const r = await register(email.trim(), password);
      track("register", { method: "password" });
      setPassword("");
      setMagicSent(true);
      if (r.dev_code) setDevCode(r.dev_code);
      setMsg(
        r.message ||
          "Se o e-mail for válido, enviamos um código de acesso.",
      );
    } catch (ex) {
      setErr(humanError(ex));
    } finally {
      setBusy(false);
    }
  }

  function switchMode(m) {
    setMode(m);
    setMagicSent(false);
    setDevCode("");
    setCode("");
    setErr("");
    setMsg("");
  }

  async function onLogoutAll() {
    if (!window.confirm("Encerrar a sessão em todos os dispositivos?")) return;
    setBusy(true);
    try {
      await logoutAll();
      setWallet(null);
      setLedger([]);
      setPix(null);
      setPaidNotice(null);
      setAuthed(false);
      setMsg("Sessões encerradas em todos os dispositivos.");
    } catch (ex) {
      setErr(humanError(ex));
    } finally {
      setBusy(false);
    }
  }

  async function onMagicRequest(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setMsg("");
    setDevCode("");
    try {
      const r = await requestMagicLink(email.trim());
      if (r.sent === false && !r.dev_code) {
        setMagicSent(false);
        setErr(
          r.message ||
            "Código por e-mail indisponível no momento. Entre com senha.",
        );
        setMode("password");
        return;
      }
      setMagicSent(true);
      if (r.dev_code) setDevCode(r.dev_code);
      setMsg(r.message || "Se o e-mail for válido, enviamos um código de acesso.");
    } catch (ex) {
      setErr(humanError(ex));
    } finally {
      setBusy(false);
    }
  }

  async function onMagicVerify(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await verifyMagicLink(email.trim(), code.trim());
      track("login", { method: mode === "signup" ? "signup_code" : "magic_link" });
      setMsg("Sessão ativa — saldo pronto para consultar.");
      setCode("");
      await refresh();
      if (params.get("next")) navigate(next);
    } catch (ex) {
      setErr(humanError(ex));
    } finally {
      setBusy(false);
    }
  }

  async function onTopup(e) {
    e.preventDefault();
    if (pix) {
      setErr("Cancele o PIX atual antes de gerar outro.");
      return;
    }
    const value = Number(String(amount).replace(",", "."));
    if (!Number.isFinite(value) || value < MIN_TOPUP) {
      setErr(`Valor mínimo é ${formatBrl(MIN_TOPUP)}.`);
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    setPaidNotice(null);
    try {
      const digits = document.replace(/\D/g, "");
      if (digits.length !== 11 && digits.length !== 14) {
        setErr("Informe CPF (11 dígitos) ou CNPJ (14 dígitos) para gerar o PIX.");
        return;
      }
      const w = await topup(value, { customerDocument: digits });
      if (w.provider === "stub_local" || w.status === "pago") {
        track("topup", { status: "paid", amount_bucket: amountBucket(value) });
        setMsg(`Recarga de ${formatBrl(value)} creditada.`);
        setWallet(w);
        setPix(null);
      } else if (w.charge) {
        track("topup", { status: "created", amount_bucket: amountBucket(value) });
        setPix({
          ...w.charge,
          expected_saldos: w.expected_saldos ?? null,
        });
        setMsg("");
      } else {
        track("topup", { status: "created", amount_bucket: amountBucket(value) });
        setMsg(w.note || "Cobrança criada.");
      }
      await refresh();
      window.dispatchEvent(new Event("vooai-auth"));
    } catch (ex) {
      setErr(humanError(ex));
    } finally {
      setBusy(false);
    }
  }

  function cancelPix() {
    setPix(null);
    setErr("");
    setMsg("");
  }

  async function onLogout() {
    await logout();
    setWallet(null);
    setLedger([]);
    setPix(null);
    setPaidNotice(null);
    setAuthed(false);
    setMsg("Saiu da conta.");
  }

  const masked =
    email && email.includes("@")
      ? `${email.slice(0, 2)}•••@${email.split("@")[1]}`
      : "seu e-mail";

  const topupPreview = previewTopup(String(amount).replace(",", "."));

  return (
    <>
      <Nav light />
      <main className="page conta anim-fade-in-bottom">
        <p className="kicker">Conta</p>
        <h1>{authed ? "Saldo para ver o sinal." : "Acesse o sinal."}</h1>
        <p className="muted">
          {authed
            ? `Cada busca de ida consome 1 saldo. Recarregue via PIX a partir de ${formatBrl(MIN_TOPUP)}.`
            : magicAvailable
              ? "Entre com senha ou código por e-mail."
              : "Entre com e-mail e senha (mín. 8 caracteres)."}
        </p>

        {!authed ? (
          <div className="conta-card">
            <div className="trip-toggle" role="group" aria-label="Modo de acesso">
              <button
                type="button"
                className={mode === "password" ? "active" : ""}
                onClick={() => switchMode("password")}
              >
                Entrar
              </button>
              <button
                type="button"
                className={mode === "signup" ? "active" : ""}
                onClick={() => switchMode("signup")}
              >
                Criar conta
              </button>
              {magicAvailable ? (
                <button
                  type="button"
                  className={mode === "magic" ? "active" : ""}
                  onClick={() => switchMode("magic")}
                >
                  Código por e-mail
                </button>
              ) : null}
            </div>

            {magicSent ? (
              <form onSubmit={onMagicVerify}>
                <p className="muted">
                  Se {masked} puder receber, enviamos um código. Ele vale por 30 minutos.
                </p>
                {devCode ? <p className="muted mono">Dev code: {devCode}</p> : null}
                <label className="field">
                  <span>Código</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                  />
                </label>
                <button type="submit" className="cta" disabled={busy}>
                  {busy ? "…" : "Confirmar"}
                </button>
                <button type="button" className="linkish" onClick={() => switchMode(mode)}>
                  Usar outro e-mail
                </button>
              </form>
            ) : mode === "magic" ? (
              <form onSubmit={onMagicRequest}>
                <label className="field">
                  <span>E-mail</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="voce@email.com"
                    autoComplete="username"
                    required
                  />
                </label>
                <button type="submit" className="cta" disabled={busy}>
                  {busy ? "…" : "Enviar código"}
                </button>
              </form>
            ) : (
              <form onSubmit={mode === "signup" ? onSignup : onPassword}>
                <label className="field">
                  <span>E-mail</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="voce@email.com"
                    autoComplete="username"
                    required
                  />
                </label>
                <label className="field">
                  <span>Senha (mín. 8)</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete={mode === "signup" ? "new-password" : "current-password"}
                    minLength={8}
                    maxLength={200}
                    required
                  />
                </label>
                <button type="submit" className="cta" disabled={busy}>
                  {busy ? "…" : mode === "signup" ? "Criar conta" : "Entrar"}
                </button>
                {mode === "signup" ? (
                  <p className="muted">Enviaremos um código para confirmar o e-mail.</p>
                ) : null}
              </form>
            )}
          </div>
        ) : (
          <div className="conta-grid">
            <section className="conta-card">
              <p className="mono conta-email">{getEmail()}</p>
              <p className="conta-balance">
                <span>Saldos</span>
                <strong>
                  {wallet
                    ? formatSaldos(wallet.balance_saldos ?? 0)
                    : "—"}
                </strong>
              </p>

              {paidNotice ? (
                <div className="pix-paid" role="status">
                  <strong>PIX confirmado</strong>
                  <span>
                    {paidNotice.saldos != null
                      ? `${formatSaldos(paidNotice.saldos)} creditados.`
                      : `${formatBrl(paidNotice.amountBrl)} na conta.`}
                  </span>
                  <button
                    type="button"
                    className="linkish"
                    onClick={() => setPaidNotice(null)}
                  >
                    Fechar
                  </button>
                </div>
              ) : null}

              <form className="topup-row" onSubmit={onTopup}>
                <label className="field">
                  <span>Recarregar (R$)</span>
                  <input
                    type="number"
                    min={MIN_TOPUP}
                    step="0.01"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    required
                    disabled={Boolean(pix)}
                  />
                </label>
                <label className="field">
                  <span>CPF ou CNPJ</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="off"
                    placeholder="000.000.000-00"
                    value={document}
                    onChange={(e) => setDocument(e.target.value)}
                    required
                    disabled={Boolean(pix)}
                  />
                </label>
                <button type="submit" className="cta" disabled={busy || Boolean(pix)}>
                  {busy ? "…" : pix ? "Aguardando PIX" : "Recarregar"}
                </button>
              </form>
              <p className="muted" style={{ marginTop: 0 }}>
                Mínimo {formatBrl(MIN_TOPUP)}. Você recebe{" "}
                <strong>{formatSaldos(topupPreview.saldos)}</strong>.
              </p>
              <button type="button" className="linkish" onClick={onLogout}>
                Sair
              </button>{" "}
              <button
                type="button"
                className="linkish"
                onClick={onLogoutAll}
                disabled={busy}
              >
                Sair de todos os dispositivos
              </button>
              {pix && (
                <div className="pix-box pix-box--pending">
                  <div className="pix-box__head">
                    <h2>Pague com PIX</h2>
                    <button type="button" className="linkish" onClick={cancelPix}>
                      Cancelar PIX
                    </button>
                  </div>
                  <p className="muted">
                    {formatBrl(pix.valor)}
                    {pix.expected_saldos != null
                      ? ` · ${formatSaldos(pix.expected_saldos)} após confirmação`
                      : ""}
                  </p>
                  <p className="pix-box__waiting" role="status">
                    Aguardando pagamento… os saldos atualizam sozinhos assim que
                    o PIX confirmar.
                  </p>
                  {pix.qr_base64 ? (
                    <img
                      className="pix-qr"
                      alt="QR Code PIX"
                      src={
                        pix.qr_base64.startsWith("data:")
                          ? pix.qr_base64
                          : `data:image/png;base64,${pix.qr_base64}`
                      }
                    />
                  ) : null}
                  {pix.copia_e_cola ? (
                    <label className="field">
                      <span>Copia e cola</span>
                      <textarea readOnly rows={4} value={pix.copia_e_cola} />
                    </label>
                  ) : null}
                  {/^https:\/\//i.test(String(pix.invoice_url || "")) ? (
                    <a
                      className="cta inline"
                      href={pix.invoice_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Abrir fatura
                    </a>
                  ) : null}
                </div>
              )}
            </section>
            <section className="conta-card">
              <h2>Extrato</h2>
              {ledger.length === 0 ? (
                <p className="muted">Nenhuma movimentação ainda.</p>
              ) : (
                <ul className="ledger-list">
                  {ledger.map((row) => (
                    <li key={row.id}>
                      <span className={`kind ${row.kind}`}>
                        {LEDGER_LABEL[row.kind] || "Movimentação"}
                      </span>
                      <span className="mono">
                        {row.kind === "debit" ? "−" : "+"}
                        {row.amount_saldos != null
                          ? formatSaldos(row.amount_saldos)
                          : Number(row.amount_brl).toLocaleString("pt-BR", {
                              style: "currency",
                              currency: "BRL",
                            })}
                      </span>
                      <small className="muted">{formatDateTime(row.created_at)}</small>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}

        {msg && <p className="status ok-box">{msg}</p>}
        {err && <p className="status error-box">{err}</p>}
        <AdSlot />
        <p className="muted" style={{ marginTop: "2rem" }}>
          <Link to="/">← Voltar à busca</Link>
        </p>
      </main>
    </>
  );
}
