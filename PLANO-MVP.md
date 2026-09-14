# Plano de Trabalho — MVP de Troca Confidencial de Arquivos

> Documento de especificação para implementação assistida.
> Leia por inteiro antes de escrever a primeira linha de código.

---

## 1. Contexto e objetivo

Construir um sistema web onde o Usuário A envia um arquivo que só o Usuário B consegue abrir, e onde **o servidor nunca tem acesso ao conteúdo original nem à chave de criptografia**.

Toda a criptografia acontece no navegador. O servidor armazena apenas bytes cifrados, indexados por um identificador derivado da chave. O arquivo expira em 24 horas.

Este é um MVP de aprendizado. Prioridade: **código legível e verificável** acima de otimização, abstração ou generalidade.

---

## 2. Instruções para quem implementa

- **Comentários, documentação e mensagens de interface em português do Brasil.** Nomes de variáveis, funções e tabelas em inglês.
- **Não use bibliotecas de criptografia de terceiros.** Apenas a Web Crypto API nativa do navegador (`crypto.subtle`) e a biblioteca `cryptography` no Python. Nada de CryptoJS, forge, ou similares.
- **Frontend em JavaScript puro, sem framework e sem etapa de build.** Sem React, sem Vue, sem bundler, sem TypeScript. Arquivos `.html`, `.css` e `.js` servidos diretamente. Isto é um requisito de legibilidade, não de performance.
- **Ao final de cada fase, escreva ou atualize um `ESTUDO.md`** explicando, em português e em prosa, o que foi construído naquela fase, quais decisões foram tomadas e por quê. Este arquivo é material de estudo, não changelog: explique conceitos, não liste commits.
- **Pare ao final de cada fase** e aguarde confirmação antes de seguir para a próxima.
- Se algum ponto desta especificação estiver ambíguo ou parecer errado, **pergunte antes de decidir sozinho**.

---

## 3. Escopo do MVP

### Incluído

- Cifragem e decifragem no navegador com AES-256-GCM
- Upload da cifra, download da cifra
- Arquivo de credenciais em JSON, gerado e baixado no navegador
- Expiração automática em 24 horas
- Limite de 100 MB por arquivo
- Ambiente completo em Docker Compose

### Explicitamente fora do escopo

Não implemente nada da lista abaixo. Se parecer necessário, pergunte primeiro.

- Cifragem em pedaços (chunking) e Web Workers
- Autenticação de usuários, contas, login
- URLs pré-assinadas do object storage
- Envio de e-mails ou notificações
- Contador de downloads ou download único
- Redis, cache, filas
- Múltiplos arquivos por envio
- Internacionalização

---

## 4. Especificação criptográfica

Esta seção é um contrato. Qualquer divergência entre o navegador e o Python quebra o sistema.

### Parâmetros

| Item | Valor |
|---|---|
| Algoritmo | AES-256-GCM |
| Chave | 32 bytes aleatórios (`crypto.getRandomValues` / `os.urandom`) |
| Nonce | 12 bytes aleatórios, novos a cada cifragem |
| Etiqueta de autenticidade | 128 bits, anexada ao final da cifra |
| Associated data (AAD) | Nenhum nesta versão |
| Localizador | `SHA-256(chave)` em hexadecimal minúsculo, 64 caracteres |

### Formato do arquivo cifrado

Bytes crus, sem cabeçalho, exatamente como sai do AES-GCM: `cifra || etiqueta`.
O tamanho é sempre `tamanho_original + 16`.

### Formato do arquivo de credenciais

```json
{
  "version": 1,
  "algorithm": "AES-256-GCM",
  "key": "<base64 dos 32 bytes>",
  "nonce": "<base64 dos 12 bytes>",
  "hash": "<sha256 da chave em hex>",
  "filename": "<nome original do arquivo>",
  "size": 123456,
  "expires_at": "2026-09-15T15:56:19Z"
}
```

Nome sugerido do arquivo baixado: `credenciais-<8 primeiros caracteres do hash>.json`

### Regras invioláveis

1. A chave e o nonce **nunca** são enviados ao servidor, em nenhum endpoint, cabeçalho, log ou parâmetro de URL.
2. O nome do arquivo original **nunca** chega ao servidor. Ele vive apenas no JSON de credenciais.
3. Toda decifragem fica dentro de `try/catch`. A falha significa "chave incorreta ou arquivo adulterado" e deve ser comunicada exatamente assim ao usuário. Nunca engula esta exceção.
4. Nenhum valor secreto vai para `localStorage` ou `sessionStorage`.
5. O servidor não valida, inspeciona nem descompacta o conteúdo enviado.

### Decisão registrada

O localizador é `SHA-256(chave)`, conforme a arquitetura aprovada. Uma evolução futura é gerar um segredo mestre e derivar chave e localizador separadamente via HKDF, desacoplando os dois. Fora do escopo do MVP, mas registre isso no `ESTUDO.md`.

---

## 5. Arquitetura e stack

```
Navegador  →  Nginx (TLS, proxy reverso)  →  FastAPI  →  MinIO   (cifras)
                                                      →  Postgres (metadados)
```

| Componente | Tecnologia |
|---|---|
| Proxy reverso | Nginx |
| API | Python 3.12 + FastAPI + Uvicorn |
| Banco | PostgreSQL 16 |
| Object storage | MinIO |
| Migrations | Alembic |
| Agendador | APScheduler |
| Testes | pytest + Playwright |
| Orquestração | Docker Compose |

Configuração inteiramente por variáveis de ambiente, com `.env.example` versionado e `.env` no `.gitignore`.

---

## 6. Modelo de dados

Tabela única: `files`

| Coluna | Tipo | Observações |
|---|---|---|
| `id` | `uuid` | chave primária |
| `locator` | `char(64)` | único, indexado |
| `object_key` | `text` | caminho no MinIO |
| `size_bytes` | `bigint` | tamanho da cifra |
| `created_at` | `timestamptz` | |
| `expires_at` | `timestamptz` | indexado |
| `status` | `text` | `available` ou `expired` |

Não existe coluna para nome de arquivo, tipo MIME, IP do remetente ou qualquer identificador de usuário. Isto é intencional.

---

## 7. Contrato da API

Prefixo: `/api`

### `POST /api/files`

Recebe a cifra. `multipart/form-data` com os campos `locator` (string de 64 hex) e `file` (binário).

Deve transmitir os bytes para o MinIO em streaming, sem carregar o arquivo inteiro na memória do processo.

- `201` → `{"locator": "...", "expires_at": "..."}`
- `400` → localizador mal formado
- `409` → localizador já existe
- `413` → acima de 100 MB

### `GET /api/files/{locator}`

Metadados, para o frontend saber se vale a pena baixar.

- `200` → `{"size_bytes": 123, "expires_at": "..."}`
- `404` → não existe **ou** expirou

### `GET /api/files/{locator}/content`

Devolve os bytes cifrados em streaming, com `Content-Type: application/octet-stream`.

- `200` → bytes
- `404` → não existe **ou** expirou

### Regras transversais

- **"Não existe" e "expirou" devem produzir respostas idênticas**, incluindo tempo de resposta aproximado. Distinguir os dois casos revela ao atacante que um localizador já foi válido.
- A validade é conferida contra `expires_at` no banco **em toda leitura**. O lifecycle do MinIO é apenas rede de segurança, nunca a fonte da verdade.
- Nenhum log registra o localizador completo. Se precisar logar, use os 8 primeiros caracteres.

---

## 8. Fases

Cada fase termina com um critério de aceitação verificável por quem não leu o código.

---

### Fase 1 — Infraestrutura

`docker-compose.yml` com Nginx, FastAPI, PostgreSQL e MinIO. Migration inicial criando a tabela `files`. Endpoint `GET /api/health` conferindo conectividade com banco e storage. README com instruções de subida.

**Aceitação:** `docker compose up` sobe tudo, e `curl http://localhost/api/health` responde `200` com o status de cada dependência.

---

### Fase 2 — Núcleo criptográfico e interoperabilidade

Módulo `static/js/crypto.js` exportando quatro funções puras, sem dependência de interface: geração de chave, cifragem, decifragem e cálculo do localizador.

Página de teste manual que cifra e decifra um arquivo local, sem nenhuma chamada ao servidor.

**Teste de interoperabilidade — o mais importante do projeto.** Um script `tests/interop.py` que:

1. cifra um arquivo com a biblioteca `cryptography` do Python
2. abre a página no navegador via Playwright e decifra com o `crypto.js`
3. confere que o resultado é byte a byte idêntico ao original
4. repete no sentido inverso: cifra no navegador, decifra no Python

**Aceitação:** `pytest tests/interop.py` passa nos dois sentidos. Este teste prova que a especificação da seção 4 foi implementada corretamente nas duas pontas.

---

### Fase 3 — Backend

Os três endpoints da seção 7, com streaming de verdade para o MinIO. Validação de formato do localizador, limite de tamanho no Nginx e na aplicação. Tratamento de erros sem vazamento de informação.

Testes de API cobrindo: upload e download bem-sucedidos, localizador duplicado, localizador inválido, arquivo acima do limite, arquivo inexistente, arquivo expirado.

**Aceitação:** `pytest tests/api/` passa. Um upload via `curl` seguido de download devolve bytes idênticos aos enviados.

---

### Fase 4 — Interface

Duas telas, sem framework.

**Envio:** seleção do arquivo → barra de progresso da cifragem → upload → download automático do JSON de credenciais → instrução clara de que o arquivo é irrecuperável sem aquele JSON.

**Recebimento:** upload do JSON de credenciais → verificação de disponibilidade → download da cifra → decifragem → gravação do arquivo com o nome original.

Mensagens de erro em português, específicas: arquivo expirado, credenciais inválidas, falha de autenticação, arquivo acima do limite.

**Aceitação:** o fluxo completo funciona em dois navegadores diferentes. Abrir o DevTools na aba Network durante um envio **não mostra a chave nem o nome do arquivo em nenhuma requisição**.

---

### Fase 5 — Expiração

Job do APScheduler rodando de hora em hora: marca registros vencidos como `expired` e remove os objetos correspondentes do MinIO. Lifecycle rule de 24h configurada no bucket como redundância. Comando administrativo para limpar objetos órfãos.

**Aceitação:** um registro com `expires_at` no passado retorna `404` imediatamente, e o objeto some do MinIO após o job rodar. Teste com o relógio manipulado, não esperando 24 horas.

---

### Fase 6 — Endurecimento e entrega

TLS 1.3 com certificado autoassinado para desenvolvimento. Cabeçalhos: HSTS, `X-Content-Type-Options`, `Referrer-Policy`, e **CSP sem `unsafe-inline`** — o que exige que todo JavaScript esteja em arquivos externos, sem handlers inline no HTML.

Rate limiting no Nginx por IP. Revisão de todos os logs procurando dados sensíveis. Scan de dependências.

Documentação final: `README.md` (como rodar), `FORMATO.md` (especificação da seção 4, para quem for implementar outro cliente), `LIMITACOES.md` (ver abaixo) e o `ESTUDO.md` consolidado.

**Aceitação:** os quatro documentos existem e a aplicação roda em HTTPS com a CSP ativa, sem erros no console.

---

## 9. Limitações a documentar

O `LIMITACOES.md` precisa declarar, em prosa e sem eufemismo:

1. **Perder o arquivo de credenciais significa perder o arquivo.** Não há recuperação, por design. Nem o administrador do sistema pode ajudar.
2. **A criptografia no navegador depende de confiar no servidor que entrega o JavaScript.** Quem controlar o servidor pode, em tese, servir um script modificado que exfiltra a chave. CSP e Subresource Integrity mitigam, não eliminam. Este é o limite fundamental do modelo.
3. **O tamanho do arquivo é visível ao servidor.** O AES-GCM não usa padding.
4. **A chave precisa chegar ao destinatário por um canal separado.** Se o JSON de credenciais e o link forem pelo mesmo e-mail, quem lê o e-mail tem tudo.
5. **Não há autenticação.** Quem tiver o JSON baixa o arquivo.
6. **Limite de 100 MB** por restrição de memória do navegador nesta versão.

---

## 10. Critérios de conclusão do MVP

- [ ] `docker compose up` entrega o sistema funcionando do zero
- [ ] Teste de interoperabilidade Python ↔ navegador passa nos dois sentidos
- [ ] Fluxo completo de envio e recebimento funciona ponta a ponta
- [ ] A aba Network não revela chave, nonce nem nome de arquivo
- [ ] O banco não contém nenhum dado que identifique conteúdo ou usuário
- [ ] Arquivo expirado retorna 404 e desaparece do storage
- [ ] Os quatro documentos estão escritos
- [ ] `ESTUDO.md` cobre as seis fases
