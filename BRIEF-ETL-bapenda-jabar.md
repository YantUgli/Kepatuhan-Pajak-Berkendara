# BRIEF PROYEK ETL — Star Schema Kepatuhan Pajak Kendaraan Bermotor Jawa Barat

> **Dokumen ini adalah brief yang bisa langsung dieksekusi oleh Claude Code.**
> Simpan sebagai `BRIEF.md` (atau tempel sebagai instruksi awal) di root repo, lalu minta
> Claude Code mengerjakannya tahap demi tahap sesuai bagian **"Tugas untuk Claude Code"**.

---

## 1. Konteks & Tujuan

Ini bagian ETL dari proyek Business Intelligence satu semester (mata kuliah BI). Studi kasus:
**Badan Pendapatan Daerah (Bapenda) Provinsi Jawa Barat**, tema kepatuhan daftar ulang pajak
kendaraan bermotor dan estimasi potensi kehilangan pendapatan daerah.

Tujuan repo ini: mengubah beberapa dataset agregat mentah dari Open Data Jabar menjadi
**sekumpulan tabel fact + dimension (star schema) yang bersih**, plus dokumentasi, sehingga
anggota kelompok lain bisa langsung memakainya untuk membangun dashboard BI dan menulis laporan.

**Output ETL ini BUKAN dashboard.** Output-nya adalah data siap-model + kamus data + katalog
analisis. Pembuatan dashboard/visualisasi dikerjakan terpisah oleh anggota lain.

---

## 2. Ruang Lingkup (Scope) & Non-Goals

**In scope**
- Membaca CSV mentah dari `data/raw/`.
- Membersihkan, meng-*unpivot* (kalau perlu), menyamakan grain, membuat surrogate key.
- Menghasilkan tabel `dim_*` dan `fakta_*` ke `data/processed/` (format CSV; opsional DuckDB).
- Menghitung measure turunan: tingkat kepatuhan & estimasi pajak hilang.
- Validasi kualitas data + menulis `docs/data_dictionary.md` dan `docs/katalog_analisis.md`.

**Out of scope (JANGAN dikerjakan)**
- Membangun dashboard / grafik / laporan naratif.
- Scraping otomatis dari portal (lihat Batasan di bawah — portal mem-block bot).
- Analisis statistik lanjutan / ML. Cukup agregasi & measure turunan yang dideklarasikan di sini.

---

## 3. ⚠️ Batasan Penting: Extract Manual (Portal Mem-block Bot)

`opendata.jabarprov.go.id` berada di belakang Cloudflare dan mengembalikan **403 / CF Challenge**
untuk request otomatis. **Jangan** habiskan waktu mencoba `requests`/`httpx`/scraping ke portal —
itu akan gagal.

**Alur extract yang benar:**
1. Manusia (Ayen) mengunduh dataset dari portal lewat browser (tombol **Unduh → CSV**).
   Portal memberi file `.zip` berisi CSV + metadata PDF.
2. Ekstrak CSV-nya, letakkan di `data/raw/` dengan nama file sesuai tabel di Bagian 4.
3. Claude Code hanya bekerja dari `data/raw/` yang sudah terisi.

Kalau `data/raw/` masih kosong saat dijalankan, ETL harus **gagal dengan pesan jelas** yang
menyebutkan file mana yang belum ada — bukan mencoba mengunduh sendiri.

---

## 4. Sumber Data (Dataset Bapenda Jabar di Open Data Jabar)

Semua dataset di bawah mengikuti skema kolom seragam ala Satu Data / BPS. **Kolom identitas
umum** yang muncul di hampir semua dataset:
`kode_provinsi, nama_provinsi, kode_kabupaten_kota, nama_kabupaten_kota, satuan, tahun`.

> **Catatan verifikasi:** nama slug/kolom persis harus dicek ulang saat mengunduh (bisa sedikit
> beda antar dataset/versi). Perlakukan tabel ini sebagai peta awal, dan sesuaikan `config/sources.yaml`
> (lihat Bagian 6) dengan header CSV yang benar-benar ada di file.

### 4a. Dataset inti (WAJIB untuk MVP)

| Alias file (`data/raw/`) | Nama dataset di portal | Dimensi khas | Measure | Rentang tahun* |
|---|---|---|---|---|
| `kendaraan_total.csv` | Jumlah Kendaraan Berdasarkan Jenis Kendaraan, Fungsi Kendaraan, dan Cabang Pelayanan di Jawa Barat | jenis_kendaraan, fungsi_kendaraan, cabang_pelayanan | jumlah_kendaraan | 2013–2023 |
| `tidak_daftar_ulang.csv` | Jumlah Kendaraan yang Tidak Daftar Ulang Berdasarkan Jenis Kendaraan, Fungsi Kendaraan, dan Cabang Pelayanan di Jawa Barat | jenis_kendaraan, fungsi_kendaraan, cabang_pelayanan | jumlah_kendaraan | 2013–2023 |
| `belum_daftar_ulang.csv` | Jumlah Kendaraan yang Belum Daftar Ulang Berdasarkan Jenis Kendaraan, Fungsi Kendaraan, dan Cabang Pelayanan di Jawa Barat | jenis_kendaraan, fungsi_kendaraan, cabang_pelayanan | jumlah_kendaraan | 2013–2023 |
| `pajak_denda.csv` | Jumlah Pajak dan Denda Kendaraan Bermotor Berdasarkan Jenis Pajak Kendaraan Bermotor | jenis_pajak | nilai (rupiah) | cek saat unduh |

*Rentang tahun perkiraan; konfirmasi dari file. Ambil **irisan tahun yang tersedia di semua
dataset inti** sebagai cakupan final (kemungkinan 2013–2023).

### 4b. Dataset pendukung (OPSIONAL, untuk pengayaan — kerjakan hanya jika diminta)

| Alias file | Nama dataset | Kegunaan |
|---|---|---|
| `target_pajak.csv` | Jumlah Target Pajak Daerah Berdasarkan Jenisnya di Jawa Barat | analisis realisasi vs target |
| `realisasi_pajak.csv` | Jumlah Pendapatan Pajak Daerah Berdasarkan Jenis Pajak Daerah di Jawa Barat | realisasi pendapatan |
| `bbnkb.csv` | Jumlah Bea Balik Nama Kendaraan (BBNKB) per Cabang Pelayanan | pendapatan BBNKB |
| `esamsat.csv` | Jumlah Pembayaran PKB Melalui e-Samsat per Bank & Cabang Pelayanan | adopsi kanal digital |
| `kendaraan_cabang.csv` | Jumlah Kendaraan Bermotor Berdasarkan Cabang Pelayanan (2013–2024) | cross-check total |

URL portal untuk memulai pencarian dataset (dibuka manual di browser):
- Katalog dataset: `https://opendata.jabarprov.go.id/id/dataset`
- Halaman Bapenda: `https://bapenda.jabarprov.go.id/open-data-jabar/`
- Contoh dataset terkonfirmasi: `https://opendata.jabarprov.go.id/id/dataset/jumlah-kendaraan-bermotor-berdasarkan-cabang-pelayanan-di-jawa-barat`

---

## 5. Target Star Schema

Karena data sudah agregat, fact table berbentuk **periodic snapshot fact** (bukan transaksional).

### Grain fact
**1 baris = 1 tahun × 1 cabang_pelayanan × 1 jenis_kendaraan × 1 fungsi_kendaraan.**

Ketiga dataset count inti (`kendaraan_total`, `tidak_daftar_ulang`, `belum_daftar_ulang`)
sudah berbagi grain ini, jadi mereka di-*join* pada grain yang sama.

### `fakta_kepatuhan_kendaraan`
| Kolom | Asal | Keterangan |
|---|---|---|
| `waktu_id` (FK) | dim_waktu | |
| `wilayah_id` (FK) | dim_wilayah | |
| `jenis_kendaraan_id` (FK) | dim_jenis_kendaraan | |
| `fungsi_kendaraan_id` (FK) | dim_fungsi_kendaraan | |
| `jumlah_kendaraan_total` | kendaraan_total | measure dasar (penyebut) |
| `jumlah_tidak_daftar_ulang` | tidak_daftar_ulang | measure dasar |
| `jumlah_belum_daftar_ulang` | belum_daftar_ulang | measure dasar |
| `jumlah_daftar_ulang` | turunan = total − tidak − belum (floor di 0) | measure turunan |
| `tingkat_kepatuhan` | turunan = jumlah_daftar_ulang / jumlah_kendaraan_total | rasio 0–1 (null bila total=0) |
| `estimasi_pajak_hilang` | turunan = jumlah_tidak_daftar_ulang × rata_pajak_per_kendaraan | rupiah; lihat asumsi Bagian 7 |

### Dimensi
- **`dim_waktu`**: `waktu_id, tahun`. (Data tahunan; cukup tahun. Tambah dekade/periode bila mau.)
- **`dim_wilayah`**: `wilayah_id, cabang_pelayanan, kode_kabupaten_kota, nama_kabupaten_kota, nama_provinsi`.
  Grain geografis fact = **cabang_pelayanan** (karena dataset daftar-ulang memakai itu). Kolom
  kab/kota diisi bila tersedia di sumber; bila satu cabang mencakup banyak kab/kota, lihat
  keputusan grain di Bagian 7.
- **`dim_jenis_kendaraan`**: `jenis_kendaraan_id, jenis_kendaraan`.
- **`dim_fungsi_kendaraan`**: `fungsi_kendaraan_id, fungsi_kendaraan` (mis. pribadi/umum/dinas).

Semua `*_id` adalah **surrogate key** integer yang dibuat di ETL (bukan dari sumber).

---

## 6. Struktur Repo

```
bi-jabar-kendaraan/
├── data/
│   ├── raw/                 # CSV mentah dari portal (diisi manual)
│   └── processed/           # OUTPUT: dim_*.csv, fakta_*.csv, (opsional star.duckdb)
├── config/
│   └── sources.yaml         # mapping nama file → kolom sumber → kolom baku
├── etl/
│   ├── __init__.py
│   ├── extract.py           # baca raw csv, validasi keberadaan file
│   ├── transform.py         # bersihkan, unpivot, samakan grain, standarisasi
│   ├── build_star.py        # bangun surrogate key, dim, fact, measure turunan
│   ├── validate.py          # cek kualitas (lihat Bagian 8)
│   └── run.py               # orkestrasi: extract→transform→build→validate→export
├── docs/
│   ├── data_dictionary.md   # dihasilkan/dirawat: grain, kolom, satuan, asumsi
│   └── katalog_analisis.md  # daftar pertanyaan analisis + measure/dim yang dipakai
├── tests/
│   └── test_transform.py    # unit test kecil untuk fungsi transform kritis
├── pyproject.toml           # atau requirements.txt
└── README.md
```

`config/sources.yaml` memisahkan *nama kolom sumber* dari *nama kolom baku*, jadi kalau header CSV
sedikit beda, cukup ubah YAML tanpa menyentuh kode. Contoh entri:

```yaml
tidak_daftar_ulang:
  file: data/raw/tidak_daftar_ulang.csv
  rename:
    jumlah_kendaraan: jumlah_tidak_daftar_ulang
  keys: [tahun, cabang_pelayanan, jenis_kendaraan, fungsi_kendaraan]
  measure: jumlah_tidak_daftar_ulang
```

---

## 7. Aturan Transform & Keputusan yang Sudah Dikunci

1. **Unpivot data wide.** Sebagian dataset menaruh kategori sebagai kolom terpisah (mis.
   `mobil_penumpang`, `mobil_bus`, `sepeda_motor` jadi kolom). Ubah ke *long* dengan
   `pandas.melt` menjadi kolom `jenis_kendaraan` + `jumlah_kendaraan` sebelum di-join.
2. **Standarisasi teks dimensi.** Trim spasi, samakan kapitalisasi (title case), rapikan
   ejaan tak konsisten pada `cabang_pelayanan`, `jenis_kendaraan`, `fungsi_kendaraan`
   (mis. "SEPEDA MOTOR" vs "Sepeda Motor"). Dokumentasikan mapping pembersihan.
3. **Tipe data.** `tahun` → int; measure → numerik (buang pemisah ribuan, koma→titik bila perlu);
   nilai kosong measure → 0 hanya bila konteksnya "tidak ada kejadian", selain itu biarkan NaN
   dan catat.
4. **Keputusan grain geografis.** Grain fact = `cabang_pelayanan`. Jika dataset count TIDAK punya
   `kode_kabupaten_kota` pada grainnya, `dim_wilayah` cukup pakai cabang_pelayanan sebagai atribut
   utama; kab/kota jadi atribut opsional (boleh null). **Jangan** memaksa join kab/kota yang
   menggandakan baris fact.
5. **Measure turunan `jumlah_daftar_ulang`** = `total − tidak_daftar_ulang − belum_daftar_ulang`.
   Bila hasilnya negatif (inkonsistensi sumber), floor ke 0 dan catat jumlah baris yang terkena
   di laporan validasi.
6. **Asumsi monetisasi (WAJIB didokumentasikan).**
   `rata_pajak_per_kendaraan` = total nilai PKB dari `pajak_denda.csv` (komponen pajak, bukan denda)
   pada tahun tsb ÷ total kendaraan terdaftar pada tahun tsb. Terapkan per-tahun (bukan satu angka
   untuk semua tahun) bila datanya memungkinkan. `estimasi_pajak_hilang` = jumlah tidak daftar ulang
   × rata_pajak_per_kendaraan. Tulis rumus + keterbatasannya di `data_dictionary.md`.
7. **Idempoten.** Menjalankan `run.py` dua kali menghasilkan output identik (surrogate key stabil,
   diurutkan deterministik).

---

## 8. Validasi (etl/validate.py) — cetak ringkasan, gagalkan bila fatal

- Setiap FK di fact punya pasangan di dim (no orphan). **Fatal** bila gagal.
- `tingkat_kepatuhan` ∈ [0, 1] atau null. Fatal bila di luar rentang.
- Tidak ada baris fact duplikat pada grain (tahun, cabang, jenis, fungsi). Fatal bila ada.
- Rentang `tahun` sesuai irisan yang diharapkan. **Warning** bila menyimpang.
- Hitung & laporkan: jumlah baris per tabel, jumlah null per measure, jumlah baris yang di-floor
  di aturan #5. **Warning** saja.

---

## 9. Output / Artefak Handoff (Definition of Done)

ETL dianggap selesai bila menghasilkan:

1. `data/processed/dim_waktu.csv`, `dim_wilayah.csv`, `dim_jenis_kendaraan.csv`,
   `dim_fungsi_kendaraan.csv`, `fakta_kepatuhan_kendaraan.csv`.
2. (Opsional, jika flag diaktifkan) `data/processed/star.duckdb` berisi semua tabel di atas.
3. `docs/data_dictionary.md` — untuk tiap tabel: grain, tiap kolom (tipe, satuan, deskripsi),
   dan asumsi monetisasi lengkap dengan rumus.
4. `docs/katalog_analisis.md` — daftar 6–10 pertanyaan analisis yang BISA dijawab dengan star
   schema ini, tiap butir menyebut measure + dimensi yang dipakai. Contoh isi:
   - Tren tingkat kepatuhan daftar ulang per tahun (measure: tingkat_kepatuhan; dim: waktu).
   - Cabang pelayanan dengan estimasi pajak hilang terbesar (measure: estimasi_pajak_hilang; dim: wilayah).
   - Kepatuhan menurut jenis kendaraan (roda dua vs roda empat).
   - Kepatuhan menurut fungsi kendaraan (pribadi vs umum vs dinas).
   - Perbandingan "tidak daftar ulang" vs "belum daftar ulang" antar wilayah.
5. `README.md` — cara menaruh data di `data/raw/`, cara menjalankan, dan daftar file raw yang dibutuhkan.
6. Log ringkasan validasi tercetak saat `run.py` selesai.

---

## 10. Batasan Teknis

- Python 3.11+. Library inti: `pandas`, `pyyaml`. Opsional: `duckdb` (hanya bila build DuckDB diminta).
- Manajemen dependensi: `uv` atau `pip` + `requirements.txt` (pilih salah satu, konsisten).
- **Tanpa akses jaringan ke portal** (lihat Bagian 3). Tidak ada dependensi berbayar/berbasis akun.
- Kode modular & terbaca; fungsi transform kritis punya unit test kecil di `tests/`.
- Komentar & docstring boleh Bahasa Indonesia; nama variabel/kolom pakai `snake_case`.
- Jangan menaruh path absolut lokal; pakai path relatif dari root repo.

---

## 11. Tugas untuk Claude Code (urutan eksekusi)

Kerjakan bertahap; berhenti dan tunjukkan hasil tiap tahap sebelum lanjut.

1. **Scaffold repo** sesuai Bagian 6 (buat folder, file kosong, `README.md`, `pyproject.toml`/`requirements.txt`, `.gitignore` yang meng-ignore `data/`).
2. **Buat `config/sources.yaml`** memakai peta dataset di Bagian 4a. Tandai dengan jelas bahwa nilai perlu dikonfirmasi dari header CSV asli.
3. **Tulis `extract.py`**: baca file di `data/raw/`, validasi keberadaannya, beri pesan jelas bila kurang. JANGAN mengakses jaringan.
4. **Tulis `transform.py`**: terapkan aturan Bagian 7 (unpivot, standarisasi, tipe data, grain).
5. **Tulis `build_star.py`**: bangun dim + surrogate key, join fact ke grain, hitung measure turunan.
6. **Tulis `validate.py`** sesuai Bagian 8, dan `run.py` untuk orkestrasi + export CSV (+ DuckDB opsional lewat flag `--duckdb`).
7. **Tulis unit test** untuk minimal: fungsi unpivot, pembuatan surrogate key, dan perhitungan `tingkat_kepatuhan`.
8. **Tulis `docs/data_dictionary.md` dan `docs/katalog_analisis.md`.**
9. Bila `data/raw/` sudah berisi CSV asli, **jalankan `run.py`**, tampilkan ringkasan validasi, dan perbaiki isu yang muncul. Bila `data/raw/` kosong, siapkan semuanya agar tinggal dijalankan, dan cetak instruksi file apa yang harus ditaruh.

**Prinsip:** kalau ada asumsi yang harus diambil (nama kolom, mapping ejaan), pilih default yang
masuk akal, JALANKAN, lalu catat asumsinya di `data_dictionary.md` — jangan berhenti menunggu
konfirmasi untuk hal-hal kecil.
