"""Titik masuk aplikasi FastAPI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR
from .database import engine, siapkan_skema
from .realtime.manajer import manajer
from .routers import api_admin, api_peserta, pages, ws


class AsetStatis(StaticFiles):
    """StaticFiles yang selalu minta browser memvalidasi ulang isi file.

    Halaman memakai `?v=` untuk cache-busting, tapi import relatif antar modul
    JS (`./common.js`) tidak ikut membawa query itu. `no-cache` memastikan
    browser tetap mengecek ETag, jadi partisipan tidak pernah menjalankan
    kombinasi file lama dan baru setelah deploy. Biayanya hanya respons 304.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("livepoll")


@asynccontextmanager
async def daur_hidup(app: FastAPI):
    await siapkan_skema()
    log.info("Skema database siap")
    yield
    await manajer.hentikan_semua()
    await engine.dispose()


app = FastAPI(title="Live Polling", version="1.0.0", lifespan=daur_hidup)

app.mount("/static", AsetStatis(directory=str(BASE_DIR / "static")), name="static")
app.include_router(pages.router)
app.include_router(api_admin.router)
app.include_router(api_peserta.router)
app.include_router(ws.router)


@app.exception_handler(500)
async def galat_server(request: Request, exc: Exception):
    log.exception("Galat tak tertangani di %s", request.url.path)
    return JSONResponse({"detail": "Terjadi kesalahan di server"}, status_code=500)
