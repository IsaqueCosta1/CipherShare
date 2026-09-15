/**
 * teste-cripto.js — página de teste manual do núcleo criptográfico.
 *
 * Faz o percurso completo sobre um arquivo local — cifrar, decifrar, comparar
 * byte a byte, adulterar e ver a recusa — sem tocar no servidor. É o
 * equivalente interativo do que o `cofre.py` faz na linha de comando.
 *
 * Esta página também é o ponto de entrada dos testes de interoperabilidade:
 * ela publica o módulo em `window.cofreCrypto` para que o Playwright possa
 * chamar as mesmas funções que a interface usa, sem precisar de uma versão
 * paralela do código.
 */

import {
  ALGORITHM,
  AuthenticationError,
  FORMAT_VERSION,
  TAG_SIZE,
  computeLocator,
  decrypt,
  encrypt,
  fromBase64,
  generateKey,
  generateNonce,
  toBase64,
} from "./crypto.js";
import { downloadBlob, formatBytes, readFileWithProgress, setupDropzone } from "./ui.js";

const registro = document.getElementById("registro");
const botaoRodar = document.getElementById("botao-rodar");
const botaoExportar = document.getElementById("botao-exportar");
const entradaArquivo = document.getElementById("entrada-arquivo");

let arquivo = null;
let ultimaExecucao = null;

function limpar() {
  registro.textContent = "";
}

function anotar(texto, classe) {
  const linha = document.createElement("span");
  if (classe) linha.className = classe;
  linha.textContent = `${texto}\n`;
  registro.appendChild(linha);
}

function selecionar(novoArquivo) {
  arquivo = novoArquivo;
  ultimaExecucao = null;
  botaoRodar.disabled = false;
  botaoExportar.disabled = true;
  limpar();
  anotar(`Arquivo: ${arquivo.name} (${arquivo.size} bytes)`);
  anotar("Clique em “Cifrar e decifrar localmente”.");
}

async function rodar() {
  if (!arquivo) return;
  botaoRodar.disabled = true;
  limpar();

  try {
    const conteudo = await readFileWithProgress(arquivo, null);
    anotar(`1. Lido do disco: ${conteudo.length} bytes (${formatBytes(conteudo.length)}).`);

    const chave = generateKey();
    const nonce = generateNonce();
    anotar(`2. Chave gerada: 32 bytes aleatórios — ${toBase64(chave)}`);
    anotar(`3. Nonce gerado: 12 bytes aleatórios — ${toBase64(nonce)}`);

    const localizador = await computeLocator(chave);
    anotar(`4. Localizador SHA-256(chave): ${localizador}`);

    const inicio = performance.now();
    const cifra = await encrypt(chave, nonce, conteudo);
    const duracao = Math.round(performance.now() - inicio);
    anotar(
      `5. Cifrado com ${ALGORITHM} em ${duracao} ms: ${cifra.length} bytes ` +
        `(${cifra.length - conteudo.length} a mais — a etiqueta de ${TAG_SIZE} bytes).`,
    );

    const recuperado = await decrypt(chave, nonce, cifra);
    anotar(`6. Decifrado: ${recuperado.length} bytes.`);

    const identico =
      recuperado.length === conteudo.length && recuperado.every((b, i) => b === conteudo[i]);
    anotar(
      identico
        ? "7. Comparação byte a byte: idêntico ao original. ✓"
        : "7. Comparação byte a byte: DIFERENTE do original. ✗",
      identico ? "ok" : "falha",
    );

    // Demonstração de adulteração, como o comando `adulterar` do cofre.py.
    const adulterada = cifra.slice();
    const posicao = Math.floor(adulterada.length / 2);
    const antes = adulterada[posicao];
    adulterada[posicao] = antes ^ 0xff;
    anotar(
      `8. Byte ${posicao} da cifra invertido: ${antes.toString(16).padStart(2, "0")} → ` +
        `${adulterada[posicao].toString(16).padStart(2, "0")}.`,
    );

    try {
      await decrypt(chave, nonce, adulterada);
      anotar("9. A adulteração passou despercebida. Isto não deveria acontecer.", "falha");
    } catch (erro) {
      if (erro instanceof AuthenticationError) {
        anotar(`9. Recusado: ${erro.message} ✓`, "ok");
      } else {
        throw erro;
      }
    }

    ultimaExecucao = { chave, nonce, localizador, cifra, nome: arquivo.name, tamanho: conteudo.length };
    botaoExportar.disabled = false;
    anotar("");
    anotar("Nenhuma requisição foi feita: confira a aba Network do DevTools.");
  } catch (erro) {
    console.error(erro);
    anotar(`Falha inesperada: ${erro.message}`, "falha");
  } finally {
    botaoRodar.disabled = false;
  }
}

/** Exporta os dois arquivos no formato que o cofre.py lê. */
function exportar() {
  if (!ultimaExecucao) return;
  const { chave, nonce, localizador, cifra, nome, tamanho } = ultimaExecucao;

  downloadBlob(new Blob([cifra], { type: "application/octet-stream" }), `${nome}.cifra`);

  const expiraEm = new Date(Date.now() + 24 * 60 * 60 * 1000)
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z");

  const credenciais = {
    version: FORMAT_VERSION,
    algorithm: ALGORITHM,
    key: toBase64(chave),
    nonce: toBase64(nonce),
    hash: localizador,
    filename: nome,
    size: tamanho,
    expires_at: expiraEm,
  };

  downloadBlob(
    new Blob([JSON.stringify(credenciais, null, 2)], { type: "application/json" }),
    `${nome}.credenciais.json`,
  );

  anotar("");
  anotar(`Exportado: ${nome}.cifra e ${nome}.credenciais.json`);
}

setupDropzone(document.getElementById("dropzone"), entradaArquivo, selecionar);
botaoRodar.addEventListener("click", rodar);
botaoExportar.addEventListener("click", exportar);

// Ponte para os testes automatizados de interoperabilidade. São as mesmas
// funções usadas pela interface — nada é reimplementado para o teste.
window.cofreCrypto = {
  generateKey,
  generateNonce,
  encrypt,
  decrypt,
  computeLocator,
  toBase64,
  fromBase64,
  AuthenticationError,
};
window.dispatchEvent(new Event("cofre-crypto-pronto"));
