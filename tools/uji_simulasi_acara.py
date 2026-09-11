"""Simulasi acara sungguhan: 300 partisipan, 5 soal quiz, dari lobi sampai
podium/leaderboard, DENGAN berbagai trouble sisi klien tercampur di dalam
satu alur (bukan skenario terpisah) — HP reconnect, klik dobel presenter,
koneksi putus, telat menjawab, jawaban dobel, nickname bentrok, sebagian
peserta baru gabung di tengah acara, sebagian keluar permanen di tengah jalan.

SENGAJA cuma dirancang untuk server jauh (Render), bukan localhost — tujuan
utamanya menguji perilaku di bawah kondisi jaringan asli (default target
Render). Kalau target localhost, banyak ambang waktu di sini akan terlalu
longgar/tidak relevan (tapi tetap boleh untuk debug skrip ini sendiri).

Jalankan:
    .venv/Scripts/python.exe tools/uji_simulasi_acara.py https://nama-app.onrender.com [jumlah_peserta]
"""

import asyncio
import json
import random
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import websockets

BASIS = sys.argv[1] if len(sys.argv) > 1 else "https://live-polling-tz7j.onrender.com"
JUMLAH_TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 300
LOKAL = BASIS.startswith("http://127.0.0.1") or BASIS.startswith("http://localhost")
if LOKAL:
    print("PERINGATAN: skrip ini dirancang untuk server jauh (Render); ambang")
    print("waktu di sini longgar untuk latensi jaringan, hasil di localhost")
    print("kurang representatif. Lanjut tetap jalan untuk keperluan debug.\n")

GELOMBANG_KONEKSI = 30 if not LOKAL else JUMLAH_TARGET
BATAS_WS = 25 if not LOKAL else 8
gagal = 0
temuan: list[str] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> None:
    global gagal
    if kondisi:
        print(f"  OK   {nama}")
    else:
        gagal += 1
        pesan = f"  GAGAL {nama} {detail}"
        print(pesan)
        temuan.append(f"{nama} {detail}".strip())


def info(pesan: str) -> None:
    print(f"  INFO {pesan}")


def panggil(metode: str, jalur: str, muatan=None):
    data = json.dumps(muatan).encode() if muatan is not None else None
    req = Request(BASIS + jalur, data=data, method=metode, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as resp:
        isi = resp.read()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return json.loads(isi)
        return isi


def panggil_status(metode: str, jalur: str, muatan=None):
    data = json.dumps(muatan).encode() if muatan is not None else None
    req = Request(BASIS + jalur, data=data, method=metode, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            isi = resp.read()
            body = json.loads(isi) if resp.headers.get("content-type", "").startswith("application/json") else isi
            return resp.status, body
    except HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = None
        return e.code, body


def ws_url(jalur: str) -> str:
    u = urlparse(BASIS)
    skema = "wss" if u.scheme == "https" else "ws"
    return f"{skema}://{u.netloc}{jalur}"


async def ambil(ws, tipe, batas=BATAS_WS):
    async with asyncio.timeout(batas):
        while True:
            pesan = json.loads(await ws.recv())
            if pesan.get("tipe") == tipe:
                return pesan


async def kirim(ws, payload: dict, timeout: float = 10.0) -> None:
    """send() TANPA timeout bawaan bisa macet selamanya kalau koneksi diam-diam
    mati (mis. proxy Render motong koneksi tanpa FIN bersih) — dengan 300 socket
    sekaligus, satu send() yang macet cukup untuk menggantung SELURUH simulasi
    karena dia bagian dari asyncio.gather bareng peserta lain. Selalu dibatasi."""
    await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=timeout)


async def ambil_semua(ws, tipe, jendela=2.0):
    hasil = []
    akhir = time.monotonic() + jendela
    while True:
        sisa = akhir - time.monotonic()
        if sisa <= 0:
            break
        try:
            async with asyncio.timeout(sisa):
                pesan = json.loads(await ws.recv())
        except asyncio.TimeoutError:
            break
        if pesan.get("tipe") == tipe:
            hasil.append(pesan)
    return hasil


class Peserta:
    """Satu 'HP' peserta simulasi: nickname, token, socket aktif, dan trouble-nya."""

    def __init__(self, idx: int, nickname: str, peran_trouble: str):
        self.idx = idx
        self.nickname = nickname
        self.peran_trouble = peran_trouble
        self.token: str | None = None
        self.participant_id: int | None = None
        self.ws = None
        self.tugas_ping: asyncio.Task | None = None
        self.pergi_permanen = False
        self.soal_untuk_diam: int | None = None  # index soal (0..4) tempat dia sengaja tidak jawab
        self.soal_untuk_telat: int | None = None  # index soal tempat dia sengaja telat jawab
        self.total_poin_diketahui = 0
        self.jawaban_per_soal: dict[int, dict] = {}  # index_soal -> {"ok":.., "alasan":..}

    async def sambung(self):
        """Sambung & kembalikan pesan pertama server APA ADANYA (bisa tipe 'state'
        ATAU 'hitung_mundur' kalau kebetulan connect persis di jendela countdown) —
        jangan difilter ke satu tipe saja, karena tipe pesan pertama itu sendiri
        bagian dari yang mau diverifikasi di skenario countdown_disconnect."""
        self.ws = await websockets.connect(ws_url(f"/ws/play/{KODE}?token={self.token}"), open_timeout=30)
        pesan_awal = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=BATAS_WS))
        self._pasang_ping()
        return pesan_awal

    def _pasang_ping(self):
        self._batalkan_ping()

        async def _loop():
            try:
                while True:
                    await asyncio.sleep(20)
                    await kirim(self.ws, {"tipe": "ping"}, timeout=10)
            except (asyncio.CancelledError, Exception):
                return

        self.tugas_ping = asyncio.create_task(_loop())

    def _batalkan_ping(self):
        if self.tugas_ping and not self.tugas_ping.done():
            self.tugas_ping.cancel()
        self.tugas_ping = None

    async def putus(self):
        self._batalkan_ping()
        if self.ws is not None:
            ws, self.ws = self.ws, None
            try:
                await asyncio.wait_for(ws.close(), timeout=5)
            except Exception:
                pass


KODE = ""


def buat_pertanyaan_quiz(kode: str, n: int) -> list[dict]:
    daftar = []
    for i in range(n):
        durasi = [15, 15, 15, 18, 18][i % 5]
        opsi = [
            {"teks": "Opsi A", "is_benar": i % 4 == 0},
            {"teks": "Opsi B", "is_benar": i % 4 == 1},
            {"teks": "Opsi C", "is_benar": i % 4 == 2},
            {"teks": "Opsi D", "is_benar": i % 4 == 3},
        ]
        q = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
            "tipe": "mc", "teks": f"Soal {i + 1} dari {n} — simulasi acara nyata",
            "durasi_detik": durasi, "opsi": opsi,
        })
        daftar.append(q)
    return daftar


def bagi_trouble(n: int) -> list[str]:
    """Bagi n peserta gelombang awal ke berbagai peran trouble, sisanya 'normal'."""
    peran = (
        ["disconnect_mid_answer"] * max(1, round(n * 0.07))
        + ["countdown_disconnect"] * max(1, round(n * 0.05))
        + ["double_submit"] * max(1, round(n * 0.05))
        + ["late_submit"] * max(1, round(n * 0.035))
        + ["diam_satu_soal"] * max(1, round(n * 0.035))
        + ["keluar_permanen_setelah_q3"] * max(1, round(n * 0.02))
    )
    peran += ["normal"] * max(0, n - len(peran))
    random.shuffle(peran)
    return peran[:n]


async def gabung_semua(peserta_list: list[Peserta]):
    """Join REST secara bergelombang (bukan sekaligus) — mirip peserta acara asli masuk berangsur."""
    for mulai in range(0, len(peserta_list), GELOMBANG_KONEKSI):
        bagian = peserta_list[mulai:mulai + GELOMBANG_KONEKSI]
        hasil = await asyncio.gather(*(
            asyncio.to_thread(panggil, "POST", f"/api/gabung/{KODE}", {"nickname": p.nickname})
            for p in bagian
        ))
        for p, h in zip(bagian, hasil):
            p.token = h["token"]
            p.participant_id = h["participant_id"]


async def uji_nickname_bentrok(nickname_dipakai: list[str]):
    """Selipkan percobaan gabung dengan nickname yang SUDAH dipakai (typo/2 device
    ngetik nama sama), harus konsisten ditolak 409 — dilakukan di tengah beban nyata,
    bukan skenario terisolasi."""
    contoh = random.sample(nickname_dipakai, min(3, len(nickname_dipakai)))
    hasil = await asyncio.gather(*(
        asyncio.to_thread(panggil_status, "POST", f"/api/gabung/{KODE}", {"nickname": f"  {n.upper()}  "})
        for n in contoh
    ))
    status_list = [h[0] for h in hasil]
    cek("nickname yang sudah dipakai tetap konsisten ditolak 409 walau di tengah beban 300 peserta",
        all(s == 409 for s in status_list), f"status: {status_list}")


async def perilaku_normal(p: Peserta, soal: dict, opsi: list[dict], idx_soal: int, durasi: int):
    await ambil(p.ws, "pertanyaan_dibuka", batas=BATAS_WS)
    if p.soal_untuk_diam == idx_soal:
        p.jawaban_per_soal[idx_soal] = {"aksi": "sengaja diam"}
        return
    tunda = random.uniform(1.0, max(2.0, durasi - 3))
    await asyncio.sleep(tunda)
    benar = random.random() < 0.7
    kandidat = [o for o in opsi if bool(o.get("is_benar")) == benar]
    target = kandidat[0] if kandidat else opsi[0]
    try:
        await kirim(p.ws, {"tipe": "jawab", "question_id": soal["id"], "option_id": target["id"]})
        ack = await ambil(p.ws, "jawaban_diterima", batas=BATAS_WS)
        p.jawaban_per_soal[idx_soal] = {"aksi": "jawab_normal", "ok": ack.get("ok"), "pesan": ack.get("pesan")}
    except Exception as e:
        p.jawaban_per_soal[idx_soal] = {"aksi": "error", "pesan": str(e)}


async def perilaku_disconnect_mid_answer(p: Peserta, soal: dict, opsi: list[dict], idx_soal: int, durasi: int):
    await ambil(p.ws, "pertanyaan_dibuka", batas=BATAS_WS)
    await p.putus()
    await asyncio.sleep(random.uniform(1.5, 4.0))
    try:
        await p.sambung()
        target = opsi[0]
        await kirim(p.ws, {"tipe": "jawab", "question_id": soal["id"], "option_id": target["id"]})
        ack = await ambil(p.ws, "jawaban_diterima", batas=BATAS_WS)
        p.jawaban_per_soal[idx_soal] = {"aksi": "reconnect_lalu_jawab", "ok": ack.get("ok"), "pesan": ack.get("pesan")}
    except Exception as e:
        p.jawaban_per_soal[idx_soal] = {"aksi": "error_reconnect", "pesan": str(e)}


async def perilaku_countdown_disconnect(p: Peserta, soal: dict, opsi: list[dict], idx_soal: int, durasi: int):
    """Diputus SEGERA setelah soal diaktifkan (dipanggil bersamaan dengan presenter
    menunggu countdown) — jadi betul-betul mendarat di jendela countdown 3 detik,
    reconnect, lalu jawab normal begitu soal benar-benar terbuka."""
    await p.putus()
    await asyncio.sleep(random.uniform(0.3, 1.2))
    try:
        pesan_awal = await p.sambung()
    except Exception as e:
        p.jawaban_per_soal[idx_soal] = {"aksi": "error_reconnect_countdown", "pesan": str(e)}
        return
    try:
        if pesan_awal.get("tipe") == "hitung_mundur":
            buka = await ambil(p.ws, "pertanyaan_dibuka", batas=BATAS_WS)
            opsi_diterima = buka["pertanyaan"]["opsi"]
        elif pesan_awal.get("tipe") == "state" and pesan_awal.get("pertanyaan"):
            opsi_diterima = pesan_awal["pertanyaan"]["opsi"]
        else:
            opsi_diterima = None
        cek_opsi_lengkap = bool(opsi_diterima) and len(opsi_diterima) == len(opsi)
        target_id = opsi_diterima[0]["id"] if opsi_diterima else opsi[0]["id"]
        await asyncio.sleep(random.uniform(0.5, 2.0))
        await kirim(p.ws, {"tipe": "jawab", "question_id": soal["id"], "option_id": target_id})
        ack = await ambil(p.ws, "jawaban_diterima", batas=BATAS_WS)
        p.jawaban_per_soal[idx_soal] = {
            "aksi": "countdown_reconnect_lalu_jawab", "ok": ack.get("ok"),
            "opsi_lengkap": cek_opsi_lengkap, "tipe_awal": pesan_awal.get("tipe"),
        }
    except Exception as e:
        p.jawaban_per_soal[idx_soal] = {"aksi": "error_countdown", "pesan": str(e)}


async def perilaku_double_submit(p: Peserta, soal: dict, opsi: list[dict], idx_soal: int, durasi: int):
    await ambil(p.ws, "pertanyaan_dibuka", batas=BATAS_WS)
    target = opsi[0]
    await kirim(p.ws, {"tipe": "jawab", "question_id": soal["id"], "option_id": target["id"]})
    ack1 = await ambil(p.ws, "jawaban_diterima", batas=BATAS_WS)
    await kirim(p.ws, {"tipe": "jawab", "question_id": soal["id"], "option_id": opsi[-1]["id"]})
    ack2 = await ambil(p.ws, "jawaban_diterima", batas=BATAS_WS)
    p.jawaban_per_soal[idx_soal] = {
        "aksi": "double_submit", "ok_pertama": ack1.get("ok"), "ok_kedua": ack2.get("ok"),
        "sudah_flag": ack2.get("sudah"),
    }


async def perilaku_late_submit(p: Peserta, soal: dict, opsi: list[dict], idx_soal: int, durasi: int):
    buka = await ambil(p.ws, "pertanyaan_dibuka", batas=BATAS_WS)
    await asyncio.sleep(durasi + 1.5)  # sengaja lewat batas waktu + toleransi 300ms
    try:
        await kirim(p.ws, {"tipe": "jawab", "question_id": soal["id"], "option_id": opsi[0]["id"]})
        ack = await ambil(p.ws, "jawaban_diterima", batas=BATAS_WS)
        p.jawaban_per_soal[idx_soal] = {"aksi": "jawab_telat", "ok": ack.get("ok"), "pesan": ack.get("pesan")}
    except Exception as e:
        p.jawaban_per_soal[idx_soal] = {"aksi": "error_telat", "pesan": str(e)}


async def jalankan_peserta_untuk_soal(p: Peserta, soal: dict, opsi: list[dict], idx_soal: int, durasi: int):
    if p.pergi_permanen or p.ws is None:
        return
    try:
        # Watchdog keras: tiap perilaku_* sendiri sudah dibatasi lewat ambil()/kirim(),
        # tapi dibungkus timeout keras lagi di sini supaya SATU peserta yang entah
        # kenapa macet tidak bisa menggantung seluruh ronde (asyncio.gather di
        # jalankan_satu_soal menunggu SEMUA peserta selesai).
        async with asyncio.timeout(durasi + 30):
            if p.peran_trouble == "keluar_permanen_setelah_q3" and idx_soal > 2:
                return
            if p.peran_trouble == "late_submit" and p.soal_untuk_telat == idx_soal:
                await perilaku_late_submit(p, soal, opsi, idx_soal, durasi)
            elif p.peran_trouble == "disconnect_mid_answer":
                await perilaku_disconnect_mid_answer(p, soal, opsi, idx_soal, durasi)
            elif p.peran_trouble == "countdown_disconnect":
                await perilaku_countdown_disconnect(p, soal, opsi, idx_soal, durasi)
            elif p.peran_trouble == "double_submit":
                await perilaku_double_submit(p, soal, opsi, idx_soal, durasi)
            else:
                await perilaku_normal(p, soal, opsi, idx_soal, durasi)
    except Exception as e:
        p.jawaban_per_soal[idx_soal] = {"aksi": "error_tak_terduga", "pesan": str(e) or type(e).__name__}

    if p.peran_trouble == "keluar_permanen_setelah_q3" and idx_soal == 2:
        await p.putus()
        p.pergi_permanen = True


async def jalankan_satu_soal(presenter, peserta_aktif: list[Peserta], soal: dict, idx_soal: int, durasi: int,
                              klik_dobel: bool = False):
    print(f"\n--- Soal {idx_soal + 1}: '{soal['teks']}' (durasi {durasi}s, {len(peserta_aktif)} peserta terhubung) ---")
    opsi = soal["opsi"]  # ground truth dari saat dibuat (punya is_benar), dipakai peserta simulasi

    if klik_dobel:
        info("presenter 'klik dobel' saat mengaktifkan soal ini (simulasi ketidaksengajaan)")
        await asyncio.gather(
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{KODE}/aktifkan/{soal['id']}"),
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{KODE}/aktifkan/{soal['id']}"),
        )
    else:
        await asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{KODE}/aktifkan/{soal['id']}")

    # Presenter menunggu countdown selesai BERSAMAAN dengan aksi peserta (termasuk
    # yang sengaja diskoneksi di jendela countdown) — bukan berurutan, supaya
    # skenario countdown_disconnect benar-benar mendarat di jendelanya.
    mulai = time.monotonic()
    buka_presenter, _ = await asyncio.gather(
        ambil(presenter, "pertanyaan_dibuka", batas=BATAS_WS),
        asyncio.gather(*(jalankan_peserta_untuk_soal(p, soal, opsi, idx_soal, durasi) for p in peserta_aktif)),
    )
    opsi_presenter = buka_presenter["pertanyaan"]["opsi"]
    cek(f"soal {idx_soal + 1} terbuka di presenter dengan 4 opsi", len(opsi_presenter) == 4, str(opsi_presenter))
    durasi_interaksi = time.monotonic() - mulai
    info(f"semua interaksi peserta untuk soal {idx_soal + 1} selesai dalam {durasi_interaksi:.1f}s")

    # Tunggu soal ditutup (timer server), pantau berapa kali presenter menerima
    # broadcast 'hasil' selama itu untuk memastikan throttling tetap jalan di skala ini.
    jumlah_broadcast = 0
    tutup = None
    akhir = time.monotonic() + durasi + 10
    while time.monotonic() < akhir:
        try:
            async with asyncio.timeout(max(0.5, akhir - time.monotonic())):
                pesan = json.loads(await presenter.recv())
        except asyncio.TimeoutError:
            break
        if pesan.get("tipe") == "hasil":
            jumlah_broadcast += 1
        elif pesan.get("tipe") == "pertanyaan_ditutup":
            tutup = pesan
            break

    cek(f"soal {idx_soal + 1} ditutup otomatis oleh timer", tutup is not None and tutup.get("alasan") == "timer",
        str(tutup.get("alasan") if tutup else "tidak ada pesan tutup"))
    cek(f"broadcast hasil soal {idx_soal + 1} ter-throttle (bukan 1 update per jawaban)",
        jumlah_broadcast < 30, f"{jumlah_broadcast} update untuk ~{len(peserta_aktif)} peserta")

    if tutup is not None:
        total = tutup["hasil"]["total_jawaban"]
        info(f"total jawaban tercatat presenter untuk soal {idx_soal + 1}: {total}")
        lb = tutup.get("leaderboard")
        if lb:
            urutan_poin = [b["poin"] for b in lb["baris"]]
            cek(f"leaderboard soal {idx_soal + 1} terurut turun (bukan acak)",
                urutan_poin == sorted(urutan_poin, reverse=True), str(urutan_poin[:10]))

    return tutup


def validasi_hasil_trouble(peserta_list: list[Peserta]):
    """Bandingkan aksi yang sengaja disimulasikan vs hasil sungguhan dari server —
    inilah deteksi bug yang sesungguhnya, bukan cuma 'skrip selesai tanpa exception'."""
    print("\n--- Validasi perilaku trouble vs ekspektasi ---")

    telat = [p for p in peserta_list if p.peran_trouble == "late_submit"]
    hasil_telat = [p.jawaban_per_soal.get(p.soal_untuk_telat, {}) for p in telat]
    ok_ditolak = sum(1 for h in hasil_telat if h.get("aksi") == "jawab_telat" and h.get("ok") is False)
    cek("SEMUA jawaban yang sengaja telat (lewat durasi+toleransi) ditolak server",
        ok_ditolak == len(telat), f"{ok_ditolak}/{len(telat)} ditolak — sisanya: {hasil_telat}")

    dobel = [p for p in peserta_list if p.peran_trouble == "double_submit"]
    hasil_dobel = [v for p in dobel for v in p.jawaban_per_soal.values() if v.get("aksi") == "double_submit"]
    ok_dobel = sum(1 for h in hasil_dobel if h.get("ok_pertama") and h.get("ok_kedua") is False)
    cek("SEMUA percobaan jawab dobel: yang pertama diterima, yang kedua ditolak",
        ok_dobel == len(hasil_dobel), f"{ok_dobel}/{len(hasil_dobel)} sesuai ekspektasi")

    diskon = [p for p in peserta_list if p.peran_trouble == "disconnect_mid_answer"]
    hasil_diskon = [v for p in diskon for v in p.jawaban_per_soal.values()]
    gagal_diskon = [h for h in hasil_diskon if h.get("aksi") != "reconnect_lalu_jawab" or not h.get("ok")]
    cek("peserta yang putus-lalu-sambung tetap berhasil menjawab",
        len(gagal_diskon) == 0, f"{len(gagal_diskon)} gagal dari {len(hasil_diskon)}: {gagal_diskon[:5]}")

    cd = [p for p in peserta_list if p.peran_trouble == "countdown_disconnect"]
    hasil_cd = [v for p in cd for v in p.jawaban_per_soal.values()]
    gagal_cd = [h for h in hasil_cd if not h.get("ok") or not h.get("opsi_lengkap", True)]
    cek("peserta yang putus SAAT countdown lalu sambung tetap dapat soal & bisa jawab",
        len(gagal_cd) == 0, f"{len(gagal_cd)} gagal dari {len(hasil_cd)}: {gagal_cd[:5]}")

    keluar = [p for p in peserta_list if p.peran_trouble == "keluar_permanen_setelah_q3"]
    cek("peserta yang keluar permanen setelah soal 3 memang tidak lagi tercatat menjawab soal 4-5",
        all(3 not in p.jawaban_per_soal and 4 not in p.jawaban_per_soal for p in keluar),
        str([p.jawaban_per_soal for p in keluar if 3 in p.jawaban_per_soal or 4 in p.jawaban_per_soal]))


async def utama():
    global KODE
    print(f"Simulasi acara nyata di {BASIS} — target {JUMLAH_TARGET} peserta, 5 soal quiz")

    sesi = panggil("POST", "/api/admin/sesi", {"judul": "Simulasi Acara Nyata", "mode": "quiz"})
    KODE = sesi["kode_sesi"]
    print(f"Sesi dibuat: {KODE}")

    soal_list = buat_pertanyaan_quiz(KODE, 5)
    cek("5 soal quiz berhasil dibuat", len(soal_list) == 5)

    jumlah_awal = round(JUMLAH_TARGET * 0.95)
    jumlah_telat = JUMLAH_TARGET - jumlah_awal

    peran_awal = bagi_trouble(jumlah_awal)
    peserta_awal = [Peserta(i, f"Peserta{i:03d}", peran_awal[i]) for i in range(jumlah_awal)]
    for p in peserta_awal:
        if p.peran_trouble == "late_submit":
            p.soal_untuk_telat = random.randint(0, 4)
        if p.peran_trouble == "diam_satu_soal":
            p.soal_untuk_diam = random.randint(0, 4)

    peserta_telat = [
        Peserta(jumlah_awal + i, f"PesertaTelatGabung{i:03d}", "normal") for i in range(jumlah_telat)
    ]

    print(f"\n--- Gelombang gabung: {jumlah_awal} peserta awal (per {GELOMBANG_KONEKSI}) ---")
    await gabung_semua(peserta_awal)
    cek(f"{jumlah_awal} peserta awal berhasil gabung", all(p.token for p in peserta_awal))

    await uji_nickname_bentrok([p.nickname for p in peserta_awal[:20]])

    print(f"\n--- Membuka {jumlah_awal} koneksi WebSocket peserta (per gelombang {GELOMBANG_KONEKSI}) ---")
    for mulai in range(0, len(peserta_awal), GELOMBANG_KONEKSI):
        bagian = peserta_awal[mulai:mulai + GELOMBANG_KONEKSI]
        await asyncio.gather(*(p.sambung() for p in bagian))
    print(f"  {sum(1 for p in peserta_awal if p.ws is not None)} socket aktif")

    presenter = await websockets.connect(ws_url(f"/ws/present/{KODE}"), open_timeout=30)
    await ambil(presenter, "state", batas=BATAS_WS)

    # Jadwal peserta yang baru gabung DI TENGAH acara (setelah soal ke-2, 3, 4, 5 dibuka),
    # mensimulasikan orang yang baru scan QR belakangan.
    jadwal_telat = {}
    sisa = list(peserta_telat)
    for idx_soal_pemicu in (1, 2, 3, 4):
        if not sisa:
            break
        n = max(1, len(peserta_telat) // 4)
        jadwal_telat[idx_soal_pemicu] = sisa[:n]
        sisa = sisa[n:]
    if sisa:
        jadwal_telat.setdefault(4, []).extend(sisa)

    peserta_semua = list(peserta_awal)
    presenter_refresh_dilakukan = False

    for idx in range(5):
        soal = soal_list[idx]
        durasi = [15, 15, 15, 18, 18][idx]
        peserta_aktif = [p for p in peserta_semua if p.ws is not None and not p.pergi_permanen]

        try:
            async with asyncio.timeout(durasi + 90):
                tutup = await jalankan_satu_soal(presenter, peserta_aktif, soal, idx, durasi, klik_dobel=(idx == 2))
        except asyncio.TimeoutError:
            cek(f"soal {idx + 1} selesai dalam batas waktu wajar (watchdog {durasi + 90}s)", False,
                "TIMEOUT — kemungkinan ada koneksi yang macet tanpa timeout, atau server macet total")
            tutup = None

        if idx == 1 and not presenter_refresh_dilakukan:
            info("presenter 'refresh browser' (reconnect socket) di tengah acara")
            await presenter.close()
            await asyncio.sleep(0.5)
            presenter = await websockets.connect(ws_url(f"/ws/present/{KODE}"), open_timeout=30)
            state = json.loads(await presenter.recv())
            cek("presenter yang refresh dapat leaderboard sementara yang benar",
                state.get("leaderboard") is not None, str(state.get("leaderboard", {}).get("total_partisipan")))
            presenter_refresh_dilakukan = True

        # Peserta yang baru gabung di tengah acara, tepat setelah soal ini ditutup.
        baru = jadwal_telat.get(idx, [])
        if baru:
            print(f"\n--- {len(baru)} peserta baru gabung di tengah acara (setelah soal {idx + 1}) ---")
            hasil = await asyncio.gather(*(
                asyncio.to_thread(panggil_status, "POST", f"/api/gabung/{KODE}", {"nickname": p.nickname})
                for p in baru
            ))
            for p, (status, h) in zip(baru, hasil):
                if status == 201 or status == 200:
                    p.token = h["token"]
                    p.participant_id = h["participant_id"]
            gagal_gabung = [p.nickname for p, (s, _) in zip(baru, hasil) if s not in (200, 201)]
            cek("semua peserta telat berhasil gabung di tengah acara",
                len(gagal_gabung) == 0, str(gagal_gabung))
            await asyncio.gather(*(p.sambung() for p in baru if p.token))
            peserta_semua.extend(baru)

    print("\n--- Menutup sesi & mengambil podium akhir ---")
    peserta_online_sebelum_akhir = [p for p in peserta_semua if p.ws is not None]

    async def dengarkan_selesai(p: Peserta):
        try:
            return await ambil(p.ws, "sesi_selesai", batas=BATAS_WS)
        except Exception as e:
            return {"error": str(e)}

    hasil_akhiri, hasil_selesai_presenter = await asyncio.gather(
        asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{KODE}/akhiri"),
        ambil(presenter, "sesi_selesai", batas=BATAS_WS),
    )
    podium_presenter = hasil_selesai_presenter.get("leaderboard")
    cek("presenter dapat podium akhir", podium_presenter is not None)
    if podium_presenter:
        cek("podium max 3 di posisi 1-3", len(podium_presenter["podium"]) <= 3)
        cek("total_partisipan podium masuk akal (mendekati total yang gabung)",
            podium_presenter["total_partisipan"] >= round(JUMLAH_TARGET * 0.9),
            f"{podium_presenter['total_partisipan']} vs target {JUMLAH_TARGET}")
        top = podium_presenter["podium"][0] if podium_presenter["podium"] else None
        info(f"juara 1: {top}")

    # Ambil podium personalisasi dari beberapa sample peserta yang masih online.
    sample = random.sample(peserta_online_sebelum_akhir, min(10, len(peserta_online_sebelum_akhir)))
    hasil_sample = await asyncio.gather(*(dengarkan_selesai(p) for p in sample))
    gagal_sample = [h for h in hasil_sample if "error" in h or h.get("leaderboard") is None]
    cek("sample peserta yang masih online dapat podium personalisasi masing-masing",
        len(gagal_sample) == 0, f"{len(gagal_sample)}/{len(sample)} gagal: {gagal_sample[:3]}")
    for h in hasil_sample:
        if h.get("leaderboard") and h["leaderboard"].get("peringkat_saya") is None:
            info("PERHATIAN: ada peserta yang jawab tapi peringkat_saya None di podium personalnya")

    validasi_hasil_trouble(peserta_semua)

    print("\n--- Export Excel dengan skala penuh ---")
    isi = panggil("GET", f"/api/admin/sesi/{KODE}/export.xlsx")
    cek("export Excel berhasil diunduh untuk skala penuh",
        isinstance(isi, bytes) and isi[:2] == b"PK" and len(isi) > 8000, f"{len(isi)} byte")

    await asyncio.gather(*(p.putus() for p in peserta_semua))
    try:
        await asyncio.wait_for(presenter.close(), timeout=5)
    except Exception:
        pass

    print(f"\n{'=' * 60}")
    if gagal == 0:
        print(f"SEMUA UJI LULUS — simulasi {JUMLAH_TARGET} peserta / 5 soal / full flow di {BASIS}")
    else:
        print(f"{gagal} UJI GAGAL — kemungkinan bug ditemukan:")
        for t in temuan:
            print(f"  - {t}")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(utama()))
