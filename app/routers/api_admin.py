"""Endpoint REST untuk admin/presenter: kelola sesi, pertanyaan, dan kontrol live."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import dapatkan_db
from ..models import (
    MODE_QUIZ,
    MODE_SURVEY,
    STATUS_Q_DRAFT,
    STATUS_SESI_AKTIF,
    STATUS_SESI_SELESAI,
    TIPE_MC,
    TIPE_RATING,
    TIPE_WORD_CLOUD,
    Jawaban,
    Opsi,
    Partisipan,
    Pertanyaan,
    Sesi,
)
from ..realtime.manajer import manajer
from ..schemas import BuatSesiIn, ModerasiIn, ModerasiSemuaIn, PertanyaanIn, UrutanIn
from ..services.export_excel import buat_excel
from ..utils import buat_kode_sesi, sekarang

log = logging.getLogger("livepoll.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])

TIPE_VALID = {TIPE_MC, TIPE_WORD_CLOUD, TIPE_RATING}


async def ambil_sesi(db: AsyncSession, kode: str, hanya_aktif: bool = False) -> Sesi:
    """Cari sesi berdasarkan kode; utamakan yang masih aktif."""
    kode = (kode or "").strip().upper()
    kueri = (
        select(Sesi)
        .where(Sesi.kode_sesi == kode)
        .options(selectinload(Sesi.daftar_pertanyaan).selectinload(Pertanyaan.daftar_opsi))
        # Sengaja BUKAN Sesi.status.desc(): status berupa string "aktif"/"selesai",
        # dan "selesai" > "aktif" secara leksikografis, jadi .desc() String itu
        # justru menaruh sesi yang SUDAH SELESAI lebih dulu — kebalikan dari
        # niat "utamakan yang masih aktif". Bandingkan ke STATUS_SESI_AKTIF
        # supaya urutannya benar terlepas dari nilai string statusnya.
        .order_by((Sesi.status == STATUS_SESI_AKTIF).desc(), Sesi.created_at.desc())
    )
    if hanya_aktif:
        kueri = kueri.where(Sesi.status == STATUS_SESI_AKTIF)
    sesi = (await db.execute(kueri.limit(1))).scalar_one_or_none()
    if sesi is None:
        raise HTTPException(404, "Sesi tidak ditemukan")
    return sesi


def rangkum_pertanyaan(q: Pertanyaan) -> dict:
    return {
        "id": q.id,
        "tipe": q.tipe,
        "teks": q.teks,
        "urutan": q.urutan,
        "status": q.status,
        "durasi_detik": q.durasi_detik,
        "rating_maks": q.rating_maks,
        "gambar": q.gambar,
        "opsi": [{"id": o.id, "teks": o.teks, "is_benar": o.is_benar} for o in q.daftar_opsi],
    }


def rangkum_sesi(sesi: Sesi, jumlah_partisipan: int = 0) -> dict:
    return {
        "id": sesi.id,
        "kode_sesi": sesi.kode_sesi,
        "judul": sesi.judul,
        "mode": sesi.mode,
        "status": sesi.status,
        "pertanyaan_aktif_id": sesi.pertanyaan_aktif_id,
        "created_at": sesi.created_at.isoformat() if sesi.created_at else None,
        "jumlah_partisipan": jumlah_partisipan,
        "pertanyaan": [rangkum_pertanyaan(q) for q in sesi.daftar_pertanyaan],
    }


# --- Sesi ----------------------------------------------------------------


@router.get("/sesi")
async def daftar_sesi(db: AsyncSession = Depends(dapatkan_db)):
    """Riwayat sesi, terbaru di atas."""
    daftar = (
        (
            await db.execute(
                select(Sesi)
                .options(selectinload(Sesi.daftar_pertanyaan))
                .order_by(Sesi.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    hitung = dict(
        (
            await db.execute(
                select(Partisipan.session_id, func.count(Partisipan.id)).group_by(Partisipan.session_id)
            )
        ).all()
    )
    return [
        {
            "id": s.id,
            "kode_sesi": s.kode_sesi,
            "judul": s.judul,
            "mode": s.mode,
            "status": s.status,
            "jumlah_pertanyaan": len(s.daftar_pertanyaan),
            "jumlah_partisipan": hitung.get(s.id, 0),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in daftar
    ]


@router.post("/sesi", status_code=201)
async def buat_sesi(payload: BuatSesiIn, db: AsyncSession = Depends(dapatkan_db)):
    """Buat sesi baru dengan kode unik yang belum dipakai sesi aktif lain."""
    mode = payload.mode if payload.mode in (MODE_SURVEY, MODE_QUIZ) else MODE_SURVEY
    for _ in range(12):
        kode = buat_kode_sesi()
        bentrok = (
            await db.execute(
                select(Sesi.id).where(Sesi.kode_sesi == kode, Sesi.status == STATUS_SESI_AKTIF)
            )
        ).first()
        if bentrok:
            continue
        sesi = Sesi(kode_sesi=kode, judul=payload.judul.strip(), mode=mode, status=STATUS_SESI_AKTIF)
        db.add(sesi)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            continue
        await db.refresh(sesi, ["daftar_pertanyaan"])
        return rangkum_sesi(sesi)
    raise HTTPException(500, "Gagal membuat kode sesi unik, coba lagi")


@router.get("/sesi/{kode}")
async def detail_sesi(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    sesi = await ambil_sesi(db, kode)
    jumlah = (
        await db.execute(select(func.count(Partisipan.id)).where(Partisipan.session_id == sesi.id))
    ).scalar_one()
    return rangkum_sesi(sesi, jumlah)


@router.post("/sesi/{kode}/akhiri")
async def akhiri_sesi(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    """Tutup sesi: partisipan yang membuka link setelah ini melihat halaman 'sesi berakhir'."""
    sesi = await ambil_sesi(db, kode, hanya_aktif=True)
    runtime = await manajer.dapatkan(sesi.kode_sesi)
    if runtime is not None:
        await runtime.akhiri_sesi()
    sesi.status = STATUS_SESI_SELESAI
    sesi.ended_at = sekarang()
    sesi.pertanyaan_aktif_id = None
    await db.commit()
    await manajer.buang(sesi.kode_sesi)
    return {"ok": True}


@router.delete("/sesi/{kode}")
async def hapus_sesi(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    sesi = await ambil_sesi(db, kode)
    await manajer.buang(sesi.kode_sesi)
    await db.delete(sesi)
    await db.commit()
    return {"ok": True}


@router.post("/sesi/{kode}/reset")
async def reset_sesi(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    """Kembalikan sesi ke kondisi awal: hapus jawaban & partisipan, soal balik ke draft.

    Pertanyaan yang sudah dibuat tetap dipertahankan supaya sesi bisa langsung
    dipakai ulang tanpa mengetik ulang semuanya.
    """
    sesi = await ambil_sesi(db, kode)
    await manajer.buang(sesi.kode_sesi)

    id_pertanyaan = [q.id for q in sesi.daftar_pertanyaan]
    if id_pertanyaan:
        await db.execute(delete(Jawaban).where(Jawaban.question_id.in_(id_pertanyaan)))
        await db.execute(
            update(Pertanyaan)
            .where(Pertanyaan.id.in_(id_pertanyaan))
            .values(status=STATUS_Q_DRAFT, dibuka_at=None, ditutup_at=None)
        )
    await db.execute(delete(Partisipan).where(Partisipan.session_id == sesi.id))

    sesi.status = STATUS_SESI_AKTIF
    sesi.pertanyaan_aktif_id = None
    sesi.ended_at = None
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Kode sesi ini sedang dipakai sesi aktif lain — akhiri sesi itu dulu")
    return {"ok": True}


# --- Pertanyaan -----------------------------------------------------------


@router.post("/sesi/{kode}/pertanyaan", status_code=201)
async def tambah_pertanyaan(kode: str, payload: PertanyaanIn, db: AsyncSession = Depends(dapatkan_db)):
    sesi = await ambil_sesi(db, kode, hanya_aktif=True)
    _validasi_pertanyaan(sesi, payload)

    urutan_maks = (
        await db.execute(select(func.max(Pertanyaan.urutan)).where(Pertanyaan.session_id == sesi.id))
    ).scalar()
    q = Pertanyaan(
        session_id=sesi.id,
        tipe=payload.tipe,
        teks=payload.teks.strip(),
        gambar=payload.gambar,
        urutan=(urutan_maks or 0) + 1,
        status=STATUS_Q_DRAFT,
        durasi_detik=payload.durasi_detik,
        rating_maks=payload.rating_maks,
    )
    db.add(q)
    await db.flush()
    if payload.tipe == TIPE_MC:
        for i, o in enumerate(payload.opsi):
            db.add(Opsi(question_id=q.id, teks=o.teks.strip(), is_benar=bool(o.is_benar), urutan=i))
    await db.commit()
    await db.refresh(q, ["daftar_opsi"])
    _segarkan_total_soal(sesi.kode_sesi, delta=1)
    return rangkum_pertanyaan(q)


@router.put("/pertanyaan/{qid}")
async def ubah_pertanyaan(qid: int, payload: PertanyaanIn, db: AsyncSession = Depends(dapatkan_db)):
    q = (
        await db.execute(
            select(Pertanyaan).where(Pertanyaan.id == qid).options(selectinload(Pertanyaan.daftar_opsi))
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(404, "Pertanyaan tidak ditemukan")
    sesi = await db.get(Sesi, q.session_id)
    if sesi is not None and sesi.pertanyaan_aktif_id == q.id:
        raise HTTPException(400, "Tutup dulu soal ini sebelum mengubahnya")
    _validasi_pertanyaan(sesi, payload)

    q.tipe = payload.tipe
    q.teks = payload.teks.strip()
    q.gambar = payload.gambar
    q.durasi_detik = payload.durasi_detik
    q.rating_maks = payload.rating_maks

    # Perbarui opsi yang sudah ada DI TEMPAT (cocokkan berdasarkan posisi)
    # alih-alih hapus-semua-lalu-buat-ulang — supaya id opsi yang tidak
    # berubah tetap sama, dan Jawaban.option_id milik jawaban lama (soal ini
    # sudah pernah ditutup & dijawab) tidak jadi nyasar ke id baru yang tak
    # pernah ada saat orang menjawab.
    lama = list(q.daftar_opsi)
    if payload.tipe == TIPE_MC:
        for i, o in enumerate(payload.opsi):
            if i < len(lama):
                lama[i].teks = o.teks.strip()
                lama[i].is_benar = bool(o.is_benar)
                lama[i].urutan = i
            else:
                db.add(Opsi(question_id=q.id, teks=o.teks.strip(), is_benar=bool(o.is_benar), urutan=i))
        for surplus in lama[len(payload.opsi):]:
            await db.delete(surplus)
    else:
        for opsi_lama in lama:
            await db.delete(opsi_lama)
    await db.commit()
    await db.refresh(q, ["daftar_opsi"])
    return rangkum_pertanyaan(q)


@router.delete("/pertanyaan/{qid}")
async def hapus_pertanyaan(qid: int, db: AsyncSession = Depends(dapatkan_db)):
    q = await db.get(Pertanyaan, qid)
    if q is None:
        raise HTTPException(404, "Pertanyaan tidak ditemukan")
    sesi = await db.get(Sesi, q.session_id)
    if sesi is not None and sesi.pertanyaan_aktif_id == q.id:
        raise HTTPException(400, "Tutup dulu soal ini sebelum menghapusnya")
    await db.delete(q)
    await db.commit()
    if sesi is not None:
        _segarkan_total_soal(sesi.kode_sesi, delta=-1)
    return {"ok": True}


@router.post("/sesi/{kode}/urutan")
async def ubah_urutan(kode: str, payload: UrutanIn, db: AsyncSession = Depends(dapatkan_db)):
    """Simpan urutan pertanyaan hasil drag-and-drop di halaman kelola sesi."""
    sesi = await ambil_sesi(db, kode)
    milik = {q.id for q in sesi.daftar_pertanyaan}
    for posisi, qid in enumerate(payload.urutan, start=1):
        if qid in milik:
            q = await db.get(Pertanyaan, qid)
            q.urutan = posisi
    await db.commit()
    return {"ok": True}


def _validasi_pertanyaan(sesi: Sesi | None, payload: PertanyaanIn) -> None:
    if payload.tipe not in TIPE_VALID:
        raise HTTPException(400, "Tipe pertanyaan tidak dikenal")
    if sesi is not None and sesi.mode == MODE_QUIZ and payload.tipe != TIPE_MC:
        raise HTTPException(400, "Quiz Mode hanya mendukung pertanyaan Multiple Choice")
    if payload.tipe == TIPE_MC:
        opsi_bersih = [o for o in payload.opsi if o.teks.strip()]
        if len(opsi_bersih) < 2:
            raise HTTPException(400, "Multiple Choice butuh minimal 2 pilihan jawaban")
        if sesi is not None and sesi.mode == MODE_QUIZ and not any(o.is_benar for o in opsi_bersih):
            raise HTTPException(400, "Quiz Mode butuh tepat satu jawaban benar")
        # Kartu jawaban Quiz Mode dirancang untuk PERSIS 4 warna kategori
        # (PANDUAN_WARNA.md) — opsi ke-5/6 (opt-e/opt-f) tidak didokumentasikan
        # di sana dan opt-e kebetulan memakai warna biru yang sama dengan
        # penanda "Jawaban Benar", jadi bisa menyesatkan peserta saat voting.
        if sesi is not None and sesi.mode == MODE_QUIZ and len(opsi_bersih) > 4:
            raise HTTPException(400, "Quiz Mode maksimal 4 pilihan jawaban")
        payload.opsi = opsi_bersih
    if payload.gambar and not payload.gambar.startswith("data:image/"):
        raise HTTPException(400, "Format gambar tidak valid")


def _segarkan_total_soal(kode: str, delta: int) -> None:
    """Sinkronkan jumlah soal di runtime agar label 'Soal x dari y' tetap benar."""
    runtime = manajer.cache(kode)
    if runtime is not None:
        runtime.total_soal = max(0, runtime.total_soal + delta)


# --- Kontrol live ---------------------------------------------------------


@router.post("/sesi/{kode}/aktifkan/{qid}")
async def aktifkan_pertanyaan(kode: str, qid: int, db: AsyncSession = Depends(dapatkan_db)):
    sesi = await ambil_sesi(db, kode, hanya_aktif=True)
    runtime = await manajer.dapatkan(sesi.kode_sesi)
    if runtime is None:
        raise HTTPException(404, "Sesi tidak aktif")
    hasil = await runtime.aktifkan(qid)
    if not hasil.get("ok"):
        raise HTTPException(400, hasil.get("pesan", "Gagal mengaktifkan pertanyaan"))
    return {"ok": True}


@router.post("/sesi/{kode}/tutup")
async def tutup_pertanyaan(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    """Tombol 'Tutup Soal Sekarang' — tidak perlu menunggu timer habis.

    Dibuat idempoten: kalau timer server kebetulan menutup soal sepersekian
    detik lebih dulu, atau presenter menekan tombolnya dua kali, hasilnya tetap
    dianggap sukses — bukan error yang membingungkan di tengah acara.
    """
    sesi = await ambil_sesi(db, kode, hanya_aktif=True)
    runtime = await manajer.dapatkan(sesi.kode_sesi)
    if runtime is None:
        raise HTTPException(404, "Sesi tidak aktif")
    hasil = await runtime.tutup(alasan="manual")
    if not hasil.get("ok"):
        return {"ok": True, "sudah_ditutup": True, "pesan": hasil.get("pesan")}
    return {"ok": True, "sudah_ditutup": False}


@router.post("/sesi/{kode}/berikutnya")
async def pertanyaan_berikutnya(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    """Aktifkan soal setelah soal yang barusan berjalan."""
    sesi = await ambil_sesi(db, kode, hanya_aktif=True)
    runtime = await manajer.dapatkan(sesi.kode_sesi)
    if runtime is None:
        raise HTTPException(404, "Sesi tidak aktif")

    urut = [q.id for q in sesi.daftar_pertanyaan]
    if not urut:
        raise HTTPException(400, "Belum ada pertanyaan di sesi ini")
    sekarang_id = runtime.aktif.id if runtime.aktif else None
    if sekarang_id in urut:
        posisi = urut.index(sekarang_id) + 1
    else:
        posisi = 0
    if posisi >= len(urut):
        return {"ok": False, "habis": True, "pesan": "Sudah di pertanyaan terakhir"}
    hasil = await runtime.aktifkan(urut[posisi])
    if not hasil.get("ok"):
        raise HTTPException(400, hasil.get("pesan", "Gagal pindah pertanyaan"))
    return {"ok": True, "question_id": urut[posisi]}


# --- Moderasi Word Cloud --------------------------------------------------


@router.post("/sesi/{kode}/moderasi")
async def moderasi_satu(kode: str, payload: ModerasiIn, db: AsyncSession = Depends(dapatkan_db)):
    runtime = await manajer.dapatkan(kode)
    if runtime is None:
        raise HTTPException(404, "Sesi tidak aktif")
    aksi = payload.aksi if payload.aksi in ("approve", "reject") else "approve"
    ok = await runtime.moderasi(payload.participant_id, aksi)
    return {"ok": ok}


@router.post("/sesi/{kode}/moderasi-semua")
async def moderasi_semua(kode: str, payload: ModerasiSemuaIn, db: AsyncSession = Depends(dapatkan_db)):
    runtime = await manajer.dapatkan(kode)
    if runtime is None:
        raise HTTPException(404, "Sesi tidak aktif")
    aksi = payload.aksi if payload.aksi in ("approve", "reject") else "approve"
    jumlah = await runtime.moderasi_semua(aksi)
    return {"ok": True, "jumlah": jumlah}


# --- Export ---------------------------------------------------------------


@router.get("/sesi/{kode}/export.xlsx")
async def export_excel(kode: str, db: AsyncSession = Depends(dapatkan_db)):
    """Unduh rekap sesi sebagai file Excel."""
    sesi = await ambil_sesi(db, kode)
    # Pastikan jawaban yang masih di antrian memory sudah tertulis sebelum diexport.
    runtime = manajer.cache(sesi.kode_sesi)
    if runtime is not None:
        await runtime._tulis_antrian()

    isi = await buat_excel(db, sesi)
    nama = f"hasil-{sesi.kode_sesi}-{sesi.judul[:40]}.xlsx".replace("/", "-")
    return Response(
        content=isi,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nama)}"},
    )
