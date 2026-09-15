"""Acesso ao object storage (MinIO).

O servidor trata cada objeto como uma sequência opaca de bytes: não valida,
não inspeciona e não descompacta nada do que recebe. Para ele, uma cifra é
indistinguível de ruído — que é exatamente o que ela deve parecer.
"""

import logging
from functools import lru_cache

from minio import Minio
from minio.commonconfig import ENABLED, Filter
from minio.error import S3Error
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from app.config import get_settings

logger = logging.getLogger(__name__)


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


def ensure_lifecycle() -> None:
    """Configura a expiração automática de objetos no bucket.

    Esta regra é rede de segurança, não a fonte da verdade: quem decide se um
    arquivo ainda vale é a coluna `expires_at` do banco, conferida em toda
    leitura, e quem apaga os bytes no prazo certo é o job do agendador. O
    lifecycle existe para o caso em que a aplicação passe um longo período fora
    do ar — sem ele, os objetos ficariam indefinidamente.

    A granularidade do S3 para esta regra é de um dia, então ela apaga o que
    tiver mais de 24 horas na próxima varredura do MinIO.
    """
    settings = get_settings()
    configuracao = LifecycleConfig(
        [
            Rule(
                ENABLED,
                rule_id="expira-em-24h",
                rule_filter=Filter(prefix=""),
                expiration=Expiration(days=1),
            )
        ]
    )
    try:
        get_client().set_bucket_lifecycle(settings.storage_bucket, configuracao)
    except S3Error:
        logger.exception("Não foi possível configurar o lifecycle do bucket")


def check_connectivity() -> None:
    """Confere que o storage responde. Levanta exceção se não responder.

    Listar buckets é a chamada mais barata que ainda exige credencial válida
    e rede funcionando.
    """
    get_client().list_buckets()
