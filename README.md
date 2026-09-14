# Troca Confidencial de Arquivos

Sistema web para enviar um arquivo que só o destinatário consegue abrir. Toda a
criptografia acontece no navegador: o servidor guarda apenas bytes cifrados,
indexados por um localizador derivado da chave, e os descarta em 24 horas.

O servidor nunca vê a chave, o nonce nem o nome do arquivo original.

> **Estado atual: Fase 1 concluída (infraestrutura).**
> As fases seguintes — núcleo criptográfico, endpoints de upload e download,
> interface, expiração automática e endurecimento — ainda não foram
> implementadas. O plano completo está em [PLANO-MVP.md](PLANO-MVP.md) e as
> decisões de cada fase em [ESTUDO.md](ESTUDO.md).

## Requisitos

- Docker com o plugin Compose (`docker compose version` deve responder)
- Portas 80 e 9001 livres no host (ambas configuráveis, veja abaixo)

## Como subir

```bash
cp .env.example .env
docker compose up --build
```

Na primeira subida o Compose baixa as imagens, constrói a imagem da API, aplica
as migrations e cria o bucket no MinIO. Nenhum passo manual é necessário.

Para conferir que tudo está de pé:

```bash
curl http://localhost/api/health
```

A resposta esperada é `200` com o estado de cada dependência:

```json
{"status":"ok","dependencies":{"database":"ok","storage":"ok"}}
```

Se alguma dependência estiver fora, o mesmo endpoint responde `503` e aponta
qual delas falhou:

```json
{"status":"degradado","dependencies":{"database":"indisponivel","storage":"ok"}}
```

## Serviços

| Serviço | Papel | Acesso a partir do host |
|---|---|---|
| `nginx` | Proxy reverso; única porta de entrada | http://localhost |
| `api` | FastAPI (Python 3.12) | apenas via Nginx |
| `postgres` | Metadados dos arquivos | apenas pela rede interna |
| `minio` | Bytes cifrados | console em http://localhost:9001 |

O console do MinIO aceita as credenciais de `MINIO_ROOT_USER` e
`MINIO_ROOT_PASSWORD`. Ele é útil para confirmar, olhando com os próprios
olhos, que o que está armazenado é ilegível.

## Configuração

Toda a configuração vem de variáveis de ambiente. O arquivo `.env.example` está
versionado e documenta cada uma delas; o `.env`, que guarda os valores reais,
não entra no Git.

Se as portas 80 ou 9001 já estiverem ocupadas na sua máquina, ajuste `HTTP_PORT`
e `MINIO_CONSOLE_PORT` no `.env` — o restante continua funcionando sem
alterações.

## Comandos úteis

```bash
docker compose logs -f api          # acompanhar os logs da API
docker compose down                 # derrubar o ambiente
docker compose down -v              # derrubar e apagar banco e storage
docker compose exec api alembic current   # revisão de migration aplicada
```

## Estrutura

```
api/                   aplicação FastAPI
  app/
    config.py          configuração lida do ambiente
    database.py        conexão com o PostgreSQL
    models.py          tabela `files`
    storage.py         cliente do MinIO
    routers/health.py  GET /api/health
  alembic/             migrations
nginx/nginx.conf       proxy reverso
docker-compose.yml     orquestração dos quatro serviços
```
