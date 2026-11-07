# Kamus Data — Star Schema Kepatuhan Pajak Kendaraan Bermotor Jawa Barat

Dokumen ini menjelaskan **isi `data/processed/`**: grain tiap tabel, arti tiap kolom,
satuan, serta seluruh asumsi yang diambil ETL. Ditujukan untuk anggota kelompok yang
membangun dashboard/laporan, jadi tidak perlu membaca kode Python.

- Sumber data: Open Data Jabar / Bapenda Provinsi Jawa Barat (agregat tahunan).
- Dihasilkan oleh: `pipenv run python -m etl.run` (lihat [README](../README.md)).
- Format: CSV UTF-8, pemisah koma, tanpa kolom index. Opsional: `star.duckdb`.

---

## 1. Model dimensional

Fact bertipe **periodic snapshot** (bukan transaksional) karena sumbernya sudah agregat
tahunan, bukan catatan per kendaraan.

```
            dim_waktu                     dim_jenis_kendaraan
                |                                  |
                | waktu_id                         | jenis_kendaraan_id
                v                                  v
    +---------------------------------------------------------+
    |            fakta_kepatuhan_kendaraan                      |
    |  grain: 1 tahun x 1 cabang x 1 jenis x 1 fungsi           |
    +---------------------------------------------------------+
                ^                                  ^
                | wilayah_id                       | fungsi_kendaraan_id
                |                                  |
            dim_wilayah                    dim_fungsi_kendaraan
```

**Grain fact:** satu baris = satu kombinasi
`tahun × cabang_pelayanan × jenis_kendaraan × fungsi_kendaraan`.
Tidak ada baris duplikat pada grain ini (dijamin `etl/validate.py`, cek FATAL).

Semua kolom `*_id` adalah **surrogate key** integer yang dibuat ETL (1..n, berurut
mengikuti nilai natural key yang di-*sort*). Nilainya **stabil antar-run** selama himpunan
nilai dimensinya sama, tetapi **bukan kode resmi** — jangan dipakai sebagai kode wilayah.

---

## 2. `fakta_kepatuhan_kendaraan`

**Grain:** `tahun × cabang_pelayanan × jenis_kendaraan × fungsi_kendaraan`
**Satu baris = potret tahunan satu segmen kendaraan di satu cabang pelayanan Samsat.**

| Kolom | Tipe | Satuan | Deskripsi |
|---|---|---|---|
| `waktu_id` | integer (FK) | — | FK ke `dim_waktu`. Tidak pernah null. |
| `wilayah_id` | integer (FK) | — | FK ke `dim_wilayah` (grain = cabang pelayanan). |
| `jenis_kendaraan_id` | integer (FK) | — | FK ke `dim_jenis_kendaraan`. |
| `fungsi_kendaraan_id` | integer (FK) | — | FK ke `dim_fungsi_kendaraan`. |
| `tahun` | integer | tahun | Didenormalisasi dari dim agar gampang di-filter di tool BI. |
| `cabang_pelayanan` | teks | — | Didenormalisasi dari `dim_wilayah`. |
| `jenis_kendaraan` | teks | — | Didenormalisasi dari `dim_jenis_kendaraan`. |
| `fungsi_kendaraan` | teks | — | Didenormalisasi dari `dim_fungsi_kendaraan`. |
| `jumlah_kendaraan_total` | numerik | unit kendaraan | **Measure dasar.** Total kendaraan terdaftar pada segmen tsb. Penyebut tingkat kepatuhan. Null bila kombinasi grain tidak ada di dataset total. |
| `jumlah_tidak_daftar_ulang` | numerik | unit kendaraan | **Measure dasar.** Kendaraan yang tidak melakukan daftar ulang. |
| `jumlah_belum_daftar_ulang` | numerik | unit kendaraan | **Measure dasar.** Kendaraan yang belum melakukan daftar ulang. |
| `jumlah_daftar_ulang` | numerik | unit kendaraan | **Turunan** = `total − tidak − belum`, di-*floor* ke 0 bila negatif. |
| `tingkat_kepatuhan` | numerik | rasio 0–1 | **Turunan** = `jumlah_daftar_ulang / jumlah_kendaraan_total`. Null bila total 0/null. Kalikan 100 untuk persen. |
| `estimasi_pajak_hilang` | numerik | rupiah (Rp) | **Turunan & berbasis ASUMSI** = `jumlah_tidak_daftar_ulang × rata_pajak_per_kendaraan`. Lihat Bagian 5. |
| `rata_pajak_per_kendaraan` | numerik | rupiah (Rp)/kendaraan | Nilai asumsi per tahun yang dipakai baris ini; disertakan supaya perhitungan transparan dan bisa diaudit. |

### Aturan agregasi untuk dashboard

| Measure | Boleh di-SUM lintas dimensi? | Catatan |
|---|---|---|
| `jumlah_kendaraan_total` | Ya | aditif penuh |
| `jumlah_tidak_daftar_ulang` | Ya | aditif penuh |
| `jumlah_belum_daftar_ulang` | Ya | aditif penuh |
| `jumlah_daftar_ulang` | Ya | aditif penuh |
| `estimasi_pajak_hilang` | Ya | aditif penuh (rupiah) |
| `tingkat_kepatuhan` | **TIDAK** | rasio — **jangan** dirata-rata. Hitung ulang: `SUM(jumlah_daftar_ulang) / SUM(jumlah_kendaraan_total)` |
| `rata_pajak_per_kendaraan` | **TIDAK** | konstanta per tahun, bukan measure aditif |

---

## 3. Tabel dimensi

### `dim_waktu`
**Grain:** 1 baris = 1 tahun.

| Kolom | Tipe | Deskripsi |
|---|---|---|
| `waktu_id` | integer (PK) | Surrogate key. |
| `tahun` | integer | Tahun data (mis. 2013–2023). |
| `dekade` | integer | Turunan, `tahun // 10 * 10` (2010, 2020) — untuk grouping kasar. |
| `label_tahun` | teks | `tahun` sebagai teks, agar tool BI tidak memperlakukannya sebagai angka. |

### `dim_wilayah`
**Grain:** 1 baris = 1 **cabang pelayanan** (unit Samsat), *bukan* kabupaten/kota.

| Kolom | Tipe | Deskripsi |
|---|---|---|
| `wilayah_id` | integer (PK) | Surrogate key. |
| `cabang_pelayanan` | teks | Nama cabang pelayanan Samsat; atribut geografis utama. |
| `kode_kabupaten_kota` | teks | **Opsional, boleh null.** Kode BPS bila tersedia di sumber. |
| `nama_kabupaten_kota` | teks | **Opsional, boleh null.** Nama kab/kota bila tersedia. |
| `nama_provinsi` | teks | Default `Jawa Barat`. |

> **Keputusan grain geografis (dikunci di brief Bagian 7 butir 4).** Dataset daftar ulang
> memakai `cabang_pelayanan`, sedangkan satu cabang bisa mencakup lebih dari satu kab/kota
> (dan sebaliknya). Karena itu fact **tidak** di-join ke kab/kota — join semacam itu akan
> menggandakan baris fact dan melipatgandakan measure. Kolom kab/kota hanya atribut
> deskriptif: pakai untuk label/tooltip, **jangan** untuk agregasi resmi per kabupaten/kota.

### `dim_jenis_kendaraan`
**Grain:** 1 baris = 1 jenis kendaraan.

| Kolom | Tipe | Deskripsi |
|---|---|---|
| `jenis_kendaraan_id` | integer (PK) | Surrogate key. |
| `jenis_kendaraan` | teks | 5 kategori baku: `Sepeda Motor`, `Sedan/Jeep/Minibus/Station Wagon` (2 label sumber digabung, lihat Bagian 4 poin 2), `Bus/Microbus`, `Truck/Pick Up`, `Alat Berat` (lihat catatan kualitas data Bagian 4 poin 3 sebelum memakai segmen ini). |

### `dim_fungsi_kendaraan`
**Grain:** 1 baris = 1 fungsi kendaraan.

| Kolom | Tipe | Deskripsi |
|---|---|---|
| `fungsi_kendaraan_id` | integer (PK) | Surrogate key. |
| `fungsi_kendaraan` | teks | Nilai baku, mis. `Pribadi`, `Umum`, `Dinas`, `TNI/Polri`. Bisa berisi `Tidak Dirinci` (lihat Bagian 6). |

### `bantu_rata_pajak_tahunan` (tabel bantu, bukan bagian star schema)
Menampilkan bahan perhitungan monetisasi agar bisa diperiksa ulang.

| Kolom | Tipe | Deskripsi |
|---|---|---|
| `tahun` | integer | Tahun. |
| `nilai_pajak_rupiah` | numerik | Total nilai komponen **pajak** (bukan denda) tahun tsb dari `pajak_denda.csv`. |
| `kendaraan_terdaftar` | numerik | `SUM(jumlah_kendaraan_total)` tahun tsb. |
| `rata_pajak_per_kendaraan` | numerik | `nilai_pajak_rupiah / kendaraan_terdaftar`. |

---

## 4. Asal data (lineage)

| Tabel/kolom hasil | Berasal dari file mentah | Dataset (organisasi Bapenda, API Satu Data Jabar) | Baris mentah |
|---|---|---|---|
| `jumlah_kendaraan_total` | `data/raw/kendaraan_total.csv` | Jumlah Kendaraan Berdasarkan Jenis, Fungsi, dan Cabang Pelayanan di Jawa Barat | 6.630 |
| `jumlah_tidak_daftar_ulang` | `data/raw/tidak_daftar_ulang.csv` | Jumlah Kendaraan yang Tidak Daftar Ulang … | 6.630 |
| `jumlah_belum_daftar_ulang` | `data/raw/belum_daftar_ulang.csv` | Jumlah Kendaraan yang Belum Daftar Ulang … | 6.630 |
| `rata_pajak_per_kendaraan`, `estimasi_pajak_hilang` | `data/raw/pajak_denda.csv` | Jumlah Pajak dan Denda Kendaraan Bermotor Berdasarkan Jenis Pajak (PKB) | 884 |
| `dim_wilayah.kode/nama_kabupaten_kota` | kolom identitas Satu Data di file manapun yang memuatnya | — | — |

Extract diambil dari **API publik Satu Data Jabar** (`galura.jabarprov.go.id`, endpoint
`/api/bigdata/bapenda/<table>?download=csv`) — bukan lewat scraping situs katalog lama
`opendata.jabarprov.go.id` yang memang diblokir Cloudflare. Detail cara memperbarui ada
di [README](../README.md) Bagian 3. ETL (`etl/`) sendiri tidak pernah mengakses
jaringan — ia hanya membaca file yang sudah ada di `data/raw/`.

**Temuan kualitas sumber yang relevan:**

1. **Spasi di depan nama cabang.** Baris 2013–2018 menulis `cabang_pelayanan` tanpa
   spasi di depan, baris 2019–2025 dengan satu spasi di depan (kemungkinan migrasi
   sistem internal Bapenda). Pembersihan teks (`bersihkan_teks`, aturan Bagian 6 butir 1)
   sudah menyatukan ini secara otomatis menjadi 36 cabang pelayanan yang benar — bukan
   70 seperti yang terlihat di CSV mentah sebelum di-trim.

2. **Penggantian nama kategori "Sedan/Jeep/Minibus" → "Sedan/Jeep/Station Wagon".**
   `kendaraan_total.csv` berhenti memakai label "Sedan, Jeep, Minibus" persis mulai
   tahun 2022 dan menggantinya dengan "Sedan, Jeep, Station Wagon" (skala angka
   setara di tahun transisi), sementara `tidak_daftar_ulang.csv` dan
   `belum_daftar_ulang.csv` tetap memakai label lama di semua tahun. **ASUMSI:** ini
   kategori kendaraan yang sama, hanya berganti nama di sumbernya — digabung jadi satu
   kategori baku `Sedan/Jeep/Minibus/Station Wagon` (lihat `config/sources.yaml` →
   `normalisasi_teks.jenis_kendaraan`) supaya grain tetap bisa disambungkan lintas
   2022–2025. Tanpa penggabungan ini, ~420 baris kehilangan penyebutnya.

3. **Kategori "Alat Berat" tidak konsisten antar dataset (BELUM DIPERBAIKI, hanya
   didokumentasikan).** `kendaraan_total.csv` melaporkan total kendaraan "Alat Berat"
   se-Jawa Barat sangat kecil (30–82 unit per tahun), tapi `tidak_daftar_ulang.csv`
   melaporkan angka "tidak daftar ulang" untuk "Alat Berat" yang jauh lebih besar
   di beberapa cabang (sampai >100.000 pada satu baris) — jelas tidak masuk akal bila
   dianggap subset dari total yang jauh lebih kecil. Kemungkinan definisi "Alat Berat"
   berbeda antar dataset (mis. salah satu memasukkan kategori kendaraan lain).
   **Tidak digabung/dikoreksi** karena — berbeda dari kasus Minibus/Station Wagon —
   tidak ada bukti kuat keduanya merujuk kategori yang sama. Akibatnya 112 baris
   berkategori "Alat Berat" punya `jumlah_kendaraan_total = 0` padahal
   `jumlah_tidak_daftar_ulang > 0`, sehingga `tingkat_kepatuhan`-nya null (sesuai
   aturan Bagian 5: null bila penyebut 0) — **bukan bug, tapi rekomendasi: jangan
   pakai segmen "Alat Berat" untuk klaim tingkat kepatuhan di laporan** tanpa
   verifikasi definisi lebih lanjut ke Bapenda.

---

## 5. Asumsi monetisasi (WAJIB dibaca sebelum memakai `estimasi_pajak_hilang`)

### Rumus

```
rata_pajak_per_kendaraan[t] = nilai_pajak_rupiah[t] / kendaraan_terdaftar[t]

  nilai_pajak_rupiah[t]  = SUM(nilai) dari pajak_denda.csv pada tahun t,
                           HANYA baris yang jenis pajaknya cocok pola
                           `monetisasi.komponen_pajak` (default: "pkb",
                           "pajak kendaraan") DAN tidak mengandung "denda".
  kendaraan_terdaftar[t] = SUM(jumlah_kendaraan_total) seluruh segmen pada tahun t.

estimasi_pajak_hilang[baris] = jumlah_tidak_daftar_ulang[baris]
                               × rata_pajak_per_kendaraan[tahun baris]
```

Perhitungan dilakukan **per tahun**, bukan satu angka untuk semua tahun, agar mengikuti
perubahan tarif/komposisi kendaraan. Semua parameter pola ada di
`config/sources.yaml` → `monetisasi`.

### Asumsi yang melekat

1. **Rata-rata rata (flat average).** Semua kendaraan dianggap punya kewajiban PKB sama
   besar. Kenyataannya PKB proporsional terhadap NJKB: sepeda motor jauh lebih murah
   daripada mobil. Akibatnya estimasi **melebih-lebihkan** kerugian pada segmen sepeda
   motor dan **meremehkan** pada segmen mobil.
2. **Hanya komponen pajak.** Denda dikeluarkan dari pembilang, jadi angka ini adalah
   *pokok pajak yang tidak masuk*, bukan total tagihan termasuk sanksi.
3. **Basis penyebut = kendaraan terdaftar**, bukan kendaraan yang benar-benar membayar.
   Bila banyak kendaraan terdaftar tidak membayar, `rata_pajak_per_kendaraan` menjadi
   lebih rendah dari tarif efektif sebenarnya (estimasi konservatif).
4. **Hanya "tidak daftar ulang" yang dimonetisasi.** `jumlah_belum_daftar_ulang` dianggap
   masih berpotensi membayar dalam tahun berjalan sehingga tidak dihitung sebagai hilang.
   Bila ingin skenario pesimistis, hitung sendiri:
   `(jumlah_tidak_daftar_ulang + jumlah_belum_daftar_ulang) × rata_pajak_per_kendaraan`.
5. **Fallback antar-tahun.** Bila suatu tahun tidak punya data pajak dan
   `monetisasi.fallback_rata_global: true`, dipakai rata-rata seluruh tahun yang tersedia.
   Kejadian ini selalu dicatat sebagai **warning** di ringkasan validasi — periksa log
   sebelum mengutip angkanya di laporan.
6. **Bukan angka resmi.** `estimasi_pajak_hilang` adalah estimasi akademik untuk keperluan
   analisis BI, bukan hitungan potensi kehilangan pendapatan versi Bapenda.

---

## 6. Asumsi & aturan pembersihan lainnya

1. **Standarisasi teks dimensi.** Nilai di-*trim*, spasi ganda dirapikan, lalu Title Case
   (`"SEPEDA MOTOR"` → `"Sepeda Motor"`). Pemetaan ejaan dibaca dari
   `config/sources.yaml` → `normalisasi_teks`. Nilai yang belum ada di peta **tidak
   dibuang**; ia tetap masuk hasil dan dilaporkan di log sebagai "belum dipetakan"
   supaya bisa ditambahkan ke YAML bila ternyata ejaan kembar.
2. **Parsing angka.** Pemisah ribuan gaya Indonesia (`1.234.567`) maupun Inggris
   (`1,234,567`), awalan `Rp`, dan kurung negatif `(1.500)` semuanya ditangani.
   Teks yang tidak bisa diparse menjadi NaN, bukan 0.
3. **Nilai kosong measure.** Kombinasi grain yang tidak muncul di dataset "tidak/belum
   daftar ulang" diisi **0** (konteksnya "tidak ada kejadian"). Sebaliknya
   `jumlah_kendaraan_total` yang hilang **dibiarkan NaN** karena ia penyebut; mengisinya 0
   akan memalsukan `tingkat_kepatuhan`. Jumlah kejadian keduanya dicetak di log.
4. **Baris agregat dibuang.** Baris sumber yang nilai dimensinya `Jumlah`, `Total`,
   `Grand Total`, dsb. dihapus agar tidak dihitung ganda; jumlahnya dilaporkan.
5. **Duplikat pada grain digabung** dengan `SUM` measure (misalnya sumber merinci lebih
   halus dari grain fact). Jumlah baris yang terlipat dilaporkan.
6. **Nilai `Tidak Dirinci`.** Bila sebuah dataset sumber tidak memuat salah satu kolom
   grain (paling sering `fungsi_kendaraan`), kolom itu diisi `"Tidak Dirinci"` supaya
   grain tetap utuh dan join tidak gagal — bukan berarti nilainya nol. `tahun` adalah
   pengecualian: bila tidak ada, ETL berhenti dengan error.
7. **Idempoten.** Menjalankan `run.py` dua kali menghasilkan file identik: surrogate key
   dibangun dari nilai yang di-*sort*, output diurutkan pada grain, dan kolom numerik
   dibulatkan saat ekspor (`tingkat_kepatuhan` 6 desimal, nilai rupiah 2 desimal).

---

## 7. Pemeriksaan kualitas yang dijalankan

| Pemeriksaan | Tingkat | Arti bila gagal |
|---|---|---|
| Semua FK fact punya pasangan di dim & tidak null | **FATAL** | ada baris fact yang tidak bisa di-slice; CSV tidak ditulis |
| `tingkat_kepatuhan` ∈ [0,1] atau null | **FATAL** | rumus/measure dasar bermasalah |
| Tidak ada duplikat pada grain fact | **FATAL** | agregasi dashboard akan dobel |
| Dimensi tidak kosong | **FATAL** | star schema tidak terpakai |
| Rentang tahun sesuai `meta.tahun_min/tahun_max` | Warning | cakupan data beda dari dugaan |
| Jumlah baris per tabel, null per measure, baris yang di-floor | Warning/info | untuk dicatat di laporan |

Bila ada temuan FATAL, `run.py` **tidak menulis** file output dan keluar dengan kode 1.
Ringkasan lengkap juga disimpan di `data/processed/laporan_validasi.txt`.

---

## 8. Batasan data yang perlu ditulis di laporan

- Data **agregat tahunan**, bukan transaksi per kendaraan → tidak bisa menganalisis
  perilaku individu, musim pembayaran, atau keterlambatan harian.
- Grain geografis **cabang pelayanan**, bukan kabupaten/kota → hindari klaim
  "kabupaten X paling tidak patuh" kecuali cabangnya memang satu kab/kota.
- Definisi "tidak daftar ulang" vs "belum daftar ulang" mengikuti definisi Bapenda pada
  metadata dataset; perbedaan tafsir antar tahun (bila ada) tidak dikoreksi ETL.
- `estimasi_pajak_hilang` bergantung penuh pada asumsi Bagian 5 — selalu sertakan
  rumus + keterbatasannya bila angkanya ditampilkan di dashboard.
- Segmen **"Alat Berat"** punya definisi yang tampak tidak konsisten antar dataset
  sumber (Bagian 4 poin 3) — hindari klaim tingkat kepatuhan untuk segmen ini tanpa
  verifikasi lebih lanjut.
