import { Link, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import Mark from "./Mark.jsx";
import { fetchWallet, getEmail, getToken, logout } from "../api.js";

export default function Nav({ light = false }) {
  const { pathname } = useLocation();
  const [token, setToken] = useState(getToken());
  const [balance, setBalance] = useState(null);

  useEffect(() => {
    function sync() {
      setToken(getToken());
    }
    window.addEventListener("vooai-auth", sync);
    sync();
    return () => window.removeEventListener("vooai-auth", sync);
  }, []);

  useEffect(() => {
    let cancel = false;
    const ac = new AbortController();
    if (!token) {
      setBalance(null);
      return undefined;
    }
    fetchWallet({ signal: ac.signal })
      .then((w) => {
        if (!cancel) setBalance(w.balance_saldos ?? null);
      })
      .catch(() => {
        if (!cancel) setBalance(null);
      });
    return () => {
      cancel = true;
      ac.abort();
    };
  }, [token]);

  return (
    <nav className={`site-nav${light ? " light" : ""}`} aria-label="Principal">
      <Link to="/" className="nav-brand" aria-label="VooAI — início">
        <Mark size={28} />
        <span>VooAI</span>
      </Link>
      <div className="nav-links">
        <Link to="/" className={pathname === "/" ? "is-current" : undefined}>
          Busca
        </Link>
        <Link
          to="/dashboard"
          className={pathname.startsWith("/dashboard") ? "is-current" : undefined}
        >
          Dashboard
        </Link>
        <Link to="/metodo" className={pathname === "/metodo" ? "is-current" : undefined}>
          Método
        </Link>
        <Link
          to="/conta"
          className={`nav-wallet${pathname.startsWith("/conta") ? " is-current" : ""}`}
        >
          {token
            ? balance != null
              ? `${Number(balance).toLocaleString("pt-BR")} saldos`
              : getEmail().split("@")[0] || "Conta"
            : "Conta"}
        </Link>
        {token ? (
          <button
            type="button"
            className="nav-logout"
            onClick={async () => {
              await logout();
              setToken("");
              setBalance(null);
            }}
          >
            Sair
          </button>
        ) : null}
      </div>
    </nav>
  );
}
