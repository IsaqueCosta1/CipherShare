"""Endpoints de arquivos.

Três operações, e nenhuma delas conhece a chave: guardar bytes cifrados sob um
localizador, informar se um localizador ainda é válido e devolver os bytes.

Duas regras atravessam todo este módulo:

1. "Não existe" e "expirou" produzem exatamente a mesma resposta. Distinguir os
   dois casos contaria a um atacante que determinado localizador já foi válido
   um dia — e, como o localizador é o hash da chave, isso é informação sobre a
   chave.
2. Nenhum log registra o localizador inteiro. Oito caracteres bastam para
   correlacionar eventos e não bastam para reconstruir o endereço.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.database import get_session
from app.models import STATUS_AVAILABLE, File as FileRecord

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

# O localizador é o SHA-256 da chave em hexadecimal minúsculo: 64 caracteres.
LOCATOR_PATTERN = re.compile(r"[0-9a-f]{64}")

# Resposta única para arquivo inexistente e para arquivo expirado.
NOT_FOUND_DETAIL = "Arquivo não encontrado ou expirado."

# Tamanho dos pedaços lidos do storage ao devolver a cifra.
STREAM_CHUNK_SIZE = 64 * 1024


def format_instant(momento: datetime) -> str:
    """Formata uma data no mesmo padrão usado pelo cofre.py: 2026-09-15T15:56:19Z."""
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short(locator: str) -> str:
    """Prefixo do localizador, para uso em log."""
    return locator[:8]


@router.post("/files", status_code=status.HTTP_201_CREATED)
def create_file(
    locator: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    """Recebe a cifra e a guarda sob o localizador informado.

    Os bytes são repassados ao object storage em streaming: o processo lê o
    corpo em pedaços e nunca mantém o arquivo inteiro na memória.
    """
    settings = get_settings()

    if not LOCATOR_PATTERN.fullmatch(locator):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Localizador mal formado: esperados 64 caracteres hexadecimais minúsculos.",
        )

    size_bytes = measure(file)

    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O corpo enviado está vazio.",
        )

    if size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Arquivo acima do limite de 100 MB.",
        )

    existing = session.scalar(select(FileRecord.id).where(FileRecord.locator == locator))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um arquivo com este localizador.",
        )

    # O nome do objeto é aleatório e não deriva do localizador: quem olhar a
    # listagem do bucket não descobre nada sobre quais localizadores existem.
    object_key = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.file_ttl_hours)

    storage.get_client().put_object(
        settings.storage_bucket,
        object_key,
        data=file.file,
        length=size_bytes,
        content_type="application/octet-stream",
    )

    record = FileRecord(
        locator=locator,
        object_key=object_key,
        size_bytes=size_bytes,
        expires_at=expires_at,
        status=STATUS_AVAILABLE,
    )
    session.add(record)

    try:
        session.commit()
    except IntegrityError:
        # Dois envios do mesmo localizador ao mesmo tempo: o índice único
        # decide, e o objeto recém-gravado é removido para não virar órfão.
        session.rollback()
        remove_object(object_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um arquivo com este localizador.",
        )

    logger.info("Cifra armazenada: localizador %s…, %d bytes", short(locator), size_bytes)

    return {"locator": locator, "expires_at": format_instant(expires_at)}


@router.get("/files/{locator}")
def get_metadata(locator: str, session: Session = Depends(get_session)) -> dict:
    """Informa tamanho e validade, para o navegador decidir se vale baixar."""
    record = find_available(session, locator)
    return {
        "size_bytes": record.size_bytes,
        "expires_at": format_instant(record.expires_at),
    }


@router.get("/files/{locator}/content")
def get_content(locator: str, session: Session = Depends(get_session)) -> StreamingResponse:
    """Devolve os bytes cifrados, em streaming."""
    record = find_available(session, locator)
    settings = get_settings()

    try:
        resposta = storage.get_client().get_object(settings.storage_bucket, record.object_key)
    except S3Error:
        # O objeto sumiu do storage — por lifecycle, por remoção manual — e o
        # banco ainda não sabe. Para quem pergunta, é o mesmo que não existir.
        logger.warning("Objeto ausente no storage para o localizador %s…", short(locator))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)

    def stream():
        try:
            yield from resposta.stream(STREAM_CHUNK_SIZE)
        finally:
            resposta.close()
            resposta.release_conn()

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={"Content-Length": str(record.size_bytes)},
    )


def find_available(session: Session, locator: str) -> FileRecord:
    """Busca um registro válido ou levanta 404.

    O caminho é o mesmo para as três formas de fracasso — localizador mal
    formado, inexistente ou vencido —: uma consulta indexada e a mesma resposta.
    A validade é decidida aqui, contra `expires_at`, e não pelo lifecycle do
    storage, que é apenas rede de segurança.
    """
    if not LOCATOR_PATTERN.fullmatch(locator):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)

    record = session.scalar(select(FileRecord).where(FileRecord.locator == locator))

    if record is None or record.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)

    return record


def measure(file: UploadFile) -> int:
    """Mede o corpo recebido sem lê-lo para a memória.

    O Starlette já escreveu o upload em um arquivo temporário; aqui só
    perguntamos o tamanho e voltamos o ponteiro para o início, de onde o
    cliente do MinIO vai ler em pedaços.
    """
    file.file.seek(0, 2)  # 2 = fim do arquivo
    tamanho = file.file.tell()
    file.file.seek(0)
    return tamanho


def remove_object(object_key: str) -> None:
    """Remove um objeto do storage, registrando falhas sem interromper o fluxo."""
    settings = get_settings()
    try:
        storage.get_client().remove_object(settings.storage_bucket, object_key)
    except S3Error:
        logger.exception("Não foi possível remover o objeto %s", object_key)
