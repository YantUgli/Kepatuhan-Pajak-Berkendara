"""Paket ETL star schema kepatuhan pajak kendaraan bermotor Jawa Barat.

Alur: extract -> transform -> build_star -> validate -> export (etl/run.py).

Semua path di paket ini RELATIF terhadap root repo (lihat ``ROOT_PROYEK``),
tidak ada path absolut lokal, dan tidak ada akses jaringan sama sekali.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

# etl/__init__.py -> etl/ -> root repo
ROOT_PROYEK: Path = Path(__file__).resolve().parent.parent

KONFIG_DEFAULT: Path = ROOT_PROYEK / "config" / "sources.yaml"
DIR_RAW_DEFAULT: Path = ROOT_PROYEK / "data" / "raw"
DIR_PROCESSED_DEFAULT: Path = ROOT_PROYEK / "data" / "processed"

__all__ = [
    "ROOT_PROYEK",
    "KONFIG_DEFAULT",
    "DIR_RAW_DEFAULT",
    "DIR_PROCESSED_DEFAULT",
    "__version__",
]
