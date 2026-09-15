"""Testes do endurecimento: TLS, cabeçalhos e política de segurança de conteúdo.

São os critérios da última fase, transformados em asserções para não dependerem
de alguém lembrar de conferir à mão.
"""

import httpx

from tests.conftest import BASE_URL


def test_http_redireciona_para_https():
    endereco_http = BASE_URL.replace("https://", "http://")
    with httpx.Client(verify=False, follow_redirects=False) as cliente:
        resposta = cliente.get(f"{endereco_http}/")
    assert resposta.status_code == 301
    assert resposta.headers["location"].startswith("https://")


def test_cabecalhos_de_seguranca_presentes(http):
    resposta = http.get("/")
    assert resposta.status_code == 200

    assert "max-age=31536000" in resposta.headers["strict-transport-security"]
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.headers["referrer-policy"] == "no-referrer"
    assert resposta.headers["cache-control"] == "no-store"


def test_csp_nao_permite_codigo_embutido(http):
    csp = http.get("/").headers["content-security-policy"]

    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_paginas_nao_tem_javascript_embutido():
    """A CSP só é cumprível se o HTML não depender de código embutido."""
    from pathlib import Path

    for pagina in Path("/work/static").glob("*.html"):
        html = pagina.read_text(encoding="utf-8")
        assert "onclick=" not in html, pagina.name
        assert "onload=" not in html, pagina.name
        # Todo <script> precisa ser uma referência externa, sem corpo.
        for trecho in html.split("<script")[1:]:
            abertura = trecho.split(">", 1)
            assert "src=" in abertura[0], f"script embutido em {pagina.name}"


def test_a_api_responde_apenas_sob_tls(http):
    """O healthcheck continua funcionando depois do endurecimento."""
    resposta = http.get("/api/health")
    assert resposta.status_code == 200
    assert resposta.json()["dependencies"] == {"database": "ok", "storage": "ok"}


def test_o_mascaramento_de_localizador_nos_logs():
    """Nenhum log pode registrar o localizador completo (seção 7 do plano).

    O código da aplicação já escreve apenas oito caracteres; o filtro testado
    aqui é a salvaguarda que cobre o log de acesso do servidor, onde o
    localizador entraria pelo caminho da requisição.
    """
    from app.logging_config import mask

    locator = "a" * 40 + "b" * 24
    assert len(locator) == 64

    assert mask(f'GET /api/files/{locator}/content HTTP/2.0') == (
        "GET /api/files/aaaaaaaa…/content HTTP/2.0"
    )
    # Textos sem localizador passam intactos.
    assert mask("nada a mascarar aqui") == "nada a mascarar aqui"
    # Um hexadecimal mais curto não é um localizador e não deve ser tocado.
    assert mask("deadbeef") == "deadbeef"
