# Estudo — Troca Confidencial de Arquivos

Este documento explica como o sistema funciona e, principalmente, por que cada decisão foi tomada.

Ele pressupõe que você sabe Python e conhece o `[cofre.py](cofre.py)`, e que
criptografia e desenvolvimento web são o terreno novo. Onde aparecer algo de
JavaScript ou de web, a explicação parte do equivalente em Python.

**Índice**

1. [O problema e a ideia central](#1-o-problema-e-a-ideia-central)
2. [A infraestrutura](#2-a-infraestrutura)
3. [O núcleo criptográfico: crypto.js lado a lado com o cofre.py](#3-o-núcleo-criptográfico-cryptojs-lado-a-lado-com-o-cofrepy)
4. [O backend](#4-o-backend)
5. [A interface](#5-a-interface)
6. [A expiração](#6-a-expiração)
7. [O endurecimento](#7-o-endurecimento)
8. [Como o sistema se prova](#8-como-o-sistema-se-prova)
9. [O que mudaria numa versão 2](#9-o-que-mudaria-numa-versão-2)

---



## 1. O problema e a ideia central

O Usuário A quer mandar um arquivo para o Usuário B. Os dois não confiam no servidor pelo qual o arquivo vai passar, nem por desonestidade, necessariamente: servidores são invadidos, recebem intimações, têm backups que vazam e administradores que erram.

A solução é antiga e simples de enunciar: **cifre antes de enviar**. O difícil
está nas consequências práticas dessa frase, e é delas que trata o sistema
inteiro.

Se o servidor não pode ler o conteúdo, ele também não pode:

- saber o nome do arquivo (o nome já é informação: `demissao-carlos.pdf`);
- indexar, buscar, prever ou classificar coisa alguma;
- ajudar quem perdeu a chave;
- provar a alguém que determinado arquivo passou por ali.

E se o servidor não conhece a chave, resta um problema novo: **como ele encontra o arquivo certo?** Alguma coisa precisa servir de endereço.

A resposta adotada é: o endereço é o `SHA-256` da chave.

```
chave ──(SHA-256)──> localizador
```

Quem tem a chave calcula o localizador em um passo. Quem tem só o localizador
não volta para a chave, porque inverter SHA-256 não é viável. O servidor guarda
os bytes sob esse endereço e nunca precisa saber o que o abre.

O resto do sistema é a consequência disso, levada a sério.

---



## 2. A infraestrutura



### Quatro serviços

**Nginx** é a única porta de entrada. Isso concentra num só lugar o TLS, os cabeçalhos de segurança, o limite de tamanho de corpo e o rate limiting. A API nem sequer publica porta para o host, quem quiser falar com ela passa pelo proxy.

**PostgreSQL** guarda metadados: dados pequenos, estruturados, consultados por
critério ("quais registros já venceram?"). Um índice em `expires_at` responde
isso em tempo desprezível; um `ls` num diretório não responde.

**MinIO** guarda os bytes cifrados: grandes, opacos, nunca consultados por conteúdo. Object storage é feito para isso, entrega em streaming, sem carregar o arquivo inteiro na memória do processo. Ele fala o protocolo S3, então trocar por um serviço de nuvem depois é questão de mudar variáveis de ambiente.

A separação também deixa visível uma propriedade central: **os dois depósitos,
somados, não bastam para abrir arquivo nenhum**. O banco tem um hash e um
caminho; o storage tem ruído. A chave não está em nenhum dos dois.

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

Não há coluna para nome de arquivo, tipo MIME, IP do remetente nem identificador
de usuário. A ausência é a decisão mais importante do modelo de dados: **o que
não é armazenado não vaza em invasão, não aparece em intimação e não precisa ser
protegido**. Há um teste que lê o `information_schema` do Postgres e falha se
alguém acrescentar uma coluna nova.

O `locator` é `char(64)` porque um hash SHA-256 em hexadecimal tem sempre esse
tamanho. O `size_bytes` guarda o tamanho da **cifra**, não do original, os dois diferem por exatamente 16 bytes, o que aliás significa que o tamanho aproximado do original é visível ao servidor (limitação 3).

O `status` parece redundante diante do `expires_at`, mas eles respondem
perguntas diferentes: `expires_at` é a **verdade** sobre a validade, conferida
em toda leitura; `status` registra que o job de limpeza já **passou** por ali e
apagou os bytes. Um registro pode estar vencido e ainda `available` durante a hora que falta para o job rodar e, mesmo nesse intervalo, a API já responde 404, porque quem manda é o `expires_at`.

### SQLAlchemy síncrono dentro de um framework assíncrono

O FastAPI é assíncrono e a tentação é declarar tudo com `async def`. Aqui é o
contrário: as rotas são `def` comuns, e o FastAPI as executa em um pool de
threads.

O motivo é que o cliente do MinIO é síncrono. Misturar os dois modelos exige envolver chamadas bloqueantes em executores, e uma chamada bloqueante esquecida dentro de uma corrotina trava o event loop inteiro, um bug silencioso, que só aparece sob carga. Com rotas síncronas, o código lê de cima para baixo, o streaming continua sendo streaming de verdade, e essa classe de erro não existe.

### Migrations em vez de `create_all`

O SQLAlchemy cria tabelas a partir dos modelos com uma linha. Não é o que
fazemos: o esquema nasce de uma migration do Alembic, aplicada pelo
`entrypoint.sh` a cada subida.

A diferença aparece na segunda alteração do esquema, não na primeira.
`create_all` cria o que não existe e ignora o que mudou. A migration é um passo
versionado, com ordem definida e registro do que já foi aplicado, e descreve a
mesma história em qualquer ambiente. Rodar `alembic upgrade head` em toda subida
é seguro justamente porque o Alembic sabe onde parou.

### O endpoint de saúde e o que ele não conta

`GET /api/health` executa um `SELECT 1` no Postgres e um `list_buckets` no
MinIO — as chamadas mais baratas que ainda provam rede e credencial. Devolve
`200` quando tudo responde e `503` quando algo falha.

O detalhe importante está no tratamento do erro. A exceção de conexão do
Postgres traz host, usuário e, dependendo do driver, a senha na mensagem. Essa
mensagem vai para o log do servidor; a resposta HTTP recebe apenas a palavra
`indisponivel`. É a primeira aparição de um princípio que atravessa o projeto:
**a resposta ao cliente diz o mínimo necessário para agir, e o log guarda o
resto** — princípio que reaparece, de outra forma, quando "não existe" e
"expirou" precisarem ser indistinguíveis.

---



## 3. O núcleo criptográfico: crypto.js lado a lado com o [cofre.py](http://cofre.py)

Esta é a parte central do documento. O `[crypto.js](static/js/crypto.js)` é o
`cofre.py` traduzido para o navegador, mesma criptografia, mesmo formato, outra plataforma. Comparar os dois é a forma mais rápida de entender tanto o que a Web Crypto tem de diferente quanto o que, na verdade, não muda nada.

### 3.1 Antes do código: o que o AES-256-GCM é

**Chave (32 bytes).** É o segredo. Não é senha: não passa por função de derivação, não tem salt, não tem iterações. São 32 bytes de ruído de um gerador criptográfico. "AES-256" é exatamente isso: 256 bits de chave.

**Nonce (12 bytes).** *Number used once*. Não é segredo e viaja em claro dentro do JSON de credenciais. O que ele garante é que cifrar a mesma mensagem duas vezes produza saídas diferentes. A regra inviolável é que o par (chave, nonce) nunca se repita: no GCM, repetir esse par com mensagens diferentes não vaza só a relação entre elas, permite recuperar o material que autentica as mensagens, e a partir daí forjar novas. Como aqui cada envio gera chave nova, a repetição é impossível na prática.

**Etiqueta de autenticidade (16 bytes).** É o que o "GCM" acrescenta ao AES. Sem
ela, um cifrador entrega bytes decifrados quaisquer quando a chave está errada,
ou bytes corrompidos silenciosamente quando alguém mexe na cifra. Com ela, o
decifrador **recusa**: ou o conteúdo é exatamente o que foi cifrado por quem
tinha a chave, ou não há resposta. Modo de cifragem sem autenticação (AES-CBC
puro, por exemplo) é hoje considerado um erro de projeto em praticamente todo
contexto.

**Associated data (AAD).** Dados que não são cifrados, mas ficam protegidos pela
etiqueta: adulterá-los invalida a decifragem. Serviria, por exemplo, para
amarrar a cifra ao nome do arquivo. Nesta versão é `None` nos dois lados — e
precisa ser `None` nos dois, porque essa escolha faz parte do formato.

### 3.2 As quatro funções, lado a lado



#### Gerar a chave

```python
# cofre.py
chave = AESGCM.generate_key(bit_length=256)
nonce = os.urandom(TAMANHO_NONCE)
```

```javascript
// crypto.js
export function generateKey() {
  return crypto.getRandomValues(new Uint8Array(KEY_SIZE));
}

export function generateNonce() {
  return crypto.getRandomValues(new Uint8Array(NONCE_SIZE));
}
```

Duas diferenças de forma e nenhuma de fundo.

A primeira é o tipo. Python tem `bytes`; JavaScript não tem um tipo nativo para
sequência de bytes crus, e usa `Uint8Array` — um vetor de inteiros de 0 a 255
sobre um buffer de memória. Onde o `cofre.py` escreve `bytes`, o `crypto.js`
escreve `Uint8Array`, e é a mesma coisa. (Um `Array` comum de JavaScript **não**
serve: ele guarda números de ponto flutuante em posições espalhadas pela
memória, e a Web Crypto não o aceita.)

A segunda é o gerador. `os.urandom` e `crypto.getRandomValues` são a mesma
categoria de coisa: o gerador criptograficamente seguro do sistema operacional.
O que **não** serve é `Math.random()`, equivalente ao `random.random()` do
Python: previsível o bastante para ser reconstruído por quem observe algumas
saídas. Toda a segurança do sistema começa nessa linha — uma chave adivinhável
torna tudo o que vem depois decorativo.

#### O localizador

```python
# cofre.py
hash_chave = hashlib.sha256(chave).hexdigest()
```

```javascript
// crypto.js
export async function computeLocator(keyBytes) {
  const digest = await crypto.subtle.digest("SHA-256", assertKey(keyBytes));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
```

Aqui aparece a maior diferença de ergonomia entre as duas plataformas: **no
navegador, a criptografia é assíncrona**.

`hashlib.sha256(chave).hexdigest()` devolve a string na hora. Já
`crypto.subtle.digest` devolve uma *Promise* — o equivalente mais próximo é a
`Awaitable` do `asyncio`: um objeto que representa um resultado que ainda vai
chegar, e que só vira valor depois de um `await`. Por isso todas as funções do
`crypto.js`, exceto as de gerar bytes aleatórios, são `async`.

O motivo é o modelo de execução do navegador. Uma aba tem **uma** thread para
JavaScript, interface e eventos. Se cifrar 50 MB bloqueasse essa thread, a
página congelaria — nada de clique, nada de rolagem, nada de barra de progresso.
A Web Crypto faz o trabalho fora dela e avisa quando termina. O preço é que o
`async`/`await` se espalha por tudo que toca criptografia.

A segunda diferença é que `hexdigest()` não existe: `digest` devolve um
`ArrayBuffer` cru, e o hexadecimal precisa ser montado à mão — cada byte para
base 16, preenchido a dois dígitos, tudo concatenado. É verboso, e é o que
`hexdigest()` faz por baixo dos panos.

#### Cifrar

```python
# cofre.py
aesgcm = AESGCM(chave)
cifra = aesgcm.encrypt(nonce, dados, None)
```

```javascript
// crypto.js
export async function encrypt(keyBytes, nonceBytes, plaintext) {
  const key = await importKey(keyBytes, "encrypt");
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: assertNonce(nonceBytes), tagLength: TAG_SIZE * 8 },
    key,
    plaintext,
  );
  return new Uint8Array(ciphertext);
}
```

Três observações.

**O** `importKey`**.** Em Python, `AESGCM(chave)` recebe os bytes e pronto. No
navegador, os bytes precisam ser convertidos num objeto `CryptoKey` antes de
qualquer operação:

```javascript
async function importKey(keyBytes, usage) {
  return crypto.subtle.importKey(
    "raw", assertKey(keyBytes), { name: "AES-GCM" }, false, [usage],
  );
}
```

Os dois últimos argumentos merecem atenção. O `false` é o `extractable`: essa
chave **não pode ser exportada de volta** pelo JavaScript. E `[usage]` é a lista
de usos permitidos — a chave é importada só para cifrar, ou só para decifrar,
nunca as duas coisas.

É importante entender o alcance real disso. Os bytes da chave continuam na
memória da aba (é de lá que o JSON de credenciais é montado), então o
`extractable: false` não é uma barreira contra código malicioso rodando na
página. O que ele faz é impedir que a chave escape **por acidente**: um `console.log`
de um objeto, uma serialização descuidada, um objeto passado para uma função que
não deveria recebê-lo. É higiene, não blindagem — e o custo é zero.

**O** `iv`**.** A Web Crypto chama o nonce de `iv`, de *initialization vector*. É o
mesmo valor com outro nome, herdado de outros modos de cifragem. Em GCM, o
tamanho recomendado é 12 bytes, e é o que os dois lados usam.

**O** `tagLength`**.** No Python, 128 bits é o padrão e não se escreve. No navegador
também é o padrão, mas o `crypto.js` escreve `tagLength: TAG_SIZE * 8`
explicitamente. A razão é documental: a especificação em `[FORMATO.md](FORMATO.md)`
fixa 128 bits, e um valor implícito é um valor que alguém pode mudar sem
perceber que quebrou o contrato.

O resultado é o mesmo layout nas duas pontas: `cifra || etiqueta`, sempre com
`tamanho_original + 16` bytes. Nenhuma das duas bibliotecas obriga a manipular a
etiqueta separadamente — as duas já a anexam ao fim. Em outras linguagens isso
nem sempre acontece, e é por isso que o `FORMATO.md` diz explicitamente onde a
etiqueta está.

#### Decifrar — e o ponto mais importante do módulo

```python
# cofre.py
try:
    dados = aesgcm.decrypt(nonce, cifra, None)
except InvalidTag:
    sys.exit("Falha na autenticação: chave incorreta ou arquivo adulterado.")
```

```javascript
// crypto.js
export async function decrypt(keyBytes, nonceBytes, ciphertext) {
  const key = await importKey(keyBytes, "decrypt");
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: assertNonce(nonceBytes), tagLength: TAG_SIZE * 8 },
      key,
      ciphertext,
    );
    return new Uint8Array(plaintext);
  } catch (erro) {
    if (erro instanceof Error && erro.name === "OperationError") {
      throw new AuthenticationError({ cause: erro });
    }
    throw erro;
  }
}
```

O `InvalidTag` do Python corresponde ao `OperationError` da Web Crypto. Os dois
significam exatamente uma coisa: **ou a chave está errada, ou os bytes foram
alterados depois de cifrados**. Nunca "deu um erro qualquer".

Repare no que o `catch` faz e no que ele recusa a fazer. Ele traduz apenas o
`OperationError` para `AuthenticationError`, com a mensagem exigida pela
especificação. Qualquer outro erro — chave com tamanho errado, argumento de tipo
inválido, um bug em outra parte do código — é **relançado como veio**.

Essa distinção é deliberada. Um `catch` que engolisse tudo transformaria
qualquer defeito de programação em "chave incorreta ou arquivo adulterado", e o
usuário passaria a receber uma mensagem falsa sobre criptografia quando o
problema real fosse outro. Perto de código criptográfico, `except Exception: pass` — ou seu equivalente em JavaScript — é uma das poucas coisas que dá para
chamar de erro sem hesitar.

A Web Crypto, por sinal, não diz *por que* a decifragem falhou, e isso é
proposital: distinguir "chave errada" de "dados adulterados" daria a um atacante
um oráculo, uma forma de fazer perguntas ao sistema e aprender com as respostas.
Uma mensagem só, para os dois casos, é a resposta certa — em Python e no
navegador.

### 3.3 base64: por que ele existe no meio disso

```python
# cofre.py
def b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode("ascii")
```

```javascript
// crypto.js
export function toBase64(bytes) {
  let binario = "";
  const BLOCO = 0x8000;
  for (let inicio = 0; inicio < bytes.length; inicio += BLOCO) {
    binario += String.fromCharCode(...bytes.subarray(inicio, inicio + BLOCO));
  }
  return btoa(binario);
}
```

base64 não tem nada de criptográfico: é só uma forma de escrever bytes
arbitrários usando 64 caracteres seguros para texto. Ele existe no projeto por
uma razão prática — o arquivo de credenciais é JSON, e JSON não tem tipo binário.
Os 32 bytes da chave precisam virar texto para caber lá dentro.

A versão JavaScript é mais longa por um detalhe de plataforma. O `btoa` do
navegador converte texto para base64, mas espera uma string em que cada caractere
representa um byte, então é preciso montar essa string antes. E
`String.fromCharCode(...bytes)` — o `...` é o mesmo desempacotamento do `*args`
do Python — estoura a pilha de chamadas quando o array tem centenas de milhares
de elementos. Daí o laço em blocos de 32 KB. É o tipo de armadilha que só
aparece quando o arquivo cresce, o que a torna especialmente traiçoeira: funciona
perfeitamente no teste com um arquivo pequeno.

### 3.4 O que não mudou

Vale listar, porque é a parte que mais importa: algoritmo, tamanho de chave,
tamanho de nonce, tamanho de etiqueta, ausência de AAD, layout do arquivo
cifrado, cálculo do localizador e formato do JSON de credenciais. **Nada disso
muda entre as duas implementações** — e é exatamente por isso que um arquivo
cifrado em qualquer uma das pontas abre na outra.

As diferenças todas são de plataforma: tipos, assincronismo, importação de chave
e conversão manual para hexadecimal. Nenhuma delas é uma decisão criptográfica.

### 3.5 O teste que prova tudo isso

Duas implementações que "deveriam" concordar concordam até o dia em que não
concordam mais. É por isso que o teste de interoperabilidade é o mais importante
do projeto — e por que ele roda nos dois sentidos:

1. o `cofre.py` cifra pela linha de comando; o navegador decifra com o
  `crypto.js`; os bytes são comparados com o original;
2. o navegador cifra; o `cofre.py` decifra pela linha de comando; os bytes são
  comparados de novo.

Ambos os sentidos rodam sobre quatro conteúdos diferentes — arquivo vazio, um
único byte, texto com acentuação em UTF-8 e 100 KB de binário — porque cada um
pega uma classe distinta de erro. O arquivo vazio, por exemplo, é o caso em que
a cifra é só a etiqueta, com 16 bytes e nenhum conteúdo; uma implementação
descuidada pode simplesmente não lidar com isso.

Há ainda quatro testes que valem a pena conhecer:

- **adulteração**, nos dois lados: um bit trocado no meio da cifra precisa
produzir recusa, e com a mensagem exata;
- **chave errada**: a mesma recusa, nunca bytes corrompidos;
- **o localizador é mesmo o SHA-256 da chave**, conferido contra um valor
calculado em Python;
- **o vetor de teste publicado no** `FORMATO.md`: cifrar aquele texto com aquela
chave e aquele nonce precisa produzir exatamente aqueles 39 bytes, nas duas
implementações. Se alguém mudar o formato, o documento e o código não podem
divergir em silêncio — este teste quebra primeiro.

Um detalhe sobre como o teste é construído: o navegador é dirigido pelo
Playwright, que abre a página `/teste-cripto.html` e chama as funções do módulo
por `window.cofreCrypto`. São **as mesmas funções que a interface usa** — não há
uma versão paralela do código escrita para o teste, que é o jeito mais comum de
um teste de interoperabilidade passar enquanto o sistema real não funciona.

---



## 4. O backend

Três endpoints, e nenhum deles conhece a chave.

### Streaming de verdade

`POST /api/files` recebe `multipart/form-data` com dois campos: o localizador e
os bytes. A instrução do plano é que os bytes cheguem ao MinIO **em streaming**,
sem o arquivo inteiro na memória do processo.

O caminho é este: o Starlette (a camada HTTP sob o FastAPI) escreve o upload em
um arquivo temporário conforme ele chega; o endpoint mede esse arquivo com um
`seek` até o fim e um `tell`; e então entrega o objeto de arquivo ao cliente do
MinIO, que lê em pedaços e vai enviando.

```python
file.file.seek(0, 2)      # 2 = fim do arquivo
tamanho = file.file.tell()
file.file.seek(0)
```

Medir assim é o ponto que faz diferença: um `file.read()` traria os 100 MB para
a memória só para saber o tamanho, desfazendo o streaming inteiro em uma linha
inocente.

### "Não existe" e "expirou" precisam ser a mesma resposta

Esta é a regra mais sutil do backend. Se o servidor respondesse `404 não existe`
para um localizador desconhecido e `410 expirou` para um vencido, ele estaria
contando a quem pergunta que aquele localizador **já foi válido um dia** — ou
seja, que existe por aí uma chave cujo SHA-256 é aquele. É informação sobre a
chave, dada de graça.

A implementação evita isso tendo um caminho só:

```python
record = session.scalar(select(FileRecord).where(FileRecord.locator == locator))
if record is None or record.expires_at <= datetime.now(timezone.utc):
    raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
```

Uma consulta indexada nos dois casos, a mesma mensagem, o mesmo código. O plano
pede também tempo de resposta aproximadamente igual, e é o que acontece: a
diferença entre "a consulta não achou nada" e "achou e a data já passou" é uma
comparação de datas em memória, ordens de grandeza abaixo do custo da consulta.
Um localizador com formato inválido cai no mesmo lugar — no `POST` ele é `400`,
porque ali é um erro de quem escreveu o cliente, mas na leitura é `404` como
todo o resto.

Há um teste que compara as duas respostas campo a campo, incluindo o
`Content-Type`.

### O limite de tamanho, em dois lugares

O Nginx corta o corpo em 101 MiB. A aplicação confere de novo, por conta
própria, em dois momentos: um middleware recusa pelo `Content-Length` antes de
ler o corpo (senão um upload de 2 GB seria inteiramente gravado em disco antes
de ser recusado), e o endpoint confere o tamanho real depois.

A duplicação é intencional. O proxy é a primeira barreira, nunca a única: se um
dia a API for exposta sem ele, ou se a configuração for alterada por engano, a
regra continua valendo. O teste correspondente envia um corpo calibrado para
passar pelo Nginx e ser recusado pelo Python, justamente para provar que a
segunda barreira existe.

O número é `100 MiB + 16`. O plano fixa 100 MB de arquivo original, e o limite
da API incide sobre a cifra, que tem os 16 bytes da etiqueta a mais — sem esse
ajuste, um arquivo de exatamente 100 MiB seria recusado por 16 bytes.

### O nome do objeto no storage

O objeto guardado no MinIO **não** tem o localizador como nome; ele recebe um
UUID aleatório, e o banco faz a ligação entre os dois. Assim, quem conseguir
listar o bucket não descobre quais localizadores existem — e, portanto, não
consegue nem dizer se um determinado arquivo está lá, quanto mais baixá-lo.

---



## 5. A interface



### Sem framework, sem build

São arquivos `.html`, `.css` e `.js` servidos como estão. Nenhum bundler,
nenhum transpilador, nenhum `node_modules`. O que você lê no editor é
exatamente o que roda no navegador — e, num sistema cujo argumento é
"você pode verificar o que este código faz", isso vale mais do que conveniência
de desenvolvimento.

A organização em módulos usa o sistema nativo do próprio JavaScript:

```html
<script type="module" src="/js/enviar.js"></script>
```

```javascript
import { encrypt, generateKey } from "./crypto.js";
```

É o mesmo conceito do `import` do Python, com duas diferenças: o caminho é
relativo e precisa da extensão `.js`, e cada módulo tem escopo próprio — nada
vaza para o escopo global, o que em JavaScript é uma melhoria e tanto.

A separação é por responsabilidade: `crypto.js` (criptografia pura),
`credenciais.js` (o formato do JSON), `api.js` (as três chamadas ao servidor),
`ui.js` (peças de interface) e um arquivo por tela. O `crypto.js` não sabe que
existe uma tela; o `api.js` não sabe o que é uma chave. Essa fronteira é o que
permite afirmar, lendo o `api.js` inteiro em dois minutos, que nenhuma função
dele tem acesso a segredo nenhum.

### As barras de progresso, e a que não podia existir

O pedido era que as duas barras fossem reais, refletindo bytes processados, sem
simulação. A do upload é exatamente isso:

```javascript
requisicao.upload.addEventListener("progress", (evento) => {
  if (evento.lengthComputable && onProgress) onProgress(evento.loaded, evento.total);
});
```

É a razão de o `api.js` usar `XMLHttpRequest` em vez do `fetch`, mais moderno:
`fetch` ainda não reporta progresso de upload, e o `XMLHttpRequest` reporta.

A da cifragem é um caso diferente, e essa diferença foi discutida antes de ser
implementada. `crypto.subtle.encrypt` **é uma chamada atômica**: entra o
conteúdo inteiro, sai a cifra inteira, sem qualquer sinal de progresso no meio.
A única forma de obter porcentagem real seria cifrar em pedaços — o que o plano
exclui do escopo e que mudaria o formato da seção 4, já que cada pedaço
precisaria do próprio nonce e da própria etiqueta.

A solução adotada divide a etapa em duas e é honesta sobre cada uma:

1. **a leitura do arquivo do disco**, feita pelo stream do próprio arquivo, com
  progresso real byte a byte — é trabalho de verdade, medido de verdade;
2. **a cifragem**, que assume aparência indeterminada: barra listrada em
  movimento, sem porcentagem, rotulada "Cifrando com AES-256-GCM…".

A alternativa seria uma barra que anda sozinha enquanto o navegador trabalha —
isto é, uma animação que mente. Uma barra que finge progresso é pior do que
nenhuma barra: ela treina quem usa a desconfiar do que a interface mostra.

### Mensagens de erro específicas

Cada recusa previsível tem mensagem própria, dizendo o que fazer:


| Situação                | O que o usuário lê                                                                                 |
| ----------------------- | -------------------------------------------------------------------------------------------------- |
| Arquivo grande demais   | "Arquivo acima do limite de 100 MB. Compacte ou divida o arquivo antes de enviar."                 |
| JSON quebrado           | "Este arquivo não é um JSON válido. Selecione o arquivo credenciais-*.json…"                       |
| Versão desconhecida     | "Versão de formato não suportada: 2. Este sistema lê apenas a versão 1."                           |
| Hash inconsistente      | "O hash não corresponde à chave: as credenciais estão corrompidas."                                |
| Expirado ou inexistente | "Arquivo expirado ou inexistente. Arquivos são apagados automaticamente 24 horas depois do envio." |
| Falha na decifragem     | "Chave incorreta ou arquivo adulterado."                                                           |
| Servidor fora           | "Servidor indisponível. Verifique sua conexão e tente novamente em instantes."                     |


Duas delas merecem comentário.

A conferência de **hash inconsistente** repete a do `cofre.py`: o `hash` que o
JSON declara bate com a chave que ele carrega? Ela não protege contra um
adversário — quem adultera o JSON recalcula o hash junto —, mas pega corrupção
acidental antes que ela vire uma mensagem confusa sobre criptografia lá na
frente.

A de **expirado ou inexistente** é uma mensagem só de propósito. A interface não
pode distinguir os dois casos porque o servidor não distingue, pelo motivo
explicado na seção anterior.

### Detalhes que não são detalhes

**O nome do arquivo é tratado como dado hostil.** Ele vem de um JSON que outra
pessoa escreveu e vai ser usado para gravar algo no disco de quem recebe. Antes
de qualquer uso, é reduzido ao último componente do caminho — `../../.bashrc`
não sobrevive à viagem. O teste de ponta a ponta usa "relatório confidencial.bin",
com acento e espaço, para exercitar esse caminho.

**O aviso de irrecuperabilidade é o elemento dominante da tela final**, com
moldura âmbar e o maior título da página. Ele não é um rodapé porque não é um
detalhe: é o único momento em que o sistema pode avisar que perder aquele JSON é
perder o arquivo.

**O download das credenciais é automático.** É o passo que não pode ser
esquecido, então ele não depende de alguém lembrar de clicar. O botão de baixar
de novo existe para quem cancelou o download sem querer.

**Fechar a aba durante a cifragem ou o upload dispara um aviso** (`beforeunload`),
porque a chave está só na memória daquela aba: fechar antes do fim perde trabalho
que não pode ser retomado.

**Nenhum valor secreto vai para** `localStorage` **ou** `sessionStorage`**.** As
credenciais vivem em uma variável de módulo — memória da aba, que some quando a
página fecha. O teste de ponta a ponta confere, ao fim do fluxo, que os dois
armazenamentos continuam vazios. Vale lembrar por quê: `localStorage` persiste
no disco indefinidamente, é legível por qualquer script rodando naquela origem e
sobrevive ao fechamento do navegador.

### Acessibilidade e direção visual

A paleta tem uma cor de acento só, um verde-petróleo, usada em três lugares: a
ação principal, o foco do teclado e a barra de progresso. O âmbar aparece uma
vez, no aviso crítico. A monoespaçada é reservada a valores que se conferem
caractere a caractere — localizador, hash, tamanhos em bytes. Não há ícone de
cadeado, escudo ou qualquer ilustração: a interface transmite "ferramenta
técnica" por sobriedade, não por simbolismo.

Sobre acessibilidade: a área de arrastar-e-soltar é focável e responde a Enter e
Espaço, o `:focus-visible` é um contorno de 3 px visível de verdade, o estado
atual é anunciado por `aria-live`, as barras de progresso têm `role="progressbar"`
com `aria-valuenow`, e `prefers-reduced-motion` desliga as animações. O layout é
uma coluna só, com uma ação principal por vez, e funciona até 360 px.

---



## 6. A expiração



### Quem manda é o banco

O arquivo expira em 24 horas, e três mecanismos participam disso — mas apenas um
decide.

**A coluna** `expires_at` é a fonte da verdade. Toda leitura a confere, e um
registro vencido responde 404 **imediatamente**, mesmo que os bytes ainda estejam
no storage e que o job de limpeza só vá rodar dali a cinquenta minutos.

**O job do APScheduler** roda de hora em hora e faz o trabalho material: apaga os
objetos do MinIO e marca os registros como `expired`. A ordem importa — primeiro
o objeto sai do storage, depois o registro muda de status. Se o processo cair no
meio, o registro continua `available` e vencido, a próxima execução tenta de
novo, e nesse intervalo a API já responde 404. O inverso — marcar primeiro,
apagar depois — deixaria bytes órfãos sem ninguém sabendo que existem.

**A regra de lifecycle do bucket** é rede de segurança, e só. Ela existe para o
caso de a aplicação passar dias fora do ar: sem ela, os objetos ficariam
indefinidamente. Não é a fonte da verdade, e o sistema não depende dela para
estar correto.

O agendador roda dentro do próprio processo da API, em uma thread de fundo. Para
um MVP com um worker, isso basta e evita introduzir fila, broker ou um contêiner
a mais. Com vários workers, cada um tentaria expirar os mesmos registros — a
operação é idempotente, então o pior caso seria trabalho repetido, mas aí valeria
uma trava distribuída ou um processo dedicado.

### Testar sem esperar 24 horas

O teste manipula o relógio, não a paciência: um `UPDATE` coloca `expires_at` no
passado, e a partir daí tudo é verificável em segundos. O teste confere a
sequência inteira — a API passa a responder 404 na hora, o objeto **ainda está**
no MinIO, o job roda, o objeto some, o status vira `expired` e a resposta
continua 404.

Há também o caminho inverso, que é o que costuma escapar: um registro **dentro**
do prazo precisa sobreviver ao job. Um bug de sinal na comparação de datas
apagaria tudo, e só esse teste pegaria.

### Órfãos

Um órfão é um objeto no storage que nenhum registro disponível referencia —
resultado de uma falha parcial. O `manage.py orfaos` lista; com `--remover`,
apaga. A separação entre listar e apagar é proposital: um comando que apaga
coisas deve ser difícil de executar por engano.

---



## 7. O endurecimento



### A CSP e por que ela obriga todo o resto

A Content-Security-Policy é um cabeçalho HTTP em que o servidor declara de onde
a página pode carregar cada tipo de recurso. A daqui é esta:

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none';
form-action 'none'; frame-ancestors 'none'
```

O que importa é o que **não** está lá: `unsafe-inline`. Sem essa permissão, o
navegador recusa executar qualquer JavaScript escrito dentro do HTML — tanto
`<script>código aqui</script>` quanto atributos como `onclick="..."`.

E é aí que a política deixa de ser decoração e vira defesa. O ataque clássico
contra uma página é injetar código nela — por um campo de texto, por um
parâmetro de URL, por um dado vindo do servidor. Com `script-src 'self'`, o
código injetado simplesmente não roda: o navegador o ignora, porque não veio de
um arquivo do próprio site.

O preço é disciplina: **todo** o JavaScript precisa estar em arquivos externos e
os eventos precisam ser ligados por `addEventListener`. Nenhum `onclick` no
HTML, em lugar nenhum. Foi por isso que o frontend nasceu assim desde o começo —
e há um teste que lê cada `.html` procurando `onclick=`, `onload=` e `<script>`
com corpo, porque disciplina que depende de memória humana dura até a próxima
pressa.

Para um sistema que faz criptografia no navegador, essa política é mais do que
higiene: é a diferença entre "um script injetado poderia exfiltrar a chave" e
"um script injetado não executa". Ela não resolve a [limitação 2](LIMITACOES.md)
— quem controla o servidor pode trocar a política junto com o script —, mas
fecha a porta para todo mundo que não controla o servidor.

### A armadilha do `add_header`

Um detalhe de Nginx que engana muita gente: `add_header` dentro de um bloco
`location` **substitui** todos os cabeçalhos herdados do bloco `server`, em vez
de acrescentar-se a eles. Uma linha de `Cache-Control` dentro de um `location`
faria a CSP e o HSTS desaparecerem silenciosamente naquele caminho — sem erro,
sem aviso, sem nada quebrar visivelmente.

Por isso todos os cabeçalhos de segurança estão declarados uma única vez, no
nível do `server`, e nenhum bloco `location` usa `add_header`. Os testes conferem
a presença deles e a ausência de `unsafe-inline` na resposta real do servidor.

### TLS e o restante

TLS 1.3 apenas: sem versões antigas, sem negociação de cifras fracas. O
certificado é autoassinado e gerado na primeira subida do contêiner, num volume,
para sobreviver a recriações. Em produção, é o único item que precisa ser
trocado.

O HTTP na porta 80 existe só para redirecionar (301) ao HTTPS, e o HSTS pede ao
navegador que nem tente a porta 80 nas próximas vezes. Isso muda uma coisa em
relação às primeiras fases: o healthcheck de aceitação agora é
`curl -k https://localhost/api/health` — em HTTP, a resposta é o redirecionamento.

O rate limiting é por IP, com zonas separadas para leitura e envio. Os valores
são folgados, calibrados para conter varredura automatizada de localizadores sem
atrapalhar uso legítimo.

### O localizador nos logs — um problema encontrado na revisão

A regra do plano diz que nenhum log pode registrar o localizador completo. O
código da aplicação obedecia desde o começo, escrevendo só os oito primeiros
caracteres. Mas a revisão dos logs, feita ao final, encontrou noventa e três
ocorrências de localizadores inteiros — vindas de onde ninguém tinha olhado: os
**logs de acesso**.

Faz sentido em retrospecto. O localizador está no caminho da URL, e tanto o log
de acesso do Nginx quanto o do Uvicorn registram o caminho da requisição:

```
"GET /api/files/3d2fab73789aaf0a10ab65a38937e502546ecdbdb64f0e2c574ca58fb54896c1 HTTP/2.0" 200
```

A correção foi em dois lugares. No Nginx, um `map` reescreve o caminho antes de
ele ser gravado. Na aplicação, um filtro de log substitui qualquer sequência de
64 caracteres hexadecimais pelos oito primeiros, instalado na subida — depois
que o Uvicorn monta os próprios handlers, senão o log de acesso ficaria de fora.

Vale explicar por que isso importa, já que o localizador não abre nada sozinho.
Quem lê um localizador sabe que aquele arquivo existiu e pode baixar a cifra
enquanto ela durar. Sem a chave não abre nada, mas é informação que não precisa
ficar espalhada por arquivos de log e coletores de observabilidade, que
costumam ter retenção longa e acesso mais amplo do que o banco de dados.

A lição aqui é a mais geral do projeto: **as regras não se cumprem sozinhas
porque foram escritas**. Ela só apareceu porque a revisão de logs era um item
explícito da última fase, executado de fato, e não presumido.

### Dependências

As versões são fixadas para que a imagem de hoje seja a mesma de amanhã, e
foram passadas pelo `pip-audit`. As versões originais, de 2024, acumulavam
vulnerabilidades conhecidas — inclusive no `python-multipart`, que é justamente
a biblioteca que processa o upload, e no `starlette`, a camada HTTP sob o
FastAPI. Todas foram atualizadas, e a auditoria volta limpa nas duas listas.

Fixar versões sem auditar é meio caminho: garante reprodutibilidade e congela
também os problemas conhecidos. As duas coisas andam juntas.

---



## 8. Como o sistema se prova

São 39 casos de teste, que produzem 55 execuções: todo teste que dirige o
navegador roda duas vezes, uma no Chromium e outra no Firefox — dois motores com
implementações independentes da Web Crypto. É assim que o critério "funciona em
dois navegadores diferentes" deixa de depender de alguém conferir à mão.

Vale entender o que cada grupo garante, porque um teste que não poderia falhar
não prova nada.

`tests/interop/` **(14 casos, 26 execuções)** — o formato é o mesmo nas duas implementações, nos dois
sentidos, com quatro conteúdos diferentes, mais adulteração, chave errada,
contrato do localizador e o vetor publicado no `FORMATO.md`.

`tests/api/` **(17 casos)** — os três endpoints e todos os casos de erro previstos;
"expirado" e "inexistente" indistinguíveis campo a campo; o esquema do banco
conferido contra a lista exata de colunas permitidas; os cabeçalhos de segurança
e a CSP na resposta real; o mascaramento de localizador em log.

`tests/e2e/` **(8 casos, 12 execuções)** — o fluxo completo no navegador com vigilância da rede; as
mensagens de erro específicas; o aviso de expiração antes do download; a
expiração com relógio manipulado, conferindo storage e banco; os objetos órfãos;
a regra de lifecycle; e um arquivo de 50 MB conferido por hash nas duas pontas.

### O teste da promessa central

O mais importante desse conjunto é o que intercepta a rede durante um envio
completo e afirma que nem a chave, nem o nonce, nem o nome do arquivo aparecem
em requisição alguma.

Escrevê-lo revelou uma armadilha que vale registrar. A primeira versão usava o
`post_data_buffer` do Playwright para ler o corpo das requisições — e ele volta
**vazio** quando o corpo é um `FormData` com um blob, que é exatamente o nosso
caso. As asserções "a chave não está no corpo" passavam porque o corpo estava
vazio. Um teste verde que não testava nada.

A correção foi instrumentar o `XMLHttpRequest` dentro da própria página,
registrando cada parte do corpo — nome do campo, tamanho, nome de arquivo
declarado e conteúdo binário — antes de ela sair. O ponto de observação ficou
mais perto da aplicação do que a rede: qualquer coisa que o código tentasse
enviar apareceria ali, mesmo que nunca chegasse ao servidor.

E, para não repetir o erro de confiar em um teste verde, o teste foi submetido a
duas mutações deliberadas:

1. um campo extra no `FormData` com o nome do arquivo — o teste falhou, apontando
  o campo a mais;
2. o nome real do arquivo no lugar do genérico `cifra.bin` na parte do
  multipart — o teste falhou de novo, apontando o nome.

Só depois disso a aprovação passou a significar alguma coisa. **Um teste de
segurança que nunca foi visto falhando é uma hipótese, não uma garantia.**

---



## 9. O que mudaria numa versão 2



### Separar a chave do endereço, com HKDF

O localizador é `SHA-256(chave)`, e isso acopla duas coisas conceitualmente
distintas: o **segredo** que decifra e o **endereço** que localiza. O acoplamento
é seguro — a função de hash não é invertível —, mas é rígido: quem tem a chave
tem necessariamente o endereço, e não há como dar a alguém o direito de consultar
a existência de um arquivo sem lhe dar a chave.

A evolução natural é gerar um segredo mestre aleatório e derivar dele, com HKDF,
duas coisas independentes:

```
segredo_mestre ──HKDF(info="cifragem")──> chave
               └─HKDF(info="localizacao")─> localizador
```

Com isso, chave e localizador deixam de ser computáveis um a partir do outro e
passam a poder circular por canais diferentes. Dá para entregar o localizador a
um serviço de sincronização, por exemplo, sem lhe dar poder de decifrar nada.

Uma nota sobre HKDF, já que o assunto é aprendizado: ele não é uma função de
senha como o `bcrypt` ou o `argon2`. Aqueles são propositalmente lentos, para
encarecer o ataque de força bruta contra algo com pouca entropia — uma senha
humana. O HKDF é rápido, porque a entrada dele já é um segredo de alta entropia:
o trabalho dele é **espalhar** essa entropia em várias chaves independentes, não
proteger uma entrada fraca.

### Cifragem em pedaços

Cifrar em blocos, cada um com seu nonce e sua etiqueta, resolveria três coisas
de uma vez: o limite de 100 MB, o progresso real da barra de cifragem e o pico de
memória na aba. O custo é um formato mais complicado — com cabeçalho, versão,
tamanho de bloco e contador — e o cuidado extra de amarrar a ordem dos blocos
(pelo AAD, justamente) para que ninguém possa reordenar ou remover pedaços sem
ser detectado. Junto com Web Workers, para a interface não travar.

### Outras coisas, em ordem de utilidade

- **Subresource Integrity** nos `<script>`, fixando o hash de cada arquivo. Mitiga
parcialmente a limitação 2 — parcialmente porque quem serve o HTML serve
também os hashes.
- **Download único ou contador de downloads**, para o remetente perceber se o
arquivo foi baixado mais vezes do que deveria.
- **Cabeçalho com tamanho arredondado**, preenchendo a cifra até o múltiplo de
potência de dois seguinte, para embaralhar o que o tamanho revela.
- **Trava distribuída no job de expiração**, se um dia a API rodar com mais de um
worker.



### O que não mudaria

Vale terminar por aqui. A decisão de não guardar nome de arquivo, tipo MIME, IP
nem identificador de usuário é o que dá ao sistema a propriedade mais difícil de
obter depois: **não há o que vazar**. É tentador acrescentar "só o nome do
arquivo, para facilitar o suporte" — e é exatamente assim que sistemas assim
deixam de ser o que são.