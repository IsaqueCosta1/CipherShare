"""Endpoint de saúde.

Serve para responder a uma pergunta objetiva: a API consegue falar com o banco
e com o object storage neste instante? Nenhuma informação sobre arquivos
armazenados aparece aqui.
"""

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import storage
from app.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _check_database(session: Session) -> str:
    """Executa a consulta mais simples possível contra o Postgres."""
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        # A mensagem original da exceção pode conter host, usuário e senha do
        # banco, então ela vai para o log do servidor e nunca para a resposta.
        logger.exception("Falha ao verificar o banco de dados")
        return "indisponivel"
    return "ok"


def _check_storage() -> str:
    """Confere que o MinIO responde com as credenciais configuradas."""
    try:
        storage.check_connectivity()
    except Exception:
        logger.exception("Falha ao verificar o object storage")
        return "indisponivel"
    return "ok"


@router.get("/health")
def health(response: Response, session: Session = Depends(get_session)) -> dict:
    """Relata o estado de cada dependência.

    Devolve 200 quando tudo responde e 503 quando qualquer dependência falha,
    de modo que um orquestrador possa usar este endpoint sem ler o corpo.
    """
    dependencies = {
        "database": _check_database(session),
        "storage": _check_storage(),
    }

    everything_ok = all(value == "ok" for value in dependencies.values())
    if not everything_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if everything_ok else "degradado",
        "dependencies": dependencies,
    }
