# Estudo — Troca Confidencial de Arquivos

Este documento acompanha a construção do sistema fase a fase. Ele não é um
changelog: o objetivo é explicar o que foi construído, quais decisões foram
tomadas e, principalmente, por quê. Quem ler daqui a seis meses deve conseguir
entender o raciocínio sem precisar reconstruí-lo a partir do código.

---

## Fase 1 — Infraestrutura

### O que existe ao fim desta fase

Quatro serviços orquestrados pelo Docker Compose — Nginx, FastAPI, PostgreSQL e
MinIO —, a tabela `files` criada por migration e um endpoint `GET /api/health`
que responde se a API consegue falar com o banco e com o object storage.

Nada de criptografia ainda, nada de upload. Esta fase existe para que, a partir
daqui, toda pergunta sobre o comportamento do sistema possa ser respondida
rodando o sistema, e não imaginando-o.

### Por que quatro serviços, e não um

O sistema poderia guardar os arquivos no disco local da API. Separar em quatro
processos não é enfeite de arquitetura; cada um resolve um problema distinto:

**Nginx** é a única porta de entrada. Isso concentra num só lugar aquilo que na
Fase 6 vira endurecimento: TLS, cabeçalhos de segurança, limite de tamanho de
corpo e rate limiting. A API nem sequer publica porta para o host — quem quiser
falar com ela passa pelo proxy.

**PostgreSQL** guarda metadados, que são dados pequenos, estruturados e
consultados por critérios (“quais registros já venceram?”). Um índice em
`expires_at` responde essa pergunta em tempo desprezível; um `ls` num diretório
não responde.

**MinIO** guarda os bytes cifrados, que são grandes, opacos e nunca consultados
por conteúdo. Object storage é feito exatamente para isso: entrega em streaming,
sem carregar o arquivo inteiro na memória do processo. Ele também fala o
protocolo S3, então trocar por um serviço de nuvem depois é questão de mudar
variáveis de ambiente.

A separação também deixa evidente uma propriedade central do projeto: **os dois
depósitos, somados, não bastam para abrir arquivo nenhum**. O banco tem um hash
e um caminho; o storage tem ruído. A chave não está em lugar nenhum dos dois.

### A tabela `files` e o que ela deliberadamente não tem

```
id          uuid         chave primária
locator     char(64)     único, indexado
object_key  text         caminho no MinIO
size_bytes  bigint       tamanho da cifra
created_at  timestamptz
expires_at  timestamptz  indexado
status      text         'available' ou 'expired'
```

Não há coluna para nome de arquivo, tipo MIME, IP do remetente nem qualquer
identificador de usuário. A ausência é a decisão mais importante do modelo de
dados: o que não é armazenado não vaza em invasão, não aparece em intimação
judicial e não precisa ser protegido.

O `locator` é `SHA-256(chave)` em hexadecimal minúsculo — daí o `char(64)`,
tamanho fixo e conhecido. Ele é o único elo entre quem envia e quem recebe, e é
uma via de mão única: o servidor consegue conferir se um localizador existe, mas
não consegue voltar dele para a chave, porque inverter SHA-256 não é viável.

O `size_bytes` guarda o tamanho da **cifra**, não do arquivo original. Como o
AES-GCM acrescenta 16 bytes de etiqueta de autenticidade e não usa padding, os
dois valores diferem por exatamente 16 bytes — o que, aliás, significa que o
tamanho aproximado do original é visível ao servidor. Isso é uma limitação real
do desenho e será declarada sem eufemismo no `LIMITACOES.md`.

O `status` parece redundante diante do `expires_at`, mas os dois respondem
perguntas diferentes: `expires_at` é a **verdade** sobre a validade, conferida
em toda leitura; `status` registra que o job de limpeza já **passou** por ali e
apagou o objeto do storage. Um registro pode estar vencido e ainda `available`
durante a hora que falta para o job rodar — e, mesmo nesse intervalo, a API já
responde 404, porque quem manda é `expires_at`.

### Por que SQLAlchemy síncrono num framework assíncrono

O FastAPI é assíncrono, e a tentação é declarar tudo com `async def`. Optamos
pelo contrário: as rotas são `def` comuns, e o FastAPI as executa num pool de
threads.

O motivo é que o cliente do MinIO é síncrono. Misturar os dois modelos exige
envolver chamadas bloqueantes em executores, e uma chamada bloqueante esquecida
dentro de uma corrotina trava o event loop inteiro — um bug silencioso, que só
aparece sob carga. Com rotas síncronas, o código lê de cima para baixo, o
streaming da Fase 3 continua sendo streaming de verdade, e não existe essa
classe de erro. O plano pede legibilidade e verificabilidade acima de
otimização; num MVP de troca de arquivos, o gargalo é a rede, não o agendador de
tarefas do Python.

### Migrations em vez de `create_all`

O SQLAlchemy sabe criar tabelas a partir dos modelos, com uma linha. Não é o que
fazemos: o esquema nasce de uma migration do Alembic, aplicada pelo
`entrypoint.sh` a cada subida do contêiner.

A diferença aparece na segunda alteração do esquema, não na primeira.
`create_all` cria o que não existe e ignora o que mudou — um banco que já tem a
tabela antiga simplesmente continua com ela. A migration é um passo versionado,
com ordem definida e registro do que já foi aplicado, e por isso descreve a
mesma história em qualquer ambiente. Rodar `alembic upgrade head` em toda subida
é seguro justamente porque o Alembic sabe onde parou.

Uma consequência prática: o `alembic.ini` não contém a URL do banco. Ela é lida
da mesma configuração que a aplicação usa, para não haver dois lugares dizendo
coisas diferentes sobre o mesmo banco.

### O endpoint de saúde e o que ele não conta

`GET /api/health` executa um `SELECT 1` no Postgres e um `list_buckets` no
MinIO — as chamadas mais baratas que ainda provam que há rede e credencial
válida. Devolve `200` quando tudo responde e `503` quando qualquer dependência
falha, para que um orquestrador possa decidir olhando apenas o código HTTP.

O detalhe que importa está no tratamento do erro. A exceção de conexão do
Postgres traz host, usuário e, dependendo do driver, a senha na mensagem. Essa
mensagem vai para o log do servidor; a resposta HTTP recebe apenas a palavra
`indisponivel`. Este é o primeiro exemplo de um princípio que vale para todo o
projeto: **a resposta ao cliente diz o mínimo necessário para agir, e o log
guarda o resto**. Na Fase 3 o mesmo princípio reaparece com outra roupa, quando
“não existe” e “expirou” tiverem que produzir respostas idênticas.

### Decisões registradas nesta fase

**Imagem do MinIO vinda do quay.io.** O repositório `minio/minio` no Docker Hub
não está mais acessível publicamente; a imagem oficial vem de
`quay.io/minio/minio`, com a tag fixada numa release específica. Tag fixa, e não
`latest`, para que a subida de amanhã produza o mesmo ambiente da de hoje.

**Limite de upload de 104.857.616 bytes.** O plano fixa 100 MB por arquivo
original. Como o AES-GCM acrescenta 16 bytes de etiqueta, a cifra correspondente
a um arquivo de exatamente 100 MiB tem 100 MiB + 16 bytes. O limite da API é
conferido sobre a cifra — o único objeto que o servidor vê —, então ele vale
100 MiB + 16. Sem esse ajuste, um arquivo de exatamente 100 MiB seria recusado
por 16 bytes.

**Limite conferido em dois lugares.** O Nginx corta o corpo em 101 MiB e a
aplicação confere o tamanho de novo por si mesma. A duplicação é intencional: o
proxy é a primeira barreira, nunca a única. Se algum dia a API for exposta
diretamente, ou se o Nginx for reconfigurado por engano, a regra continua valendo.

**Portas do host configuráveis.** `HTTP_PORT` e `MINIO_CONSOLE_PORT` existem
porque a máquina de desenvolvimento pode já ter algo ocupando 80 ou 9001. Os
valores padrão são os do plano; a variável só evita que um conflito de porta
vire um obstáculo à primeira subida.

### Uma decisão que fica registrada para o futuro

O localizador é `SHA-256(chave)`, conforme a arquitetura aprovada. Isso acopla
duas coisas que conceitualmente são distintas: o **segredo** que decifra e o
**endereço** que localiza. O acoplamento é seguro — a função de hash não é
invertível —, mas é rígido: quem tem a chave tem necessariamente o endereço, e
não há como dar a alguém o direito de consultar a existência de um arquivo sem
lhe dar a chave.

A evolução natural é gerar um segredo mestre aleatório e derivar dele, via HKDF,
duas coisas independentes: uma chave de cifragem e um localizador. Com isso os
dois deixam de ser computáveis um a partir do outro e passam a poder circular
por canais diferentes. Está fora do escopo deste MVP e fica anotado aqui como o
primeiro candidato a mudança de uma versão 2.

### Como verificar esta fase

```bash
cp .env.example .env
docker compose up --build
curl http://localhost/api/health
```

A resposta deve ser `200` com `{"status":"ok","dependencies":{"database":"ok","storage":"ok"}}`.

Para ver o caminho degradado funcionando, derrube uma dependência e consulte o
mesmo endereço:

```bash
docker compose stop postgres
curl -i http://localhost/api/health     # 503, database: indisponivel
docker compose start postgres
```
