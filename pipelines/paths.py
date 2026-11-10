"""Paths do lakehouse local / box (SoR → SoT → Spec)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    raw = os.getenv("VOOAI_DATA_DIR", "").strip()
    return Path(raw) if raw else ROOT / "data"


def sor_dir() -> Path:
    return data_dir() / "SoR"


def sot_dir() -> Path:
    return data_dir() / "SoT"


def spec_dir() -> Path:
    raw = os.getenv("VOOAI_SPEC_DIR", "").strip()
    return Path(raw) if raw else data_dir() / "Spec"


def cotacoes_sor_dir() -> Path:
    return sor_dir() / "SoR_cotacoes"


def cotacoes_sot_dir() -> Path:
    return sot_dir() / "SoT_cotacoes"


def cotacoes_spec_dir() -> Path:
    return spec_dir() / "spec_cotacoes"


def vra_sor_dir() -> Path:
    return sor_dir() / "SoR_voos_operacoes"


def rotas_mvp_md() -> Path:
    return ROOT / "docs" / "rotas-mvp.md"
