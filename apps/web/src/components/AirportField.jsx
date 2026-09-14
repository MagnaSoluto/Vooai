import { useEffect, useId, useRef, useState } from "react";
import { fetchAirports } from "../api.js";

export default function AirportField({ label, value, onChange, placeholder = "Cidade ou IATA" }) {
  const listId = useId();
  const wrapRef = useRef(null);
  const [query, setQuery] = useState(value || "");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setQuery(value || "");
  }, [value]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 1) {
      setItems([]);
      return undefined;
    }
    let cancel = false;
    const t = setTimeout(() => {
      setLoading(true);
      fetchAirports(q)
        .then((rows) => {
          if (!cancel) setItems(rows);
        })
        .catch(() => {
          if (!cancel) setItems([]);
        })
        .finally(() => {
          if (!cancel) setLoading(false);
        });
    }, 180);
    return () => {
      cancel = true;
      clearTimeout(t);
    };
  }, [query]);

  useEffect(() => {
    function onDoc(e) {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function pick(item) {
    const next = item.value;
    setQuery(item.label);
    onChange(next, item);
    setOpen(false);
  }

  return (
    <label className="field airport-field" ref={wrapRef}>
      <span>{label}</span>
      <input
        value={query}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          onChange(e.target.value, null);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && open && items[0]) {
            e.preventDefault();
            pick(items[0]);
          }
        }}
      />
      {open && query.trim() && (
        <ul id={listId} className="airport-suggest" role="listbox">
          {loading && <li className="muted">Buscando…</li>}
          {!loading && items.length === 0 && <li className="muted">Nenhum aeroporto</li>}
          {items.map((item) => (
            <li key={`${item.kind}-${item.value}-${item.iata}`}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(item)}>
                <strong>{item.kind === "city" ? item.municipio : item.iata}</strong>
                <span>{item.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </label>
  );
}
