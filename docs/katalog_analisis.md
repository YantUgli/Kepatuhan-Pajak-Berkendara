# Katalog Analisis — Pertanyaan yang Bisa Dijawab Star Schema Ini

Daftar pertanyaan analisis yang **sudah pasti bisa dijawab** dari `data/processed/`,
lengkap dengan measure + dimensi yang dipakai dan rumus agregasinya. Dipakai sebagai
peta kerja oleh anggota kelompok yang membangun dashboard & menulis laporan.

Definisi kolom ada di [data_dictionary.md](data_dictionary.md).

> **Aturan wajib:** `tingkat_kepatuhan` **tidak boleh** dirata-rata antar baris. Selalu
> hitung ulang sebagai `SUM(jumlah_daftar_ulang) / SUM(jumlah_kendaraan_total)` pada level
> agregasi yang diinginkan. Measure jumlah dan `estimasi_pajak_hilang` aditif penuh.

---

## A1. Bagaimana tren tingkat kepatuhan daftar ulang dari tahun ke tahun?

- **Measure:** `tingkat_kepatuhan` (hitung ulang dari `jumlah_daftar_ulang`, `jumlah_kendaraan_total`)
- **Dimensi:** `dim_waktu.tahun`
- **Agregasi:** `SUM(jumlah_daftar_ulang) / SUM(jumlah_kendaraan_total)` per tahun
- **Visual usulan:** line chart, sumbu Y 0–100%
- **Kegunaan:** pertanyaan utama laporan — apakah kepatuhan membaik atau memburuk.

```sql
SELECT w.tahun,
       SUM(f.jumlah_daftar_ulang) / NULLIF(SUM(f.jumlah_kendaraan_total), 0) AS tingkat_kepatuhan
FROM fakta_kepatuhan_kendaraan f
JOIN dim_waktu w ON w.waktu_id = f.waktu_id
GROUP BY w.tahun
ORDER BY w.tahun;
```

## A2. Cabang pelayanan mana yang estimasi pajak hilangnya terbesar?

- **Measure:** `estimasi_pajak_hilang`
- **Dimensi:** `dim_wilayah.cabang_pelayanan` (opsional filter `dim_waktu.tahun`)
- **Agregasi:** `SUM(estimasi_pajak_hilang)`
- **Visual usulan:** bar chart horizontal Top-10
- **Catatan:** sertakan disclaimer asumsi monetisasi (kamus data Bagian 5).

```sql
SELECT d.cabang_pelayanan, SUM(f.estimasi_pajak_hilang) AS potensi_hilang
FROM fakta_kepatuhan_kendaraan f
JOIN dim_wilayah d ON d.wilayah_id = f.wilayah_id
WHERE f.tahun = 2023
GROUP BY d.cabang_pelayanan
ORDER BY potensi_hilang DESC
LIMIT 10;
```

## A3. Cabang pelayanan mana yang tingkat kepatuhannya terendah?

- **Measure:** `tingkat_kepatuhan`
- **Dimensi:** `dim_wilayah.cabang_pelayanan`, `dim_waktu.tahun`
- **Agregasi:** rasio SUM/SUM per cabang
- **Visual usulan:** bar chart + tabel pendamping berisi `jumlah_kendaraan_total`
  (agar cabang kecil dengan rasio ekstrem tidak salah dibaca)
- **Kegunaan:** menentukan prioritas intervensi — beda dengan A2 yang berbasis nilai rupiah.

## A4. Bagaimana kepatuhan berbeda menurut jenis kendaraan (roda dua vs roda empat)?

- **Measure:** `tingkat_kepatuhan`, `jumlah_kendaraan_total`
- **Dimensi:** `dim_jenis_kendaraan.jenis_kendaraan`, `dim_waktu.tahun`
- **Agregasi:** rasio SUM/SUM per jenis per tahun
- **Visual usulan:** multi-line chart (satu garis per jenis)
- **Kegunaan:** menguji dugaan bahwa sepeda motor mendominasi ketidakpatuhan karena
  jumlahnya paling besar.
- **Kategori aktual di data:** `Sepeda Motor`, `Sedan/Jeep/Minibus/Station Wagon`,
  `Bus/Microbus`, `Truck/Pick Up`, `Alat Berat` (bukan kategori generik "roda
  dua/roda empat" — kelompokkan manual bila butuh perbandingan itu, mis.
  `Sepeda Motor` = roda dua, sisanya = roda empat+). **Catatan:** hindari memakai
  segmen `Alat Berat` untuk klaim tingkat kepatuhan — definisinya tampak tidak
  konsisten antar dataset sumber (lihat data_dictionary.md Bagian 4 poin 3).

## A5. Bagaimana kepatuhan berbeda menurut fungsi kendaraan (pribadi vs umum vs dinas)?

- **Measure:** `tingkat_kepatuhan`
- **Dimensi:** `dim_fungsi_kendaraan.fungsi_kendaraan`, `dim_waktu.tahun`
- **Agregasi:** rasio SUM/SUM per fungsi
- **Visual usulan:** grouped bar per tahun
- **Catatan:** buang/labeli kategori `Tidak Dirinci` bila muncul — artinya sumber tidak
  merinci fungsi untuk baris tersebut, bukan kategori nyata.

## A6. Mana yang lebih dominan: "tidak daftar ulang" atau "belum daftar ulang", dan di wilayah mana?

- **Measure:** `jumlah_tidak_daftar_ulang`, `jumlah_belum_daftar_ulang`
- **Dimensi:** `dim_wilayah.cabang_pelayanan`, `dim_waktu.tahun`
- **Agregasi:** `SUM` masing-masing, plus rasio `tidak / (tidak + belum)`
- **Visual usulan:** stacked bar 100% per cabang
- **Kegunaan:** membedakan masalah **kebocoran permanen** (tidak daftar ulang) dari
  **keterlambatan** (belum daftar ulang) — implikasi kebijakannya berbeda.

## A7. Segmen mana (kombinasi jenis × fungsi) yang paling banyak menyumbang potensi kehilangan?

- **Measure:** `estimasi_pajak_hilang`, `jumlah_tidak_daftar_ulang`
- **Dimensi:** `dim_jenis_kendaraan` × `dim_fungsi_kendaraan`
- **Agregasi:** `SUM` per kombinasi
- **Visual usulan:** heatmap / matrix jenis × fungsi
- **Kegunaan:** menemukan segmen prioritas penagihan.

## A8. Berapa total estimasi potensi kehilangan pendapatan daerah per tahun, dan bagaimana trennya?

- **Measure:** `estimasi_pajak_hilang`
- **Dimensi:** `dim_waktu.tahun`
- **Agregasi:** `SUM(estimasi_pajak_hilang)` per tahun
- **Visual usulan:** KPI card (tahun terakhir) + bar chart tren
- **Catatan:** dampingi dengan `bantu_rata_pajak_tahunan` agar pembaca melihat asumsi
  Rp/kendaraan yang dipakai tiap tahun.

## A9. Apakah pertumbuhan jumlah kendaraan diikuti perbaikan kepatuhan?

- **Measure:** `jumlah_kendaraan_total` (pertumbuhan YoY) vs `tingkat_kepatuhan`
- **Dimensi:** `dim_waktu.tahun`, opsional `dim_wilayah.cabang_pelayanan`
- **Agregasi:** `SUM` populasi per tahun + rasio kepatuhan per tahun
- **Visual usulan:** combo chart (bar populasi + line kepatuhan) atau scatter per cabang
- **Kegunaan:** menjawab apakah beban administrasi tumbuh lebih cepat dari kapasitas
  pelayanan.

## A10. Cabang mana yang membaik dan mana yang memburuk antara tahun awal dan tahun akhir?

- **Measure:** delta `tingkat_kepatuhan` (tahun terakhir − tahun pertama)
- **Dimensi:** `dim_wilayah.cabang_pelayanan`, `dim_waktu.tahun`
- **Agregasi:** hitung rasio per cabang per tahun, lalu selisihkan
- **Visual usulan:** diverging bar chart (positif hijau / negatif merah)
- **Kegunaan:** rekomendasi akhir laporan — praktik cabang yang membaik bisa dicontoh.

---

## Pertanyaan yang **TIDAK** bisa dijawab star schema ini

Ditulis eksplisit supaya tidak dijanjikan di dashboard:

| Pertanyaan | Alasan |
|---|---|
| Kepatuhan per kabupaten/kota | Grain geografis = cabang pelayanan; join ke kab/kota akan menggandakan baris fact (kamus data Bagian 3). |
| Kepatuhan per bulan / musiman | Sumber agregat tahunan. |
| Profil pemilik kendaraan yang menunggak | Tidak ada data level individu. |
| Realisasi vs target pendapatan | Butuh dataset opsional `target_pajak` & `realisasi_pajak` (belum masuk MVP; ada di `config/sources.yaml` → `sumber_opsional`). |
| Adopsi kanal pembayaran (e-Samsat) | Butuh dataset opsional `esamsat`. |
| Nilai pajak per kendaraan yang sebenarnya | ETL hanya punya rata-rata agregat, bukan tarif per NJKB. |
