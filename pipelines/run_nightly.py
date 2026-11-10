"""Orquestra jobs baratos da box (sem Glue / sem Kafka).

Passos:
  1) ingest ANAC poll (+ download latest se novo)
  2) collect_quotes (SerpAPI → SoR)
  3) etl_quotes (SoR → SoT → Spec cotacoes)
  4) publish_spec + reload API

Heavy (notebooks 08/09): só com --heavy e se houver mês ANAC novo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(module: str, *args: str) -> int:
    cmd = [sys.executable, "-m", module, *args]
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pipeline nightly VooAI (box barata)")
    p.add_argument("--skip-anac", action="store_true")
    p.add_argument("--skip-collect", action="store_true")
    p.add_argument("--skip-etl", action="store_true")
    p.add_argument("--skip-publish", action="store_true")
    p.add_argument("--dry-run-collect", action="store_true")
    p.add_argument("--max-routes", type=int, default=0)
    p.add_argument("--heavy", action="store_true", help="nbconvert 08+09 (caro em CPU/RAM)")
    args = p.parse_args(argv)

    rc = 0
    if not args.skip_anac:
        # poll + baixa só o mais recente faltante
        code = _run("pipelines.ingest_anac_vra", "--latest")
        if code not in (0, 1):
            rc = code

    if not args.skip_collect:
        cargs = []
        if args.dry_run_collect:
            cargs.append("--dry-run")
        if args.max_routes:
            cargs.extend(["--max-routes", str(args.max_routes)])
        code = _run("pipelines.collect_quotes", *cargs)
        if code != 0:
            rc = code

    if not args.skip_etl:
        code = _run("pipelines.etl_quotes")
        if code != 0:
            rc = code

    if not args.skip_publish:
        code = _run("pipelines.publish_spec")
        if code != 0:
            rc = code

    if args.heavy:
        nb = ROOT / "pipelines" / "run_heavy_etl.sh"
        if nb.exists():
            code = subprocess.call(["bash", str(nb)], cwd=str(ROOT))
            if code != 0:
                rc = code
        else:
            print("AVISO: run_heavy_etl.sh ausente — pule --heavy ou rode notebooks 08/09 manualmente")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
