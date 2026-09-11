"""Uji skenario edge case yang tidak tercakup tools/uji_alur.py.

Jalankan ke server (lokal atau Render sungguhan):
    .venv/Scripts/python.exe tools/uji_edge_case.py https://nama-app.onrender.com

Skenario yang diuji (semua otomatis kecuali #6):
    1. Reconnect tepat di tengah countdown 3 detik
    2. Klik "Soal Berikutnya"/aktifkan dobel cepat (race condition generasi soal)
    3. Dua sesi (Survey + Quiz) berjalan bersamaan, state tidak boleh bocor silang
    4. Gambar besar (~1.9MB dan ~2.6MB) di pertanyaan — cek batas sisi server
    5. Nickname sama dikirim nyaris bersamaan oleh 2 "device" (race constraint DB)
    6. Presenter reconnect di tengah sesi aktif (restart instance sungguhan di
       Render perlu aksi manual di dashboard — lihat pesan saat skrip jalan)
    7. Partisipan putus koneksi sebelum soal ditutup, lalu balik setelah ditutup

Ditulis mandiri (bukan pytest) supaya bisa langsung diarahkan ke URL Render,
seperti tools/uji_alur.py.
"""

import asyncio
import base64
import json
import os
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import websockets

BASIS = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
LOKAL = BASIS.startswith("http://127.0.0.1") or BASIS.startswith("http://localhost")
BATAS_WS = 20 if not LOKAL else 8
gagal = 0


def cek(nama: str, kondisi: bool, detail: str = "") -> None:
    global gagal
    if kondisi:
        print(f"  OK   {nama}")
    else:
        gagal += 1
        print(f"  GAGAL {nama} {detail}")


def panggil(metode: str, jalur: str, muatan=None):
    data = json.dumps(muatan).encode() if muatan is not None else None
    req = Request(BASIS + jalur, data=data, method=metode, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as resp:
        isi = resp.read()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return json.loads(isi)
        return isi


def panggil_status(metode: str, jalur: str, muatan=None):
    """Sama seperti panggil(), tapi mengembalikan (status_code, body_json_atau_None)."""
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


async def ambil_semua(ws, tipe, jendela=2.5):
    """Kumpulkan SEMUA pesan bertipe tertentu yang datang dalam jendela waktu tertentu."""
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


def buat_sesi_mc(mode: str, judul: str, durasi=5):
    sesi = panggil("POST", "/api/admin/sesi", {"judul": judul, "mode": mode})
    kode = sesi["kode_sesi"]
    opsi = [{"teks": "A", "is_benar": True}, {"teks": "B"}, {"teks": "C"}, {"teks": "D"}]
    if mode != "quiz":
        opsi = [{"teks": "A"}, {"teks": "B"}, {"teks": "C"}]
    q = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": f"Soal {judul}", "durasi_detik": durasi, "opsi": opsi,
    })
    q2 = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": f"Soal ke-2 {judul}", "durasi_detik": durasi, "opsi": opsi,
    })
    return kode, q, q2


# ---------------------------------------------------------------------------
# 1. Reconnect tepat di tengah countdown 3 detik
# ---------------------------------------------------------------------------

async def uji_reconnect_saat_countdown():
    print("\n[1] Reconnect tepat di tengah countdown 3 detik")
    kode, q1, _ = buat_sesi_mc("quiz", "Countdown", durasi=6)
    peserta = panggil("POST", f"/api/gabung/{kode}", {"nickname": "PesertaCountdown"})

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        ws = await websockets.connect(ws_url(f"/ws/play/{kode}?token={peserta['token']}"))
        await ambil(ws, "state")

        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}")
        # Presenter harus lihat hitung_mundur dulu, BUKAN pertanyaan_dibuka.
        cd_presenter = await ambil(presenter, "hitung_mundur")
        cek("presenter menerima hitung_mundur", cd_presenter["detik"] == 3, str(cd_presenter))

        # Putuskan & sambung ulang koneksi partisipan SEBELUM countdown (3 detik) selesai.
        await ws.close()
        await asyncio.sleep(0.8)
        ws2 = await websockets.connect(ws_url(f"/ws/play/{kode}?token={peserta['token']}"))
        state_awal = json.loads(await ws2.recv())
        cek("state awal saat reconnect = hitung_mundur (bukan soal dibuka lebih awal)",
            state_awal.get("tipe") == "hitung_mundur", str(state_awal))
        cek("payload countdown tidak bocorkan opsi jawaban",
            "opsi" not in state_awal.get("pertanyaan", {}), str(state_awal.get("pertanyaan")))

        buka = await ambil(ws2, "pertanyaan_dibuka", batas=BATAS_WS)
        cek("soal tetap terbuka normal setelah reconnect", buka["pertanyaan"]["id"] == q1["id"])
        cek("opsi baru muncul SETELAH countdown selesai, bukan sebelumnya",
            len(buka["pertanyaan"]["opsi"]) == 4, str(buka["pertanyaan"]["opsi"]))

        opsi = buka["pertanyaan"]["opsi"]
        await ws2.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": opsi[0]["id"]}))
        ack = await ambil(ws2, "jawaban_diterima")
        cek("jawaban tetap bisa masuk setelah reconnect mid-countdown", ack["ok"], str(ack))

        await ws2.close()
    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


# ---------------------------------------------------------------------------
# 2. Klik "Soal Berikutnya"/aktifkan dobel cepat
# ---------------------------------------------------------------------------

async def uji_klik_dobel():
    print('\n[2] Klik aktifkan soal dobel cepat (race condition generasi)')
    kode, q1, q2 = buat_sesi_mc("quiz", "KlikDobel", durasi=8)
    peserta = panggil("POST", f"/api/gabung/{kode}", {"nickname": "PesertaDobel"})

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        ws = await websockets.connect(ws_url(f"/ws/play/{kode}?token={peserta['token']}"))
        await ambil(ws, "state")

        # Dua klik "aktifkan" pada soal yang SAMA, nyaris bersamaan (simulasi
        # double-click presenter) — dikirim lewat thread supaya sungguh paralel
        # di level jaringan, bukan cuma berurutan dalam satu event loop.
        await asyncio.gather(
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}"),
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}"),
        )

        dibuka_partisipan = await ambil_semua(ws, "pertanyaan_dibuka", jendela=6)
        cek("partisipan cuma terima SATU pertanyaan_dibuka meski diklik dobel",
            len(dibuka_partisipan) == 1, f"dapat {len(dibuka_partisipan)}")

        dibuka_presenter = await ambil_semua(presenter, "pertanyaan_dibuka", jendela=1)
        cek("presenter juga cuma SATU pertanyaan_dibuka",
            len(dibuka_presenter) == 1, f"dapat {len(dibuka_presenter)}")

        # Soal harus tetap bisa dijawab normal setelah race ini (tidak macet).
        opsi = dibuka_partisipan[0]["pertanyaan"]["opsi"]
        await ws.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": opsi[0]["id"]}))
        ack = await ambil(ws, "jawaban_diterima")
        cek("soal tetap bisa dijawab setelah race aktifkan dobel", ack["ok"], str(ack))

        # Sekarang uji dobel klik "berikutnya" (dua soal BERBEDA diaktifkan nyaris
        # bersamaan) — hasil akhir harus konsisten satu soal aktif, bukan tercampur.
        r1, r2 = await asyncio.gather(
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{kode}/berikutnya"),
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{kode}/berikutnya"),
        )
        await asyncio.sleep(4.5)
        runtime = panggil("GET", f"/api/admin/sesi/{kode}")
        cek("soal aktif akhir tetap salah satu ID yang valid (tidak korup)",
            runtime["pertanyaan_aktif_id"] in (q1["id"], q2["id"], None), str(runtime["pertanyaan_aktif_id"]))

        await ws.close()
    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


# ---------------------------------------------------------------------------
# 3. Banyak sesi (Survey + Quiz) berjalan bersamaan
# ---------------------------------------------------------------------------

async def uji_multi_sesi():
    print("\n[3] Survey Mode dan Quiz Mode berjalan bersamaan, state tidak boleh bocor silang")
    kode_a, qa, _ = buat_sesi_mc("survey", "MultiA")
    kode_b, qb, _ = buat_sesi_mc("quiz", "MultiB", durasi=10)

    peserta_a = [panggil("POST", f"/api/gabung/{kode_a}", {}) for _ in range(4)]
    peserta_b = [panggil("POST", f"/api/gabung/{kode_b}", {"nickname": f"B{i}"}) for i in range(3)]

    async with websockets.connect(ws_url(f"/ws/present/{kode_a}")) as pres_a, \
            websockets.connect(ws_url(f"/ws/present/{kode_b}")) as pres_b:
        await ambil(pres_a, "state")
        await ambil(pres_b, "state")

        ws_a = [await websockets.connect(ws_url(f"/ws/play/{kode_a}?token={p['token']}")) for p in peserta_a]
        ws_b = [await websockets.connect(ws_url(f"/ws/play/{kode_b}?token={p['token']}")) for p in peserta_b]
        for ws in ws_a + ws_b:
            await ambil(ws, "state")

        # Buka soal di kedua sesi HAMPIR bersamaan.
        await asyncio.gather(
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{kode_a}/aktifkan/{qa['id']}"),
            asyncio.to_thread(panggil, "POST", f"/api/admin/sesi/{kode_b}/aktifkan/{qb['id']}"),
        )
        buka_a = await ambil(pres_a, "pertanyaan_dibuka", batas=BATAS_WS)
        buka_b = await ambil(pres_b, "pertanyaan_dibuka", batas=BATAS_WS)
        cek("sesi A dapat soal miliknya sendiri", buka_a["pertanyaan"]["id"] == qa["id"])
        cek("sesi B dapat soal miliknya sendiri", buka_b["pertanyaan"]["id"] == qb["id"])
        cek("sesi A (survey) tidak bertimer", buka_a["pertanyaan"]["sisa_ms"] is None)
        cek("sesi B (quiz) bertimer", buka_b["pertanyaan"]["sisa_ms"] is not None)

        opsi_a = buka_a["pertanyaan"]["opsi"]
        opsi_b = buka_b["pertanyaan"]["opsi"]
        for ws in ws_a:
            await ambil(ws, "pertanyaan_dibuka")
        for ws in ws_b:
            await ambil(ws, "pertanyaan_dibuka")

        # 4 jawaban di sesi A, 3 jawaban di sesi B, dikirim bersamaan.
        async def jawab_a(ws):
            await ws.send(json.dumps({"tipe": "jawab", "question_id": qa["id"], "option_id": opsi_a[0]["id"]}))
            return await ambil(ws, "jawaban_diterima")

        async def jawab_b(ws):
            await ws.send(json.dumps({"tipe": "jawab", "question_id": qb["id"], "option_id": opsi_b[0]["id"]}))
            return await ambil(ws, "jawaban_diterima")

        await asyncio.gather(*(jawab_a(w) for w in ws_a), *(jawab_b(w) for w in ws_b))

        hasil_a = await ambil(pres_a, "hasil", batas=4)
        while hasil_a["hasil"]["total_jawaban"] < 4:
            hasil_a = await ambil(pres_a, "hasil", batas=4)
        cek("agregat sesi A cuma 4 (bukan tercampur 7 dari sesi B)",
            hasil_a["hasil"]["total_jawaban"] == 4, str(hasil_a["hasil"]["total_jawaban"]))

        hasil_b = await ambil(pres_b, "hasil", batas=4)
        while hasil_b["hasil"]["total_jawaban"] < 3:
            hasil_b = await ambil(pres_b, "hasil", batas=4)
        cek("agregat sesi B cuma 3 (bukan tercampur dari sesi A)",
            hasil_b["hasil"]["total_jawaban"] == 3, str(hasil_b["hasil"]["total_jawaban"]))

        for ws in ws_a + ws_b:
            await ws.close()

    panggil("POST", f"/api/admin/sesi/{kode_a}/akhiri")
    panggil("POST", f"/api/admin/sesi/{kode_b}/akhiri")


# ---------------------------------------------------------------------------
# 4. Gambar besar di pertanyaan
# ---------------------------------------------------------------------------

def _data_uri_kira_kira(ukuran_akhir_byte: int) -> str:
    """Bangun data URI base64 palsu (bukan gambar asli — server tidak mem-parse
    isinya, cuma cek prefix) dengan panjang string kira-kira sebesar target."""
    prefix = "data:image/png;base64,"
    raw_len = int((ukuran_akhir_byte - len(prefix)) * 3 / 4)
    return prefix + base64.b64encode(os.urandom(raw_len)).decode()


async def uji_gambar_besar():
    print("\n[4] Gambar besar (~1.9MB dan ~2.6MB) di pertanyaan")
    sesi = panggil("POST", "/api/admin/sesi", {"judul": "UjiGambar", "mode": "survey"})
    kode = sesi["kode_sesi"]

    gambar_1_9mb = _data_uri_kira_kira(1_900_000)
    status, body = panggil_status("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": "Soal dengan gambar 1.9MB", "gambar": gambar_1_9mb,
        "opsi": [{"teks": "A"}, {"teks": "B"}],
    })
    detail_ringkas = str(body)[:200] if not (status == 201 and isinstance(body, dict)) else ""
    cek("gambar ~1.9MB (di bawah batas UI 2MB) diterima server", status == 201, f"status {status} {detail_ringkas}")
    if status == 201:
        balik = panggil("GET", f"/api/admin/sesi/{kode}")
        gambar_tersimpan = next((q["gambar"] for q in balik["pertanyaan"] if q["id"] == body["id"]), None)
        cek("gambar tersimpan utuh (panjang string sama)",
            gambar_tersimpan is not None and len(gambar_tersimpan) == len(gambar_1_9mb),
            f"{len(gambar_tersimpan or '')} vs {len(gambar_1_9mb)}")

    gambar_2_6mb = _data_uri_kira_kira(2_600_000)
    status2, body2 = panggil_status("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": "Soal dengan gambar 2.6MB", "gambar": gambar_2_6mb,
        "opsi": [{"teks": "A"}, {"teks": "B"}],
    })
    # Ini BUKAN uji pass/fail semata — dicek dan dilaporkan apa adanya, karena
    # per catatan README/CHANGELOG, batas 2MB itu HANYA di form UI (client),
    # belum ada validasi ukuran di server (_validasi_pertanyaan cuma cek prefix
    # "data:image/"). Kalau ini lolos, artinya endpoint API bisa dipakai untuk
    # menyimpan gambar di atas batas yang dimaksudkan UI.
    if status2 == 201:
        print(f"  INFO gambar ~2.6MB (DI ATAS batas UI 2MB) tetap DITERIMA server (status {status2}) — "
              "tidak ada validasi ukuran sisi server, cuma format prefix. Sesuai catatan README "
              "('belum ada kompresi/resize di sisi server'), bukan bug baru, tapi tetap risiko "
              "ukuran DB/row membengkak kalau banyak dipakai.")
    else:
        print(f"  INFO gambar ~2.6MB ditolak server (status {status2}): {str(body2)[:200]}")

    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


# ---------------------------------------------------------------------------
# 5. Nickname sama dikirim nyaris bersamaan oleh 2 device
# ---------------------------------------------------------------------------

async def uji_nickname_race():
    print("\n[5] Nickname sama dikirim nyaris bersamaan oleh 2 device")
    sesi = panggil("POST", "/api/admin/sesi", {"judul": "UjiNicknameRace", "mode": "quiz"})
    kode = sesi["kode_sesi"]

    # Dua device beda kapitalisasi/spasi, dikirim betul-betul paralel via thread
    # terpisah supaya keduanya lolos pre-check SELECT sebelum salah satu commit
    # duluan — ini yang justru menguji unique constraint DB, bukan cuma
    # pre-check di kode aplikasi (skenario yang beda dari uji_alur.py yang
    # mengirim berurutan).
    hasil = await asyncio.gather(
        asyncio.to_thread(panggil_status, "POST", f"/api/gabung/{kode}", {"nickname": "Dedi Kurniawan"}),
        asyncio.to_thread(panggil_status, "POST", f"/api/gabung/{kode}", {"nickname": " dedi kurniawan "}),
        asyncio.to_thread(panggil_status, "POST", f"/api/gabung/{kode}", {"nickname": "DEDI KURNIAWAN"}),
    )
    kode_status = [h[0] for h in hasil]
    sukses = sum(1 for c in kode_status if c == 200)
    ditolak = sum(1 for c in kode_status if c == 409)
    cek("tepat SATU dari 3 device dengan nickname sama yang berhasil gabung",
        sukses == 1, f"status: {kode_status}")
    cek("sisanya (2) ditolak 409, bukan malah lolos jadi peserta ganda",
        ditolak == 2, f"status: {kode_status}")

    daftar = panggil("GET", f"/api/admin/sesi/{kode}")
    cek("cuma ADA SATU baris partisipan tersimpan di database",
        daftar["jumlah_partisipan"] == 1, str(daftar["jumlah_partisipan"]))

    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


# ---------------------------------------------------------------------------
# 6. Presenter reconnect di tengah sesi aktif (+ catatan restart instance)
# ---------------------------------------------------------------------------

async def uji_presenter_reconnect():
    print("\n[6] Presenter reconnect di tengah sesi aktif")
    kode, q1, _ = buat_sesi_mc("quiz", "PresenterReconnect", durasi=15)
    peserta = panggil("POST", f"/api/gabung/{kode}", {"nickname": "PesertaPresenterReconnect"})

    presenter1 = await websockets.connect(ws_url(f"/ws/present/{kode}"))
    await ambil(presenter1, "state")
    ws = await websockets.connect(ws_url(f"/ws/play/{kode}?token={peserta['token']}"))
    await ambil(ws, "state")

    panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}")
    buka = await ambil(presenter1, "pertanyaan_dibuka", batas=BATAS_WS)
    await ambil(ws, "pertanyaan_dibuka", batas=BATAS_WS)
    opsi = buka["pertanyaan"]["opsi"]
    await ws.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": opsi[0]["id"]}))
    await ambil(ws, "jawaban_diterima")

    # Simulasikan presenter refresh browser: putuskan lalu sambung ulang socket
    # presenter tanpa mengganggu soal yang sedang berjalan.
    await presenter1.close()
    await asyncio.sleep(0.5)
    presenter2 = await websockets.connect(ws_url(f"/ws/present/{kode}"))
    state = json.loads(await presenter2.recv())
    cek("presenter yang reconnect dapat soal yang masih sama & masih berjalan",
        state.get("pertanyaan", {}).get("id") == q1["id"], str(state.get("pertanyaan")))
    cek("presenter yang reconnect tetap lihat 1 jawaban yang sudah masuk sebelumnya",
        state.get("hasil", {}).get("total_jawaban") == 1, str(state.get("hasil")))

    panggil("POST", f"/api/admin/sesi/{kode}/tutup")
    await ambil(presenter2, "pertanyaan_ditutup", batas=BATAS_WS)
    await presenter2.close()
    await ws.close()
    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")

    print("  CATATAN: ini menguji reconnect socket presenter, BUKAN restart")
    print("  instance Render sungguhan (memory RuntimeSesi dibuang total lalu")
    print("  dibangun ulang dari database lewat app/realtime/manajer.py). Uji")
    print("  itu perlu aksi manual di dashboard Render (restart service) dan")
    print("  tidak bisa dipicu dari skrip ini tanpa akses dashboard/API key")
    print("  Render kamu. Jalankan tools/uji_edge_case.py dengan argumen kedua")
    print("  'restart' untuk mode uji berbantuan manual (lihat instruksi saat")
    print("  dijalankan).")


async def uji_restart_manual():
    """Mode berbantuan manual: skrip menjaga satu soal quiz tetap terbuka lalu
    menunggu sambil kamu restart service-nya sendiri lewat dashboard Render,
    supaya app/realtime/manajer.py sungguh-sungguh diuji jalur bangun-ulang-
    dari-DB-nya, bukan cuma reconnect socket biasa."""
    print("\n[6b] Uji restart instance sungguhan (mode manual)")
    kode, q1, _ = buat_sesi_mc("quiz", "RestartManual", durasi=180)
    peserta = [panggil("POST", f"/api/gabung/{kode}", {"nickname": f"Restart{i}"}) for i in range(3)]

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        soket = []
        for p in peserta:
            w = await websockets.connect(ws_url(f"/ws/play/{kode}?token={p['token']}"))
            await ambil(w, "state")
            soket.append(w)

        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}")
        buka = await ambil(presenter, "pertanyaan_dibuka", batas=BATAS_WS)
        opsi = buka["pertanyaan"]["opsi"]
        for w in soket:
            await ambil(w, "pertanyaan_dibuka", batas=BATAS_WS)
        # Cuma 2 dari 3 yang menjawab duluan — sisanya harus tetap valid setelah restart.
        for w in soket[:2]:
            await w.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": opsi[0]["id"]}))
            await ambil(w, "jawaban_diterima")
        for w in soket:
            await w.close()

    print(f"\n  Sesi aktif dibuat: kode {kode}, soal '{q1['teks']}' sedang terbuka")
    print("  (durasi timer 180 detik), 2 dari 3 peserta sudah menjawab opsi A.")
    print(f"  SEKARANG: buka dashboard Render kamu, pilih service live-polling,")
    print("  lalu klik 'Manual Deploy' > 'Restart service' (atau redeploy tanpa")
    print("  cache). Skrip ini menunggu 60 detik supaya kamu sempat klik, lalu")
    print("  otomatis cek apakah state (jawaban, soal aktif, timer) selamat.")
    for sisa in range(60, 0, -10):
        print(f"  ...menunggu {sisa} detik lagi")
        await asyncio.sleep(10)

    print("  Mengecek state via API admin + WebSocket baru setelah (semoga) restart...")
    runtime = panggil("GET", f"/api/admin/sesi/{kode}")
    cek("sesi masih aktif setelah restart", runtime["status"] == "aktif", str(runtime["status"]))
    cek("soal aktif masih tercatat di DB", runtime["pertanyaan_aktif_id"] == q1["id"],
        str(runtime["pertanyaan_aktif_id"]))

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        state = json.loads(await presenter.recv())
        cek("presenter baru dapat soal yang sama persis setelah restart (dibangun ulang dari DB)",
            state.get("pertanyaan", {}).get("id") == q1["id"], str(state.get("pertanyaan")))
        cek("2 jawaban yang sudah masuk sebelum restart tidak hilang",
            state.get("hasil", {}).get("total_jawaban") == 2, str(state.get("hasil")))
        cek("timer sisa waktu tetap masuk akal (bukan reset ke penuh / ke nol aneh)",
            0 < state.get("pertanyaan", {}).get("sisa_ms", 0) <= 180_000,
            str(state.get("pertanyaan", {}).get("sisa_ms")))

        panggil("POST", f"/api/admin/sesi/{kode}/tutup")
        await ambil(presenter, "pertanyaan_ditutup", batas=BATAS_WS)

    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


# ---------------------------------------------------------------------------
# 7. Partisipan putus sebelum soal ditutup, balik setelah ditutup
# ---------------------------------------------------------------------------

async def uji_peserta_putus_lalu_balik():
    print("\n[7] Partisipan putus koneksi sebelum soal ditutup, balik setelah ditutup")
    kode, q1, _ = buat_sesi_mc("quiz", "PutusBalik", durasi=5)
    p_jawab = panggil("POST", f"/api/gabung/{kode}", {"nickname": "PutusSetelahJawab"})
    p_tanpa = panggil("POST", f"/api/gabung/{kode}", {"nickname": "PutusTanpaJawab"})

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        ws_a = await websockets.connect(ws_url(f"/ws/play/{kode}?token={p_jawab['token']}"))
        ws_b = await websockets.connect(ws_url(f"/ws/play/{kode}?token={p_tanpa['token']}"))
        await ambil(ws_a, "state")
        await ambil(ws_b, "state")

        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}")
        buka = await ambil(presenter, "pertanyaan_dibuka", batas=BATAS_WS)
        opsi = buka["pertanyaan"]["opsi"]
        await ambil(ws_a, "pertanyaan_dibuka", batas=BATAS_WS)
        await ambil(ws_b, "pertanyaan_dibuka", batas=BATAS_WS)

        # A menjawab lalu putus koneksi. B putus TANPA menjawab sama sekali.
        await ws_a.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": opsi[0]["id"]}))
        await ambil(ws_a, "jawaban_diterima")
        await ws_a.close()
        await ws_b.close()

        # Tunggu soal ditutup otomatis oleh timer server (tanpa ada yang online).
        tutup_presenter = await ambil(presenter, "pertanyaan_ditutup", batas=BATAS_WS + 8)
        cek("soal tetap ditutup timer meski kedua partisipan sedang offline",
            tutup_presenter["alasan"] == "timer", str(tutup_presenter["alasan"]))

    # Sekarang keduanya balik (reconnect) SETELAH soal ditutup.
    ws_a2 = await websockets.connect(ws_url(f"/ws/play/{kode}?token={p_jawab['token']}"))
    state_a = json.loads(await ws_a2.recv())
    cek("peserta yg SUDAH jawab, balik setelah ditutup, dapat pribadi.menjawab=True",
        state_a.get("pribadi", {}).get("menjawab") is True, str(state_a.get("pribadi")))
    cek("poin peserta yg sudah jawab tercatat (bukan 0 karena dianggap ga jawab)",
        state_a.get("pribadi", {}).get("poin", 0) > 0, str(state_a.get("pribadi")))

    ws_b2 = await websockets.connect(ws_url(f"/ws/play/{kode}?token={p_tanpa['token']}"))
    state_b = json.loads(await ws_b2.recv())
    cek("peserta yg TIDAK jawab, balik setelah ditutup, dapat pribadi.menjawab=False",
        state_b.get("pribadi", {}).get("menjawab") is False, str(state_b.get("pribadi")))
    cek("peserta yang tidak jawab dapat 0 poin", state_b.get("pribadi", {}).get("poin") == 0,
        str(state_b.get("pribadi")))

    await ws_a2.close()
    await ws_b2.close()
    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


async def utama():
    print(f"Menguji edge case di {BASIS}")
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    if mode == "restart":
        await uji_restart_manual()
    else:
        await uji_reconnect_saat_countdown()
        await uji_klik_dobel()
        await uji_multi_sesi()
        await uji_gambar_besar()
        await uji_nickname_race()
        await uji_presenter_reconnect()
        await uji_peserta_putus_lalu_balik()
    print(f"\n{'SEMUA UJI LULUS' if gagal == 0 else f'{gagal} UJI GAGAL'}")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(utama()))
