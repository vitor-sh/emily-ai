"""Prepara um rascunho de fontes públicas, sem publicar ou executar a Emily.

Lista positiva de arquivos + verificações em memória antes de gravar o ZIP.
Não use este arquivo como promessa de que a aplicação já pode ser distribuída.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import os
from zipfile import ZipFile, ZIP_DEFLATED

KIT = Path(__file__).resolve().parent
RAIZ = KIT.parent


class ExportacaoInsegura(ValueError):
    pass


# Nunca imprimir o conteúdo encontrado: a mensagem identifica só arquivo/regra.
PADROES = {
    "credencial conhecida": re.compile(
        r"(?:nvapi-[\w-]{20,}|gh[pousr]_[\w]{20,}|github_pat_[\w]{20,}|"
        r"AIza[\w-]{30,}|sk-(?:proj-|ant-)?[\w-]{28,}|"
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
    "endpoint pessoal": re.compile(
        r"https?://(?!exemplo\.|xxxx\.|seu-endereco\.)[a-z0-9.-]+"
        r"\.(?:ngrok-free\.(?:app|dev)|ngrok\.app|workers\.dev)\b", re.I),
    "caminho pessoal": re.compile(r"(?:/home/Hiucksam/|C:\\Users\\(?:Vitor|Hiucksam)\\)", re.I),
    "email pessoal": re.compile(r"vitorsh\.dev@gmail\.com", re.I),
    "identificador Discord embutido": re.compile(r"\b\d{17,20}\b"),
}
NOMES_PROIBIDOS = {
    "config.yaml", "credentials.json", "google-services.json", "memoria.json",
    "agenda.json", "vida_discord.json", "regras_servidor.md", "publicacoes.json",
    "configuracao.json", "provedor.env",
}
PARTES_PROIBIDAS = {
    ".git", "__pycache__", "backups", "build", "dist", "output", ".venv",
    "node_modules", "runtime", "emily-linux-instance", "emily-windows-instance",
}
EXTENSOES = {".py", ".js", ".css", ".html", ".md", ".txt", ".json", ".cs", ".csproj"}
LIMITE_ARQUIVO = 5 * 1024 * 1024


def caminho_seguro(nome: str) -> PurePosixPath:
    p = PurePosixPath(nome)
    if (not nome or "\\" in nome or p.is_absolute() or ":" in nome or
            any(parte in {"..", "."} for parte in nome.split("/")) or
            any(parte in PARTES_PROIBIDAS for parte in p.parts) or
            p.name in NOMES_PROIBIDOS or
            (p.name.startswith(".env") and p.name != ".env.example") or
            (p.suffix not in EXTENSOES and p.name not in {"LICENSE", ".gitignore", ".env.example"})):
        raise ExportacaoInsegura(f"Caminho não permitido: {nome}")
    return p


def ler_seguro(raiz: Path, nome: str) -> bytes:
    relativo = caminho_seguro(nome)
    if raiz.is_symlink():
        raise ExportacaoInsegura("A raiz não pode ser um link simbólico")
    atual = raiz
    for parte in relativo.parts:
        atual = atual / parte
        if atual.is_symlink():
            raise ExportacaoInsegura(f"Link simbólico não permitido: {nome}")
    if not atual.is_file() or atual.stat().st_size > LIMITE_ARQUIVO:
        raise ExportacaoInsegura(f"Arquivo ausente ou grande demais: {nome}")
    return atual.read_bytes()


def substituir_atribuicao(texto: str, nome: str, expressao: str) -> str:
    """Substitui só uma atribuição de módulo; aborta se a estrutura mudar."""
    nos = [n for n in ast.parse(texto).body if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == nome for t in n.targets)]
    if len(nos) != 1:
        raise ExportacaoInsegura(f"Padrão público precisa ser revisado: {nome}")
    no = nos[0]
    linhas = texto.splitlines(keepends=True)
    linhas[no.lineno - 1:no.end_lineno] = [f"{nome} = {expressao}\n"]
    return "".join(linhas)


def preparar_texto(nome: str, bruto: bytes) -> tuple[bytes, list[str]]:
    texto = bruto.decode("utf-8")
    mudancas = []
    if nome == "interface.py":
        antigo = "Discord\\app-1.x\\)."
        if texto.count(antigo) != 1:
            raise ExportacaoInsegura("Docstring de caminho precisa ser revisada: interface.py")
        texto = texto.replace(antigo, "Discord/app-1.x/).")
        mudancas.append("Exemplo de caminho em docstring sem escapes inválidos no Python")
    if nome == "hollow_knight_emily/mod/EmilyCompanion.csproj":
        texto, quantidade = re.subn(r"<HollowKnightRefs>[^<]+</HollowKnightRefs>",
                                   '<HollowKnightRefs Condition="\'$(HollowKnightRefs)\' == \'\'"></HollowKnightRefs>', texto)
        if quantidade != 1:
            raise ExportacaoInsegura("Referência do Hollow Knight precisa ser revisada")
        mudancas.append("Caminho Steam pessoal removido; build exige propriedade HollowKnightRefs do usuário")
    if nome == "requirements.txt":
        marcador = "# ── LLM"
        if marcador not in texto:
            raise ExportacaoInsegura("Cabeçalho de dependências precisa ser revisado")
        texto = ("# Dependências da instalação pessoal atual, ainda não validadas em perfis limpos.\n"
                 "# Windows e Linux: revisar dependências nativas por sistema antes de instalar.\n"
                 "# Não é uma lista mínima; veja RELEASE_CHECKLIST.md.\n\n" + marcador + texto.split(marcador, 1)[1])
        mudancas.append("Cabeçalho antigo Windows-only substituído por status de validação real")
    if nome == "discord_bot.py":
        texto = substituir_atribuicao(texto, "APELIDOS_MEMBROS", "{}")
        arvore = ast.parse(texto)
        no = next(n for n in arvore.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_CONFIG_PADRAO" for t in n.targets))
        config = ast.literal_eval(no.value)
        config.update(coadmins_id=[], nomes_do_dono=[], permitir_admin=False,
                      ouvir_call=False, responder_call=False, responder_dm=False)
        texto = substituir_atribuicao(texto, "_CONFIG_PADRAO", repr(config))
        mudancas.append("Padrões Discord sem membros/coadmins pessoais; escuta, DM e administração desativadas")
    if nome == "voz.py":
        texto = substituir_atribuicao(texto, "FISH_VOICE_ID", 'os.getenv("FISH_VOICE_ID", "1d5c6866f45a44a3aa8df65061908ab2")')
        mudancas.append("ID não secreto da voz Emily autorizado como padrão; chave fornecida pelo usuário")
    if nome == "preferencias.py":
        antigo = 'os.getenv("EMILY_USUARIO", "Vitor")'
        if texto.count(antigo) != 1:
            raise ExportacaoInsegura("Padrão de nome precisa ser revisado: preferencias.py")
        texto = texto.replace(antigo, 'os.getenv("EMILY_USUARIO", "Usuário")')
        mudancas.append("Nome padrão neutro")
    if nome == "memoria.py":
        antigo = 'os.getenv("EMILY_USUARIO", "Vitor")'
        if texto.count(antigo) != 3:
            raise ExportacaoInsegura("Padrão de memória precisa ser revisado: memoria.py")
        texto = texto.replace(antigo, 'os.getenv("EMILY_USUARIO", "Usuário")')
        mudancas.append("Memória nova sem nome pessoal padrão")
    # Exemplos de IDs em comentários não precisam divulgar IDs reais.
    if nome.endswith(".py"):
        linhas = texto.splitlines(keepends=True)
        linhas_doc = set()
        for no in ast.walk(ast.parse(texto)):
            if (isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant)
                    and isinstance(no.value.value, str)):
                linhas_doc.update(range(no.lineno - 1, no.end_lineno))
        for i, linha in enumerate(linhas):
            if linha.lstrip().startswith("#") or i in linhas_doc:
                linhas[i] = re.sub(r"\b\d{17,20}\b", "ID_DO_ADMIN", linha)
        novo = "".join(linhas)
        if novo != texto:
            mudancas.append("IDs de exemplo removidos de comentários/docstrings")
        texto = novo
    if nome.endswith(".py"):
        ast.parse(texto, filename=nome)
    return texto.encode("utf-8"), mudancas


def verificar(nome: str, bruto: bytes) -> None:
    texto = bruto.decode("utf-8")
    for regra, padrao in PADROES.items():
        if padrao.search(texto):
            raise ExportacaoInsegura(f"Revisão obrigatória: {nome} ({regra})")
    # Segredos literais em variáveis comuns; referências os.getenv não são valores.
    if nome.endswith(".py"):
        for no in ast.walk(ast.parse(texto)):
            if isinstance(no, ast.Dict):
                for chave, valor in zip(no.keys, no.values):
                    if (isinstance(chave, ast.Constant) and isinstance(chave.value, str) and
                            re.fullmatch(r"(?:api_key|token|password|secret|chave|senha)", chave.value, re.I) and
                            isinstance(valor, ast.Constant) and isinstance(valor.value, str) and
                            len(valor.value) > 12 and valor.value != "COLE_SEU_TOKEN_AQUI"):
                        raise ExportacaoInsegura(f"Revisão obrigatória: {nome} (segredo em dicionário)")
            if isinstance(no, (ast.Assign, ast.AnnAssign)):
                alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
                for alvo in alvos:
                    if (isinstance(alvo, ast.Name) and alvo.id != "env_chave" and
                            re.search(r"(?:API_KEY|TOKEN|PASSWORD|SECRET|CHAVE)$", alvo.id, re.I) and
                            isinstance(no.value, ast.Constant) and isinstance(no.value.value, str) and
                            len(no.value.value) > 12):
                        raise ExportacaoInsegura(f"Revisão obrigatória: {nome} (segredo literal)")
    if nome == ".env.example":
        for linha in texto.splitlines():
            if "=" not in linha or linha.lstrip().startswith("#"):
                continue
            chave, valor = linha.split("=", 1)
            if (re.search(r"(?:API_KEY|TOKEN|PASSWORD|SECRET|CHAVE)$", chave.strip(), re.I) and valor.strip()
                    and not (chave.strip().startswith("EMILY_PROVEDOR_") and
                             chave.strip().endswith("_CHAVE") and re.fullmatch(r"[A-Z][A-Z0-9_]*", valor.strip()))):
                raise ExportacaoInsegura(f"Revisão obrigatória: {nome} (valor de credencial no exemplo)")


def montar(destino: Path, raiz: Path = RAIZ, kit: Path = KIT) -> dict:
    manifesto = json.loads(ler_seguro(kit, "manifesto.json"))
    arquivos: dict[str, bytes] = {}
    alteracoes = {}
    for nome in manifesto["fontes"]:
        if nome in arquivos:
            raise ExportacaoInsegura(f"Arquivo repetido no manifesto: {nome}")
        bruto, mudancas = preparar_texto(nome, ler_seguro(raiz, nome))
        verificar(nome, bruto)
        arquivos[nome] = bruto
        if mudancas:
            alteracoes[nome] = mudancas
    for nome in manifesto["documentos"]:
        caminho_seguro(nome)
        if nome in arquivos:
            raise ExportacaoInsegura(f"Colisão de documento: {nome}")
        bruto = ler_seguro(kit / "modelo", nome)
        verificar(nome, bruto)
        arquivos[nome] = bruto
    relatorio = {
        "estado": "RASCUNHO — NÃO PUBLICAR ANTES DOS GATES",
        "licenca_codigo_proprio": "GPL-3.0-only",
        "alteracoes_apenas_na_copia": alteracoes,
        "arquivos": {nome: {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                     for nome, b in sorted(arquivos.items())},
        "limites": ["Scanner não substitui revisão humana de privacidade e direitos",
                    "Assets e instaladores privados excluídos; aplicação completa ainda não validada"],
    }
    arquivos["EXPORTACAO.json"] = json.dumps(relatorio, ensure_ascii=False, indent=2).encode()
    destino = destino.absolute()
    if destino.suffix.lower() != ".zip":
        raise ExportacaoInsegura("O destino deve ser um arquivo .zip")
    if destino.exists() or destino.is_symlink():
        raise FileExistsError("Destino já existe; escolha outro nome para preservar o arquivo")
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".public-source-", dir=destino.parent)
    os.close(fd)
    try:
        with ZipFile(temp, "w", ZIP_DEFLATED) as z:
            for nome, bruto in sorted(arquivos.items()):
                z.writestr("emily/" + nome, bruto)
        # link cria o destino sem sobrescrever arquivos criados durante o trabalho.
        os.link(temp, destino)
    finally:
        Path(temp).unlink(missing_ok=True)
    return relatorio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        relatorio = montar(args.output)
    except (ExportacaoInsegura, OSError, ValueError, SyntaxError) as exc:
        print(f"Exportação interrompida: {exc}")
        return 1
    print(f"Rascunho: {args.output} ({len(relatorio['arquivos'])} arquivos revisados automaticamente)")
    print("Não publicado. Leia RELEASE_CHECKLIST.md antes de distribuir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
