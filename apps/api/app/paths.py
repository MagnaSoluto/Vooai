"""Resolução de pastas SoR / SoT / Spec."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


HERE = Path(__file__).resolve()
# Monorepo local: apps/api/app/paths.py → parents[3] = repo root.
# Imagem Docker: /app/app/paths.py → use VOOAI_DATA_DIR (obrigatório em prod).
try:
    REPO_ROOT = HERE.parents[3]
except IndexError:
    REPO_ROOT = HERE.parents[min(2, len(HERE.parents) - 1)]


@lru_cache(maxsize=1)
def data_root() -> Path:
    env = os.environ.get("VOOAI_DATA_DIR")
    if env:
        return Path(env).resolve()
    return (REPO_ROOT / "data").resolve()


def sot_dir() -> Path:
    return data_root() / "SoT"


def spec_dir() -> Path:
    override = os.environ.get("VOOAI_SPEC_DIR") or os.environ.get("VOOAI_GOLD_DIR")
    if override:
        return Path(override).resolve()
    return data_root() / "Spec"


def latest_glob(pattern: str) -> Path:
    import glob

    files = glob.glob(pattern, recursive=True)
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo em {pattern}")
    return Path(max(files, key=os.path.getmtime))
