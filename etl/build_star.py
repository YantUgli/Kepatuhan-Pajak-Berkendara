"""Tahap BUILD: membangun dimensi, surrogate key, fact, dan measure turunan.

Star schema target (Bagian 5 brief):

    fakta_kepatuhan_kendaraan
      grain = 1 tahun x 1 cabang_pelayanan x 1 jenis_kendaraan x 1 fungsi_kendaraan
      FK    -> dim_waktu, dim_wilayah, dim_jenis_kendaraan, dim_fungsi_kendaraan

Semua ``*_id`` adalah surrogate key integer yang dibuat di sini (bukan dari
sumber) dan STABIL: dibangun dari nilai natural key yang diurutkan, sehingga
menjalankan ETL dua kali menghasilkan file identik (aturan idempoten, Bagian 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .transform import HasilTransform, NILAI_TIDAK_DIRINCI

GRAIN_FACT: tuple[str, ...] = (
    "tahun",
    "cabang_pelayanan",
    "jenis_kendaraan",
    "fungsi_kendaraan",
)

# Alias sumber count inti -> nama kolom measure di fact.
MEASURE_INTI: dict[str, str] = {
    "kendaraan_total": "jumlah_kendaraan_total",
    "tidak_daftar_ulang": "jumlah_tidak_daftar_ulang",
    "belum_daftar_ulang": "jumlah_belum_daftar_ulang",
}

KOLOM_FACT: tuple[str, ...] = (
    "waktu_id",
    "wilayah_id",
    "jenis_kendaraan_id",
    "fungsi_kendaraan_id",
    "tahun",
    "cabang_pelayanan",
    "jenis_kendaraan",
    "fungsi_kendaraan",
    "jumlah_kendaraan_total",
    "jumlah_tidak_daftar_ulang",
    "jumlah_belum_daftar_ulang",
    "jumlah_daftar_ulang",
    "tingkat_kepatuhan",
    "estimasi_pajak_hilang",
    "rata_pajak_per_kendaraan",
)


@dataclass
class StarSchema:
    """Kumpulan tabel hasil build + catatan proses."""

    tabel: dict[str, pd.DataFrame] = field(default_factory=dict)
    catatan: list[str] = field(default_factory=list)
    metrik: dict[str, Any] = field(default_factory=dict)

    def catat(self, pesan: str) -> None:
        self.catatan.append(f"[build] {pesan}")

    @property
    def fact(self) -> pd.DataFrame:
        return self.tabel["fakta_kepatuhan_kendaraan"]


# --------------------------------------------------------------------------- #
# Dimensi & surrogate key
# --------------------------------------------------------------------------- #
def buat_dimensi(
    nilai: Sequence[Any],
    kolom_natural: str,
    kolom_id: str,
    atribut: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Bangun tabel dimensi dengan surrogate key 1..n yang stabil.

    ``nilai`` di-*dedupe* lalu diurutkan sehingga id tidak berubah antar run
    selama himpunan nilainya sama.
    """
    unik = pd.Series(list(nilai)).dropna().drop_duplicates()
    unik = unik.sort_values(kind="mergesort").reset_index(drop=True)

    dim = pd.DataFrame({kolom_natural: unik})
    dim.insert(0, kolom_id, np.arange(1, len(dim) + 1, dtype="int64"))

    if atribut is not None and not atribut.empty:
        dim = dim.merge(atribut, on=kolom_natural, how="left")
    return dim


def bangun_dim_waktu(tahun: Sequence[Any]) -> pd.DataFrame:
    """``dim_waktu``: waktu_id, tahun, dekade (atribut turunan sederhana)."""
    seri = pd.to_numeric(pd.Series(list(tahun)), errors="coerce").dropna().astype("int64")
    dim = buat_dimensi(seri, "tahun", "waktu_id")
    dim["tahun"] = dim["tahun"].astype("int64")
    dim["dekade"] = (dim["tahun"] // 10 * 10).astype("int64")
    dim["label_tahun"] = dim["tahun"].astype(str)
    return dim


def bangun_dim_wilayah(
    cabang: Sequence[Any], atribut: pd.DataFrame | None = None
) -> pd.DataFrame:
    """``dim_wilayah``: grain = cabang_pelayanan (Bagian 7 butir 4 brief).

    Atribut kab/kota bersifat OPSIONAL dan boleh null. Kalau satu cabang
    memetakan ke banyak kab/kota, hanya satu yang disimpan sebagai atribut
    deskriptif -- fact TIDAK di-join ke kab/kota supaya baris tidak berganda.
    """
    dim = buat_dimensi(cabang, "cabang_pelayanan", "wilayah_id", atribut)
    for kolom in ("kode_kabupaten_kota", "nama_kabupaten_kota", "nama_provinsi"):
        if kolom not in dim.columns:
            dim[kolom] = pd.NA
    dim["nama_provinsi"] = dim["nama_provinsi"].fillna("Jawa Barat")
    return dim[
        [
            "wilayah_id",
            "cabang_pelayanan",
            "kode_kabupaten_kota",
            "nama_kabupaten_kota",
            "nama_provinsi",
        ]
    ]


def kumpulkan_atribut_wilayah(
    hasil: Mapping[str, HasilTransform]
) -> pd.DataFrame:
    """Ambil atribut kab/kota per cabang dari sumber manapun yang punya."""
    potongan: list[pd.DataFrame] = []
    kolom = ["cabang_pelayanan", "kode_kabupaten_kota", "nama_kabupaten_kota", "nama_provinsi"]
    for h in hasil.values():
        ada = [k for k in kolom if k in h.df.columns]
        if "cabang_pelayanan" in ada and len(ada) > 1:
            potongan.append(h.df[ada].dropna(subset=["cabang_pelayanan"]))
    if not potongan:
        return pd.DataFrame(columns=kolom)

    gabung = pd.concat(potongan, ignore_index=True).drop_duplicates()
    gabung = gabung.sort_values(list(gabung.columns), kind="mergesort")
    return gabung.groupby("cabang_pelayanan", as_index=False, sort=True).first()


# --------------------------------------------------------------------------- #
# Penggabungan measure ke satu grain
# --------------------------------------------------------------------------- #
def gabung_measure_inti(
    hasil: Mapping[str, HasilTransform], star: StarSchema | None = None
) -> pd.DataFrame:
    """Outer-join tiga dataset count inti pada grain fact."""
    grain = list(GRAIN_FACT)
    gabungan: pd.DataFrame | None = None

    for alias, kolom_measure in MEASURE_INTI.items():
        h = hasil.get(alias)
        if h is None:
            raise KeyError(
                f"Sumber inti '{alias}' tidak ada pada hasil transform; "
                "cek config/sources.yaml -> sumber."
            )
        potong = h.df[[*grain, kolom_measure]].copy()
        gabungan = potong if gabungan is None else gabungan.merge(potong, on=grain, how="outer")

    assert gabungan is not None
    gabungan = gabungan.sort_values(grain, kind="mergesort").reset_index(drop=True)

    # Aturan Bagian 7 butir 3: kombinasi grain yang tidak muncul di dataset
    # "tidak/belum daftar ulang" berarti TIDAK ADA KEJADIAN -> 0.
    # Sebaliknya `jumlah_kendaraan_total` yang hilang dibiarkan NaN karena ia
    # penyebut; menganggapnya 0 akan memalsukan tingkat kepatuhan.
    for kolom in ("jumlah_tidak_daftar_ulang", "jumlah_belum_daftar_ulang"):
        n_null = int(gabungan[kolom].isna().sum())
        if n_null and star is not None:
            star.catat(f"{n_null:,} sel '{kolom}' kosong -> diisi 0 (tidak ada kejadian)")
        gabungan[kolom] = gabungan[kolom].fillna(0.0)

    n_total_null = int(gabungan["jumlah_kendaraan_total"].isna().sum())
    if n_total_null and star is not None:
        star.catat(
            f"{n_total_null:,} baris tanpa 'jumlah_kendaraan_total' -> dibiarkan NaN "
            "(penyebut tidak diketahui, tingkat_kepatuhan jadi null)"
        )
    return gabungan


# --------------------------------------------------------------------------- #
# Monetisasi: rata-rata pajak per kendaraan per tahun
# --------------------------------------------------------------------------- #
def hitung_rata_pajak_per_kendaraan(
    df_pajak: pd.DataFrame | None,
    df_fact: pd.DataFrame,
    monetisasi: Mapping[str, Any] | None = None,
    star: StarSchema | None = None,
) -> pd.DataFrame:
    """Hitung ``rata_pajak_per_kendaraan`` per tahun (Bagian 7 butir 6 brief).

    ``rata_pajak_per_kendaraan[t] = total nilai PKB (komponen pajak, BUKAN denda)
    tahun t / total kendaraan terdaftar tahun t``.

    Mengembalikan DataFrame ``[tahun, nilai_pajak_rupiah, kendaraan_terdaftar,
    rata_pajak_per_kendaraan]``.
    """
    monetisasi = monetisasi or {}
    pola_pajak = [str(p).lower() for p in monetisasi.get("komponen_pajak", ["pkb"])]
    pola_denda = [str(p).lower() for p in monetisasi.get("komponen_denda", ["denda"])]

    penyebut = (
        df_fact.groupby("tahun", as_index=False, sort=True)["jumlah_kendaraan_total"]
        .sum(min_count=1)
        .rename(columns={"jumlah_kendaraan_total": "kendaraan_terdaftar"})
    )

    if df_pajak is None or df_pajak.empty or "nilai_rupiah" not in df_pajak.columns:
        if star is not None:
            star.catat(
                "data pajak_denda tidak tersedia -> estimasi_pajak_hilang = NaN "
                "(rata_pajak_per_kendaraan tidak bisa dihitung)"
            )
        hasil = penyebut.copy()
        hasil["nilai_pajak_rupiah"] = np.nan
        hasil["rata_pajak_per_kendaraan"] = np.nan
        return hasil[
            ["tahun", "nilai_pajak_rupiah", "kendaraan_terdaftar", "rata_pajak_per_kendaraan"]
        ]

    jenis = df_pajak["jenis_pajak"].astype("string").str.lower().fillna("")
    is_denda = jenis.apply(lambda v: any(p in v for p in pola_denda))
    is_pajak = jenis.apply(lambda v: any(p in v for p in pola_pajak)) & ~is_denda

    if not bool(is_pajak.any()):
        if star is not None:
            star.catat(
                f"tidak ada baris pajak_denda yang cocok pola {pola_pajak} -> "
                f"memakai SELURUH baris non-denda sebagai komponen pajak (ASUMSI)"
            )
        is_pajak = ~is_denda

    pembilang = (
        df_pajak.loc[is_pajak]
        .groupby("tahun", as_index=False, sort=True)["nilai_rupiah"]
        .sum(min_count=1)
        .rename(columns={"nilai_rupiah": "nilai_pajak_rupiah"})
    )

    hasil = penyebut.merge(pembilang, on="tahun", how="left")
    hasil["rata_pajak_per_kendaraan"] = np.where(
        (hasil["kendaraan_terdaftar"] > 0) & hasil["nilai_pajak_rupiah"].notna(),
        hasil["nilai_pajak_rupiah"] / hasil["kendaraan_terdaftar"],
        np.nan,
    )

    kosong = hasil["rata_pajak_per_kendaraan"].isna()
    if bool(kosong.any()) and monetisasi.get("fallback_rata_global", True):
        rata_global = float(hasil["rata_pajak_per_kendaraan"].mean(skipna=True) or np.nan)
        if not np.isnan(rata_global):
            tahun_fallback = hasil.loc[kosong, "tahun"].tolist()
            hasil.loc[kosong, "rata_pajak_per_kendaraan"] = rata_global
            if star is not None:
                star.catat(
                    f"tahun {tahun_fallback} tidak punya data pajak -> memakai rata-rata "
                    f"global Rp {rata_global:,.0f}/kendaraan (ASUMSI, lihat data_dictionary)"
                )

    return hasil[
        ["tahun", "nilai_pajak_rupiah", "kendaraan_terdaftar", "rata_pajak_per_kendaraan"]
    ]


# --------------------------------------------------------------------------- #
# Measure turunan
# --------------------------------------------------------------------------- #
def hitung_measure_turunan(
    df: pd.DataFrame, star: StarSchema | None = None
) -> pd.DataFrame:
    """Hitung jumlah_daftar_ulang, tingkat_kepatuhan, estimasi_pajak_hilang.

    - ``jumlah_daftar_ulang = total - tidak - belum``; hasil negatif di-*floor*
      ke 0 (inkonsistensi sumber) dan jumlah barisnya dilaporkan.
    - ``tingkat_kepatuhan = jumlah_daftar_ulang / jumlah_kendaraan_total``;
      null bila total 0 atau NaN.
    - ``estimasi_pajak_hilang = jumlah_tidak_daftar_ulang * rata_pajak_per_kendaraan``.
    """
    df = df.copy()
    mentah = (
        df["jumlah_kendaraan_total"]
        - df["jumlah_tidak_daftar_ulang"]
        - df["jumlah_belum_daftar_ulang"]
    )
    n_negatif = int((mentah < 0).sum())
    df["jumlah_daftar_ulang"] = mentah.clip(lower=0)
    if n_negatif and star is not None:
        star.catat(
            f"{n_negatif:,} baris punya (total - tidak - belum) < 0 -> di-floor ke 0 "
            "(inkonsistensi sumber, aturan Bagian 7 butir 5)"
        )
    if star is not None:
        star.metrik["baris_difloor"] = n_negatif

    total = df["jumlah_kendaraan_total"]
    df["tingkat_kepatuhan"] = np.where(
        total.notna() & (total > 0), df["jumlah_daftar_ulang"] / total, np.nan
    )

    if "rata_pajak_per_kendaraan" in df.columns:
        df["estimasi_pajak_hilang"] = (
            df["jumlah_tidak_daftar_ulang"] * df["rata_pajak_per_kendaraan"]
        )
    else:
        df["estimasi_pajak_hilang"] = np.nan
    return df


# --------------------------------------------------------------------------- #
# Orkestrasi build
# --------------------------------------------------------------------------- #
def bangun_star(
    hasil: Mapping[str, HasilTransform], konfig: Mapping[str, Any] | None = None
) -> StarSchema:
    """Bangun seluruh tabel star schema dari hasil transform."""
    konfig = konfig or {}
    star = StarSchema()

    fact = gabung_measure_inti(hasil, star)

    # --- dimensi ---------------------------------------------------------- #
    dim_waktu = bangun_dim_waktu(fact["tahun"])
    dim_wilayah = bangun_dim_wilayah(
        fact["cabang_pelayanan"], kumpulkan_atribut_wilayah(hasil)
    )
    dim_jenis = buat_dimensi(
        fact["jenis_kendaraan"], "jenis_kendaraan", "jenis_kendaraan_id"
    )
    dim_fungsi = buat_dimensi(
        fact["fungsi_kendaraan"], "fungsi_kendaraan", "fungsi_kendaraan_id"
    )

    # --- monetisasi ------------------------------------------------------- #
    h_pajak = hasil.get("pajak_denda")
    tabel_rata = hitung_rata_pajak_per_kendaraan(
        h_pajak.df if h_pajak is not None else None,
        fact,
        konfig.get("monetisasi", {}),
        star,
    )
    fact["tahun"] = pd.to_numeric(fact["tahun"], errors="coerce").astype("Int64")
    fact = fact.merge(
        tabel_rata[["tahun", "rata_pajak_per_kendaraan"]].assign(
            tahun=lambda d: pd.to_numeric(d["tahun"], errors="coerce").astype("Int64")
        ),
        on="tahun",
        how="left",
    )

    # --- measure turunan + FK --------------------------------------------- #
    fact = hitung_measure_turunan(fact, star)
    fact = fact.merge(dim_waktu[["waktu_id", "tahun"]].astype({"tahun": "Int64"}), on="tahun", how="left")
    fact = fact.merge(dim_wilayah[["wilayah_id", "cabang_pelayanan"]], on="cabang_pelayanan", how="left")
    fact = fact.merge(dim_jenis, on="jenis_kendaraan", how="left")
    fact = fact.merge(dim_fungsi, on="fungsi_kendaraan", how="left")

    fact = fact[[k for k in KOLOM_FACT if k in fact.columns]]
    fact = fact.sort_values(list(GRAIN_FACT), kind="mergesort").reset_index(drop=True)
    for kolom in ("waktu_id", "wilayah_id", "jenis_kendaraan_id", "fungsi_kendaraan_id"):
        fact[kolom] = fact[kolom].astype("Int64")

    star.tabel = {
        "dim_waktu": dim_waktu,
        "dim_wilayah": dim_wilayah,
        "dim_jenis_kendaraan": dim_jenis,
        "dim_fungsi_kendaraan": dim_fungsi,
        "fakta_kepatuhan_kendaraan": fact,
        "bantu_rata_pajak_tahunan": tabel_rata,
    }
    star.metrik["jumlah_baris"] = {k: len(v) for k, v in star.tabel.items()}
    star.catat(
        f"fact terbangun: {len(fact):,} baris, {fact['tahun'].nunique()} tahun, "
        f"{fact['cabang_pelayanan'].nunique()} cabang pelayanan"
    )
    if (fact["fungsi_kendaraan"] == NILAI_TIDAK_DIRINCI).all():
        star.catat(
            "seluruh 'fungsi_kendaraan' bernilai 'Tidak Dirinci' -- sumber tidak "
            "memuat dimensi ini (ASUMSI didokumentasikan di data_dictionary)"
        )
    return star
