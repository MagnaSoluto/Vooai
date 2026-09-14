"""Utilitário legado — Spec já materializada pelos notebooks 08–10.

A API lê diretamente `data/Spec/spec_modelos_risco/*.parquet`.
Use os notebooks para regenerar a Spec no Databricks/local.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "Spec" / "spec_modelos_risco"


def main() -> None:
    files = sorted(SPEC.glob("spec_modelos_risco_*.parquet")) if SPEC.exists() else []
    if not files:
        raise SystemExit(f"Nenhum parquet em {SPEC}. Rode o notebook 09.")
    print("Spec disponível:")
    for f in files:
        print(" ", f.relative_to(ROOT), f.stat().st_size)


if __name__ == "__main__":
    main()
