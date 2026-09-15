# Limitações

Este documento existe para ser lido antes de confiar no sistema, não depois.
Nada aqui é um defeito a ser corrigido em uma versão futura: são consequências
diretas do desenho, e quem usa a ferramenta precisa saber de todas elas.

---

## 1. Perder o arquivo de credenciais significa perder o arquivo

A chave que abre o arquivo existe em um único lugar: o JSON baixado no momento
do envio. Ela não é derivada de senha, não está no banco de dados, não está no
object storage e não passou pela rede em nenhum momento.

Se esse arquivo for apagado, corrompido ou esquecido, **o conteúdo é
irrecuperável**. Não há recuperação por e-mail, não há pergunta secreta, não há
suporte que resolva. O administrador do sistema, com acesso total ao servidor,
ao banco e ao storage, tem exatamente o mesmo que um estranho: bytes ilegíveis.

Isso é o objetivo do sistema, e não um efeito colateral. Um sistema que consegue
recuperar seu arquivo é um sistema que consegue ler seu arquivo.

---

## 2. A criptografia no navegador depende de confiar no servidor que entrega o JavaScript

Este é o limite fundamental do modelo, e vale a pena entendê-lo por inteiro.

O `crypto.js` que cifra o seu arquivo é baixado do mesmo servidor que vai
guardar a cifra. Quem controla esse servidor pode, a qualquer momento, servir
uma versão modificada do script — uma que envie a chave junto com os bytes
cifrados, ou que simplesmente mande o arquivo em claro. Você não teria como
perceber: a página pareceria idêntica.

A Content-Security-Policy configurada aqui impede que um script injetado de
fora execute, e o Subresource Integrity permitiria fixar o conteúdo esperado de
cada arquivo. As duas coisas **mitigam, não eliminam**: ambas são entregues pelo
mesmo servidor, e quem pode trocar o script pode trocar a política junto.

Em outras palavras: a criptografia fim a fim no navegador protege você contra um
servidor **curioso** — que armazena, lê, é invadido ou é intimado — mas não
contra um servidor **ativamente malicioso** no momento exato do envio. Proteção
contra esse segundo caso exige um cliente que você mesmo instale e verifique,
fora do alcance de quem opera o servidor.

---

## 3. O tamanho do arquivo é visível ao servidor

O AES-GCM não usa padding. A cifra tem exatamente o tamanho do original mais os
16 bytes da etiqueta de autenticidade, e esse número fica registrado no banco,
aparece nos metadados e é visível para qualquer um que observe o tráfego.

O tamanho parece inofensivo e nem sempre é. Ele permite descartar hipóteses
("isto não é um contrato de 40 páginas") e, em certos contextos, identificar um
arquivo conhecido pelo seu tamanho exato. Também revela o padrão de uso: quantos
arquivos, de que porte, com que frequência.

O mesmo vale para os horários: o servidor sabe quando cada envio aconteceu e
quando cada download foi feito.

---

## 4. A chave precisa chegar ao destinatário por um canal separado

O sistema resolve o transporte do arquivo, não o transporte da chave. Essa parte
continua sendo sua.

Se você mandar o JSON de credenciais no mesmo e-mail em que avisa sobre o
arquivo, quem tiver acesso àquela caixa de entrada tem as duas metades — e o
trabalho todo de cifrar terá servido apenas para proteger o arquivo de quem
opera o servidor, que é metade do problema.

Use canais diferentes, de preferência com naturezas diferentes: o aviso por
e-mail e as credenciais por mensageiro com cifragem fim a fim, ou entregues
pessoalmente, ou ditadas por telefone. O princípio é que comprometer um canal
não pode bastar.

---

## 5. Não há autenticação

Não existem contas, senhas, login ou controle de acesso. Quem tiver o JSON de
credenciais baixa o arquivo — o sistema não pergunta quem é, e nem teria como
saber.

Isso significa que o arquivo de credenciais é um portador: vale para quem o
tiver em mãos, como uma chave física. Encaminhá-lo é o mesmo que fazer uma
cópia da chave. Não há como revogar, limitar a um destinatário ou saber quantas
vezes o arquivo foi baixado — o sistema não conta downloads, por escolha.

O servidor também não guarda quem enviou: não há coluna para IP, usuário ou
qualquer identificador. Isso protege o remetente e, ao mesmo tempo, significa
que não existe trilha de auditoria.

---

## 6. Limite de 100 MB por arquivo

O limite não é comercial, é técnico. Nesta versão, o navegador lê o arquivo
inteiro para a memória, cifra o bloco inteiro de uma vez e mantém original e
cifra simultaneamente — o que, no pior momento, ocupa mais de duas vezes o
tamanho do arquivo em memória RAM da aba.

Cem megabytes é um valor conservador que funciona em navegadores de celular
antigos. Passar disso exige cifrar em pedaços, com Web Workers para não travar a
interface, e um formato de arquivo diferente, com cabeçalho e um nonce por
pedaço. Está fora do escopo desta versão.

---

## O que o servidor sabe, em resumo

Vale registrar com precisão o que continua exposto mesmo com tudo funcionando
como projetado:

| O servidor sabe | O servidor não sabe |
|---|---|
| Que um arquivo existe | O que ele contém |
| O tamanho exato da cifra | O nome do arquivo |
| Quando foi enviado e quando expira | Quem enviou |
| O localizador (SHA-256 da chave) | A chave |
| O endereço IP de quem envia e baixa, enquanto a conexão dura | Quem é essa pessoa |

O endereço IP aparece nos logs de acesso do Nginx, como em qualquer servidor
web. Ele não é gravado no banco de dados e não é associado a nenhum arquivo,
mas os logs existem — e, se isso importar no seu contexto, é preciso tratá-los
(rotação curta, ou remoção do log de acesso).
