"""State sesi di memory: agregasi jawaban, timer server-side, dan skor kuis.

Prinsip yang dipegang di sini:
- Jawaban diagregasi di memory dulu, broadcast ke presenter di-throttle
  (default 500ms) supaya 300 orang menjawab bersamaan tidak membanjiri socket.
- Penulisan ke database dibatch di background, tidak memblokir balasan ke partisipan.
- Timer soal dihitung dari waktu server, bukan dari HP partisipan.
"""

import asyncio
import logging
import time

from sqlalchemy import delete, select, update

from ..config import FAKTOR_PENGURANGAN, INTERVAL_BROADCAST, IS_SQLITE, TOLERANSI_TELAT_MS
from ..database import BuatSesiDB
from ..models import (
    MOD_APPROVED,
    MOD_PENDING,
    MOD_REJECTED,
    MODE_QUIZ,
    STATUS_Q_BERJALAN,
    STATUS_Q_SELESAI,
    STATUS_SESI_SELESAI,
    TIPE_MC,
    TIPE_RATING,
    TIPE_WORD_CLOUD,
    Jawaban,
    Partisipan,
    Pertanyaan,
    Sesi,
)
from ..utils import ke_utc, normalisasi_kata, sekarang
from .hub import PERAN_PARTISIPAN, PERAN_PRESENTER, hub

log = logging.getLogger("livepoll.runtime")

TOTAL_BARIS_TABEL = 7  # + 3 podium = maksimal 10 nama tampil di layar sesi selesai


def bangun_podium(urut: list[dict], participant_id: int | None = None, total_tabel: int = TOTAL_BARIS_TABEL) -> dict:
    """Podium peringkat 1-3 + tabel ringkas di bawahnya, maksimal 10 nama total.

    `urut` sudah terurut dari peringkat 1. Kalau `participant_id` berada di
    luar jendela default (peringkat 4 s.d. 3+total_tabel), tabel digeser
    supaya berakhir 2 peringkat di bawah dia — jadi peserta mana pun tetap
    melihat posisinya sendiri, bukan cuma top-10 generik yang sama untuk semua.
    """
    total = len(urut)
    podium = [{**urut[i], "peringkat": i + 1} for i in range(min(3, total))]
    peringkat_saya = next((i + 1 for i, b in enumerate(urut) if b["participant_id"] == participant_id), None)

    akhir = min(total, 3 + total_tabel)
    if peringkat_saya is not None and peringkat_saya > akhir:
        akhir = min(total, peringkat_saya + 2)
    awal = max(4, akhir - total_tabel + 1)

    tabel = [{**urut[i], "peringkat": i + 1} for i in range(awal - 1, akhir)] if akhir >= awal else []

    return {
        "podium": podium,
        "tabel": tabel,
        "total_partisipan": total,
        "peringkat_saya": peringkat_saya,
    }


def hitung_poin(benar: bool, waktu_ms: int, durasi_detik: int, poin_maksimal: int) -> int:
    """Skor gaya Kahoot: makin cepat menjawab benar, makin besar poinnya."""
    if not benar:
        return 0
    total_ms = max(durasi_detik, 1) * 1000
    rasio = min(max(waktu_ms / total_ms, 0.0), 1.0)
    poin = poin_maksimal * (1 - rasio * FAKTOR_PENGURANGAN)
    poin_minimum = int(poin_maksimal * (1 - FAKTOR_PENGURANGAN))
    return max(int(round(poin)), poin_minimum)


def _insert_upsert():
    """Ambil konstruktor INSERT yang mendukung ON CONFLICT sesuai dialek DB."""
    if IS_SQLITE:
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return insert


class StatePertanyaan:
    """Agregat jawaban untuk satu pertanyaan yang sedang/pernah berjalan."""

    def __init__(self, q: Pertanyaan, urutan_ke: int, total_soal: int, bertimer: bool = False) -> None:
        self.id = q.id
        self.tipe = q.tipe
        self.teks = q.teks
        self.gambar = q.gambar
        # Hanya Quiz Mode yang punya batas waktu; soal survey ditutup manual
        # oleh presenter, jadi tidak boleh kedaluwarsa sendiri.
        self.bertimer = bertimer
        self.durasi = q.durasi_detik
        self.poin_maksimal = q.poin_maksimal
        self.rating_maks = q.rating_maks
        self.urutan_ke = urutan_ke
        self.total_soal = total_soal
        self.opsi = [{"id": o.id, "teks": o.teks, "is_benar": bool(o.is_benar)} for o in q.daftar_opsi]

        dibuka = ke_utc(q.dibuka_at)
        self.dibuka_epoch: float | None = dibuka.timestamp() if dibuka else None
        self.ditutup: bool = q.status == STATUS_Q_SELESAI

        self.hitung_opsi: dict[int, int] = {o["id"]: 0 for o in self.opsi}
        self.kata: dict[str, dict] = {}
        self.pending: dict[int, dict] = {}
        self.hitung_rating: dict[int, int] = {}
        self.jawaban: dict[int, dict] = {}

    # -- perhitungan waktu -------------------------------------------------

    @property
    def batas_epoch(self) -> float | None:
        """Kapan soal otomatis ditutup (hanya untuk soal bertimer)."""
        if not self.bertimer or self.dibuka_epoch is None or not self.durasi:
            return None
        return self.dibuka_epoch + self.durasi

    def sisa_ms(self) -> int | None:
        batas = self.batas_epoch
        if batas is None:
            return None
        return max(0, int((batas - time.time()) * 1000))

    def waktu_jawab_ms(self) -> int:
        if self.dibuka_epoch is None:
            return 0
        return max(0, int((time.time() - self.dibuka_epoch) * 1000))

    # -- pembaruan agregat -------------------------------------------------

    def catat(self, participant_id: int, data: dict) -> None:
        """Masukkan satu jawaban ke agregat memory."""
        self.jawaban[participant_id] = data
        if self.tipe == TIPE_MC and data.get("option_id") is not None:
            self.hitung_opsi[data["option_id"]] = self.hitung_opsi.get(data["option_id"], 0) + 1
        elif self.tipe == TIPE_RATING and data.get("nilai_rating") is not None:
            nilai = int(data["nilai_rating"])
            self.hitung_rating[nilai] = self.hitung_rating.get(nilai, 0) + 1
        elif self.tipe == TIPE_WORD_CLOUD:
            self.pending[participant_id] = {"participant_id": participant_id, "teks": data.get("teks") or ""}

    def setujui_kata(self, participant_id: int) -> bool:
        """Pindahkan satu jawaban word cloud dari antrian ke word cloud live."""
        item = self.pending.pop(participant_id, None)
        if item is None:
            return False
        kunci = normalisasi_kata(item["teks"])
        if not kunci:
            return False
        entri = self.kata.setdefault(kunci, {"teks": item["teks"].strip(), "jumlah": 0})
        entri["jumlah"] += 1
        data = self.jawaban.get(participant_id)
        if data:
            data["status_moderasi"] = MOD_APPROVED
        return True

    def tolak_kata(self, participant_id: int) -> bool:
        item = self.pending.pop(participant_id, None)
        if item is None:
            return False
        data = self.jawaban.get(participant_id)
        if data:
            data["status_moderasi"] = MOD_REJECTED
        return True

    @property
    def total_jawaban(self) -> int:
        return len(self.jawaban)

    # -- payload untuk client ---------------------------------------------

    def payload_pertanyaan(self, untuk_presenter: bool = False) -> dict:
        buka_kunci = self.ditutup or untuk_presenter
        opsi = [
            {"id": o["id"], "teks": o["teks"], **({"benar": o["is_benar"]} if buka_kunci else {})}
            for o in self.opsi
        ]
        return {
            "id": self.id,
            "tipe": self.tipe,
            "teks": self.teks,
            "gambar": self.gambar,
            "urutan_ke": self.urutan_ke,
            "total_soal": self.total_soal,
            "durasi": self.durasi if self.bertimer else None,
            "sisa_ms": self.sisa_ms(),
            "rating_maks": self.rating_maks,
            "ditutup": self.ditutup,
            "opsi": opsi,
        }

    def payload_hasil(self) -> dict:
        total = self.total_jawaban or 0
        opsi = []
        for o in self.opsi:
            jumlah = self.hitung_opsi.get(o["id"], 0)
            opsi.append(
                {
                    "id": o["id"],
                    "teks": o["teks"],
                    "jumlah": jumlah,
                    "persen": round(jumlah * 100 / total, 1) if total else 0.0,
                    "benar": o["is_benar"] if self.ditutup else None,
                }
            )
        kata = sorted(self.kata.values(), key=lambda k: (-k["jumlah"], k["teks"]))[:60]
        total_rating = sum(self.hitung_rating.values())
        jumlah_nilai = sum(n * c for n, c in self.hitung_rating.items())
        rating = {
            "maks": self.rating_maks,
            "rata": round(jumlah_nilai / total_rating, 2) if total_rating else 0.0,
            "distribusi": [
                {"nilai": n, "jumlah": self.hitung_rating.get(n, 0)} for n in range(1, self.rating_maks + 1)
            ],
        }
        return {
            "question_id": self.id,
            "tipe": self.tipe,
            "ditutup": self.ditutup,
            "total_jawaban": total,
            "opsi": opsi,
            "kata": kata,
            "rating": rating,
            "pending": len(self.pending),
        }

    def payload_moderasi(self) -> dict:
        return {
            "question_id": self.id,
            "antrian": [
                {"participant_id": pid, "teks": item["teks"]} for pid, item in list(self.pending.items())[:80]
            ],
            "jumlah": len(self.pending),
        }


class RuntimeSesi:
    """Semua state hidup untuk satu sesi: soal aktif, skor, dan loop broadcast."""

    def __init__(self, sesi: Sesi) -> None:
        self.kode = sesi.kode_sesi
        self.session_id = sesi.id
        self.mode = sesi.mode
        self.judul = sesi.judul
        self.status = sesi.status
        self.total_soal = len(sesi.daftar_pertanyaan)

        self.aktif: StatePertanyaan | None = None
        self.poin_total: dict[int, int] = {}
        self.nama: dict[int, str] = {}

        self._kotor = False
        self._moderasi_kotor = False
        self._antrian_tulis: list[dict] = []
        self._gembok = asyncio.Lock()
        self._task_flush: asyncio.Task | None = None
        self._task_timer: asyncio.Task | None = None

    # -- siklus hidup ------------------------------------------------------

    def mulai_loop(self) -> None:
        if self._task_flush is None or self._task_flush.done():
            self._task_flush = asyncio.create_task(self._loop_flush())

    async def hentikan(self) -> None:
        self._batalkan_timer()
        if self._task_flush and not self._task_flush.done():
            self._task_flush.cancel()
        await self._tulis_antrian()

    def tandai_kotor(self) -> None:
        self._kotor = True

    async def _loop_flush(self) -> None:
        """Loop tunggal: tulis jawaban tertunda ke DB, lalu broadcast bila ada perubahan."""
        while True:
            await asyncio.sleep(INTERVAL_BROADCAST)
            try:
                await self._tulis_antrian()
                if self._kotor:
                    self._kotor = False
                    await self._siarkan_hasil()
                if self._moderasi_kotor:
                    self._moderasi_kotor = False
                    await self._siarkan_moderasi()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Gagal saat flush sesi %s", self.kode)

    # -- persistensi -------------------------------------------------------

    async def _tulis_antrian(self) -> None:
        """Tulis batch jawaban ke DB dengan upsert (aman terhadap retry client)."""
        if not self._antrian_tulis:
            return
        batch, self._antrian_tulis = self._antrian_tulis, []
        insert = _insert_upsert()
        try:
            async with BuatSesiDB() as db:
                stmt = insert(Jawaban).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["question_id", "participant_id"],
                    set_={
                        "option_id": stmt.excluded.option_id,
                        "teks": stmt.excluded.teks,
                        "nilai_rating": stmt.excluded.nilai_rating,
                        "waktu_jawab_ms": stmt.excluded.waktu_jawab_ms,
                        "poin": stmt.excluded.poin,
                        "benar": stmt.excluded.benar,
                        "status_moderasi": stmt.excluded.status_moderasi,
                        "submitted_at": stmt.excluded.submitted_at,
                    },
                )
                await db.execute(stmt)
                await db.commit()
        except Exception:
            log.exception("Gagal menulis %d jawaban sesi %s", len(batch), self.kode)

    # -- broadcast ---------------------------------------------------------

    async def _siarkan_hasil(self) -> None:
        if self.aktif is None:
            return
        await hub.siarkan(
            self.kode,
            {
                "tipe": "hasil",
                "hasil": self.aktif.payload_hasil(),
                "online": hub.jumlah_partisipan_online(self.kode),
            },
            peran=PERAN_PRESENTER,
        )
        # Partisipan cukup tahu berapa banyak yang sudah menjawab.
        await hub.siarkan(
            self.kode,
            {"tipe": "progres", "question_id": self.aktif.id, "total_jawaban": self.aktif.total_jawaban},
            peran=PERAN_PARTISIPAN,
        )

    async def _siarkan_moderasi(self) -> None:
        if self.aktif is None or self.aktif.tipe != TIPE_WORD_CLOUD:
            return
        await hub.siarkan(self.kode, {"tipe": "moderasi", **self.aktif.payload_moderasi()}, peran=PERAN_PRESENTER)

    def leaderboard_terurut(self) -> list[tuple[int, int]]:
        return sorted(self.poin_total.items(), key=lambda x: (-x[1], self.nama.get(x[0], "")))

    def payload_leaderboard(self, batas: int = 12) -> dict:
        urut = self.leaderboard_terurut()
        baris = [
            {"participant_id": pid, "nickname": self.nama.get(pid) or "Anonim", "poin": poin, "peringkat": i + 1}
            for i, (pid, poin) in enumerate(urut[:batas])
        ]
        return {"baris": baris, "total_partisipan": len(self.poin_total)}

    def payload_podium(self, participant_id: int | None = None) -> dict:
        urut = [
            {"participant_id": pid, "nickname": self.nama.get(pid) or "Anonim", "poin": poin}
            for pid, poin in self.leaderboard_terurut()
        ]
        return bangun_podium(urut, participant_id)

    def payload_peserta(self) -> list[dict]:
        """Daftar peserta yang sudah gabung, urutan waktu join — dipakai bubble lobi presenter."""
        return [{"participant_id": pid, "nickname": nama} for pid, nama in self.nama.items()]

    def peringkat_partisipan(self, participant_id: int) -> int | None:
        urut = self.leaderboard_terurut()
        for i, (pid, _) in enumerate(urut):
            if pid == participant_id:
                return i + 1
        return None

    def sekitar_partisipan(self, participant_id: int) -> dict | None:
        """Baris leaderboard di sekitar satu peserta: satu di atas dan satu di bawah."""
        urut = self.leaderboard_terurut()
        idx = next((i for i, (pid, _) in enumerate(urut) if pid == participant_id), None)
        if idx is None:
            return None

        def _baris(i: int) -> dict | None:
            if i < 0 or i >= len(urut):
                return None
            pid, poin = urut[i]
            return {"participant_id": pid, "nickname": self.nama.get(pid) or "Anonim", "poin": poin, "peringkat": i + 1}

        return {
            "atas": _baris(idx - 1),
            "saya": _baris(idx),
            "bawah": _baris(idx + 1),
            "total_partisipan": len(urut),
        }

    def payload_sesi(self) -> dict:
        return {
            "kode": self.kode,
            "judul": self.judul,
            "mode": self.mode,
            "status": self.status,
            "total_soal": self.total_soal,
            "online": hub.jumlah_partisipan_online(self.kode),
        }

    # -- operasi presenter -------------------------------------------------

    async def aktifkan(self, question_id: int) -> dict:
        """Buka satu soal: tutup soal sebelumnya, reset timer, broadcast ke semua."""
        async with self._gembok:
            if self.aktif is not None and not self.aktif.ditutup:
                await self._tutup_internal(siarkan=False)

            async with BuatSesiDB() as db:
                q = await db.get(Pertanyaan, question_id)
                if q is None or q.session_id != self.session_id:
                    return {"ok": False, "pesan": "Pertanyaan tidak ditemukan"}

                semua = (
                    (
                        await db.execute(
                            select(Pertanyaan.id)
                            .where(Pertanyaan.session_id == self.session_id)
                            .order_by(Pertanyaan.urutan, Pertanyaan.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                self.total_soal = len(semua)
                urutan_ke = semua.index(question_id) + 1 if question_id in semua else 1

                q.status = STATUS_Q_BERJALAN
                q.dibuka_at = sekarang()
                q.ditutup_at = None
                # Jawaban lama soal ini dibuang supaya soal benar-benar mulai bersih.
                await db.execute(delete(Jawaban).where(Jawaban.question_id == question_id))
                sesi = await db.get(Sesi, self.session_id)
                if sesi is not None:
                    sesi.pertanyaan_aktif_id = question_id
                await db.commit()
                await db.refresh(q, ["daftar_opsi"])
                self.aktif = StatePertanyaan(
                    q, urutan_ke, self.total_soal, bertimer=self.mode == MODE_QUIZ
                )

        self.mulai_loop()
        self._pasang_timer()
        await hub.siarkan(
            self.kode,
            {
                "tipe": "pertanyaan_dibuka",
                "sesi": self.payload_sesi(),
                "pertanyaan": self.aktif.payload_pertanyaan(),
                "hasil": self.aktif.payload_hasil(),
            },
            peran=PERAN_PARTISIPAN,
        )
        await hub.siarkan(
            self.kode,
            {
                "tipe": "pertanyaan_dibuka",
                "sesi": self.payload_sesi(),
                "pertanyaan": self.aktif.payload_pertanyaan(untuk_presenter=True),
                "hasil": self.aktif.payload_hasil(),
                "moderasi": self.aktif.payload_moderasi() if self.aktif.tipe == TIPE_WORD_CLOUD else None,
            },
            peran=PERAN_PRESENTER,
        )
        return {"ok": True}

    def _batalkan_timer(self) -> None:
        """Batalkan task timer, kecuali kalau kode ini justru berjalan di dalamnya.

        Tanpa penjagaan ini, penutupan yang dipicu timer akan membatalkan dirinya
        sendiri dan berhenti di tengah jalan (soal tidak pernah benar-benar ditutup).
        """
        task = self._task_timer
        if task is None or task.done():
            return
        try:
            berjalan = asyncio.current_task()
        except RuntimeError:
            berjalan = None
        if task is berjalan:
            return
        task.cancel()
        self._task_timer = None

    def _pasang_timer(self) -> None:
        """Pasang penutup otomatis berbasis waktu server (hanya untuk soal bertimer)."""
        self._batalkan_timer()
        if self.aktif is None or not self.aktif.bertimer:
            return

        sisa = self.aktif.sisa_ms()
        if sisa is None:
            return
        question_id = self.aktif.id

        async def _tunggu_lalu_tutup() -> None:
            try:
                await asyncio.sleep(sisa / 1000)
                if self.aktif is not None and self.aktif.id == question_id and not self.aktif.ditutup:
                    await self.tutup(alasan="timer")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Timer sesi %s gagal", self.kode)

        self._task_timer = asyncio.create_task(_tunggu_lalu_tutup())

    async def tutup(self, alasan: str = "manual") -> dict:
        async with self._gembok:
            return await self._tutup_internal(alasan=alasan)

    async def _tutup_internal(self, alasan: str = "manual", siarkan: bool = True) -> dict:
        if self.aktif is None or self.aktif.ditutup:
            return {"ok": False, "pesan": "Tidak ada soal yang sedang berjalan"}

        state = self.aktif
        state.ditutup = True
        self._batalkan_timer()

        # Semua jawaban yang masih tertunda ditulis dulu sebelum menghitung total.
        await self._tulis_antrian()

        naik: dict[int, int] = {}
        if self.mode == MODE_QUIZ:
            for pid, data in state.jawaban.items():
                poin = int(data.get("poin") or 0)
                if poin:
                    naik[pid] = poin
                self.poin_total[pid] = self.poin_total.get(pid, 0) + poin

        async with BuatSesiDB() as db:
            q = await db.get(Pertanyaan, state.id)
            if q is not None:
                q.status = STATUS_Q_SELESAI
                q.ditutup_at = sekarang()
            sesi = await db.get(Sesi, self.session_id)
            if sesi is not None:
                sesi.pertanyaan_aktif_id = None
            for pid, tambahan in naik.items():
                await db.execute(
                    update(Partisipan).where(Partisipan.id == pid).values(total_poin=Partisipan.total_poin + tambahan)
                )
            await db.commit()

        if not siarkan:
            return {"ok": True}

        leaderboard = self.payload_leaderboard() if self.mode == MODE_QUIZ else None
        await hub.siarkan(
            self.kode,
            {
                "tipe": "pertanyaan_ditutup",
                "alasan": alasan,
                "pertanyaan": state.payload_pertanyaan(untuk_presenter=True),
                "hasil": state.payload_hasil(),
                "leaderboard": leaderboard,
            },
            peran=PERAN_PRESENTER,
        )

        # Tiap partisipan menerima hasil pribadinya masing-masing.
        for koneksi in hub.koneksi_sesi(self.kode):
            if koneksi.peran != PERAN_PARTISIPAN or koneksi.participant_id is None:
                continue
            await koneksi.kirim(
                {
                    "tipe": "pertanyaan_ditutup",
                    "alasan": alasan,
                    "pertanyaan": state.payload_pertanyaan(),
                    "hasil": state.payload_hasil() if self.mode != MODE_QUIZ else None,
                    "pribadi": self.hasil_pribadi(koneksi.participant_id),
                    "leaderboard": leaderboard,
                }
            )
        return {"ok": True}

    def hasil_pribadi(self, participant_id: int) -> dict | None:
        if self.aktif is None:
            return None
        data = self.aktif.jawaban.get(participant_id)
        if data is None:
            return {
                "menjawab": False,
                "benar": False,
                "poin": 0,
                "total_poin": self.poin_total.get(participant_id, 0),
                "peringkat": self.peringkat_partisipan(participant_id),
                "sekitar": self.sekitar_partisipan(participant_id),
            }
        return {
            "menjawab": True,
            "benar": bool(data.get("benar")),
            "poin": int(data.get("poin") or 0),
            "option_id": data.get("option_id"),
            "total_poin": self.poin_total.get(participant_id, 0),
            "peringkat": self.peringkat_partisipan(participant_id),
            "sekitar": self.sekitar_partisipan(participant_id),
        }

    async def moderasi(self, participant_id: int, aksi: str) -> bool:
        if self.aktif is None or self.aktif.tipe != TIPE_WORD_CLOUD:
            return False
        ok = self.aktif.setujui_kata(participant_id) if aksi == "approve" else self.aktif.tolak_kata(participant_id)
        if not ok:
            return False
        status = MOD_APPROVED if aksi == "approve" else MOD_REJECTED
        async with BuatSesiDB() as db:
            await db.execute(
                update(Jawaban)
                .where(Jawaban.question_id == self.aktif.id, Jawaban.participant_id == participant_id)
                .values(status_moderasi=status)
            )
            await db.commit()
        self.tandai_kotor()
        self._moderasi_kotor = True
        return True

    async def moderasi_semua(self, aksi: str) -> int:
        if self.aktif is None or self.aktif.tipe != TIPE_WORD_CLOUD:
            return 0
        daftar = list(self.aktif.pending.keys())
        for pid in daftar:
            if aksi == "approve":
                self.aktif.setujui_kata(pid)
            else:
                self.aktif.tolak_kata(pid)
        if daftar:
            status = MOD_APPROVED if aksi == "approve" else MOD_REJECTED
            async with BuatSesiDB() as db:
                await db.execute(
                    update(Jawaban)
                    .where(Jawaban.question_id == self.aktif.id, Jawaban.participant_id.in_(daftar))
                    .values(status_moderasi=status)
                )
                await db.commit()
            self.tandai_kotor()
            self._moderasi_kotor = True
        return len(daftar)

    async def akhiri_sesi(self) -> None:
        if self.aktif is not None and not self.aktif.ditutup:
            await self.tutup(alasan="sesi_berakhir")
        self.status = STATUS_SESI_SELESAI

        if self.mode != MODE_QUIZ:
            await hub.siarkan(self.kode, {"tipe": "sesi_selesai", "leaderboard": None})
            return

        # Presenter (layar besar) melihat podium generik top-10.
        await hub.siarkan(
            self.kode, {"tipe": "sesi_selesai", "leaderboard": self.payload_podium()}, peran=PERAN_PRESENTER
        )
        # Tiap partisipan melihat podium yang sama, tapi tabelnya digeser
        # supaya peringkatnya sendiri selalu ikut tampil.
        for koneksi in hub.koneksi_sesi(self.kode):
            if koneksi.peran != PERAN_PARTISIPAN or koneksi.participant_id is None:
                continue
            await koneksi.kirim(
                {"tipe": "sesi_selesai", "leaderboard": self.payload_podium(koneksi.participant_id)}
            )

    # -- operasi partisipan ------------------------------------------------

    def daftarkan_partisipan(self, participant_id: int, nickname: str | None, total_poin: int = 0) -> None:
        self.nama[participant_id] = nickname or "Anonim"
        self.poin_total.setdefault(participant_id, total_poin)

    async def terima_jawaban(self, participant_id: int, muatan: dict) -> dict:
        """Validasi + catat satu jawaban. Dipanggil dari handler WebSocket."""
        state = self.aktif
        if state is None:
            return {"ok": False, "pesan": "Belum ada soal yang dibuka"}
        if muatan.get("question_id") not in (None, state.id):
            return {"ok": False, "pesan": "Soal sudah berganti"}
        if state.ditutup:
            return {"ok": False, "pesan": "Waktu sudah habis"}
        if participant_id in state.jawaban:
            return {"ok": False, "pesan": "Kamu sudah menjawab soal ini", "sudah": True}

        batas = state.batas_epoch
        if batas is not None and time.time() > batas + TOLERANSI_TELAT_MS / 1000:
            return {"ok": False, "pesan": "Waktu sudah habis"}

        data: dict = {
            "question_id": state.id,
            "participant_id": participant_id,
            "option_id": None,
            "teks": None,
            "nilai_rating": None,
            "waktu_jawab_ms": state.waktu_jawab_ms(),
            "poin": 0,
            "benar": False,
            "status_moderasi": MOD_APPROVED,
            "submitted_at": sekarang(),
        }

        if state.tipe == TIPE_MC:
            try:
                option_id = int(muatan.get("option_id"))
            except (TypeError, ValueError):
                return {"ok": False, "pesan": "Pilihan jawaban tidak valid"}
            cocok = next((o for o in state.opsi if o["id"] == option_id), None)
            if cocok is None:
                return {"ok": False, "pesan": "Pilihan jawaban tidak valid"}
            data["option_id"] = option_id
            data["benar"] = cocok["is_benar"]
            if self.mode == MODE_QUIZ:
                data["poin"] = hitung_poin(
                    cocok["is_benar"], data["waktu_jawab_ms"], state.durasi, state.poin_maksimal
                )
        elif state.tipe == TIPE_WORD_CLOUD:
            teks = (muatan.get("teks") or "").strip()
            if not teks:
                return {"ok": False, "pesan": "Jawaban tidak boleh kosong"}
            data["teks"] = teks[:60]
            data["status_moderasi"] = MOD_PENDING
        elif state.tipe == TIPE_RATING:
            try:
                nilai = int(muatan.get("nilai"))
            except (TypeError, ValueError):
                return {"ok": False, "pesan": "Nilai rating tidak valid"}
            if not 1 <= nilai <= state.rating_maks:
                return {"ok": False, "pesan": "Nilai rating di luar rentang"}
            data["nilai_rating"] = nilai
        else:
            return {"ok": False, "pesan": "Tipe pertanyaan tidak dikenal"}

        state.catat(participant_id, data)
        self._antrian_tulis.append(dict(data))
        self.mulai_loop()
        self.tandai_kotor()
        if state.tipe == TIPE_WORD_CLOUD:
            self._moderasi_kotor = True

        return {
            "ok": True,
            "terkunci": True,
            "menunggu_moderasi": state.tipe == TIPE_WORD_CLOUD,
            "waktu_jawab_ms": data["waktu_jawab_ms"],
        }

    def state_untuk_partisipan(self, participant_id: int) -> dict:
        """State lengkap saat partisipan pertama connect atau reconnect."""
        muatan: dict = {"tipe": "state", "sesi": self.payload_sesi(), "pertanyaan": None}
        if self.mode == MODE_QUIZ:
            muatan["total_poin"] = self.poin_total.get(participant_id, 0)
            muatan["peringkat"] = self.peringkat_partisipan(participant_id)
            muatan["nickname"] = self.nama.get(participant_id)
        if self.aktif is None:
            return muatan
        muatan["pertanyaan"] = self.aktif.payload_pertanyaan()
        jawaban = self.aktif.jawaban.get(participant_id)
        muatan["sudah_menjawab"] = jawaban is not None
        muatan["total_jawaban"] = self.aktif.total_jawaban
        if jawaban is not None:
            muatan["jawaban_saya"] = {
                "option_id": jawaban.get("option_id"),
                "teks": jawaban.get("teks"),
                "nilai_rating": jawaban.get("nilai_rating"),
                "menunggu_moderasi": jawaban.get("status_moderasi") == MOD_PENDING,
            }
        if self.aktif.ditutup:
            muatan["pribadi"] = self.hasil_pribadi(participant_id)
            muatan["hasil"] = self.aktif.payload_hasil() if self.mode != MODE_QUIZ else None
            if self.mode == MODE_QUIZ:
                muatan["leaderboard"] = self.payload_leaderboard()
        return muatan

    def state_untuk_presenter(self) -> dict:
        muatan: dict = {
            "tipe": "state",
            "sesi": self.payload_sesi(),
            "pertanyaan": self.aktif.payload_pertanyaan(untuk_presenter=True) if self.aktif else None,
            "hasil": self.aktif.payload_hasil() if self.aktif else None,
            "leaderboard": self.payload_leaderboard() if self.mode == MODE_QUIZ else None,
        }
        if self.mode == MODE_QUIZ:
            muatan["peserta"] = self.payload_peserta()
        if self.aktif is not None and self.aktif.tipe == TIPE_WORD_CLOUD:
            muatan["moderasi"] = self.aktif.payload_moderasi()
        return muatan
