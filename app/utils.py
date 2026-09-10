"""Fungsi bantu umum: kode sesi, normalisasi teks, waktu."""

import re
import secrets
import unicodedata
from datetime import datetime, timezone

# Huruf/angka yang tidak ambigu saat dibacakan atau diketik ulang oleh audiens.
_ALFABET_KODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def buat_kode_sesi(panjang: int = 6) -> str:
    """Kode sesi 6 karakter alfanumerik, tanpa karakter yang mudah tertukar."""
    return "".join(secrets.choice(_ALFABET_KODE) for _ in range(panjang))


def buat_token() -> str:
    """Token partisipan yang disimpan di localStorage browser."""
    return secrets.token_urlsafe(24)


def normalisasi_nickname(teks: str) -> str:
    """Trim + lowercase + rapatkan spasi ganda, untuk cek keunikan nickname."""
    return re.sub(r"\s+", " ", (teks or "").strip()).lower()


def normalisasi_kata(teks: str) -> str:
    """Normalisasi jawaban Word Cloud agar varian mirip digabung jadi satu entri."""
    bersih = unicodedata.normalize("NFKC", teks or "").strip().lower()
    bersih = re.sub(r"\s+", " ", bersih)
    return bersih.strip(" .,!?;:\"'")


def sekarang() -> datetime:
    """Waktu server dalam UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def ke_utc(nilai: datetime | None) -> datetime | None:
    """Pastikan datetime dari DB selalu punya timezone UTC."""
    if nilai is None:
        return None
    if nilai.tzinfo is None:
        return nilai.replace(tzinfo=timezone.utc)
    return nilai.astimezone(timezone.utc)
