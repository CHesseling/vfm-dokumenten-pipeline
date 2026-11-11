"""Gemeinsame Spaltentypen: Enums als einfache Strings (keine nativen PG-Enums)."""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


def enum_spalte(enum_klasse: type[Enum], **kwargs) -> Column:
    """VARCHAR statt nativem PG-Enum - neue Werte brauchen keine Migration."""
    return Column(
        SAEnum(
            enum_klasse,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        **kwargs,
    )


def zeit_spalte() -> Column:
    return Column(DateTime(timezone=True), nullable=False, default=jetzt)
