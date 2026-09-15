# Formato criptográfico

Especificação do formato usado por este sistema, completa o bastante para
alguém implementar outro cliente — em qualquer linguagem — sem ler o código
existente.

Há duas implementações de referência neste repositório, e elas são testadas uma
contra a outra a cada execução da suíte:

- [`cofre.py`](cofre.py), em Python, com a biblioteca `cryptography`;
- [`static/js/crypto.js`](static/js/crypto.js), no navegador, com a Web Crypto API.

---

## 1. Parâmetros

| Item | Valor |
|---|---|
| Algoritmo | AES-256-GCM |
| Chave | 32 bytes (256 bits) de origem criptograficamente aleatória |
| Nonce | 12 bytes aleatórios, novos a cada cifragem |
| Etiqueta de autenticidade | 128 bits, anexada ao fim da cifra |
| Associated data (AAD) | nenhum |
| Localizador | `SHA-256(chave)` em hexadecimal minúsculo, 64 caracteres |

A chave não é derivada de senha: não há KDF, não há salt, não há iterações. São
32 bytes de ruído, e o gerador precisa ser o criptográfico da plataforma
(`os.urandom`, `crypto.getRandomValues`, `/dev/urandom`), nunca um `random`
comum.

O par (chave, nonce) jamais pode se repetir. Como cada envio gera uma chave
nova, a garantia já vem daí; ainda assim, gere um nonce novo a cada cifragem.

---

## 2. Arquivo cifrado

Bytes crus, sem cabeçalho, sem número mágico, sem versão embutida:

```
cifra || etiqueta
```

É exatamente a saída do AES-GCM na maioria das bibliotecas — inclusive a
`cryptography` do Python e a Web Crypto do navegador, que já anexam a etiqueta
ao fim do resultado.

O tamanho é sempre `tamanho_original + 16`. Não há padding: o AES-GCM opera em
modo de fluxo, e o tamanho do texto cifrado revela o tamanho do texto claro.

Se a sua biblioteca devolver cifra e etiqueta separadas (é o caso de algumas
APIs em Go, Java e C), concatene nesta ordem antes de gravar, e separe os
últimos 16 bytes antes de decifrar.

---

## 3. Arquivo de credenciais

JSON em UTF-8. Este arquivo é o segredo: ele nunca deve ser enviado ao servidor.

```json
{
  "version": 1,
  "algorithm": "AES-256-GCM",
  "key": "<base64 dos 32 bytes da chave>",
  "nonce": "<base64 dos 12 bytes do nonce>",
  "hash": "<sha256 da chave, hexadecimal minúsculo, 64 caracteres>",
  "filename": "<nome original do arquivo>",
  "size": 123456,
  "expires_at": "2026-09-16T15:56:19Z"
}
```

| Campo | Tipo | Observações |
|---|---|---|
| `version` | inteiro | Sempre `1` nesta versão. Recuse o que não reconhecer. |
| `algorithm` | texto | Sempre `"AES-256-GCM"`. |
| `key` | base64 | 32 bytes. Base64 padrão, com `=` de preenchimento. |
| `nonce` | base64 | 12 bytes. |
| `hash` | hex | `SHA-256(chave)`. É também o localizador no servidor. |
| `filename` | texto | Nome original. Existe só aqui; o servidor não o conhece. |
| `size` | inteiro | Tamanho do arquivo **original**, não da cifra. |
| `expires_at` | texto | Instante da expiração, em UTC, formato `%Y-%m-%dT%H:%M:%SZ`. |

Nome sugerido para o arquivo: `credenciais-<8 primeiros caracteres do hash>.json`.

### Conferências obrigatórias na leitura

Um cliente correto recusa o arquivo, com mensagem específica, quando:

1. o JSON não parseia;
2. `version` não é 1, ou `algorithm` não é `AES-256-GCM`;
3. `key` não decodifica para exatamente 32 bytes, ou `nonce` para 12;
4. `SHA-256(key)` não é igual a `hash` — as credenciais estão corrompidas;
5. `filename` está ausente ou vazio.

A conferência 4 merece atenção. Ela não protege contra um adversário (quem
adultera o JSON recalcula o hash junto), mas pega corrupção acidental antes que
ela vire uma falha de autenticação confusa, que diria "chave incorreta ou
arquivo adulterado" quando o problema real era outro.

Trate `filename` como dado hostil: ele vem de um arquivo que outra pessoa
escreveu e vai ser usado para gravar algo no disco de quem recebe. Reduza-o ao
último componente do caminho antes de usar — `../../.bashrc` não pode
sobreviver a essa viagem.

---

## 4. Localizador

```
localizador = hex(sha256(chave))
```

Sessenta e quatro caracteres, hexadecimal **minúsculo**. É o nome do arquivo no
servidor, e a única coisa que atravessa a rede além dos bytes cifrados.

A propriedade que torna isso seguro é a de mão única: o servidor confere se um
localizador existe, mas não consegue voltar dele para a chave. Quem observa o
tráfego aprende que um arquivo existe e qual o seu tamanho, e nada além disso.

A consequência é que chave e endereço estão acoplados: ter a chave é ter o
endereço. A seção correspondente do [`ESTUDO.md`](ESTUDO.md) discute como
separar os dois com HKDF numa versão futura.

---

## 5. Protocolo com o servidor

Prefixo: `/api`. Todas as respostas de erro têm corpo `{"detail": "..."}`.

### `POST /api/files`

`multipart/form-data` com dois campos:

- `locator`: o localizador, 64 caracteres hexadecimais minúsculos;
- `file`: os bytes cifrados, como arquivo binário.

O nome de arquivo declarado na parte `file` **não** deve ser o nome real: os
clientes de referência enviam `cifra.bin`.

| Resposta | Significado |
|---|---|
| `201` | `{"locator": "...", "expires_at": "..."}` |
| `400` | localizador mal formado, ou corpo vazio |
| `409` | o localizador já existe no servidor |
| `413` | acima de 100 MiB |

### `GET /api/files/{locator}`

| Resposta | Significado |
|---|---|
| `200` | `{"size_bytes": 123, "expires_at": "..."}` — tamanho **da cifra** |
| `404` | não existe **ou** expirou — os dois casos são indistinguíveis |

### `GET /api/files/{locator}/content`

| Resposta | Significado |
|---|---|
| `200` | os bytes cifrados, `Content-Type: application/octet-stream` |
| `404` | não existe **ou** expirou |

O servidor nunca recebe a chave, o nonce ou o nome do arquivo — em nenhum
endpoint, cabeçalho, parâmetro de URL ou log.

---

## 6. Vetor de teste

Com estes valores, qualquer implementação pode se conferir sem rodar o sistema.

```
chave (32 bytes, hex)  000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
chave (base64)         AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=
localizador            630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd

nonce (12 bytes, hex)  000102030405060708090a0b
nonce (base64)         AAECAwQFBgcICQoL

texto claro            "Mensagem confidencial.\n"   (23 bytes, UTF-8)

cifra || etiqueta      0a67b868a482a776ad22f8e5d7801c08edb5ee559c55552f
(hexadecimal)          687a404940c688926ca525ae8ca566
cifra (base64)         Cme4aKSCp3atIvjl14AcCO217lWcVVUvaHpASUDGiJJspSWujKVm
tamanho da cifra       39 bytes  (23 + 16)
```

Repartido: os 23 primeiros bytes são o texto cifrado
(`0a67b868a482a776ad22f8e5d7801c08edb5ee559c5555`) e os 16 últimos são a
etiqueta de autenticidade (`2f687a404940c688926ca525ae8ca566`).

Uma implementação correta, ao cifrar aquele texto com aquela chave e aquele
nonce, produz exatamente aqueles 39 bytes. O AES-GCM é determinístico: mesma
entrada, mesma saída.

---

## 7. Como conferir contra as implementações de referência

Pela linha de comando, com o `cofre.py`:

```bash
python3 cofre.py cifrar   documento.pdf
python3 cofre.py decifrar documento.pdf.cifra documento.pdf.credenciais.json
python3 cofre.py adulterar documento.pdf.cifra documento.pdf.credenciais.json
```

Pelo navegador, na página `/teste-cripto.html`, que cifra, decifra, compara
byte a byte e exporta os dois arquivos no formato que o `cofre.py` lê — sem
fazer nenhuma requisição ao servidor.

E, automaticamente, nos dois sentidos:

```bash
docker compose --profile test run --rm tests pytest tests/interop -v
```
