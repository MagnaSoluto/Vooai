"""Ingestão ANAC VRA → SoR_voos_operacoes (Bronze operacional).

Fonte: dados abertos ANAC (mensal). Poll barato na box — sem Glue.

  python -m pipelines.ingest_anac_vra --poll
  python -m pipelines.ingest_anac_vra --year 2025 --month 12
  python -m pipelines.ingest_anac_vra --latest

Cadência sugerida: 1×/semana (poll). Load só quando houver mês novo.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx

from .paths import vra_sor_dir

ANAC_VRA_ROOT = (
    "https://sistemas.anac.gov.br/dadosabertos/"
    "Voos%20e%20opera%C3%A7%C3%B5es%20a%C3%A9reas/"
    "Voo%20Regular%20Ativo%20%28VRA%29"
)

MESES = {
    1: "01 - Janeiro",
    2: "02 - Fevereiro",
    3: "03 - Março",
    4: "04 - Abril",
    5: "05 - Maio",
    6: "06 - Junho",
    7: "07 - Julho",
    8: "08 - Agosto",
    9: "09 - Setembro",
    10: "10 - Outubro",
    11: "11 - Novembro",
    12: "12 - Dezembro",
}


def _month_folder(year: int, month: int) -> str:
    return f"{year}/{MESES[month]}"


def vra_csv_url(year: int, month: int) -> str:
    # pasta com acentos precisa de quote por segmento
    folder = MESES[month]
    y = str(year)
    # encode folder keeping spaces as %20
    enc_folder = quote(folder, safe=" -")
    fname = f"VRA_{year}{month:02d}.csv"
    return f"{ANAC_VRA_ROOT}/{y}/{enc_folder}/{fname}"


def local_names(year: int, month: int) -> list[str]:
    """Nomes aceitos no SoR local (histórico do grupo usa VRA_YYYYM sem zero)."""
    return [
        f"VRA_{year}{month:02d}.csv",
        f"VRA_{year}{month}.csv",  # ex. VRA_20266
    ]


def already_have(year: int, month: int) -> Path | None:
    dest = vra_sor_dir()
    for name in local_names(year, month):
        p = dest / name
        if p.exists() and p.stat().st_size > 1000:
            return p
    return None


def download_month(year: int, month: int, *, force: bool = False) -> Path:
    existing = already_have(year, month)
    if existing and not force:
        print(f"já existe: {existing}")
        return existing

    url = vra_csv_url(year, month)
    dest = vra_sor_dir()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"VRA_{year}{month:02d}.csv"
    print(f"baixando {url}")
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        r = client.get(url)
        if r.status_code == 404:
            raise FileNotFoundError(f"Mês ainda não publicado na ANAC: {year}-{month:02d}")
        r.raise_for_status()
        out.write_bytes(r.content)
    print(f"OK → {out} ({out.stat().st_size} bytes)")
    return out


def list_remote_months(year: int) -> list[int]:
    """Parseia o index HTML do ano e retorna meses com pasta."""
    url = f"{ANAC_VRA_ROOT}/{year}/"
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        html = r.text
    found = sorted({int(m) for m in re.findall(r"href=\"(\d{2})\s+-", html)})
    return found


def poll_new_months(*, years: list[int] | None = None) -> list[tuple[int, int]]:
    today = date.today()
    years = years or [today.year - 1, today.year]
    pending: list[tuple[int, int]] = []
    for y in years:
        try:
            months = list_remote_months(y)
        except Exception as exc:  # noqa: BLE001
            print(f"poll {y}: {exc}", file=sys.stderr)
            continue
        for m in months:
            if not already_have(y, m):
                pending.append((y, m))
    return pending


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingest ANAC VRA → SoR")
    p.add_argument("--poll", action="store_true", help="Lista meses remotos faltando no SoR")
    p.add_argument("--latest", action="store_true", help="Baixa o mês remoto mais recente faltante")
    p.add_argument("--year", type=int, default=0)
    p.add_argument("--month", type=int, default=0)
    p.add_argument("--force", action="store_true")
    p.add_argument("--download-missing", action="store_true", help="Baixa todos os faltantes do poll")
    args = p.parse_args(argv)

    if args.year and args.month:
        download_month(args.year, args.month, force=args.force)
        return 0

    pending = poll_new_months()
    print(f"meses faltantes no SoR: {pending or 'nenhum'}")

    if args.poll and not args.latest and not args.download_missing:
        return 0

    if args.latest:
        if not pending:
            print("nada a baixar")
            return 0
        y, m = pending[-1]
        download_month(y, m, force=args.force)
        return 0

    if args.download_missing:
        for y, m in pending:
            try:
                download_month(y, m, force=args.force)
            except Exception as exc:  # noqa: BLE001
                print(f"skip {y}-{m:02d}: {exc}", file=sys.stderr)
        return 0

    if not args.poll:
        p.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
