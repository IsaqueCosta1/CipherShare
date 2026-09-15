"""Testes dos três endpoints da API.

O conteúdo enviado aqui é ruído: para o servidor, uma cifra e uma sequência
aleatória de bytes são a mesma coisa, e é justamente essa indiferença que estes
testes exercitam.
"""

import hashlib
import os
import re

import pytest

from tests.conftest import fetch_row, random_locator, set_expiration_to_past, upload

# Formato de data devolvido pela API, igual ao do cofre.py.
FORMATO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Limite da aplicação: 100 MiB de original mais os 16 bytes da etiqueta.
LIMITE_BYTES = 100 * 1024 * 1024 + 16


def test_upload_e_download_devolvem_os_mesmos_bytes(http, engine):
    """O caminho feliz: o que sobe é exatamente o que desce."""
    locator = random_locator()
    conteudo = os.urandom(64 * 1024)

    resposta = upload(http, locator, conteudo)
    assert resposta.status_code == 201

    corpo = resposta.json()
    assert corpo["locator"] == locator
    assert FORMATO_DATA.match(corpo["expires_at"])

    baixado = http.get(f"/api/files/{locator}/content")
    assert baixado.status_code == 200
    assert baixado.headers["content-type"] == "application/octet-stream"
    assert baixado.content == conteudo
    assert hashlib.sha256(baixado.content).hexdigest() == hashlib.sha256(conteudo).hexdigest()


def test_metadados_informam_tamanho_e_validade(http):
    locator = random_locator()
    conteudo = os.urandom(4096)
    assert upload(http, locator, conteudo).status_code == 201

    resposta = http.get(f"/api/files/{locator}")
    assert resposta.status_code == 200

    corpo = resposta.json()
    assert corpo["size_bytes"] == len(conteudo)
    assert FORMATO_DATA.match(corpo["expires_at"])
    # O servidor não sabe o nome do arquivo, e portanto não pode devolvê-lo.
    assert "filename" not in corpo


def test_localizador_duplicado_responde_409(http):
    locator = random_locator()
    assert upload(http, locator, os.urandom(512)).status_code == 201

    repetido = upload(http, locator, os.urandom(512))
    assert repetido.status_code == 409


def test_localizador_mal_formado_responde_400_no_upload(http):
    for invalido in ["curto", "Z" * 64, "ABCDEF" + "0" * 58, "0" * 63, "0" * 65]:
        resposta = upload(http, invalido, os.urandom(128))
        assert resposta.status_code == 400, invalido


def test_localizador_mal_formado_responde_404_na_leitura(http):
    """Na leitura, mal formado não se distingue de inexistente."""
    resposta = http.get("/api/files/nao-e-um-localizador")
    assert resposta.status_code == 404


def test_arquivo_inexistente_responde_404(http):
    locator = random_locator()
    assert http.get(f"/api/files/{locator}").status_code == 404
    assert http.get(f"/api/files/{locator}/content").status_code == 404


def test_arquivo_expirado_responde_404(http, engine):
    """Com o relógio manipulado, o registro vencido some da vista na hora."""
    locator = random_locator()
    assert upload(http, locator, os.urandom(2048)).status_code == 201
    assert http.get(f"/api/files/{locator}").status_code == 200

    set_expiration_to_past(engine, locator)

    assert http.get(f"/api/files/{locator}").status_code == 404
    assert http.get(f"/api/files/{locator}/content").status_code == 404

    # O registro continua no banco até o job passar — e mesmo assim a API já
    # responde 404. A verdade sobre validade é o expires_at, não o status.
    linha = fetch_row(engine, locator)
    assert linha is not None


def test_expirado_e_inexistente_sao_indistinguiveis(http, engine):
    """A resposta precisa ser idêntica, ou ela conta que o localizador já valeu."""
    expirado = random_locator()
    assert upload(http, expirado, os.urandom(1024)).status_code == 201
    set_expiration_to_past(engine, expirado)

    inexistente = random_locator()

    a = http.get(f"/api/files/{expirado}")
    b = http.get(f"/api/files/{inexistente}")

    assert a.status_code == b.status_code == 404
    assert a.json() == b.json()
    assert a.headers.get("content-type") == b.headers.get("content-type")

    a_conteudo = http.get(f"/api/files/{expirado}/content")
    b_conteudo = http.get(f"/api/files/{inexistente}/content")
    assert a_conteudo.status_code == b_conteudo.status_code == 404
    assert a_conteudo.json() == b_conteudo.json()


def test_corpo_vazio_responde_400(http):
    assert upload(http, random_locator(), b"").status_code == 400


@pytest.mark.lento
def test_acima_do_limite_responde_413(http):
    """Um corpo maior que 100 MiB + 16 bytes é recusado.

    O tamanho é escolhido de propósito acima do limite da aplicação e abaixo do
    corte do Nginx, para que quem responda seja o código Python — o limite do
    proxy tem teste próprio, e é a primeira barreira, não a única.
    """
    excesso = LIMITE_BYTES + 4096
    conteudo = b"\x00" * excesso

    resposta = upload(http, random_locator(), conteudo)
    assert resposta.status_code == 413


def test_o_banco_nao_guarda_nada_sobre_o_conteudo(http, engine):
    """O modelo de dados não tem onde escrever nome, tipo ou dono."""
    from sqlalchemy import text

    with engine.begin() as conexao:
        colunas = {
            linha[0]
            for linha in conexao.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'files'")
            )
        }

    assert colunas == {
        "id",
        "locator",
        "object_key",
        "size_bytes",
        "created_at",
        "expires_at",
        "status",
    }
