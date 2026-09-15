/**
 * credenciais.js — leitura e escrita do arquivo de credenciais.
 *
 * O JSON de credenciais é o único lugar do sistema onde a chave, o nonce e o
 * nome do arquivo existem. Ele é gerado no navegador, baixado para o disco de
 * quem envia e nunca, em hipótese alguma, enviado ao servidor.
 *
 * O formato é o mesmo produzido pelo cofre.py, campo a campo.
 */

import {
  ALGORITHM,
  FORMAT_VERSION,
  KEY_SIZE,
  NONCE_SIZE,
  computeLocator,
  fromBase64,
  toBase64,
} from "./crypto.js";

/**
 * Erro de credenciais, com mensagem já escrita para o usuário final.
 *
 * Separado do erro de autenticação de propósito: "seu JSON está quebrado" e
 * "a chave não abre este arquivo" são problemas diferentes, com ações
 * diferentes, e merecem mensagens diferentes.
 */
export class CredentialsError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "CredentialsError";
  }
}

/** Monta o objeto de credenciais, pronto para virar JSON. */
export function buildCredentials({ key, nonce, locator, filename, size, expiresAt }) {
  return {
    version: FORMAT_VERSION,
    algorithm: ALGORITHM,
    key: toBase64(key),
    nonce: toBase64(nonce),
    hash: locator,
    filename,
    size,
    expires_at: expiresAt,
  };
}

/** Nome sugerido para o arquivo baixado: credenciais-<8 primeiros do hash>.json */
export function credentialsFilename(locator) {
  return `credenciais-${locator.slice(0, 8)}.json`;
}

/**
 * Lê e confere um arquivo de credenciais.
 *
 * Devolve os campos já convertidos para bytes. Cada recusa tem uma mensagem
 * específica, porque "erro inesperado" não diz a ninguém o que fazer em
 * seguida.
 */
export async function parseCredentials(texto) {
  let dados;
  try {
    dados = JSON.parse(texto);
  } catch (erro) {
    throw new CredentialsError(
      "Este arquivo não é um JSON válido. Selecione o arquivo " +
        "credenciais-*.json que foi baixado no momento do envio.",
      { cause: erro },
    );
  }

  if (dados === null || typeof dados !== "object" || Array.isArray(dados)) {
    throw new CredentialsError(
      "O conteúdo do arquivo não tem o formato de credenciais esperado.",
    );
  }

  // A versão é conferida antes de qualquer outra coisa: um arquivo de uma
  // versão futura deve ser recusado com clareza, nunca interpretado errado.
  if (dados.version !== FORMAT_VERSION) {
    throw new CredentialsError(
      `Versão de formato não suportada: ${JSON.stringify(dados.version)}. ` +
        `Este sistema lê apenas a versão ${FORMAT_VERSION}.`,
    );
  }

  if (dados.algorithm !== ALGORITHM) {
    throw new CredentialsError(
      `Algoritmo não suportado: ${JSON.stringify(dados.algorithm)}. ` +
        `Este sistema usa ${ALGORITHM}.`,
    );
  }

  const key = decodeField(dados.key, KEY_SIZE, "chave");
  const nonce = decodeField(dados.nonce, NONCE_SIZE, "nonce");

  if (typeof dados.hash !== "string" || !/^[0-9a-f]{64}$/.test(dados.hash)) {
    throw new CredentialsError(
      "O campo de hash não é um SHA-256 em hexadecimal. " +
        "O arquivo de credenciais está corrompido.",
    );
  }

  // A mesma conferência de sanidade do cofre.py: o hash declarado bate com a
  // chave que o arquivo carrega? Se não bate, o JSON foi montado errado, foi
  // editado à mão ou se corrompeu no caminho — e seguir em frente só produziria
  // uma falha de autenticação confusa lá na frente.
  const locatorCalculado = await computeLocator(key);
  if (locatorCalculado !== dados.hash) {
    throw new CredentialsError(
      "O hash não corresponde à chave: as credenciais estão corrompidas. " +
        "Peça um novo envio a quem mandou o arquivo.",
    );
  }

  if (typeof dados.filename !== "string" || dados.filename.trim() === "") {
    throw new CredentialsError(
      "O arquivo de credenciais não informa o nome do arquivo original.",
    );
  }

  return {
    key,
    nonce,
    locator: dados.hash,
    filename: sanitizeFilename(dados.filename),
    size: Number.isInteger(dados.size) ? dados.size : null,
    expiresAt: typeof dados.expires_at === "string" ? dados.expires_at : null,
  };
}

/** Decodifica um campo base64 e confere o tamanho esperado. */
function decodeField(valor, tamanhoEsperado, nome) {
  if (typeof valor !== "string") {
    throw new CredentialsError(
      `O arquivo de credenciais não contém o campo "${nome}".`,
    );
  }

  let bytes;
  try {
    bytes = fromBase64(valor);
  } catch (erro) {
    throw new CredentialsError(
      `O campo "${nome}" não está em base64 válido. ` +
        "O arquivo de credenciais está corrompido.",
      { cause: erro },
    );
  }

  if (bytes.length !== tamanhoEsperado) {
    throw new CredentialsError(
      `O campo "${nome}" tem ${bytes.length} bytes, e deveria ter ` +
        `${tamanhoEsperado}. O arquivo de credenciais está corrompido.`,
    );
  }

  return bytes;
}

/**
 * Reduz o nome do arquivo ao seu último componente.
 *
 * O nome vem de um arquivo que outra pessoa escreveu, e vai ser usado para
 * gravar algo no disco de quem recebe. Um valor como "../../.bashrc" não deve
 * sobreviver a essa viagem.
 */
function sanitizeFilename(nome) {
  const semCaminho = nome.split(/[\\/]/).pop().trim();
  return semCaminho === "" || semCaminho === "." || semCaminho === ".."
    ? "arquivo-recuperado"
    : semCaminho;
}
