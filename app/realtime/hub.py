"""Manajemen koneksi WebSocket aktif, dikelompokkan per kode sesi.

Untuk skala 100-300 partisipan dalam satu instance, menyimpan daftar koneksi
di memory sudah cukup — belum perlu Redis pub/sub.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

log = logging.getLogger("livepoll.hub")

PERAN_PRESENTER = "presenter"
PERAN_PARTISIPAN = "partisipan"


# eq=False: identitas objek dipakai apa adanya supaya Koneksi bisa masuk set.
@dataclass(eq=False)
class Koneksi:
    """Satu socket yang sedang terhubung ke sebuah sesi."""

    ws: WebSocket
    peran: str
    participant_id: int | None = None
    _gembok: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def kirim(self, payload: dict) -> bool:
        """Kirim satu pesan JSON. Mengembalikan False bila socket sudah mati."""
        try:
            # Lock supaya dua broadcast bersamaan tidak saling menimpa frame.
            async with self._gembok:
                await self.ws.send_json(payload)
            return True
        except Exception:
            return False


class Hub:
    """Registry koneksi WebSocket per sesi."""

    def __init__(self) -> None:
        self._per_sesi: dict[str, set[Koneksi]] = {}

    def daftarkan(self, kode: str, koneksi: Koneksi) -> None:
        self._per_sesi.setdefault(kode, set()).add(koneksi)

    def lepas(self, kode: str, koneksi: Koneksi) -> None:
        kumpulan = self._per_sesi.get(kode)
        if not kumpulan:
            return
        kumpulan.discard(koneksi)
        if not kumpulan:
            self._per_sesi.pop(kode, None)

    def koneksi_sesi(self, kode: str) -> set[Koneksi]:
        return set(self._per_sesi.get(kode, ()))

    def jumlah_partisipan_online(self, kode: str) -> int:
        """Hitung partisipan unik yang sedang online (bukan jumlah socket)."""
        unik = {
            k.participant_id
            for k in self._per_sesi.get(kode, ())
            if k.peran == PERAN_PARTISIPAN and k.participant_id is not None
        }
        return len(unik)

    def ada_presenter(self, kode: str) -> bool:
        return any(k.peran == PERAN_PRESENTER for k in self._per_sesi.get(kode, ()))

    async def siarkan(self, kode: str, payload: dict, peran: str | None = None) -> None:
        """Kirim payload ke semua koneksi sesi (opsional: batasi ke satu peran)."""
        target = [k for k in self._per_sesi.get(kode, ()) if peran is None or k.peran == peran]
        if not target:
            return
        hasil = await asyncio.gather(*(k.kirim(payload) for k in target), return_exceptions=True)
        for koneksi, sukses in zip(target, hasil):
            if sukses is not True:
                self.lepas(kode, koneksi)

    async def kirim_ke_partisipan(self, kode: str, participant_id: int, payload: dict) -> None:
        """Kirim payload ke semua socket milik satu partisipan (bisa >1 tab)."""
        target = [
            k
            for k in self._per_sesi.get(kode, ())
            if k.peran == PERAN_PARTISIPAN and k.participant_id == participant_id
        ]
        for koneksi in target:
            if not await koneksi.kirim(payload):
                self.lepas(kode, koneksi)


hub = Hub()
