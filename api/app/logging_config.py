"""Mascaramento de localizadores nos logs.

A regra da seção 7 do plano é direta: nenhum log registra o localizador
completo. O código da aplicação já obedece, escrevendo apenas os oito primeiros
caracteres — mas o log de acesso do Uvicorn registra o caminho da requisição
inteiro, e o caminho contém o localizador.

Em vez de desligar o log de acesso (que é útil) ou confiar em cada ponto do
código lembrar da regra, instalamos um filtro que reescreve qualquer sequência
de 64 caracteres hexadecimais antes de ela chegar ao arquivo de log. É uma
salvaguarda, não uma desculpa para escrever segredos em log.

Por que isso importa: o localizador é o SHA-256 da chave. Quem lê um localizador
sabe que aquele arquivo existiu e pode baixar a cifra enquanto ela durar. Ele
não abre nada sem a chave, mas é informação que não precisa ficar espalhada por
arquivos de log e coletores de observabilidade.
"""

import logging
import re

# Exatamente 64 caracteres hexadecimais minúsculos, isolados de outros
# caracteres hexadecimais à esquerda e à direita.
LOCATOR_PATTERN = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")

VISIBLE_CHARS = 8


def mask(texto: str) -> str:
    """Troca cada localizador pelos seus oito primeiros caracteres."""
    return LOCATOR_PATTERN.sub(lambda achado: f"{achado.group(0)[:VISIBLE_CHARS]}…", texto)


class LocatorMaskFilter(logging.Filter):
    """Reescreve a mensagem e os argumentos de cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {chave: mask_value(valor) for chave, valor in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(mask_value(valor) for valor in record.args)

        return True


def mask_value(valor):
    return mask(valor) if isinstance(valor, str) else valor


def install() -> None:
    """Instala o filtro em todos os handlers já configurados.

    É chamado na subida da aplicação, e não no import, porque o Uvicorn monta
    os próprios handlers depois de importar o módulo — instalar antes disso
    deixaria justamente o log de acesso de fora.
    """
    filtro = LocatorMaskFilter()

    def aplicar(logger: logging.Logger) -> None:
        for handler in logger.handlers:
            if not any(isinstance(f, LocatorMaskFilter) for f in handler.filters):
                handler.addFilter(filtro)

    aplicar(logging.getLogger())
    for nome in list(logging.root.manager.loggerDict):
        aplicar(logging.getLogger(nome))
