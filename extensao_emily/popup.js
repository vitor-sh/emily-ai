/**
 * popup.js — Lógica do popup da extensão Emily Browser Bridge
 * Lê o status de conexão do chrome.storage.local e atualiza a UI.
 */

const $ = id => document.getElementById(id);
const indicator = $("indicator");
const statusLabel = $("status-label");
const statusSub = $("status-sub");
const refresh = $("refresh");

function atualizarUI(conectado) {
  if (conectado) {
    indicator.className = "indicator conectado";
    statusLabel.className = "status-label conectado";
    statusLabel.textContent = "Conectada";
    statusSub.textContent = "Serviço local pronto para receber seus pedidos";
  } else {
    indicator.className = "indicator desconectado";
    statusLabel.className = "status-label desconectado";
    statusLabel.textContent = "Desconectada";
    statusSub.textContent = "Confira se o gateway está ativo e se o token foi salvo";
  }
}

function dominio(url) {
  try { return new URL(url).hostname || new URL(url).protocol; }
  catch (_) { return url || "Nenhuma aba"; }
}

async function carregar() {
  refresh.disabled = true;
  refresh.textContent = "Analisando...";
  try {
    const dados = await chrome.runtime.sendMessage({ tipo: "POPUP_DIAGNOSTICO" });
    atualizarUI(!!dados?.conectado);
    $("version").textContent = `Emily v${dados?.versao || chrome.runtime.getManifest().version}`;
    const aba = dados?.aba;
    $("page-title").textContent = aba?.titulo || "Nenhuma aba disponível";
    $("page-domain").textContent = dominio(aba?.url);
    $("media-count").textContent = String(dados?.midias ?? 0);
    $("access-status").textContent = aba?.restrita ? "Restrito" : (aba ? "Completo" : "—");
    $("favicon").src = aba?.url?.startsWith("http")
      ? chrome.runtime.getURL(`/_favicon/?pageUrl=${encodeURIComponent(aba.url)}&size=64`)
      : "icon.png";
    const notice = $("notice");
    if (aba?.restrita) {
      notice.className = "notice warning";
      notice.textContent = "Páginas internas do navegador e lojas de extensões não permitem automação. Abra um site comum para usar a Emily.";
    } else if (dados?.erro) {
      notice.className = "notice warning";
      notice.textContent = `Não foi possível analisar esta página: ${dados.erro}`;
    } else {
      notice.className = "notice";
      notice.textContent = "A Emily só age quando você pede. CAPTCHA, login e conteúdo protegido continuam sob seu controle.";
    }
  } catch (e) {
    atualizarUI(false);
    $("notice").className = "notice warning";
    $("notice").textContent = "O service worker da extensão não respondeu. Recarregue a extensão na página de extensões.";
  } finally {
    refresh.disabled = false;
    refresh.textContent = "Analisar novamente";
  }
}

async function carregarConfig() {
  const cfg = await chrome.runtime.sendMessage({ tipo: "POPUP_CONFIG_OBTER" });
  if (cfg?.url) $("bridge-url").value = cfg.url;
  $("config-status").textContent = cfg?.token_configurado
    ? "Token configurado. Ele não é exibido novamente."
    : "Cole o mesmo EMILY_PONTE_TOKEN configurado no gateway.";
}

async function salvarConfig() {
  const botao = $("save-config");
  botao.disabled = true;
  $("config-status").textContent = "Salvando e reconectando...";
  try {
    const resposta = await chrome.runtime.sendMessage({
      tipo: "POPUP_CONFIG_SALVAR",
      url: $("bridge-url").value,
      token: $("bridge-token").value,
    });
    if (resposta?.erro) throw new Error(resposta.erro);
    $("bridge-token").value = "";
    $("config-status").textContent = "Configuração salva. Reconexão iniciada.";
    setTimeout(carregar, 500);
  } catch (e) {
    $("config-status").textContent = e.message || String(e);
  } finally {
    botao.disabled = false;
  }
}

// Lê o estado inicial ao abrir o popup
chrome.storage.local.get(["emily_conectado"], result => atualizarUI(result.emily_conectado === true));

// Observa mudanças em tempo real (quando o background conecta/desconecta)
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "emily_conectado" in changes) {
    atualizarUI(changes.emily_conectado.newValue === true);
  }
});

refresh.addEventListener("click", carregar);
$("downloads").addEventListener("click", () => chrome.runtime.sendMessage({ tipo: "POPUP_ABRIR_DOWNLOADS" }));
$("save-config").addEventListener("click", salvarConfig);
carregarConfig().catch(() => {});
carregar();
