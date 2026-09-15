"""Agendador do job de expiração.

O APScheduler roda dentro do próprio processo da API, em uma thread de fundo.
Para um MVP com um único worker isso basta e evita introduzir fila, broker ou
um segundo contêiner — nenhum dos quais está no escopo.

Se um dia a API rodar com vários workers, este job precisará de trava
distribuída ou de um processo dedicado, porque cada worker tentaria expirar os
mesmos registros. A operação é idempotente, então o pior caso hoje seria
trabalho repetido, não perda de dados.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.cleanup import expire_files

logger = logging.getLogger(__name__)

# De hora em hora, conforme o plano.
INTERVAL_HOURS = 1

_scheduler: BackgroundScheduler | None = None


def start() -> None:
    """Liga o agendador e roda uma primeira limpeza logo na subida."""
    global _scheduler

    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_expiration,
        trigger="interval",
        hours=INTERVAL_HOURS,
        id="expire_files",
        # Se o processo ficou parado por horas, não faz sentido acumular
        # execuções atrasadas: uma passada resolve todas as pendências.
        coalesce=True,
        max_instances=1,
        next_run_time=None,
    )
    _scheduler.start()
    logger.info("Agendador iniciado: expiração a cada %d hora(s).", INTERVAL_HOURS)

    # Uma execução imediata evita que um arquivo vencido durante uma parada do
    # sistema fique até uma hora ocupando espaço no storage.
    run_expiration()


def shutdown() -> None:
    """Desliga o agendador na parada da aplicação."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def run_expiration() -> None:
    """Executa a limpeza, sem deixar exceção escapar para dentro do agendador."""
    try:
        expire_files()
    except Exception:
        logger.exception("Falha na execução do job de expiração")
