# Panduan Warna — Live Polling App

Referensi warna final dari mockup (`mockup_bold_primary.html`), untuk dipakai konsisten saat coding aplikasi asli nanti. File token CSS-nya ada di `design-tokens.css` — tinggal di-import.

## Palet Warna

| Nama | Hex | Dipakai untuk |
|---|---|---|
| Putih (dasar) | `#FDFFFC` | Background utama semua layar |
| Hitam (garis/teks) | `#020100` | Border, garis, teks utama |
| Merah (aksen brand) | `#ED1C24` | Tombol CTA utama, kode sesi, timer ring |
| Biru Lapis Lazuli | `#235789` | Indikator "Jawaban Benar" di Quiz Mode |
| Kuning (badge) | `#F1D302` | Badge juara #1 leaderboard |
| **Biru Crate** | `#290370` | Kategori/opsi 1 (kartu jawaban, bar chart, tag) |
| **Merah Tomat** | `#B81817` | Kategori/opsi 2 |
| **Kuning Citrus** | `#E9B900` | Kategori/opsi 3 |
| **Hijau Beans** | `#557618` | Kategori/opsi 4 |

## Peta Pemakaian per Komponen

**Kartu jawaban Quiz Mode (4 pilihan)**
Solid warna + teks putih: Biru Crate → Merah Tomat → Kuning Citrus → Hijau Beans (urutan A/B/C/D).

**Bar chart hasil (layar Presenter, Survey Mode)**
Tiap opsi jawaban dapat warna berbeda dari 4 kategori di atas, supaya gampang dibedain sekilas — bukan satu warna dominan untuk semua bar.

**Progress bar poll di HP partisipan**
Versi tint lembut (soft) dari 4 warna kategori, teks persentase pakai warna solidnya. Nilai tint sudah dihitung di `design-tokens.css` (`.poll-tint-1` s/d `.poll-tint-4`).

**Tag tipe pertanyaan (Admin)**
- Multiple Choice → Biru Crate
- Word Cloud → Kuning Citrus (teks gelap `#3A2E00`, bukan putih, karena kuning terang kurang kontras dengan teks putih)
- Rating → Hijau Beans

**Badge peringkat leaderboard**
- Juara 1 → Kuning `#F1D302` (kesan medali)
- Juara 2 → Biru Crate
- Juara 3 → Hijau Beans
- Juara 4 → Merah Tomat

**Indikator jawaban benar/salah (Quiz Mode)**
- Benar → Biru (`#235789` + tint `#E1EAF1`)
- Salah → Merah aksen (`#ED1C24` + tint `#FCE1E2`)
- **Catatan penting**: sengaja dipisah biru/merah (bukan merah untuk keduanya), supaya tidak rancu antara "merah = aksen brand" dan "merah = jawaban salah".

**Dekorasi background**
Tiap layar aplikasi (Admin, Presenter, Partisipan) dikasih 2-3 blob warna blur samar (opacity 12-18%) dari 4 warna kategori, biar background nggak flat putih polos tapi dasarnya tetap putih. Implementasi teknis ada di `design-tokens.css` bagian `.bg-decoration` — **wajib** kasih `position: relative; z-index: 1;` ke elemen konten (header, teks, tombol) supaya nggak ketutupan blob.

## Catatan Aksesibilitas
Kuning Citrus (`#E9B900`) kontrasnya lebih rendah dibanding warna lain kalau dipasangkan teks putih. Sudah diantisipasi:
- Kartu jawaban Quiz Mode: tetap putih (sesuai permintaan eksplisit), tapi kalau nanti pas testing di layar proyektor kurang kebaca, bisa digelapin dikit huenya atau teks diganti hitam khusus kartu ini.
- Tag "Word Cloud": sudah pakai teks gelap (`#3A2E00`), bukan putih.

## Status Implementasi di Aplikasi Ini

Palet ini **sudah diterapkan** — token warnanya tinggal di `:root`
[static/css/app.css](static/css/app.css), jadi tidak perlu impor
`design-tokens.css` terpisah. Pemetaan nama tokennya:

| Panduan | Token di app.css |
|---|---|
| Putih dasar | `--canvas` |
| Hitam garis/teks | `--ink`, `--line` |
| Merah aksen | `--accent`, `--accent-tint`, `--accent-deep`, `--danger` |
| Biru "jawaban benar" | `--benar`, `--benar-soft` |
| Kuning juara | `--juara`, `--juara-soft` |
| 4 warna kategori | `--kat-biru`, `--kat-merah`, `--kat-kuning`, `--kat-hijau` |
| (tambahan) warna aksi/tombol | `--utama` = Biru Crate |

**Merah tidak dipakai untuk elemen yang diklik.** Tombol/menu aksi
(Gabung, Buat Sesi, Presentasi, Simpan, pil tipe soal, pilihan rating)
memakai **Biru Crate `#290370`** (token `--utama`). Merah disisakan untuk:

- penanda non-klik: kode sesi, ring timer, titik LIVE, chip label;
- aksi merusak: Hapus/Akhiri Sesi, hapus opsi — di sini merah justru
  konvensi yang benar supaya tidak terklik tanpa sadar;
- kartu pilihan jawaban kuis (salah satu dari 4 warna kategori).

Tiga penyimpangan yang disengaja dari panduan, semuanya demi keterbacaan
atau kejelasan maksud:

1. **Kartu jawaban kuning** pakai teks gelap (`#3A2E00`), bukan putih —
   memakai jalan keluar yang sudah panduan ini sendiri sebut di bagian
   Catatan Aksesibilitas, karena putih di atas kuning citrus terlalu tipis
   kontrasnya untuk dibaca dari jauh saat dipresentasikan.
2. **Sorotan baris "ini kamu"** di leaderboard pakai kuning lembut, bukan
   merah/biru — merah dan biru sudah punya arti "salah"/"benar" di layar
   yang sama, jadi dipakai warna ketiga supaya tidak rancu.
3. **Tombol CTA biru, bukan merah** (lihat bagian di atas) — permintaan
   langsung user: merah di tombol yang sering diklik terasa seperti
   peringatan.

## File Terkait
- `mockup_bold_primary.html` — mockup visual lengkap sebagai referensi tata letak
- `PRD_Live_Polling_App.md` — dokumen kebutuhan fungsional & teknis aplikasi
