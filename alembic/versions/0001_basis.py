"""Basis-Schema der Workshop-Pipeline

Revision ID: 0001_basis
Revises:
Create Date: 2026-11-10

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel  # noqa: F401

revision: str = "0001_basis"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _zeit() -> sa.Column:
    return sa.Column("erstellt_am", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "dokument",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("dateiname", sa.String(), nullable=False),
        sa.Column("typ", sa.String(32), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("groesse", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("dokument.id", ondelete="SET NULL")),
        sa.Column("metadaten", postgresql.JSONB(), nullable=False),
        _zeit(),
    )
    op.create_index("ix_dokument_sha256", "dokument", ["sha256"], unique=True)

    op.create_table(
        "textextraktion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dokument_id", sa.Integer(), sa.ForeignKey("dokument.id", ondelete="CASCADE"), nullable=False),
        sa.Column("methode", sa.String(32), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("modell", sa.String()),
        sa.Column("dauer_ms", sa.Integer(), nullable=False),
        sa.Column("ist_aktiv", sa.Boolean(), nullable=False),
        _zeit(),
        sa.UniqueConstraint("dokument_id", "methode"),
    )

    op.create_table(
        "chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("textextraktion_id", sa.Integer(), sa.ForeignKey("textextraktion.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("ende", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed("to_tsvector('german', text)", persisted=True)),
    )
    op.create_index("ix_chunk_tsv", "chunk", ["tsv"], postgresql_using="gin")

    op.create_table(
        "embedding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chunk_id", sa.Integer(), sa.ForeignKey("chunk.id", ondelete="CASCADE"), nullable=False),
        sa.Column("modell", sa.String(), nullable=False),
        sa.Column("vektor", pgvector.sqlalchemy.Vector(), nullable=False),
        _zeit(),
        sa.UniqueConstraint("chunk_id", "modell"),
    )
    op.create_index("ix_embedding_modell", "embedding", ["modell"])

    op.create_table(
        "entitaet",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("textextraktion_id", sa.Integer(), sa.ForeignKey("textextraktion.id", ondelete="CASCADE"), nullable=False),
        sa.Column("methode", sa.String(32), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("normalisiert", sa.String()),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("ende", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float()),
    )

    op.create_table(
        "analyse",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dokument_id", sa.Integer(), sa.ForeignKey("dokument.id", ondelete="CASCADE"), nullable=False),
        sa.Column("art", sa.String(32), nullable=False),
        sa.Column("modell", sa.String(), nullable=False),
        sa.Column("ergebnis", postgresql.JSONB(), nullable=False),
        _zeit(),
        sa.UniqueConstraint("dokument_id", "art"),
    )

    op.create_table(
        "lauf",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schritt", sa.String(), nullable=False),
        sa.Column("dokument_id", sa.Integer(), sa.ForeignKey("dokument.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("modell", sa.String()),
        sa.Column("dauer_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fehler", sa.String()),
        sa.Column("roh_output", postgresql.JSONB()),
        _zeit(),
    )

    # Read-only-Rolle fuer die SQL-Abfrage im Workshop
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='vfm_leser') "
        "THEN CREATE ROLE vfm_leser LOGIN PASSWORD 'vfm_leser'; END IF; END $$;"
    )
    db_name = op.get_bind().execute(sa.text("SELECT current_database()")).scalar()
    quoted = '"' + db_name.replace('"', '""') + '"'
    op.execute(f"GRANT CONNECT ON DATABASE {quoted} TO vfm_leser")
    op.execute("GRANT USAGE ON SCHEMA public TO vfm_leser")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO vfm_leser")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO vfm_leser")
    op.execute("ALTER ROLE vfm_leser SET statement_timeout = '10s'")


def downgrade() -> None:
    # Die Rolle vfm_leser bleibt bewusst bestehen (clusterweit, evtl. von anderen DBs genutzt).
    for tabelle in ("lauf", "analyse", "entitaet", "embedding", "chunk", "textextraktion", "dokument"):
        op.drop_table(tabelle)
