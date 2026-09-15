"""Fluxo completo pelo navegador, com a rede sob vigilância.

Este arquivo contém a prova automatizada da promessa central do sistema: fazer
um envio inteiro e afirmar que nenhuma requisição carregou a chave, o nonce ou
o nome do arquivo.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from tests.conftest import BASE_URL

INSTRUMENTACAO = (Path(__file__).parent / "instrumentacao.js").read_text(encoding="utf-8")

# Nome com acento e espaço de propósito: se algum lugar do sistema tratasse o
# nome do arquivo de forma descuidada, é aqui que apareceria.
NOME_DO_ARQUIVO = "relatório confidencial.bin"


def capturar_requisicoes(page):
    """Registra url, método e cabeçalhos de toda requisição que sair da aba.

    Cobre tudo — documentos, folhas de estilo, módulos JavaScript, chamadas de
    API —, e não apenas o que a aplicação emite conscientemente.
    """
    capturadas = []

    def ao_requisitar(requisicao):
        capturadas.append(
            {
                "url": requisicao.url,
                "metodo": requisicao.method,
                "cabecalhos": dict(requisicao.headers),
            }
        )

    page.on("request", ao_requisitar)
    return capturadas


def corpos_enviados(page):
    """Devolve o corpo completo de cada requisição emitida pela aplicação.

    Espera as leituras assíncronas dos blobs terminarem antes de ler o
    registro, para que nenhuma parte volte pela metade.
    """
    page.wait_for_function("() => window.__capturas.every((c) => c.pendentes === 0)")
    return page.evaluate("() => window.__capturas")


def test_envio_e_recebimento_ponta_a_ponta(page, tmp_path):
    conteudo_original = os.urandom(32 * 1024)
    arquivo = tmp_path / NOME_DO_ARQUIVO
    arquivo.write_bytes(conteudo_original)

    page.add_init_script(INSTRUMENTACAO)
    requisicoes = capturar_requisicoes(page)
    erros_de_console = []
    page.on("console", lambda msg: erros_de_console.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda erro: erros_de_console.append(str(erro)))

    # --- Envio -------------------------------------------------------------
    page.goto(f"{BASE_URL}/")

    with page.expect_file_chooser() as seletor:
        page.click("#dropzone")
    seletor.value.set_files(str(arquivo))

    page.wait_for_selector("#painel-arquivo", state="visible")
    assert NOME_DO_ARQUIVO in page.inner_text("#arquivo-nome")

    with page.expect_download() as download_credenciais:
        page.click("#botao-enviar")
    page.wait_for_selector("#painel-resultado", state="visible")

    assert page.get_attribute("#estado", "data-estado") == "concluido"

    caminho_credenciais = download_credenciais.value.path()
    credenciais = json.loads(open(caminho_credenciais, encoding="utf-8").read())

    assert download_credenciais.value.suggested_filename == (
        f"credenciais-{credenciais['hash'][:8]}.json"
    )
    assert credenciais["version"] == 1
    assert credenciais["algorithm"] == "AES-256-GCM"
    assert credenciais["filename"] == NOME_DO_ARQUIVO
    assert credenciais["size"] == len(conteudo_original)
    assert len(base64.b64decode(credenciais["key"])) == 32
    assert len(base64.b64decode(credenciais["nonce"])) == 12
    assert hashlib.sha256(base64.b64decode(credenciais["key"])).hexdigest() == credenciais["hash"]

    # O aviso de irrecuperabilidade precisa estar visível no fim do envio.
    aviso = page.inner_text(".aviso-critico")
    assert "irrecuperável" in aviso
    assert "administrador" in aviso

    # --- A prova: nada sensível saiu do navegador --------------------------
    chave_b64 = credenciais["key"]
    nonce_b64 = credenciais["nonce"]
    chave_bytes = base64.b64decode(chave_b64)
    nonce_bytes = base64.b64decode(nonce_b64)

    segredos_em_texto = {
        "chave (base64)": chave_b64,
        "nonce (base64)": nonce_b64,
        "nome do arquivo": NOME_DO_ARQUIVO,
        "nome do arquivo (url)": quote(NOME_DO_ARQUIVO),
    }

    # (a) URL e cabeçalhos de toda e qualquer requisição da aba.
    requisicoes_de_api = [r for r in requisicoes if "/api/" in r["url"]]
    assert requisicoes_de_api, "nenhuma requisição à API foi capturada"

    for requisicao in requisicoes:
        onde = f"{requisicao['metodo']} {requisicao['url']}"
        texto = requisicao["url"] + " " + " ".join(requisicao["cabecalhos"].values())
        for rotulo, segredo in segredos_em_texto.items():
            assert segredo not in texto, f"{rotulo} apareceu em {onde}"

    # (b) O corpo completo de cada requisição emitida pela aplicação, parte a
    #     parte, com o conteúdo binário dos blobs.
    capturas = corpos_enviados(page)
    envios = [c for c in capturas if c["metodo"] == "POST"]
    assert len(envios) == 1, "esperada exatamente uma requisição de envio"

    envio = envios[0]
    assert envio["url"] == "/api/files"

    # O multipart tem exatamente dois campos, e nenhum deles é segredo.
    assert {parte["nome"] for parte in envio["partes"]} == {"locator", "file"}

    for captura in capturas:
        onde = f"{captura['metodo']} {captura['url']}"
        for parte in captura["partes"]:
            if parte["tipo"] == "texto":
                for rotulo, segredo in segredos_em_texto.items():
                    assert segredo not in parte["valor"], f"{rotulo} em {onde}/{parte['nome']}"
                continue

            # Parte binária: conferimos os bytes crus e as duas formas de texto.
            conteudo = base64.b64decode(parte["conteudoB64"])
            assert chave_bytes not in conteudo, f"bytes da chave em {onde}"
            assert nonce_bytes not in conteudo, f"bytes do nonce em {onde}"
            for rotulo, segredo in segredos_em_texto.items():
                assert segredo.encode("utf-8") not in conteudo, f"{rotulo} em {onde}"

            # O nome de arquivo declarado no multipart é genérico e fixo.
            assert parte["nomeDeArquivo"] == "cifra.bin"

    # O que o servidor recebe é a cifra, e nada além dela: tamanho original
    # mais os 16 bytes da etiqueta.
    parte_cifra = next(p for p in envio["partes"] if p["nome"] == "file")
    assert parte_cifra["tamanho"] == len(conteudo_original) + 16

    # O localizador, esse sim, precisa ter sido enviado: é o endereço.
    parte_localizador = next(p for p in envio["partes"] if p["nome"] == "locator")
    assert parte_localizador["valor"] == credenciais["hash"]

    # Regra 4 do plano: nenhum valor secreto foi parar no armazenamento local.
    armazenamento = page.evaluate(
        "() => ({ local: window.localStorage.length, sessao: window.sessionStorage.length })"
    )
    assert armazenamento == {"local": 0, "sessao": 0}

    # --- Recebimento -------------------------------------------------------
    page.goto(f"{BASE_URL}/receber.html")

    with page.expect_file_chooser() as seletor:
        page.click("#dropzone")
    seletor.value.set_files(str(caminho_credenciais))

    page.wait_for_selector("#painel-disponibilidade", state="visible")
    assert credenciais["hash"] in page.inner_text("#dado-localizador")
    assert NOME_DO_ARQUIVO in page.inner_text("#dado-nome")

    with page.expect_download() as download_arquivo:
        page.click("#botao-baixar")
    page.wait_for_selector("#painel-resultado", state="visible")

    assert download_arquivo.value.suggested_filename == NOME_DO_ARQUIVO

    recuperado = open(download_arquivo.value.path(), "rb").read()
    assert recuperado == conteudo_original
    assert hashlib.sha256(recuperado).hexdigest() == hashlib.sha256(conteudo_original).hexdigest()

    assert page.get_attribute("#estado", "data-estado") == "concluido"
    assert erros_de_console == []


def test_credenciais_invalidas_produzem_mensagem_especifica(page, tmp_path):
    """Cada recusa previsível tem mensagem própria — nada de "erro inesperado"."""
    page.goto(f"{BASE_URL}/receber.html")

    casos = [
        ("nao-json.json", b"isto nao e json", "não é um JSON válido"),
        (
            "versao-futura.json",
            json.dumps({"version": 99, "algorithm": "AES-256-GCM"}).encode(),
            "Versão de formato não suportada",
        ),
        (
            "hash-inconsistente.json",
            json.dumps(
                {
                    "version": 1,
                    "algorithm": "AES-256-GCM",
                    "key": base64.b64encode(bytes(32)).decode(),
                    "nonce": base64.b64encode(bytes(12)).decode(),
                    "hash": "0" * 64,
                    "filename": "x.bin",
                    "size": 1,
                    "expires_at": "2099-01-01T00:00:00Z",
                }
            ).encode(),
            "hash não corresponde à chave",
        ),
    ]

    for nome, conteudo, trecho_esperado in casos:
        caminho = tmp_path / nome
        caminho.write_bytes(conteudo)

        with page.expect_file_chooser() as seletor:
            page.click("#dropzone")
        seletor.value.set_files(str(caminho))

        page.wait_for_selector("#erro", state="visible")
        assert trecho_esperado in page.inner_text("#erro"), nome
        assert page.get_attribute("#estado", "data-estado") == "erro"


def test_arquivo_expirado_e_avisado_antes_do_download(page, tmp_path, http, engine):
    """Quem recebe precisa saber do vencimento antes de esperar por nada."""
    from tests.conftest import random_locator, set_expiration_to_past, upload

    # Um envio qualquer, cujas credenciais montamos à mão para poder vencer o
    # registro sem passar pela interface.
    chave = os.urandom(32)
    nonce = os.urandom(12)
    locator = hashlib.sha256(chave).hexdigest()

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    cifra = AESGCM(chave).encrypt(nonce, b"conteudo qualquer", None)
    assert upload(http, locator, cifra).status_code == 201
    set_expiration_to_past(engine, locator)

    credenciais = tmp_path / "credenciais-expirado.json"
    credenciais.write_text(
        json.dumps(
            {
                "version": 1,
                "algorithm": "AES-256-GCM",
                "key": base64.b64encode(chave).decode(),
                "nonce": base64.b64encode(nonce).decode(),
                "hash": locator,
                "filename": "documento.bin",
                "size": 17,
                "expires_at": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    page.goto(f"{BASE_URL}/receber.html")
    with page.expect_file_chooser() as seletor:
        page.click("#dropzone")
    seletor.value.set_files(str(credenciais))

    page.wait_for_selector("#erro", state="visible")
    assert "expirado ou inexistente" in page.inner_text("#erro")
    # O painel de download nem chega a aparecer.
    assert page.is_hidden("#painel-disponibilidade")
