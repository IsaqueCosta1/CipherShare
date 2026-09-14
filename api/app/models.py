"""Modelo de dados.

Existe uma única tabela, `files`, e ela guarda o mínimo indispensável para
localizar e expirar uma cifra. Não há coluna para nome de arquivo, tipo MIME,
IP do remetente ou identificador de usuário — a ausência é intencional: o que
não é armazenado não pode vazar.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CHAR, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Valores possíveis da coluna `status`.
STATUS_AVAILABLE = "available"
STATUS_EXPIRED = "expired"


class File(Base):
    """Metadados de uma cifra armazenada no object storage."""

    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # SHA-256 da chave, em hexadecimal minúsculo: sempre 64 caracteres.
    # É o único elo entre quem envia e quem recebe, e o servidor não consegue
    # voltar dele para a chave.
    locator: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)

    # Caminho do objeto dentro do bucket do MinIO.
    object_key: Mapped[str] = mapped_column(Text, nullable=False)

    # Tamanho da cifra (texto original + 16 bytes de etiqueta do AES-GCM).
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text(f"'{STATUS_AVAILABLE}'")
    )
