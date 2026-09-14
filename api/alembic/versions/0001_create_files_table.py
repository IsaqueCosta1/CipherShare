"""Cria a tabela files

Revision ID: 0001
Revises:
Create Date: 2026-09-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Localizador: SHA-256 da chave em hexadecimal minúsculo, 64 caracteres.
        sa.Column("locator", sa.CHAR(length=64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        # Tamanho da cifra, não do arquivo original.
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'available'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("locator"),
    )

    # Índice de expiração: o job de limpeza varre por expires_at, e toda
    # leitura confere a validade contra esta coluna.
    op.create_index("ix_files_expires_at", "files", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_files_expires_at", table_name="files")
    op.drop_table("files")
