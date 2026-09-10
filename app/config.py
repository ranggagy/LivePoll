"""Konfigurasi aplikasi, dibaca dari environment variable."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BASE_DIR = Path(__file__).resolve().parent.parent


def _muat_dotenv() -> None:
    """Muat file .env sederhana tanpa dependensi tambahan."""
    berkas = BASE_DIR / ".env"
    if not berkas.exists():
        return
    for baris in berkas.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci, nilai = baris.split("=", 1)
        os.environ.setdefault(kunci.strip(), nilai.strip().strip('"').strip("'"))


_muat_dotenv()


_HOST_LOKAL = ("localhost", "127.0.0.1", "::1", "")


def siapkan_database_url(mentah: str) -> tuple[str, dict, dict]:
    """Ubah URL database jadi bentuk yang dimengerti SQLAlchemy async.

    Mengembalikan (url, connect_args, engine_kwargs).

    Tiga hal yang dirapikan di sini:

    1. Skema. Render/Neon memberi `postgres://` atau `postgresql://`, sedangkan
       SQLAlchemy async butuh `postgresql+asyncpg://`.
    2. Parameter SSL. asyncpg tidak mengenal `sslmode`/`channel_binding` ala
       psycopg2, jadi keduanya dibuang dan diganti `ssl=True` di connect_args.
       SSL dinyalakan secara default untuk host non-lokal — Neon dan Render
       menolak koneksi tanpa TLS.
    3. Connection pooler. String koneksi bawaan Neon memakai host `-pooler`
       (PgBouncer mode transaksi). Di mode itu prepared statement milik asyncpg
       bocor antar sesi dan memunculkan galat `prepared statement "__asyncpg_stmt_x__"
       already exists` saat beban naik. Karena itu cache prepared statement
       dimatikan otomatis begitu host pooler terdeteksi.
    """
    connect_args: dict = {}
    engine_kwargs: dict = {}
    url = (mentah or "").strip()

    if not url:
        # Tanpa konfigurasi, pakai SQLite lokal supaya aplikasi bisa langsung jalan.
        return f"sqlite+aiosqlite:///{(BASE_DIR / 'live_poll.db').as_posix()}", connect_args, engine_kwargs

    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    elif url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = "sqlite+aiosqlite://" + url[len("sqlite://"):]

    if url.startswith("postgresql+asyncpg://"):
        bagian = urlsplit(url)
        param = dict(parse_qsl(bagian.query))
        sslmode = param.pop("sslmode", None)
        param.pop("channel_binding", None)
        pakai_pgbouncer = param.pop("pgbouncer", "").lower() in ("true", "1")

        host = (bagian.hostname or "").lower()
        if sslmode in ("disable", "allow"):
            pass  # dinonaktifkan secara eksplisit
        elif sslmode or host not in _HOST_LOKAL:
            connect_args["ssl"] = True

        if pakai_pgbouncer or "-pooler" in host or "pgbouncer" in host:
            connect_args["statement_cache_size"] = 0
            engine_kwargs["prepared_statement_cache_size"] = 0

        url = urlunsplit((bagian.scheme, bagian.netloc, bagian.path, urlencode(param), bagian.fragment))

    return url, connect_args, engine_kwargs


DATABASE_URL, DB_CONNECT_ARGS, DB_ENGINE_KWARGS = siapkan_database_url(os.getenv("DATABASE_URL", ""))
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# Interval throttle broadcast hasil ke presenter (detik).
INTERVAL_BROADCAST = float(os.getenv("INTERVAL_BROADCAST", "0.5"))
# Toleransi jaringan saat menerima jawaban yang lewat sedikit dari deadline (ms).
TOLERANSI_TELAT_MS = int(os.getenv("TOLERANSI_TELAT_MS", "300"))
# Konfigurasi skor Quiz Mode.
POIN_MAKSIMAL = int(os.getenv("POIN_MAKSIMAL", "1000"))
FAKTOR_PENGURANGAN = float(os.getenv("FAKTOR_PENGURANGAN", "0.5"))
DURASI_DEFAULT = int(os.getenv("DURASI_DEFAULT", "20"))
