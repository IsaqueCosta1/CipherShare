# Troca Confidencial de Arquivos

Sistema web para enviar um arquivo que só o destinatário consegue abrir. Toda a
criptografia acontece no navegador: o servidor recebe bytes cifrados indexados
por um localizador derivado da chave, e os apaga em 24 horas.

**O servidor nunca vê a chave, o nonce nem o nome do arquivo original.** Não é
uma promessa de política de privacidade — é uma propriedade verificável, e há um
teste automatizado que intercepta todas as requisições de um envio completo para
provar isso a cada execução da suíte.

| Documento | Para quê |
|---|---|
| [`ESTUDO.md`](ESTUDO.md) | Como o sistema funciona e por que foi feito assim |
| [`FORMATO.md`](FORMATO.md) | A especificação criptográfica, para implementar outro cliente |
| [`LIMITACOES.md`](LIMITACOES.md) | O que o sistema **não** protege. Leia antes de confiar nele |
| [`PLANO-MVP.md`](PLANO-MVP.md) | A especificação original do projeto |

---

## Como subir

Requisitos: Docker com o plugin Compose. Nada mais.

```bash
cp .env.example .env
docker compose up --build
```

Na primeira subida o Compose baixa as imagens, constrói a imagem da API, aplica
as migrations, cria o bucket no MinIO com a regra de expiração e gera um
certificado TLS autoassinado. Nenhum passo manual é necessário.

Depois disso, abra **<https://localhost>**. O navegador vai avisar que o
certificado não é confiável — ele é autoassinado, gerado na sua máquina; aceite
a exceção para seguir.

Conferência rápida pela linha de comando (o `-k` aceita o certificado local):

```bash
curl -k https://localhost/api/health
```

```json
{"status":"ok","dependencies":{"database":"ok","storage":"ok"}}
```

Se alguma dependência estiver fora, o mesmo endereço responde `503` dizendo
qual. O HTTP na porta 80 existe apenas para redirecionar ao HTTPS.

### Se as portas estiverem ocupadas

O `.env` controla as portas publicadas no host: `HTTP_PORT`, `HTTPS_PORT` e
`MINIO_CONSOLE_PORT`. Ajuste, suba de novo, e o resto continua funcionando.

---

## As três telas

| Endereço | O que faz |
|---|---|
| <https://localhost/> | Envio: escolher, cifrar, enviar, baixar as credenciais |
| <https://localhost/receber.html> | Recebimento: credenciais, baixar, decifrar, salvar |
| <https://localhost/teste-cripto.html> | Teste manual do núcleo criptográfico, sem tocar no servidor |

O fluxo completo é: quem envia escolhe um arquivo e recebe de volta um
`credenciais-XXXXXXXX.json`; quem recebe abre a segunda tela e arrasta esse
JSON. O arquivo de credenciais precisa viajar por um canal diferente do
restante — a razão está na [limitação 4](LIMITACOES.md).

---

## Como rodar os testes

A suíte roda em um contêiner próprio, com os navegadores do Playwright já
instalados. Ela conversa com o sistema pelo Nginx, em HTTPS, como um usuário.

```bash
# Tudo: 39 casos, 55 execuções (os testes de navegador rodam em Chromium e Firefox)
docker compose --profile test run --rm tests pytest tests/ -v

# Só a interoperabilidade cofre.py ↔ crypto.js, nos dois sentidos
docker compose --profile test run --rm tests pytest tests/interop -v

# Só a API
docker compose --profile test run --rm tests pytest tests/api -v

# Pulando o que move dezenas de megabytes
docker compose --profile test run --rm tests pytest tests/ -m "not lento"

# Em um navegador só, quando a rodada precisa ser rápida
docker compose --profile test run --rm -e BROWSERS=chromium tests pytest tests/
```

O que cada pasta cobre:

| Pasta | Cobertura |
|---|---|
| `tests/interop/` | O `cofre.py` e o `crypto.js` produzem e leem exatamente o mesmo formato, nos dois sentidos, incluindo o vetor publicado no `FORMATO.md` |
| `tests/api/` | Os três endpoints, todos os casos de erro, os cabeçalhos de segurança e a CSP |
| `tests/e2e/` | Fluxo completo no navegador, vigilância da rede, expiração com relógio manipulado e um arquivo de 50 MB conferido por hash |

Os testes que dirigem o navegador rodam duas vezes, em Chromium e em Firefox.
Para rodar em um só, defina `BROWSERS=chromium`.

---

## Linha de comando

O `cofre.py` na raiz é a implementação de referência da criptografia, em Python.
Ele funciona sozinho, sem o sistema no ar:

```bash
pip install cryptography

python3 cofre.py cifrar    relatorio.pdf
python3 cofre.py decifrar  relatorio.pdf.cifra relatorio.pdf.credenciais.json
python3 cofre.py adulterar relatorio.pdf.cifra relatorio.pdf.credenciais.json
```

Os arquivos que ele gera são intercambiáveis com os do navegador: cifre aqui e
decifre na tela de recebimento, ou o contrário.

Tarefas administrativas, de dentro do contêiner da API:

```bash
docker compose exec api python manage.py expirar         # roda a limpeza agora
docker compose exec api python manage.py orfaos          # lista objetos sem registro
docker compose exec api python manage.py orfaos --remover
```

---

## Arquitetura

```
Navegador  →  Nginx (TLS 1.3, CSP, rate limit)  →  FastAPI  →  MinIO    (cifras)
                                                            →  Postgres (metadados)
```

| Componente | Tecnologia | Papel |
|---|---|---|
| `nginx` | Nginx 1.27 | Única porta de entrada: TLS, cabeçalhos, limites, arquivos estáticos |
| `api` | Python 3.12 + FastAPI | Três endpoints; nunca toca em chave nem em conteúdo |
| `postgres` | PostgreSQL 16 | Uma tabela, `files`, com o mínimo indispensável |
| `minio` | MinIO | Bytes cifrados, opacos, com lifecycle de 24h como rede de segurança |

```
api/                    aplicação FastAPI
  app/
    config.py           configuração lida do ambiente
    database.py         conexão com o PostgreSQL
    models.py           a tabela `files`
    storage.py          cliente do MinIO e regra de ciclo de vida
    cleanup.py          expiração e objetos órfãos
    scheduler.py        job de hora em hora
    logging_config.py   mascaramento de localizadores em log
    routers/            health.py e files.py
  alembic/              migrations
  manage.py             comandos administrativos
static/                 frontend, servido direto pelo Nginx
  js/crypto.js          o núcleo criptográfico do navegador
  js/credenciais.js     leitura e escrita do JSON de credenciais
  js/api.js             as três chamadas ao servidor
  js/enviar.js          tela de envio
  js/receber.js         tela de recebimento
nginx/                  configuração do proxy e geração do certificado
tests/                  suíte completa
cofre.py                implementação de referência em Python
```

O frontend não tem etapa de build: são arquivos `.html`, `.css` e `.js` servidos
como estão. Editar uma tela e recarregar a página basta — não há bundler,
transpilador ou framework no caminho.

---

## Segurança

O que está configurado:

- **TLS 1.3** apenas, com certificado autoassinado para desenvolvimento.
- **CSP sem `unsafe-inline`**: todo o JavaScript vive em arquivos externos e não
  há um único `onclick=` nos documentos. Um script injetado na página não executa.
- **HSTS**, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY` e `Permissions-Policy` restritiva.
- **Rate limiting por IP** no Nginx, separado para leitura e envio.
- **Localizadores mascarados nos logs**: nem o Nginx nem a aplicação registram
  os 64 caracteres completos — apenas os oito primeiros.
- **Limite de tamanho em dois lugares**: no proxy e na aplicação.

Varredura de dependências (a suíte roda contra as versões fixadas em
`api/requirements.txt` e `tests/requirements.txt`):

```bash
docker run --rm -v "$PWD/api/requirements.txt:/req.txt:ro" python:3.12-slim \
  sh -c "pip install -q pip-audit && pip-audit -r /req.txt"
```

Em produção, o certificado autoassinado precisa ser trocado por um emitido por
uma autoridade reconhecida, e vale revisar a retenção do log de acesso do Nginx,
que registra endereços IP como qualquer servidor web.

**Antes de confiar no sistema, leia [`LIMITACOES.md`](LIMITACOES.md).** Em
particular, a limitação 2: criptografia no navegador protege contra um servidor
curioso, não contra um servidor malicioso.

---

## Comandos úteis

```bash
docker compose logs -f api            # acompanhar os logs da API
docker compose ps                     # estado dos serviços
docker compose down                   # derrubar o ambiente
docker compose down -v                # derrubar e apagar banco, storage e certificado
docker compose exec api alembic current
```
