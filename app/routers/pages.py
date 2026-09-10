"""Route halaman HTML (Jinja2)."""

import io

import segno
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import BASE_DIR
from ..database import dapatkan_db
from ..models import STATUS_SESI_AKTIF, Sesi
from ..realtime.manajer import manajer

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _versi_aset() -> str:
    """Penanda versi dari waktu modifikasi file statis terbaru.

    Dipakai sebagai query string `?v=` supaya browser partisipan tidak memakai
    CSS/JS lama setelah deploy — masalah nyata kalau sesi sedang berjalan.
    """
    direktori = BASE_DIR / "static"
    try:
        terbaru = max(f.stat().st_mtime for f in direktori.rglob("*") if f.is_file())
    except ValueError:
        terbaru = 0
    return str(int(terbaru))


templates.env.globals["versi_aset"] = _versi_aset()


async def _cari_sesi(db: AsyncSession, kode: str) -> Sesi | None:
    return (
        await db.execute(
            select(Sesi).where(Sesi.kode_sesi == (kode or "").strip().upper()).order_by(Sesi.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


@router.get("/", response_class=HTMLResponse)
async def halaman_depan(request: Request):
    return templates.TemplateResponse(request, "index.html", {"judul_halaman": "Live Polling"})


@router.get("/admin", response_class=HTMLResponse)
async def halaman_admin(request: Request):
    return templates.TemplateResponse(request, "admin.html", {"judul_halaman": "Admin · Live Polling"})


@router.get("/admin/{kode}", response_class=HTMLResponse)
async def halaman_kelola(request: Request, kode: str, db: AsyncSession = Depends(dapatkan_db)):
    sesi = await _cari_sesi(db, kode)
    if sesi is None:
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request,
        "kelola.html",
        {"judul_halaman": f"Kelola {sesi.kode_sesi}", "kode": sesi.kode_sesi},
    )


@router.get("/present/{kode}", response_class=HTMLResponse)
async def halaman_presenter(request: Request, kode: str, db: AsyncSession = Depends(dapatkan_db)):
    sesi = await _cari_sesi(db, kode)
    if sesi is None:
        return RedirectResponse("/admin", status_code=303)
    tautan_join = str(request.base_url).rstrip("/") + f"/join/{sesi.kode_sesi}"
    return templates.TemplateResponse(
        request,
        "present.html",
        {
            "judul_halaman": f"Live · {sesi.kode_sesi}",
            "kode": sesi.kode_sesi,
            "judul_sesi": sesi.judul,
            "mode": sesi.mode,
            "tautan_join": tautan_join,
        },
    )


@router.get("/join/{kode}", response_class=HTMLResponse)
async def halaman_gabung(request: Request, kode: str, db: AsyncSession = Depends(dapatkan_db)):
    kode = (kode or "").strip().upper()
    sesi = await _cari_sesi(db, kode)
    if sesi is None or sesi.status != STATUS_SESI_AKTIF:
        return templates.TemplateResponse(
            request,
            "berakhir.html",
            {"judul_halaman": "Sesi telah berakhir", "kode": kode},
            status_code=410 if sesi is not None else 404,
        )
    return templates.TemplateResponse(
        request,
        "join.html",
        {
            "judul_halaman": f"Gabung {sesi.kode_sesi}",
            "kode": sesi.kode_sesi,
            "judul_sesi": sesi.judul,
            "mode": sesi.mode,
        },
    )


@router.get("/play/{kode}", response_class=HTMLResponse)
async def halaman_main(request: Request, kode: str, db: AsyncSession = Depends(dapatkan_db)):
    kode = (kode or "").strip().upper()
    sesi = await _cari_sesi(db, kode)
    if sesi is None or sesi.status != STATUS_SESI_AKTIF:
        return templates.TemplateResponse(
            request,
            "berakhir.html",
            {"judul_halaman": "Sesi telah berakhir", "kode": kode},
            status_code=410 if sesi is not None else 404,
        )
    return templates.TemplateResponse(
        request,
        "play.html",
        {
            "judul_halaman": f"Sesi {sesi.kode_sesi}",
            "kode": sesi.kode_sesi,
            "judul_sesi": sesi.judul,
            "mode": sesi.mode,
        },
    )


@router.get("/qr/{kode}.svg")
async def qr_sesi(request: Request, kode: str):
    """QR code menuju halaman join, digambar sebagai SVG (tanpa dependensi gambar)."""
    kode = (kode or "").strip().upper()
    tautan = str(request.base_url).rstrip("/") + f"/join/{kode}"
    qr = segno.make(tautan, error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=8, border=2, dark="#1A1A17", light=None)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=600"},
    )


@router.get("/healthz")
async def cek_sehat():
    """Endpoint keep-alive: dipakai uptime pinger supaya Render free tier tidak idle-sleep."""
    return {"ok": True, "sesi_aktif": len(manajer._runtime)}
