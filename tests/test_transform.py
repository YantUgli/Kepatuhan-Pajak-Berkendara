"""Unit test fungsi transform & build yang kritis (Bagian 11 butir 7 brief).

Cakupan wajib: unpivot, pembuatan surrogate key, perhitungan tingkat_kepatuhan.
Ditambah: parsing angka gaya Indonesia, normalisasi ejaan, dan idempotensi.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etl.build_star import (
    buat_dimensi,
    bangun_dim_waktu,
    bangun_dim_wilayah,
    hitung_measure_turunan,
    hitung_rata_pajak_per_kendaraan,
)
from etl.transform import (
    NILAI_TIDAK_DIRINCI,
    agregasi_ke_grain,
    bangun_peta_alias,
    bangun_peta_nilai,
    bersihkan_teks,
    ke_numerik,
    ke_tahun,
    normalisasi_nama_kolom,
    petakan_kolom,
    terapkan_peta_nilai,
    transform_sumber,
    unpivot_wide,
)


# --------------------------------------------------------------------------- #
# Unpivot (wide -> long)
# --------------------------------------------------------------------------- #
def test_unpivot_wide_mengubah_kolom_kategori_jadi_baris():
    wide = pd.DataFrame(
        {
            "tahun": [2020, 2021],
            "cabang_pelayanan": ["Bandung", "Bandung"],
            "sepeda_motor": [100, 110],
            "mobil_penumpang": [20, 25],
        }
    )
    panjang = unpivot_wide(
        wide,
        id_vars=["tahun", "cabang_pelayanan"],
        var_name="jenis_kendaraan",
        value_name="jumlah_kendaraan",
    )

    assert list(panjang.columns) == [
        "tahun",
        "cabang_pelayanan",
        "jenis_kendaraan",
        "jumlah_kendaraan",
    ]
    assert len(panjang) == 4  # 2 tahun x 2 kategori
    assert set(panjang["jenis_kendaraan"]) == {"sepeda_motor", "mobil_penumpang"}
    assert panjang["jumlah_kendaraan"].sum() == 255


def test_unpivot_wide_tanpa_kolom_kategori_gagal():
    wide = pd.DataFrame({"tahun": [2020], "cabang_pelayanan": ["Bandung"]})
    with pytest.raises(Exception):
        unpivot_wide(wide, ["tahun", "cabang_pelayanan"], "jenis_kendaraan", "jumlah")


def test_transform_sumber_mendeteksi_bentuk_wide_secara_otomatis():
    wide = pd.DataFrame(
        {
            "Tahun": ["2020", "2021"],
            "Cabang Pelayanan": ["BANDUNG", "bandung"],
            "Sepeda Motor": ["1.000", "1.100"],
            "Mobil Penumpang": ["200", "250"],
        }
    )
    konfig_sumber = {
        "bentuk": "auto",
        "keys": ["tahun", "cabang_pelayanan", "jenis_kendaraan", "fungsi_kendaraan"],
        "measure_sumber": ["jumlah_kendaraan"],
        "measure": "jumlah_kendaraan_total",
        "unpivot": {"id_vars": ["tahun", "cabang_pelayanan"], "var_name": "jenis_kendaraan"},
    }
    konfig = {
        "alias_kolom": {"tahun": ["tahun"], "cabang_pelayanan": ["cabang_pelayanan"]},
        "normalisasi_teks": {"jenis_kendaraan": {"Sepeda Motor": ["sepeda motor"]}},
    }

    hasil = transform_sumber(wide, "kendaraan_total", konfig_sumber, konfig)

    assert set(hasil.df.columns) >= {
        "tahun",
        "cabang_pelayanan",
        "jenis_kendaraan",
        "fungsi_kendaraan",
        "jumlah_kendaraan_total",
    }
    # Ejaan cabang disamakan -> hanya satu nilai
    assert hasil.df["cabang_pelayanan"].unique().tolist() == ["Bandung"]
    # Dimensi yang tidak ada di sumber diisi placeholder, bukan dibuang
    assert (hasil.df["fungsi_kendaraan"] == NILAI_TIDAK_DIRINCI).all()
    assert hasil.df["jumlah_kendaraan_total"].sum() == 2550.0


# --------------------------------------------------------------------------- #
# Surrogate key
# --------------------------------------------------------------------------- #
def test_surrogate_key_mulai_dari_satu_dan_unik():
    dim = buat_dimensi(["Bogor", "Bandung", "Bekasi"], "cabang_pelayanan", "wilayah_id")

    assert dim["wilayah_id"].tolist() == [1, 2, 3]
    assert dim["cabang_pelayanan"].tolist() == ["Bandung", "Bekasi", "Bogor"]  # terurut
    assert dim["wilayah_id"].is_unique


def test_surrogate_key_stabil_walau_urutan_input_berbeda():
    a = buat_dimensi(["Bogor", "Bandung", "Bandung"], "cabang_pelayanan", "wilayah_id")
    b = buat_dimensi(["Bandung", "Bogor"], "cabang_pelayanan", "wilayah_id")

    pd.testing.assert_frame_equal(a, b)  # idempoten: id tidak bergeser antar run


def test_buat_dimensi_membuang_null_dan_duplikat():
    dim = buat_dimensi(
        ["Umum", None, "Pribadi", "Umum", np.nan], "fungsi_kendaraan", "fungsi_kendaraan_id"
    )
    assert len(dim) == 2
    assert dim["fungsi_kendaraan"].tolist() == ["Pribadi", "Umum"]


def test_dim_waktu_punya_atribut_turunan():
    dim = bangun_dim_waktu([2021, 2013, 2013])
    assert dim["waktu_id"].tolist() == [1, 2]
    assert dim["tahun"].tolist() == [2013, 2021]
    assert dim["dekade"].tolist() == [2010, 2020]


def test_dim_wilayah_grain_cabang_dan_kolom_kabkota_boleh_null():
    atribut = pd.DataFrame(
        {
            "cabang_pelayanan": ["Bandung"],
            "kode_kabupaten_kota": ["3273"],
            "nama_kabupaten_kota": ["Kota Bandung"],
            "nama_provinsi": ["Jawa Barat"],
        }
    )
    dim = bangun_dim_wilayah(["Bandung", "Bekasi"], atribut)

    assert len(dim) == 2  # tetap 1 baris per cabang, tidak berganda
    assert list(dim.columns) == [
        "wilayah_id",
        "cabang_pelayanan",
        "kode_kabupaten_kota",
        "nama_kabupaten_kota",
        "nama_provinsi",
    ]
    assert pd.isna(dim.loc[dim["cabang_pelayanan"] == "Bekasi", "kode_kabupaten_kota"].iloc[0])
    assert dim["nama_provinsi"].tolist() == ["Jawa Barat", "Jawa Barat"]


# --------------------------------------------------------------------------- #
# Measure turunan & tingkat kepatuhan
# --------------------------------------------------------------------------- #
def _fact_contoh() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tahun": [2020, 2020, 2020, 2020],
            "jumlah_kendaraan_total": [100.0, 100.0, 0.0, np.nan],
            "jumlah_tidak_daftar_ulang": [20.0, 80.0, 0.0, 5.0],
            "jumlah_belum_daftar_ulang": [10.0, 40.0, 0.0, 5.0],
            "rata_pajak_per_kendaraan": [1_000_000.0] * 4,
        }
    )


def test_tingkat_kepatuhan_dihitung_benar():
    hasil = hitung_measure_turunan(_fact_contoh())
    assert hasil.loc[0, "jumlah_daftar_ulang"] == 70.0
    assert hasil.loc[0, "tingkat_kepatuhan"] == pytest.approx(0.7)


def test_tingkat_kepatuhan_selalu_dalam_rentang_nol_satu():
    hasil = hitung_measure_turunan(_fact_contoh())
    nilai = hasil["tingkat_kepatuhan"].dropna()
    assert ((nilai >= 0) & (nilai <= 1)).all()


def test_daftar_ulang_negatif_di_floor_ke_nol():
    # total 100 - tidak 80 - belum 40 = -20 -> harus jadi 0
    hasil = hitung_measure_turunan(_fact_contoh())
    assert hasil.loc[1, "jumlah_daftar_ulang"] == 0.0
    assert hasil.loc[1, "tingkat_kepatuhan"] == pytest.approx(0.0)


def test_tingkat_kepatuhan_null_bila_penyebut_nol_atau_kosong():
    hasil = hitung_measure_turunan(_fact_contoh())
    assert pd.isna(hasil.loc[2, "tingkat_kepatuhan"])  # total = 0
    assert pd.isna(hasil.loc[3, "tingkat_kepatuhan"])  # total = NaN


def test_estimasi_pajak_hilang_dari_rata_pajak_per_kendaraan():
    hasil = hitung_measure_turunan(_fact_contoh())
    assert hasil.loc[0, "estimasi_pajak_hilang"] == pytest.approx(20 * 1_000_000)


def test_rata_pajak_per_kendaraan_mengecualikan_denda():
    df_pajak = pd.DataFrame(
        {
            "tahun": [2020, 2020],
            "jenis_pajak": ["PKB", "Denda PKB"],
            "nilai_rupiah": [1_000_000_000.0, 500_000_000.0],
        }
    )
    df_fact = pd.DataFrame({"tahun": [2020], "jumlah_kendaraan_total": [1000.0]})

    hasil = hitung_rata_pajak_per_kendaraan(
        df_pajak, df_fact, {"komponen_pajak": ["pkb"], "komponen_denda": ["denda"]}
    )
    # Hanya komponen pajak (1 miliar) / 1000 kendaraan = 1 juta
    assert hasil.loc[0, "rata_pajak_per_kendaraan"] == pytest.approx(1_000_000.0)


def test_rata_pajak_per_kendaraan_nan_bila_data_pajak_tidak_ada():
    df_fact = pd.DataFrame({"tahun": [2020], "jumlah_kendaraan_total": [1000.0]})
    hasil = hitung_rata_pajak_per_kendaraan(None, df_fact, {})
    assert pd.isna(hasil.loc[0, "rata_pajak_per_kendaraan"])


# --------------------------------------------------------------------------- #
# Tipe data
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("masukan", "harapan"),
    [
        ("1.234.567", 1_234_567.0),
        ("1,234,567", 1_234_567.0),
        ("1.234.567,89", 1_234_567.89),
        ("1,234,567.89", 1_234_567.89),
        ("Rp 25.000", 25_000.0),
        ("1234", 1234.0),
        ("12,5", 12.5),
        ("(1.500)", -1500.0),
        ("", np.nan),
        ("-", np.nan),
        (None, np.nan),
    ],
)
def test_ke_numerik_menangani_format_angka_indonesia(masukan, harapan):
    hasil = ke_numerik(pd.Series([masukan])).iloc[0]
    if pd.isna(harapan):
        assert pd.isna(hasil)
    else:
        assert hasil == pytest.approx(harapan)


def test_ke_tahun_menghasilkan_integer_nullable():
    hasil = ke_tahun(pd.Series(["2013", "2020.0", "Tahun 2021", "bukan tahun"]))
    assert hasil.tolist()[:3] == [2013, 2020, 2021]
    assert pd.isna(hasil.iloc[3])
    assert str(hasil.dtype) == "Int64"


# --------------------------------------------------------------------------- #
# Standarisasi teks & pemetaan kolom
# --------------------------------------------------------------------------- #
def test_bersihkan_teks_trim_dan_title_case():
    hasil = bersihkan_teks(pd.Series(["  SEPEDA   MOTOR ", "mobil_bus"]))
    assert hasil.tolist() == ["Sepeda Motor", "Mobil Bus"]


def test_terapkan_peta_nilai_menyamakan_ejaan_dan_melaporkan_sisa():
    peta = bangun_peta_nilai({"Sepeda Motor": ["sepeda motor", "motor"]})
    seri, belum = terapkan_peta_nilai(pd.Series(["MOTOR", "Sepeda  Motor", "Perahu"]), peta)

    assert seri.tolist()[:2] == ["Sepeda Motor", "Sepeda Motor"]
    assert seri.tolist()[2] == "Perahu"  # tidak dibuang
    assert belum == ["Perahu"]


def test_petakan_kolom_memakai_alias_dari_konfigurasi():
    df = pd.DataFrame({"BPS Nama Kabupaten Kota": ["Kota Bandung"], "Thn": ["2020"]})
    peta = bangun_peta_alias(
        {"nama_kabupaten_kota": ["bps_nama_kabupaten_kota"], "tahun": ["thn"]}
    )
    hasil = petakan_kolom(normalisasi_nama_kolom(df), peta)
    assert set(hasil.columns) == {"nama_kabupaten_kota", "tahun"}


def test_normalisasi_nama_kolom_membuat_snake_case():
    df = pd.DataFrame({"Jenis Kendaraan": [1], "JUMLAH-KENDARAAN": [2]})
    assert list(normalisasi_nama_kolom(df).columns) == ["jenis_kendaraan", "jumlah_kendaraan"]


# --------------------------------------------------------------------------- #
# Grain
# --------------------------------------------------------------------------- #
def test_agregasi_ke_grain_menjumlahkan_duplikat():
    df = pd.DataFrame(
        {
            "tahun": [2020, 2020, 2021],
            "cabang_pelayanan": ["Bandung", "Bandung", "Bandung"],
            "jumlah": [10.0, 5.0, 7.0],
        }
    )
    hasil, terlipat = agregasi_ke_grain(df, ["tahun", "cabang_pelayanan"], "jumlah")

    assert terlipat == 1
    assert len(hasil) == 2
    assert hasil.loc[hasil["tahun"] == 2020, "jumlah"].iloc[0] == 15.0


def test_transform_sumber_membuang_baris_total():
    df = pd.DataFrame(
        {
            "tahun": ["2020", "2020"],
            "cabang_pelayanan": ["Bandung", "Jumlah"],
            "jenis_kendaraan": ["Sepeda Motor", "Sepeda Motor"],
            "fungsi_kendaraan": ["Pribadi", "Pribadi"],
            "jumlah_kendaraan": ["10", "10"],
        }
    )
    konfig_sumber = {
        "bentuk": "auto",
        "keys": ["tahun", "cabang_pelayanan", "jenis_kendaraan", "fungsi_kendaraan"],
        "measure_sumber": ["jumlah_kendaraan"],
        "measure": "jumlah_kendaraan_total",
    }
    hasil = transform_sumber(df, "kendaraan_total", konfig_sumber, {})

    assert len(hasil.df) == 1
    assert hasil.df["cabang_pelayanan"].iloc[0] == "Bandung"
