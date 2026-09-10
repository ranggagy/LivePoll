"""Endpoint WebSocket untuk presenter dan partisipan."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..database import BuatSesiDB
from ..models import MODE_QUIZ, Partisipan, Sesi
from ..realtime.hub import PERAN_PARTISIPAN, PERAN_PRESENTER, Koneksi, hub
from ..realtime.manajer import manajer

log = logging.getLogger("livepoll.ws")
router = APIRouter()

# Tutup koneksi yang diam terlalu lama; client mengirim ping tiap 25 detik.
BATAS_DIAM_DETIK = 90


async def _ringkasan_selesai(kode: str) -> dict | None:
    """Ringkasan akhir sesi yang sudah ditutup, dibaca ulang dari database.

    Dipakai supaya presenter yang me-refresh halaman setelah acara selesai
    tetap melihat leaderboard final, bukan layar kosong.
    """
    async with BuatSesiDB() as db:
        sesi = (
            await db.execute(
                select(Sesi).where(Sesi.kode_sesi == kode).order_by(Sesi.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if sesi is None:
            return None
        papan = None
        if sesi.mode == MODE_QUIZ:
            peserta = (
                (
                    await db.execute(
                        select(Partisipan)
                        .where(Partisipan.session_id == sesi.id)
                        .order_by(Partisipan.total_poin.desc())
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )
            papan = {
                "baris": [
                    {
                        "participant_id": p.id,
                        "nickname": p.nickname or "Anonim",
                        "poin": p.total_poin or 0,
                        "peringkat": i + 1,
                    }
                    for i, p in enumerate(peserta)
                ],
                "total_partisipan": len(peserta),
            }
    return {
        "tipe": "sesi_selesai",
        "sesi": {"kode": sesi.kode_sesi, "judul": sesi.judul, "mode": sesi.mode},
        "leaderboard": papan,
    }


async def _kabari_jumlah_online(kode: str) -> None:
    await hub.siarkan(
        kode, {"tipe": "online", "jumlah": hub.jumlah_partisipan_online(kode)}, peran=PERAN_PRESENTER
    )


@router.websocket("/ws/present/{kode}")
async def ws_presenter(websocket: WebSocket, kode: str):
    """Socket layar presenter: menerima hasil live, moderasi, dan leaderboard."""
    await websocket.accept()
    kode = (kode or "").strip().upper()
    runtime = await manajer.dapatkan(kode)
    if runtime is None:
        await websocket.send_json(await _ringkasan_selesai(kode) or {"tipe": "sesi_tidak_ada"})
        await websocket.close()
        return

    koneksi = Koneksi(ws=websocket, peran=PERAN_PRESENTER)
    hub.daftarkan(kode, koneksi)
    runtime.mulai_loop()
    try:
        await websocket.send_json(runtime.state_untuk_presenter())
        while True:
            pesan = await asyncio.wait_for(websocket.receive_json(), timeout=BATAS_DIAM_DETIK)
            tipe = pesan.get("tipe")
            if tipe == "ping":
                await websocket.send_json({"tipe": "pong"})
            elif tipe == "sinkron":
                await websocket.send_json(runtime.state_untuk_presenter())
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        log.exception("Socket presenter sesi %s berhenti tidak wajar", kode)
    finally:
        hub.lepas(kode, koneksi)


@router.websocket("/ws/play/{kode}")
async def ws_partisipan(websocket: WebSocket, kode: str, token: str = ""):
    """Socket partisipan: menerima soal aktif dan mengirim jawaban."""
    await websocket.accept()
    kode = (kode or "").strip().upper()
    runtime = await manajer.dapatkan(kode)
    if runtime is None:
        await websocket.send_json({"tipe": "sesi_selesai", "pesan": "Sesi telah berakhir"})
        await websocket.close()
        return

    async with BuatSesiDB() as db:
        peserta = (
            await db.execute(
                select(Partisipan).where(
                    Partisipan.token == token, Partisipan.session_id == runtime.session_id
                )
            )
        ).scalar_one_or_none()

    if peserta is None:
        await websocket.send_json({"tipe": "token_tidak_valid"})
        await websocket.close()
        return

    runtime.daftarkan_partisipan(peserta.id, peserta.nickname, peserta.total_poin or 0)
    koneksi = Koneksi(ws=websocket, peran=PERAN_PARTISIPAN, participant_id=peserta.id)
    hub.daftarkan(kode, koneksi)
    runtime.mulai_loop()
    await _kabari_jumlah_online(kode)

    try:
        await websocket.send_json(runtime.state_untuk_partisipan(peserta.id))
        while True:
            pesan = await asyncio.wait_for(websocket.receive_json(), timeout=BATAS_DIAM_DETIK)
            tipe = pesan.get("tipe")
            if tipe == "ping":
                await websocket.send_json({"tipe": "pong"})
            elif tipe == "sinkron":
                await websocket.send_json(runtime.state_untuk_partisipan(peserta.id))
            elif tipe == "jawab":
                hasil = await runtime.terima_jawaban(peserta.id, pesan)
                await websocket.send_json({"tipe": "jawaban_diterima", **hasil})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        log.exception("Socket partisipan sesi %s berhenti tidak wajar", kode)
    finally:
        hub.lepas(kode, koneksi)
        await _kabari_jumlah_online(kode)
