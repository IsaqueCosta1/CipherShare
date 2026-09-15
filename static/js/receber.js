/**
 * receber.js — tela de recebimento.
 *
 * A sequência é: ler as credenciais do disco, conferir se o arquivo ainda
 * existe no servidor, baixar a cifra, decifrar na memória desta aba e gravar o
 * arquivo com o nome original. A chave que o JSON carrega não é enviada a
 * lugar nenhum: o servidor só recebe o localizador, que já é público para quem
 * tem as credenciais.
 */

import { decrypt } from "./crypto.js";
import { parseCredentials } from "./credenciais.js";
import { fetchMetadata, downloadCiphertext } from "./api.js";
import {
  createProgress,
  downloadBlob,
  formatBytes,
  formatRemaining,
  setUnloadGuard,
  setupDropzone,
} from "./ui.js";

const elementos = {
  estado: document.getElementById("estado"),
  dropzone: document.getElementById("dropzone"),
  entradaCredenciais: document.getElementById("entrada-credenciais"),
  passoSelecao: document.getElementById("passo-selecao"),
  painelDisponibilidade: document.getElementById("painel-disponibilidade"),
  painelProgresso: document.getElementById("painel-progresso"),
  painelResultado: document.getElementById("painel-resultado"),
  dadoNome: document.getElementById("dado-nome"),
  dadoTamanho: document.getElementById("dado-tamanho"),
  dadoLocalizador: document.getElementById("dado-localizador"),
  dadoValidade: document.getElementById("dado-validade"),
  botaoBaixar: document.getElementById("botao-baixar"),
  botaoTrocar: document.getElementById("botao-trocar"),
  botaoSalvarNovamente: document.getElementById("botao-salvar-novamente"),
  botaoRecomecar: document.getElementById("botao-recomecar"),
  resultadoNome: document.getElementById("resultado-nome"),
  resultadoTamanho: document.getElementById("resultado-tamanho"),
  erro: document.getElementById("erro"),
};

const progressoDownload = createProgress(document.getElementById("progresso-download"));
const progressoDecifragem = createProgress(document.getElementById("progresso-decifragem"));

// Memória da aba, e só dela: credenciais em uso e o conteúdo já decifrado,
// mantido para o botão "salvar novamente". Nada disso é persistido.
let credenciais = null;
let conteudoRecuperado = null;

const ROTULOS_DE_ESTADO = {
  repouso: "Em repouso",
  pronto: "Pronto para baixar",
  verificando: "Verificando",
  baixando: "Baixando",
  decifrando: "Decifrando",
  concluido: "Concluído",
  erro: "Erro",
};

function definirEstado(estado) {
  elementos.estado.dataset.estado = estado;
  elementos.estado.textContent = ROTULOS_DE_ESTADO[estado];
}

function mostrarErro(mensagem) {
  elementos.erro.hidden = false;
  elementos.erro.textContent = mensagem;
  definirEstado("erro");
}

function limparErro() {
  elementos.erro.hidden = true;
  elementos.erro.textContent = "";
}

async function selecionarCredenciais(arquivo) {
  limparErro();
  elementos.painelResultado.hidden = true;
  elementos.painelProgresso.hidden = true;
  conteudoRecuperado = null;

  let texto;
  try {
    texto = await arquivo.text();
  } catch (erro) {
    console.error(erro);
    mostrarErro("Não foi possível ler o arquivo selecionado.");
    return;
  }

  try {
    credenciais = await parseCredentials(texto);
  } catch (erro) {
    console.error(erro);
    credenciais = null;
    mostrarErro(erro.message);
    return;
  }

  definirEstado("verificando");

  // Consultamos a disponibilidade antes de iniciar qualquer download: um
  // arquivo expirado precisa ser informado agora, e não depois de uma espera
  // inútil.
  let metadados;
  try {
    metadados = await fetchMetadata(credenciais.locator);
  } catch (erro) {
    console.error(erro);
    mostrarErro(erro.message);
    return;
  }

  elementos.dadoNome.textContent = credenciais.filename;
  elementos.dadoTamanho.textContent =
    `${formatBytes(metadados.size_bytes)} cifrados` +
    (credenciais.size !== null ? ` — ${formatBytes(credenciais.size)} originais` : "");
  elementos.dadoLocalizador.textContent = credenciais.locator;
  elementos.dadoValidade.textContent =
    `${metadados.expires_at} (${formatRemaining(metadados.expires_at)})`;

  elementos.painelDisponibilidade.hidden = false;
  definirEstado("pronto");
  elementos.botaoBaixar.focus();
}

async function baixarEDecifrar() {
  if (!credenciais) return;

  limparErro();
  elementos.botaoBaixar.disabled = true;
  elementos.botaoTrocar.disabled = true;
  elementos.painelProgresso.hidden = false;
  progressoDownload.reset();
  progressoDecifragem.reset();
  setUnloadGuard(true);

  try {
    definirEstado("baixando");
    const cifra = await downloadCiphertext(credenciais.locator, (baixado, total) =>
      progressoDownload.set(baixado, total),
    );

    definirEstado("decifrando");
    // Como na cifragem, a decifragem é uma chamada única: a barra indica
    // trabalho em curso, sem fingir medir bytes.
    progressoDecifragem.indeterminate("Conferindo a etiqueta e decifrando…");

    // A falha aqui significa exatamente uma coisa — chave incorreta ou arquivo
    // adulterado — e é isso que o usuário lê. Nunca um "erro inesperado".
    conteudoRecuperado = await decrypt(credenciais.key, credenciais.nonce, cifra);

    progressoDecifragem.set(conteudoRecuperado.length, conteudoRecuperado.length);

    elementos.resultadoNome.textContent = credenciais.filename;
    elementos.resultadoTamanho.textContent =
      `${formatBytes(conteudoRecuperado.length)} (${conteudoRecuperado.length} bytes)`;

    document.getElementById("titulo-progresso").textContent = "Download e decifragem concluídos";
    elementos.painelDisponibilidade.hidden = true;
    elementos.passoSelecao.hidden = true;
    elementos.painelResultado.hidden = false;

    salvarArquivo();
    definirEstado("concluido");
    elementos.botaoSalvarNovamente.focus();
  } catch (erro) {
    console.error(erro);
    mostrarErro(erro.message);
    elementos.botaoBaixar.disabled = false;
    elementos.botaoTrocar.disabled = false;
  } finally {
    setUnloadGuard(false);
  }
}

function salvarArquivo() {
  if (!conteudoRecuperado || !credenciais) return;
  // O tipo é genérico de propósito: o sistema não guarda nem adivinha o tipo
  // MIME do arquivo original.
  const blob = new Blob([conteudoRecuperado], { type: "application/octet-stream" });
  downloadBlob(blob, credenciais.filename);
}

function recomecar() {
  credenciais = null;
  conteudoRecuperado = null;
  elementos.entradaCredenciais.value = "";
  elementos.passoSelecao.hidden = false;
  elementos.painelDisponibilidade.hidden = true;
  elementos.painelProgresso.hidden = true;
  elementos.painelResultado.hidden = true;
  elementos.botaoBaixar.disabled = false;
  elementos.botaoTrocar.disabled = false;
  progressoDownload.reset();
  progressoDecifragem.reset();
  document.getElementById("titulo-progresso").textContent = "Processando";
  limparErro();
  definirEstado("repouso");
  elementos.dropzone.focus();
}

setupDropzone(elementos.dropzone, elementos.entradaCredenciais, selecionarCredenciais);
elementos.botaoBaixar.addEventListener("click", baixarEDecifrar);
elementos.botaoTrocar.addEventListener("click", () => elementos.entradaCredenciais.click());
elementos.botaoSalvarNovamente.addEventListener("click", salvarArquivo);
elementos.botaoRecomecar.addEventListener("click", recomecar);
