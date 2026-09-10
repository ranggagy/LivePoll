"""Engine dan session factory SQLAlchemy async."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import DATABASE_URL, DB_CONNECT_ARGS, DB_ENGINE_KWARGS, IS_SQLITE


class Base(DeclarativeBase):
    """Base class untuk semua model."""


_opsi_engine: dict = {"echo": False, "future": True, "connect_args": DB_CONNECT_ARGS}
if not IS_SQLITE:
    # Pool kecil tapi cukup: satu instance melayani 100-300 partisipan.
    # pool_pre_ping penting untuk Neon/Render yang menutup koneksi idle.
    _opsi_engine.update(pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800)
    _opsi_engine.update(DB_ENGINE_KWARGS)

engine = create_async_engine(DATABASE_URL, **_opsi_engine)
BuatSesiDB = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def dapatkan_db():
    """Dependency FastAPI: satu session DB per request."""
    async with BuatSesiDB() as db:
        yield db


async def siapkan_skema() -> None:
    """Buat tabel bila belum ada (cukup untuk aplikasi internal sekecil ini)."""
    from . import models  # noqa: F401  -- pastikan model ter-register

    async with engine.begin() as conn:
        if IS_SQLITE:
            # WAL bikin baca-tulis bersamaan jauh lebih lancar di SQLite.
            from sqlalchemy import text

            await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
