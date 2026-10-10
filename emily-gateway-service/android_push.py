"""Canal FCM privado do gateway: registro de um celular e envio de avisos.

Credenciais de serviço ficam exclusivamente no PC, nunca no APK. O chamador
das rotas é autenticado pelo gateway com EMILY_PONTE_TOKEN.
"""

import json
import os
import tempfile
from pathlib import Path

import requests

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
PROJECT_ID = "emily-assistente"
if os.name == "nt":
    TOKEN_FILE = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Emily" / "android-push-token.json"
else:
    TOKEN_FILE = Path.home() / ".local/share/emily/android-push-token.json"


def salvar_token(token: str, caminho: Path = TOKEN_FILE) -> None:
    if not isinstance(token, str) or not 20 <= len(token) <= 4096 or any(c.isspace() for c in token):
        raise ValueError("token FCM inválido")
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


def ler_token(caminho: Path = TOKEN_FILE) -> str:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))["token"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def enviar(titulo: str, texto: str, *, caminho: Path = TOKEN_FILE,
           credentials_file: str = "", session=None) -> dict:
    return _enviar_mensagem({"notification": {"title": titulo, "body": texto},
                            "android": {"priority": "HIGH",
                                        "notification": {"channel_id": "emily_geral"}}},
                           caminho=caminho, credentials_file=credentials_file, session=session)


def enviar_dados(dados: dict[str, str], *, caminho: Path = TOKEN_FILE,
                 credentials_file: str = "", session=None) -> dict:
    """Entrega uma troca de endpoint mesmo com o app em segundo plano."""
    if not dados or any(not isinstance(k, str) or not isinstance(v, str)
                        for k, v in dados.items()):
        raise ValueError("dados FCM inválidos")
    return _enviar_mensagem({"data": dados, "android": {"priority": "HIGH"}},
                           caminho=caminho, credentials_file=credentials_file, session=session)


def _enviar_mensagem(mensagem: dict, *, caminho: Path, credentials_file: str,
                    session=None) -> dict:
    token = ler_token(caminho)
    if not token:
        raise RuntimeError("celular ainda não registrou o token FCM no gateway")
    if not credentials_file:
        raise RuntimeError("configure EMILY_FIREBASE_SERVICE_ACCOUNT no .env do gateway")
    # Import tardio: o gateway continua disponível quando push não está configurado.
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    credentials = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=[FCM_SCOPE])
    if credentials.project_id != PROJECT_ID:
        raise RuntimeError("credencial Firebase pertence a outro projeto")
    credentials.refresh(Request())
    resposta = (session or requests).post(
        f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send",
        headers={"Authorization": f"Bearer {credentials.token}"},
        json={"message": {"token": token, **mensagem}},
        timeout=15,
    )
    resposta.raise_for_status()
    return resposta.json()
