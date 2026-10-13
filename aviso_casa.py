"""
aviso_casa.py — avisa o Vitor quando a agenda da casa faz (ou não consegue fazer) algo.

Quem avisa é a Oracle, que dispara o agendamento. O caminho do aviso:

1. PC em uso (ele usou a Emily nos últimos minutos) e livre para falar: a Emily
   do PC fala. A Oracle pede pela rota interna /internal/casa/aviso.
2. Senão (PC desligado, sem uso recente, mudo, ocupado): push FCM para o celular.
   O app recebe o dado `casa_aviso`, mostra a notificação e fala o aviso.

Nunca os dois: quem estava em uso já ouviu. A credencial do Firebase e o token do
celular ficam em ~/.config/emily-runtime-cloud/casa/ (0600, fora do git).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import requests

import casa_inteligente as casa

PROJECT_ID = "emily-assistente"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ARQ_CREDENCIAL = "firebase-service-account.json"
ARQ_TOKEN = "android-push-token.json"
# "Uso recente" do PC = ele falou ou escreveu para a Emily nesta janela.
JANELA_PC_S = float(os.getenv("EMILY_AVISO_PC_JANELA_S", "600"))


def pc_pode_falar(*, ultimo_uso: float, agora: float, ocupada: bool, falando: bool,
                  escutando: bool, mudo: bool, escrito: bool,
                  janela: Optional[float] = None) -> Tuple[bool, str]:
    """Decisão pura (testável) usada pela Emily do PC: pode falar o aviso agora?"""
    janela = JANELA_PC_S if janela is None else janela
    if not ultimo_uso or agora - ultimo_uso > janela:
        return False, "o PC não está em uso recente"
    if mudo:
        return False, "a voz do PC está muda"
    if escrito:
        return False, "o PC está em modo escrito"
    if ocupada or falando or escutando:
        return False, "a Emily do PC está ocupada"
    return True, ""


# ─── Token do celular ─────────────────────────────────────────────

def salvar_token(token: str) -> None:
    if not isinstance(token, str) or not 20 <= len(token) <= 4096 or any(c.isspace() for c in token):
        raise casa.CasaErro("token FCM inválido")
    caminho = casa.pasta() / ARQ_TOKEN
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=caminho.parent, prefix=".push-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            json.dump({"token": token}, arquivo)
        os.chmod(temp, 0o600)
        os.replace(temp, caminho)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def ler_token() -> str:
    try:
        return json.loads((casa.pasta() / ARQ_TOKEN).read_text(encoding="utf-8"))["token"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""


# ─── Canais ───────────────────────────────────────────────────────

def avisar_pc(texto: str) -> Tuple[bool, str]:
    """Pede à Emily do PC para falar. (falou, motivo). Qualquer falha = não falou."""
    try:
        cfg = json.loads(Path(os.environ["EMILY_RELAY_CONFIG"]).read_text())
        r = requests.post(
            cfg["pc_url"].rstrip("/") + "/internal/casa/aviso",
            headers={"Authorization": "Bearer " + cfg["pc_token"], "X-Emily-Cloud-Key": cfg["upload_key"]},
            json={"texto": texto}, timeout=(2, 28))
        if r.status_code != 200:
            return False, f"PC respondeu HTTP {r.status_code}"
        dados = r.json()
        return bool(dados.get("falou")), str(dados.get("motivo") or "")
    except Exception as e:  # noqa: BLE001 - PC fora do ar é o caso comum
        return False, f"PC indisponível ({type(e).__name__})"


def enviar_push(titulo: str, texto: str, sessao=None) -> dict:
    """FCM só com dados: o app mostra a notificação E fala (mensagem com 'notification' não fala)."""
    token = ler_token()
    if not token:
        raise casa.CasaErro("o celular ainda não registrou o token de aviso na Oracle")
    credencial = casa.pasta() / ARQ_CREDENCIAL
    if not credencial.is_file():
        raise casa.CasaErro("falta a credencial do Firebase na Oracle")
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    credenciais = service_account.Credentials.from_service_account_file(str(credencial), scopes=[FCM_SCOPE])
    if credenciais.project_id != PROJECT_ID:
        raise casa.CasaErro("credencial Firebase pertence a outro projeto")
    credenciais.refresh(Request())
    resposta = (sessao or requests).post(
        f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send",
        headers={"Authorization": f"Bearer {credenciais.token}"},
        json={"message": {"token": token,
                          "data": {"type": "casa_aviso", "titulo": titulo[:100], "texto": texto[:600]},
                          "android": {"priority": "HIGH"}}},
        timeout=15)
    resposta.raise_for_status()
    return resposta.json()


def avisar(texto: str, titulo: str = "Emily", *,
           pc: Callable[[str], Tuple[bool, str]] = avisar_pc,
           push: Callable[[str, str], dict] = enviar_push) -> dict:
    """PC em uso fala; senão o celular recebe voz + notificação. Nunca levanta."""
    texto = (texto or "").strip()
    if not texto:
        return {"canal": "nenhum", "detalhe": "sem texto"}
    falou, motivo_pc = pc(texto)
    if falou:
        print(f"[AVISO-CASA] falado no PC: {texto[:80]}", flush=True)
        return {"canal": "pc", "detalhe": ""}
    try:
        push(titulo, texto)
        print(f"[AVISO-CASA] enviado ao celular ({motivo_pc}): {texto[:80]}", flush=True)
        return {"canal": "celular", "detalhe": motivo_pc}
    except Exception as e:  # noqa: BLE001 - o agendamento já foi feito; aviso é extra
        print(f"[AVISO-CASA] sem canal para avisar ({motivo_pc}; push: {e})", flush=True)
        return {"canal": "nenhum", "detalhe": f"{motivo_pc}; push: {e}"}
