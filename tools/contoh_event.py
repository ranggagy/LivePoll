"""Buat dua event contoh: satu Survey Mode dan satu Quiz Mode, masing-masing 5 pertanyaan.

Isinya sengaja dibuat siap pakai untuk demo/latihan — silakan diubah lewat
halaman kelola sesi setelah dibuat.

Jalankan setelah server hidup:
    .venv/Scripts/python.exe tools/contoh_event.py
    .venv/Scripts/python.exe tools/contoh_event.py https://nama-app.onrender.com
"""

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASIS = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010").rstrip("/")


def panggil(metode: str, jalur: str, muatan=None):
    data = json.dumps(muatan).encode() if muatan is not None else None
    req = Request(BASIS + jalur, data=data, method=metode, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"Gagal {metode} {jalur} -> {e.code}: {detail}")


# --- Event 1: Survey Mode, semua tipe pertanyaan dipakai ------------------

SURVEY = {
    "judul": "Town Hall Divisi Keuangan — Q4 2026",
    "mode": "survey",
    "pertanyaan": [
        {
            "tipe": "mc",
            "teks": "Area mana yang paling perlu ditingkatkan tahun depan?",
            "opsi": [
                {"teks": "Proses & efisiensi kerja"},
                {"teks": "Kolaborasi antar tim"},
                {"teks": "Tools & teknologi"},
                {"teks": "Komunikasi internal"},
            ],
        },
        {
            "tipe": "word_cloud",
            "teks": "Satu kata untuk menggambarkan tahun ini?",
            "opsi": [],
        },
        {
            "tipe": "rating",
            "teks": "Seberapa puas kamu dengan komunikasi internal selama ini?",
            "rating_maks": 5,
            "opsi": [],
        },
        {
            "tipe": "mc",
            "teks": "Format pertemuan tim yang paling efektif menurutmu?",
            "opsi": [
                {"teks": "Daily stand-up singkat"},
                {"teks": "Mingguan, tapi lebih dalam"},
                {"teks": "Bulanan + update tertulis"},
                {"teks": "Cukup asinkron lewat chat"},
            ],
        },
        {
            "tipe": "rating",
            "teks": "Seberapa besar kemungkinan kamu merekomendasikan tempat kerja ini ke teman?",
            "rating_maks": 10,
            "opsi": [],
        },
    ],
}

# --- Event 2: Quiz Mode, 5 soal pilihan ganda bertimer --------------------

QUIZ = {
    "judul": "Kuis Literasi Pelaporan Keuangan",
    "mode": "quiz",
    "pertanyaan": [
        {
            "tipe": "mc",
            "teks": "Dalam neraca, total Aset harus selalu sama dengan?",
            "durasi_detik": 20,
            "opsi": [
                {"teks": "Liabilitas + Ekuitas", "is_benar": True},
                {"teks": "Liabilitas − Ekuitas"},
                {"teks": "Pendapatan − Beban"},
                {"teks": "Ekuitas + Laba ditahan"},
            ],
        },
        {
            "tipe": "mc",
            "teks": "OJK adalah singkatan dari?",
            "durasi_detik": 15,
            "opsi": [
                {"teks": "Otoritas Jasa Keuangan", "is_benar": True},
                {"teks": "Organisasi Jaminan Kredit"},
                {"teks": "Otoritas Jaminan Kas"},
                {"teks": "Ombudsman Jasa Keuangan"},
            ],
        },
        {
            "tipe": "mc",
            "teks": "Laporan yang menunjukkan posisi keuangan pada satu titik waktu tertentu adalah?",
            "durasi_detik": 20,
            "opsi": [
                {"teks": "Neraca", "is_benar": True},
                {"teks": "Laporan laba rugi"},
                {"teks": "Laporan arus kas"},
                {"teks": "Laporan perubahan ekuitas"},
            ],
        },
        {
            "tipe": "mc",
            "teks": "Dalam akuntansi, 'rekonsiliasi' paling tepat berarti?",
            "durasi_detik": 20,
            "opsi": [
                {"teks": "Mencocokkan dua catatan sampai selisihnya nol", "is_benar": True},
                {"teks": "Menghapus transaksi yang salah input"},
                {"teks": "Memindahkan saldo ke periode berikutnya"},
                {"teks": "Menghitung ulang penyusutan aset"},
            ],
        },
        {
            "tipe": "mc",
            "teks": "Pada pembukuan berpasangan (double-entry), satu transaksi dicatat minimal di berapa akun?",
            "durasi_detik": 15,
            "opsi": [
                {"teks": "Dua akun", "is_benar": True},
                {"teks": "Satu akun"},
                {"teks": "Tiga akun"},
                {"teks": "Tergantung nilai transaksinya"},
            ],
        },
    ],
}


def buat_event(spesifikasi: dict) -> str:
    sesi = panggil("POST", "/api/admin/sesi", {"judul": spesifikasi["judul"], "mode": spesifikasi["mode"]})
    kode = sesi["kode_sesi"]
    for q in spesifikasi["pertanyaan"]:
        panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", q)
    label = "Quiz Mode" if spesifikasi["mode"] == "quiz" else "Survey Mode"
    rincian = ", ".join(
        {"mc": "Multiple Choice", "word_cloud": "Word Cloud", "rating": "Rating"}[q["tipe"]]
        for q in spesifikasi["pertanyaan"]
    )
    print(f"\n  {spesifikasi['judul']}")
    print(f"  Kode sesi   : {kode}   ({label}, {len(spesifikasi['pertanyaan'])} pertanyaan)")
    print(f"  Tipe soal   : {rincian}")
    print(f"  Kelola      : {BASIS}/admin/{kode}")
    print(f"  Presenter   : {BASIS}/present/{kode}")
    print(f"  Partisipan  : {BASIS}/join/{kode}")
    return kode


if __name__ == "__main__":
    print(f"Membuat event contoh di {BASIS}")
    buat_event(SURVEY)
    buat_event(QUIZ)
    print("\nDua event ini berjalan berdampingan — aplikasi mendukung banyak sesi aktif sekaligus.")
