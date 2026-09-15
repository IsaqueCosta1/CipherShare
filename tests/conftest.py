"""Infraestrutura comum dos testes.

Os testes rodam em um contêiner próprio, na mesma rede do Docker Compose, e
falam com o sistema exatamente como um usuário falaria: pelo Nginx, em HTTPS.
O certificado é autoassinado, então tanto o cliente HTTP quanto o navegador
recebem instrução explícita para aceitá-lo — é a única concessão, e ela vale
apenas para o ambiente de desenvolvimento.
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from minio import Minio
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, text

BASE_URL = os.environ.get("BASE_URL", "https://nginx")
REPO_ROOT = Path("/work")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def http():
    """Cliente HTTP para os testes de API."""
    with httpx.Client(base_url=BASE_URL, verify=False, timeout=600.0) as client:
        yield client


@pytest.fixture(scope="session")
def engine():
    """Conexão direta com o banco, usada para inspecionar e manipular o relógio."""
    return create_engine(os.environ["DATABASE_URL"], future=True)


@pytest.fixture(scope="session")
def storage() -> Minio:
    """Cliente do object storage, para conferir o que está realmente gravado."""
    return Minio(
        os.environ["STORAGE_ENDPOINT"],
        access_key=os.environ["STORAGE_ACCESS_KEY"],
        secret_key=os.environ["STORAGE_SECRET_KEY"],
        secure=os.environ.get("STORAGE_SECURE", "false").lower() == "true",
    )


@pytest.fixture(scope="session")
def bucket() -> str:
    return os.environ["STORAGE_BUCKET"]


@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as playwright:
        yield playwright


# O plano pede que o fluxo funcione em dois navegadores diferentes. Em vez de
# conferir isso à mão, cada teste de navegador roda duas vezes, uma em cada
# motor: o Chromium (base do Chrome e do Edge) e o Firefox, que têm
# implementações independentes da Web Crypto.
NAVEGADORES = os.environ.get("BROWSERS", "chromium,firefox").split(",")


@pytest.fixture(scope="session", params=NAVEGADORES)
def browser(playwright_instance, request):
    navegador = getattr(playwright_instance, request.param).launch()
    yield navegador
    navegador.close()


@pytest.fixture
def context(browser):
    """Contexto novo a cada teste: nada de estado vazando entre eles."""
    ctx = browser.new_context(ignore_https_errors=True, accept_downloads=True)
    ctx.set_default_timeout(120_000)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    return context.new_page()


# ---------------------------------------------------------------------------
# Utilidades compartilhadas
# ---------------------------------------------------------------------------


def random_locator() -> str:
    """Um localizador sintático válido, sem chave por trás."""
    return secrets.token_hex(32)


def run_cofre(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Executa o cofre.py como o usuário executaria, pela linha de comando."""
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "cofre.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def upload(http_client, locator: str, ciphertext: bytes) -> httpx.Response:
    """Envia uma cifra pela API, no mesmo formato que o navegador usa."""
    return http_client.post(
        "/api/files",
        data={"locator": locator},
        files={"file": ("cifra.bin", ciphertext, "application/octet-stream")},
    )


def set_expiration_to_past(engine, locator: str) -> None:
    """Manipula o relógio do registro, em vez de esperar 24 horas."""
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "UPDATE files SET expires_at = now() - interval '1 minute' "
                "WHERE locator = :locator"
            ),
            {"locator": locator},
        )


def fetch_row(engine, locator: str):
    with engine.begin() as conexao:
        return conexao.execute(
            text("SELECT object_key, size_bytes, status FROM files WHERE locator = :locator"),
            {"locator": locator},
        ).one_or_none()
