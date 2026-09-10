"""Model data: sesi, pertanyaan, opsi, partisipan, jawaban."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import DURASI_DEFAULT, POIN_MAKSIMAL
from .database import Base
from .utils import sekarang

# Nilai enum disimpan sebagai string biasa supaya gampang di-migrate manual.
MODE_SURVEY = "survey"
MODE_QUIZ = "quiz"

TIPE_MC = "mc"
TIPE_WORD_CLOUD = "word_cloud"
TIPE_RATING = "rating"

STATUS_SESI_AKTIF = "aktif"
STATUS_SESI_SELESAI = "selesai"

STATUS_Q_DRAFT = "draft"
STATUS_Q_BERJALAN = "berjalan"
STATUS_Q_SELESAI = "selesai"

MOD_PENDING = "pending"
MOD_APPROVED = "approved"
MOD_REJECTED = "rejected"


class Sesi(Base):
    """Satu acara polling/kuis dengan kode yang dibagikan ke audiens."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode_sesi: Mapped[str] = mapped_column(String(12), index=True)
    judul: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(10), default=MODE_SURVEY)
    status: Mapped[str] = mapped_column(String(10), default=STATUS_SESI_AKTIF, index=True)
    pertanyaan_aktif_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=sekarang)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    daftar_pertanyaan: Mapped[list["Pertanyaan"]] = relationship(
        back_populates="sesi",
        cascade="all, delete-orphan",
        order_by="Pertanyaan.urutan",
        lazy="selectin",
    )
    daftar_partisipan: Mapped[list["Partisipan"]] = relationship(
        back_populates="sesi", cascade="all, delete-orphan"
    )

    # Kode unik hanya berlaku untuk sesi yang masih aktif — kode lama boleh dipakai ulang.
    __table_args__ = (
        Index(
            "uq_kode_sesi_aktif",
            "kode_sesi",
            unique=True,
            sqlite_where=(status == STATUS_SESI_AKTIF),
            postgresql_where=(status == STATUS_SESI_AKTIF),
        ),
    )


class Pertanyaan(Base):
    """Satu pertanyaan dalam sesi. Hanya satu yang berjalan pada satu waktu."""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    tipe: Mapped[str] = mapped_column(String(20), default=TIPE_MC)
    teks: Mapped[str] = mapped_column(Text)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default=STATUS_Q_DRAFT)

    durasi_detik: Mapped[int] = mapped_column(Integer, default=DURASI_DEFAULT)
    poin_maksimal: Mapped[int] = mapped_column(Integer, default=POIN_MAKSIMAL)
    rating_maks: Mapped[int] = mapped_column(Integer, default=5)

    dibuka_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ditutup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sesi: Mapped["Sesi"] = relationship(back_populates="daftar_pertanyaan")
    daftar_opsi: Mapped[list["Opsi"]] = relationship(
        back_populates="pertanyaan",
        cascade="all, delete-orphan",
        order_by="Opsi.urutan",
        lazy="selectin",
    )


class Opsi(Base):
    """Pilihan jawaban untuk pertanyaan bertipe Multiple Choice."""

    __tablename__ = "options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    teks: Mapped[str] = mapped_column(Text)
    is_benar: Mapped[bool] = mapped_column(Boolean, default=False)
    urutan: Mapped[int] = mapped_column(Integer, default=0)

    pertanyaan: Mapped["Pertanyaan"] = relationship(back_populates="daftar_opsi")


class Partisipan(Base):
    """Satu perangkat yang bergabung ke sesi. Nickname hanya wajib di Quiz Mode."""

    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    nickname: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nickname_normalized: Mapped[str | None] = mapped_column(String(60), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    total_poin: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=sekarang)

    sesi: Mapped["Sesi"] = relationship(back_populates="daftar_partisipan")

    # Pengaman terakhir untuk race condition dua nickname sama nyaris bersamaan.
    __table_args__ = (
        UniqueConstraint("session_id", "nickname_normalized", name="uq_nickname_per_sesi"),
    )


class Jawaban(Base):
    """Jawaban satu partisipan untuk satu pertanyaan (upsert, anti data dobel)."""

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), index=True)

    option_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teks: Mapped[str | None] = mapped_column(Text, nullable=True)
    nilai_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    waktu_jawab_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poin: Mapped[int] = mapped_column(Integer, default=0)
    benar: Mapped[bool] = mapped_column(Boolean, default=False)
    status_moderasi: Mapped[str] = mapped_column(String(10), default=MOD_APPROVED)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=sekarang)

    __table_args__ = (
        UniqueConstraint("question_id", "participant_id", name="uq_jawaban_per_partisipan"),
    )
