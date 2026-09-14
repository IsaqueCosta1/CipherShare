"""Acesso ao object storage (MinIO).

O servidor trata cada objeto como uma sequência opaca de bytes: não valida,
não inspeciona e não descompacta nada do que recebe. Para ele, uma cifra é
indistinguível de ruído — que é exatamente o que ela deve parecer.
"""

from functools import lru_cache

from minio import Minio

from app.config import get_settings


@lru_cache
def get_client() -> Minio:
    """Devolve o cliente do MinIO, criado uma única vez por processo."""
    settings = get_settings()
    return Minio(
        settings.storage_endpoint,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        secure=settings.storage_secure,
    )


def ensure_bucket() -> None:
    """Cria o bucket de cifras caso ele ainda não exista.

    Chamado na subida da API para que o ambiente funcione a partir de um
    `docker compose up` em uma máquina limpa, sem nenhum passo manual.
    """
    settings = get_settings()
    client = get_client()
    if not client.bucket_exists(settings.storage_bucket):
        client.make_bucket(settings.storage_bucket)


def check_connectivity() -> None:
    """Confere que o storage responde. Levanta exceção se não responder.

    Listar buckets é a chamada mais barata que ainda exige credencial válida
    e rede funcionando.
    """
    get_client().list_buckets()
