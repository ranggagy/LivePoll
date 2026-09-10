# Changelog

Catatan perubahan fitur, supaya pengembangan bisa dilanjutkan kapan saja tanpa
kehilangan konteks. **Setiap ada perubahan baru, tambahkan entri di paling
atas** (di bawah judul ini), format: tanggal, ringkasan, file yang tersentuh,
dan hal yang masih perlu diperhatikan (kalau ada).

Untuk dokumentasi arsitektur/setup lengkap, lihat [README.md](README.md).

---

## Belum di-commit

_(kosong — semua perubahan terakhir sudah di-commit & push)_

## 2026-09-10 — Fireworks di podium + gambar pada pertanyaan

- **Fireworks saat podium** — animasi kembang api (canvas, ~3.6 detik) main
  otomatis sekali saat layar "Kuis Telah Berakhir!" muncul (presenter & HP).
  `mainkanKembangApi()` di [static/js/common.js](static/js/common.js).
- **Gambar di pertanyaan** — form Tambah/Ubah Pertanyaan di Kelola Sesi punya
  tombol "Pilih Gambar" (maks 2MB). Disimpan sebagai **data URI base64
  langsung di kolom `gambar` (TEXT) tabel `questions`** — sengaja bukan file
  di disk, supaya tidak hilang saat Render redeploy (filesystem Render
  ephemeral). Kalau soal punya gambar: layout gambar di kiri, teks pertanyaan
  di kanan (presenter & HP, class `.pertanyaan-baris`).
  - **Migrasi manual**: `create_all` SQLAlchemy tidak mengubah tabel yang
    sudah ada, jadi kolom `gambar` ditambahkan lewat `ALTER TABLE ... ADD
    COLUMN` manual di `siapkan_skema()` ([app/database.py](app/database.py)) —
    jalan otomatis tiap start, aman dipanggil berkali-kali (cek dulu via
    `PRAGMA table_info` untuk SQLite, `IF NOT EXISTS` untuk Postgres/Neon).
    **Pola ini harus diulang tiap kali menambah kolom baru ke tabel yang
    sudah pernah di-deploy** — jangan andalkan `create_all` saja.

---

## 2026-09-10 — Perbaiki alur akhir kuis dan tampilan lobi presenter

Commit: `60e7aa9`

- Klik "Soal Berikutnya" di soal terakhir langsung memanggil `/akhiri` sendiri
  (bukan cuma toast "sudah di pertanyaan terakhir") — presenter langsung lihat
  podium tanpa langkah manual tambahan.
- Copy layar akhir Quiz Mode diperbagus: "🎉 Kuis Telah Berakhir!" + "Selamat
  kepada para pemenang!" (presenter & HP). Survey Mode tetap "Terima kasih
  untuk survey!".
- QR code di lobi presenter bisa diklik untuk zoom (overlay penuh layar, tutup
  dengan klik lagi / Esc) — `bukaZoomQr()` di [present.js](static/js/present.js).
- Nama peserta yang join dipindah dari bawah QR ke card "Peserta Bergabung" di
  kolom kanan (`#kartu-peserta-lobi` di [present.html](templates/present.html)),
  otomatis tersembunyi begitu soal pertama dibuka.

## 2026-09-10 — Tambah pengalaman Quiz Mode: lobi live, leaderboard, kelola sesi

Commit: `e724191`

- **Lobi presenter**: bubble nama peserta yang join real-time (broadcast
  `peserta_gabung` dari `POST /api/gabung/{kode}` ke role presenter).
- **Leaderboard presenter**: disembunyikan total selama soal berjalan. Setelah
  soal ditutup, grafik jawaban benar/salah tampil dulu, lalu tombol "Lihat
  Leaderboard →" membuka panel penuh (bukan sidebar kecil) dengan animasi FLIP
  saat posisi berubah.
- **Posisi di HP peserta**: setelah soal ditutup, tampilkan peringkat sendiri
  + 1 di atas + 1 di bawah (bukan top-5 umum) — `sekitar_partisipan()` di
  [runtime.py](app/realtime/runtime.py).
- **Podium sesi selesai** (Quiz Mode, presenter & HP): peringkat 1-3 podium +
  tabel ringkas 4 dst, **maksimal 10 nama total**, dipersonalisasi per peserta
  — kalau peringkatnya di luar 10 besar, tabel otomatis geser supaya berakhir
  2 peringkat di bawah posisinya (`bangun_podium()` di
  [runtime.py](app/realtime/runtime.py), dipakai ulang di
  [ws.py](app/routers/ws.py) untuk kasus reconnect setelah sesi berakhir).
  Baris/kolom milik sendiri di-highlight. Survey Mode cukup pesan terima kasih.
- Export Excel dihapus dari layar presenter (tetap ada di Kelola Sesi).
- **Kelola Sesi**: tombol **Reset Sesi** (hapus jawaban/skor/partisipan, soal
  balik draft, kode sesi bisa dipakai ulang) dan **Hapus Sesi** (permanen,
  endpoint `DELETE /api/admin/sesi/{kode}` ternyata sudah ada sebelumnya,
  tinggal disambungkan ke UI).
- `/play/{kode}` tidak lagi langsung menampilkan halaman statis "sesi
  berakhir" kalau sesi sudah selesai — tetap render `play.html` supaya
  peserta yang reconnect dapat podium personalisasi lewat WebSocket, bukan
  cuma pesan generik ([pages.py](app/routers/pages.py)).

## 2026-09-10 — Fix crash saat connect ke Neon pooler

Commit: `8dfe97e`

`prepared_statement_cache_size` bukan argumen valid untuk `create_engine()`
SQLAlchemy — bikin app crash saat startup begitu `DATABASE_URL` memakai host
`-pooler` Neon. `statement_cache_size` di `connect_args` saja sudah cukup.
File: [app/config.py](app/config.py).

## 2026-09-10 — Siapkan deploy Render + Neon Postgres

Commit: `63f4f05`. Deploy pertama ke Render (Blueprint) + Neon Postgres
sebagai database. Lihat README.md bagian deploy untuk detail.

---

## Catatan arsitektur yang relevan untuk lanjutan

- **State live** disimpan di memory (`RuntimeSesi` per kode sesi,
  [app/realtime/runtime.py](app/realtime/runtime.py)) dan dibangun ulang dari
  DB kalau instance restart — lihat `manajer.py`.
- **Satu worker saja** (`uvicorn --workers 1`, lihat [render.yaml](render.yaml))
  — jangan diubah tanpa refactor state management, karena WebSocket &
  agregasi jawaban ada di memory per-instance.
- Tidak ada Alembic/migrasi otomatis — skema tabel dibuat via
  `Base.metadata.create_all` + migrasi manual kecil di `siapkan_skema()` untuk
  kolom yang ditambahkan belakangan (lihat pola `gambar` di atas).
- Gambar pertanyaan disimpan sebagai base64 di DB, bukan file — pertimbangkan
  ini kalau nanti mau menambah banyak gambar besar (ukuran DB/row akan
  membengkak; belum ada kompresi/resize di sisi server).
