from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    category: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(100), unique=True)
    source_manifest: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    effective_month: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    category: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("category", "code"),)


class CountryValue(Base):
    __tablename__ = "country_values"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    population: Mapped[int] = mapped_column(Integer)
    area_km2: Mapped[float] = mapped_column(Numeric(14, 2))
    gdp_per_capita_usd: Mapped[float] = mapped_column(Numeric(14, 2))
    temp_c: Mapped[float] = mapped_column(Numeric(6, 2))
    capital: Mapped[str] = mapped_column(String(160))
    capital_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    capital_lon: Mapped[float] = mapped_column(Numeric(9, 6))
    provenance: Mapped[dict] = mapped_column(JSON)
    entity: Mapped[Entity] = relationship()


class Puzzle(Base):
    __tablename__ = "puzzles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    category: Mapped[str] = mapped_column(String(40))
    question_id: Mapped[str] = mapped_column("question", String(80), default="identify-country")
    day: Mapped[date | None] = mapped_column(Date, nullable=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("entities.id"))
    __table_args__ = (UniqueConstraint("day", name="uq_puzzles_day"),)


class AnonymousPlayer(Base):
    __tablename__ = "anonymous_players"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Round(Base):
    __tablename__ = "rounds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    player_id: Mapped[str] = mapped_column(ForeignKey("anonymous_players.id"), index=True)
    puzzle_id: Mapped[str] = mapped_column(ForeignKey("puzzles.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="playing")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("player_id", "puzzle_id"),)


class Guess(Base):
    __tablename__ = "guesses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), index=True)
    turn: Mapped[int] = mapped_column(Integer)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"))
    feedback: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    __table_args__ = (UniqueConstraint("round_id", "turn"), UniqueConstraint("round_id", "entity_id"), UniqueConstraint("round_id", "idempotency_key"))


class Installation(Base):
    __tablename__ = "installation"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="installation")
    deployment_id: Mapped[str] = mapped_column(String(100), unique=True)
    environment: Mapped[str] = mapped_column(String(20))
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperatorJob(Base):
    __tablename__ = "operator_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    admin_subject: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
