/**
 * enviar.js — tela de envio.
 *
 * A sequência é: ler o arquivo do disco, cifrar na memória desta aba, enviar a
 * cifra e, só então, entregar o JSON de credenciais a quem está enviando. O
 * servidor vê dois campos: o localizador e os bytes cifrados.
 */

import { TAG_SIZE, computeLocator, encrypt, generateKey, generateNonce } from "./crypto.js";
import { buildCredentials, credentialsFilename } from "./credenciais.js";
import { uploadCiphertext } from "./api.js";
import {
  createProgress,
  downloadBlob,
  formatBytes,
  formatRemaining,
  readFileWithProgress,
  setUnloadGuard,
  setupDropzone,
} from "./ui.js";

/** Limite de 100 MB sobre o arquivo original, conferido antes de qualquer trabalho. */
const LIMITE_BYTES = 100 * 1024 * 1024;

const elementos = {
  estado: document.getElementById("estado"),
  dropzone: document.getElementById("dropzone"),
  entradaArquivo: document.getElementById("entrada-arquivo"),
  passoSelecao: document.getElementById("passo-selecao"),
  painelArquivo: document.getElementById("painel-arquivo"),
  painelProgresso: document.getElementById("painel-progresso"),
  painelResultado: document.getElementById("painel-resultado"),
  arquivoNome: document.getElementById("arquivo-nome"),
  arquivoTamanho: document.getElementById("arquivo-tamanho"),
  botaoEnviar: document.getElementById("botao-enviar"),
  botaoTrocar: document.getElementById("botao-trocar"),
  botaoBaixarCredenciais: document.getElementById("botao-baixar-credenciais"),
  botaoNovoEnvio: document.getElementById("botao-novo-envio"),
  resultadoNome: document.getElementById("resultado-nome"),
  resultadoTamanho: document.getElementById("resultado-tamanho"),
  resultadoCifra: document.getElementById("resultado-cifra"),
  resultadoLocalizador: document.getElementById("resultado-localizador"),
  resultadoExpiracao: document.getElementById("resultado-expiracao"),
  erro: document.getElementById("erro"),
};

const progressoCifragem = createProgress(document.getElementById("progresso-cifragem"));
const progressoUpload = createProgress(document.getElementById("progresso-upload"));

/**
 * Estado da aba. `credenciais` guarda o JSON pronto para ser baixado de novo.
 *
 * Isto vive em uma variável de módulo, ou seja, na memória da aba, e some
 * quando a página é fechada ou recarregada. Não vai para localStorage nem para
 * sessionStorage: valor secreto não se persiste.
 */
let arquivoSelecionado = null;
let credenciais = null;

const ROTULOS_DE_ESTADO = {
  repouso: "Em repouso",
  pronto: "Pronto para enviar",
  cifrando: "Cifrando",
  enviando: "Enviando",
  concluido: "Concluído",
  erro: "Erro",
};

function definirEstado(estado) {
  elementos.estado.dataset.estado = estado;
  elementos.estado.textContent = ROTULOS_DE_ESTADO[estado];
}

function mostrarErro(titulo, detalhe) {
  elementos.erro.hidden = false;
  elementos.erro.innerHTML = "";
  const forte = document.createElement("strong");
  forte.textContent = titulo;
  elementos.erro.append(forte, document.createTextNode(detalhe ?? ""));
  definirEstado("erro");
}

function limparErro() {
  elementos.erro.hidden = true;
  elementos.erro.textContent = "";
}

function selecionarArquivo(arquivo) {
  limparErro();

  if (arquivo.size === 0) {
    mostrarErro(
      "Arquivo vazio. ",
      "Escolha um arquivo com conteúdo: não há o que cifrar em zero bytes.",
    );
    return;
  }

  if (arquivo.size > LIMITE_BYTES) {
    mostrarErro(
      "Arquivo acima do limite de 100 MB. ",
      `Este arquivo tem ${formatBytes(arquivo.size)}. ` +
        "Compacte ou divida o conteúdo antes de enviar.",
    );
    return;
  }

  arquivoSelecionado = arquivo;
  elementos.arquivoNome.textContent = arquivo.name;
  elementos.arquivoTamanho.textContent = `${formatBytes(arquivo.size)} (${arquivo.size} bytes)`;
  elementos.painelArquivo.hidden = false;
  elementos.painelResultado.hidden = true;
  elementos.painelProgresso.hidden = true;
  definirEstado("pronto");
  elementos.botaoEnviar.focus();
}

async function enviar() {
  if (!arquivoSelecionado) return;

  const arquivo = arquivoSelecionado;
  limparErro();
  elementos.botaoEnviar.disabled = true;
  elementos.botaoTrocar.disabled = true;
  elementos.painelProgresso.hidden = false;
  progressoCifragem.reset();
  progressoUpload.reset();

  // A partir daqui existe trabalho em andamento que não pode ser retomado:
  // a chave está só na memória desta aba.
  setUnloadGuard(true);

  try {
    definirEstado("cifrando");

    // Primeira etapa mensurável: ler o arquivo do disco, pedaço a pedaço.
    const conteudo = await readFileWithProgress(arquivo, (lido, total) =>
      progressoCifragem.set(lido, total),
    );

    // Segunda etapa: a cifragem em si. `crypto.subtle.encrypt` é uma chamada
    // única sobre o conteúdo inteiro — não existe progresso a reportar, e a
    // barra assume aparência indeterminada em vez de simular avanço.
    progressoCifragem.indeterminate("Cifrando com AES-256-GCM…");

    const chave = generateKey();
    const nonce = generateNonce();
    const localizador = await computeLocator(chave);
    const cifra = await encrypt(chave, nonce, conteudo);

    progressoCifragem.set(cifra.length, cifra.length);

    definirEstado("enviando");
    const resposta = await uploadCiphertext(localizador, cifra, (enviado, total) =>
      progressoUpload.set(enviado, total),
    );

    credenciais = buildCredentials({
      key: chave,
      nonce,
      locator: localizador,
      filename: arquivo.name,
      size: arquivo.size,
      expiresAt: resposta.expires_at,
    });

    elementos.resultadoNome.textContent = arquivo.name;
    elementos.resultadoTamanho.textContent = `${formatBytes(arquivo.size)} (${arquivo.size} bytes)`;
    elementos.resultadoCifra.textContent =
      `${formatBytes(cifra.length)} (${cifra.length} bytes, ` +
      `${TAG_SIZE} a mais: a etiqueta de autenticidade)`;
    elementos.resultadoLocalizador.textContent = localizador;
    elementos.resultadoExpiracao.textContent =
      `${resposta.expires_at} (${formatRemaining(resposta.expires_at)})`;

    // As barras ficam à vista como registro do que aconteceu, mas o título
    // deixa de dizer "Processando" quando não há mais nada em processamento.
    document.getElementById("titulo-progresso").textContent = "Cifragem e envio concluídos";
    elementos.painelArquivo.hidden = true;
    elementos.passoSelecao.hidden = true;
    elementos.painelResultado.hidden = false;

    // O download das credenciais é automático: é o passo que não pode ser
    // esquecido, então ele não depende de o usuário lembrar de clicar.
    baixarCredenciais();
    definirEstado("concluido");
    elementos.botaoBaixarCredenciais.focus();
  } catch (erro) {
    console.error(erro);
    mostrarErro(`${erro.message} `, "");
    elementos.botaoEnviar.disabled = false;
    elementos.botaoTrocar.disabled = false;
  } finally {
    setUnloadGuard(false);
  }
}

function baixarCredenciais() {
  if (!credenciais) return;
  const blob = new Blob([JSON.stringify(credenciais, null, 2)], {
    type: "application/json",
  });
  downloadBlob(blob, credentialsFilename(credenciais.hash));
}

function recomecar() {
  arquivoSelecionado = null;
  credenciais = null;
  elementos.entradaArquivo.value = "";
  elementos.passoSelecao.hidden = false;
  elementos.painelArquivo.hidden = true;
  elementos.painelProgresso.hidden = true;
  elementos.painelResultado.hidden = true;
  elementos.botaoEnviar.disabled = false;
  elementos.botaoTrocar.disabled = false;
  progressoCifragem.reset();
  progressoUpload.reset();
  document.getElementById("titulo-progresso").textContent = "Processando";
  limparErro();
  definirEstado("repouso");
  elementos.dropzone.focus();
}

setupDropzone(elementos.dropzone, elementos.entradaArquivo, selecionarArquivo);
elementos.botaoEnviar.addEventListener("click", enviar);
elementos.botaoTrocar.addEventListener("click", () => elementos.entradaArquivo.click());
elementos.botaoBaixarCredenciais.addEventListener("click", baixarCredenciais);
elementos.botaoNovoEnvio.addEventListener("click", recomecar);
