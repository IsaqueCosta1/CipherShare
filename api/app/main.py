"""Ponto de entrada da API.

Regra que atravessa todo o projeto: o servidor nunca vê a chave, o nonce nem o
nome do arquivo original. Ele recebe bytes cifrados e um localizador, e é só.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import storage
from app.routers import health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepara o ambiente na subida da aplicação."""
    try:
        storage.ensure_bucket()
    except Exception:
        # Não derrubamos a API: o /api/health passa a reportar o storage como
        # indisponível, o que é mais útil para diagnóstico do que um contêiner
        # em reinício infinito.
        logger.exception("Não foi possível preparar o bucket no object storage")
    yield


app = FastAPI(
    title="Troca Confidencial de Arquivos",
    description=(
        "API que armazena apenas bytes cifrados. A criptografia acontece "
        "inteiramente no navegador."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/api")
