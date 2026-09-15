/**
 * api.js — conversa com o servidor.
 *
 * Só três coisas atravessam esta fronteira: o localizador, os bytes cifrados e
 * os metadados de tamanho e validade. A chave, o nonce e o nome do arquivo não
 * aparecem em nenhuma função deste módulo — nem em URL, nem em cabeçalho, nem
 * em corpo de requisição. É por isso que o teste de rede em tests/e2e/ consegue
 * afirmar que nada vaza: não há por onde.
 *
 * Usamos XMLHttpRequest, e não fetch, por um motivo específico: é a única API
 * do navegador que reporta progresso de upload byte a byte.
 */

/** Erro de comunicação ou de resposta do servidor, com mensagem para o usuário. */
export class ApiError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "ApiError";
  }
}

/** O servidor não conhece este localizador — ou ele já expirou. */
export class NotFoundError extends ApiError {
  constructor() {
    super(
      "Arquivo expirado ou inexistente. Arquivos são apagados automaticamente " +
        "24 horas depois do envio.",
    );
    this.name = "NotFoundError";
  }
}

const MENSAGEM_SERVIDOR_INDISPONIVEL =
  "Servidor indisponível. Verifique sua conexão e tente novamente em instantes.";

/**
 * Envia a cifra. Devolve `{ locator, expires_at }`.
 *
 * `onProgress` recebe bytes enviados e total, e reflete o que o navegador
 * realmente entregou à rede.
 */
export function uploadCiphertext(locator, ciphertext, onProgress) {
  const formulario = new FormData();
  formulario.append("locator", locator);
  // O terceiro argumento é o nome do arquivo dentro do multipart. Ele é fixo e
  // genérico de propósito: o nome real do arquivo não pode chegar ao servidor.
  formulario.append("file", new Blob([ciphertext]), "cifra.bin");

  return new Promise((resolve, reject) => {
    const requisicao = new XMLHttpRequest();
    requisicao.open("POST", "/api/files");

    requisicao.upload.addEventListener("progress", (evento) => {
      if (evento.lengthComputable && onProgress) {
        onProgress(evento.loaded, evento.total);
      }
    });

    requisicao.addEventListener("load", () => {
      if (requisicao.status === 201) {
        try {
          resolve(JSON.parse(requisicao.responseText));
        } catch (erro) {
          reject(new ApiError("Resposta inesperada do servidor.", { cause: erro }));
        }
        return;
      }
      reject(erroDeUpload(requisicao.status));
    });

    requisicao.addEventListener("error", () => {
      reject(new ApiError(MENSAGEM_SERVIDOR_INDISPONIVEL));
    });
    requisicao.addEventListener("abort", () => {
      reject(new ApiError("Envio cancelado."));
    });

    requisicao.send(formulario);
  });
}

/** Consulta tamanho e validade antes de baixar. */
export function fetchMetadata(locator) {
  return new Promise((resolve, reject) => {
    const requisicao = new XMLHttpRequest();
    requisicao.open("GET", `/api/files/${locator}`);

    requisicao.addEventListener("load", () => {
      if (requisicao.status === 200) {
        try {
          resolve(JSON.parse(requisicao.responseText));
        } catch (erro) {
          reject(new ApiError("Resposta inesperada do servidor.", { cause: erro }));
        }
        return;
      }
      if (requisicao.status === 404) {
        reject(new NotFoundError());
        return;
      }
      reject(new ApiError(MENSAGEM_SERVIDOR_INDISPONIVEL));
    });

    requisicao.addEventListener("error", () => {
      reject(new ApiError(MENSAGEM_SERVIDOR_INDISPONIVEL));
    });

    requisicao.send();
  });
}

/** Baixa os bytes cifrados, reportando progresso real. */
export function downloadCiphertext(locator, onProgress) {
  return new Promise((resolve, reject) => {
    const requisicao = new XMLHttpRequest();
    requisicao.open("GET", `/api/files/${locator}/content`);
    requisicao.responseType = "arraybuffer";

    requisicao.addEventListener("progress", (evento) => {
      if (evento.lengthComputable && onProgress) {
        onProgress(evento.loaded, evento.total);
      }
    });

    requisicao.addEventListener("load", () => {
      if (requisicao.status === 200) {
        resolve(new Uint8Array(requisicao.response));
        return;
      }
      if (requisicao.status === 404) {
        reject(new NotFoundError());
        return;
      }
      reject(new ApiError(MENSAGEM_SERVIDOR_INDISPONIVEL));
    });

    requisicao.addEventListener("error", () => {
      reject(new ApiError(MENSAGEM_SERVIDOR_INDISPONIVEL));
    });

    requisicao.send();
  });
}

/** Traduz o código de resposta do upload para uma mensagem acionável. */
function erroDeUpload(status) {
  if (status === 413) {
    return new ApiError(
      "Arquivo acima do limite de 100 MB. Compacte ou divida o arquivo antes de enviar.",
    );
  }
  if (status === 409) {
    return new ApiError(
      "Já existe um arquivo com este localizador no servidor. " +
        "Tente enviar novamente — uma nova chave será gerada.",
    );
  }
  if (status === 400) {
    return new ApiError("O servidor recusou o localizador enviado.");
  }
  return new ApiError(MENSAGEM_SERVIDOR_INDISPONIVEL);
}
