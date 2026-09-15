/**
 * crypto.js — núcleo criptográfico do navegador.
 *
 * Este módulo é o espelho do `cofre.py`. Ele implementa exatamente o mesmo
 * formato: AES-256-GCM, chave de 32 bytes, nonce de 12 bytes, etiqueta de
 * autenticidade de 128 bits anexada ao fim da cifra e nenhum associated data.
 * Um arquivo cifrado aqui é decifrável lá, e vice-versa — o teste de
 * interoperabilidade em tests/interop/ existe para provar isso a cada execução.
 *
 * As quatro funções centrais são puras: recebem bytes, devolvem bytes, não
 * tocam no DOM, não fazem requisição e não gravam nada em lugar nenhum.
 * Nenhum valor secreto sai deste módulo por conta própria.
 */

// Constantes do formato. São as mesmas do cofre.py, com os mesmos valores.
export const FORMAT_VERSION = 1;
export const ALGORITHM = "AES-256-GCM";
export const KEY_SIZE = 32; // 32 bytes = 256 bits
export const NONCE_SIZE = 12; // tamanho recomendado para o modo GCM
export const TAG_SIZE = 16; // etiqueta de autenticidade: 16 bytes = 128 bits

/** Mensagem única para a falha de autenticação, conforme a regra 3 do plano. */
export const AUTHENTICATION_FAILURE_MESSAGE =
  "Chave incorreta ou arquivo adulterado.";

/**
 * Erro lançado quando o AES-GCM recusa a decifragem.
 *
 * Equivale ao `InvalidTag` do cofre.py e significa exatamente uma coisa: ou a
 * chave está errada, ou os bytes foram alterados depois de cifrados. Nunca é
 * um erro genérico, e nunca deve ser silenciado.
 */
export class AuthenticationError extends Error {
  constructor(options) {
    super(AUTHENTICATION_FAILURE_MESSAGE, options);
    this.name = "AuthenticationError";
  }
}

/**
 * Gera uma chave de 32 bytes.
 *
 * Não é senha e não é derivada de nada: é ruído de um gerador
 * criptograficamente seguro, como o `AESGCM.generate_key` do cofre.py.
 */
export function generateKey() {
  return crypto.getRandomValues(new Uint8Array(KEY_SIZE));
}

/**
 * Gera um nonce de 12 bytes, novo a cada cifragem.
 *
 * O nonce não é segredo — ele viaja em claro dentro do JSON de credenciais —,
 * mas o par (chave, nonce) jamais pode se repetir. Como a chave também é nova
 * a cada envio, a repetição é impossível na prática.
 */
export function generateNonce() {
  return crypto.getRandomValues(new Uint8Array(NONCE_SIZE));
}

/**
 * Cifra `plaintext` e devolve `cifra || etiqueta`.
 *
 * A Web Crypto já anexa a etiqueta ao fim do resultado, que é o mesmo layout
 * produzido pelo `aesgcm.encrypt(nonce, dados, None)` do Python. Por isso o
 * retorno tem sempre `plaintext.length + 16` bytes.
 */
export async function encrypt(keyBytes, nonceBytes, plaintext) {
  const key = await importKey(keyBytes, "encrypt");
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: assertNonce(nonceBytes), tagLength: TAG_SIZE * 8 },
    key,
    plaintext,
  );
  return new Uint8Array(ciphertext);
}

/**
 * Decifra `ciphertext` (que inclui a etiqueta no fim) e devolve os bytes
 * originais.
 *
 * Toda a chamada está dentro de um try/catch, e a falha é traduzida para um
 * `AuthenticationError` com a mensagem exigida pelo plano. Qualquer outro erro
 * — chave com tamanho errado, argumento inválido — é relançado como veio: só a
 * recusa da etiqueta vira falha de autenticação, e nada é engolido.
 */
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
    // A Web Crypto sinaliza etiqueta inválida com OperationError. É o
    // equivalente exato do InvalidTag do cofre.py.
    if (erro instanceof Error && erro.name === "OperationError") {
      throw new AuthenticationError({ cause: erro });
    }
    throw erro;
  }
}

/**
 * Calcula o localizador: SHA-256 da chave, em hexadecimal minúsculo.
 *
 * É o endereço do arquivo no servidor. A função é de mão única: o servidor
 * consegue conferir se um localizador existe, mas não consegue voltar dele
 * para a chave.
 */
export async function computeLocator(keyBytes) {
  const digest = await crypto.subtle.digest("SHA-256", assertKey(keyBytes));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

// ---------------------------------------------------------------------------
// Utilidades de codificação. Equivalem ao b64/de_b64 do cofre.py e existem
// porque bytes crus não cabem dentro de um JSON.
// ---------------------------------------------------------------------------

/** Bytes crus -> texto base64. */
export function toBase64(bytes) {
  // Convertido em blocos porque `String.fromCharCode(...bytes)` estoura a
  // pilha de chamadas com arrays grandes.
  let binario = "";
  const BLOCO = 0x8000;
  for (let inicio = 0; inicio < bytes.length; inicio += BLOCO) {
    binario += String.fromCharCode(...bytes.subarray(inicio, inicio + BLOCO));
  }
  return btoa(binario);
}

/** Texto base64 -> bytes crus. */
export function fromBase64(texto) {
  const binario = atob(texto);
  const bytes = new Uint8Array(binario.length);
  for (let i = 0; i < binario.length; i += 1) {
    bytes[i] = binario.charCodeAt(i);
  }
  return bytes;
}

// ---------------------------------------------------------------------------
// Conferências internas
// ---------------------------------------------------------------------------

function assertKey(keyBytes) {
  if (!(keyBytes instanceof Uint8Array) || keyBytes.length !== KEY_SIZE) {
    throw new TypeError(`A chave precisa ter exatamente ${KEY_SIZE} bytes.`);
  }
  return keyBytes;
}

function assertNonce(nonceBytes) {
  if (!(nonceBytes instanceof Uint8Array) || nonceBytes.length !== NONCE_SIZE) {
    throw new TypeError(`O nonce precisa ter exatamente ${NONCE_SIZE} bytes.`);
  }
  return nonceBytes;
}

/**
 * Importa os bytes da chave para dentro da Web Crypto.
 *
 * O quarto argumento (`extractable`) é `false`: a chave importada não pode ser
 * exportada de volta pelo JavaScript. Os bytes originais continuam na memória
 * da aba — é de lá que o JSON de credenciais é montado —, mas o objeto CryptoKey
 * em si não vaza. A chave também é importada com um único uso por vez, cifrar
 * ou decifrar, nunca os dois.
 */
async function importKey(keyBytes, usage) {
  return crypto.subtle.importKey(
    "raw",
    assertKey(keyBytes),
    { name: "AES-GCM" },
    false,
    [usage],
  );
}
