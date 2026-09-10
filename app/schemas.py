"""Skema request/response (Pydantic)."""

from pydantic import BaseModel, Field

from .config import DURASI_DEFAULT
from .models import MODE_SURVEY, TIPE_MC


class BuatSesiIn(BaseModel):
    judul: str = Field(min_length=1, max_length=200)
    mode: str = MODE_SURVEY


class OpsiIn(BaseModel):
    teks: str = Field(min_length=1, max_length=300)
    is_benar: bool = False


class PertanyaanIn(BaseModel):
    tipe: str = TIPE_MC
    teks: str = Field(min_length=1, max_length=500)
    durasi_detik: int = Field(default=DURASI_DEFAULT, ge=5, le=300)
    rating_maks: int = Field(default=5, ge=2, le=10)
    opsi: list[OpsiIn] = []


class UrutanIn(BaseModel):
    urutan: list[int]


class ModerasiIn(BaseModel):
    participant_id: int
    aksi: str = "approve"


class ModerasiSemuaIn(BaseModel):
    aksi: str = "approve"


class GabungIn(BaseModel):
    nickname: str | None = None
    token: str | None = None
