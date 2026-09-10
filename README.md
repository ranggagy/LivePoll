# Live Polling

Aplikasi polling interaktif self-hosted — alternatif Mentimeter tanpa batas jumlah partisipan.
Presenter membuka pertanyaan satu per satu, partisipan menjawab lewat HP tanpa akun, hasil muncul
live di layar presenter.

Dibangun dengan FastAPI async + WebSocket + PostgreSQL, dirancang untuk 100–300 partisipan
serentak dalam satu instance.

---

## Fitur

**Dua mode sesi**

| Mode | Isi |
|---|---|
| **Survey Mode** | Multiple Choice, Word Cloud, Rating Scale. Partisipan anonim, tanpa skor, tanpa timer — presenter yang menutup soal. |
| **Quiz Mode** | Multiple Choice dengan satu jawaban benar. Wajib nickname unik, timer per soal dihitung di server, skor berbasis kecepatan, leaderboard live. |

**Yang sudah jalan**

- **Banyak event sekaligus** — tiap sesi punya kode, timer, dan grup koneksi sendiri;
  beberapa acara boleh berjalan bersamaan di satu instance
- Buat sesi → kode 6 karakter + QR code otomatis
- Kelola pertanyaan: tambah, ubah, hapus, ubah urutan
- Kontrol presenter: aktifkan soal, **Tutup Soal Sekarang**, soal berikutnya, akhiri sesi
- **Hasil ditahan dulu** — Survey Mode membuka grafik setelah separuh partisipan menjawab;
  Quiz Mode menahannya sampai soal ditutup dan hanya menampilkan pilihan jawaban
  (lihat bagian di bawah)
- Moderasi Word Cloud: approve/tolak satu per satu atau **Approve Semua**
- Normalisasi Word Cloud — "Semangat", "semangat " dan "SEMANGAT" digabung jadi satu entri
- Jawaban terkunci sekali klik, tidak bisa diubah
- Refresh HP / WiFi putus tidak menghilangkan progres (token di `localStorage` + auto-reconnect)
- Halaman "Sesi telah berakhir" yang jelas, bukan error kosong
- Export Excel: ringkasan, rekap per pertanyaan, jawaban mentah, leaderboard final
- Pintasan keyboard presenter: `Spasi` = soal berikutnya, `X` = tutup soal, tombol Layar Penuh

---

## Tahapan tampilan hasil di layar presenter

Grafik tidak langsung muncul begitu soal dibuka. Alasannya sama untuk kedua mode:
kalau layar sudah memperlihatkan pilihan mana yang unggul, peserta yang belum menjawab
tinggal ikut suara terbanyak — dan hasilnya jadi bias. Cara menahannya berbeda per mode.

### Survey Mode — terbuka setelah separuh menjawab

1. **Pertanyaan saja.** Teks pertanyaan besar, penghitung `x / y partisipan`, dan bar
   progres menuju ambang. Belum ada grafik.
2. **Hasil terbuka** begitu jawaban mencapai **setengah partisipan yang sedang online**
   (20 online → terbuka di jawaban ke-10). Bar tumbuh dari nol dengan animasi.
3. **Terus ter-update live** setiap jawaban baru masuk, sampai soal ditutup.

| Situasi | Yang terjadi |
|---|---|
| Presenter mau lebih cepat | Tombol **Tampilkan Hasil Sekarang** di bawah bar progres |
| Soal ditutup | Hasil selalu terbuka penuh, tanpa peduli ambang |
| Partisipan sempat putus koneksi | Angka acuan memakai **jumlah online tertinggi** selama soal berjalan, jadi ambang tidak ikut turun |
| Word Cloud | Terbuka begitu presenter menyetujui kata pertama — approve sudah tindakan sadar presenter, tidak perlu digerbang dua kali |
| Soal diaktifkan ulang | Jawaban lama dibuang dan gerbang hasil tertutup lagi dari awal |

Ambangnya ada di `AMBANG_TAMPIL` pada `static/js/present.js` (default `0.5`). Ganti ke `0.3`
kalau mau lebih cepat terbuka, atau `1` kalau hasil hanya boleh muncul setelah semua menjawab.

### Quiz Mode — tertutup rapat sampai soal ditutup

Di kuis kompetitif, memperlihatkan distribusi selagi timer jalan sama saja dengan
membocorkan jawaban. Jadi selama soal berjalan layar hanya menampilkan:

- teks pertanyaan,
- **empat kotak pilihan jawaban berwarna** (warnanya sama persis dengan tombol di HP
  partisipan, jadi audiens bisa membaca opsi dari proyektor),
- cincin timer, dan penghitung `x dari y sudah menjawab` — **tanpa angka per pilihan**.

Distribusi, penanda jawaban benar, dan leaderboard baru muncul saat soal ditutup — baik
karena timer server habis maupun karena presenter menekan **Tutup Soal Sekarang**.

---

## Menjalankan di komputer sendiri

Butuh Python 3.11+ (diuji di 3.13). Tanpa setup database — otomatis pakai SQLite lokal.

**Windows** — klik dua kali `jalankan.bat`, atau:

```bash
jalankan.bat
```

**macOS / Linux:**

```bash
./jalankan.sh
```

Lalu buka:

| Halaman | URL |
|---|---|
| Admin (buat & kelola sesi) | http://localhost:8000/admin |
| Layar presenter | http://localhost:8000/present/KODE |
| Partisipan | http://localhost:8000 |

Partisipan di jaringan yang sama bisa membuka lewat IP komputer kamu, misal
`http://192.168.1.10:8000` — QR code di layar presenter sudah otomatis memakai alamat yang benar.

---

## Deploy ke Render + Neon

Susunannya: **aplikasi di Render** (free web service) dan **database di Neon**
(Postgres free tier). Neon dipilih karena free tier-nya tidak kedaluwarsa,
sedangkan Postgres free di Render dihapus setelah masa gratisnya habis.

Total sekitar 15 menit.

### Langkah 1 — Buat database di Neon

1. Daftar di [neon.tech](https://neon.tech) (bisa login dengan akun GitHub).
2. **Create project**. Isi:
   - Project name: `live-polling`
   - Postgres version: bebas (default terbaru)
   - Region: **Asia Pacific (Singapore)** — samakan dengan region Render supaya latensinya rendah
3. Setelah project jadi, Neon menampilkan **Connection string**. Pastikan pilihannya:
   - Connection type: **Pooled connection**
   - Format: **Parameters / URI** (yang berbentuk `postgresql://...`)
4. Salin string-nya. Bentuknya kira-kira:

   ```
   postgresql://livepolling_owner:xxxxx@ep-nama-1234-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

   Simpan dulu — string ini berisi password, jangan di-commit ke repo.

> **Kenapa "Pooled"?** Neon menyediakan dua host: langsung dan `-pooler` (PgBouncer).
> Keduanya didukung aplikasi ini. Kalau host mengandung `-pooler`, aplikasi otomatis
> mematikan cache prepared statement asyncpg — tanpa itu akan muncul galat
> `prepared statement "__asyncpg_stmt_x__" already exists` saat beban naik.
> Penanganannya ada di `app/config.py`, jadi tidak ada yang perlu kamu atur manual.

### Langkah 2 — Push kode ke GitHub

Repo lokal sudah diinisialisasi dan di-commit. Buat repo kosong di GitHub
(**tanpa** README/gitignore), lalu:

```bash
git remote add origin https://github.com/USERNAME/live-polling.git
git push -u origin main
```

Ganti `USERNAME` dan nama repo sesuai punyamu.

### Langkah 3 — Deploy di Render

1. Daftar/login di [render.com](https://render.com), sambungkan akun GitHub.
2. **New → Blueprint**, pilih repo `live-polling`.
3. Render membaca `render.yaml` dan menampilkan satu web service bernama
   `live-polling`, lalu meminta nilai untuk **`DATABASE_URL`**.
4. Tempel connection string Neon dari Langkah 1 ke situ.
5. **Apply**. Build berjalan ±3–5 menit.

Tabel dibuat otomatis saat aplikasi pertama kali start — tidak perlu migrasi manual.

Kalau lebih suka tanpa Blueprint: **New → Web Service**, pilih repo, lalu isi
Build Command `pip install -r requirements.txt`, Start Command
`uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`,
Health Check Path `/healthz`, dan tambahkan env var `DATABASE_URL` serta
`PYTHON_VERSION=3.13.1`.

### Langkah 4 — Uji sebelum dipakai acara

Setelah deploy selesai, jalankan uji end-to-end langsung ke server sungguhan:

```bash
.venv/Scripts/python.exe tools/uji_alur.py https://live-polling-xxxx.onrender.com
```

Ini menguji ketiga tipe pertanyaan, moderasi, keunikan nickname, timer server,
skor kecepatan, reconnect, export Excel, plus 150 partisipan menjawab bersamaan
— semuanya terhadap Postgres Neon, bukan SQLite. **Jalankan ini sekali sebelum
hari-H**; kalau semua lulus, jalur Postgres sudah terbukti.

Lalu isi event contoh:

```bash
.venv/Scripts/python.exe tools/contoh_event.py https://live-polling-xxxx.onrender.com
```

### Yang wajib diperhatikan

**Harus satu worker.** Daftar koneksi WebSocket dan agregasi jawaban hidup di
memory instance. Kalau `--workers` dinaikkan, partisipan yang mendarat di worker
berbeda tidak akan melihat soal yang sama. Untuk skala lebih dari satu instance
perlu Redis pub/sub — belum ada di versi ini.

**Render free tier tidur setelah ±15 menit tanpa traffic**, bangun lagi ±50 detik.
**Neon free tier juga scale-to-zero** setelah beberapa menit idle, tapi bangunnya
cepat (di bawah 1 detik) dan `pool_pre_ping` sudah menangani koneksi yang terputus.
Dua cara mengatasi tidurnya Render:

- *Paling aman:* buka `/admin` **5–10 menit sebelum acara**.
- *Keep-alive otomatis:* daftarkan `https://<app>.onrender.com/healthz` di uptime
  monitor gratis (UptimeRobot, Better Stack, cron-job.org), interval 10 menit.

**Batas free tier Neon** adalah 0,5 GB storage dan kuota compute bulanan. Untuk
polling teks segini, ribuan sesi pun masih jauh di bawah batas.

**Jangan commit connection string.** `.env` sudah masuk `.gitignore`; di Render
simpan sebagai environment variable, bukan di dalam kode.

**Ganti password Neon** lewat dashboard Neon (Roles → Reset password) kalau
string-nya pernah bocor, lalu perbarui `DATABASE_URL` di Render.

### Deploy ke platform lain

`Procfile` sudah tersedia, jadi Railway/Fly.io/Heroku juga bisa. Syaratnya sama:
satu proses, satu worker, dan `DATABASE_URL` mengarah ke Postgres. URL bergaya
`postgres://...?sslmode=require` otomatis dirapikan jadi bentuk `asyncpg` oleh
`app/config.py`.

## Alur pakai saat acara

1. `/admin` → **+ Sesi Baru** → pilih Survey atau Quiz Mode → **Buat Sesi**
2. Tambahkan pertanyaan. Di Quiz Mode, tandai jawaban benar dengan tombol **✓** dan atur durasi timer.
3. Buka **Layar Presenter**, tampilkan di proyektor. QR + kode sesi muncul besar di layar.
4. Audiens scan QR atau buka halaman depan lalu masukkan kode.
5. **Soal Berikutnya** untuk mulai. Hasil masuk live.
   - Word Cloud: approve jawaban di panel kanan sebelum tampil di layar.
   - Quiz: timer jalan otomatis, atau tekan **Tutup Soal Sekarang** kalau semua sudah menjawab.
6. Selesai → **Export Excel**, lalu **Akhiri Sesi** di halaman kelola.

---

## Event contoh siap pakai

Untuk demo atau latihan sebelum acara, ada skrip yang membuat dua event sekaligus:

```bash
.venv/Scripts/python.exe tools/contoh_event.py
```

| Event | Mode | Isi |
|---|---|---|
| **Town Hall Divisi Keuangan — Q4 2026** | Survey | 5 pertanyaan: Multiple Choice, Word Cloud, Rating (1–5), Multiple Choice, Rating (1–10) |
| **Kuis Literasi Pelaporan Keuangan** | Quiz | 5 soal pilihan ganda bertimer 15–20 detik, masing-masing satu jawaban benar |

Skrip mencetak kode sesi plus tautan kelola/presenter/partisipan untuk keduanya. Keduanya aktif
bersamaan — memang begitu cara aplikasi ini dipakai. Isinya bebas diubah lewat halaman kelola.

Bisa juga diarahkan ke server yang sudah live:

```bash
.venv/Scripts/python.exe tools/contoh_event.py https://nama-app.onrender.com
```

---

## Konfigurasi

Semua opsional — salin `.env.example` jadi `.env` kalau mau mengubah.

| Variabel | Default | Fungsi |
|---|---|---|
| `DATABASE_URL` | kosong → SQLite lokal | Koneksi Postgres. Skema `postgres://`/`postgresql://` otomatis diubah ke `asyncpg`, `sslmode`/`channel_binding` dibuang dan diganti TLS, dan host `-pooler` (PgBouncer Neon) otomatis mematikan cache prepared statement |
| `INTERVAL_BROADCAST` | `0.5` | Jeda throttle broadcast hasil ke presenter (detik) |
| `TOLERANSI_TELAT_MS` | `300` | Toleransi jaringan untuk jawaban yang masuk mepet deadline |
| `POIN_MAKSIMAL` | `1000` | Poin maksimum satu soal quiz |
| `FAKTOR_PENGURANGAN` | `0.5` | Seberapa besar poin berkurang karena lambat menjawab |
| `DURASI_DEFAULT` | `20` | Durasi timer default per soal quiz (detik) |

Rumus skor quiz:
`poin = POIN_MAKSIMAL × (1 − (waktu_jawab / durasi) × FAKTOR_PENGURANGAN)`
Dengan default di atas, jawaban benar bernilai 1000 (instan) sampai 500 (mepet habis waktu);
jawaban salah atau tidak menjawab = 0.

---

## Uji sebelum hari-H

Jalankan server, lalu di terminal lain:

```bash
.venv/Scripts/python.exe tools/uji_alur.py http://127.0.0.1:8010
```

Skrip ini menguji ketiga tipe pertanyaan, moderasi, keunikan nickname, timer server, skor
kecepatan, reconnect, export Excel, plus simulasi **150 partisipan menjawab bersamaan** dan
memastikan broadcast benar-benar ter-throttle. Ganti angka di `uji_beban(150)` untuk menguji
beban lebih besar.

Cek kompatibilitas Postgres (tanpa perlu server Postgres berjalan) — mengompilasi DDL,
indeks parsial, dan statement upsert ke dialek `postgresql+asyncpg`, serta menguji
normalisasi connection string Neon/Render:

```bash
.venv/Scripts/python.exe tools/cek_postgres.py
```

Uji alur sengaja dibuat sebagai skrip mandiri (bukan pytest) supaya bisa dijalankan langsung
terhadap URL Render sesungguhnya sebelum acara:

```bash
.venv/Scripts/python.exe tools/uji_alur.py https://nama-app.onrender.com
```

---

## Struktur project

```
app/
  main.py               entry point FastAPI
  config.py             konfigurasi & normalisasi DATABASE_URL
  database.py           engine SQLAlchemy async
  models.py             tabel: sessions, questions, options, participants, answers
  schemas.py            validasi request
  utils.py              kode sesi, normalisasi nickname & kata
  realtime/
    hub.py              registry koneksi WebSocket per sesi
    runtime.py          agregasi memory, timer server, skor, broadcast throttled
    manajer.py          pemulihan state sesi dari DB setelah restart
  routers/
    pages.py            halaman HTML + QR + /healthz
    api_admin.py        REST admin/presenter
    api_peserta.py      REST partisipan (info sesi, gabung)
    ws.py               endpoint WebSocket
  services/
    export_excel.py     penyusun workbook hasil
templates/              Jinja2
static/css/app.css      design system
static/js/              common.js (soket, animasi), kelola.js, present.js, play.js
tools/uji_alur.py       uji end-to-end + uji beban
tools/cek_postgres.py   cek kompatibilitas Postgres tanpa server
tools/contoh_event.py   pembuat dua event contoh
```

---

## Catatan desain

**Kenapa hasil tidak di-broadcast tiap jawaban masuk.** Kalau 300 orang menjawab dalam 20 detik,
broadcast per-klik berarti 300 pesan ke tiap koneksi. Jawaban diagregasi di memory dulu, lalu
dikirim maksimal dua kali per detik. Di uji beban, 150 jawaban serentak menghasilkan **1 kali
broadcast**, dan semua jawaban di-ack di bawah 100 ms.

**Kenapa hasil tidak langsung ditampilkan.** Lihat bagian "Tahapan tampilan hasil" di atas —
ini soal menjaga jawaban tetap jujur, bukan sekadar efek visual. Quiz Mode digerbang lebih
ketat daripada Survey Mode karena di sana distribusi sama saja dengan bocoran jawaban.

**Kenapa nilai akhir animasi tidak bergantung pada requestAnimationFrame.** rAF berhenti
dipanggil di tab yang tidak digambar (dan `document.hidden` tidak selalu ikut `true`, mis. saat
jendela presenter tertutup jendela lain). Kalau angka dan lebar bar hanya ditulis di dalam rAF,
layar bisa membeku di nilai lama. Karena itu lebar bar ditulis langsung dan penghitung angka
punya jaring pengaman `setTimeout`.

**Kenapa timer dihitung di server.** Countdown di HP hanya tampilan. Server yang menentukan kapan
soal ditutup, jadi partisipan tidak bisa curang dengan mengubah jam perangkat, dan yang
reconnect di tengah soal tidak mendapat waktu tambahan — sisa waktu dihitung ulang dari
`waktu_soal_dibuka + durasi − waktu_server_sekarang`.

**Kenapa satu partisipan = satu perangkat.** `participant_token` di `localStorage` terikat ke
browser tersebut. Ini yang membuat refresh aman, sekaligus mencegah orang lain memakai nickname
peserta yang sudah ada. Pindah perangkat di tengah sesi memang tidak didukung.

**Keunikan nickname** dicek di aplikasi *dan* dijaga unique constraint database pada
`(session_id, nickname_normalized)`, supaya dua orang yang mengirim nickname sama pada saat
nyaris bersamaan tidak sama-sama lolos.

**Halaman admin tidak dipassword** — ini keputusan sadar untuk tool internal. Siapa pun yang tahu
URL `/admin` bisa mengelola sesi, jadi jangan sebarkan URL itu ke partisipan; yang dibagikan
cukup `/join/KODE` atau QR.

---

## Yang belum dikerjakan (Fase 2 di PRD)

Q&A dengan upvote, branding kustom per acara, multi-admin per sesi.
