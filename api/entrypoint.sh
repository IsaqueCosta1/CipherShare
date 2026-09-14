#!/bin/sh
# Subida da API: primeiro as migrations, depois o servidor.
#
# Rodar `alembic upgrade head` a cada subida é seguro — o Alembic sabe quais
# revisões já foram aplicadas e não repete nenhuma.
set -e

echo "Aplicando migrations..."
alembic upgrade head

echo "Iniciando a API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
