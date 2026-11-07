"""Tahap VALIDATE: cek kualitas star schema (Bagian 8 brief).

FATAL (menggagalkan ETL):
  - FK di fact tidak punya pasangan di dim (orphan) atau bernilai null.
  - ``tingkat_kepatuhan`` di luar rentang [0, 1] (null diperbolehkan).
  - Ada baris fact duplikat pada grain.

WARNING (dicatat, ETL tetap lanjut):
  - Rentang ``tahun`` menyimpang dari yang diharapkan di ``config/sources.yaml``.
  - Jumlah baris per tabel, jumlah null per measure, jumlah baris yang di-floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from .build_star import GRAIN_FACT, StarSchema

# FK di fact -> (tabel dim, kolom id di dim)
RELASI_FK: dict[str, tuple[str, str]] = {
    "waktu_id": ("dim_waktu", "waktu_id"),
    "wilayah_id": ("dim_wilayah", "wilayah_id"),
    "jenis_kendaraan_id": ("dim_jenis_kendaraan", "jenis_kendaraan_id"),
    "fungsi_kendaraan_id": ("dim_fungsi_kendaraan", "fungsi_kendaraan_id"),
}

MEASURE_FACT: tuple[str, ...] = (
    "jumlah_kendaraan_total",
    "jumlah_tidak_daftar_ulang",
    "jumlah_belum_daftar_ulang",
    "jumlah_daftar_ulang",
    "tingkat_kepatuhan",
    "estimasi_pajak_hilang",
)


class ValidasiGagalError(RuntimeError):
    """Minimal satu pemeriksaan FATAL tidak lolos."""


@dataclass
class LaporanValidasi:
    """Hasil seluruh pemeriksaan kualitas data."""

    fatal: list[str] = field(default_factory=list)
    peringatan: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    metrik: dict[str, Any] = field(default_factory=dict)

    @property
    def lolos(self) -> bool:
        return not self.fatal

    def tambah_fatal(self, pesan: str) -> None:
        self.fatal.append(pesan)

    def tambah_peringatan(self, pesan: str) -> None:
        self.peringatan.append(pesan)

    def tambah_info(self, pesan: str) -> None:
        self.info.append(pesan)

    def ringkasan(self) -> str:
        garis = "=" * 78
        baris = [garis, "RINGKASAN VALIDASI", garis]

        baris.append("")
        baris.append("Jumlah baris per tabel:")
        for nama, n in (self.metrik.get("jumlah_baris") or {}).items():
            baris.append(f"  - {nama:<32} {n:>10,} baris")

        if null_measure := self.metrik.get("null_per_measure"):
            baris.append("")
            baris.append("Null per measure (fakta_kepatuhan_kendaraan):")
            for kolom, n in null_measure.items():
                baris.append(f"  - {kolom:<32} {n:>10,} null")

        if self.info:
            baris.append("")
            baris.append("Catatan proses:")
            baris += [f"  - {p}" for p in self.info]

        baris.append("")
        if self.peringatan:
            baris.append(f"PERINGATAN ({len(self.peringatan)}):")
            baris += [f"  ! {p}" for p in self.peringatan]
        else:
            baris.append("PERINGATAN: tidak ada.")

        baris.append("")
        if self.fatal:
            baris.append(f"FATAL ({len(self.fatal)}):")
            baris += [f"  X {p}" for p in self.fatal]
            baris.append("")
            baris.append("STATUS: GAGAL -- output tidak boleh dipakai untuk dashboard.")
        else:
            baris.append("STATUS: LOLOS -- star schema siap dipakai.")
        baris.append(garis)
        return "\n".join(baris)


# --------------------------------------------------------------------------- #
# Pemeriksaan satuan
# --------------------------------------------------------------------------- #
def cek_integritas_fk(star: StarSchema, laporan: LaporanValidasi) -> None:
    """FATAL: setiap FK di fact harus punya pasangan di dim dan tidak null."""
    fact = star.fact
    for fk, (nama_dim, kolom_dim) in RELASI_FK.items():
        if fk not in fact.columns:
            laporan.tambah_fatal(f"Kolom FK '{fk}' tidak ada di fact.")
            continue
        dim = star.tabel.get(nama_dim)
        if dim is None:
            laporan.tambah_fatal(f"Tabel dimensi '{nama_dim}' tidak terbangun.")
            continue

        n_null = int(fact[fk].isna().sum())
        if n_null:
            laporan.tambah_fatal(
                f"{n_null:,} baris fact punya '{fk}' null (gagal join ke {nama_dim})."
            )
        valid = set(dim[kolom_dim].dropna().tolist())
        yatim = sorted({v for v in fact[fk].dropna().tolist() if v not in valid})
        if yatim:
            laporan.tambah_fatal(
                f"{len(yatim):,} nilai '{fk}' tidak ada di {nama_dim} (orphan FK): "
                f"{yatim[:10]}"
            )


def cek_rentang_kepatuhan(star: StarSchema, laporan: LaporanValidasi) -> None:
    """FATAL: ``tingkat_kepatuhan`` harus di [0, 1] atau null."""
    fact = star.fact
    if "tingkat_kepatuhan" not in fact.columns:
        laporan.tambah_fatal("Kolom 'tingkat_kepatuhan' tidak ada di fact.")
        return
    nilai = pd.to_numeric(fact["tingkat_kepatuhan"], errors="coerce")
    diluar = fact[nilai.notna() & ((nilai < 0) | (nilai > 1))]
    if not diluar.empty:
        contoh = diluar.head(5)[list(GRAIN_FACT) + ["tingkat_kepatuhan"]]
        laporan.tambah_fatal(
            f"{len(diluar):,} baris punya tingkat_kepatuhan di luar [0,1].\n"
            f"{contoh.to_string(index=False)}"
        )


def cek_duplikat_grain(star: StarSchema, laporan: LaporanValidasi) -> None:
    """FATAL: tidak boleh ada dua baris fact pada grain yang sama."""
    fact = star.fact
    grain = [k for k in GRAIN_FACT if k in fact.columns]
    if len(grain) != len(GRAIN_FACT):
        laporan.tambah_fatal(
            f"Kolom grain tidak lengkap di fact; ditemukan {grain}, harusnya {list(GRAIN_FACT)}."
        )
        return
    dup = fact[fact.duplicated(subset=grain, keep=False)]
    if not dup.empty:
        laporan.tambah_fatal(
            f"{len(dup):,} baris fact duplikat pada grain {tuple(grain)}.\n"
            f"{dup.head(5)[grain].to_string(index=False)}"
        )


def cek_rentang_tahun(
    star: StarSchema, konfig: Mapping[str, Any], laporan: LaporanValidasi
) -> None:
    """WARNING: rentang tahun menyimpang dari ekspektasi konfigurasi."""
    meta = (konfig or {}).get("meta", {}) or {}
    fact = star.fact
    tahun = pd.to_numeric(fact["tahun"], errors="coerce").dropna()
    if tahun.empty:
        laporan.tambah_fatal("Fact tidak punya satu pun tahun valid.")
        return

    minimum, maksimum = int(tahun.min()), int(tahun.max())
    laporan.metrik["rentang_tahun"] = (minimum, maksimum)
    laporan.tambah_info(
        f"rentang tahun pada fact: {minimum}-{maksimum} ({tahun.nunique()} tahun unik)"
    )

    harap_min, harap_maks = meta.get("tahun_min"), meta.get("tahun_max")
    if harap_min is not None and minimum != int(harap_min):
        laporan.tambah_peringatan(
            f"tahun minimum {minimum} != ekspektasi {harap_min} (config/sources.yaml meta.tahun_min)."
        )
    if harap_maks is not None and maksimum != int(harap_maks):
        laporan.tambah_peringatan(
            f"tahun maksimum {maksimum} != ekspektasi {harap_maks} (config/sources.yaml meta.tahun_max)."
        )


def cek_kelengkapan_measure(star: StarSchema, laporan: LaporanValidasi) -> None:
    """WARNING: hitung null per measure + baris yang di-floor."""
    fact = star.fact
    null_measure = {
        kolom: int(fact[kolom].isna().sum())
        for kolom in MEASURE_FACT
        if kolom in fact.columns
    }
    laporan.metrik["null_per_measure"] = null_measure

    for kolom, n in null_measure.items():
        if n:
            persen = n / max(len(fact), 1) * 100
            laporan.tambah_peringatan(
                f"{n:,} null ({persen:.1f}%) pada measure '{kolom}'."
            )

    n_floor = int(star.metrik.get("baris_difloor", 0) or 0)
    if n_floor:
        laporan.tambah_peringatan(
            f"{n_floor:,} baris di-floor ke 0 pada 'jumlah_daftar_ulang' "
            "(total - tidak - belum bernilai negatif)."
        )

    if "estimasi_pajak_hilang" in fact.columns:
        total_hilang = float(
            pd.to_numeric(fact["estimasi_pajak_hilang"], errors="coerce").sum(skipna=True)
        )
        laporan.metrik["total_estimasi_pajak_hilang"] = total_hilang
        laporan.tambah_info(
            f"total estimasi_pajak_hilang seluruh periode: Rp {total_hilang:,.0f}"
        )

    if "tingkat_kepatuhan" in fact.columns:
        rata = pd.to_numeric(fact["tingkat_kepatuhan"], errors="coerce").mean()
        if pd.notna(rata):
            laporan.metrik["rata_tingkat_kepatuhan"] = float(rata)
            laporan.tambah_info(f"rata-rata tingkat_kepatuhan (unweighted): {rata:.4f}")


def cek_dimensi_tidak_kosong(star: StarSchema, laporan: LaporanValidasi) -> None:
    """FATAL: dimensi kosong berarti fact tidak bisa di-slice sama sekali."""
    for nama in ("dim_waktu", "dim_wilayah", "dim_jenis_kendaraan", "dim_fungsi_kendaraan"):
        dim = star.tabel.get(nama)
        if dim is None or dim.empty:
            laporan.tambah_fatal(f"Dimensi '{nama}' kosong.")


# --------------------------------------------------------------------------- #
# Orkestrasi validasi
# --------------------------------------------------------------------------- #
def validasi(
    star: StarSchema,
    konfig: Mapping[str, Any] | None = None,
    catatan_tambahan: list[str] | None = None,
) -> LaporanValidasi:
    """Jalankan semua pemeriksaan dan kembalikan laporannya."""
    laporan = LaporanValidasi()
    laporan.metrik["jumlah_baris"] = {k: len(v) for k, v in star.tabel.items()}

    for pesan in list(catatan_tambahan or []) + list(star.catatan):
        laporan.tambah_info(pesan)

    if "fakta_kepatuhan_kendaraan" not in star.tabel:
        laporan.tambah_fatal("Tabel 'fakta_kepatuhan_kendaraan' tidak terbangun.")
        return laporan
    if star.fact.empty:
        laporan.tambah_fatal("Tabel fact kosong (0 baris).")
        return laporan

    cek_dimensi_tidak_kosong(star, laporan)
    cek_integritas_fk(star, laporan)
    cek_rentang_kepatuhan(star, laporan)
    cek_duplikat_grain(star, laporan)
    cek_rentang_tahun(star, konfig or {}, laporan)
    cek_kelengkapan_measure(star, laporan)
    return laporan


def validasi_atau_gagal(
    star: StarSchema,
    konfig: Mapping[str, Any] | None = None,
    catatan_tambahan: list[str] | None = None,
) -> LaporanValidasi:
    """Seperti :func:`validasi`, tapi raise bila ada temuan FATAL."""
    laporan = validasi(star, konfig, catatan_tambahan)
    if not laporan.lolos:
        raise ValidasiGagalError(laporan.ringkasan())
    return laporan
