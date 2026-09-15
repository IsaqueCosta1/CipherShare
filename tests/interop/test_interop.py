"""Interoperabilidade entre o cofre.py e o crypto.js.

Este é o teste mais importante do projeto. Ele não confere se cada lado
funciona sozinho — confere se os dois falam a mesma língua, que é a única coisa
capaz de quebrar o sistema inteiro de um jeito silencioso.

O lado Python é exercitado pela linha de comando, exatamente como uma pessoa o
usaria. O lado navegador é exercitado pelas funções que a interface usa, sem
nenhuma reimplementação para efeito de teste.
"""

import base64
import json

import pytest

from tests.conftest import BASE_URL, run_cofre

# Conteúdos variados: vazio, um byte, texto com acentuação e ruído de 100 KB.
PAYLOADS = {
    "vazio": b"",
    "um-byte": b"\x00",
    "texto-acentuado": "Relatório de março — conteúdo confidencial.\n".encode("utf-8"),
    "binario-100kb": bytes(range(256)) * 400,
}


@pytest.fixture
def pagina_cripto(page):
    """Abre a página de teste e espera o módulo ficar disponível."""
    page.goto(f"{BASE_URL}/teste-cripto.html")
    page.wait_for_function("() => window.cofreCrypto !== undefined")
    return page


@pytest.mark.parametrize("nome_do_caso", list(PAYLOADS))
def test_python_cifra_e_navegador_decifra(pagina_cripto, tmp_path, nome_do_caso):
    """Sentido 1: cofre.py cifra, crypto.js decifra, bytes idênticos."""
    original = PAYLOADS[nome_do_caso]
    arquivo = tmp_path / "documento.bin"
    arquivo.write_bytes(original)

    resultado = run_cofre("cifrar", "documento.bin", cwd=tmp_path)
    assert resultado.returncode == 0, resultado.stderr

    cifra = (tmp_path / "documento.bin.cifra").read_bytes()
    credenciais = json.loads((tmp_path / "documento.bin.credenciais.json").read_text())

    # O formato prometido: cifra é o original mais os 16 bytes da etiqueta.
    assert len(cifra) == len(original) + 16

    saida = pagina_cripto.evaluate(
        """async ({ chaveB64, nonceB64, cifraB64 }) => {
            const cripto = window.cofreCrypto;
            const chave = cripto.fromBase64(chaveB64);
            const nonce = cripto.fromBase64(nonceB64);
            const cifra = cripto.fromBase64(cifraB64);
            const conteudo = await cripto.decrypt(chave, nonce, cifra);
            return {
                conteudoB64: cripto.toBase64(conteudo),
                localizador: await cripto.computeLocator(chave),
            };
        }""",
        {
            "chaveB64": credenciais["key"],
            "nonceB64": credenciais["nonce"],
            "cifraB64": base64.b64encode(cifra).decode("ascii"),
        },
    )

    assert base64.b64decode(saida["conteudoB64"]) == original
    # Os dois lados calculam o mesmo localizador a partir da mesma chave.
    assert saida["localizador"] == credenciais["hash"]


@pytest.mark.parametrize("nome_do_caso", list(PAYLOADS))
def test_navegador_cifra_e_python_decifra(pagina_cripto, tmp_path, nome_do_caso):
    """Sentido 2: crypto.js cifra, cofre.py decifra, bytes idênticos."""
    original = PAYLOADS[nome_do_caso]

    saida = pagina_cripto.evaluate(
        """async (conteudoB64) => {
            const cripto = window.cofreCrypto;
            const conteudo = cripto.fromBase64(conteudoB64);
            const chave = cripto.generateKey();
            const nonce = cripto.generateNonce();
            const cifra = await cripto.encrypt(chave, nonce, conteudo);
            return {
                chaveB64: cripto.toBase64(chave),
                nonceB64: cripto.toBase64(nonce),
                cifraB64: cripto.toBase64(cifra),
                localizador: await cripto.computeLocator(chave),
            };
        }""",
        base64.b64encode(original).decode("ascii"),
    )

    cifra = base64.b64decode(saida["cifraB64"])
    assert len(cifra) == len(original) + 16

    (tmp_path / "documento.bin.cifra").write_bytes(cifra)
    (tmp_path / "documento.bin.credenciais.json").write_text(
        json.dumps(
            {
                "version": 1,
                "algorithm": "AES-256-GCM",
                "key": saida["chaveB64"],
                "nonce": saida["nonceB64"],
                "hash": saida["localizador"],
                "filename": "documento.bin",
                "size": len(original),
                "expires_at": "2099-01-01T00:00:00Z",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    resultado = run_cofre(
        "decifrar", "documento.bin.cifra", "documento.bin.credenciais.json", cwd=tmp_path
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "Etiqueta conferida" in resultado.stdout

    assert (tmp_path / "documento.bin").read_bytes() == original


def test_navegador_recusa_cifra_adulterada(pagina_cripto, tmp_path):
    """Um bit trocado precisa ser recusado com a mensagem exata do plano."""
    original = b"conteudo que sera adulterado" * 100

    mensagem = pagina_cripto.evaluate(
        """async (conteudoB64) => {
            const cripto = window.cofreCrypto;
            const conteudo = cripto.fromBase64(conteudoB64);
            const chave = cripto.generateKey();
            const nonce = cripto.generateNonce();
            const cifra = await cripto.encrypt(chave, nonce, conteudo);

            const adulterada = cifra.slice();
            const meio = Math.floor(adulterada.length / 2);
            adulterada[meio] = adulterada[meio] ^ 0xff;

            try {
                await cripto.decrypt(chave, nonce, adulterada);
                return "A adulteração passou despercebida.";
            } catch (erro) {
                return `${erro.name}: ${erro.message}`;
            }
        }""",
        base64.b64encode(original).decode("ascii"),
    )

    assert mensagem == "AuthenticationError: Chave incorreta ou arquivo adulterado."


def test_navegador_recusa_chave_errada(pagina_cripto):
    """Chave trocada produz a mesma recusa — e nunca bytes corrompidos."""
    mensagem = pagina_cripto.evaluate(
        """async () => {
            const cripto = window.cofreCrypto;
            const conteudo = new TextEncoder().encode("mensagem qualquer");
            const chave = cripto.generateKey();
            const nonce = cripto.generateNonce();
            const cifra = await cripto.encrypt(chave, nonce, conteudo);

            const outraChave = cripto.generateKey();
            try {
                await cripto.decrypt(outraChave, nonce, cifra);
                return "Decifrou com a chave errada.";
            } catch (erro) {
                return `${erro.name}: ${erro.message}`;
            }
        }"""
    )

    assert mensagem == "AuthenticationError: Chave incorreta ou arquivo adulterado."


def test_python_recusa_cifra_adulterada(tmp_path):
    """O mesmo comportamento do lado Python, pelo comando de demonstração."""
    arquivo = tmp_path / "documento.bin"
    arquivo.write_bytes(b"conteudo integro" * 64)

    assert run_cofre("cifrar", "documento.bin", cwd=tmp_path).returncode == 0

    resultado = run_cofre(
        "adulterar", "documento.bin.cifra", "documento.bin.credenciais.json", cwd=tmp_path
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "InvalidTag: adulteração detectada" in resultado.stdout


def test_o_localizador_e_o_sha256_da_chave(pagina_cripto):
    """Prova o contrato do localizador contra um vetor calculado em Python."""
    import hashlib

    chave = bytes(range(32))
    esperado = hashlib.sha256(chave).hexdigest()

    calculado = pagina_cripto.evaluate(
        """async (chaveB64) => {
            const cripto = window.cofreCrypto;
            return cripto.computeLocator(cripto.fromBase64(chaveB64));
        }""",
        base64.b64encode(chave).decode("ascii"),
    )

    assert calculado == esperado
    assert len(calculado) == 64


# ---------------------------------------------------------------------------
# Vetor de teste publicado no FORMATO.md
#
# Estes valores estão no documento que outra pessoa usaria para implementar um
# cliente próprio. O teste existe para que o documento não possa divergir do
# código: se alguém mudar o formato, este é o primeiro teste a quebrar.
# ---------------------------------------------------------------------------

VETOR_CHAVE_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
VETOR_NONCE_HEX = "000102030405060708090a0b"
VETOR_TEXTO = "Mensagem confidencial.\n".encode("utf-8")
VETOR_LOCALIZADOR = "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd"
VETOR_CIFRA_HEX = (
    "0a67b868a482a776ad22f8e5d7801c08edb5ee559c55552f687a404940c688926ca525ae8ca566"
)


def test_vetor_do_formato_no_python():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    chave = bytes.fromhex(VETOR_CHAVE_HEX)
    nonce = bytes.fromhex(VETOR_NONCE_HEX)

    cifra = AESGCM(chave).encrypt(nonce, VETOR_TEXTO, None)
    assert cifra.hex() == VETOR_CIFRA_HEX
    assert len(cifra) == len(VETOR_TEXTO) + 16


def test_vetor_do_formato_no_navegador(pagina_cripto):
    saida = pagina_cripto.evaluate(
        """async ({ chaveB64, nonceB64, textoB64 }) => {
            const cripto = window.cofreCrypto;
            const chave = cripto.fromBase64(chaveB64);
            const nonce = cripto.fromBase64(nonceB64);
            const texto = cripto.fromBase64(textoB64);
            const cifra = await cripto.encrypt(chave, nonce, texto);
            return {
                cifraHex: Array.from(cifra)
                    .map((b) => b.toString(16).padStart(2, "0"))
                    .join(""),
                localizador: await cripto.computeLocator(chave),
            };
        }""",
        {
            "chaveB64": base64.b64encode(bytes.fromhex(VETOR_CHAVE_HEX)).decode(),
            "nonceB64": base64.b64encode(bytes.fromhex(VETOR_NONCE_HEX)).decode(),
            "textoB64": base64.b64encode(VETOR_TEXTO).decode(),
        },
    )

    assert saida["cifraHex"] == VETOR_CIFRA_HEX
    assert saida["localizador"] == VETOR_LOCALIZADOR
