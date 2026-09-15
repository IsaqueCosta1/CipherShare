#!/usr/bin/env python3
"""Comandos administrativos.

Uso, de dentro do contêiner da API:

    docker compose exec api python manage.py expirar
    docker compose exec api python manage.py orfaos
    docker compose exec api python manage.py orfaos --remover
"""

import argparse
import logging

from app.cleanup import expire_files, find_orphans, remove_orphans

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def comando_expirar() -> None:
    """Roda agora a mesma limpeza que o agendador faz de hora em hora."""
    total = expire_files()
    print(f"Arquivos expirados nesta execução: {total}")


def comando_orfaos(remover: bool) -> None:
    """Lista — e opcionalmente apaga — objetos sem registro correspondente."""
    orfaos = find_orphans()

    if not orfaos:
        print("Nenhum objeto órfão no bucket.")
        return

    print(f"Objetos órfãos encontrados: {len(orfaos)}")
    for chave in orfaos:
        print(f"  {chave}")

    if remover:
        removidos = remove_orphans(orfaos)
        print(f"Objetos removidos: {removidos}")
    else:
        print()
        print("Nada foi apagado. Use --remover para excluir estes objetos.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tarefas administrativas do sistema.")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("expirar", help="expira agora os arquivos vencidos")

    p = sub.add_parser("orfaos", help="procura objetos no storage sem registro no banco")
    p.add_argument("--remover", action="store_true", help="apaga os órfãos encontrados")

    args = parser.parse_args()

    if args.comando == "expirar":
        comando_expirar()
    elif args.comando == "orfaos":
        comando_orfaos(args.remover)


if __name__ == "__main__":
    main()
