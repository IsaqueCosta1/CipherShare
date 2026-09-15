"""Expiração de arquivos.

O banco é a fonte da verdade sobre validade: um registro vencido já retorna 404
na primeira leitura, antes mesmo de qualquer limpeza acontecer. O trabalho deste
módulo é outro — apagar de fato os bytes do storage, para que o conteúdo deixe
de existir e não apenas de ser servido.

São duas rotinas:

- `expire_files`, que roda de hora em hora pelo agendador;
- `find_orphans`, para o caso em que um objeto sobra no storage sem registro
  correspondente no banco.
"""

import logging
from datetime import datetime, timezone

from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.database import SessionFactory
from app.models import STATUS_AVAILABLE, STATUS_EXPIRED, File as FileRecord

logger = logging.getLogger(__name__)


def expire_files(session: Session | None = None) -> int:
    """Remove do storage os arquivos vencidos e marca os registros como expirados.

    Devolve quantos arquivos foram expirados. A ordem importa: primeiro o
    objeto sai do storage, depois o registro muda de status. Se o processo cair
    no meio, o registro continua `available` e vencido — a próxima execução
    tenta de novo, e enquanto isso a API já responde 404.
    """
    sessao_propria = session is None
    sessao = session or SessionFactory()
    settings = get_settings()

    try:
        vencidos = sessao.scalars(
            select(FileRecord).where(
                FileRecord.status == STATUS_AVAILABLE,
                FileRecord.expires_at <= datetime.now(timezone.utc),
            )
        ).all()

        total = 0
        for record in vencidos:
            try:
                storage.get_client().remove_object(settings.storage_bucket, record.object_key)
            except S3Error as erro:
                if erro.code != "NoSuchKey":
                    # Falhou por outro motivo: não marcamos como expirado, para
                    # que a próxima execução tente novamente.
                    logger.exception(
                        "Falha ao remover o objeto do arquivo %s…", record.locator[:8]
                    )
                    continue

            record.status = STATUS_EXPIRED
            total += 1

        sessao.commit()

        if total:
            logger.info("Expiração: %d arquivo(s) removidos do storage.", total)
        return total
    finally:
        if sessao_propria:
            sessao.close()


def find_orphans(session: Session | None = None) -> list[str]:
    """Lista objetos do bucket que nenhum registro disponível referencia.

    Um órfão é resultado de uma falha parcial: o objeto foi gravado e o
    registro não, ou o registro foi expirado e a remoção falhou. Ele ocupa
    espaço sem ser alcançável por ninguém.
    """
    sessao_propria = session is None
    sessao = session or SessionFactory()
    settings = get_settings()

    try:
        referenciados = {
            chave
            for (chave,) in sessao.execute(
                select(FileRecord.object_key).where(FileRecord.status == STATUS_AVAILABLE)
            )
        }

        objetos = storage.get_client().list_objects(settings.storage_bucket, recursive=True)
        return [obj.object_name for obj in objetos if obj.object_name not in referenciados]
    finally:
        if sessao_propria:
            sessao.close()


def remove_orphans(object_keys: list[str]) -> int:
    """Apaga do storage a lista de objetos órfãos informada."""
    settings = get_settings()
    removidos = 0
    for chave in object_keys:
        try:
            storage.get_client().remove_object(settings.storage_bucket, chave)
            removidos += 1
        except S3Error:
            logger.exception("Falha ao remover o objeto órfão %s", chave)
    return removidos
