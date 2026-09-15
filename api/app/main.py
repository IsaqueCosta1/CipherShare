"""Ponto de entrada da API.

Regra que atravessa todo o projeto: o servidor nunca vê a chave, o nonce nem o
nome do arquivo original. Ele recebe bytes cifrados e um localizador, e é só.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import logging_config, scheduler, storage
from app.config import get_settings
from app.routers import files, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepara o ambiente na subida e desliga o agendador na parada."""
    # Antes de qualquer outra coisa: garantir que nenhum log registre um
    # localizador completo, inclusive o log de acesso do Uvicorn.
    logging_config.install()

    try:
        storage.ensure_bucket()
        storage.ensure_lifecycle()
    except Exception:
        # Não derrubamos a API: o /api/health passa a reportar o storage como
        # indisponível, o que é mais útil para diagnóstico do que um contêiner
        # em reinício infinito.
        logger.exception("Não foi possível preparar o bucket no object storage")

    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(
    title="Troca Confidencial de Arquivos",
    description=(
        "API que armazena apenas bytes cifrados. A criptografia acontece "
        "inteiramente no navegador."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def reject_oversized_body(request: Request, call_next):
    """Recusa corpos grandes demais antes de lê-los.

    Sem esta barreira, um upload de 2 GB seria inteiramente gravado no disco do
    contêiner antes de o endpoint ter a chance de recusá-lo. O Nginx já corta
    na entrada; esta é a mesma regra aplicada pela própria aplicação, para que
    ela continue valendo se um dia a API for exposta sem o proxy na frente.
    """
    declarado = request.headers.get("content-length")
    if declarado is not None and declarado.isdigit():
        # A folga acomoda o envelope multipart (fronteiras, cabeçalhos de
        # parte e o campo do localizador), que acompanha os bytes da cifra.
        limite = get_settings().max_upload_bytes + 8192
        if int(declarado) > limite:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Arquivo acima do limite de 100 MB."},
            )
    return await call_next(request)


app.include_router(health.router, prefix="/api")
app.include_router(files.router, prefix="/api")
