import { Link } from "react-router-dom";

export default function Nav({ light = false }) {
  return (
    <nav className={`site-nav${light ? " light" : ""}`}>
      <Link to="/">Busca</Link>
      <Link to="/metodo">Método</Link>
    </nav>
  );
}
