"""Materializa tabelas Gold em data/gold/ para a API local.

MVP: copia as amostras versionadas. Com Databricks Free, substitua
`copy_samples()` por download SQL / arquivos do Unity Catalog.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "gold" / "sample"
TARGET = ROOT / "data" / "gold"

TABLES = (
    "routes.csv",
    "quotes.csv",
    "recommendations.csv",
    "reliability.csv",
    "model_metrics.csv",
)


def copy_samples() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        src = SAMPLE / name
        if not src.exists():
            raise FileNotFoundError(f"Amostra ausente: {src}")
        dest = TARGET / name
        shutil.copyfile(src, dest)
        print(f"ok {dest.relative_to(ROOT)}")


def main() -> None:
    copy_samples()
    print("Gold local pronta. A API lê data/gold/*.csv (fallback: sample/).")


if __name__ == "__main__":
    main()
