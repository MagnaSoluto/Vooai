import { Link, useLocation } from "react-router-dom";
import Mark from "./Mark.jsx";

export default function Nav({ light = false }) {
  const { pathname } = useLocation();
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
      </div>
    </nav>
  );
}
