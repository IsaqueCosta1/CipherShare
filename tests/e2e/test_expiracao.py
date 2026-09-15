"""Expiração: o que vence some da vista na hora e some do disco depois.

O relógio é manipulado no banco — esperar 24 horas não seria um teste, seria
uma vigília. O job exercitado aqui é o mesmo que o agendador executa em
produção, importado do código da API, e não uma cópia escrita para o teste.
"""

import hashlib
import os

import pytest
from minio.error import S3Error

from tests.conftest import fetch_row, random_locator, set_expiration_to_past, upload


def objeto_existe(storage, bucket, object_key) -> bool:
    try:
        storage.stat_object(bucket, object_key)
        return True
    except S3Error as erro:
        if erro.code in ("NoSuchKey", "NoSuchObject"):
            return False
        raise


def test_registro_vencido_some_da_api_e_depois_do_storage(http, engine, storage, bucket):
    from app.cleanup import expire_files

    locator = random_locator()
    conteudo = os.urandom(8192)
    assert upload(http, locator, conteudo).status_code == 201

    object_key, size_bytes, status = fetch_row(engine, locator)
    assert status == "available"
    assert size_bytes == len(conteudo)
    assert objeto_existe(storage, bucket, object_key)

    # Relógio manipulado: o registro passa a estar vencido agora mesmo.
    set_expiration_to_past(engine, locator)

    # Primeiro efeito, imediato: a API já não entrega nada.
    assert http.get(f"/api/files/{locator}").status_code == 404
    assert http.get(f"/api/files/{locator}/content").status_code == 404

    # O objeto, porém, ainda está lá: quem apaga é o job.
    assert objeto_existe(storage, bucket, object_key)

    expirados = expire_files()
    assert expirados >= 1

    # Segundo efeito: os bytes deixaram de existir.
    assert not objeto_existe(storage, bucket, object_key)
    assert fetch_row(engine, locator)[2] == "expired"

    # E continua respondendo 404, agora sem nada por trás.
    assert http.get(f"/api/files/{locator}/content").status_code == 404


def test_registro_valido_sobrevive_ao_job(http, engine, storage, bucket):
    """A limpeza não pode levar junto o que ainda está no prazo."""
    from app.cleanup import expire_files

    locator = random_locator()
    assert upload(http, locator, os.urandom(4096)).status_code == 201
    object_key = fetch_row(engine, locator)[0]

    expire_files()

    assert objeto_existe(storage, bucket, object_key)
    assert http.get(f"/api/files/{locator}").status_code == 200
    assert fetch_row(engine, locator)[2] == "available"


def test_objetos_orfaos_sao_encontrados_e_removidos(storage, bucket):
    """O comando administrativo enxerga objetos sem registro correspondente."""
    import io

    from app.cleanup import find_orphans, remove_orphans

    chave_orfa = f"orfao-de-teste-{os.urandom(8).hex()}"
    dados = os.urandom(256)
    storage.put_object(bucket, chave_orfa, io.BytesIO(dados), length=len(dados))

    orfaos = find_orphans()
    assert chave_orfa in orfaos

    assert remove_orphans([chave_orfa]) == 1
    assert not objeto_existe(storage, bucket, chave_orfa)


def test_bucket_tem_regra_de_ciclo_de_vida(storage, bucket):
    """A rede de segurança de 24h está configurada no próprio storage."""
    configuracao = storage.get_bucket_lifecycle(bucket)
    assert configuracao is not None

    regras = configuracao.rules
    assert len(regras) >= 1
    assert regras[0].expiration.days == 1
    assert regras[0].status == "Enabled"
