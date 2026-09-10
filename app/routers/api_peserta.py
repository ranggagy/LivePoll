"""Endpoint REST untuk partisipan: cek sesi dan gabung."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import dapatkan_db
from ..models import MODE_QUIZ, STATUS_SESI_AKTIF, Partisipan, Sesi
from ..realtime.manajer import manajer
from ..schemas import GabungIn
from ..utils import buat_token, normalisasi_nickname

log = logging.getLogger("livepoll.peserta")
router = APIRouter(prefix="/api", tags=["partisipan"])


async def _sesi_aktif(db: AsyncSession, kode: str) -> Sesi | None:
    kode = (kode or "").strip().upper()
    return (
        await db.execute(
            select(Sesi)
            .where(Sesi.kode_sesi == kode, Sesi.status == STATUS_SESI_AKTIF)
            .order_by(Sesi.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/sesi/{kode}/info")
async def info_sesi(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    """Dipakai halaman join untuk tahu sesi ada/tidak dan butuh nickname atau tidak."""
    sesi = await _sesi_aktif(db, kode)
    if sesi is None:
        return {"ada": False, "kode": (kode or "").strip().upper()}
    return {
        "ada": True,
        "kode": sesi.kode_sesi,
        "judul": sesi.judul,
        "mode": sesi.mode,
        "butuh_nickname": sesi.mode == MODE_QUIZ,
    }


@router.post("/gabung/{kode}")
async def gabung(kode: str, payload: GabungIn, db: AsyncSession = Depends(dapatkan_db)):
    """Gabung ke sesi. Token lama dipakai ulang supaya refresh tidak bikin peserta baru."""
    sesi = await _sesi_aktif(db, kode)
    if sesi is None:
        raise HTTPException(410, "Sesi tidak ditemukan atau sudah berakhir")

    # Resume: token dari localStorage masih valid untuk sesi ini.
    if payload.token:
        lama = (
            await db.execute(
                select(Partisipan).where(
                    Partisipan.token == payload.token, Partisipan.session_id == sesi.id
                )
            )
        ).scalar_one_or_none()
        if lama is not None:
            runtime = await manajer.dapatkan(sesi.kode_sesi)
            if runtime is not None:
                runtime.daftarkan_partisipan(lama.id, lama.nickname, lama.total_poin or 0)
            return _hasil_gabung(sesi, lama, resume=True)

    nickname = (payload.nickname or "").strip()[:60]
    if sesi.mode == MODE_QUIZ:
        if not nickname:
            raise HTTPException(400, "Nickname wajib diisi untuk Quiz Mode")
        ternormalisasi = normalisasi_nickname(nickname)
        sudah_ada = (
            await db.execute(
                select(Partisipan.id).where(
                    Partisipan.session_id == sesi.id,
                    Partisipan.nickname_normalized == ternormalisasi,
                )
            )
        ).first()
        if sudah_ada:
            raise HTTPException(409, "Nickname sudah dipakai, coba nama lain")
    else:
        ternormalisasi = None
        nickname = nickname or None

    peserta = Partisipan(
        session_id=sesi.id,
        nickname=nickname,
        nickname_normalized=ternormalisasi,
        token=buat_token(),
    )
    db.add(peserta)
    try:
        await db.commit()
    except IntegrityError:
        # Dua orang mengirim nickname sama nyaris bersamaan — constraint DB yang memutus.
        await db.rollback()
        raise HTTPException(409, "Nickname sudah dipakai, coba nama lain")
    await db.refresh(peserta)

    runtime = await manajer.dapatkan(sesi.kode_sesi)
    if runtime is not None:
        runtime.daftarkan_partisipan(peserta.id, peserta.nickname, 0)
    return _hasil_gabung(sesi, peserta, resume=False)


def _hasil_gabung(sesi: Sesi, peserta: Partisipan, resume: bool) -> dict:
    return {
        "ok": True,
        "resume": resume,
        "token": peserta.token,
        "participant_id": peserta.id,
        "nickname": peserta.nickname,
        "total_poin": peserta.total_poin or 0,
        "sesi": {"kode": sesi.kode_sesi, "judul": sesi.judul, "mode": sesi.mode},
    }
