"""Verifikasi kompatibilitas Postgres tanpa perlu server Postgres berjalan.

Skrip mengompilasi DDL tabel, indeks parsial, dan statement upsert ke dialek
`postgresql+asyncpg`, lalu menguji normalisasi URL bergaya Render. Ini menangkap
kesalahan tingkat dialek sebelum deploy.

    .venv/Scripts/python.exe tools/cek_postgres.py
"""

import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.config import siapkan_database_url  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import Jawaban, Partisipan, Sesi  # noqa: E402

DIALEK = postgresql.asyncpg.dialect()
gagal = 0


def cek(nama: str, kondisi: bool, detail: str = "") -> None:
    global gagal
    print(f"  {'OK  ' if kondisi else 'GAGAL'} {nama}" + (f"  {detail}" if detail and not kondisi else ""))
    if not kondisi:
        gagal += 1


print("\n[1] DDL semua tabel dapat dikompilasi ke Postgres")
for tabel in Base.metadata.sorted_tables:
    try:
        sql = str(CreateTable(tabel).compile(dialect=DIALEK))
        cek(f"CREATE TABLE {tabel.name}", "CREATE TABLE" in sql)
    except Exception as e:  # pragma: no cover - hanya untuk diagnosa
        cek(f"CREATE TABLE {tabel.name}", False, repr(e))

print("\n[2] Indeks parsial kode sesi aktif")
indeks = next(i for i in Sesi.__table__.indexes if i.name == "uq_kode_sesi_aktif")
sql_indeks = str(CreateIndex(indeks).compile(dialect=DIALEK))
cek("indeks unik + klausa WHERE", "UNIQUE INDEX" in sql_indeks and "WHERE" in sql_indeks, sql_indeks)
print(f"       {sql_indeks.strip()}")

print("\n[3] Upsert jawaban (ON CONFLICT) memakai dialek Postgres")
stmt = postgresql.insert(Jawaban).values(
    question_id=1, participant_id=1, option_id=1, teks=None, nilai_rating=None,
    waktu_jawab_ms=100, poin=900, benar=True, status_moderasi="approved",
)
stmt = stmt.on_conflict_do_update(
    index_elements=["question_id", "participant_id"],
    set_={
        "option_id": stmt.excluded.option_id,
        "teks": stmt.excluded.teks,
        "nilai_rating": stmt.excluded.nilai_rating,
        "waktu_jawab_ms": stmt.excluded.waktu_jawab_ms,
        "poin": stmt.excluded.poin,
        "benar": stmt.excluded.benar,
        "status_moderasi": stmt.excluded.status_moderasi,
        "submitted_at": stmt.excluded.submitted_at,
    },
)
sql_upsert = str(stmt.compile(dialect=DIALEK))
cek("ON CONFLICT DO UPDATE terkompilasi", "ON CONFLICT" in sql_upsert and "DO UPDATE" in sql_upsert)
cek("target konflik memakai kolom unik", "(question_id, participant_id)" in sql_upsert, sql_upsert)

print("\n[4] Constraint unik yang jadi sandaran upsert & nickname")
nama_constraint = {c.name for c in Jawaban.__table__.constraints if c.name}
cek("uq_jawaban_per_partisipan ada", "uq_jawaban_per_partisipan" in nama_constraint, str(nama_constraint))
nama_partisipan = {c.name for c in Partisipan.__table__.constraints if c.name}
cek("uq_nickname_per_sesi ada", "uq_nickname_per_sesi" in nama_partisipan, str(nama_partisipan))

print("\n[5] Normalisasi DATABASE_URL bergaya Render/Neon")
NEON_POOLED = "postgresql://u:p@ep-cool-dawn-123-pooler.ap-southeast-1.aws.neon.tech/livepoll?sslmode=require&channel_binding=require"
NEON_LANGSUNG = "postgresql://u:p@ep-cool-dawn-123.ap-southeast-1.aws.neon.tech/livepoll?sslmode=require"

# (url mentah, url harapan, perlu ssl, perlu matikan prepared statement)
kasus = [
    ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db", True, False),
    ("postgresql://u:p@host/db?sslmode=require", "postgresql+asyncpg://u:p@host/db", True, False),
    ("postgresql://u:p@localhost:5432/db", "postgresql+asyncpg://u:p@localhost:5432/db", False, False),
    ("postgresql://u:p@localhost/db?sslmode=disable", "postgresql+asyncpg://u:p@localhost/db", False, False),
    (NEON_POOLED,
     "postgresql+asyncpg://u:p@ep-cool-dawn-123-pooler.ap-southeast-1.aws.neon.tech/livepoll", True, True),
    (NEON_LANGSUNG,
     "postgresql+asyncpg://u:p@ep-cool-dawn-123.ap-southeast-1.aws.neon.tech/livepoll", True, False),
    ("postgresql://u:p@host/db?pgbouncer=true", "postgresql+asyncpg://u:p@host/db", True, True),
    ("", None, False, False),
]
for mentah, harapan, butuh_ssl, matikan_ps in kasus:
    url, args, ekw = siapkan_database_url(mentah)
    label = (mentah[:58] + "…") if len(mentah) > 58 else (mentah or "(kosong)")
    if harapan is None:
        cek(f"{label} -> SQLite lokal", url.startswith("sqlite+aiosqlite:///"), url)
        continue
    cek(f"{label}", url == harapan, f"dapat {url}")
    cek(f"    ssl={butuh_ssl}", bool(args.get("ssl")) == butuh_ssl, str(args))
    ps_mati = args.get("statement_cache_size") == 0 and ekw.get("prepared_statement_cache_size") == 0
    cek(f"    prepared-statement dimatikan={matikan_ps}", ps_mati == matikan_ps, f"{args} {ekw}")

print("\n[6] Driver Postgres terpasang")
try:
    import asyncpg

    cek(f"asyncpg {asyncpg.__version__}", True)
except Exception as e:
    cek("asyncpg terpasang", False, repr(e))
try:
    import greenlet

    cek(f"greenlet {greenlet.__version__} (dibutuhkan SQLAlchemy async)", True)
except Exception as e:
    cek("greenlet terpasang", False, repr(e))

print(f"\n{'SEMUA CEK POSTGRES LULUS' if gagal == 0 else f'{gagal} CEK GAGAL'}")
sys.exit(1 if gagal else 0)
