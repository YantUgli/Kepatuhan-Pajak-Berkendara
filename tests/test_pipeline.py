"""Smoke test end-to-end: extract -> transform -> build -> validate -> export.

Memakai CSV sintetis kecil di folder sementara (bukan data asli), sehingga test
tetap jalan walau ``data/raw/`` masih kosong. Tujuannya memastikan pipeline utuh
menghasilkan star schema yang lolos validasi dan idempoten.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from etl import KONFIG_DEFAULT
from etl.extract import BerkasMentahHilangError, muat_konfigurasi
from etl.run import jalankan

CABANG = ["Bandung", "Bekasi"]
JENIS = ["Sepeda Motor", "Mobil Penumpang"]
FUNGSI = ["Pribadi", "Umum"]
TAHUN = [2013, 2014]


def _baris_count(nilai_awal: int) -> pd.DataFrame:
    baris = []
    n = nilai_awal
    for tahun in TAHUN:
        for i, cabang in enumerate(CABANG):
            for jenis in JENIS:
                for fungsi in FUNGSI:
                    baris.append(
                        {
                            "kode_provinsi": "32",
                            "nama_provinsi": "JAWA BARAT",
                            "kode_kabupaten_kota": f"327{i}",
                            "nama_kabupaten_kota": f"KOTA {cabang.upper()}",
                            "cabang_pelayanan": cabang.upper(),
                            "jenis_kendaraan": jenis.upper(),
                            "fungsi_kendaraan": fungsi.upper(),
                            "jumlah_kendaraan": f"{n:,}".replace(",", "."),
                            "satuan": "UNIT",
                            "tahun": str(tahun),
                        }
                    )
                    n += 137
    return pd.DataFrame(baris)


@pytest.fixture()
def root_sintetis(tmp_path: Path) -> Path:
    """Root repo tiruan: config asli + data/raw berisi CSV sintetis."""
    (tmp_path / "config").mkdir()
    shutil.copy(KONFIG_DEFAULT, tmp_path / "config" / "sources.yaml")
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)

    total = _baris_count(10_000)
    total.to_csv(raw / "kendaraan_total.csv", index=False)

    tidak = total.copy()
    tidak["jumlah_kendaraan"] = (
        total["jumlah_kendaraan"].str.replace(".", "", regex=False).astype(int) // 10
    ).astype(str)
    tidak.to_csv(raw / "tidak_daftar_ulang.csv", index=False)

    belum = total.copy()
    belum["jumlah_kendaraan"] = (
        total["jumlah_kendaraan"].str.replace(".", "", regex=False).astype(int) // 20
    ).astype(str)
    belum.to_csv(raw / "belum_daftar_ulang.csv", index=False)

    pajak = pd.DataFrame(
        [
            {"kode_provinsi": "32", "nama_provinsi": "JAWA BARAT", "jenis_pajak": jp,
             "nilai": nilai, "satuan": "RUPIAH", "tahun": str(tahun)}
            for tahun in TAHUN
            for jp, nilai in (
                ("PAJAK KENDARAAN BERMOTOR", "5.000.000.000"),
                ("DENDA PKB", "250.000.000"),
            )
        ]
    )
    pajak.to_csv(raw / "pajak_denda.csv", index=False)
    return tmp_path


def test_pipeline_penuh_lolos_validasi(root_sintetis: Path):
    star, laporan = jalankan(
        path_konfig=root_sintetis / "config" / "sources.yaml",
        dir_keluaran=root_sintetis / "data" / "processed",
        root=root_sintetis,
        diam=True,
    )

    assert laporan.lolos, laporan.ringkasan()

    # Grain: 2 tahun x 2 cabang x 2 jenis x 2 fungsi = 16 baris
    fact = star.fact
    assert len(fact) == 16
    assert not fact.duplicated(
        subset=["tahun", "cabang_pelayanan", "jenis_kendaraan", "fungsi_kendaraan"]
    ).any()

    # Semua FK terisi dan measure turunan masuk akal
    for fk in ("waktu_id", "wilayah_id", "jenis_kendaraan_id", "fungsi_kendaraan_id"):
        assert fact[fk].notna().all()
    assert fact["tingkat_kepatuhan"].between(0, 1).all()
    assert (fact["estimasi_pajak_hilang"] > 0).all()

    # Dimensi sesuai target Bagian 5 brief
    assert star.tabel["dim_waktu"]["tahun"].tolist() == TAHUN
    assert star.tabel["dim_wilayah"]["cabang_pelayanan"].tolist() == CABANG
    assert star.tabel["dim_jenis_kendaraan"]["jenis_kendaraan"].tolist() == sorted(JENIS)
    assert star.tabel["dim_fungsi_kendaraan"]["fungsi_kendaraan"].tolist() == sorted(FUNGSI)


def test_semua_file_output_terbentuk(root_sintetis: Path):
    keluaran = root_sintetis / "data" / "processed"
    jalankan(
        path_konfig=root_sintetis / "config" / "sources.yaml",
        dir_keluaran=keluaran,
        root=root_sintetis,
        diam=True,
    )
    wajib = [
        "dim_waktu.csv",
        "dim_wilayah.csv",
        "dim_jenis_kendaraan.csv",
        "dim_fungsi_kendaraan.csv",
        "fakta_kepatuhan_kendaraan.csv",
    ]
    for nama in wajib:
        assert (keluaran / nama).exists(), f"{nama} tidak dihasilkan"


def test_pipeline_idempoten(root_sintetis: Path):
    """Menjalankan run.py dua kali menghasilkan file yang identik byte-per-byte."""
    keluaran = root_sintetis / "data" / "processed"
    argumen = dict(
        path_konfig=root_sintetis / "config" / "sources.yaml",
        dir_keluaran=keluaran,
        root=root_sintetis,
        diam=True,
    )

    jalankan(**argumen)
    pertama = {p.name: p.read_bytes() for p in sorted(keluaran.glob("*.csv"))}
    jalankan(**argumen)
    kedua = {p.name: p.read_bytes() for p in sorted(keluaran.glob("*.csv"))}

    assert pertama.keys() == kedua.keys()
    for nama in pertama:
        assert pertama[nama] == kedua[nama], f"{nama} berubah antar run"


def test_ekspor_duckdb_opsional(root_sintetis: Path):
    """Flag --duckdb menulis semua tabel ke satu database (dilewati bila duckdb belum dipasang)."""
    duckdb = pytest.importorskip("duckdb", reason="pasang dengan: pipenv install --categories duckdb")

    keluaran = root_sintetis / "data" / "processed"
    jalankan(
        path_konfig=root_sintetis / "config" / "sources.yaml",
        dir_keluaran=keluaran,
        root=root_sintetis,
        tulis_duckdb=True,
        diam=True,
    )
    path_db = keluaran / "star.duckdb"
    assert path_db.exists()

    koneksi = duckdb.connect(str(path_db))
    try:
        tabel = {t[0] for t in koneksi.execute("SHOW TABLES").fetchall()}
        assert {"dim_waktu", "dim_wilayah", "fakta_kepatuhan_kendaraan"} <= tabel
        jumlah = koneksi.execute("SELECT COUNT(*) FROM fakta_kepatuhan_kendaraan").fetchone()[0]
        assert jumlah == 16
    finally:
        koneksi.close()


def test_gagal_dengan_pesan_jelas_bila_raw_kosong(tmp_path: Path):
    (tmp_path / "config").mkdir()
    shutil.copy(KONFIG_DEFAULT, tmp_path / "config" / "sources.yaml")
    (tmp_path / "data" / "raw").mkdir(parents=True)

    with pytest.raises(BerkasMentahHilangError) as exc:
        jalankan(
            path_konfig=tmp_path / "config" / "sources.yaml",
            dir_keluaran=tmp_path / "data" / "processed",
            root=tmp_path,
            diam=True,
        )

    pesan = str(exc.value)
    assert "kendaraan_total.csv" in pesan
    assert "tidak_daftar_ulang.csv" in pesan
    assert "belum_daftar_ulang.csv" in pesan
    assert "pajak_denda.csv" in pesan
    assert "Unduh" in pesan  # instruksi extract manual ikut tercetak


def test_konfigurasi_default_memuat_semua_sumber_inti():
    konfig = muat_konfigurasi(KONFIG_DEFAULT)
    assert set(konfig["sumber"]) == {
        "kendaraan_total",
        "tidak_daftar_ulang",
        "belum_daftar_ulang",
        "pajak_denda",
    }
    for ksum in konfig["sumber"].values():
        assert ksum["wajib"] is True
        assert ksum["file"].startswith("data/raw/")
