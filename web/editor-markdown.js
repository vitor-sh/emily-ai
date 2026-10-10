/* Renderer do chat da Emily; isolado para os editores. */
const svg=()=>'', ICO={copiar:''};
const esc = t => String(t ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/* As instruções entre colchetes pertencem ao Fish Audio, não à conversa.
   O texto cru continua intacto no backend/TTS; só a camada visual as oculta. */
const TAGS_VOZ_FISH = new Set(["angry", "breathy", "chuckling", "clear throat", "clears throat", "confident", "conversational", "crying", "curious", "embarrassed", "empathetic", "emphasis", "excited", "exhale", "friendly", "gasp", "giggle", "grateful", "groan", "in a hurry tone", "inhale", "laughing", "laughs", "long pause", "loud voice", "low voice", "nervous", "panting", "pause", "relieved", "sad", "scared", "screaming", "short pause", "shouting", "sigh", "sighing", "sobbing", "soft", "soft voice", "speaking slowly", "surprised", "tender", "tired", "whisper", "whispering"]);
const PADRAO_TAG_VOZ_LIVRE = /^(?:speaking|sighing|sighs|sigh|sobbing|chuckling|gasping|hesitating|breathing|pausing|pause|whispering|whisper|shouting|screaming|laughing|laughs|laugh|crying|smiling|nodding|tilting|exclaiming|mumbling|sniffling|stuttering|trailing|curious|cheerful|excited|sad|angry|nervous|scared|confident|surprised|calm|sarcastic|teasing|warm|cold|soft|firm|gentle|serious|playful|mocking|smooth|friendly|empathetic|relieved|grateful|embarrassed|conversational|breathy|tender|tired|dead tired|professional|low voice|loud voice|voice breaking|voice rough|pitch up|pitch down|short pause|long pause|emphasis|inhale|exhale|gasp|panting|giggle|groan|clear throat|clears throat|falando|rindo|hesitando|sussurrando|gritando|chorando|suspirando|pausa|calma|com (?:um |uma )?tom|(?:with|in) (?:a |an )?.*tone\b|(?:emotion|tone|style|mood|voice)\s*[:=])\b/i;

function textoVisivelSemTagsDeVoz(texto) {
  return String(texto ?? '')
    .replace(/\[([^\]\r\n]{1,80})\]/g, (tagCompleta, conteudo) => {
      const tag = String(conteudo || '').trim().toLowerCase();
      const livre = PADRAO_TAG_VOZ_LIVRE.test(tag);
      return TAGS_VOZ_FISH.has(tag) || livre ? '' : tagCompleta;
    })
    // O texto do modelo também passa por aqui: recuos de código e quebras de
    // tabela precisam chegar intactos ao renderizador Markdown.
    .trim();
}

/* Estado do saneamento incremental. O backend já filtra o caminho normal, mas
   esta segunda barreira protege eventos vindos de integrações/reconexões que
   chamem `delta` diretamente. Nunca renderiza "[exci" enquanto espera "ted]". */
let _tagVozPendente = '';
function deltaVisivelSemTagsDeVoz(pedaco, finalizar = false) {
  const entrada = _tagVozPendente + String(pedaco ?? '');
  _tagVozPendente = '';
  let saida = '', pos = 0;
  while (pos < entrada.length) {
    const abre = entrada.indexOf('[', pos);
    if (abre < 0) { saida += entrada.slice(pos); break; }
    saida += entrada.slice(pos, abre);
    const fecha = entrada.indexOf(']', abre + 1);
    if (fecha < 0) {
      const candidato = entrada.slice(abre);
      if (finalizar || candidato.includes('\n') || candidato.length > 82) saida += candidato;
      else _tagVozPendente = candidato;
      break;
    }
    const conteudo = entrada.slice(abre + 1, fecha);
    const tag = conteudo.trim().toLowerCase();
    const livre = PADRAO_TAG_VOZ_LIVRE.test(tag);
    if (conteudo.length <= 80 && (TAGS_VOZ_FISH.has(tag) || livre)) {
      pos = fecha + 1;
      continue;
    }
    saida += entrada.slice(abre, fecha + 1);
    pos = fecha + 1;
  }
  return saida;
}

/* ── Realce de código ──────────────────────────────────────────────
   Sem biblioteca externa (é app local, offline). Um tokenizador só, que
   colore o que dá o visual de "código de verdade" na esmagadora maioria
   das linguagens que ela manda: comentário, string, número, palavra-chave,
   constante e nome de função. Não é um parser por linguagem — é um passe
   genérico que acerta Python, JS, e a maioria das de sintaxe C-like. */

const _COD_KW = new Set((
  // controle e declaração — a união das linguagens comuns
  'def class return if elif else for while try except finally raise with as ' +
  'import from in is not and or lambda yield global nonlocal pass break continue assert del ' +
  'async await function var let const new typeof instanceof of do switch case default throw ' +
  'public private protected static void int float double char boolean string export interface ' +
  'extends implements package super this end then elsif module fn use struct impl match'
).split(' '));

const _COD_CONST = new Set(
  'True False None self __name__ true false null undefined nil NaN Infinity'.split(' '));

function destacar(codigo) {
  // Ordem importa: comentário e string primeiro, pra não colorir palavra
  // dentro deles. O último grupo ([\s\S]) garante que nada escapa sem escape.
  const re = /(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/|"""[\s\S]*?"""|'''[\s\S]*?''')|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.eExXbBoOaAfF]*\b)|([A-Za-z_$][\w$]*)(\s*\()?|([\s\S])/g;
  let out = '';
  codigo.replace(re, (m, com, str, num, id, chamada, resto) => {
    if (com != null) out += `<span class="tk-com">${esc(com)}</span>`;
    else if (str != null) out += `<span class="tk-str">${esc(str)}</span>`;
    else if (num != null) out += `<span class="tk-num">${esc(num)}</span>`;
    else if (id != null) {
      const cls = _COD_KW.has(id) ? 'tk-kw'
        : _COD_CONST.has(id) ? 'tk-const'
          : chamada ? 'tk-fn' : null;
      const marcado = cls ? `<span class="${cls}">${esc(id)}</span>` : esc(id);
      out += marcado + (chamada || '');
    } else out += esc(resto);
    return '';
  });
  return out;
}

// Nome bonito da linguagem pra mostrar no topo do bloco.
const _COD_NOME = {
  py: 'Python', python: 'Python', js: 'JavaScript', javascript: 'JavaScript',
  ts: 'TypeScript', typescript: 'TypeScript', jsx: 'JSX', tsx: 'TSX',
  html: 'HTML', css: 'CSS', json: 'JSON', bash: 'Bash', sh: 'Shell',
  shell: 'Shell', sql: 'SQL', java: 'Java', c: 'C', cpp: 'C++', 'c++': 'C++',
  cs: 'C#', csharp: 'C#', go: 'Go', rust: 'Rust', rs: 'Rust', php: 'PHP',
  rb: 'Ruby', ruby: 'Ruby', yaml: 'YAML', yml: 'YAML', md: 'Markdown',
  toml: 'TOML', xml: 'XML', kt: 'Kotlin', kotlin: 'Kotlin', lua: 'Lua',
};

function inline(t) {
  return esc(t)
    .replace(/`([^`\n]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<![*\w])\*([^*\n]+)\*(?![*\w])/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, '$1<a href="$2" target="_blank">$2</a>');
}

function markdown(bruto) {
  const texto = String(bruto ?? '');
  const saida = [];
  // Fence primeiro: o conteúdo dele não passa por mais nenhuma regra.
  const partes = texto.split(/```/);
  partes.forEach((parte, i) => {
    if (i % 2 === 1) {
      const nl = parte.indexOf('\n');
      const rotulo = (nl >= 0 ? parte.slice(0, nl) : '').trim().toLowerCase();
      // Se não veio nome de linguagem, o "primeiro token" NÃO é linguagem —
      // é código. Só corta a primeira linha como rótulo se ela for uma
      // palavra só (nome de linguagem), senão é tudo código.
      const ehRotulo = /^[a-z0-9+#]{1,15}$/.test(rotulo);
      const cod = (ehRotulo && nl >= 0 ? parte.slice(nl + 1) : parte).replace(/^\n/, '').replace(/\n$/, '');
      const lang = ehRotulo ? rotulo : '';
      const nome = _COD_NOME[lang] || (lang ? lang : 'código');
      saida.push(
        `<div class="bloco-cod"><div class="bloco-cod-topo"><span>${esc(nome)}</span>` +
        `<button class="btn-copiar-cod" data-cod="${encodeURIComponent(cod)}">` +
        svg(ICO.copiar) + `copiar</button></div>` +
        `<pre><code>${destacar(cod)}</code></pre></div>`
      );
    } else {
      saida.push(blocos(parte));
    }
  });
  return saida.join('');
}

function _celulasTabela(linha) {
  let miolo = String(linha || '').trim();
  if (miolo.startsWith('|')) miolo = miolo.slice(1);
  if (miolo.endsWith('|')) miolo = miolo.slice(0, -1);

  const celulas = [];
  let atual = '', escapado = false, emCodigo = false;
  for (const caractere of miolo) {
    if (escapado) {
      atual += caractere;
      escapado = false;
    } else if (caractere === '\\') {
      escapado = true;
    } else if (caractere === '`') {
      emCodigo = !emCodigo;
      atual += caractere;
    } else if (caractere === '|' && !emCodigo) {
      celulas.push(atual.trim());
      atual = '';
    } else atual += caractere;
  }
  celulas.push(atual.trim());
  return celulas;
}

function _separadorTabela(linha) {
  const celulas = _celulasTabela(linha);
  return celulas.length > 0 && celulas.every(c => /^:?-{3,}:?$/.test(c));
}

function _alinhamentosTabela(linha) {
  return _celulasTabela(linha).map(c => {
    if (c.startsWith(':') && c.endsWith(':')) return 'al-centro';
    if (c.endsWith(':')) return 'al-dir';
    return 'al-esq';
  });
}

function _linhaTabela(celulas, tag, alinhamentos, total) {
  const prontas = celulas.slice(0, total);
  while (prontas.length < total) prontas.push('');
  return `<tr>${prontas.map((c, i) =>
    `<${tag} class="${alinhamentos[i] || 'al-esq'}">${inline(c)}</${tag}>`
  ).join('')}</tr>`;
}

function blocos(trecho) {
  // Alguns modelos colam um header no fim da frase mesmo quando foram
  // instruídos a deixá-lo numa linha própria. O marcador com 2+ # é específico
  // o bastante para recuperar a estrutura sem confundir conversa normal.
  const normalizado = String(trecho).replace(/([^\n])\s+(#{2,6}\s+)/g, '$1\n\n$2');
  const linhas = normalizado.split('\n');
  const out = [];
  let lista = null, para = [], citacao = [];

  const fechaPara = () => {
    if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
  };
  const fechaLista = () => {
    if (lista) { out.push(`<${lista.tag}>${lista.itens.join('')}</${lista.tag}>`); lista = null; }
  };
  const fechaCitacao = () => {
    if (citacao.length) {
      out.push(`<blockquote>${inline(citacao.join(' '))}</blockquote>`);
      citacao = [];
    }
  };

  for (let i = 0; i < linhas.length; i++) {
    const linha = linhas[i];
    const l = linha.trim();
    if (!l) { fechaPara(); fechaLista(); fechaCitacao(); continue; }

    const cabecalho = l.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (cabecalho) {
      fechaPara(); fechaLista(); fechaCitacao();
      const nivel = Math.min(6, cabecalho[1].length);
      out.push(`<h${nivel}>${inline(cabecalho[2])}</h${nivel}>`);
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(l)) {
      fechaPara(); fechaLista(); fechaCitacao();
      out.push('<hr>');
      continue;
    }

    const linhaSeguinte = linhas[i + 1]?.trim() || '';
    if (l.includes('|') && _separadorTabela(linhaSeguinte)) {
      fechaPara(); fechaLista(); fechaCitacao();
      const cabecalhos = _celulasTabela(l);
      const alinhamentos = _alinhamentosTabela(linhaSeguinte);
      const total = cabecalhos.length;
      const corpo = [];
      i += 2;
      while (i < linhas.length) {
        const candidata = linhas[i].trim();
        if (!candidata || !candidata.includes('|')) break;
        corpo.push(_linhaTabela(_celulasTabela(candidata), 'td', alinhamentos, total));
        i++;
      }
      i--;
      out.push(
        '<div class="md-tabela-wrap" role="region" aria-label="Tabela da resposta" tabindex="0">' +
        '<table class="md-tabela"><thead>' +
        _linhaTabela(cabecalhos, 'th', alinhamentos, total) +
        `</thead>${corpo.length ? `<tbody>${corpo.join('')}</tbody>` : ''}</table></div>`
      );
      continue;
    }

    const mCitacao = l.match(/^>\s?(.*)$/);
    if (mCitacao) {
      fechaPara(); fechaLista();
      citacao.push(mCitacao[1]);
      continue;
    }
    fechaCitacao();

    const mUl = l.match(/^[-*+•]\s+(.*)$/);
    const mOl = l.match(/^\d+[.)]\s+(.*)$/);
    if (mUl || mOl) {
      fechaPara();
      const tag = mUl ? 'ul' : 'ol';
      if (!lista || lista.tag !== tag) { fechaLista(); lista = { tag, itens: [] }; }
      lista.itens.push(`<li>${inline((mUl || mOl)[1])}</li>`);
      continue;
    }
    fechaLista();
    para.push(l);
  }
  fechaPara(); fechaLista(); fechaCitacao();
  return out.join('');
}

/* ════════════════════════════════════════════════════════════════
   TOASTS
   ════════════════════════════════════════════════════════════════ */

