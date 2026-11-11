from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.enums import DokumentTyp, ExtraktionsMethode
from app.models._typen import enum_spalte, jetzt, zeit_spalte


class Dokument(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    sha256: str = Field(unique=True, index=True)
    dateiname: str
    typ: DokumentTyp = Field(sa_column=enum_spalte(DokumentTyp, nullable=False))
    mime: str
    groesse: int
    parent_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("dokument.id", ondelete="SET NULL")),
    )
    metadaten: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, default=dict)
    )
    erstellt_am: datetime = Field(default_factory=jetzt, sa_column=zeit_spalte())

    def dateipfad(self, daten_pfad: str) -> Path:
        return Path(daten_pfad) / self.sha256[:2] / self.sha256


class TextExtraktion(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("dokument_id", "methode"),)

    id: int | None = Field(default=None, primary_key=True)
    dokument_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("dokument.id", ondelete="CASCADE"), nullable=False
        )
    )
    methode: ExtraktionsMethode = Field(
        sa_column=enum_spalte(ExtraktionsMethode, nullable=False)
    )
    text: str
    modell: str | None = None
    dauer_ms: int = 0
    ist_aktiv: bool = False
    erstellt_am: datetime = Field(default_factory=jetzt, sa_column=zeit_spalte())
