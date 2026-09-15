/**
 * ui.js — peças de interface compartilhadas pelas duas telas.
 *
 * Nada aqui toca em criptografia: são utilidades de apresentação, leitura de
 * arquivo com progresso e gravação de arquivo no disco de quem está usando.
 */

/** Formata um tamanho em bytes de forma legível, sem esconder o número exato. */
export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const unidades = ["KB", "MB", "GB"];
  let valor = bytes / 1024;
  let unidade = 0;
  while (valor >= 1024 && unidade < unidades.length - 1) {
    valor /= 1024;
    unidade += 1;
  }
  return `${valor.toFixed(valor < 10 ? 1 : 0)} ${unidades[unidade]}`;
}

/** Converte uma data de expiração em "faltam X h Y min". */
export function formatRemaining(expiresAtIso) {
  const expiraEm = new Date(expiresAtIso);
  if (Number.isNaN(expiraEm.getTime())) return "prazo desconhecido";

  const restanteMs = expiraEm.getTime() - Date.now();
  if (restanteMs <= 0) return "expirado";

  const minutos = Math.floor(restanteMs / 60000);
  const horas = Math.floor(minutos / 60);
  if (horas >= 1) return `faltam ${horas} h ${minutos % 60} min`;
  return `faltam ${minutos} min`;
}

/**
 * Liga uma área de arrastar-e-soltar a um `<input type="file">`.
 *
 * A área é um elemento focável: clicar, apertar Enter ou apertar Espaço abrem
 * o seletor de arquivos, de modo que quem navega por teclado tem o mesmo
 * caminho de quem usa o mouse.
 */
export function setupDropzone(area, input, aoReceberArquivo) {
  const abrirSeletor = () => input.click();

  area.addEventListener("click", abrirSeletor);
  area.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter" || evento.key === " ") {
      evento.preventDefault();
      abrirSeletor();
    }
  });

  input.addEventListener("change", () => {
    if (input.files && input.files.length > 0) {
      aoReceberArquivo(input.files[0]);
    }
  });

  ["dragenter", "dragover"].forEach((evento) => {
    area.addEventListener(evento, (e) => {
      e.preventDefault();
      area.classList.add("is-dragging");
    });
  });

  ["dragleave", "drop"].forEach((evento) => {
    area.addEventListener(evento, (e) => {
      e.preventDefault();
      area.classList.remove("is-dragging");
    });
  });

  area.addEventListener("drop", (evento) => {
    const arquivos = evento.dataTransfer?.files;
    if (arquivos && arquivos.length > 0) {
      aoReceberArquivo(arquivos[0]);
    }
  });
}

/**
 * Controla uma barra de progresso.
 *
 * `set` mostra bytes reais processados. `indeterminate` é usado apenas na
 * etapa em que não existe progresso para medir — a chamada de cifragem da Web
 * Crypto é atômica —, e nesse caso a barra assume uma aparência distinta, em
 * vez de fingir um avanço que não está acontecendo.
 */
export function createProgress(elemento) {
  const barra = elemento.querySelector(".progress-bar");
  const rotulo = elemento.querySelector(".progress-label");

  return {
    reset() {
      elemento.hidden = true;
      elemento.classList.remove("is-indeterminate");
      barra.style.width = "0%";
      elemento.setAttribute("aria-valuenow", "0");
      rotulo.textContent = "";
    },
    set(carregado, total) {
      elemento.hidden = false;
      elemento.classList.remove("is-indeterminate");
      const porcentagem = total > 0 ? Math.round((carregado / total) * 100) : 0;
      barra.style.width = `${porcentagem}%`;
      elemento.setAttribute("aria-valuenow", String(porcentagem));
      rotulo.textContent = `${porcentagem}% — ${formatBytes(carregado)} de ${formatBytes(total)}`;
    },
    indeterminate(texto) {
      elemento.hidden = false;
      elemento.classList.add("is-indeterminate");
      elemento.removeAttribute("aria-valuenow");
      barra.style.width = "100%";
      rotulo.textContent = texto;
    },
  };
}

/**
 * Lê um arquivo do disco reportando bytes lidos de verdade.
 *
 * A leitura é feita em pedaços pelo stream do próprio arquivo, então o
 * progresso corresponde a trabalho realmente concluído. Os pedaços são
 * remontados em um único bloco porque a cifragem que vem depois é uma operação
 * única sobre o conteúdo inteiro.
 */
export async function readFileWithProgress(file, onProgress) {
  if (typeof file.stream !== "function") {
    // Caminho de compatibilidade: sem stream não há progresso a reportar.
    const buffer = await file.arrayBuffer();
    if (onProgress) onProgress(file.size, file.size);
    return new Uint8Array(buffer);
  }

  const conteudo = new Uint8Array(file.size);
  const leitor = file.stream().getReader();
  let posicao = 0;

  for (;;) {
    const { done, value } = await leitor.read();
    if (done) break;
    conteudo.set(value, posicao);
    posicao += value.length;
    if (onProgress) onProgress(posicao, file.size);
  }

  return conteudo;
}

/** Entrega um blob ao usuário como download, com o nome indicado. */
export function downloadBlob(blob, filename) {
  const endereco = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = endereco;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Liberamos o endereço temporário depois que o navegador iniciou o download.
  setTimeout(() => URL.revokeObjectURL(endereco), 60_000);
}

/**
 * Liga e desliga o aviso de saída da página.
 *
 * Fechar a aba no meio da cifragem ou do upload perde trabalho que não pode
 * ser retomado: a chave está apenas na memória desta aba.
 */
export function setUnloadGuard(ativo) {
  if (ativo) {
    window.addEventListener("beforeunload", avisarSaida);
  } else {
    window.removeEventListener("beforeunload", avisarSaida);
  }
}

function avisarSaida(evento) {
  evento.preventDefault();
  // Navegadores modernos ignoram a mensagem e mostram um texto próprio, mas
  // ainda exigem que returnValue seja definido.
  evento.returnValue = "";
}
