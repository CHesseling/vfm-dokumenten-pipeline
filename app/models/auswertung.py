from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlmodel import Field, SQLModel

from app.enums import AnalyseArt, LaufStatus, NerMethode
from app.models._typen import enum_spalte, jetzt, zeit_spalte


def _fk(ziel: str, ondelete: str, nullable: bool = False) -> Column:
    return Column(Integer, ForeignKey(ziel, ondelete=ondelete), nullable=nullable)


class Chunk(SQLModel, table=True):
    __table_args__ = (Index("ix_chunk_tsv", "tsv", postgresql_using="gin"),)

    id: int | None = Field(default=None, primary_key=True)
    textextraktion_id: int = Field(
        sa_column=_fk("textextraktion.id", "CASCADE")
    )
    position: int
    start: int
    ende: int
    text: str
    tsv: str | None = Field(
        default=None,
        sa_column=Column(TSVECTOR, Computed("to_tsvector('german', text)", persisted=True)),
    )


class Embedding(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("chunk_id", "modell"),)

    id: int | None = Field(default=None, primary_key=True)
    chunk_id: int = Field(sa_column=_fk("chunk.id", "CASCADE"))
    modell: str = Field(index=True)
    vektor: list[float] = Field(sa_column=Column(Vector(), nullable=False))
    erstellt_am: datetime = Field(default_factory=jetzt, sa_column=zeit_spalte())


class Entitaet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    textextraktion_id: int = Field(
        sa_column=_fk("textextraktion.id", "CASCADE")
    )
    methode: NerMethode = Field(sa_column=enum_spalte(NerMethode, nullable=False))
    label: str
    text: str
    normalisiert: str | None = None
    start: int
    ende: int
    score: float | None = None


class Analyse(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("dokument_id", "art"),)

    id: int | None = Field(default=None, primary_key=True)
    dokument_id: int = Field(sa_column=_fk("dokument.id", "CASCADE"))
    art: AnalyseArt = Field(sa_column=enum_spalte(AnalyseArt, nullable=False))
    modell: str
    ergebnis: dict = Field(sa_column=Column(JSONB, nullable=False))
    erstellt_am: datetime = Field(default_factory=jetzt, sa_column=zeit_spalte())


class Lauf(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    schritt: str
    dokument_id: int | None = Field(
        default=None, sa_column=_fk("dokument.id", "SET NULL", nullable=True)
    )
    provider: str
    modell: str | None = None
    dauer_ms: int = 0
    status: LaufStatus = Field(sa_column=enum_spalte(LaufStatus, nullable=False))
    fehler: str | None = None
    roh_output: dict | None = Field(default=None, sa_column=Column(JSONB))
    erstellt_am: datetime = Field(default_factory=jetzt, sa_column=zeit_spalte())
