"""Registry runtime sesi + pemulihan state dari database.

Kalau instance restart (Render free tier bisa sleep/redeploy), state di memory
hilang. Modul ini membangun ulang state sesi dari database saat sesi pertama
kali diakses lagi, jadi presenter maupun partisipan bisa lanjut tanpa kehilangan
jawaban yang sudah masuk.
"""

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..database import BuatSesiDB
from ..models import (
    MOD_APPROVED,
    MOD_PENDING,
    MODE_QUIZ,
    STATUS_SESI_AKTIF,
    TIPE_MC,
    TIPE_RATING,
    TIPE_WORD_CLOUD,
    Jawaban,
    Partisipan,
    Pertanyaan,
    Sesi,
)
from ..utils import normalisasi_kata
from .runtime import RuntimeSesi, StatePertanyaan

log = logging.getLogger("livepoll.manajer")


class ManajerRuntime:
    """Menyimpan satu RuntimeSesi per kode sesi yang sedang dipakai."""

    def __init__(self) -> None:
        self._runtime: dict[str, RuntimeSesi] = {}
        self._gembok = asyncio.Lock()

    async def dapatkan(self, kode: str) -> RuntimeSesi | None:
        """Ambil runtime sesi; bangun ulang dari DB bila belum ada di memory."""
        kode = (kode or "").strip().upper()
        ada = self._runtime.get(kode)
        if ada is not None:
            return ada

        async with self._gembok:
            ada = self._runtime.get(kode)
            if ada is not None:
                return ada
            runtime = await self._bangun_dari_db(kode)
            if runtime is not None:
                self._runtime[kode] = runtime
                runtime.mulai_loop()
            return runtime

    def cache(self, kode: str) -> RuntimeSesi | None:
        return self._runtime.get((kode or "").strip().upper())

    async def buang(self, kode: str) -> None:
        runtime = self._runtime.pop((kode or "").strip().upper(), None)
        if runtime is not None:
            await runtime.hentikan()

    async def hentikan_semua(self) -> None:
        for runtime in list(self._runtime.values()):
            await runtime.hentikan()
        self._runtime.clear()

    async def _bangun_dari_db(self, kode: str) -> RuntimeSesi | None:
        async with BuatSesiDB() as db:
            sesi = (
                await db.execute(
                    select(Sesi)
                    .where(Sesi.kode_sesi == kode, Sesi.status == STATUS_SESI_AKTIF)
                    .options(selectinload(Sesi.daftar_pertanyaan).selectinload(Pertanyaan.daftar_opsi))
                    .order_by(Sesi.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if sesi is None:
                return None

            runtime = RuntimeSesi(sesi)

            # Pulihkan daftar partisipan beserta poinnya.
            peserta = (
                (await db.execute(select(Partisipan).where(Partisipan.session_id == sesi.id))).scalars().all()
            )
            for p in peserta:
                runtime.daftarkan_partisipan(p.id, p.nickname, p.total_poin or 0)

            # Pulihkan soal yang sedang berjalan beserta jawaban yang sudah masuk.
            if sesi.pertanyaan_aktif_id:
                urut = [q.id for q in sesi.daftar_pertanyaan]
                q = next((x for x in sesi.daftar_pertanyaan if x.id == sesi.pertanyaan_aktif_id), None)
                if q is not None:
                    urutan_ke = urut.index(q.id) + 1
                    runtime._generasi_aktif += 1
                    state = StatePertanyaan(
                        q, urutan_ke, len(urut), bertimer=sesi.mode == MODE_QUIZ,
                        generasi=runtime._generasi_aktif,
                    )
                    jawaban = (
                        (await db.execute(select(Jawaban).where(Jawaban.question_id == q.id))).scalars().all()
                    )
                    _pulihkan_agregat(state, jawaban)
                    if state.dibuka_epoch is None:
                        # Instance restart persis di tengah hitung mundur (jendela
                        # sangat sempit) — konteksnya sudah hilang, jadi anggap
                        # soal mulai sekarang daripada macet selamanya menunggu
                        # task yang tidak akan pernah datang lagi.
                        state.dibuka_epoch = time.time()
                    runtime.aktif = state
                    runtime._pasang_timer()

        return runtime


def _pulihkan_agregat(state: StatePertanyaan, jawaban: list[Jawaban]) -> None:
    """Isi ulang agregat memory dari baris jawaban yang tersimpan di DB."""
    for a in jawaban:
        data = {
            "question_id": a.question_id,
            "participant_id": a.participant_id,
            "option_id": a.option_id,
            "teks": a.teks,
            "nilai_rating": a.nilai_rating,
            "waktu_jawab_ms": a.waktu_jawab_ms,
            "poin": a.poin,
            "benar": a.benar,
            "status_moderasi": a.status_moderasi,
            "submitted_at": a.submitted_at,
        }
        state.jawaban[a.participant_id] = data

        if state.tipe == TIPE_MC and a.option_id is not None:
            state.hitung_opsi[a.option_id] = state.hitung_opsi.get(a.option_id, 0) + 1
        elif state.tipe == TIPE_RATING and a.nilai_rating is not None:
            state.hitung_rating[a.nilai_rating] = state.hitung_rating.get(a.nilai_rating, 0) + 1
        elif state.tipe == TIPE_WORD_CLOUD and a.teks:
            if a.status_moderasi == MOD_PENDING:
                state.pending[a.participant_id] = {"participant_id": a.participant_id, "teks": a.teks}
            elif a.status_moderasi == MOD_APPROVED:
                kunci = normalisasi_kata(a.teks)
                if kunci:
                    entri = state.kata.setdefault(kunci, {"teks": a.teks.strip(), "jumlah": 0})
                    entri["jumlah"] += 1


manajer = ManajerRuntime()
