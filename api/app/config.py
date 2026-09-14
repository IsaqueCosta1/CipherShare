"""Configuração da aplicação, lida inteiramente de variáveis de ambiente.

Nenhum valor sensível fica embutido no código: tudo chega pelo ambiente, que em
desenvolvimento vem do arquivo `.env` carregado pelo Docker Compose.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores de configuração usados por toda a aplicação."""

    # Banco de dados
    database_url: str

    # Object storage
    storage_endpoint: str
    storage_access_key: str
    storage_secret_key: str
    storage_bucket: str
    storage_secure: bool = False

    # Regras de negócio
    max_upload_bytes: int = 104_857_616
    file_ttl_hours: int = 24

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração, lida uma única vez por processo."""
    return Settings()
