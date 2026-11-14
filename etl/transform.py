"""Tahap TRANSFORM: membersihkan, meng-unpivot, dan menyamakan grain.

Menerapkan aturan Bagian 7 brief:

1. Unpivot data wide (``pandas.melt``) menjadi long.
2. Standarisasi teks dimensi (trim, rapikan spasi, Title Case, pemetaan ejaan).
3. Tipe data: ``tahun`` -> int, measure -> numerik (pemisah ribuan dibuang).
4. Grain fact = (tahun, cabang_pelayanan, jenis_kendaraan, fungsi_kendaraan).
7. Idempoten: semua operasi deterministik, hasil diurutkan.

Semua fungsi di sini murni (tidak menulis file, tidak menyentuh jaringan)
supaya gampang diuji di ``tests/test_transform.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

# Nilai dimensi yang sebenarnya baris agregat/total di CSV sumber. Kalau ikut
# dihitung, measure jadi dobel. Dibuang dan jumlahnya dilaporkan.
NILAI_AGREGAT: frozenset[str] = frozenset(
    {
        "jumlah",
        "total",
        "jumlah total",
        "total jumlah",
        "grand total",
        "semua",
        "seluruhnya",
        "jumlah keseluruhan",
    }
)

# Placeholder untuk kolom grain yang tidak tersedia di sebuah dataset sumber.
NILAI_TIDAK_DIRINCI = "Tidak Dirinci"

# Kolom identitas Satu Data yang ikut dibawa (dipakai membangun dim_wilayah).
KOLOM_ATRIBUT_WILAYAH = (
    "kode_provinsi",
    "nama_provinsi",
    "kode_kabupaten_kota",
    "nama_kabupaten_kota",
)


class GrainTidakLengkapError(ValueError):
    """Kolom kunci yang tidak bisa dipulihkan (mis. ``tahun``) tidak ada."""


@dataclass
class HasilTransform:
    """DataFrame hasil bersih + catatan proses untuk laporan validasi."""

    alias: str
    df: pd.DataFrame
    measure: str
    keys: list[str]
    catatan: list[str] = field(default_factory=list)
    nilai_belum_dipetakan: dict[str, list[str]] = field(default_factory=dict)

    def catat(self, pesan: str) -> None:
        self.catatan.append(f"[{self.alias}] {pesan}")


# --------------------------------------------------------------------------- #
# 1. Normalisasi nama kolom & pemetaan alias
# --------------------------------------------------------------------------- #
def normalisasi_nama_kolom(df: pd.DataFrame) -> pd.DataFrame:
    """Ubah header jadi ``snake_case`` lowercase tanpa karakter aneh."""
    df = df.copy()
    df.columns = [_slug_kolom(str(k)) for k in df.columns]
    return df


def _slug_kolom(nama: str) -> str:
    nama = nama.replace("﻿", "").strip().lower()
    nama = re.sub(r"[^\w]+", "_", nama, flags=re.UNICODE)
    return re.sub(r"_+", "_", nama).strip("_")


def bangun_peta_alias(alias_kolom: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """``{varian_ternormalisasi: kolom_baku}`` dari blok ``alias_kolom`` YAML."""
    peta: dict[str, str] = {}
    for baku, varian in (alias_kolom or {}).items():
        peta.setdefault(_slug_kolom(baku), baku)
        for v in varian or []:
            peta.setdefault(_slug_kolom(str(v)), baku)
    return peta


def petakan_kolom(
    df: pd.DataFrame,
    peta_alias: Mapping[str, str],
    rename_eksplisit: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Rename kolom sumber ke kolom baku.

    ``rename_eksplisit`` (dari YAML per-sumber) menang atas ``peta_alias``.
    Kolom yang tidak dikenali dibiarkan apa adanya -- pada dataset wide, kolom
    sisa itu justru kandidat kategori yang akan di-unpivot.
    """
    rename_eksplisit = {
        _slug_kolom(k): v for k, v in (rename_eksplisit or {}).items()
    }
    mapping: dict[str, str] = {}
    terpakai: set[str] = set()
    for kolom in df.columns:
        baku = rename_eksplisit.get(kolom) or peta_alias.get(kolom)
        # Jangan menimpa kolom baku yang sudah terisi dari kolom lain.
        if baku and baku not in terpakai:
            mapping[kolom] = baku
            terpakai.add(baku)
    return df.rename(columns=mapping)


# --------------------------------------------------------------------------- #
# 2. Unpivot (wide -> long)
# --------------------------------------------------------------------------- #
def unpivot_wide(
    df: pd.DataFrame,
    id_vars: Sequence[str],
    var_name: str,
    value_name: str,
) -> pd.DataFrame:
    """Melt kolom kategori jadi baris.

    Hanya ``id_vars`` yang benar-benar ada di ``df`` yang dipakai; sisa kolom
    dianggap kategori. Kolom kategori yang seluruhnya kosong dibuang.
    """
    id_ada = [k for k in id_vars if k in df.columns]
    value_vars = [k for k in df.columns if k not in id_ada]
    if not value_vars:
        raise GrainTidakLengkapError(
            f"Tidak ada kolom kategori untuk di-unpivot; kolom tersedia: {list(df.columns)}"
        )
    panjang = df.melt(
        id_vars=id_ada,
        value_vars=value_vars,
        var_name=var_name,
        value_name=value_name,
    )
    return panjang.reset_index(drop=True)


def tentukan_bentuk(
    df: pd.DataFrame, bentuk: str, measure_sumber: Sequence[str]
) -> str:
    """Resolusi ``bentuk: auto`` -> "long" bila kolom measure ditemukan."""
    bentuk = (bentuk or "auto").lower()
    if bentuk in {"long", "wide"}:
        return bentuk
    return "long" if _cari_kolom_measure(df, measure_sumber) else "wide"


def _cari_kolom_measure(
    df: pd.DataFrame, measure_sumber: Sequence[str]
) -> str | None:
    for kandidat in measure_sumber or []:
        slug = _slug_kolom(str(kandidat))
        if slug in df.columns:
            return slug
    return None


# --------------------------------------------------------------------------- #
# 3. Standarisasi teks dimensi
# --------------------------------------------------------------------------- #
def bersihkan_teks(seri: pd.Series) -> pd.Series:
    """Trim, rapikan spasi ganda/underscore, lalu Title Case."""
    hasil = seri.astype("string")
    hasil = hasil.str.replace(r"[_\s]+", " ", regex=True).str.strip()
    hasil = hasil.replace({"": pd.NA, "-": pd.NA, "nan": pd.NA, "NaN": pd.NA})
    return hasil.str.title()


def bangun_peta_nilai(peta_yaml: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """``{varian_lowercase: "Nilai Baku"}`` dari satu blok ``normalisasi_teks``."""
    peta: dict[str, str] = {}
    for baku, varian in (peta_yaml or {}).items():
        peta.setdefault(_kunci_nilai(baku), baku)
        for v in varian or []:
            peta.setdefault(_kunci_nilai(str(v)), baku)
    return peta


def _kunci_nilai(nilai: str) -> str:
    return re.sub(r"[\s_]+", " ", str(nilai)).strip().lower()


def terapkan_peta_nilai(
    seri: pd.Series, peta_nilai: Mapping[str, str]
) -> tuple[pd.Series, list[str]]:
    """Petakan varian ejaan ke nilai baku.

    Mengembalikan ``(seri_baku, daftar_nilai_belum_dipetakan)``. Nilai yang tidak
    ada di peta TIDAK dibuang -- tetap dipakai (sudah Title Case) dan dilaporkan.
    """
    bersih = bersihkan_teks(seri)
    if not peta_nilai:
        return bersih, []

    kunci = bersih.map(lambda v: _kunci_nilai(v) if pd.notna(v) else v)
    hasil = kunci.map(lambda k: peta_nilai.get(k) if pd.notna(k) else k)
    belum = sorted(
        {
            str(asli)
            for asli, baku in zip(bersih, hasil)
            if pd.notna(asli) and pd.isna(baku)
        }
    )
    hasil = hasil.astype("string").fillna(bersih)
    return hasil, belum


# --------------------------------------------------------------------------- #
# 4. Tipe data
# --------------------------------------------------------------------------- #
_POLA_TAHUN = r"((?:19|20)\d{2})"


def ke_tahun(seri: pd.Series) -> pd.Series:
    """Ekstrak tahun 4 digit -> Int64 (nullable, supaya NaN tidak jadi float).

    Toleran terhadap nilai seperti ``"2019"``, ``"2019.0"``, atau ``"Tahun 2019"``.
    """
    teks = seri.astype("string").str.strip()
    cocok = teks.str.extract(_POLA_TAHUN, expand=False)
    return pd.to_numeric(cocok, errors="coerce").astype("Int64")


def ke_numerik(seri: pd.Series) -> pd.Series:
    """Ubah teks angka gaya Indonesia/Inggris jadi float.

    Menangani ``"1.234.567"``, ``"1,234,567"``, ``"1.234.567,89"``,
    ``"Rp 1.234.567"``, ``"(1.234)"`` (negatif), ``"-"``/``""`` -> NaN.
    """
    return seri.map(_parse_angka).astype("float64")


def _parse_angka(nilai: Any) -> float:
    if nilai is None or (isinstance(nilai, float) and np.isnan(nilai)):
        return np.nan
    if isinstance(nilai, (int, np.integer, float, np.floating)):
        return float(nilai)

    teks = str(nilai).strip()
    if teks == "" or teks.lower() in {"na", "nan", "none", "null", "-", "--"}:
        return np.nan

    negatif = teks.startswith("(") and teks.endswith(")")
    teks = re.sub(r"(?i)\b(rp|idr|unit|kendaraan)\b", "", teks)
    teks = re.sub(r"[^\d,.\-]", "", teks)
    if teks in {"", "-", ".", ","}:
        return np.nan
    if teks.startswith("-"):
        negatif = True
    teks = teks.lstrip("+-")

    ada_titik, ada_koma = "." in teks, "," in teks
    if ada_titik and ada_koma:
        # Pemisah desimal = yang muncul paling belakang.
        if teks.rfind(",") > teks.rfind("."):
            teks = teks.replace(".", "").replace(",", ".")
        else:
            teks = teks.replace(",", "")
    elif ada_koma:
        teks = teks.replace(",", "") if _pola_ribuan(teks, ",") else teks.replace(",", ".")
    elif ada_titik:
        if _pola_ribuan(teks, "."):
            teks = teks.replace(".", "")

    try:
        angka = float(teks)
    except ValueError:
        return np.nan
    return -angka if negatif else angka


def _pola_ribuan(teks: str, pemisah: str) -> bool:
    """True bila ``teks`` berpola pengelompokan ribuan (mis. 1.234.567)."""
    bagian = teks.split(pemisah)
    if len(bagian) < 2:
        return False
    if len(bagian) > 2:
        return all(len(b) == 3 for b in bagian[1:])
    return len(bagian[1]) == 3 and len(bagian[0]) <= 3


# --------------------------------------------------------------------------- #
# 5. Pipeline per sumber
# --------------------------------------------------------------------------- #
def transform_sumber(
    df_mentah: pd.DataFrame,
    alias: str,
    konfig_sumber: Mapping[str, Any],
    konfig: Mapping[str, Any],
) -> HasilTransform:
    """Jalankan seluruh pipeline transform untuk satu tabel sumber."""
    keys = list(konfig_sumber.get("keys") or [])
    measure = str(konfig_sumber["measure"])
    measure_sumber = list(konfig_sumber.get("measure_sumber") or [])
    peta_alias = bangun_peta_alias(konfig.get("alias_kolom", {}))
    peta_teks_semua = konfig.get("normalisasi_teks", {}) or {}

    hasil = HasilTransform(alias=alias, df=pd.DataFrame(), measure=measure, keys=keys)

    df = normalisasi_nama_kolom(df_mentah)
    df = petakan_kolom(df, peta_alias, konfig_sumber.get("rename"))

    # --- bentuk: long vs wide -------------------------------------------- #
    bentuk = tentukan_bentuk(df, str(konfig_sumber.get("bentuk", "auto")), measure_sumber)
    atribut = [k for k in KOLOM_ATRIBUT_WILAYAH if k in df.columns]

    if bentuk == "long":
        kolom_measure = _cari_kolom_measure(df, measure_sumber)
        if kolom_measure is None:
            raise GrainTidakLengkapError(
                f"[{alias}] bentuk 'long' tapi kolom measure {measure_sumber} tidak ada. "
                f"Kolom tersedia: {list(df.columns)}. Perbaiki `measure_sumber` di config/sources.yaml."
            )
        df = df.rename(columns={kolom_measure: measure})
        hasil.catat(f"bentuk=long, kolom measure sumber='{kolom_measure}'")
    else:
        unpivot = konfig_sumber.get("unpivot") or {}
        id_vars = list(unpivot.get("id_vars") or [k for k in keys if k != unpivot.get("var_name")])
        id_vars = list(dict.fromkeys(id_vars + atribut + ["satuan"]))
        var_name = str(unpivot.get("var_name") or "kategori")
        df = unpivot_wide(df, id_vars=id_vars, var_name=var_name, value_name=measure)
        hasil.catat(f"bentuk=wide, di-unpivot menjadi kolom '{var_name}'")

    # --- kolom grain yang tidak tersedia --------------------------------- #
    for k in keys:
        if k in df.columns:
            continue
        if k == "tahun":
            raise GrainTidakLengkapError(
                f"[{alias}] kolom 'tahun' tidak ditemukan. Kolom tersedia: {list(df.columns)}. "
                "Tambahkan alias yang benar di config/sources.yaml -> alias_kolom.tahun."
            )
        df[k] = NILAI_TIDAK_DIRINCI
        hasil.catat(
            f"kolom grain '{k}' tidak ada di sumber -> diisi '{NILAI_TIDAK_DIRINCI}' (ASUMSI)"
        )

    # --- tipe data & standarisasi teks ----------------------------------- #
    df["tahun"] = ke_tahun(df["tahun"])
    df[measure] = ke_numerik(df[measure])

    for kolom in [k for k in keys if k != "tahun"] + atribut:
        if kolom in {"kode_provinsi", "kode_kabupaten_kota"}:
            df[kolom] = df[kolom].astype("string").str.strip()
            continue
        seri, belum = terapkan_peta_nilai(df[kolom], bangun_peta_nilai(peta_teks_semua.get(kolom, {})))
        df[kolom] = seri
        if belum:
            hasil.nilai_belum_dipetakan[kolom] = belum

    # --- buang baris agregat & tahun tidak valid ------------------------- #
    sebelum = len(df)
    df = df[df["tahun"].notna()]
    if (dibuang := sebelum - len(df)) > 0:
        hasil.catat(f"{dibuang:,} baris dibuang: 'tahun' tidak bisa diparse")

    for kolom in [k for k in keys if k != "tahun"]:
        mask = df[kolom].map(lambda v: _kunci_nilai(v) in NILAI_AGREGAT if pd.notna(v) else False)
        if (n := int(mask.sum())) > 0:
            df = df[~mask]
            hasil.catat(f"{n:,} baris agregat/total dibuang dari kolom '{kolom}'")

    # --- samakan grain: agregasi duplikat -------------------------------- #
    kolom_akhir = keys + [measure] + atribut
    df = df[[k for k in kolom_akhir if k in df.columns]]
    df, n_gabung = agregasi_ke_grain(df, keys, measure, atribut)
    if n_gabung:
        hasil.catat(f"{n_gabung:,} baris duplikat pada grain digabung (sum measure)")

    df = df.sort_values(keys, kind="mergesort").reset_index(drop=True)
    hasil.df = df
    hasil.catat(f"hasil akhir: {len(df):,} baris, grain={tuple(keys)}")
    return hasil


def agregasi_ke_grain(
    df: pd.DataFrame,
    keys: Sequence[str],
    measure: str,
    atribut: Sequence[str] = (),
) -> tuple[pd.DataFrame, int]:
    """Jumlahkan measure per grain; atribut non-grain diambil nilai pertama.

    Mengembalikan ``(df_agregat, jumlah_baris_yang_terlipat)``.
    """
    keys = list(keys)
    atribut = [a for a in atribut if a in df.columns and a not in keys]
    if df.empty:
        return df.reset_index(drop=True), 0

    agg: dict[str, Any] = {measure: "sum"}
    for a in atribut:
        agg[a] = "first"
    hasil = df.groupby(keys, dropna=False, as_index=False, sort=True).agg(agg)
    return hasil, len(df) - len(hasil)


def transform_semua(
    tabel_mentah: Mapping[str, Any], konfig: Mapping[str, Any]
) -> dict[str, HasilTransform]:
    """Terapkan ``transform_sumber`` ke semua tabel hasil extract."""
    hasil: dict[str, HasilTransform] = {}
    for alias, tabel in tabel_mentah.items():
        df = tabel.df if hasattr(tabel, "df") else tabel
        ksum = tabel.konfig if hasattr(tabel, "konfig") else konfig["sumber"][alias]
        hasil[alias] = transform_sumber(df, alias, ksum, konfig)
    return hasil


def kumpulkan_catatan(hasil: Mapping[str, HasilTransform]) -> list[str]:
    """Gabungkan semua catatan transform untuk laporan akhir."""
    catatan: list[str] = []
    for h in hasil.values():
        catatan.extend(h.catatan)
        for kolom, nilai in h.nilai_belum_dipetakan.items():
            contoh = ", ".join(nilai[:8])
            lanjut = " ..." if len(nilai) > 8 else ""
            catatan.append(
                f"[{h.alias}] {len(nilai)} nilai '{kolom}' belum dipetakan di "
                f"normalisasi_teks: {contoh}{lanjut}"
            )
    return catatan


def daftar_unik(seri: Iterable[Any]) -> list[str]:
    """Nilai unik non-null, terurut -- dipakai saat membangun dimensi."""
    nilai = {str(v) for v in seri if pd.notna(v)}
    return sorted(nilai)
