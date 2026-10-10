"""
emily_code.py — O "Emily Code": assistente de código da Emily.

Uma camada fina que dá à Emily superpoderes de edição de código no PC do
Vitor: ler/escrever/editar/apagar arquivos do projeto, buscar texto, listar
pastas, executar comandos. Com um sistema de PERMISSÕES: leitura é livre,
escrita/execução pedem confirmação (e pode "permitir sempre").

Design do fluxo:
- O Vitor escolhe uma PASTA DE PROJETO (uma vez, nas configurações).
- As ferramentas entram na mesa via abrir_ferramentas("code").
- Operações de escrita/execução passam por requer_permissao(), que devolve
  "sim"/"sempre"/"não" — a confirmação acontece num modal bonito no JS.
- code_perguntar() manda uma pergunta pro JS (janela com opções) e espera.

A pasta de projeto é salva em preferencias["emily_code_projeto"].
Permissões "sempre" ficam em preferencias["emily_code_permissoes"].
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

# ─────────────────────────────────────────────────────────────────
# PASTA DE PROJETO
# ─────────────────────────────────────────────────────────────────

def projeto_raiz() -> Optional[Path]:
    """Pasta de projeto da conversa ativa, ou a PADRÃO (global) como fallback.

    Cada conversa pode ter a própria pasta (definir_projeto grava nela). Mas a
    conversa NASCE sem pasta própria ("projeto": "") e pode carregar um caminho
    que morreu — a migração Windows -> Linux deixou pra trás todo caminho tipo
    "C:/..." . Nesses dois casos a pasta PADRÃO que o Vitor definiu é a resposta
    certa: era exatamente pra isso que ele a definiu. Antes, o None daqui
    sombreava a global, e a Emily dizia "nenhum projeto definido" com a pasta
    certa salva e aparecendo no terminal.
    """
    try:
        import modo_demo
        raiz_demo = modo_demo.workspace()
        if modo_demo.ativo():
            return raiz_demo
    except Exception:
        pass
    c = _conversa_atual_dict()
    if c is not None and "projeto" in c:
        p = str(c.get("projeto") or "").strip()
        if p:
            caminho = Path(p).expanduser()
            if caminho.is_dir():
                return caminho
            print(f"[EMILY-CODE] a pasta da conversa não existe mais "
                  f"({p}); usando a pasta padrão.")
        # Vazia (conversa nova) ou morta: cai na pasta padrão abaixo.
    import preferencias
    p = preferencias.obter("emily_code_projeto") or ""
    p = str(p).strip()
    if not p:
        return None
    caminho = Path(p).expanduser()
    return caminho if caminho.is_dir() else None


def definir_projeto(caminho: str) -> str:
    """Define a pasta de projeto. Devolve mensagem de confirmação ou erro."""
    try:
        import modo_demo
        if modo_demo.ativo():
            raiz = modo_demo.workspace()
            return f"Pasta de projeto definida: {raiz}" if raiz else "Workspace demo indisponível."
    except Exception:
        pass
    import preferencias
    caminho = (caminho or "").strip().strip('"').strip("'")
    if not caminho:
        return "Me diz o caminho da pasta de projeto, Vitor!"
    p = Path(caminho).expanduser()
    if not p.exists():
        return f"Não achei a pasta '{caminho}'."
    if not p.is_dir():
        return f"'{caminho}' não é uma pasta."
    preferencias.definir(emily_code_projeto=str(p))
    # Registra na conversa ativa também, pra cada conversa lembrar a sua pasta.
    c = _conversa_atual_dict()
    if c:
        _atualizar_conversa(c["id"], projeto=str(p))
    return f"Pasta de projeto definida: {p}"


# ─────────────────────────────────────────────────────────────────
# PERMISSÕES
# ─────────────────────────────────────────────────────────────────

# Respostas possíveis pra uma permissão. A confirmação acontece no JS.
PERMISSAO_SIM = "sim"
PERMISSAO_SEMPRE = "sempre"
PERMISSAO_NAO = "nao"


def _regras_sempre() -> List[str]:
    """Regras "permitir sempre" vigentes: globais + as da conversa ativa."""
    try:
        import modo_demo
        if modo_demo.ativo():
            return []
    except Exception:
        pass
    import preferencias
    globais = list(preferencias.obter("emily_code_permissoes", {}).get("sempre", []) or [])
    c = _conversa_atual_dict()
    locais = list((c or {}).get("permissoes", {}).get("sempre", []) or [])
    # Junta sem duplicar; ordem não importa (é um conjunto de regras).
    return list(dict.fromkeys(globais + locais))


def _regra_id(acao: str, caminho: Optional[Path]) -> str:
    """Identificador de uma regra de permissão, pra comparar com 'sempre'."""
    base = f"{acao}"
    if caminho:
        base += f":{os.path.normcase(str(caminho))}"
    return base


def _caminho_no_projeto(caminho: Path) -> bool:
    """True se o caminho está dentro da pasta de projeto."""
    raiz = projeto_raiz()
    if not raiz:
        return True  # sem projeto definido, não bloqueia por estar fora
    try:
        return caminho.resolve().is_relative_to(raiz.resolve())
    except Exception:
        return True


def requer_permissao(acao: str, caminho: Optional[Path] = None) -> bool:
    r"""
    Uma escrita/execução pede confirmação? Retorna False se já tem
    "permitir sempre" pra essa ação+caminho, ou se é leitura.

    A regra SEM caminho (ex: "escrever") cobre TODOS os caminhos.
    A regra COM caminho (ex: "escrever:C:\proj\src") cobre só aquele — e
    qualquer caminho DENTRO dele (regra de pasta cobre a subárvore). É o
    que permite o Emily Code multi-modelo auto-aprovar a pasta de projeto
    inteira: "escrever:C:\proj" cobre "escrever:C:\proj\src\main.py".
    """
    try:
        import modo_demo
        if modo_demo.ativo():
            return False
    except Exception:
        pass
    if acao in ("ler", "listar", "buscar", "estrutura", "projeto"):
        return False
    sempre = _regras_sempre()
    # Regra sem caminho (cobre tudo)
    if _regra_id(acao, None) in sempre:
        return False
    # Regra com caminho específico: bate exato ou o caminho pedido está
    # DENTRO da pasta da regra (ancestral).
    if caminho:
        try:
            alvo = caminho.resolve()
        except Exception:
            alvo = caminho
        for regra in sempre:
            acao_regra, sep, caminho_regra = regra.partition(":")
            if acao_regra != acao or not sep or not caminho_regra:
                continue
            try:
                raiz_regra = Path(caminho_regra).resolve()
            except Exception:
                continue
            if alvo == raiz_regra or alvo.is_relative_to(raiz_regra):
                return False
    return True


def registrar_permissao_sempre(acao: str, caminho: Optional[Path] = None) -> None:
    """Guarda "permitir sempre" pra uma ação+caminho (global e na conversa ativa)."""
    try:
        import modo_demo
        if modo_demo.ativo():
            return
    except Exception:
        pass
    import preferencias
    regra = _regra_id(acao, caminho)
    # Global (comportamento antigo, vale pra qualquer conversa).
    dados = preferencias.obter("emily_code_permissoes", {}) or {}
    sempre = list(dados.get("sempre", []) or [])
    if regra not in sempre:
        sempre.append(regra)
    dados["sempre"] = sempre
    preferencias.definir(emily_code_permissoes=dados)
    # Local (conversa ativa) — cada conversa lembra as suas regras.
    c = _conversa_atual_dict()
    if c:
        locais = list((c.get("permissoes", {}) or {}).get("sempre", []) or [])
        if regra not in locais:
            locais.append(regra)
        _atualizar_conversa(c["id"], permissoes={"sempre": locais})


def _pedir_permissao(tipo: str, acao: str, caminho: Optional[Path],
                     preview: str = "") -> str:
    """
    Abre o modal de permissão no JS e espera a resposta (sim/sempre/nao).
    Usa a ponte do interface_web, mesma do code_perguntar.
    preview — texto extra (diff/conteúdo) que o JS mostra antes de decidir.
    """
    try:
        import interface_web
        return interface_web._perguntar_permissao(tipo, acao, caminho, preview)
    except Exception as e:
        print(f"[EMILY-CODE] erro ao pedir permissão: {e}")
        return PERMISSAO_NAO


# ── Preview pra confirmação (Fase 1.2) ─────────────────────────────
# O modal de permissão mostra o que VAI mudar (diff/conteúdo) antes de
# clicar "sim" — não só o nome do arquivo.

def _diff_unificado(caminho: Path, antes: str, depois: str,
                    rotulo: Optional[str] = None) -> str:
    """Diff unificado (formato git) entre dois conteúdos."""
    rotulo = rotulo or str(caminho)
    diff = list(difflib.unified_diff(
        antes.splitlines(keepends=True),
        depois.splitlines(keepends=True),
        fromfile=f"a/{rotulo}", tofile=f"b/{rotulo}",
        lineterm="",
    ))
    return "".join(diff) if diff else "(sem alterações)"


def _preview_escrever(caminho: Path, novo_conteudo: str) -> str:
    """Diff do que vai mudar ao criar/atualizar um arquivo."""
    if caminho.exists() and caminho.is_file():
        try:
            atual = caminho.read_text(encoding="utf-8", errors="replace")
        except Exception:
            atual = ""
        return f"Diff de {caminho.name}:\n" + _diff_unificado(
            caminho, atual, novo_conteudo or "", rotulo=caminho.name)
    return f"(arquivo novo) {caminho.name} — {len(novo_conteudo or '')} caracteres"


def _preview_apagar(caminho: Path) -> str:
    """Primeiras linhas + tamanho antes de confirmar apagar."""
    if caminho.is_dir():
        try:
            qtd = sum(1 for _ in caminho.rglob("*"))
        except Exception:
            qtd = -1
        return f"(pasta) {caminho.name}/ — {qtd} itens dentro"
    try:
        conteudo = caminho.read_text(encoding="utf-8", errors="replace")
    except Exception:
        conteudo = ""
    linhas = conteudo.splitlines()
    cabeca = "\n".join(linhas[:15])
    try:
        tamanho = _formatar_tamanho(caminho.stat().st_size)
    except OSError:
        tamanho = "? B"
    resumo = f"{caminho.name} — {len(linhas)} linhas, {tamanho}\n"
    return resumo + (f"Primeiras linhas:\n{cabeca}" if cabeca else "(vazio)")


def _gerar_preview(acao: str, caminho: Optional[Path], campos: dict) -> str:
    """Texto de preview pro modal, conforme a ação: diff ou conteúdo."""
    if caminho is None:
        return ""
    try:
        if acao == "escrever_arquivo":
            preview = _preview_escrever(caminho, campos.get("conteudo", ""))
            return _anexar_aviso_sintaxe(caminho.name, "", campos.get("conteudo", ""), preview)
        if acao == "editar_arquivo":
            buscar = campos.get("buscar", "")
            substituir = campos.get("substituir", "")
            if not buscar or not caminho.is_file():
                return f"Edição em {caminho.name}"
            try:
                atual = caminho.read_text(encoding="utf-8", errors="replace")
            except Exception:
                atual = ""
            novo = atual.replace(buscar, substituir) if buscar else atual
            preview = f"Diff de {caminho.name}:\n" + _diff_unificado(
                caminho.name, atual, novo)
            return _anexar_aviso_sintaxe(caminho.name, atual, novo, preview)
        if acao == "editar_linhas":
            ini = int(campos.get("linha_inicio", 1))
            fim = int(campos.get("linha_fim", ini))
            novo_c = campos.get("novo_conteudo", "")
            if not caminho.is_file():
                return f"Edição em {caminho.name}"
            try:
                linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                linhas = []
            total = len(linhas)
            ini = max(1, ini)
            fim = min(total, fim)
            atual = "".join(linhas)
            novo = "".join(linhas[:ini - 1]) + (novo_c or "") + "".join(linhas[fim:])
            preview = f"Diff de {caminho.name} (linhas {ini}-{fim}):\n" + _diff_unificado(
                caminho.name, atual, novo)
            return _anexar_aviso_sintaxe(caminho.name, atual, novo, preview)
        if acao == "apagar_arquivo":
            return _preview_apagar(caminho)
        if acao == "editar_transacao":
            # Preview dos VÁRIOS arquivos da transação (um diff por arquivo).
            blocos = []
            for ed in (campos.get("edicoes") or []):
                if not isinstance(ed, dict):
                    continue
                arq = str(ed.get("arquivo", ""))
                p = _resolver(arq)
                if p is None:
                    blocos.append(f"{arq}: (fora do projeto)")
                    continue
                if "conteudo" in ed:
                    blocos.append(_preview_escrever(p, ed.get("conteudo", "")))
                else:
                    try:
                        linhas = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                    except Exception:
                        linhas = []
                    ini = max(1, int(ed.get("linha_inicio", 1)))
                    fim = min(len(linhas), int(ed.get("linha_fim", ini)))
                    atual = "".join(linhas)
                    novo = "".join(linhas[:ini - 1]) + (ed.get("novo_conteudo", "") or "") + "".join(linhas[fim:])
                    blocos.append(_diff_unificado(arq, atual, novo))
            if not blocos:
                return "(transação sem arquivos)"
            return "TRANSAÇÃO — vários arquivos (tudo-ou-nada):\n\n" + "\n\n".join(blocos)
    except Exception as e:
        return f"(não consegui gerar preview: {e})"
    return ""


def _anexar_aviso_sintaxe(nome: str, antes: str, depois: str, preview: str) -> str:
    """Anexa aviso de erro de sintaxe novo (se houver) ao preview."""
    try:
        erro = _tem_erro_sintaxe(antes, depois, nome)
        if erro:
            return preview + f"\n\n⚠ AVISO DE SINTAXE: {erro}"
    except Exception:
        pass
    return preview


# ── Checagem de sintaxe (Fase 3.1) ─────────────────────────────────
# Antes de escrever/editar, verifica se o conteúdo resultante é
# sintaticamente válido (Python, JS, JSON). Avisa no preview, não
# substitui o pedido de permissão — o Vitor vê o aviso e decide.

_EXT_SINTAXE = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def _checar_sintaxe(nome: str, conteudo: str) -> Optional[str]:
    """Checa sintaxe do conteúdo. Devolve erro ou None se ok."""
    if not conteudo:
        return None
    ext = Path(nome).suffix.lower()
    tipo = _EXT_SINTAXE.get(ext)
    if tipo is None:
        return None
    try:
        if tipo == "python":
            compile(conteudo, nome, "exec")
        elif tipo == "javascript":
            # node --check: precisa de arquivo real. Cria temp.
            import tempfile
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".js", mode="w",
                                                 delete=False, encoding="utf-8") as f:
                    tmp_path = f.name
                    f.write(conteudo)
                    f.flush()
                res = subprocess.run(
                    ["node", "--check", tmp_path],
                    capture_output=True, text=True, timeout=15,
                    encoding="utf-8", errors="replace",
                )
                if res.returncode != 0:
                    return (res.stderr or res.stdout or "").strip()[:500]
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
        elif tipo == "json":
            json.loads(conteudo)
        elif tipo == "yaml":
            # Tenta importar yaml; se não estiver instalado, passa sem erro.
            try:
                import yaml as _yaml
                _yaml.safe_load(conteudo)
            except ImportError:
                return None  # pyyaml não instalado: não atrapalha
            except Exception as e:
                return f"YAML inválido: {e}"
    except SyntaxError as e:
        return f"Erro de sintaxe: {e}"
    except json.JSONDecodeError as e:
        return f"JSON inválido: {e}"
    except FileNotFoundError:
        return None  # node não instalado: não atrapalha
    except Exception as e:
        return f"Erro ao checar sintaxe: {e}"
    return None


def _tem_erro_sintaxe(conteudo_antes: str, conteudo_depois: str,
                       nome: str) -> Optional[str]:
    """
    Compara o antes e depois: se o 'antes' já tinha erro, não reclama.
    Só avisa se o 'depois' introduziu erro novo.
    """
    erro_antes = _checar_sintaxe(nome, conteudo_antes)
    erro_depois = _checar_sintaxe(nome, conteudo_depois)
    if erro_depois and not erro_antes:
        return erro_depois
    return None
# Antes de qualquer escrita/edição/apagada, guarda o estado atual do arquivo
# num backup fora da pasta de projeto (pra não poluir o git do Vitor).
# desfazer_ultima_mudanca() restaura o backup mais recente daquele arquivo.

# Quantos dias um backup sobrevive (depois disso é limpo na próxima escrita).
_BACKUP_DIAS_MAX = 7
# Quantos backups por arquivo guardar no máximo (apaga os mais antigos).
_BACKUP_MAX_POR_ARQUIVO = 10


def _pasta_backups() -> Path:
    """Pasta de backups fora da pasta de projeto (global do usuário)."""
    try:
        import modo_demo
        raiz = modo_demo.workspace()
        if modo_demo.ativo() and raiz:
            p = raiz / ".backups"
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    # Prefere a pasta do usuário (mesma do .emily_code_conversas), sempre fora
    # do projeto pra não aparecer no git do Vitor.
    p = Path.home() / ".emily_code_backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _nome_backup(pasta: Path, relativo: str) -> Path:
    """Caminho de um backup específico de um arquivo relativo."""
    # Sanitiza o relativo: substitui separadores e caracteres estranhos.
    nome = re.sub(r"[^\w.\-]", "_", relativo or "arquivo")
    return pasta / f"{nome}.bak"


def _fazer_backup(relativo: str, caminho: Path) -> None:
    """Copia o estado atual do arquivo pra pasta de backups (se existir)."""
    if not caminho or not caminho.is_file():
        return
    try:
        pasta = _pasta_backups()
        backup = _nome_backup(pasta, relativo)
        backup.parent.mkdir(parents=True, exist_ok=True)
        # Timestamp + conteúdo original: backup numerado pra permitir várias
        # versões de um mesmo arquivo.
        ts = time.strftime("%Y%m%d-%H%M%S")
        versao = pasta / f"{backup.name}.{ts}"
        import shutil
        shutil.copy2(caminho, versao)
        # Guarda também o mais recente "sempre" (nome fixo) pra desfazer rápido.
        shutil.copy2(caminho, backup)
        _limpar_backups_antigos(pasta, relativo, backup)
    except Exception as e:
        print(f"[EMILY-CODE] não consegui fazer backup: {e}")


def _limpar_backups_antigos(pasta: Path, relativo: str, backup_fixo: Path) -> None:
    """Remove backups antigos (mais de X dias) e além do limite por arquivo."""
    try:
        agora = time.time()
        prefixo = backup_fixo.name
        versoes = []
        for f in pasta.glob(f"{prefixo}.*"):
            if f.is_file():
                if agora - f.stat().st_mtime > _BACKUP_DIAS_MAX * 86400:
                    f.unlink()
                else:
                    versoes.append(f)
        # Mantém no máximo _BACKUP_MAX_POR_ARQUIVO versões (mais a fixa).
        versoes.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for f in versoes[_BACKUP_MAX_POR_ARQUIVO:]:
            f.unlink()
    except Exception:
        pass


def _restaurar_backup(relativo: str, caminho: Path) -> str:
    """Restaura o backup mais recente do arquivo. Devolve mensagem."""
    try:
        pasta = _pasta_backups()
        backup_fixo = _nome_backup(pasta, relativo)
        if backup_fixo.is_file():
            import shutil
            shutil.copy2(backup_fixo, caminho)
            return f"Restaurei o backup mais recente de '{relativo}'."
        # Sem backup fixo, procura a versão mais recente.
        versoes = sorted(pasta.glob(f"{backup_fixo.name}.*"),
                         key=lambda f: f.stat().st_mtime, reverse=True)
        if versoes:
            import shutil
            shutil.copy2(versoes[0], caminho)
            return f"Restaurei a versão mais recente de '{relativo}'."
        return f"Não tenho backup de '{relativo}'."
    except Exception as e:
        return f"Não consegui restaurar: {e}"


def desfazer_ultima_mudanca(relativo: str) -> str:
    """
    Restaura o backup mais recente de um arquivo (Fase 1.3).

    Se o arquivo ainda existe, restaura o conteúdo; se foi apagado, recria.
    Pedir permissão: é uma ESCRITA no arquivo, então passa pelo mesmo fluxo.
    """
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    caminho = _resolver(relativo)
    if caminho is None:
        return "Arquivo fora do projeto."
    pasta = _pasta_backups()
    backup_fixo = _nome_backup(pasta, relativo)
    if not backup_fixo.is_file():
        versoes = list(pasta.glob(f"{backup_fixo.name}.*"))
        if not versoes:
            return f"Não tenho backup de '{relativo}'."
    # Restaura de fato (com permissão, já que escreve no arquivo).
    return _restaurar_backup(relativo, caminho)


# ─────────────────────────────────────────────────────────────────
# HELPERS DE ARQUIVO
# ─────────────────────────────────────────────────────────────────

def _corrigir_caixa(p: Path, raiz: Optional[Path]) -> Path:
    """
    Linux diferencia maiúsculas; o Windows não. Um caminho que veio do
    Windows (do Vitor ou de um modelo) pode chegar com a caixa errada.
    Se o caminho exato não existe mas existe UMA única variante de caixa,
    usa ela. Zero ou ambíguo → devolve o original (criar arquivo novo é um
    caso legítimo, e adivinhar entre dois nomes seria pior).
    """
    if raiz is None or p.exists():
        return p
    try:
        relativo = p.relative_to(raiz)
    except ValueError:
        return p
    atual = raiz
    for parte in relativo.parts:
        if (atual / parte).exists():
            atual = atual / parte
            continue
        try:
            candidatas = [c for c in atual.iterdir()
                          if c.name.lower() == parte.lower()]
        except OSError:
            return p
        if len(candidatas) != 1:
            return p
        atual = candidatas[0]
    return atual


def _resolver(relativo: str) -> Optional[Path]:
    """Resolve um caminho relativo dentro do projeto. None se fora."""
    raiz = projeto_raiz()
    rel = (relativo or "").strip().strip("/").strip("\\")
    # Backslash é separador de Windows. No Linux, Path trata "src\utils.js"
    # como UM nome de arquivo com barra invertida — e não acha nada.
    rel = rel.replace("\\", "/")
    if not rel:
        return raiz or None
    p = (raiz / rel) if raiz else Path(rel).expanduser()
    if raiz and not p.resolve().is_relative_to(raiz.resolve()):
        return None
    return _corrigir_caixa(p, raiz) if raiz else p


def _ignorar(nome: str) -> bool:
    """Pastas/arquivos que a Emily não deve mexer (git, node_modules, etc.)."""
    ignorados = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".env", "dist", "build", ".next", "target", ".idea", ".vscode",
    }
    return nome in ignorados


# Nomes SENSÍVEIS mesmo fora de pasta ignorada: config/credencial. O _ignorar
# já cobre os diretórios; estes padrões pegam arquivos de credencial soltos
# (na raiz do projeto ou dentro de pastas normais).
_PADROES_SENSIVEIS = (
    re.compile(r"^\.env(\..*)?$", re.IGNORECASE),     # .env, .env.local, .env.antes
    re.compile(r".*\.(key|pem|p12|pfx)$", re.IGNORECASE),  # chaves privadas
    re.compile(r"^credentials?.*$", re.IGNORECASE),
    re.compile(r"^credenciai[ls].*$", re.IGNORECASE),
    re.compile(r"^secrets?.*$", re.IGNORECASE),
    re.compile(r"^\.?(npmrc|pypirc|netrc|git-credentials|htpasswd)$", re.IGNORECASE),
)


def _nome_sensivel(nome: str) -> bool:
    """True se o NOME (arquivo/pasta) cai na lista de bloqueio de leitura."""
    if _ignorar(nome):
        return True
    return any(rx.match(nome) for rx in _PADROES_SENSIVEIS)


def _eh_sensivel(caminho: Path) -> bool:
    """True se o caminho OU alguma pasta ancestral é sensível (ex: dentro de .git/)."""
    try:
        partes = list(caminho.resolve().parts)
    except Exception:
        partes = list(caminho.parts)
    return any(_nome_sensivel(p) for p in partes)


_MENSAGEM_SENSIVEL = (
    "Não posso ler esse arquivo: é sensível (config/credencial) e a leitura "
    "dele é bloqueada por segurança. Se precisar, o Vitor mexe nele direto."
)


def _formatar_tamanho(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


# ─────────────────────────────────────────────────────────────────
# FERRAMENTAS DE ARQUIVO
# ─────────────────────────────────────────────────────────────────

def ler_arquivo(relativo: str, linha_inicio: Optional[int] = None,
                linha_fim: Optional[int] = None) -> str:
    """Lê um arquivo do projeto, com leitura parcial opcional por linhas."""
    p = _resolver(relativo)
    if p is None or not p.is_file():
        return f"Não achei o arquivo '{relativo}' no projeto."
    if _eh_sensivel(p):
        return _MENSAGEM_SENSIVEL
    try:
        conteudo = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Não consegui ler o arquivo: {e}"
    linhas = conteudo.splitlines()
    total = len(linhas)
    # Faixa pedida: recorta linhas. Linha é 1-indexada; fora do intervalo
    # acha o primeiro/last índice válido, em vez de estourar.
    if linha_inicio is not None or linha_fim is not None:
        ini = max(1, int(linha_inicio or 1))
        fim = min(total, int(linha_fim or total))
        if ini > total:
            return f"`{relativo}` tem {total} linhas; não dá pra ler a partir da {ini}."
        trecho = "\n".join(linhas[ini - 1:fim])
        return (f"`{relativo}` linhas {ini}-{fim} de {total} "
                f"({_formatar_tamanho(p.stat().st_size)}):\n\n{trecho}")
    # Arquivo grande sem faixa: devolve resumo, não o arquivo inteiro.
    if total > 500:
        cabeca = "\n".join(linhas[:50])
        rabo = "\n".join(linhas[-20:])
        return (
            f"`{relativo}` tem {total} linhas ({_formatar_tamanho(p.stat().st_size)}) "
            f"— grande demais pra ler inteiro.\n\n"
            f"Primeiras linhas (1-50):\n{cabeca}\n\n"
            f"Últimas linhas ({total-19}-{total}):\n{rabo}\n\n"
            f"Pra ler um trecho, usa ler_arquivo com linha_inicio/linha_fim."
        )
    return f"`{relativo}` ({total} linhas, {_formatar_tamanho(p.stat().st_size)}):\n\n{conteudo}"


def listar_arquivos(relativo: str = "") -> str:
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda. Define uma nas configurações."
    alvo = _resolver(relativo) or raiz
    if not alvo.is_dir():
        return f"'{relativo or '.'}' não é uma pasta no projeto."
    try:
        itens = sorted(alvo.iterdir(), key=lambda i: (not i.is_dir(), i.name.lower()))
    except Exception as e:
        return f"Não consegui listar: {e}"
    if not itens:
        return f"A pasta '{relativo or '.'}' está vazia."
    linhas = [f"Conteúdo de '{relativo or '.'}':"]
    for item in itens:
        if _ignorar(item.name):
            continue
        marcador = "📁" if item.is_dir() else "📄"
        detalhe = "" if item.is_dir() else f"  ({_formatar_tamanho(item.stat().st_size)})"
        linhas.append(f"{marcador} {item.name}{detalhe}")
    return "\n".join(linhas)


def ver_estrutura(profundidade: int = 3) -> str:
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    profundidade = max(1, min(int(profundidade or 3), 6))
    linhas: List[str] = [f"Estrutura do projeto ({raiz.name}):"]

    def _andar(p: Path, nivel: int):
        if nivel > profundidade:
            return
        try:
            itens = sorted(p.iterdir(), key=lambda i: (not i.is_dir(), i.name.lower()))
        except Exception:
            return
        for item in itens:
            if _ignorar(item.name):
                continue
            prefixo = "  " * nivel
            if item.is_dir():
                linhas.append(f"{prefixo}📁 {item.name}/")
                _andar(item, nivel + 1)
            else:
                linhas.append(f"{prefixo}📄 {item.name}")

    _andar(raiz, 0)
    return "\n".join(linhas) if len(linhas) > 1 else "Projeto vazio."


def escrever_arquivo(relativo: str, conteudo: str) -> str:
    p = _resolver(relativo)
    if p is None:
        return "Arquivo fora do projeto."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(conteudo or "", encoding="utf-8")
    except Exception as e:
        return f"Não consegui escrever: {e}"
    return f"Arquivo '{relativo}' criado/atualizado."


def editar_arquivo(relativo: str, buscar: str, substituir: str, ocorrencia: int = 0) -> str:
    """Substitui um trecho específico (busca → substituir) no arquivo."""
    p = _resolver(relativo)
    if p is None or not p.is_file():
        return f"Não achei o arquivo '{relativo}' no projeto."
    try:
        conteudo = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Não consegui ler: {e}"
    if not buscar:
        return "Me diz o trecho que quer substituir."
    ocorrencia = max(0, int(ocorrencia or 0))
    partes = conteudo.split(buscar)
    if len(partes) < 2:
        return f"Não achei o trecho '{buscar[:40]}' no arquivo."
    if ocorrencia >= len(partes) - 1:
        ocorrencia = len(partes) - 2
    novo = buscar.join(partes[:ocorrencia + 1]) + substituir + buscar.join(partes[ocorrencia + 1:])
    try:
        p.write_text(novo, encoding="utf-8")
    except Exception as e:
        return f"Não consegui salvar: {e}"
    return f"Editei '{relativo}' (substituí '{buscar[:30]}...')."


# ── Edição robusta (Fase 2.2) ──────────────────────────────────────
# Substitui o editar_arquivo frágil (split textual) por edição por
# número de linha, múltipla com rollback tudo-ou-nada.

def _editar_linhas_inplace(relativo: str, linha_inicio: int,
                           linha_fim: Optional[int],
                           novo_conteudo: str) -> tuple[str, Optional[str]]:
    """
    Edita um trecho do arquivo DELIMITADO POR LINHAS.
    Troca da linha_inicio à linha_fim (inclusive) pelo novo_conteudo.
    linha_fim=None significa até o final do arquivo.
    Devolve (mensagem, conteudo_anterior_ou_none_se_erro).
    """
    p = _resolver(relativo)
    if p is None or not p.is_file():
        return f"Não achei '{relativo}'.", None
    try:
        conteudo = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Não consegui ler '{relativo}': {e}", None
    linhas = conteudo.splitlines(keepends=True)
    total = len(linhas)
    ini = max(1, int(linha_inicio or 1))
    fim = min(total, int(linha_fim if linha_fim is not None else total))
    if ini > total:
        return f"Arquivo tem {total} linhas; não dá começar na {ini}.", None
    if ini > fim:
        return f"linha_inicio ({ini}) maior que linha_fim ({fim}).", None
    anterior = "".join(linhas)
    # Monta com a substituição.
    novo = "".join(linhas[:ini - 1]) + (novo_conteudo or "") + "".join(linhas[fim:])
    p.write_text(novo, encoding="utf-8")
    return (f"Editei '{relativo}' (linhas {ini}-{fim}).", anterior)


def editar_linhas(relativo: str, linha_inicio: int, linha_fim: Optional[int],
                  novo_conteudo: str) -> str:
    """Edita um trecho de arquivo por número de linha (mais confiável que buscar/substituir).
    linha_fim=None edita até o final do arquivo."""
    msg, _ = _editar_linhas_inplace(relativo, linha_inicio, linha_fim, novo_conteudo)
    return msg


def editar_multi(relativo: str, edicoes: list) -> str:
    """
    Múltiplas edições no mesmo arquivo, aplicadas em ordem. TUDO-OU-NADA:
    se qualquer edição falhar, reverte TODAS as anteriores da mesma leva.
    Cada edição é dict: {"linha_inicio": N, "linha_fim": M, "novo_conteudo": "..."}

    IMPORTANTE: os índices de linha referem-se ao arquivo ORIGINAL. As edições
    são reordenadas do fim para o começo automaticamente, para que inserções/
    remoções anteriores no arquivo não desloquem os índices das edições seguintes.
    """
    p = _resolver(relativo)
    if p is None or not p.is_file():
        return f"Não achei '{relativo}'."
    try:
        conteudo_original = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Não consegui ler '{relativo}': {e}"
    linhas = conteudo_original.splitlines(keepends=True)
    total_original = len(linhas)

    # Valida o formato de todas as edições ANTES de aplicar qualquer uma.
    for i, ed in enumerate(edicoes or []):
        # Guarda de formato: sem as chaves explícitas, os defaults abaixo
        # (linha 1 → última linha, conteúdo vazio) substituiriam o arquivo
        # INTEIRO por nada — e a ferramenta ainda diria "deu certo". Um
        # modelo que mande {buscar, substituir} aqui apagaria o arquivo.
        if (not isinstance(ed, dict) or "linha_inicio" not in ed
                or "novo_conteudo" not in ed):
            return (f"Erro na edição {i + 1}: faltam 'linha_inicio' e/ou "
                    f"'novo_conteudo'. O formato é {{'linha_inicio': N, "
                    f"'linha_fim': M, 'novo_conteudo': '...'}}. "
                    f"NENHUMA edição foi aplicada.")
        ini = max(1, int(ed.get("linha_inicio", 1)))
        fim = int(ed.get("linha_fim", ini))
        if ini > total_original:
            return (f"Erro na edição {i + 1}: arquivo tem {total_original} linhas, "
                    f"não dá começar na {ini}. NENHUMA edição foi aplicada.")
        if ini > fim:
            return (f"Erro na edição {i + 1}: linha_inicio ({ini}) > linha_fim ({fim}). "
                    f"NENHUMA edição foi aplicada.")

    # Aplica do fim para o começo: assim os índices originais dos registros
    # acima do ponto de edição permanecem válidos para as próximas edições.
    edicoes_ordenadas = sorted(
        enumerate(edicoes or []),
        key=lambda x: -int(x[1].get("linha_inicio", 1))
    )
    linhas_mutaveis = list(linhas)
    for _, ed in edicoes_ordenadas:
        ini = max(1, int(ed.get("linha_inicio", 1)))
        fim = min(len(linhas_mutaveis), int(ed.get("linha_fim", ini)))
        novo = ed.get("novo_conteudo", "")
        linhas_mutaveis = linhas_mutaveis[:ini - 1] + [novo] + linhas_mutaveis[fim:]

    # Todas ok: salva
    p.write_text("".join(linhas_mutaveis), encoding="utf-8")
    return f"Editei '{relativo}' ({len(edicoes)} alterações, tudo ou nada)."


def apagar_arquivo(relativo: str) -> str:
    p = _resolver(relativo)
    if p is None:
        return "Arquivo fora do projeto."
    if not p.exists():
        return f"Não achei '{relativo}' pra apagar."
    try:
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
        else:
            p.unlink()
    except Exception as e:
        return f"Não consegui apagar: {e}"
    return f"Apaguei '{relativo}'."


def renomear_arquivo(relativo: str, novo_nome: str) -> str:
    p = _resolver(relativo)
    if p is None or not p.exists():
        return f"Não achei '{relativo}'."
    # Valida que o novo nome não tenta escapar via separadores ou '..'
    if any(c in novo_nome for c in ("/", "\\")) or ".." in novo_nome:
        return "Nome inválido: não pode conter separadores de caminho ou '..'."
    novo = p.with_name(novo_nome)
    try:
        p.rename(novo)
    except Exception as e:
        return f"Não consegui renomear: {e}"
    return f"Renomeei '{relativo}' pra '{novo_nome}'."


def mover_arquivo(relativo: str, destino_relativo: str) -> str:
    p = _resolver(relativo)
    if p is None or not p.exists():
        return f"Não achei '{relativo}'."
    destino = _resolver(destino_relativo)
    if destino is None:
        return "Destino fora do projeto."
    # Faz backup antes de mover (pra desfazer ser possível)
    if p.is_file():
        _fazer_backup(relativo, p)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        p.rename(destino)
    except Exception as e:
        return f"Não consegui mover: {e}"
    return f"Movi '{relativo}' pra '{destino_relativo}'."


# ─────────────────────────────────────────────────────────────────
# FERRAMENTAS DE BUSCA
# ─────────────────────────────────────────────────────────────────

def buscar_texto(padrao: str, em: str = "") -> str:
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    alvo = _resolver(em) or raiz
    if not alvo.is_dir():
        return f"'{em or '.'}' não é uma pasta."
    try:
        regex = re.compile(padrao, re.IGNORECASE)
    except re.error as e:
        return f"Padrão de busca inválido: {e}"
    resultados: List[str] = []
    limite = 60
    for raiz_dir, dirs, arquivos in os.walk(alvo):
        dirs[:] = [d for d in dirs if not _ignorar(d)]
        for arq in arquivos:
            if _nome_sensivel(arq):
                continue
            caminho = Path(raiz_dir) / arq
            try:
                # Symlink quebrado (comum no Linux) ou arquivo que sumiu
                # durante a varredura não pode derrubar a busca inteira.
                if caminho.stat().st_size > 1024 * 1024:
                    continue
            except OSError:
                continue
            try:
                texto = caminho.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            linhas = texto.splitlines()
            for i, linha in enumerate(linhas, 1):
                if not regex.search(linha):
                    continue
                rel = caminho.relative_to(raiz)
                # Contexto ao redor: 2 linhas antes e 2 depois da ocorrência.
                ini = max(1, i - 2)
                fim = min(len(linhas), i + 2)
                ctx = " | ".join(
                    f"{n}:{linhas[n - 1].strip()[:80]}" for n in range(ini, fim + 1)
                )
                resultados.append(f"{rel}:{i}: {linha.strip()[:100]}\n    [{ctx}]")
                if len(resultados) >= limite:
                    break
            if len(resultados) >= limite:
                break
        if len(resultados) >= limite:
            break
    if not resultados:
        return f"Não achei '{padrao}' no projeto."
    return f"Resultados pra '{padrao}' ({len(resultados)}):\n" + "\n\n".join(resultados)


def achar_arquivo(nome: str) -> str:
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    alvo = (nome or "").strip().lower()
    achados: List[str] = []
    for raiz_dir, dirs, arquivos in os.walk(raiz):
        dirs[:] = [d for d in dirs if not _nome_sensivel(d)]
        for arq in arquivos:
            # Pode listar o NOME do arquivo sensível, mas não expõe conteúdo depois.
            if alvo in arq.lower():
                achados.append(str(Path(raiz_dir) / arq))
    if not achados:
        return f"Não achei nenhum arquivo com '{nome}'."
    return "Arquivos encontrados:\n" + "\n".join(achados[:40])


# ─────────────────────────────────────────────────────────────────
# FERRAMENTAS DE EXECUÇÃO
# ─────────────────────────────────────────────────────────────────

def executar_comando(comando: str) -> str:
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    try:
        resultado = subprocess.run(
            comando, shell=True, cwd=str(raiz),
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return "O comando demorou demais e deu timeout."
    except Exception as e:
        return f"Erro ao executar: {e}"
    saida = (resultado.stdout or "").strip()
    erro = (resultado.stderr or "").strip()
    if saida and erro:
        return f"Saída:\n{saida}\n\nErro:\n{erro}"
    if saida:
        return saida[:4000]
    if erro:
        return f"(comando falhou) {erro[:2000]}"
    return f"Comando executou (código {resultado.returncode}), sem saída."


def executar_script(relativo: str, args: str = "") -> str:
    p = _resolver(relativo)
    if p is None or not p.is_file():
        return f"Não achei o script '{relativo}' no projeto."
    if p.suffix.lower() in (".py", ".pyw"):
        comando = f'python "{p}" {args}'
    elif p.suffix.lower() in (".js", ".mjs", ".cjs"):
        comando = f'node "{p}" {args}'
    elif p.suffix.lower() == ".sh":
        comando = f'bash "{p}" {args}'
    else:
        comando = f'"{p}" {args}'
    return executar_comando(comando)


# ── Transação de múltiplos arquivos (Fase 3.3) ─────────────────────
# Uma operação que edita/escreve VÁRIOS arquivos com TUDO-OU-NADA: se
# qualquer um falhar, reverte todos os outros da mesma transação.
# Reusa o sistema de backup da Fase 1.3 (já salva antes de cada escrita).


def editar_transacao(edicoes: list) -> str:
    """
    Aplica múltiplas edições em ARQUIVOS DIFERENTES como uma transação.
    Cada edição é dict: {"arquivo": "src/x.py", "conteudo": "..."} ou
    {"arquivo": "src/x.py", "linha_inicio": N, "linha_fim": M, "novo_conteudo": "..."}.

    Se QUALQUER edição falhar, reverte TODAS as anteriores (backups da Fase 1.3).
    """
    if not edicoes:
        return "Nenhuma edição fornecida."
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."

    arquivos_editados: List[str] = []  # relativos que já foram alterados

    def _reverter_tudo() -> None:
        for r in reversed(arquivos_editados):
            p = _resolver(r)
            if p:
                _restaurar_backup(r, p)

    for i, ed in enumerate(edicoes or []):
        relativo = (ed.get("arquivo") or "").strip()
        if not relativo:
            _reverter_tudo()
            return (f"Erro na edição {i + 1}: 'arquivo' não informado. "
                    f"TODAS as edições foram revertidas.")

        p = _resolver(relativo)
        if p is None:
            _reverter_tudo()
            return f"Erro na edição {i + 1}: '{relativo}' está fora do projeto. Transação revertida."

        # Guarda de formato: edição sem 'conteudo' E sem o par
        # 'linha_inicio'+'novo_conteudo' cairia na edição por linha com
        # defaults vazios e truncaria o arquivo. Melhor recusar a transação.
        if not isinstance(ed, dict) or (
                "conteudo" not in ed
                and not ("linha_inicio" in ed and "novo_conteudo" in ed)):
            _reverter_tudo()
            return (f"Erro na edição {i + 1}: '{relativo}' sem 'conteudo' nem "
                    f"'linha_inicio'+'novo_conteudo'. Transação revertida.")

        # Backup antes de qualquer alteração (só na primeira vez que toca no arquivo)
        if relativo not in arquivos_editados:
            if p.is_file():
                _fazer_backup(relativo, p)

        try:
            if "conteudo" in ed:
                # Escrita completa (como escrever_arquivo)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(ed["conteudo"] or "", encoding="utf-8")
            else:
                # Edição por linha (como editar_linhas)
                if not p.is_file():
                    _reverter_tudo()
                    return (f"Erro na edição {i + 1}: '{relativo}' não existe. "
                            f"Transação revertida.")
                ini = max(1, int(ed.get("linha_inicio", 1)))
                fim = int(ed.get("linha_fim", ini))
                novo_c = ed.get("novo_conteudo", "")
                linhas = p.read_text(encoding="utf-8").splitlines(keepends=True)
                total = len(linhas)
                ini = max(1, ini)
                fim = min(total, fim)
                if ini > total:
                    _reverter_tudo()
                    return (f"Erro na edição {i + 1}: '{relativo}' tem {total} linhas, "
                            f"não dá começar na {ini}. Transação revertida.")
                novo = "".join(linhas[:ini - 1]) + (novo_c or "") + "".join(linhas[fim:])
                p.write_text(novo, encoding="utf-8")
        except Exception as e:
            _reverter_tudo()
            return f"Erro na edição {i + 1}: {e}. Transação revertida."

        if relativo not in arquivos_editados:
            arquivos_editados.append(relativo)

    return (f"Transação concluída: {len(edicoes)} alterações em "
            f"{len(arquivos_editados)} arquivo(s).")


# ── Execução em segundo plano (Fase 2.5) ───────────────────────────
# Processos que rodam sem travar o Emily Code: inicia, consulta a saída
# acumulada, encerra. Útil pra "sobe um servidor de teste e continua".

_processos_fundo: dict = {}   # id -> dict com Popen, saída, thread
_lock_processos = threading.Lock()


def executar_comando_fundo(comando: str) -> str:
    """Inicia um comando em segundo plano e devolve o id do processo."""
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    # Limpa processos já finalizados antes de criar um novo (evita acúmulo).
    _limpar_processos_mortos()
    try:
        proc = subprocess.Popen(
            comando, shell=True, cwd=str(raiz),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace",
        )
    except Exception as e:
        return f"Erro ao iniciar em segundo plano: {e}"
    pid = uuid.uuid4().hex[:8]
    entrada = {
        "proc": proc, "pid_sistema": proc.pid,
        "saida": [], "terminou": False, "codigo": None,
    }
    def _leitor():
        try:
            for linha in proc.stdout:
                entrada["saida"].append(linha)
                if len(entrada["saida"]) > 500:
                    entrada["saida"] = entrada["saida"][-500:]
        except Exception:
            pass
        entrada["terminou"] = True
        entrada["codigo"] = proc.poll()
    t = threading.Thread(target=_leitor, daemon=True)
    entrada["thread"] = t
    with _lock_processos:
        _processos_fundo[pid] = entrada
    t.start()
    return (f"Processo iniciado em segundo plano (id {pid}, pid {proc.pid}). "
            f"Pra ver a saída usa ver_saida_processo('{pid}'); pra encerrar, "
            f"encerrar_processo('{pid}').")


def ver_saida_processo(id_processo: str) -> str:
    """Consulta a saída acumulada de um processo em segundo plano."""
    id_processo = (id_processo or "").strip()
    with _lock_processos:
        entrada = _processos_fundo.get(id_processo)
    if entrada is None:
        return f"Não achei processo com id '{id_processo}'."
    saida = "".join(entrada["saida"]).strip()
    estado = "terminou" if entrada["terminou"] else "rodando"
    cod = entrada["codigo"]
    base = f"Processo {id_processo} ({estado})"
    if cod is not None:
        base += f", código {cod}"
    if not saida:
        return f"{base}, sem saída até agora."
    return f"{base}:\n{saida[-3000:]}"


def encerrar_processo(id_processo: str) -> str:
    """Encerra (mata) um processo em segundo plano."""
    id_processo = (id_processo or "").strip()
    with _lock_processos:
        entrada = _processos_fundo.get(id_processo)
    if entrada is None:
        return f"Não achei processo com id '{id_processo}'."
    proc = entrada["proc"]
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception as e:
            return f"Não consegui encerrar: {e}"
    entrada["terminou"] = True
    entrada["codigo"] = proc.poll()
    # Remove o processo do dicionário pra não acumular memória.
    with _lock_processos:
        _processos_fundo.pop(id_processo, None)
    return f"Processo {id_processo} encerrado."


def _limpar_processos_mortos() -> None:
    """Remove processos já finalizados do dicionário (evita memory leak)."""
    with _lock_processos:
        mortos = [pid for pid, e in _processos_fundo.items() if e.get("terminou")]
        for pid in mortos:
            _processos_fundo.pop(pid, None)


# ── Workspace de teste isolado (Fase 2.6) ──────────────────────────
# Uma área de rascunho FORA do projeto real, onde a Emily pode copiar
# arquivos e testar/rodar sem risco de estragar o projeto do Vitor.
# Escrever/lê na workspace é livre (não é o projeto real); rodar comando
# lá ainda pede permissão de execução (é comando), mas o cwd é a workspace.

def _workspace() -> Path:
    """Pasta de rascunho do Emily Code, fora do projeto (global do usuário)."""
    try:
        import modo_demo
        raiz = modo_demo.workspace()
        if modo_demo.ativo() and raiz:
            p = raiz / ".workspace"
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    p = Path.home() / ".emily_code_workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _workspace_resolver(nome: str) -> Optional[Path]:
    """Resolve um nome dentro da workspace. None se tentar escapar."""
    base = _workspace().resolve()
    alvo = (base / (nome or "")).resolve()
    if not alvo.is_relative_to(base):
        return None
    return alvo


def workspace_copiar(relativo: str, para: str = "") -> str:
    """Copia um arquivo do projeto pra workspace, pra testar sem risco."""
    p = _resolver(relativo)
    if p is None or not p.is_file():
        return f"Não achei '{relativo}' no projeto."
    destino = _workspace_resolver(para or p.name)
    if destino is None:
        return "Nome de destino inválido (fora da workspace)."
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(p, destino)
    except Exception as e:
        return f"Não consegui copiar: {e}"
    return f"Copiei '{relativo}' pra workspace (teste à vontade, não mexe no projeto)."


def workspace_escrever(nome: str, conteudo: str) -> str:
    """Escreve um arquivo de rascunho na workspace."""
    destino = _workspace_resolver(nome)
    if destino is None:
        return "Nome de arquivo inválido (fora da workspace)."
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo or "", encoding="utf-8")
    except Exception as e:
        return f"Não consegui escrever na workspace: {e}"
    return f"Escrevi '{nome}' na workspace."


def workspace_ler(nome: str) -> str:
    """Lê um arquivo da workspace."""
    destino = _workspace_resolver(nome)
    if destino is None or not destino.is_file():
        return f"Não achei '{nome}' na workspace."
    try:
        conteudo = destino.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Não consegui ler da workspace: {e}"
    linhas = conteudo.splitlines()
    return f"`{nome}` (workspace, {len(linhas)} linhas):\n\n{conteudo}"


def workspace_listar() -> str:
    """Lista os arquivos da workspace."""
    base = _workspace()
    itens = sorted(base.iterdir()) if base.is_dir() else []
    if not itens:
        return "A workspace está vazia."
    return "Workspace (fora do projeto, pode apagar à vontade):\n" + \
        "\n".join(f"📄 {i.name}" for i in itens if i.is_file())


def workspace_rodar(comando: str) -> str:
    """Roda um comando COM o cwd na workspace (isola do projeto real)."""
    base = _workspace()
    try:
        resultado = subprocess.run(
            comando, shell=True, cwd=str(base),
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return "O comando demorou demais e deu timeout."
    except Exception as e:
        return f"Erro ao executar: {e}"
    saida = (resultado.stdout or "").strip()
    erro = (resultado.stderr or "").strip()
    if saida and erro:
        return f"Saída:\n{saida}\n\nErro:\n{erro}"
    if saida:
        return saida[:4000]
    if erro:
        return f"(comando falhou) {erro[:2000]}"
    return f"Comando executou (código {resultado.returncode}), sem saída."


def workspace_limpar() -> str:
    """Apaga os arquivos da workspace (só rascunho, não toca o projeto)."""
    base = _workspace()
    try:
        import shutil
        for item in base.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    except Exception as e:
        return f"Não consegui limpar a workspace: {e}"
    return "Workspace limpa."


# ── Gerenciamento de dependências (Fase 3.2) ───────────────────────
# listar_dependencias lê requirements.txt/package.json; instalar_pacote
# roda o gerenciador (pip/npm) na pasta de projeto (pede permissão de execução).

def listar_dependencias() -> str:
    """Lê e mostra as dependências declaradas no projeto."""
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    linhas: List[str] = []
    # requirements.txt / requirements-dev.txt
    for req in sorted(raiz.glob("requirements*.txt")):
        try:
            conteudo = req.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        deps = [l.strip() for l in conteudo.splitlines()
                if l.strip() and not l.strip().startswith("#")]
        if deps:
            linhas.append(f"{req.name} ({len(deps)}):")
            linhas.extend(f"  - {d}" for d in deps[:40])
    # package.json
    pkg = raiz / "package.json"
    if pkg.is_file():
        try:
            dados = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            dados = {}
        deps = list((dados.get("dependencies") or {}).items())
        dev = list((dados.get("devDependencies") or {}).items())
        if deps:
            linhas.append(f"package.json dependencies ({len(deps)}):")
            linhas.extend(f"  - {n}@{v}" for n, v in deps[:40])
        if dev:
            linhas.append(f"package.json devDependencies ({len(dev)}):")
            linhas.extend(f"  - {n}@{v}" for n, v in dev[:40])
    if not linhas:
        return "Não achei requirements.txt nem package.json no projeto."
    return "\n".join(linhas)


def instalar_pacote(gerenciador: str, nome: str) -> str:
    """
    Instala um pacote com o gerenciador pedido (pip/npm) na pasta de projeto.
    Pede permissão de execução.
    """
    ger = (gerenciador or "").strip().lower()
    pacote = (nome or "").strip()
    if ger not in ("pip", "npm"):
        return "Me diz o gerenciador: 'pip' ou 'npm'."
    if not pacote:
        return "Me diz qual pacote instalar."
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    if ger == "pip":
        comando = f'python -m pip install "{pacote}"'
    else:
        comando = f'npm install "{pacote}"'
    return executar_comando(comando)


# ─────────────────────────────────────────────────────────────────
# CONTEXTO
# ─────────────────────────────────────────────────────────────────

def ver_projeto() -> str:
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida. Define uma nas configurações."
    return f"Pasta de projeto: {raiz}\n\n" + listar_arquivos("")


# ─────────────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL DE EXECUÇÃO (chamada pelas ferramentas)
# ─────────────────────────────────────────────────────────────────

# Onde as ações pedem permissão:
_ACAO_PEDE_PERMISSAO = {
    "escrever_arquivo": "escrever",
    "editar_arquivo": "escrever",
    "editar_linhas": "escrever",
    "editar_multi": "escrever",
    "apagar_arquivo": "apagar",
    "renomear_arquivo": "renomear",
    "mover_arquivo": "mover",
    "executar_comando": "executar",
    "executar_script": "executar",
    "executar_comando_fundo": "executar",
    "workspace_rodar": "executar",
    "desfazer_ultima_mudanca": "escrever",
    "editar_transacao": "escrever",
    "git_commit": "executar",
}


def executar(acao: str, **campos) -> str:
    """
    Ponto único que as ferramentas do ferramentas.py chamam. Resolve a ação,
    pede permissão quando necessário, e executa. Devolve o texto pro modelo.
    """
    try:
        import modo_demo
        if modo_demo.ativo() and acao in {
                "executar_comando", "executar_script", "executar_comando_fundo",
                "workspace_rodar", "instalar_pacote", "git_commit"}:
            return ("Execução de comandos e instalação ficam bloqueadas no Modo Demo. "
                    "Posso continuar lendo e editando o projeto temporário.")
    except Exception:
        pass
    # Leitura/contexto — sem permissão.
    if acao == "ler_arquivo":
        return ler_arquivo(campos.get("arquivo", ""),
                           campos.get("linha_inicio"),
                           campos.get("linha_fim"))
    if acao == "listar_arquivos":
        return listar_arquivos(campos.get("pasta", ""))
    if acao == "ver_estrutura":
        return ver_estrutura(campos.get("profundidade", 3))
    if acao == "buscar_texto":
        return buscar_texto(campos.get("padrao", ""), campos.get("em", ""))
    if acao == "achar_arquivo":
        return achar_arquivo(campos.get("nome", ""))
    if acao == "ver_projeto":
        return ver_projeto()

    # Git — leitura livre; commit pede permissão (via _ACAO_PEDE_PERMISSAO).
    if acao == "git_status":
        return git_status()
    if acao == "git_diff":
        return git_diff(campos.get("relativo", ""))
    if acao == "git_log":
        return git_log(campos.get("quantos", 10))

    # Pergunta — o JS responde (modal). Tratada pela ponte do interface_web.
    if acao == "perguntar":
        raise NotImplementedError("perguntar é tratado pela ponte do interface_web")

    # Escrita/execução — pede permissão se necessário, com preview do que muda.
    tipo = _ACAO_PEDE_PERMISSAO.get(acao)
    relativo = campos.get("arquivo") or campos.get("comando") or ""
    # Transação multi-arquivo: a permissão ancora no PRIMEIRO arquivo da leva
    # (o modal avisa que são vários arquivos via preview).
    if not relativo and acao == "editar_transacao":
        edicoes = campos.get("edicoes") or []
        if edicoes and isinstance(edicoes, list):
            relativo = str(edicoes[0].get("arquivo", "")) if isinstance(edicoes[0], dict) else ""
    caminho = _resolver(relativo) if relativo and tipo != "executar" else None
    if tipo == "executar":
        caminho = None
    # Execução não aponta pra um arquivo, então a regra de "permitir sempre"
    # ancora na PASTA DO PROJETO — foi assim que o multi-modelo registrou a
    # dela (emily_code_multi._auto_aprovar_permissoes). Antes o check era
    # sempre sem caminho, então uma regra por pasta nunca casava e todo
    # comando do pipeline vinha "Operação negada pelo Vitor".
    ancora = projeto_raiz() if tipo == "executar" else caminho
    if tipo and requer_permissao(tipo, ancora):
        preview = _gerar_preview(acao, caminho, campos)
        resposta = _pedir_permissao(tipo, acao, caminho, preview)
        if resposta != PERMISSAO_SIM:
            if resposta == PERMISSAO_SEMPRE:
                registrar_permissao_sempre(tipo, ancora)
            else:
                return "Operação negada pelo Vitor."

    # Executa.
    if acao == "escrever_arquivo":
        rel = campos.get("arquivo", "")
        p = _resolver(rel)
        if p and p.is_file():
            _fazer_backup(rel, p)
        return escrever_arquivo(rel, campos.get("conteudo", ""))
    if acao == "editar_arquivo":
        rel = campos.get("arquivo", "")
        p = _resolver(rel)
        if p and p.is_file():
            _fazer_backup(rel, p)
        return editar_arquivo(rel,
                              campos.get("buscar", ""), campos.get("substituir", ""),
                              campos.get("ocorrencia", 0))
    if acao == "editar_linhas":
        rel = campos.get("arquivo", "")
        p = _resolver(rel)
        if p and p.is_file():
            _fazer_backup(rel, p)
        return editar_linhas(rel,
                             campos.get("linha_inicio", 1),
                             campos.get("linha_fim"),   # None → a função usa o total do arquivo
                             campos.get("novo_conteudo", ""))
    if acao == "editar_multi":
        rel = campos.get("arquivo", "")
        p = _resolver(rel)
        if p and p.is_file():
            _fazer_backup(rel, p)
        return editar_multi(rel, campos.get("edicoes", []))
    if acao == "apagar_arquivo":
        rel = campos.get("arquivo", "")
        p = _resolver(rel)
        if p and p.exists():
            _fazer_backup(rel, p)
        return apagar_arquivo(rel)
    if acao == "desfazer_ultima_mudanca":
        return desfazer_ultima_mudanca(campos.get("arquivo", ""))
    if acao == "renomear_arquivo":
        return renomear_arquivo(campos.get("arquivo", ""), campos.get("novo_nome", ""))
    if acao == "mover_arquivo":
        return mover_arquivo(campos.get("arquivo", ""), campos.get("destino", ""))
    if acao == "executar_comando":
        return executar_comando(campos.get("comando", ""))
    if acao == "executar_script":
        return executar_script(campos.get("arquivo", ""), campos.get("args", ""))
    if acao == "executar_comando_fundo":
        return executar_comando_fundo(campos.get("comando", ""))
    if acao == "ver_saida_processo":
        return ver_saida_processo(campos.get("id_processo", ""))
    if acao == "encerrar_processo":
        return encerrar_processo(campos.get("id_processo", ""))
    if acao == "git_commit":
        return git_commit(campos.get("mensagem", ""))
    if acao == "workspace_copiar":
        return workspace_copiar(campos.get("arquivo", ""), campos.get("para", ""))
    if acao == "workspace_escrever":
        return workspace_escrever(campos.get("nome", ""), campos.get("conteudo", ""))
    if acao == "workspace_ler":
        return workspace_ler(campos.get("nome", ""))
    if acao == "workspace_listar":
        return workspace_listar()
    if acao == "workspace_rodar":
        return workspace_rodar(campos.get("comando", ""))
    if acao == "workspace_limpar":
        return workspace_limpar()
    if acao == "listar_dependencias":
        return listar_dependencias()
    if acao == "instalar_pacote":
        return instalar_pacote(campos.get("gerenciador", ""), campos.get("nome", ""))
    if acao == "editar_transacao":
        # O backup dos arquivos é feito dentro da função na primeira alteração.
        return editar_transacao(campos.get("edicoes", []))

    return f"Não conheço a ação '{acao}' do Emily Code."


# ─────────────────────────────────────────────────────────────────
# GIT LOCAL (Fase 2.1)
# ─────────────────────────────────────────────────────────────────
# Ferramentas de git LOCAL: operam no repositório da pasta de projeto.
# A Emily já tem github_api.py pra GitHub remoto (PRs, issues, etc.);
# aqui é o git da máquina (status, diff, log, commit).

def _git_cmd(*args: str) -> str:
    """Roda um comando git na pasta de projeto e devolve a saída."""
    raiz = projeto_raiz()
    if raiz is None:
        return "Nenhuma pasta de projeto definida ainda."
    try:
        res = subprocess.run(
            ("git",) + args, cwd=str(raiz),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return "Git não está instalado no sistema."
    except subprocess.TimeoutExpired:
        return "O comando git demorou demais."
    except Exception as e:
        return f"Erro ao executar git: {e}"
    saida = (res.stdout or "").strip()
    erro = (res.stderr or "").strip()
    if res.returncode != 0:
        return f"(git falhou) {erro[:2000]}" if erro else f"(código {res.returncode})"
    return saida if saida else "(sem saída)"


def git_status() -> str:
    """Mostra o que mudou desde o último commit (working tree + staged)."""
    saida = _git_cmd("status", "--short", "--branch")
    if saida.startswith("(git falhou)"):
        # Tenta sem --short pra ver se é repositório mesmo
        return saida
    # Conta arquivos modificados, adicionados, etc.
    if not saida.strip() or saida == "(sem saída)":
        return "Nada mudou desde o último commit. Tudo limpo."
    return f"Status do repositório:\n{saida}"


def git_diff(relativo: str = "") -> str:
    """Diff do working tree (não staged). Um arquivo ou tudo."""
    args = ["diff", "--no-color"]
    if relativo:
        args.append(relativo.strip())
    saida = _git_cmd(*args)
    if not saida.strip() or saida == "(sem saída)":
        return "Nada modificado no working tree (ou o arquivo não mudou)."
    # Limita a 200 linhas pra não estourar o contexto
    linhas = saida.splitlines()
    if len(linhas) > 200:
        saida = "\n".join(linhas[:200]) + f"\n... (mais {len(linhas) - 200} linhas)"
    return saida


def git_log(quantos: int = 10) -> str:
    """Últimos commits: hash, autor, data, mensagem."""
    quantos = max(1, min(int(quantos or 10), 50))
    saida = _git_cmd(
        "log", f"-{quantos}",
        "--format=%h %ad %an: %s",
        "--date=short"
    )
    if not saida.strip() or saida == "(sem saída)":
        return "Nenhum commit encontrado (repositório sem histórico?)."
    return saida


def git_commit(mensagem: str) -> str:
    """
    Faz git add -A + git commit com a mensagem.
    Pede permissão (escreve no repositório).
    """
    if not mensagem or not mensagem.strip():
        return "Me diz a mensagem do commit."
    # Stage tudo
    add = _git_cmd("add", "-A")
    if add.startswith("(git falhou)"):
        return add
    # Commit
    res = _git_cmd("commit", "-m", mensagem.strip())
    return res


# ─────────────────────────────────────────────────────────────────
# CONVERSAS DO EMILY CODE (separadas das conversas normais)
#
# Mesmo padrão do conversas.py: gravação atômica, id/título separados,
# teto por conversa e por mensagem. Arquivo próprio pra não misturar
# com as conversas normais da Emily.
# ─────────────────────────────────────────────────────────────────

_ARQUIVO_CONVERSAS = Path(
    os.getenv("EMILY_ARQUIVO_CODE_CONVERSAS",
              str(Path.home() / ".emily_code_conversas.json")))
_MAX_CONVERSAS_CODE = 30
_MAX_MENSAGENS_CODE = 100
_lock_conversas = threading.Lock()

# Conversa ativa do Emily Code nesta sessão.
_conversa_atual: Optional[str] = None
# A tarefa de uma conversa continua rodando mesmo se o usuário abrir outra.
# Ferramentas consultam este contexto local antes do seletor global da UI, para
# não trocar pasta/permissões no meio de uma execução antiga.
_contexto_conversa = threading.local()


@contextmanager
def code_contexto_conversa(cid: Optional[str]):
    """Prende pasta e permissões à conversa da thread durante uma execução."""
    anterior = getattr(_contexto_conversa, "cid", None)
    _contexto_conversa.cid = cid or None
    try:
        yield
    finally:
        _contexto_conversa.cid = anterior


def _carregar_conversas() -> dict:
    try:
        with open(_ARQUIVO_CONVERSAS, encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict) and isinstance(dados.get("conversas"), list):
            # Arquivos de versões antigas/crashes podem conter IDs repetidos ou
            # uma ativa que já não existe. Sanitiza em memória antes de expor.
            unicas = []
            ids = set()
            for c in dados["conversas"]:
                if not isinstance(c, dict) or not c.get("id") or c["id"] in ids:
                    continue
                ids.add(c["id"])
                c.setdefault("mensagens", [])
                if not isinstance(c["mensagens"], list):
                    c["mensagens"] = []
                unicas.append(c)
            # Versões antigas criavam um cartão a cada clique em "Novo", mesmo
            # sem mensagem. Mantém só um rascunho realmente vazio; qualquer
            # conversa com conteúdo, pasta ou permissão é preservada.
            vazias = [c for c in unicas if not c.get("mensagens")
                      and not str(c.get("projeto") or "").strip()
                      and not (c.get("permissoes", {}) or {}).get("sempre")
                      and (c.get("titulo") or "Conversa de código") == "Conversa de código"]
            if len(vazias) > 1:
                ativa = dados.get("ativa")
                manter = next((c for c in vazias if c.get("id") == ativa), None)
                manter = manter or max(vazias, key=lambda c: c.get("mexida", 0))
                ids_descartar = {c["id"] for c in vazias if c is not manter}
                unicas = [c for c in unicas if c.get("id") not in ids_descartar]
            dados["conversas"] = unicas
            ids = {c["id"] for c in unicas}
            if dados.get("ativa") not in ids:
                dados["ativa"] = None
            return dados
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"conversas": [], "ativa": None}


def _guardar_conversas(dados: dict) -> None:
    """Grava o estado NOVO (não recarrega o disco, que gravaria o velho)."""
    dados["ativa"] = _conversa_atual
    try:
        _ARQUIVO_CONVERSAS.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ARQUIVO_CONVERSAS.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _ARQUIVO_CONVERSAS)
    except OSError as e:
        print(f"[EMILY-CODE] não consegui gravar conversas: {e}")


def _achar_conversa(cid: str) -> Optional[dict]:
    for c in _carregar_conversas()["conversas"]:
        if c.get("id") == cid:
            return c
    return None


def _conversa_atual_dict() -> Optional[dict]:
    """O dict da conversa ativa do code (sessão ou disco), ou None."""
    cid = getattr(_contexto_conversa, "cid", None) or code_conversa_atual()
    if not cid:
        return None
    return _achar_conversa(cid)


def _atualizar_conversa(cid: str, **campos) -> None:
    """Grava campos extras numa conversa do novo estado (sem recarregar o disco)."""
    if not cid:
        return
    with _lock_conversas:
        dados = _carregar_conversas()
        c = next((x for x in dados["conversas"] if x.get("id") == cid), None)
        if c is None:
            return
        c.update(campos)
        c["mexida"] = time.time()
        _guardar_conversas(dados)


def code_criar_conversa(primeira: str = "") -> str:
    """Cria uma conversa do Emily Code e devolve o id."""
    global _conversa_atual
    try:
        import modo_demo
        if modo_demo.ativo():
            return modo_demo.code_criar(primeira)
    except Exception:
        pass
    with _lock_conversas:
        dados = _carregar_conversas()
        # "Novo" repetido não deve empilhar cartões vazios. Reaproveita o
        # rascunho ativo enquanto ele ainda não recebeu mensagem.
        ativa = next((c for c in dados["conversas"]
                      if c.get("id") == _conversa_atual), None)
        if ativa is not None and not ativa.get("mensagens") and not primeira.strip():
            return ativa["id"]
        cid = uuid.uuid4().hex[:12]
        agora = time.time()
        titulo = (primeira or "").strip()[:40] or "Conversa de código"
        # Conversa nova nasce SEM pasta própria: enquanto ela não tiver uma,
        # trabalha na pasta PADRÃO (projeto_raiz cai na global). O primeiro
        # definir_projeto dá a pasta dela — e a partir dali a conversa segue
        # a sua, mesmo que a padrão mude.
        dados["conversas"].append({
            "id": cid, "titulo": titulo, "criada": agora, "mexida": agora,
            "mensagens": [], "projeto": "", "permissoes": {"sempre": []},
        })
        if len(dados["conversas"]) > _MAX_CONVERSAS_CODE:
            dados["conversas"].sort(key=lambda c: c.get("mexida", 0))
            del dados["conversas"][:len(dados["conversas"]) - _MAX_CONVERSAS_CODE]
        _conversa_atual = cid
        _guardar_conversas(dados)
        return cid


def code_listar_conversas() -> list:
    """Metadados das conversas do code, da mais recente pra mais antiga."""
    try:
        import modo_demo
        if modo_demo.ativo():
            return modo_demo.code_listar()
    except Exception:
        pass
    with _lock_conversas:
        atual = code_conversa_atual()
        saida = [
            {"id": c["id"], "titulo": c.get("titulo") or "Conversa de código",
             "mexida": c.get("mexida", 0), "quantas": len(c.get("mensagens", [])),
             "ativa": c["id"] == atual, "projeto": c.get("projeto") or ""}
            for c in _carregar_conversas()["conversas"] if c.get("id")
        ]
    saida.sort(key=lambda c: -c["mexida"])
    return saida


def _persistir_ativa() -> None:
    """Grava a chave 'ativa' do disco com a conversa atual (já em _conversa_atual)."""
    with _lock_conversas:
        dados = _carregar_conversas()
        _guardar_conversas(dados)  # _guardar_conversas já seta dados["ativa"] = _conversa_atual


def code_abrir_conversa(cid: str) -> list:
    """As mensagens de uma conversa do code. Define e persiste a conversa ativa."""
    global _conversa_atual
    try:
        import modo_demo
        if modo_demo.ativo():
            return modo_demo.code_abrir(cid)
    except Exception:
        pass
    with _lock_conversas:
        c = _achar_conversa(cid)
        if c is None:
            return []
        _conversa_atual = cid
        mensagens = [dict(m) for m in c.get("mensagens", [])]
    _persistir_ativa()  # fora do lock: grava a 'ativa' no disco
    return mensagens


def code_acrescentar(cid: str, papel: str, texto: str) -> None:
    """Guarda uma mensagem na conversa do code."""
    try:
        import modo_demo
        if modo_demo.ativo():
            modo_demo.code_acrescentar(cid, papel, texto)
            return
    except Exception:
        pass
    if not cid or not texto or not texto.strip():
        return
    with _lock_conversas:
        dados = _carregar_conversas()
        c = next((x for x in dados["conversas"] if x.get("id") == cid), None)
        if c is None:
            return
        c["mensagens"].append({
            "papel": "emily" if papel == "emily" else "user",
            "texto": texto, "quando": time.time(),
        })
        if len(c["mensagens"]) > _MAX_MENSAGENS_CODE:
            del c["mensagens"][:len(c["mensagens"]) - _MAX_MENSAGENS_CODE]
        c["mexida"] = time.time()
        if c.get("titulo") in ("", "Conversa de código") and papel == "user":
            c["titulo"] = (texto or "").strip()[:40] or c["titulo"]
        _guardar_conversas(dados)

def code_renomear_conversa(cid: str, titulo: str) -> bool:
    try:
        import modo_demo
        if modo_demo.ativo():
            return modo_demo.code_renomear(cid, titulo)
    except Exception:
        pass
    novo = re.sub(r"\s+", " ", (titulo or "").strip())[:80]
    if not novo:
        return False
    with _lock_conversas:
        dados = _carregar_conversas()
        c = next((x for x in dados["conversas"] if x.get("id") == cid), None)
        if c is None:
            return False
        c["titulo"] = novo
        _guardar_conversas(dados)
        return True


def code_apagar_conversa(cid: str) -> bool:
    global _conversa_atual
    try:
        import modo_demo
        if modo_demo.ativo():
            return modo_demo.code_apagar(cid)
    except Exception:
        pass
    with _lock_conversas:
        dados = _carregar_conversas()
        antes = len(dados["conversas"])
        dados["conversas"] = [c for c in dados["conversas"]
                              if c.get("id") != cid]
        if len(dados["conversas"]) == antes:
            return False
        if _conversa_atual == cid:
            # Escolhe a conversa mais recente restante e salva esse ID no MESMO
            # write. Antes o JSON recebia o ID apagado e ressuscitava uma ativa
            # fantasma no próximo boot.
            restantes = sorted(dados["conversas"],
                               key=lambda c: c.get("mexida", 0), reverse=True)
            _conversa_atual = restantes[0].get("id") if restantes else None
        _guardar_conversas(dados)
        return True


def code_conversa_atual() -> Optional[str]:
    """Conversa da tarefa nesta thread, ou a selecionada/persistida na UI."""
    global _conversa_atual
    try:
        import modo_demo
        if modo_demo.ativo():
            return getattr(_contexto_conversa, "cid", None) or modo_demo.code_atual()
    except Exception:
        pass
    contexto = getattr(_contexto_conversa, "cid", None)
    if contexto:
        return contexto
    if _conversa_atual is None:
        _conversa_atual = _carregar_conversas().get("ativa") or None
    return _conversa_atual


def code_definir_conversa_atual(cid: Optional[str]) -> None:
    global _conversa_atual
    try:
        import modo_demo
        if modo_demo.ativo():
            modo_demo.code_definir_atual(cid or "")
            return
    except Exception:
        pass
    with _lock_conversas:
        dados = _carregar_conversas()
        ids = {c.get("id") for c in dados["conversas"]}
        _conversa_atual = cid if cid in ids else None
        _guardar_conversas(dados)


def code_para_o_modelo(cid: str) -> list:
    """Mensagens da conversa do code no formato de histórico do modelo."""
    try:
        import modo_demo
        if modo_demo.ativo():
            return modo_demo.code_para_modelo(cid)
    except Exception:
        pass
    with _lock_conversas:
        c = _achar_conversa(cid)
        if c is None:
            return []
        return [{"role": "user" if m.get("papel") == "user" else "assistant",
                 "content": m.get("texto", "")}
                for m in c.get("mensagens", [])]


