# Changelog

Catatan perubahan fitur, supaya pengembangan bisa dilanjutkan kapan saja tanpa
kehilangan konteks. **Setiap ada perubahan baru, tambahkan entri di paling
atas** (di bawah judul ini), format: tanggal, ringkasan, file yang tersentuh,
dan hal yang masih perlu diperhatikan (kalau ada).

Untuk dokumentasi arsitektur/setup lengkap, lihat [README.md](README.md).

---

## Belum di-commit

_(kosong — semua perubahan terakhir sudah di-commit)_

## 2026-09-11 — Bug asli overflow horizontal di Layar Penuh ketemu & diperbaiki

Perbaikan sebelumnya (`document.fonts.ready`) ternyata cuma menutupi gejala,
bukan akar masalah — user masih melapor opsi/podium kepotong di Layar Penuh,
tapi kali ini jelas terlihat **horizontal** (teks & bar warna meluber ke
kanan lewat tepi layar), bukan soal tinggi.

**Akar masalah sesungguhnya**: [static/css/app.css](static/css/app.css)
kelas `.tampilan` (dipasang tiap kali layar presenter berganti tampilan —
lobi, soal, hasil, leaderboard, podium, lewat `gantiTampilan()` di
[common.js](static/js/common.js)) pakai
`animation: tampilMasuk 340ms ... both`. Fill-mode `both` mengunci properti
yang dianimasikan **selamanya** — dan `tampilMasuk` ikut menganimasikan
`transform: translateY(...)`. Akibatnya elemen yang sama itu juga jadi
target scale-down `sesuaikanUkuranPanggung()` di
[present.js](static/js/present.js): `konten.style.transform = "scale(...)"`
yang di-set lewat JS **selalu ditimpa balik** ke `translateY(0)` oleh
animasi CSS ini (animasi CSS menang atas inline style untuk properti yang
sama), sementara `konten.style.width = "100/skala%"` (properti yang TIDAK
disentuh animasi) tetap terpasang penuh. Hasilnya: konten dibuat jauh lebih
LEBAR untuk kompensasi scale yang seharusnya mengecilkan baliknya — tapi
scale itu sendiri tidak pernah benar-benar terjadi secara visual, jadi
konten meluber ke kanan alih-alih mengecil proporsional.

**Perbaikan**: `tampilMasuk`/`tampilKeluar` di app.css diubah jadi cuma
animasi opacity (fade), transform dihapus dari keyframe-nya. Efek slide
halus yang hilang cuma kosmetik minor; yang penting elemen `.tampilan`
sekarang bebas dipakai `transform` lewat inline style oleh kode lain
(termasuk scale-down Layar Penuh) tanpa direbut balik animasi CSS.

**Cara verifikasi** (Fullscreen API tidak bisa dites di browser pane
sandbox): override `document.fullscreenElement` via
`Object.defineProperty` + paksa viewport pendek (`resize_window` /
DevTools), lalu cek `getComputedStyle(konten).transform` benar-benar
`matrix(0.55,...)` (bukan cuma inline style yang di-set tapi tidak
computed). Sebelum fix: computed transform tetap `translateY(0)` walau
inline style sudah di-set ke scale(). Sesudah fix: computed transform
ikut inline style dengan benar, tidak ada lagi overflow horizontal.

**Pelajaran untuk ke depan**: kalau ada elemen yang PERLU di-manipulasi
`transform`/properti lain lewat JS di masa depan, jangan taruh
`animation:...both/forwards` yang menyentuh properti yang sama pada elemen
itu — fill-mode yang "menempel" selamanya akan selalu menang atas inline
style JS untuk properti tersebut.

## 2026-09-11 — 10 bug dari code review diperbaiki (skor dobel, race condition, tampilan)

Hasil code review menyeluruh (8 sudut pandang: backend, frontend, kontrak
backend↔frontend, tampilan, reuse, simplifikasi, efisiensi, root-cause). Semua
diverifikasi ulang manual + lolos `uji_alur.py`/`uji_edge_case.py`.

**Bug skor/data (paling kritis):**

- **Reaktivasi soal yang sudah dinilai dobel-hitung poin** — klik "Aktifkan"
  pada soal yang sudah pernah selesai (mis. tombolnya memang tidak pernah
  disable untuk soal lama) menghapus jawaban lama tapi tidak pernah membalik
  poin yang sudah ditambahkan ke `poin_total`/`total_poin`, jadi menjawab
  ulang MENUMPUK poin baru di atas yang lama. Sekarang `aktifkan()` di
  [runtime.py](app/realtime/runtime.py) membalikkan dulu poin lama sebelum
  soal dibuka ulang.
- **Jawaban telat (delay jaringan) bisa nyasar ke aktivasi baru** — `StatePertanyaan`
  sekarang punya nomor `generasi` (naik tiap aktivasi, termasuk soal yang
  SAMA), dikirim ke klien dan diminta balik di setiap jawaban
  (`static/js/play.js`). Jawaban yang generasinya tidak cocok lagi ditolak
  ("Soal sudah berganti") alih-alih diam-diam kena skor ke soal yang sudah
  beda aktivasi.
- **Soal yang batal SAAT countdown (diganti sebelum benar-benar terbuka)
  dulu ditandai "selesai"** padahal `dibuka_at` masih kosong — mencemari
  data (tidak ada yang mungkin sempat menjawab). Sekarang dikembalikan ke
  status draft.
- **`ambil_sesi` di [api_admin.py](app/routers/api_admin.py) mengurutkan
  status TERBALIK** — `Sesi.status.desc()` menaruh sesi `"selesai"` sebelum
  `"aktif"` (leksikografis, bukan makna), jadi kalau kode sesi lama yang
  sudah berakhir dipakai ulang oleh sesi baru, `detail_sesi`/`hapus_sesi`/
  `reset_sesi` bisa salah mengenai sesi yang sudah mati. Diganti
  `(Sesi.status == STATUS_SESI_AKTIF).desc()`.
- **Edit soal ("Ubah") yang sedang aktif/sudah dijawab bisa merusak hasil**
  — opsi lama dihapus-lalu-dibuat-ulang dengan id baru, jawaban lama jadi
  menunjuk ke id opsi yang sudah tidak ada (hilang diam-diam dari export).
  Sekarang: (1) tombol "Ubah" di-disable untuk soal yang sedang aktif, sama
  seperti "Hapus"; (2) opsi yang tetap ada di posisi yang sama diperbarui DI
  TEMPAT (bukan hapus-buat-ulang), jadi id-nya tidak berubah untuk edit
  biasa (perbaiki teks/tandai jawaban benar).
- **Approve/reject Word Cloud race dengan pindah soal** — `moderasi()`/
  `moderasi_semua()` baca-tulis `self.aktif` tanpa lock yang sama dipakai
  `aktifkan()`/`tutup()`, jadi presenter yang moderasi nyaris bersamaan
  dengan pindah soal bisa membuat UPDATE database menimpa jawaban milik soal
  yang sudah berbeda. Sekarang dikunci dengan `_gembok` yang sama.
- **Word Cloud dengan `teks` bukan string bikin partisipan itu terputus** —
  `.strip()` dipanggil tanpa cek tipe dulu (beda dari cabang MC/Rating yang
  sudah ada try/except). Sekarang divalidasi dulu.

**Bug tampilan:**

- **Timer & tombol "Tutup Soal" macet kalau presenter buka Leaderboard**
  saat soal masih berjalan — `if (modeTampilan === "leaderboard") return;`
  di [present.js](static/js/present.js) skip kode sinkronisasi timer/tombol
  di bawahnya. Sekarang timer/tombol selalu ikut kondisi soal sebenarnya
  lewat fungsi `sinkronkanKontrolSoal()`, terlepas dari layar mana yang
  sedang ditampilkan.
- **Opsi jawaban ke-5 (Quiz Mode) pakai warna sama dengan "Jawaban Benar"**
  — `.opt-e` pakai `var(--benar)`, warna yang PANDUAN_WARNA.md khususkan
  untuk penanda jawaban benar, jadi bisa menyesatkan peserta SAAT VOTING
  (sebelum jawaban dibuka). Desain warna memang cuma untuk 4 kategori —
  sekarang Quiz Mode dibatasi maksimal 4 pilihan jawaban (validasi di
  server + tombol "+ Tambah Opsi" di kelola.js).
- **Fokus input & highlight baris aktif masih pakai hijau lime dari palet
  lama** (`rgba(198,241,53,...)`, tidak ada lagi di `:root` manapun sejak
  redesign) — diganti `--utama` (Biru Crate), konsisten dengan tombol CTA.
- **Layar "Sesi Berakhir" tampil judul kosong** kalau presenter masih
  terkoneksi live saat sesi diakhiri — broadcast `sesi_selesai` yang live
  tidak pernah menyertakan field `"sesi"` (cuma jalur reconnect yang
  menyertakannya). Sekarang disertakan di semua broadcast.
- **Opsi jawaban/podium bisa terpotong tanpa scroll di Layar Penuh** — Google
  Font (`display=swap`) kadang baru selesai dimuat SETELAH
  `sesuaikanUkuranPanggung()` pertama kali mengukur tinggi konten; teks
  membesar/reflow tapi `overflowY` sudah kadung dikunci "hidden" dari
  pengukuran lama, jadi kelebihan tinggi diam-diam hilang (bukan discale
  ulang). Diperbaiki dengan mengukur ulang begitu `document.fonts.ready`.
  Podium+tabel peringkat 4-10 (layar "Kuis Telah Berakhir") juga disusun
  dua kolom (podium kiri, tabel kanan) khusus di Layar Penuh
  (`:fullscreen #podium-wadah`), supaya lebar layar dipakai alih-alih
  tinggi — jauh lebih mungkin muat tanpa perlu di-scale-turun.

## 2026-09-11 — Simulasi acara nyata 300 peserta / 5 soal lolos di Render

Skrip baru [tools/uji_simulasi_acara.py](tools/uji_simulasi_acara.py): satu
alur utuh dari lobi sampai podium (bukan skenario terpisah-pisah), 300
peserta quiz menjawab 5 soal, dengan berbagai trouble device TERCAMPUR di
dalamnya — reconnect saat countdown, putus-lalu-sambung mid-soal, jawaban
dobel, telat menjawab lewat batas waktu, keluar permanen di tengah acara,
15 peserta baru gabung berangsur di tengah acara, presenter refresh browser
dan klik dobel aktifkan soal. Dijalankan ke `live-polling-tz7j.onrender.com`:

```bash
.venv/Scripts/python.exe tools/uji_simulasi_acara.py https://nama-app.onrender.com 300
```

**Hasil: SEMUA LULUS**, selesai 4m10s. ~285-288 dari 303 peserta menjawab tiap
soal, broadcast tetap ter-throttle di skala ini, leaderboard & podium akhir
konsisten, tiap trouble device berperilaku persis sesuai aturan server
(ditolak/diterima). Aplikasi sendiri tidak menunjukkan bug di uji ini.

**3 bug ditemukan & diperbaiki, tapi di SKRIP UJI-nya sendiri, bukan aplikasi**
(dicatat supaya tidak terulang kalau nanti nulis skrip beban serupa):

1. Peserta "putus saat countdown" awalnya salah timing — kode menunggu
   presenter selesai menerima `pertanyaan_dibuka` (yang berarti countdown 3
   detik sudah lewat) SEBELUM menjalankan aksi peserta, jadi diskoneksi-nya
   selalu telat. Diperbaiki: presenter-wait dan aksi peserta sekarang jalan
   bersamaan lewat satu `asyncio.gather`.
2. **`.send()` WebSocket tanpa timeout bisa menggantung SELAMANYA** kalau satu
   dari ratusan koneksi diam-diam mati (Render motong koneksi tanpa close
   frame bersih) — karena ada di dalam `asyncio.gather` bareng peserta lain,
   satu socket macet cukup untuk menggantung seluruh simulasi (sempat terjadi,
   proses jalan 30+ menit tanpa progres tanpa CPU aktif). Sekarang semua
   `send()`/`close()` dibungkus `asyncio.wait_for`, plus watchdog per ronde
   (`asyncio.timeout(durasi + 30)` per peserta, `durasi + 90` per ronde) supaya
   satu koneksi bermasalah tidak pernah bisa menggantung keseluruhan proses.
3. Penutupan ratusan koneksi di akhir dilakukan satu-per-satu (`for p in ...:
   await p.putus()`) — kalau banyak yang sudah setengah mati, totalnya bisa
   berkali-kali lipat lebih lama dari perlu. Diperbaiki jadi paralel lewat
   `asyncio.gather`.

**Catatan penting kalau mau uji beban besar lagi**: kalau proses klien
dihentikan paksa (mis. `kill`/Ctrl+C) di tengah ratusan koneksi WebSocket
aktif, instance Render bisa butuh waktu untuk "sadar" semua koneksi itu mati
(tidak ada close frame bersih) — sempat terjadi endpoint biasa jadi lambat
selama beberapa saat setelahnya. Kalau harus menghentikan paksa, cek
`/healthz` dulu sebelum lanjut uji berikutnya.

## 2026-09-11 — 7 skenario edge case lolos di Render sungguhan

Skrip baru [tools/uji_edge_case.py](tools/uji_edge_case.py) (gaya sama seperti
`uji_alur.py`, standalone bukan pytest), dijalankan ke
`live-polling-tz7j.onrender.com`:

```bash
.venv/Scripts/python.exe tools/uji_edge_case.py https://nama-app.onrender.com
```

Semua **lolos**:

1. **Reconnect tepat di tengah countdown 3 detik** — partisipan yang
   putus-sambung persis di jendela hitung mundur dapat pesan `hitung_mundur`
   (bukan opsi soal lebih awal), lalu soal terbuka normal setelah countdown
   selesai.
2. **Klik dobel "aktifkan soal"** — dua request `aktifkan` nyaris bersamaan
   pada soal yang sama cuma menghasilkan SATU `pertanyaan_dibuka` yang sampai
   ke klien (mekanisme `_generasi_aktif` di `runtime.py` bekerja sesuai
   desain), soal tidak macet.
3. **Survey Mode + Quiz Mode jalan bersamaan** — agregat jawaban dua sesi
   berbeda tidak bocor silang meski soal dibuka & dijawab hampir serentak.
4. **Gambar besar di pertanyaan** — 1.9MB tersimpan utuh. **Catatan (bukan
   bug baru, sudah didokumentasikan sebelumnya)**: gambar 2.6MB (di atas
   batas 2MB yang cuma ditulis di form UI) tetap **diterima server** karena
   `_validasi_pertanyaan` di `api_admin.py` cuma cek prefix
   `data:image/...`, tidak ada validasi ukuran sisi server.
5. **Nickname sama dikirim bersamaan oleh 2 "device"** — dikirim betul-betul
   paralel (bukan berurutan) lewat 3 thread terpisah: tepat satu yang lolos,
   dua lainnya kena 409 lewat jalur `IntegrityError` di `api_peserta.py`
   (bukan cuma pre-check SELECT), DB tidak pernah punya nickname duplikat.
6. **Presenter reconnect di tengah sesi** (socket) — dapat kembali soal aktif
   & agregat jawaban yang sudah masuk.
6b. **Restart instance Render sungguhan** (bukan cuma reconnect socket) —
   diuji manual: buat sesi aktif dengan soal bertimer 180 detik + 2 jawaban
   masuk, lalu restart service dari dashboard Render di tengah jalan. Setelah
   restart, `manajer.py` berhasil membangun ulang `RuntimeSesi` dari database:
   soal aktif, 2 jawaban, dan sisa waktu timer semuanya selamat. Mode ini
   perlu aksi manual (skrip menunggu 60 detik lalu mengecek):
   ```bash
   .venv/Scripts/python.exe tools/uji_edge_case.py https://nama-app.onrender.com restart
   ```
7. **Partisipan putus koneksi sebelum soal ditutup, balik setelahnya** — baik
   yang sempat menjawab maupun yang tidak, keduanya mendapat `pribadi`
   (menjawab/poin) yang benar saat reconnect, soal tetap ditutup timer meski
   keduanya offline saat itu.

## 2026-09-11 — Uji beban 200 partisipan lolos di Render

Dijalankan ke deployment sungguhan (`live-polling-tz7j.onrender.com`,
Render free tier + Neon): **semua uji lulus**, 200/200 jawaban di-ack dalam
**138 ms**, broadcast presenter tetap 1 update (bukan 200).

Percobaan pertama sempat gagal `TimeoutError: timed out during handshake` —
bukan karena aplikasi, tapi karena skrip membuka 200 handshake WebSocket
**serentak** ke server jauh. Diperbaiki: koneksi dibuka bergelombang 25
(`GELOMBANG_KONEKSI`, tetap sekaligus kalau target localhost) dengan
`open_timeout=30`. Ini juga lebih mirip kenyataan — di acara asli peserta
masuk berangsur-angsur. Bagian yang memang harus serentak (semua menjawab
bersamaan) tetap diuji penuh.

Batas tunggu `pertanyaan_dibuka` juga dinaikkan ke 20 detik karena sekarang
ada hitung mundur 3 detik sebelum soal benar-benar terbuka.

## 2026-09-11 — Uji beban bisa diatur jumlah partisipannya

`tools/uji_alur.py` sekarang menerima argumen kedua = jumlah partisipan pada
uji beban (default 150):

```bash
.venv/Scripts/python.exe tools/uji_alur.py https://nama-app.onrender.com 200
```

Ambang "ack di bawah N detik" otomatis jadi 5 detik kalau targetnya server
jauh (bukan localhost) — sebelumnya kaku 2 detik, yang berarti latensi
jaringan ke Render bakal dilaporkan sebagai kegagalan aplikasi padahal bukan.
Angka ack sebenarnya tetap dicetak.

Sudah diverifikasi lokal dengan 200 partisipan: 200/200 jawaban di-ack dalam
114 ms, broadcast ke presenter tetap ter-throttle jadi 1 update (bukan 200).

## 2026-09-11 — Tombol aksi tidak lagi merah

Merah di tombol yang sering diklik terasa seperti peringatan, jadi semua
aksi utama (Gabung, Buat Sesi, Presentasi, Simpan Pertanyaan, pil tipe
soal, pilihan rating) pindah ke **Biru Crate `#290370`** — token baru
`--utama` di [app.css](static/css/app.css). Chip "← Kembali ke admin"
ikut dinetralkan jadi abu.

Merah sengaja **tetap** dipakai di tiga tempat, jangan diubah tanpa alasan:

- penanda non-klik (kode sesi, ring timer, titik LIVE berdenyut, chip label);
- aksi merusak (Hapus/Akhiri Sesi, hapus opsi) — konvensi yang justru
  membantu supaya tidak terklik tanpa sadar;
- kartu pilihan jawaban kuis, karena merah tomat salah satu dari 4 warna
  kategori (ini eksplisit disetujui user).

## 2026-09-11 — Palet warna baru, hitung mundur soal, dan rapikan layar presenter

- **Ganti palet warna** mengikuti [PANDUAN_WARNA.md](PANDUAN_WARNA.md) (dari
  user, hasil mockup `mockup_bold_primary.html`): dasar putih, garis & teks
  hitam pekat, aksen merah `#ED1C24`, plus 4 warna kategori untuk opsi
  jawaban/bar hasil. Semua token ada di `:root`
  [static/css/app.css](static/css/app.css) — tidak ada file token terpisah.
  - Aturan semantik yang wajib dijaga: **merah = brand + jawaban salah,
    biru `#235789` = jawaban benar, kuning `#F1D302` = juara**. Jangan
    pakai merah untuk "sukses/benar" (dulu hijau limau dipakai untuk
    keduanya) — makanya toast sukses & lencana "Jawaban Benar" sekarang biru.
  - Kartu jawaban kuis jadi solid 4 warna kategori + teks putih
    (`.opt-a`–`.opt-f`); bar hasil presenter dan bar poll di HP dapat warna
    per-opsi lewat kelas `warna-1`–`warna-4` yang di-set dari JS
    (`gambarHasilMC` di present.js, `gambarHasilSurvey` di play.js).
  - Tipe soal di daftar kelola jadi pil berwarna (`.pil-tipe-*`): MC biru,
    Word Cloud kuning, Rating hijau.
  - Dua penyimpangan disengaja dari panduan (alasannya ditulis di
    PANDUAN_WARNA.md bagian "Status Implementasi"): teks gelap di kartu
    kuning, dan sorotan baris "ini kamu" pakai kuning lembut.

- **Hitung mundur 3 detik sebelum soal mulai** — begitu presenter aktifkan
  soal, semua orang (presenter & HP) lihat pertanyaannya dulu + angka
  mundur 3-2-1 (animasi pop tiap detik), opsi jawaban & timer jawab baru
  muncul/mulai SETELAH hitung mundur selesai — bukan berkurang dari durasi
  jawab. Endpoint `aktifkan`/`berikutnya` langsung selesai (tidak nunggu
  3 detik); hitung mundur & "mulai sungguhan" jalan sebagai background
  task terpisah (`_mulai_setelah_hitung_mundur()` di
  [runtime.py](app/realtime/runtime.py)).
  - Pesan WS baru: `hitung_mundur` (`{sesi, pertanyaan: {..tanpa opsi..}, detik}`),
    dikirim ke semua role. Ditangani `gambarHitungMundur()` di
    [present.js](static/js/present.js) & [play.js](static/js/play.js).
  - `Pertanyaan.dibuka_at` sengaja `None` dulu selama hitung mundur (bukan
    langsung diisi saat tombol diklik) — `StatePertanyaan.dibuka_epoch`
    ikut `None`, dipakai `terima_jawaban()` buat nolak jawaban yang entah
    bagaimana masuk sebelum soal benar-benar dibuka.
  - **Bug yang sempat ketemu & sudah diperbaiki**: kalau soal yang SAMA
    diaktifkan ulang cepat (klik dobel dsb) sebelum hitung mundur pertama
    selesai, task lama yang basi bisa salah memicu mulai lebih awal —
    dicegah dengan nomor generasi (`_generasi_aktif`) di `RuntimeSesi`,
    bukan cuma cocokkan `question_id` (soal yang sama = id yang sama juga).
  - `state_untuk_partisipan()`/`state_untuk_presenter()` juga dibuat sadar
    fase ini (kirim ulang `hitung_mundur` kalau reconnect persis di tengah
    jendela 3 detik itu), dan `manajer.py` self-heal kalau instance restart
    persis di tengah countdown (anggap mulai sekarang, daripada macet
    selamanya nunggu task yang sudah hilang).
  - **Catatan pengujian**: kalau menguji manual lewat script/browser
    otomatis, ukur waktu pakai `Date.now()`/timestamp asli, JANGAN asumsikan
    tiap `setTimeout` di loop = durasi persis yang diminta — tab browser
    yang tidak sedang di-foreground bisa di-throttle drastis oleh browser,
    bikin hasil ukur "kelihatan" jauh lebih cepat dari yang sebenarnya
    terjadi di server (sempat bikin bingung waktu development ini).

- **Spacing opsi kuis tidak dempet** — gap `.kuis-grid` diperbesar (10px →
  14px). Opsi jawaban dengan teks > 24 karakter otomatis pindah dari grid
  2 kolom ke **1 kolom penuh** (`adaOpsiPanjang()` di
  [common.js](static/js/common.js), dipakai di `pasangMC()` play.js dan
  `gambarOpsiKuis()` present.js) — CSS `.kuis-grid.satu-kolom`.
- **Layar presenter tidak pernah scroll saat Layar Penuh** — `sesuaikanUkuranPanggung()`
  di [present.js](static/js/present.js): kalau konten (soal panjang, banyak
  opsi, dst) melebihi tinggi yang tersisa di viewport, seluruh konten
  `#isi-panggung` di-scale-down proporsional (`transform: scale()` + lebar
  dikompensasi `100/skala%`, mirip zoom-out) sampai muat, minimal skala 0.55.
  Kalau skala minimum masih kurang, `#isi-panggung` sendiri yang jadi
  scrollable (bukan halaman) sebagai fallback. **Hanya aktif kalau
  `document.fullscreenElement` ada** (klik "Layar Penuh") — di luar itu,
  scroll biasa tetap dibiarkan. Dipanggil ulang di setiap titik render
  (lobi, kerangka soal, hasil, leaderboard, podium) + event `resize` dan
  `fullscreenchange`.
  - **Catatan teknis penting**: hitung ruang tersedia JANGAN pakai posisi
    elemen yang letaknya di bawah `#isi-panggung` (mis. `#kontrol`) langsung
    dari `getBoundingClientRect()` — posisinya ikut bergeser kalau konten di
    atasnya meluber, jadi hasilnya muter (lingkaran setan). Yang aman:
    `#isi-panggung`'s top position (tidak bergantung tinggi dirinya sendiri)
    dikurangi tinggi elemen-elemen SETELAHNYA yang diukur dari
    `offsetHeight`/margin/padding CSS langsung (bukan posisi relatif viewport).

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
