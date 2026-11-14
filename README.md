# ETL Star Schema — Kepatuhan Pajak Kendaraan Bermotor Jawa Barat

Bagian **ETL** dari proyek Business Intelligence (studi kasus Bapenda Provinsi Jawa Barat,
tema kepatuhan daftar ulang pajak kendaraan bermotor & estimasi potensi kehilangan
pendapatan daerah).

Repo ini mengubah CSV agregat mentah dari Open Data Jabar menjadi **star schema bersih**
(`dim_*` + `fakta_*`) di `data/processed/`, siap dipakai anggota kelompok lain untuk
membangun dashboard.

> **Output repo ini bukan dashboard.** Output-nya: data siap-model + kamus data + katalog
> analisis. Pembuatan visualisasi dikerjakan terpisah.

---

## 1. Ringkas cepat

```powershell
pipenv install --dev              # siapkan environment (Python 3.12)
pipenv run python -m etl.run             # jalankan ETL + validasi + ekspor CSV
pipenv run pytest -q                     # jalankan unit test
```

4 CSV wajib sudah ada di `data/raw/` (diambil dari API publik Satu Data Jabar — lihat
Bagian 3 untuk detail sumber & cara memperbarui).

---

## 2. Setup environment (pipenv)

```powershell
pipenv install --dev
```

Perintah di atas membuat virtualenv Python 3.12 dan memasang `pandas`, `pyyaml`, `pytest`.

Ekspor DuckDB bersifat opsional — pasang hanya bila dibutuhkan:

```powershell
pipenv install --categories duckdb
pipenv run python -m etl.run --duckdb
```

Shortcut yang tersedia di `Pipfile` → `[scripts]`:

| Perintah | Arti |
|---|---|
| `pipenv run etl` | jalankan ETL |
| `pipenv run etl-duckdb` | jalankan ETL + tulis `star.duckdb` |
| `pipenv run test` | jalankan unit test |

---

## 3. Menyiapkan data mentah

Brief awal proyek ini mengasumsikan extract harus manual lewat browser karena portal
`opendata.jabarprov.go.id` (situs katalog lama) berada di belakang Cloudflare dan
menolak request otomatis (403/CF Challenge) — itu benar dan sudah dikonfirmasi lagi.
**Tapi** Bapenda/Diskominfo Jabar ternyata juga mempublikasikan dataset yang sama lewat
**API resmi "Satu Data Jabar / Galura"** (`galura.jabarprov.go.id`), yang publik, **tanpa
token**, dan tidak diblokir — API ini dirancang untuk diakses terprogram (endpoint
`?download=csv` disediakan khusus untuk itu). Keempat CSV wajib di repo ini sudah
diambil dari sana dan siap dipakai; **kamu tidak perlu mengunduh ulang.**

> **ETL (`etl/`) sendiri tetap tidak punya kode jaringan sama sekali** — prinsip
> "extract terpisah dari transform, ETL hanya baca `data/raw/`" tetap dipegang. Yang
> berubah hanya *cara* file itu sampai ke `data/raw/`, bukan bagaimana ETL memakainya.

### File yang sudah ada di `data/raw/`

| Nama file | Dataset (Bapenda, organisasi `bapenda` di Galura) | Baris |
|---|---|---|
| `kendaraan_total.csv` | Jumlah Kendaraan Berdasarkan Jenis Kendaraan, Fungsi Kendaraan, dan Cabang Pelayanan di Jawa Barat | 6.630 |
| `tidak_daftar_ulang.csv` | Jumlah Kendaraan yang Tidak Daftar Ulang Berdasarkan Jenis, Fungsi, dan Cabang Pelayanan | 6.630 |
| `belum_daftar_ulang.csv` | Jumlah Kendaraan yang Belum Daftar Ulang Berdasarkan Jenis, Fungsi, dan Cabang Pelayanan | 6.630 |
| `pajak_denda.csv` | Jumlah Pajak dan Denda Kendaraan Bermotor Berdasarkan Jenis Pajak Kendaraan Bermotor (PKB) | 884 |

Cakupan tahun aktual: **2013–2025** (lebih panjang dari dugaan awal brief 2013–2023;
`config/sources.yaml` → `meta` sudah disesuaikan).

### Cara mengambil ulang / memperbarui data (kalau perlu)

Dataset Bapenda diakses lewat pola URL:

```
https://galura.jabarprov.go.id/api/bigdata/bapenda/<nama_tabel>?download=csv
```

`<nama_tabel>` untuk tiap dataset (dicari lewat `GET /api/datasets?where={"organisasi_id":1005}`,
1005 = id organisasi Bapenda Provinsi; lihat juga `GET /api/organisasi?q=bapenda`):

| Alias | `table` |
|---|---|
| `kendaraan_total` | `od_15829_jml_kndrn_brdsrkn_jenis_kndrn_fungsi_kndrn_cabang__v1` |
| `tidak_daftar_ulang` | `od_15832_jml_kndrn_tidak_daftar_ulang_brdsrkn_jenis_kndrn_f_v1` |
| `belum_daftar_ulang` | `od_15831_jml_kndrn_belum_daftar_ulang_brdsrkn_jenis_kndrn_f_v1` |
| `pajak_denda` | `od_15833_jml_pajak_denda_kndrn_brmtr_brdsrkn_jenis_pajak_kn_v1` |

Contoh (PowerShell): `curl.exe -o data/raw/kendaraan_total.csv "https://galura.jabarprov.go.id/api/bigdata/bapenda/od_15829_jml_kndrn_brdsrkn_jenis_kndrn_fungsi_kndrn_cabang__v1?download=csv"`

Dataset **opsional** (belum dipakai MVP, sudah terdaftar di `config/sources.yaml` →
`sumber_opsional`, dan sudah punya slug/tabel yang sama di API Galura organisasi
`bapenda`): `target_pajak.csv`, `realisasi_pajak.csv`, `bbnkb.csv`, `esamsat.csv`,
`kendaraan_cabang.csv`.

Kalau `data/raw/` sampai kosong (mis. clone ulang repo, ingat `data/` di-gitignore),
`run.py` berhenti dengan pesan yang menyebut file mana yang kurang, dan keluar dengan
**kode 2**. Jalur fallback manual (unduh via browser di `opendata.jabarprov.go.id` /
`bapenda.jabarprov.go.id/open-data-jabar/`) tetap berlaku bila API Galura suatu saat
berubah/down.

`data/` masuk `.gitignore` — CSV mentah maupun hasil olahan tidak ikut di-commit.

---

## 4. Menyesuaikan header CSV yang berbeda

Nama kolom antar dataset/versi bisa sedikit berbeda. Karena itu pemetaan kolom ada di
**`config/sources.yaml`**, bukan di kode.

```powershell
pipenv run python -m etl.run --inspect
```

Perintah itu mencetak, untuk tiap file: header asli, hasil pemetaan ke kolom baku, dan
kolom yang belum dikenali. Bila ada kolom penting yang belum dikenali, tambahkan namanya
di `alias_kolom` (atau `rename` pada sumber terkait) — **tanpa menyentuh Python**.

Hal lain yang diatur dari YAML:

| Blok | Fungsi |
|---|---|
| `meta.tahun_min` / `tahun_max` | rentang tahun yang diharapkan (menyimpang → warning) |
| `alias_kolom` | nama kolom sumber → kolom baku |
| `normalisasi_teks` | penyamaan ejaan nilai dimensi (`"SEPEDA MOTOR"` → `Sepeda Motor`) |
| `sumber.*.bentuk` | `long` / `wide` / `auto` (deteksi otomatis; `wide` akan di-unpivot) |
| `monetisasi` | pola komponen pajak vs denda untuk `rata_pajak_per_kendaraan` |

---

## 5. Menjalankan ETL

```powershell
pipenv run python -m etl.run
```

Tahapan yang dijalankan: **extract → transform → build → validate → export**.

Opsi CLI:

| Flag | Arti |
|---|---|
| `--duckdb` | tulis juga `data/processed/star.duckdb` (butuh paket `duckdb`) |
| `--inspect` | hanya cetak header CSV mentah + pemetaan kolom, lalu berhenti |
| `--config PATH` | pakai file konfigurasi lain |
| `--out-dir PATH` | folder output selain `data/processed` |
| `--quiet` | cetak ringkasan validasi saja |

Kode keluar (exit code): `0` lolos · `1` ada temuan validasi FATAL (output **tidak**
ditulis) · `2` file mentah kurang / konfigurasi tidak valid.

Menjalankan dua kali menghasilkan file yang **identik byte-per-byte** (idempoten).

---

## 6. Output

| File | Isi |
|---|---|
| `data/processed/dim_waktu.csv` | 1 baris per tahun |
| `data/processed/dim_wilayah.csv` | 1 baris per cabang pelayanan (kab/kota = atribut opsional) |
| `data/processed/dim_jenis_kendaraan.csv` | 1 baris per jenis kendaraan |
| `data/processed/dim_fungsi_kendaraan.csv` | 1 baris per fungsi kendaraan |
| `data/processed/fakta_kepatuhan_kendaraan.csv` | fact utama, grain tahun × cabang × jenis × fungsi |
| `data/processed/bantu_rata_pajak_tahunan.csv` | bahan perhitungan monetisasi per tahun |
| `data/processed/laporan_validasi.txt` | salinan ringkasan validasi terakhir |
| `data/processed/star.duckdb` | opsional, semua tabel di atas dalam satu database |

Dokumentasi untuk tim dashboard:

- **[docs/data_dictionary.md](docs/data_dictionary.md)** — grain, tiap kolom, satuan,
  aturan agregasi, dan **asumsi monetisasi lengkap dengan rumus**.
- **[docs/katalog_analisis.md](docs/katalog_analisis.md)** — 10 pertanyaan analisis yang
  bisa dijawab (measure + dimensi + contoh SQL), plus daftar pertanyaan yang **tidak** bisa.

> Peringatan penting bagi pembuat dashboard: `tingkat_kepatuhan` adalah rasio —
> **jangan dirata-rata**. Hitung ulang `SUM(jumlah_daftar_ulang) / SUM(jumlah_kendaraan_total)`
> di setiap level agregasi.

---

## 7. Validasi kualitas data

Dicek otomatis tiap kali ETL berjalan:

**FATAL** (menggagalkan ETL, output tidak ditulis)
- setiap FK fact punya pasangan di dim & tidak null (no orphan);
- `tingkat_kepatuhan` ∈ [0, 1] atau null;
- tidak ada baris fact duplikat pada grain;
- tidak ada dimensi kosong.

**WARNING** (dicatat, ETL lanjut)
- rentang tahun menyimpang dari `meta.tahun_min`/`tahun_max`;
- jumlah baris per tabel, jumlah null per measure;
- jumlah baris yang di-*floor* ke 0 pada `jumlah_daftar_ulang`;
- nilai dimensi yang belum dipetakan di `normalisasi_teks`.

---

## 8. Struktur repo

```
.
├── config/sources.yaml     # peta nama file -> kolom sumber -> kolom baku
├── data/
│   ├── raw/                # CSV mentah (diisi MANUAL, di-gitignore)
│   └── processed/          # OUTPUT: dim_*.csv, fakta_*.csv, star.duckdb
├── docs/
│   ├── data_dictionary.md  # grain, kolom, satuan, asumsi monetisasi
│   └── katalog_analisis.md # pertanyaan analisis + measure/dim yang dipakai
├── etl/
│   ├── extract.py          # baca raw csv, validasi keberadaan file (tanpa jaringan)
│   ├── transform.py        # bersihkan, unpivot, samakan grain, standarisasi
│   ├── build_star.py       # surrogate key, dim, fact, measure turunan
│   ├── validate.py         # pemeriksaan kualitas data
│   └── run.py              # orkestrasi + CLI
├── tests/
│   ├── test_transform.py   # unit test fungsi transform/build kritis
│   └── test_pipeline.py    # smoke test end-to-end atas data sintetis
├── Pipfile / Pipfile.lock  # dependensi (pipenv)
└── BRIEF-ETL-bapenda-jabar.md
```

---

## 9. Testing

```powershell
pipenv run pytest -q
```

Cakupan: unpivot wide→long, pembuatan & kestabilan surrogate key, perhitungan
`tingkat_kepatuhan` (termasuk floor negatif & penyebut nol), parsing angka gaya Indonesia,
normalisasi ejaan, agregasi grain, serta smoke test pipeline penuh yang memakai CSV
sintetis di folder sementara — jadi test tetap jalan walau `data/raw/` masih kosong.
