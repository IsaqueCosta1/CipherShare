#!/usr/bin/env python3
"""
cofre.py — cifragem de arquivos com AES-256-GCM.

Este é o núcleo criptográfico do projeto de troca confidencial de arquivos,
escrito em Python para você estudar o conceito antes de portá-lo ao navegador.

O que ele produz, a partir de um arquivo qualquer:

  relatorio.pdf  ->  relatorio.pdf.cifra          (vai para o servidor)
                     relatorio.pdf.credenciais.json  (fica com o usuário)

Uso:
    python3 cofre.py cifrar    relatorio.pdf
    python3 cofre.py decifrar  relatorio.pdf.cifra relatorio.pdf.credenciais.json
    python3 cofre.py adulterar relatorio.pdf.cifra relatorio.pdf.credenciais.json

Requer:  pip install cryptography
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ---------------------------------------------------------------------------
# Constantes do formato. Mudar qualquer uma delas quebra a compatibilidade com
# arquivos já cifrados — por isso o campo "version" no JSON de credenciais.
# ---------------------------------------------------------------------------

VERSAO_FORMATO = 1
ALGORITMO = "AES-256-GCM"
TAMANHO_CHAVE = 32   # 32 bytes = 256 bits
TAMANHO_NONCE = 12   # tamanho recomendado para o modo GCM
TAMANHO_ETIQUETA = 16  # a etiqueta de autenticidade que o GCM anexa à cifra
VALIDADE_HORAS = 24


def b64(dados: bytes) -> str:
    """Bytes crus -> texto base64, para caber dentro de um JSON."""
    return base64.b64encode(dados).decode("ascii")


def de_b64(texto: str) -> bytes:
    """Caminho inverso: texto base64 -> bytes crus."""
    return base64.b64decode(texto)


# ---------------------------------------------------------------------------
# Cifragem
# ---------------------------------------------------------------------------

def cifrar(caminho_origem: str) -> None:
    origem = Path(caminho_origem)
    if not origem.is_file():
        sys.exit(f"Arquivo não encontrado: {origem}")

    # Lemos o arquivo inteiro para a memória. Isso é aceitável para estudo e
    # para arquivos pequenos; a partir de algumas centenas de MB é preciso
    # cifrar em pedaços — é o assunto da etapa 4 do plano.
    dados = origem.read_bytes()

    # 1. A chave: 32 bytes de um gerador criptograficamente seguro.
    #    Não é senha, não é derivada de nada. É ruído.
    chave = AESGCM.generate_key(bit_length=256)

    # 2. O nonce: 12 bytes novos a cada cifragem. Não é segredo, mas o par
    #    (chave, nonce) jamais pode se repetir.
    nonce = os.urandom(TAMANHO_NONCE)

    # 3. O hash da chave: é o endereço do arquivo no servidor. O servidor
    #    consegue localizar a cifra sem nunca conhecer a chave.
    hash_chave = hashlib.sha256(chave).hexdigest()

    # 4. A cifragem propriamente dita. O terceiro argumento é o "associated
    #    data": dados que não são cifrados, mas ficam protegidos pela etiqueta.
    #    Deixamos None por ora; ele reaparece na etapa dos pedaços.
    aesgcm = AESGCM(chave)
    cifra = aesgcm.encrypt(nonce, dados, None)

    destino_cifra = origem.with_suffix(origem.suffix + ".cifra")
    destino_cifra.write_bytes(cifra)

    # 5. As credenciais. Repare no que está aqui e não no servidor: a chave,
    #    o nonce e até o nome do arquivo. O servidor guarda apenas a cifra
    #    indexada pelo hash — ele não sabe nem como o arquivo se chama.
    expira_em = datetime.now(timezone.utc) + timedelta(hours=VALIDADE_HORAS)
    credenciais = {
        "version": VERSAO_FORMATO,
        "algorithm": ALGORITMO,
        "key": b64(chave),
        "nonce": b64(nonce),
        "hash": hash_chave,
        "filename": origem.name,
        "size": len(dados),
        "expires_at": expira_em.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    destino_cred = origem.with_suffix(origem.suffix + ".credenciais.json")
    destino_cred.write_text(json.dumps(credenciais, indent=2), encoding="utf-8")

    print(f"Original .......... {origem}  ({len(dados)} bytes)")
    print(f"Cifra ............. {destino_cifra}  ({len(cifra)} bytes)")
    print(f"Credenciais ....... {destino_cred}")
    print()
    print(f"A cifra ficou {len(cifra) - len(dados)} bytes maior: é a etiqueta de autenticidade.")
    print(f"Hash da chave (o servidor veria só isto): {hash_chave}")
    print()
    print("Guarde o JSON. Sem ele o arquivo é irrecuperável — inclusive por você.")


# ---------------------------------------------------------------------------
# Decifragem
# ---------------------------------------------------------------------------

def carregar_credenciais(caminho: str) -> dict:
    cred = json.loads(Path(caminho).read_text(encoding="utf-8"))

    # Checar a versão antes de qualquer coisa. Um arquivo do futuro deve ser
    # recusado com clareza, não interpretado errado.
    if cred.get("version") != VERSAO_FORMATO:
        sys.exit(f"Versão de formato não suportada: {cred.get('version')}")
    return cred


def decifrar(caminho_cifra: str, caminho_cred: str) -> None:
    cred = carregar_credenciais(caminho_cred)

    chave = de_b64(cred["key"])
    nonce = de_b64(cred["nonce"])
    cifra = Path(caminho_cifra).read_bytes()

    # Conferência de sanidade: o hash das credenciais bate com a chave que
    # elas carregam? Se não, o JSON foi montado errado ou adulterado.
    if hashlib.sha256(chave).hexdigest() != cred["hash"]:
        sys.exit("O hash não corresponde à chave. Credenciais inconsistentes.")

    aesgcm = AESGCM(chave)
    try:
        dados = aesgcm.decrypt(nonce, cifra, None)
    except InvalidTag:
        # Este é o ponto mais importante do script. InvalidTag significa
        # exatamente uma coisa: "a chave está errada OU os dados foram
        # alterados". Nunca trate esta exceção como um erro genérico.
        sys.exit("Falha na autenticação: chave incorreta ou arquivo adulterado.")

    destino = Path(cred["filename"])
    if destino.exists():
        destino = destino.with_name("recuperado_" + destino.name)
    destino.write_bytes(dados)

    print(f"Etiqueta conferida. Conteúdo íntegro.")
    print(f"Arquivo recuperado: {destino}  ({len(dados)} bytes)")


# ---------------------------------------------------------------------------
# Demonstração: o que acontece quando alguém mexe na cifra
# ---------------------------------------------------------------------------

def adulterar(caminho_cifra: str, caminho_cred: str) -> None:
    cred = carregar_credenciais(caminho_cred)
    chave = de_b64(cred["key"])
    nonce = de_b64(cred["nonce"])

    cifra = bytearray(Path(caminho_cifra).read_bytes())
    posicao = len(cifra) // 2
    antes = cifra[posicao]
    cifra[posicao] = antes ^ 0xFF  # inverte todos os bits deste byte

    print(f"Byte {posicao} alterado: {antes:02x} -> {cifra[posicao]:02x}")
    print("Tentando decifrar a versão adulterada...")
    print()

    aesgcm = AESGCM(chave)
    try:
        aesgcm.decrypt(nonce, bytes(cifra), None)
        print("A adulteração passou despercebida. Isto não deveria acontecer.")
    except InvalidTag:
        print("InvalidTag: adulteração detectada, decifragem recusada.")
        print()
        print("Compare com um cifrador sem autenticação (AES-CBC, por exemplo):")
        print("ele devolveria bytes corrompidos sem avisar, e o usuário B")
        print("receberia um arquivo defeituoso achando que está tudo certo.")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Cifragem de arquivos com AES-256-GCM.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("cifrar", help="cifra um arquivo e gera as credenciais")
    p.add_argument("arquivo")

    p = sub.add_parser("decifrar", help="recupera o arquivo original")
    p.add_argument("cifra")
    p.add_argument("credenciais")

    p = sub.add_parser("adulterar", help="demonstra a detecção de adulteração")
    p.add_argument("cifra")
    p.add_argument("credenciais")

    args = parser.parse_args()

    if args.comando == "cifrar":
        cifrar(args.arquivo)
    elif args.comando == "decifrar":
        decifrar(args.cifra, args.credenciais)
    elif args.comando == "adulterar":
        adulterar(args.cifra, args.credenciais)


if __name__ == "__main__":
    main()
