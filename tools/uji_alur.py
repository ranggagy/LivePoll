"""Uji alur end-to-end: buat sesi, join, jawab, tutup soal, cek hasil & export.

Jalankan setelah server hidup:
    .venv/Scripts/python.exe tools/uji_alur.py http://127.0.0.1:8010

Argumen kedua (opsional) mengatur jumlah partisipan pada uji beban:
    .venv/Scripts/python.exe tools/uji_alur.py https://nama-app.onrender.com 200
"""

import asyncio
import json
import sys

import websockets
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASIS = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
JUMLAH_BEBAN = int(sys.argv[2]) if len(sys.argv) > 2 else 150
# Server jauh (Render) punya latensi jaringan yang tidak ada di localhost,
# jadi ambang ack dilonggarkan supaya yang dilaporkan gagal benar-benar
# masalah aplikasi, bukan sekadar jarak ke Singapura.
BATAS_ACK_DETIK = 2.0 if BASIS.startswith("http://127.0.0.1") or BASIS.startswith("http://localhost") else 5.0
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
    with urlopen(req) as resp:
        isi = resp.read()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return json.loads(isi)
        return isi


def ws_url(jalur: str) -> str:
    u = urlparse(BASIS)
    skema = "wss" if u.scheme == "https" else "ws"
    return f"{skema}://{u.netloc}{jalur}"


async def ambil(ws, tipe, batas=6.0):
    """Tunggu pesan bertipe tertentu, abaikan pesan lain."""
    async with asyncio.timeout(batas):
        while True:
            pesan = json.loads(await ws.recv())
            if pesan.get("tipe") == tipe:
                return pesan


async def uji_survey():
    print("\n[1] Survey Mode — Multiple Choice + Word Cloud + Rating")
    sesi = panggil("POST", "/api/admin/sesi", {"judul": "Uji Survey", "mode": "survey"})
    kode = sesi["kode_sesi"]
    cek("sesi dibuat", len(kode) == 6, kode)

    q_mc = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": "Area mana yang perlu ditingkatkan?",
        "opsi": [{"teks": "Proses kerja"}, {"teks": "Kolaborasi"}, {"teks": "Tools"}],
    })
    q_wc = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "word_cloud", "teks": "Satu kata untuk tahun ini?", "opsi": [],
    })
    q_rt = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "rating", "teks": "Seberapa puas?", "rating_maks": 5, "opsi": [],
    })
    cek("3 pertanyaan dibuat", all(q["id"] for q in (q_mc, q_wc, q_rt)))

    peserta = [panggil("POST", f"/api/gabung/{kode}", {}) for _ in range(5)]
    cek("5 partisipan anonim gabung", all(p["ok"] for p in peserta))

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        soket_peserta = []
        for p in peserta:
            ws = await websockets.connect(ws_url(f"/ws/play/{kode}?token={p['token']}"))
            await ambil(ws, "state")
            soket_peserta.append(ws)

        # --- Multiple Choice ---
        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q_mc['id']}")
        buka = await ambil(presenter, "pertanyaan_dibuka")
        cek("presenter menerima soal MC", buka["pertanyaan"]["tipe"] == "mc")
        # Survey Mode tidak boleh punya batas waktu — presenter yang menutup soal.
        cek("soal survey tanpa timer", buka["pertanyaan"]["sisa_ms"] is None,
            str(buka["pertanyaan"]["sisa_ms"]))

        opsi = buka["pertanyaan"]["opsi"]
        for i, ws in enumerate(soket_peserta):
            await ambil(ws, "pertanyaan_dibuka")
            await ws.send(json.dumps({"tipe": "jawab", "question_id": q_mc["id"],
                                      "option_id": opsi[0 if i < 3 else 1]["id"]}))
            ack = await ambil(ws, "jawaban_diterima")
            cek(f"jawaban peserta #{i+1} diterima", ack["ok"], ack.get("pesan", ""))

        # Jawaban kedua dari peserta yang sama harus ditolak (kunci sekali klik).
        await soket_peserta[0].send(json.dumps({"tipe": "jawab", "question_id": q_mc["id"],
                                                "option_id": opsi[2]["id"]}))
        ack2 = await ambil(soket_peserta[0], "jawaban_diterima")
        cek("jawaban dobel ditolak", ack2["ok"] is False and ack2.get("sudah") is True)

        hasil = await ambil(presenter, "hasil", batas=4)
        while hasil["hasil"]["total_jawaban"] < 5:
            hasil = await ambil(presenter, "hasil", batas=4)
        agg = hasil["hasil"]
        cek("agregat MC benar (3 vs 2)",
            agg["opsi"][0]["jumlah"] == 3 and agg["opsi"][1]["jumlah"] == 2,
            str([o["jumlah"] for o in agg["opsi"]]))
        cek("persen MC benar", agg["opsi"][0]["persen"] == 60.0, str(agg["opsi"][0]["persen"]))

        panggil("POST", f"/api/admin/sesi/{kode}/tutup")
        tutup = await ambil(presenter, "pertanyaan_ditutup")
        cek("soal MC ditutup manual", tutup["hasil"]["ditutup"] is True)

        # Soal survey yang dibuka lama tetap menerima jawaban (regresi: dulu
        # durasi_detik default 20 ikut dipakai sebagai batas waktu).
        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q_mc['id']}")
        await ambil(presenter, "pertanyaan_dibuka")
        await ambil(soket_peserta[0], "pertanyaan_dibuka")
        runtime = panggil("GET", f"/api/admin/sesi/{kode}")
        await asyncio.sleep(1.2)
        await soket_peserta[0].send(json.dumps({"tipe": "jawab", "question_id": q_mc["id"],
                                                "option_id": opsi[0]["id"]}))
        ack_lambat = await ambil(soket_peserta[0], "jawaban_diterima")
        cek("jawaban survey tetap diterima tanpa batas timer", ack_lambat["ok"],
            str(ack_lambat.get("pesan")))
        panggil("POST", f"/api/admin/sesi/{kode}/tutup")
        await ambil(presenter, "pertanyaan_ditutup")
        for ws in soket_peserta[1:]:
            await ambil(ws, "pertanyaan_ditutup")
        await ambil(soket_peserta[0], "pertanyaan_ditutup")

        # --- Word Cloud + moderasi ---
        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q_wc['id']}")
        await ambil(presenter, "pertanyaan_dibuka")
        kata = ["Progresif", "progresif ", "Kolaboratif", "sibuk", "PROGRESIF"]
        for ws, teks in zip(soket_peserta, kata):
            await ambil(ws, "pertanyaan_dibuka")
            await ws.send(json.dumps({"tipe": "jawab", "question_id": q_wc["id"], "teks": teks}))
            ack = await ambil(ws, "jawaban_diterima")
            cek(f"word cloud '{teks.strip()}' masuk antrian", ack["ok"] and ack["menunggu_moderasi"])

        mod = await ambil(presenter, "moderasi", batas=4)
        while mod["jumlah"] < 5:
            mod = await ambil(presenter, "moderasi", batas=4)
        cek("5 jawaban menunggu approval", mod["jumlah"] == 5, str(mod["jumlah"]))

        hasil_sebelum = panggil("GET", f"/api/admin/sesi/{kode}")
        cek("sesi masih bisa dibaca saat moderasi", hasil_sebelum["kode_sesi"] == kode)

        panggil("POST", f"/api/admin/sesi/{kode}/moderasi-semua", {"aksi": "approve"})
        hasil = await ambil(presenter, "hasil", batas=4)
        while not hasil["hasil"]["kata"]:
            hasil = await ambil(presenter, "hasil", batas=4)
        peta = {k["teks"].strip().lower(): k["jumlah"] for k in hasil["hasil"]["kata"]}
        cek("varian 'Progresif/progresif /PROGRESIF' digabung jadi 3",
            peta.get("progresif") == 3, str(peta))

        panggil("POST", f"/api/admin/sesi/{kode}/tutup")
        await ambil(presenter, "pertanyaan_ditutup")

        # --- Rating ---
        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q_rt['id']}")
        await ambil(presenter, "pertanyaan_dibuka")
        for i, ws in enumerate(soket_peserta):
            await ambil(ws, "pertanyaan_dibuka")
            await ws.send(json.dumps({"tipe": "jawab", "question_id": q_rt["id"], "nilai": (i % 5) + 1}))
            await ambil(ws, "jawaban_diterima")
        hasil = await ambil(presenter, "hasil", batas=4)
        while hasil["hasil"]["total_jawaban"] < 5:
            hasil = await ambil(presenter, "hasil", batas=4)
        cek("rata-rata rating = 3.0", hasil["hasil"]["rating"]["rata"] == 3.0,
            str(hasil["hasil"]["rating"]["rata"]))

        # Rating di luar rentang harus ditolak.
        await soket_peserta[0].send(json.dumps({"tipe": "jawab", "question_id": q_rt["id"], "nilai": 99}))
        ack = await ambil(soket_peserta[0], "jawaban_diterima")
        cek("rating di luar rentang ditolak", ack["ok"] is False)

        for ws in soket_peserta:
            await ws.close()

    isi = panggil("GET", f"/api/admin/sesi/{kode}/export.xlsx")
    cek("export Excel terunduh", isinstance(isi, bytes) and isi[:2] == b"PK" and len(isi) > 4000,
        f"{len(isi)} byte")

    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")
    info = panggil("GET", f"/api/sesi/{kode}/info")
    cek("sesi selesai tidak bisa dijoin", info["ada"] is False)
    return kode


async def uji_quiz():
    print("\n[2] Quiz Mode — nickname unik, timer server, skor kecepatan, leaderboard")
    sesi = panggil("POST", "/api/admin/sesi", {"judul": "Uji Quiz", "mode": "quiz"})
    kode = sesi["kode_sesi"]

    q1 = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": "Apa singkatan dari LBUT?", "durasi_detik": 6,
        "opsi": [{"teks": "Laporan Bulanan Umum Terbatas", "is_benar": True},
                 {"teks": "Laporan Berkala Unit Transaksi"},
                 {"teks": "Laporan Bank Umum Terintegrasi"},
                 {"teks": "Laporan Bulanan Uang Tunai"}],
    })
    cek("soal quiz dibuat dengan 1 jawaban benar",
        sum(1 for o in q1["opsi"] if o["is_benar"]) == 1)

    try:
        panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan",
                {"tipe": "word_cloud", "teks": "Tidak boleh", "opsi": []})
        cek("word cloud ditolak di Quiz Mode", False)
    except Exception as e:
        cek("word cloud ditolak di Quiz Mode", "400" in str(e), str(e))

    try:
        panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan",
                {"tipe": "mc", "teks": "Tanpa kunci jawaban",
                 "opsi": [{"teks": "A"}, {"teks": "B"}]})
        cek("MC tanpa jawaban benar ditolak di Quiz Mode", False)
    except Exception as e:
        cek("MC tanpa jawaban benar ditolak di Quiz Mode", "400" in str(e), str(e))

    budi = panggil("POST", f"/api/gabung/{kode}", {"nickname": "Budi"})
    rina = panggil("POST", f"/api/gabung/{kode}", {"nickname": "RinaFinance"})
    cek("2 partisipan quiz gabung", budi["ok"] and rina["ok"])

    try:
        panggil("POST", f"/api/gabung/{kode}", {"nickname": "  budi "})
        cek("nickname duplikat (beda kapital/spasi) ditolak", False)
    except Exception as e:
        cek("nickname duplikat (beda kapital/spasi) ditolak", "409" in str(e), str(e))

    resume = panggil("POST", f"/api/gabung/{kode}", {"token": budi["token"]})
    cek("resume dengan token lama tidak bikin peserta baru",
        resume["resume"] is True and resume["participant_id"] == budi["participant_id"])

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        ws_budi = await websockets.connect(ws_url(f"/ws/play/{kode}?token={budi['token']}"))
        ws_rina = await websockets.connect(ws_url(f"/ws/play/{kode}?token={rina['token']}"))
        await ambil(ws_budi, "state")
        await ambil(ws_rina, "state")

        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q1['id']}")
        buka = await ambil(presenter, "pertanyaan_dibuka")
        cek("timer server terkirim ke presenter",
            4000 < buka["pertanyaan"]["sisa_ms"] <= 6000, str(buka["pertanyaan"]["sisa_ms"]))

        soal_budi = await ambil(ws_budi, "pertanyaan_dibuka")
        await ambil(ws_rina, "pertanyaan_dibuka")
        cek("kunci jawaban tidak dibocorkan ke partisipan",
            all("benar" not in o for o in soal_budi["pertanyaan"]["opsi"]))

        opsi = buka["pertanyaan"]["opsi"]
        benar = next(o for o in opsi if o["benar"])
        salah = next(o for o in opsi if not o["benar"])

        # Budi menjawab benar & cepat, Rina menjawab benar tapi lebih lambat.
        await ws_budi.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": benar["id"]}))
        await ambil(ws_budi, "jawaban_diterima")
        await asyncio.sleep(2.0)
        await ws_rina.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": benar["id"]}))
        await ambil(ws_rina, "jawaban_diterima")

        tutup_budi = await ambil(ws_budi, "pertanyaan_ditutup", batas=12)
        tutup_rina = await ambil(ws_rina, "pertanyaan_ditutup", batas=12)
        cek("soal ditutup otomatis oleh timer server", tutup_budi["alasan"] == "timer",
            tutup_budi["alasan"])
        poin_budi = tutup_budi["pribadi"]["poin"]
        poin_rina = tutup_rina["pribadi"]["poin"]
        cek("kedua jawaban benar", tutup_budi["pribadi"]["benar"] and tutup_rina["pribadi"]["benar"])
        cek(f"yang lebih cepat dapat poin lebih besar ({poin_budi} > {poin_rina})", poin_budi > poin_rina)
        cek("poin dalam rentang 500-1000", 500 <= poin_rina <= poin_budi <= 1000,
            f"{poin_rina}..{poin_budi}")

        papan = tutup_budi["leaderboard"]["baris"]
        cek("leaderboard urut berdasarkan poin",
            papan[0]["nickname"] == "Budi" and papan[0]["peringkat"] == 1, str(papan))

        # Jawaban setelah soal ditutup harus ditolak.
        await ws_budi.send(json.dumps({"tipe": "jawab", "question_id": q1["id"], "option_id": salah["id"]}))
        ack = await ambil(ws_budi, "jawaban_diterima")
        cek("jawaban setelah waktu habis ditolak", ack["ok"] is False, str(ack.get("pesan")))

        # Simulasi refresh HP: reconnect dengan token yang sama harus dapat state penuh.
        await ws_budi.close()
        ws_budi2 = await websockets.connect(ws_url(f"/ws/play/{kode}?token={budi['token']}"))
        state = await ambil(ws_budi2, "state")
        cek("reconnect memulihkan total poin", state["total_poin"] == poin_budi, str(state.get("total_poin")))
        cek("reconnect memulihkan nickname", state.get("nickname") == "Budi")

        await ws_budi2.close()
        await ws_rina.close()

    isi = panggil("GET", f"/api/admin/sesi/{kode}/export.xlsx")
    cek("export quiz (dengan leaderboard) terunduh", isinstance(isi, bytes) and len(isi) > 4000)
    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")
    return kode


async def uji_beban(jumlah=JUMLAH_BEBAN):
    print(f"\n[3] Uji beban — {jumlah} partisipan menjawab bersamaan")
    sesi = panggil("POST", "/api/admin/sesi", {"judul": "Uji Beban", "mode": "quiz"})
    kode = sesi["kode_sesi"]
    q = panggil("POST", f"/api/admin/sesi/{kode}/pertanyaan", {
        "tipe": "mc", "teks": "Beban?", "durasi_detik": 25,
        "opsi": [{"teks": "A", "is_benar": True}, {"teks": "B"}, {"teks": "C"}, {"teks": "D"}],
    })

    token = []
    for i in range(jumlah):
        token.append(panggil("POST", f"/api/gabung/{kode}", {"nickname": f"peserta{i:03d}"})["token"])

    async with websockets.connect(ws_url(f"/ws/present/{kode}")) as presenter:
        await ambil(presenter, "state")
        sockets = await asyncio.gather(
            *(websockets.connect(ws_url(f"/ws/play/{kode}?token={t}"), max_queue=64) for t in token)
        )
        await asyncio.gather(*(ambil(ws, "state") for ws in sockets))
        print(f"  info  {len(sockets)} koneksi WebSocket aktif")

        panggil("POST", f"/api/admin/sesi/{kode}/aktifkan/{q['id']}")
        buka = await ambil(presenter, "pertanyaan_dibuka")
        opsi = buka["pertanyaan"]["opsi"]
        await asyncio.gather(*(ambil(ws, "pertanyaan_dibuka") for ws in sockets))

        mulai = asyncio.get_event_loop().time()

        async def jawab(i, ws):
            await ws.send(json.dumps({"tipe": "jawab", "question_id": q["id"],
                                      "option_id": opsi[i % 4]["id"]}))
            return await ambil(ws, "jawaban_diterima", batas=20)

        hasil = await asyncio.gather(*(jawab(i, ws) for i, ws in enumerate(sockets)))
        durasi = asyncio.get_event_loop().time() - mulai
        diterima = sum(1 for h in hasil if h["ok"])
        print(f"  info  {diterima}/{jumlah} jawaban di-ack dalam {durasi*1000:.0f} ms")
        cek("semua jawaban diterima server", diterima == jumlah, f"{diterima}/{jumlah}")
        cek(f"ack di bawah {BATAS_ACK_DETIK:.0f} detik", durasi < BATAS_ACK_DETIK, f"{durasi:.2f}s")

        # Hitung berapa kali presenter menerima broadcast (harus di-throttle, bukan 150x).
        agg = await ambil(presenter, "hasil", batas=6)
        putaran = 1
        while agg["hasil"]["total_jawaban"] < jumlah:
            agg = await ambil(presenter, "hasil", batas=6)
            putaran += 1
        cek("agregat presenter lengkap", agg["hasil"]["total_jawaban"] == jumlah,
            str(agg["hasil"]["total_jawaban"]))
        cek(f"broadcast di-throttle ({putaran} update, bukan {jumlah})", putaran < 20, str(putaran))

        panggil("POST", f"/api/admin/sesi/{kode}/tutup")
        await ambil(presenter, "pertanyaan_ditutup", batas=15)
        await asyncio.gather(*(ws.close() for ws in sockets))

    isi = panggil("GET", f"/api/admin/sesi/{kode}/export.xlsx")
    cek(f"export {jumlah} jawaban berhasil", isinstance(isi, bytes) and len(isi) > 8000, f"{len(isi)} byte")
    panggil("POST", f"/api/admin/sesi/{kode}/akhiri")


async def utama():
    print(f"Menguji {BASIS}")
    await uji_survey()
    await uji_quiz()
    await uji_beban()
    print(f"\n{'SEMUA UJI LULUS' if gagal == 0 else f'{gagal} UJI GAGAL'}")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(utama()))
