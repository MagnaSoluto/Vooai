"""Publica Spec no volume da API e pede reload (invalida lru_cache).

  python -m pipelines.publish_spec
  python -m pipelines.publish_spec --reload-url http://127.0.0.1:8000/admin/reload-spec
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import httpx

from .paths import ROOT, cotacoes_spec_dir, spec_dir


def sync_cotacoes_into_spec() -> list[Path]:
    """Garante que spec_cotacoes está sob data/Spec (já é o path padrão)."""
    src = cotacoes_spec_dir()
    if not src.exists():
        return []
    return sorted(src.glob("spec_cotacoes_*.parquet"))


def reload_api(url: str, token: str) -> None:
    headers = {"X-VooAI-Admin-Token": token} if token else {}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers)
        r.raise_for_status()
        print("reload:", r.json())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Publish Spec + reload API")
    p.add_argument(
        "--reload-url",
        default=os.getenv("VOOAI_RELOAD_URL", "http://127.0.0.1:8000/admin/reload-spec"),
    )
    p.add_argument("--no-reload", action="store_true")
    p.add_argument(
        "--copy-from",
        default="",
        help="Diretório Spec externo para rsync leve → VOOAI_SPEC_DIR",
    )
    args = p.parse_args(argv)

    files = sync_cotacoes_into_spec()
    print(f"spec_cotacoes: {len(files)} arquivo(s) em {cotacoes_spec_dir()}")
    for f in files[-3:]:
        print(" ", f.relative_to(ROOT) if f.is_relative_to(ROOT) else f)

    if args.copy_from:
        src = Path(args.copy_from)
        dst = spec_dir()
        if not src.is_dir():
            print(f"ERRO: {src} não é diretório", file=sys.stderr)
            return 2
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
            print(f"copied {item.name} → {target}")

    if args.no_reload:
        return 0

    token = os.getenv("VOOAI_ADMIN_TOKEN", "").strip()
    if not token:
        print("AVISO: VOOAI_ADMIN_TOKEN vazio — reload pode falhar (401).")
    try:
        reload_api(args.reload_url, token)
    except Exception as exc:  # noqa: BLE001
        print(f"reload falhou (Spec já no disco): {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
