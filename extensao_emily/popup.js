/**
 * popup.js — Lógica do popup da extensão Emily Browser Bridge
 * Lê o status de conexão do chrome.storage.local e atualiza a UI.
 */

const indicator = document.getElementById("indicator");
const statusLabel = document.getElementById("status-label");
const statusSub = document.getElementById("status-sub");

function atualizarUI(conectado) {
  if (conectado) {
    indicator.className = "indicator conectado";
    statusLabel.className = "status-label conectado";
    statusLabel.textContent = "Conectada";
    statusSub.textContent = "Emily está controlando o navegador";
  } else {
    indicator.className = "indicator desconectado";
    statusLabel.className = "status-label desconectado";
    statusLabel.textContent = "Desconectada";
    statusSub.textContent = "Aguardando a Emily iniciar...";
  }
}

// Lê o estado inicial ao abrir o popup
chrome.storage.local.get(["emily_conectado"], (result) => {
  atualizarUI(result.emily_conectado === true);
});

// Observa mudanças em tempo real (quando o background conecta/desconecta)
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "emily_conectado" in changes) {
    atualizarUI(changes.emily_conectado.newValue === true);
  }
});
