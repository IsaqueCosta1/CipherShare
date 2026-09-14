"""Conexão com o PostgreSQL.

Usamos o SQLAlchemy em modo síncrono de propósito: as rotas são declaradas com
`def` (e não `async def`), então o FastAPI as executa em um pool de threads.
Isso evita misturar código assíncrono com os clientes síncronos do MinIO e
mantém o fluxo de leitura do código linear, que é a prioridade deste MVP.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Classe base das tabelas mapeadas."""


_settings = get_settings()

# pool_pre_ping evita entregar uma conexão que o banco já fechou (comum quando
# o Postgres reinicia enquanto a API continua de pé).
engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)

SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependência do FastAPI: abre uma sessão por requisição e a fecha ao fim."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
