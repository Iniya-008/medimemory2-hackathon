"""After-visit capture: recorded consultation -> reviewed instructions -> translations -> cached audio."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.entities import TimestampMixin, utcnow

CATEGORIES = ("medicine", "timing", "diet", "test", "follow_up", "lifestyle", "other")


class Visit(TimestampMixin, Base):
    __tablename__ = "mm_visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("mm_users.id", ondelete="CASCADE"), index=True, nullable=False)
    doctor_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    # draft -> confirmed (or discarded = deleted). Nothing is usable by Ask until confirmed.
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="recording", nullable=False)  # recording | document | typed | sample
    document_id: Mapped[int | None] = mapped_column(ForeignKey("mm_medical_documents.id", ondelete="SET NULL"))
    text_method: Mapped[str | None] = mapped_column(String(20))  # speech_to_text | pdf_text | ocr | ai_vision | text | typed
    recording_consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_note: Mapped[str | None] = mapped_column(String(255))
    transcript: Mapped[str] = mapped_column(Text, default="", nullable=False)
    transcript_language: Mapped[str | None] = mapped_column(String(10))
    extraction_method: Mapped[str | None] = mapped_column(String(20))  # llm | rules
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("mm_consultations.id", ondelete="SET NULL"))

    instructions: Mapped[list["VisitInstruction"]] = relationship(
        back_populates="visit", cascade="all, delete-orphan", order_by="VisitInstruction.position")


class VisitInstruction(TimestampMixin, Base):
    __tablename__ = "mm_visit_instructions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("mm_visits.id", ondelete="CASCADE"), index=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("mm_users.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    source_sentence: Mapped[str] = mapped_column(Text, default="", nullable=False)  # doctor's words, from the transcript
    simple_text: Mapped[str] = mapped_column(Text, nullable=False)                    # plain-English instruction
    needs_check: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    check_reason: Mapped[str | None] = mapped_column(String(255))
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    visit: Mapped[Visit] = relationship(back_populates="instructions")
    translations: Mapped[list["InstructionTranslation"]] = relationship(
        back_populates="instruction", cascade="all, delete-orphan")


class InstructionTranslation(TimestampMixin, Base):
    __tablename__ = "mm_instruction_translations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instruction_id: Mapped[int] = mapped_column(ForeignKey("mm_visit_instructions.id", ondelete="CASCADE"), index=True, nullable=False)
    lang: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(20), default="machine", nullable=False)  # machine | human
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    instruction: Mapped[VisitInstruction] = relationship(back_populates="translations")
    __table_args__ = (UniqueConstraint("instruction_id", "lang", name="uq_instruction_lang"),)


class AudioClip(Base):
    """Cached text-to-speech output keyed by sha256(model|voice|lang|text). Shared across users (no personal data in key)."""
    __tablename__ = "mm_audio_clips"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    lang: Mapped[str] = mapped_column(String(10), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(80), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class PhraseTranslation(Base):
    """Machine translations of the fixed safety messages (emergency, refusals, not found), cached per language."""
    __tablename__ = "mm_phrase_translations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    lang: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("kind", "lang", name="uq_phrase_lang"),)
