"""Um arquivo binário grande, de verdade, pelo caminho de verdade.

50 MB atravessando o navegador, o Nginx, a API, o MinIO e o caminho de volta,
com o resultado conferido por hash. É o teste que pega o que os pequenos não
pegam: limites de corpo, buffers, timeouts e qualquer lugar onde alguém tenha
carregado o arquivo inteiro na memória sem perceber.
"""

import hashlib
import json
import os

import httpx
import pytest

from tests.conftest import BASE_URL

TAMANHO = 50 * 1024 * 1024


@pytest.mark.lento
def test_arquivo_de_50_mb_ponta_a_ponta(page, tmp_path):
    conteudo = os.urandom(TAMANHO)
    hash_original = hashlib.sha256(conteudo).hexdigest()

    arquivo = tmp_path / "video-grande.bin"
    arquivo.write_bytes(conteudo)

    # --- Envio -------------------------------------------------------------
    page.goto(f"{BASE_URL}/")

    with page.expect_file_chooser() as seletor:
        page.click("#dropzone")
    seletor.value.set_files(str(arquivo))
    page.wait_for_selector("#painel-arquivo", state="visible")

    with page.expect_download(timeout=300_000) as download_credenciais:
        page.click("#botao-enviar")
    page.wait_for_selector("#painel-resultado", state="visible", timeout=300_000)

    caminho_credenciais = download_credenciais.value.path()
    credenciais = json.loads(open(caminho_credenciais, encoding="utf-8").read())
    assert credenciais["size"] == TAMANHO

    # A cifra guardada tem exatamente 16 bytes a mais que o original.
    with httpx.Client(base_url=BASE_URL, verify=False, timeout=600.0) as cliente:
        metadados = cliente.get(f"/api/files/{credenciais['hash']}").json()
    assert metadados["size_bytes"] == TAMANHO + 16

    # --- Recebimento -------------------------------------------------------
    page.goto(f"{BASE_URL}/receber.html")

    with page.expect_file_chooser() as seletor:
        page.click("#dropzone")
    seletor.value.set_files(str(caminho_credenciais))
    page.wait_for_selector("#painel-disponibilidade", state="visible")

    with page.expect_download(timeout=300_000) as download_arquivo:
        page.click("#botao-baixar")
    page.wait_for_selector("#painel-resultado", state="visible", timeout=300_000)

    recuperado = open(download_arquivo.value.path(), "rb").read()

    assert len(recuperado) == TAMANHO
    assert hashlib.sha256(recuperado).hexdigest() == hash_original
