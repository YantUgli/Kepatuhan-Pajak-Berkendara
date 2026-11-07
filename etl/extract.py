"""Tahap EXTRACT: membaca CSV mentah dari ``data/raw/``.

PENTING (Bagian 3 brief): portal opendata.jabarprov.go.id berada di belakang
Cloudflare dan menolak request otomatis (403 / CF challenge). Modul ini
**sengaja tidak punya akses jaringan sama sekali** -- tidak ada import
``requests``/``httpx``/``urllib``. File mentah diunduh manual lewat browser lalu
diletakkan di ``data/raw/``.

Bila ada file wajib yang belum ada, ETL gagal cepat dengan pesan yang menyebut
nama file mana yang kurang beserta nama dataset aslinya di portal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from . import KONFIG_DEFAULT, ROOT_PROYEK

URL_KATALOG = "https://opendata.jabarprov.go.id/id/dataset"
URL_BAPENDA = "https://bapenda.jabarprov.go.id/open-data-jabar/"


class BerkasMentahHilangError(FileNotFoundError):
    """Satu atau lebih CSV wajib belum ada di ``data/raw/``."""


class KonfigurasiTidakValidError(ValueError):
    """Isi ``config/sources.yaml`` tidak memenuhi bentuk yang diharapkan."""


@dataclass(frozen=True)
class TabelMentah:
    """Satu tabel mentah beserta konteks konfigurasinya."""

    alias: str
    path: Path
    df: pd.DataFrame
    konfig: dict[str, Any]

    @property
    def jumlah_baris(self) -> int:
        return len(self.df)


# --------------------------------------------------------------------------- #
# Konfigurasi
# --------------------------------------------------------------------------- #
def muat_konfigurasi(path_konfig: str | Path | None = None) -> dict[str, Any]:
    """Baca ``config/sources.yaml`` dan validasi kunci minimalnya."""
    path = Path(path_konfig) if path_konfig else KONFIG_DEFAULT
    if not path.exists():
        raise KonfigurasiTidakValidError(
            f"File konfigurasi tidak ditemukan: {_relatif(path)}"
        )

    with path.open("r", encoding="utf-8") as f:
        konfig = yaml.safe_load(f) or {}

    if not isinstance(konfig, dict):
        raise KonfigurasiTidakValidError(
            f"{_relatif(path)} harus berupa mapping YAML di level teratas."
        )
    if "sumber" not in konfig or not isinstance(konfig["sumber"], dict):
        raise KonfigurasiTidakValidError(
            f"{_relatif(path)} wajib punya blok `sumber:` berisi minimal satu dataset."
        )

    konfig.setdefault("meta", {})
    konfig.setdefault("alias_kolom", {})
    konfig.setdefault("normalisasi_teks", {})
    konfig.setdefault("monetisasi", {})
    konfig.setdefault("sumber_opsional", {})
    return konfig


def path_sumber(konfig_sumber: dict[str, Any], root: Path | None = None) -> Path:
    """Resolusi path file sebuah sumber relatif terhadap root repo."""
    root = root or ROOT_PROYEK
    berkas = Path(konfig_sumber.get("file", ""))
    return berkas if berkas.is_absolute() else root / berkas


# --------------------------------------------------------------------------- #
# Pemeriksaan keberadaan file
# --------------------------------------------------------------------------- #
def periksa_berkas_mentah(
    konfig: dict[str, Any], root: Path | None = None
) -> dict[str, Path]:
    """Pastikan semua sumber ``wajib: true`` ada. Raise bila ada yang kurang.

    Mengembalikan mapping ``alias -> path`` untuk file wajib yang tersedia.
    """
    root = root or ROOT_PROYEK
    tersedia: dict[str, Path] = {}
    hilang: list[tuple[str, Path, str]] = []

    for alias, ksum in konfig["sumber"].items():
        path = path_sumber(ksum, root)
        if not ksum.get("wajib", True):
            if path.exists():
                tersedia[alias] = path
            continue
        if path.exists():
            tersedia[alias] = path
        else:
            hilang.append((alias, path, str(ksum.get("deskripsi", "")).strip()))

    if hilang:
        raise BerkasMentahHilangError(_pesan_berkas_hilang(hilang, root))
    return tersedia


def _pesan_berkas_hilang(
    hilang: list[tuple[str, Path, str]], root: Path
) -> str:
    baris = [
        "",
        "=" * 78,
        "ETL DIHENTIKAN: file CSV mentah belum lengkap di data/raw/.",
        "=" * 78,
        "",
        f"Ada {len(hilang)} file wajib yang belum ada:",
        "",
    ]
    for alias, path, deskripsi in hilang:
        baris.append(f"  [-] {_relatif(path, root)}")
        baris.append(f"      alias    : {alias}")
        if deskripsi:
            baris.append(f"      dataset  : {deskripsi}")
        baris.append("")
    baris += [
        "Cara memperbaiki (extract MANUAL -- portal mem-block bot, lihat README):",
        "  1. Buka katalog dataset lewat browser:",
        f"       {URL_KATALOG}",
        f"       {URL_BAPENDA}",
        "  2. Cari dataset sesuai deskripsi di atas, klik Unduh -> CSV",
        "     (portal memberi .zip berisi CSV + metadata PDF).",
        "  3. Ekstrak .zip, ganti nama CSV-nya persis seperti path di atas,",
        "     lalu taruh di data/raw/.",
        "  4. Jalankan ulang: pipenv run python -m etl.run",
        "",
        "Catatan: ETL ini TIDAK mengunduh sendiri dari portal (Cloudflare 403).",
        "=" * 78,
    ]
    return "\n".join(baris)


# --------------------------------------------------------------------------- #
# Pembacaan CSV
# --------------------------------------------------------------------------- #
def baca_csv(
    path: Path, encoding: str = "utf-8", sep: str | None = None
) -> pd.DataFrame:
    """Baca CSV mentah apa adanya (semua kolom dibaca sebagai string).

    Membaca sebagai string disengaja: pembersihan tipe data dilakukan di
    ``transform.py`` supaya pemisah ribuan/koma desimal tidak dirusak pandas.
    ``sep=None`` memakai sniffing pemisah (butuh engine="python").
    """
    opsi: dict[str, Any] = {"dtype": str, "keep_default_na": True}
    if sep in (None, "auto", ""):
        opsi["sep"] = None
        opsi["engine"] = "python"
    else:
        opsi["sep"] = sep

    for enc in _kandidat_encoding(encoding):
        try:
            df = pd.read_csv(path, encoding=enc, **opsi)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - hanya bila semua encoding gagal
        raise UnicodeDecodeError(
            "utf-8", b"", 0, 1, f"Gagal membaca {_relatif(path)} dengan encoding manapun"
        )

    df.attrs["sumber_file"] = str(path)
    return df


def _kandidat_encoding(encoding: str) -> list[str]:
    """Encoding utama + cadangan umum untuk CSV instansi (sering cp1252/latin-1)."""
    kandidat = [encoding or "utf-8", "utf-8-sig", "cp1252", "latin-1"]
    hasil: list[str] = []
    for enc in kandidat:
        if enc not in hasil:
            hasil.append(enc)
    return hasil


# --------------------------------------------------------------------------- #
# Orkestrasi tahap extract
# --------------------------------------------------------------------------- #
def ekstrak(
    konfig: dict[str, Any], root: Path | None = None
) -> dict[str, TabelMentah]:
    """Baca semua sumber yang terdaftar di ``sumber:``.

    Sumber ``wajib: false`` yang filenya tidak ada akan dilewati tanpa error.
    """
    root = root or ROOT_PROYEK
    tersedia = periksa_berkas_mentah(konfig, root)

    meta = konfig.get("meta", {}) or {}
    encoding = str(meta.get("encoding", "utf-8"))
    sep = meta.get("sep", "auto")

    hasil: dict[str, TabelMentah] = {}
    for alias, path in tersedia.items():
        ksum = konfig["sumber"][alias]
        df = baca_csv(path, encoding=encoding, sep=sep)
        hasil[alias] = TabelMentah(alias=alias, path=path, df=df, konfig=ksum)
    return hasil


def ringkas_ekstrak(tabel: dict[str, TabelMentah], root: Path | None = None) -> str:
    """Ringkasan satu baris per tabel untuk dicetak ke log."""
    root = root or ROOT_PROYEK
    baris = []
    for alias, t in tabel.items():
        baris.append(
            f"  {alias:<22} {t.jumlah_baris:>8,} baris x {len(t.df.columns):>2} kolom"
            f"  <- {_relatif(t.path, root)}"
        )
    return "\n".join(baris)


def _relatif(path: Path, root: Path | None = None) -> str:
    """Tampilkan path relatif terhadap root repo bila memungkinkan."""
    root = root or ROOT_PROYEK
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()
