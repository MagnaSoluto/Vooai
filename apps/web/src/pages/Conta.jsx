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
  register,
  requestMagicLink,
  safeNextPath,
  topup,
  verifyMagicLink,
} from "../api.js";
import { amountBucket, track } from "../telemetry.js";

/** Espelha MIN_TOPUP_BRL da API / MinRechargeBrl do Leads. */
const MIN_TOPUP = 5;
/** Taxa Asaas PIX padrão (mesma default da API). */
const ASAAS_FEE = 1.99;
const SALDO_UNIT = 0.12;

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
  const fee = Math.min(ASAAS_FEE, Math.max(0, bruto));
  const net = Math.round((bruto - fee) * 100) / 100;
  const saldos = net > 0 ? Math.floor(net / SALDO_UNIT + 1e-9) : 0;
  return { bruto, fee, net, saldos };
}

export default function Conta() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"), "/");
  const [mode, setMode] = useState("password"); // password | magic
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
        if (!on) setMode("password");
      })
      .catch(() => {
        if (!cancel) {
          setMagicAvailable(false);
          setMode("password");
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
      if (ex instanceof ApiError && ex.status === 401) {
        try {
          await register(email.trim(), password);
          track("register", { method: "password" });
          track("login", { method: "password" });
          setMsg("Conta criada — sessão ativa.");
          setPassword("");
          await refresh();
          if (params.get("next")) navigate(next);
          return;
        } catch (regEx) {
          if (regEx instanceof ApiError && /cadastrad/i.test(String(regEx.message))) {
            setErr("Senha incorreta para este e-mail.");
            return;
          }
          setErr(humanError(regEx));
          return;
        }
      }
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
      track("login", { method: "magic_link" });
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
          expected_saldos: w.expected_saldos ?? w.topup_breakdown?.saldos,
          topup_breakdown: w.topup_breakdown,
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
            ? "Cada busca consome saldos (ida = 1 saldo ≈ R$ 0,12). Recarga mínima "
            : magicAvailable
              ? "Entre com senha ou código por e-mail — sem login só com o endereço."
              : "Entre com e-mail e senha (mín. 8). Sem login só com o endereço."}
          {authed ? `${formatBrl(MIN_TOPUP)} via PIX (desconta taxa Asaas).` : ""}
        </p>

        {!authed ? (
          <div className="conta-card">
            {magicAvailable ? (
              <div className="trip-toggle" role="group" aria-label="Modo de acesso">
                <button
                  type="button"
                  className={mode === "password" ? "active" : ""}
                  onClick={() => setMode("password")}
                >
                  Senha
                </button>
                <button
                  type="button"
                  className={mode === "magic" ? "active" : ""}
                  onClick={() => setMode("magic")}
                >
                  Código por e-mail
                </button>
              </div>
            ) : null}

            {mode === "password" ? (
              <form onSubmit={onPassword}>
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
                    autoComplete="current-password"
                    minLength={8}
                    required
                  />
                </label>
                <button type="submit" className="cta" disabled={busy}>
                  {busy ? "…" : "Entrar / criar conta"}
                </button>
              </form>
            ) : (
              <>
                {!magicSent ? (
                  <form onSubmit={onMagicRequest}>
                    <label className="field">
                      <span>E-mail</span>
                      <input
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="voce@email.com"
                        required
                      />
                    </label>
                    <button type="submit" className="cta" disabled={busy}>
                      {busy ? "…" : "Enviar código"}
                    </button>
                  </form>
                ) : (
                  <form onSubmit={onMagicVerify}>
                    <p className="muted">Enviamos instruções para {masked}.</p>
                    {devCode ? (
                      <p className="muted mono">Dev code: {devCode}</p>
                    ) : null}
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
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => {
                        setMagicSent(false);
                        setDevCode("");
                      }}
                    >
                      Usar outro e-mail
                    </button>
                  </form>
                )}
              </>
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
              {wallet ? (
                <p className="muted" style={{ marginTop: 0 }}>
                  Equiv. {formatBrl(wallet.balance_brl ?? 0)} · 1 saldo ={" "}
                  {formatBrl(wallet.saldo_unit_brl ?? SALDO_UNIT)}
                </p>
              ) : null}

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
                Mínimo {formatBrl(MIN_TOPUP)}. Taxa Asaas ≈ {formatBrl(ASAAS_FEE)}{" "}
                por PIX. Você recebe{" "}
                <strong>{formatSaldos(topupPreview.saldos)}</strong> (líquido{" "}
                {formatBrl(topupPreview.net)}).
              </p>
              <button type="button" className="linkish" onClick={onLogout}>
                Sair
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
                    {formatBrl(pix.valor)} · status {pix.status}
                    {pix.expected_saldos != null
                      ? ` · ~${formatSaldos(pix.expected_saldos)} após confirmação`
                      : ""}
                  </p>
                  {pix.topup_breakdown ? (
                    <p className="muted">
                      Bruto {formatBrl(pix.topup_breakdown.pay_brl)} − Asaas{" "}
                      {formatBrl(pix.topup_breakdown.asaas_fee_brl)} = líquido{" "}
                      {formatBrl(pix.topup_breakdown.net_brl)}.
                    </p>
                  ) : null}
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
                  {pix.invoice_url ? (
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
                      <span className={`kind ${row.kind}`}>{row.kind}</span>
                      <span className="mono">
                        {row.kind === "debit" ? "−" : "+"}
                        {row.amount_saldos != null
                          ? formatSaldos(row.amount_saldos)
                          : Number(row.amount_brl).toLocaleString("pt-BR", {
                              style: "currency",
                              currency: "BRL",
                            })}
                      </span>
                      <small className="muted">{row.created_at}</small>
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
