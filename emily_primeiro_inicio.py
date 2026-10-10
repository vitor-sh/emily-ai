"""Configuração pública isolada, antes de importar clientes, voz ou main.

Não lê o .env pessoal nem devolve credenciais à interface.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit

PROVEDORES = {
    "openrouter": {"nome": "OpenRouter", "base": "https://openrouter.ai/api/v1",
                   "ajuda": "https://openrouter.ai/settings/keys"},
    "openai": {"nome": "OpenAI", "base": "https://api.openai.com/v1",
               "ajuda": "https://platform.openai.com/api-keys"},
    "ollama": {"nome": "Neste computador", "base": "http://127.0.0.1:11434/v1",
               "ajuda": "https://ollama.com/download"},
    "custom": {"nome": "Outro servidor", "base": "", "ajuda": ""},
}
SCHEMA = 1
VOZ_EMILY = "1d5c6866f45a44a3aa8df65061908ab2"
MODELO_VOZ = "s2.1-pro-free"

def normalizar_voz(valor):
    if not isinstance(valor, dict) or type(valor.get("ativa", False)) is not bool:
        raise ErroConfiguracao("Confira a configuração de voz.")
    if not valor.get("ativa", False):
        return {"ativa": False}
    chave = valor.get("chave", "")
    referencia = valor.get("id", VOZ_EMILY)
    if not isinstance(chave, str) or not chave.strip() or len(chave) > 4096 or any(ord(c) < 32 for c in chave):
        raise ErroConfiguracao("Cole sua chave Fish Audio para ativar a voz.")
    if not isinstance(referencia, str) or len(referencia) != 32 or any(c not in "0123456789abcdef" for c in referencia):
        raise ErroConfiguracao("O ID da voz precisa ter 32 caracteres hexadecimais.")
    return {"ativa": True, "chave": chave.strip(), "id": referencia, "modelo": MODELO_VOZ}

def normalizar_microfone(valor):
    if not isinstance(valor, dict) or type(valor.get("ativo", False)) is not bool:
        raise ErroConfiguracao("Confira a configuração do microfone.")
    if not valor.get("ativo", False):
        return {"ativo": False}
    chave = valor.get("chave", "")
    if not isinstance(chave, str) or not chave.strip() or len(chave) > 4096 or any(ord(c) < 32 for c in chave):
        raise ErroConfiguracao("Cole sua chave Groq para ativar o microfone.")
    return {"ativo": True, "chave": chave.strip()}


def normalizar_discord(valor):
    if not isinstance(valor, dict) or type(valor.get("ativo", False)) is not bool:
        raise ErroConfiguracao("Confira a configuração do Discord.")
    if not valor.get("ativo", False):
        return {"ativo": False}
    token = valor.get("token", "")
    canais = valor.get("canais", "")
    if not isinstance(token, str) or not token.strip() or len(token) > 4096 or any(ord(c) < 32 for c in token):
        raise ErroConfiguracao("Cole o token do seu bot, não o token da sua conta pessoal.")
    if isinstance(canais, str):
        canais = canais.replace(",", " ").split()
    if not isinstance(canais, list) or not 1 <= len(canais) <= 20 or any(not isinstance(c, str) or not c.isascii() or not c.isdigit() or not 10 <= len(c) <= 20 or not 0 < int(c) < 2**64 for c in canais):
        raise ErroConfiguracao("Cole entre 1 e 20 IDs de canais de texto, separados por espaço ou vírgula.")
    return {"ativo": True, "token": token.strip(), "canais": list(dict.fromkeys(canais))}


def _verificar_discord(cfg):
    import requests
    with requests.Session() as session:
        session.trust_env = False
        try:
            with session.get("https://discord.com/api/v10/users/@me", headers={"Authorization": "Bot " + cfg["token"]}, timeout=(4, 15), allow_redirects=False, stream=True) as resposta:
                if resposta.status_code != 200:
                    raise ErroConfiguracao("Discord recusou o token ou está indisponível. Confira o token do bot.")
                bruto = bytearray()
                for parte in resposta.iter_content(4096):
                    bruto.extend(parte)
                    if len(bruto) > 64000:
                        raise ErroConfiguracao("Resposta inesperada do Discord.")
                dados = json.loads(bruto)
                if not isinstance(dados, dict) or dados.get("bot") is not True:
                    raise ErroConfiguracao("Use somente um token de bot do Discord.")
        except (requests.RequestException, ValueError):
            raise ErroConfiguracao("Não consegui conferir o bot no Discord. Tente novamente.") from None


def _audio_fish(cfg):
    import requests
    with requests.Session() as session:
        session.trust_env = False
        try:
            with session.post("https://api.fish.audio/v1/tts",
                    headers={"Authorization": "Bearer " + cfg["chave"], "model": MODELO_VOZ},
                    json={"text": "Oi! Eu sou a Emily. Que bom ter você por aqui.", "reference_id": cfg["id"], "format": "mp3"},
                    timeout=(4, 25), allow_redirects=False, stream=True) as resposta:
                if resposta.status_code in (401, 403):
                    raise ErroConfiguracao("O Fish recusou o acesso. Confira sua chave e a disponibilidade desta voz na sua conta.")
                if resposta.status_code == 429:
                    raise ErroConfiguracao("O Fish está limitando solicitações. Aguarde e tente novamente.")
                if resposta.status_code != 200:
                    raise ErroConfiguracao("O Fish não conseguiu gerar a amostra. Tente mais tarde ou confira o ID da voz.")
                audio = bytearray(); inicio = time.monotonic()
                for parte in resposta.iter_content(16384):
                    audio.extend(parte)
                    if len(audio) > 2000000 or time.monotonic() - inicio > 35:
                        raise ErroConfiguracao("A amostra demorou demais ou excedeu o tamanho permitido.")
                if not (audio.startswith(b"ID3") or (len(audio) > 2 and audio[0] == 255 and audio[1] & 224 == 224)):
                    raise ErroConfiguracao("O Fish não retornou uma amostra MP3 válida.")
                return bytes(audio)
        except requests.RequestException:
            raise ErroConfiguracao("Não consegui conectar ao Fish. Confira sua internet e tente novamente.") from None

def _assinatura_voz(cfg):
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


class ErroConfiguracao(ValueError):
    pass


def pasta_perfil() -> Path:
    alternativa = os.getenv("EMILY_PUBLIC_HOME", "").strip()
    if alternativa:
        return Path(alternativa).expanduser().absolute()
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "EmilyPublica"
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "emily-publica"


def _url(valor: str) -> str:
    try:
        p = urlsplit(valor.strip())
        local = p.hostname in {"localhost", "127.0.0.1", "::1"}
        if (len(valor) > 2048 or p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or
                p.query or p.fragment or (p.scheme == "http" and not local) or
                any(c in valor for c in "\r\n\x00\\") or p.port == 0):
            raise ValueError()
    except ValueError:
        raise ErroConfiguracao("Use um endereço HTTPS. HTTP é permitido apenas neste computador.") from None
    caminho = p.path.rstrip("/")
    if not caminho.endswith("/v1"):
        caminho += "/v1"
    return urlunsplit((p.scheme, p.netloc, caminho, "", ""))


def normalizar(dados: dict) -> dict:
    if not isinstance(dados, dict):
        raise ErroConfiguracao("Confira os campos da configuração.")
    provedor = dados.get("provedor")
    if not isinstance(provedor, str) or provedor not in PROVEDORES:
        raise ErroConfiguracao("Escolha como conectar sua Emily.")
    campos = ("nome", "modelo", "chave", "base")
    if any(not isinstance(dados.get(campo, ""), str) for campo in campos):
        raise ErroConfiguracao("A configuração tem um campo inválido. Confira nome, chave e modelo.")
    nome = str(dados.get("nome", "")).strip()
    modelo = str(dados.get("modelo", "")).strip()
    chave = str(dados.get("chave", "")).strip()
    if not nome or len(nome) > 60 or any(ord(c) < 32 for c in nome):
        raise ErroConfiguracao("Como posso te chamar? Use um nome com até 60 caracteres.")
    if len(chave) > 4096 or any(c in chave for c in "\r\n\x00"):
        raise ErroConfiguracao("A chave parece incompleta ou contém uma quebra de linha. Cole novamente.")
    if len(modelo) > 180 or any(c in modelo for c in "\r\n\x00"):
        raise ErroConfiguracao("Confira o nome do modelo.")
    base = _url(PROVEDORES[provedor]["base"] if provedor != "custom" else str(dados.get("base", "")))
    if provedor == "ollama":
        chave = ""
    elif not chave:
        raise ErroConfiguracao("Cole a chave de acesso da sua conta para continuar.")
    cfg = {"schema": SCHEMA, "nome": nome, "provedor": provedor, "base": base,
            "modelo": modelo, "chave": chave}
    if "voz" in dados:
        cfg["voz"] = normalizar_voz(dados["voz"])
    if "microfone" in dados:
        cfg["microfone"] = normalizar_microfone(dados["microfone"])
    if "discord" in dados:
        cfg["discord"] = normalizar_discord(dados["discord"])
    return cfg


def carregar(perfil: Path) -> dict | None:
    arquivo = perfil / "configuracao.json"
    try:
        if arquivo.is_symlink() or arquivo.stat().st_size > 128000:
            return None
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or dados.get("schema") != SCHEMA or dados.get("concluido") is not True:
            return None
        cfg = normalizar(dados)
        return cfg if cfg["modelo"] else None
    except (OSError, ValueError, TypeError):
        return None


def _gravar(perfil: Path, nome: str, texto: str) -> None:
    if perfil.is_symlink() or (perfil / nome).is_symlink():
        raise ErroConfiguracao("Escolha uma pasta de perfil sem links simbólicos.")
    perfil.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(prefix=".config-", dir=perfil)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, perfil / nome)
    finally:
        Path(temporario).unlink(missing_ok=True)


def _assinatura(cfg: dict) -> str:
    valores = {k: cfg[k] for k in ("provedor", "base", "modelo", "chave")}
    return hashlib.sha256(json.dumps(valores, sort_keys=True).encode()).hexdigest()


def _request(cfg: dict, metodo: str, rota: str, corpo=None) -> dict:
    # O assistente envia credenciais só ao endereço escolhido. Redirects podem
    # apontar para outro host; não os seguimos. Limites de tempo/tamanho finitos.
    import requests
    headers = {"Accept": "application/json"}
    if cfg["chave"]:
        headers["Authorization"] = "Bearer " + cfg["chave"]
    try:
        with requests.Session() as sessao:
            sessao.trust_env = False
            with sessao.request(metodo, cfg["base"] + rota, json=corpo,
                                headers=headers, timeout=(4, 20), stream=True,
                                allow_redirects=False) as resposta:
                if resposta.status_code in {401, 403}:
                    raise ErroConfiguracao("A conta recusou a chave. Confira se ela está ativa e tem acesso ao modelo.")
                if resposta.status_code == 429:
                    raise ErroConfiguracao("A conta está sem saldo ou atingiu um limite. Confira o provedor e tente novamente.")
                if 300 <= resposta.status_code < 400:
                    raise ErroConfiguracao("Esse endereço redirecionou a conexão. Use o endereço final da API.")
                if resposta.status_code >= 400:
                    raise ErroConfiguracao("O provedor não aceitou o teste. Confira o modelo e o endereço da API.")
                partes, tamanho = [], 0
                inicio = time.monotonic()
                for parte in resposta.iter_content(65536):
                    tamanho += len(parte)
                    if tamanho > 4 * 1024 * 1024 or time.monotonic() - inicio > 25:
                        raise ErroConfiguracao("O provedor demorou ou enviou uma resposta grande demais. Tente novamente.")
                    partes.append(parte)
                retorno = json.loads(b"".join(partes))
                if not isinstance(retorno, dict):
                    raise ValueError()
                return retorno
    except requests.RequestException:
        raise ErroConfiguracao("Não consegui conectar. Confira sua internet ou se o servidor está ligado.") from None
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ErroConfiguracao):
            raise
        raise ErroConfiguracao("O endereço respondeu, mas não parece ser uma API compatível.") from None


class ApiPrimeiroInicio:
    def __init__(self, perfil: Path, request=_request, audio_fish=_audio_fish, verificar_discord=_verificar_discord):
        self._perfil = perfil
        self._request = request
        self._audio_fish = audio_fish
        self._voz_validada = None
        self._microfone_validado = None
        self._discord_validado = None
        self._verificar_discord = verificar_discord
        self._anterior = carregar(perfil)
        self._recibos = {}
        self._lock = threading.Lock()
        self._window = None
        self._concluido = False

    def estado(self):
        cfg = self._anterior or {}
        return {"provedores": PROVEDORES, "nome": cfg.get("nome", ""),
                "provedor": cfg.get("provedor", ""), "base": cfg.get("base", ""),
                "modelo": cfg.get("modelo", ""), "tem_chave": bool(cfg.get("chave")),
                "discord": {"ativo": cfg.get("discord", {}).get("ativo", False), "tem_token": bool(cfg.get("discord", {}).get("token")), "canais": cfg.get("discord", {}).get("canais", [])},
                "microfone": {"ativo": cfg.get("microfone", {}).get("ativo", False), "tem_chave": bool(cfg.get("microfone", {}).get("chave"))},
                "voz": {"ativa": cfg.get("voz", {}).get("ativa", False), "id": cfg.get("voz", {}).get("id", VOZ_EMILY), "tem_chave": bool(cfg.get("voz", {}).get("chave"))},
                "refazer": (self._perfil / "configuracao.json").exists() and not self._anterior}

    def _config(self, dados):
        if not isinstance(dados, dict):
            raise ErroConfiguracao("Confira os campos da configuração.")
        dados = dict(dados)
        # Uma chave salva pode ser mantida sem devolvê-la ao JavaScript. Nunca
        # reaproveitar a credencial para outro provedor/endereço.
        if not dados.get("chave") and dados.get("manter_chave") and self._anterior:
            anterior = self._anterior
            base = PROVEDORES.get(dados.get("provedor"), {}).get("base") or dados.get("base", "")
            if isinstance(base, str) and dados.get("provedor") == anterior["provedor"] and _url(base) == anterior["base"]:
                dados["chave"] = anterior["chave"]
        if isinstance(dados.get("voz"), dict):
            voz = dict(dados["voz"])
            if not voz.get("chave") and voz.get("manter_chave") and self._anterior:
                voz["chave"] = self._anterior.get("voz", {}).get("chave", "")
            dados["voz"] = voz
        if isinstance(dados.get("microfone"), dict):
            microfone = dict(dados["microfone"])
            if not microfone.get("chave") and microfone.get("manter_chave") and self._anterior:
                microfone["chave"] = self._anterior.get("microfone", {}).get("chave", "")
            dados["microfone"] = microfone
        if isinstance(dados.get("discord"), dict):
            discord = dict(dados["discord"])
            if not discord.get("token") and discord.get("manter_token") and self._anterior:
                discord["token"] = self._anterior.get("discord", {}).get("token", "")
            dados["discord"] = discord
        return normalizar(dados)

    def modelos(self, dados):
        try:
            cfg = self._config(dados)
            resposta = self._request(cfg, "GET", "/models")
            itens = resposta.get("data")
            if not isinstance(itens, list):
                raise ErroConfiguracao("Não consegui ler a lista de modelos. Você pode digitar o nome manualmente.")
            modelos = sorted({m["id"] for m in itens if isinstance(m, dict) and
                              isinstance(m.get("id"), str) and 0 < len(m["id"]) <= 180 and
                              not any(c in m["id"] for c in "\r\n\x00")})
            if not modelos:
                raise ErroConfiguracao("Nenhum modelo disponível. No Ollama, instale um modelo antes de tentar novamente.")
            return {"ok": True, "modelos": modelos[:2000]}
        except ErroConfiguracao as e:
            return {"ok": False, "mensagem": str(e)}

    def testar(self, dados):
        try:
            cfg = self._config(dados)
            if not cfg["modelo"]:
                raise ErroConfiguracao("Escolha ou digite um modelo para testar.")
            limite = "max_completion_tokens" if cfg["provedor"] == "openai" else "max_tokens"
            resposta = self._request(cfg, "POST", "/chat/completions", {
                "model": cfg["modelo"], "messages": [{"role": "user", "content": "Responda apenas: oi"}],
                limite: 32, "stream": False,
            })
            escolhas = resposta.get("choices")
            if not isinstance(escolhas, list) or not escolhas or not isinstance(escolhas[0], dict) or not isinstance(escolhas[0].get("message"), dict):
                raise ErroConfiguracao("O teste não retornou uma resposta de conversa. Confira o modelo escolhido.")
            # Não devolver texto livre do serviço (pode incluir dados/credenciais).
            recibo = secrets.token_hex(24)
            with self._lock:
                self._recibos = {recibo: (_assinatura(cfg), time.monotonic())}
            return {"ok": True, "recibo": recibo, "mensagem": "Conexão pronta. Sua Emily já pode conversar."}
        except ErroConfiguracao as e:
            return {"ok": False, "mensagem": str(e)}

    def testar_discord(self, dados):
        try:
            cfg = self._config(dados).get("discord", {"ativo": False})
            if not cfg["ativo"]:
                raise ErroConfiguracao("Ative o Discord antes de testar o bot.")
            self._verificar_discord(cfg)
            with self._lock:
                self._discord_validado = (_assinatura_voz(cfg), time.monotonic())
            return {"ok": True, "mensagem": "Token de bot aceito. Confira o convite e as permissões dos canais no Discord ao abrir a Emily."}
        except ErroConfiguracao as e:
            return {"ok": False, "mensagem": str(e)}

    def testar_microfone(self, dados):
        try:
            cfg = self._config(dados).get("microfone", {"ativo": False})
            if not cfg["ativo"]:
                raise ErroConfiguracao("Ative o microfone para testar sua chave Groq.")
            resposta = self._request({"base": "https://api.groq.com/openai/v1", "chave": cfg["chave"]}, "GET", "/models")
            if not isinstance(resposta.get("data"), list) or not any(isinstance(m, dict) and m.get("id") == "whisper-large-v3-turbo" for m in resposta["data"]):
                raise ErroConfiguracao("O modelo Whisper não está disponível nesta conta Groq.")
            with self._lock:
                self._microfone_validado = (_assinatura_voz(cfg), time.monotonic())
            return {"ok": True, "mensagem": "Chave aceita e Whisper disponível. Nenhum áudio foi gravado neste teste."}
        except ErroConfiguracao as e:
            return {"ok": False, "mensagem": str(e)}

    def testar_voz(self, dados):
        import base64
        try:
            cfg = self._config(dados).get("voz", {"ativa": False})
            if not cfg["ativa"]:
                raise ErroConfiguracao("Ative a voz para ouvir a amostra.")
            audio = self._audio_fish(cfg)
            with self._lock:
                self._voz_validada = (_assinatura_voz(cfg), time.monotonic())
            return {"ok": True, "audio": base64.b64encode(audio).decode("ascii")}
        except ErroConfiguracao as e:
            return {"ok": False, "mensagem": str(e)}

    def concluir(self, dados, recibo, consentimento=False):
        try:
            cfg = self._config(dados)
            with self._lock:
                validado = self._recibos.get(str(recibo))
                if not validado or validado[0] != _assinatura(cfg) or time.monotonic() - validado[1] > 600:
                    raise ErroConfiguracao("Teste a conexão novamente antes de salvar.")
                discord = cfg.get("discord", {"ativo": False})
                if discord["ativo"] and (not self._discord_validado or self._discord_validado[0] != _assinatura_voz(discord) or time.monotonic() - self._discord_validado[1] > 600):
                    raise ErroConfiguracao("Confira seu bot Discord novamente antes de salvar.")
                microfone = cfg.get("microfone", {"ativo": False})
                if microfone["ativo"] and (not self._microfone_validado or self._microfone_validado[0] != _assinatura_voz(microfone) or time.monotonic() - self._microfone_validado[1] > 600):
                    raise ErroConfiguracao("Teste sua chave Groq novamente antes de salvar.")
                voz = cfg.get("voz", {"ativa": False})
                if voz["ativa"] and (not self._voz_validada or self._voz_validada[0] != _assinatura_voz(voz) or time.monotonic() - self._voz_validada[1] > 600):
                    raise ErroConfiguracao("Ouça a amostra da voz novamente antes de salvar.")
                if consentimento is not True:
                    raise ErroConfiguracao("Confirme que entendeu como a conexão funciona.")
                _gravar(self._perfil, "configuracao.json", json.dumps({**cfg, "concluido": True}, ensure_ascii=False, indent=2))
                self._anterior = cfg
                self._concluido = True
            return {"ok": True}
        except (ErroConfiguracao, OSError) as e:
            mensagem = str(e) if isinstance(e, ErroConfiguracao) else "Não consegui salvar neste perfil. Confira as permissões da pasta."
            return {"ok": False, "mensagem": mensagem}

    def ajuda(self, provedor):
        url = {"fish": "https://fish.audio/app/api-keys", "groq": "https://console.groq.com/keys", "discord": "https://discord.com/developers/applications"}.get(str(provedor)) or PROVEDORES.get(str(provedor), {}).get("ajuda")
        if url:
            import webbrowser
            webbrowser.open(url)
        return bool(url)

    def abrir(self):
        if self._concluido and self._window:
            self._window.destroy()
            return True
        return False


def configurar(perfil: Path) -> bool:
    import sys
    import webview
    api = ApiPrimeiroInicio(perfil)
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    api._window = webview.create_window("Emily · Vamos começar", str(raiz / "web" / "primeiro-inicio.html"),
                                       js_api=api, width=1080, height=760, min_size=(520, 620),
                                       background_color="#111210", text_select=True)
    webview.start(private_mode=True)
    return api._concluido


def aplicar(perfil: Path, cfg: dict) -> None:
    """Configura só o processo público. Nada é salvo no projeto pessoal."""
    cfg = normalizar(cfg)
    if not cfg["modelo"]:
        raise ErroConfiguracao("Escolha um modelo antes de abrir a Emily.")
    env = ("# >>> provedor: publico\n"
           f"EMILY_PROVEDOR_PUBLICO_BASE={cfg['base']}\n"
           "EMILY_PROVEDOR_PUBLICO_CHAVE=EMILY_PUBLIC_LLM_KEY\n"
           f"EMILY_PROVEDOR_PUBLICO_MODELO={cfg['modelo']}\n"
           f"EMILY_PROVEDOR_PUBLICO_MODELOS={cfg['modelo']}\n"
           f"EMILY_PROVEDOR_PUBLICO_TIPO={'ollama' if cfg['provedor'] == 'ollama' else 'openai'}\n"
           f"EMILY_PROVEDOR_PUBLICO_SEM_CHAVE={int(cfg['provedor'] == 'ollama')}\n"
           "# <<< provedor: publico\n")
    _gravar(perfil, "provedor.env", env)
    pasta_dados = perfil / "dados"
    pasta_dados.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "EMILY_PUBLIC_MODE": "1", "EMILY_PUBLIC_CONFIG": str(perfil / "configuracao.json"), "PYTHON_DOTENV_DISABLED": "1",
        "EMILY_CONFIG_FILE": str(perfil / "provedor.env"),
        "EMILY_DATA_DIR": str(pasta_dados), "EMILY_USUARIO": cfg["nome"],
        "EMILY_PUBLIC_LLM_KEY": cfg["chave"] or "ollama",
        "EMILY_PROVEDOR_LLM": "publico", "EMILY_MEMORIA_UNIFICADA": "0",
        "EMILY_MEMORIA_PASTA": str(pasta_dados / "memoria_unificada"),
        "EMILY_OLLAMA_URL": "http://127.0.0.1:11434",
        "EMILY_ARQUIVO_PREFERENCIAS": str(pasta_dados / "preferencias.json"),
        "EMILY_ARQUIVO_CONVERSAS": str(pasta_dados / "conversas.json"),
        "EMILY_ARQUIVO_DISCORD": str(pasta_dados / "discord.json"),
        "EMILY_LOG_PATH": str(pasta_dados / "emily.log"), "EMILY_SPRITE": "0",
        "EMILY_UI": "web", "EMILY_PONTE_TOKEN": "", "EMILY_GATEWAY_URL": "",
        "GROQ_API_KEY": cfg.get("microfone", {}).get("chave", ""),
        "EMILY_PUBLIC_MICROFONE": "1" if cfg.get("microfone", {}).get("ativo") else "0",
        "FISH_AUDIO_KEY": cfg.get("voz", {}).get("chave", ""),
        "FISH_VOICE_ID": cfg.get("voz", {}).get("id", VOZ_EMILY),
        "EMILY_FISH_BACKEND": MODELO_VOZ,
        "EMILY_FISH_BASE_URL": "https://api.fish.audio",
    })
