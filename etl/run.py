"""Orkestrasi ETL: extract -> transform -> build -> validate -> export.

Contoh pemakaian::

    pipenv run python -m etl.run              # jalankan ETL, ekspor CSV
    pipenv run python -m etl.run --duckdb     # + tulis data/processed/star.duckdb
    pipenv run python -m etl.run --inspect    # cetak header CSV mentah, lalu berhenti

Keluar dengan kode 0 bila lolos, 1 bila validasi FATAL, 2 bila file mentah kurang.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from . import DIR_PROCESSED_DEFAULT, KONFIG_DEFAULT, ROOT_PROYEK
from .build_star import StarSchema, bangun_star
from .extract import (
    BerkasMentahHilangError,
    KonfigurasiTidakValidError,
    baca_csv,
    ekstrak,
    muat_konfigurasi,
    path_sumber,
    ringkas_ekstrak,
)
from .transform import (
    bangun_peta_alias,
    kumpulkan_catatan,
    normalisasi_nama_kolom,
    petakan_kolom,
    transform_semua,
)
from .validate import LaporanValidasi, validasi

# Pembulatan saat ekspor supaya file CSV stabil antar-run (idempoten) dan
# tidak dipenuhi ekor floating point.
PEMBULATAN_EKSPOR: dict[str, int] = {
    "tingkat_kepatuhan": 6,
    "estimasi_pajak_hilang": 2,
    "rata_pajak_per_kendaraan": 2,
    "nilai_pajak_rupiah": 2,
    "kendaraan_terdaftar": 0,
}

URUTAN_EKSPOR: tuple[str, ...] = (
    "dim_waktu",
    "dim_wilayah",
    "dim_jenis_kendaraan",
    "dim_fungsi_kendaraan",
    "fakta_kepatuhan_kendaraan",
    "bantu_rata_pajak_tahunan",
)


# --------------------------------------------------------------------------- #
# Ekspor
# --------------------------------------------------------------------------- #
def ekspor_csv(star: StarSchema, dir_keluaran: Path) -> list[Path]:
    """Tulis semua tabel star schema ke CSV (UTF-8, tanpa index)."""
    dir_keluaran.mkdir(parents=True, exist_ok=True)
    ditulis: list[Path] = []
    for nama in _urutan(star):
        df = _bulatkan(star.tabel[nama])
        path = dir_keluaran / f"{nama}.csv"
        df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
        ditulis.append(path)
    return ditulis


def ekspor_duckdb(star: StarSchema, path_db: Path) -> Path:
    """Tulis semua tabel ke satu file DuckDB (opsional, flag ``--duckdb``)."""
    try:
        import duckdb  # noqa: PLC0415 -- dependensi opsional, sengaja lazy import
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Paket 'duckdb' belum terpasang. Pasang dulu:\n"
            "    pipenv install --categories duckdb\n"
            "atau jalankan tanpa flag --duckdb."
        ) from exc

    path_db.parent.mkdir(parents=True, exist_ok=True)
    if path_db.exists():
        path_db.unlink()  # tulis ulang dari nol supaya idempoten

    koneksi = duckdb.connect(str(path_db))
    try:
        for nama in _urutan(star):
            df = _bulatkan(star.tabel[nama])
            koneksi.register("df_sementara", df)  # DataFrame dibaca DuckDB via nama ini
            koneksi.execute(f'CREATE OR REPLACE TABLE "{nama}" AS SELECT * FROM df_sementara')
            koneksi.unregister("df_sementara")
    finally:
        koneksi.close()
    return path_db


def _urutan(star: StarSchema) -> list[str]:
    sisa = [k for k in star.tabel if k not in URUTAN_EKSPOR]
    return [k for k in URUTAN_EKSPOR if k in star.tabel] + sorted(sisa)


def _bulatkan(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for kolom, digit in PEMBULATAN_EKSPOR.items():
        if kolom in df.columns:
            df[kolom] = pd.to_numeric(df[kolom], errors="coerce").round(digit)
    return df


# --------------------------------------------------------------------------- #
# Mode --inspect
# --------------------------------------------------------------------------- #
def inspeksi(konfig: Mapping[str, Any], root: Path) -> int:
    """Cetak header asli tiap CSV mentah + hasil pemetaan ke kolom baku."""
    peta_alias = bangun_peta_alias(konfig.get("alias_kolom", {}))
    semua_sumber = {**konfig.get("sumber", {}), **(konfig.get("sumber_opsional") or {})}
    meta = konfig.get("meta", {}) or {}

    print("=" * 78)
    print("INSPEKSI HEADER CSV MENTAH (data/raw/)")
    print("=" * 78)
    ada_file = False

    for alias, ksum in semua_sumber.items():
        path = path_sumber(ksum, root)
        print(f"\n### {alias}  ({ksum.get('file')})")
        if not path.exists():
            wajib = "WAJIB" if ksum.get("wajib", True) else "opsional"
            print(f"    [belum ada] file {wajib} ini belum diletakkan di data/raw/.")
            continue

        ada_file = True
        df = baca_csv(path, str(meta.get("encoding", "utf-8")), meta.get("sep", "auto"))
        print(f"    baris: {len(df):,} | kolom: {len(df.columns)}")
        print(f"    header asli : {list(df.columns)}")

        ternormalisasi = normalisasi_nama_kolom(df)
        terpetakan = petakan_kolom(ternormalisasi, peta_alias, ksum.get("rename"))
        print(f"    setelah map : {list(terpetakan.columns)}")

        baku = set(peta_alias.values()) | {str(ksum.get("measure", ""))}
        sisa = [k for k in terpetakan.columns if k not in baku]
        if sisa:
            print(f"    belum dikenali (kandidat kolom kategori/measure): {sisa}")
        print(f"    contoh baris:\n{df.head(3).to_string(index=False)}")

    print("\n" + "=" * 78)
    if not ada_file:
        print("Tidak ada satu pun CSV di data/raw/. Lihat README bagian 'Menyiapkan data'.")
    else:
        print("Kalau ada kolom penting yang 'belum dikenali', tambahkan namanya ke")
        print("config/sources.yaml -> alias_kolom (atau rename pada sumber terkait).")
    print("=" * 78)
    return 0


# --------------------------------------------------------------------------- #
# Pipeline utama
# --------------------------------------------------------------------------- #
def jalankan(
    path_konfig: Path | None = None,
    dir_keluaran: Path | None = None,
    root: Path | None = None,
    tulis_duckdb: bool = False,
    diam: bool = False,
) -> tuple[StarSchema, LaporanValidasi]:
    """Jalankan pipeline penuh dan kembalikan ``(star, laporan)``."""
    root = root or ROOT_PROYEK
    dir_keluaran = dir_keluaran or DIR_PROCESSED_DEFAULT
    konfig = muat_konfigurasi(path_konfig or KONFIG_DEFAULT)

    def log(pesan: str = "") -> None:
        if not diam:
            print(pesan)

    log("=" * 78)
    log("ETL STAR SCHEMA KEPATUHAN PAJAK KENDARAAN BERMOTOR - JAWA BARAT")
    log("=" * 78)

    log("\n[1/5] EXTRACT - membaca CSV mentah dari data/raw/ (tanpa akses jaringan)")
    tabel_mentah = ekstrak(konfig, root)
    log(ringkas_ekstrak(tabel_mentah, root))

    log("\n[2/5] TRANSFORM - membersihkan, unpivot, menyamakan grain")
    hasil = transform_semua(tabel_mentah, konfig)
    catatan_transform = kumpulkan_catatan(hasil)
    for pesan in catatan_transform:
        log(f"  {pesan}")

    log("\n[3/5] BUILD - membangun dimensi, surrogate key, dan measure turunan")
    star = bangun_star(hasil, konfig)
    for pesan in star.catatan:
        log(f"  {pesan}")

    log("\n[4/5] VALIDATE")
    laporan = validasi(star, konfig, catatan_transform)

    log("\n[5/5] EXPORT")
    if laporan.lolos:
        for path in ekspor_csv(star, dir_keluaran):
            log(f"  ditulis: {_rel(path, root)}")
        if tulis_duckdb:
            path_db = ekspor_duckdb(star, dir_keluaran / "star.duckdb")
            log(f"  ditulis: {_rel(path_db, root)}")
    else:
        log("  DILEWATI - validasi menemukan masalah FATAL, output tidak ditulis.")

    log("")
    log(laporan.ringkasan())
    _simpan_laporan(laporan, dir_keluaran)
    return star, laporan


def _simpan_laporan(laporan: LaporanValidasi, dir_keluaran: Path) -> None:
    dir_keluaran.mkdir(parents=True, exist_ok=True)
    (dir_keluaran / "laporan_validasi.txt").write_text(
        laporan.ringkasan() + "\n", encoding="utf-8"
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_argumen(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m etl.run",
        description=(
            "Bangun star schema kepatuhan pajak kendaraan bermotor Jawa Barat "
            "dari CSV mentah Open Data Jabar di data/raw/."
        ),
    )
    parser.add_argument("--config", type=Path, default=None, help="path config/sources.yaml")
    parser.add_argument("--out-dir", type=Path, default=None, help="folder output (default data/processed)")
    parser.add_argument("--duckdb", action="store_true", help="tulis juga data/processed/star.duckdb")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="hanya cetak header CSV mentah + hasil pemetaan kolom, lalu berhenti",
    )
    parser.add_argument("--quiet", action="store_true", help="cetak ringkasan validasi saja")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_argumen(argv)
    try:
        konfig_path = args.config or KONFIG_DEFAULT
        if args.inspect:
            return inspeksi(muat_konfigurasi(konfig_path), ROOT_PROYEK)

        _, laporan = jalankan(
            path_konfig=konfig_path,
            dir_keluaran=args.out_dir,
            tulis_duckdb=args.duckdb,
            diam=args.quiet,
        )
        if args.quiet:
            print(laporan.ringkasan())
        return 0 if laporan.lolos else 1

    except BerkasMentahHilangError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KonfigurasiTidakValidError as exc:
        print(f"Konfigurasi tidak valid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
