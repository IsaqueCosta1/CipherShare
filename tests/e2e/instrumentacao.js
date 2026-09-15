// Instrumentação usada apenas pelos testes de rede.
//
// O Playwright não consegue devolver o corpo de uma requisição multipart que
// carrega um Blob — ele chega vazio, e uma asserção sobre um corpo vazio não
// prova coisa nenhuma. Então envolvemos o XMLHttpRequest e o fetch dentro da
// própria página e registramos, entrada por entrada, tudo o que a aplicação
// entrega à camada de rede: método, URL, cabeçalhos e cada parte do corpo,
// incluindo o conteúdo binário dos blobs.
//
// É um ponto de observação mais próximo da aplicação do que a rede: qualquer
// coisa que o código tentasse enviar apareceria aqui, mesmo que nunca chegasse
// ao servidor.

window.__capturas = [];

const abrirOriginal = XMLHttpRequest.prototype.open;
const cabecalhoOriginal = XMLHttpRequest.prototype.setRequestHeader;
const enviarOriginal = XMLHttpRequest.prototype.send;

XMLHttpRequest.prototype.open = function (metodo, url) {
  this.__info = { metodo, url, cabecalhos: {} };
  return abrirOriginal.apply(this, arguments);
};

XMLHttpRequest.prototype.setRequestHeader = function (nome, valor) {
  if (this.__info) this.__info.cabecalhos[nome] = valor;
  return cabecalhoOriginal.apply(this, arguments);
};

function paraBase64(bytes) {
  let binario = "";
  const BLOCO = 0x8000;
  for (let i = 0; i < bytes.length; i += BLOCO) {
    binario += String.fromCharCode(...bytes.subarray(i, i + BLOCO));
  }
  return btoa(binario);
}

XMLHttpRequest.prototype.send = function (corpo) {
  const registro = {
    origem: "xhr",
    metodo: this.__info?.metodo ?? "?",
    url: this.__info?.url ?? "?",
    cabecalhos: this.__info?.cabecalhos ?? {},
    partes: [],
    pendentes: 0,
  };
  window.__capturas.push(registro);

  if (corpo instanceof FormData) {
    for (const [nome, valor] of corpo.entries()) {
      if (valor instanceof Blob) {
        const parte = {
          nome,
          tipo: "blob",
          nomeDeArquivo: valor.name ?? null,
          tamanho: valor.size,
          conteudoB64: undefined,
        };
        registro.partes.push(parte);
        registro.pendentes += 1;
        valor.arrayBuffer().then((buffer) => {
          parte.conteudoB64 = paraBase64(new Uint8Array(buffer));
          registro.pendentes -= 1;
        });
      } else {
        registro.partes.push({ nome, tipo: "texto", valor: String(valor) });
      }
    }
  } else if (typeof corpo === "string") {
    registro.partes.push({ nome: "(corpo)", tipo: "texto", valor: corpo });
  } else if (corpo) {
    registro.partes.push({ nome: "(corpo)", tipo: "desconhecido", valor: String(corpo) });
  }

  return enviarOriginal.apply(this, arguments);
};

const fetchOriginal = window.fetch;
window.fetch = function (recurso, opcoes) {
  window.__capturas.push({
    origem: "fetch",
    metodo: opcoes?.method ?? "GET",
    url: String(recurso?.url ?? recurso),
    cabecalhos: opcoes?.headers ? Object.fromEntries(new Headers(opcoes.headers).entries()) : {},
    partes: opcoes?.body ? [{ nome: "(corpo)", tipo: "texto", valor: String(opcoes.body) }] : [],
    pendentes: 0,
  });
  return fetchOriginal.apply(this, arguments);
};
