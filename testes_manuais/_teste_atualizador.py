"""
_teste_atualizador.py — o botão "Atualizar agora" da Emily empacotada.

Simula um pacote (pasta _internal/) e uma origem (pasta do projeto) e valida
o ciclo inteiro do atualizador_emily:
  1. origem sem registro é recuperada e persistida;
  2. aplicar com tudo novo → main, módulos e assets caem em _internal/;
  2. estado vira "tudo em dia";
  3. mudança na origem → diff detecta; reaplicar guarda backup da anterior;
  4. desfazer → volta exatamente pro estado anterior;
  5. .py com erro de sintaxe → recusa, nada é aplicado, staging limpo;
  6. módulo importando biblioteca inexistente → preflight falha → recusa com
     aviso de recompilação (o caso "adicionei lib nova");
  7. módulo removido da origem → override fantasma é apagado;
  8. main.py e requirements.txt mudados → ambos são sincronizados;
  9. pacote legado ainda avisa que main precisa da recompilação de migração.

O preflight roda num subprocess real, com o mesmo mecanismo do botão.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

_base = Path(tempfile.mkdtemp(prefix="emily_atualizador_teste_"))
_origem = _base / "projeto"
_pacote = _base / "pacote"
(_origem / "web").mkdir(parents=True)
(_origem / "assets" / "audio").mkdir(parents=True)
(_origem / "memoria_unificada").mkdir(parents=True)
(_origem / "emily_cloud").mkdir(parents=True)
(_pacote / "_internal" / "web").mkdir(parents=True)

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    r = "OK" if condicao else "FALHOU"
    print(f"[{r}] {nome}" + (f" -> {detalhe}" if detalhe and not condicao else ""))
    if not condicao:
        falhas.append(nome)


def _escrever(caminho: Path, conteudo: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding="utf-8")


# ── "projeto" (origem) e "pacote" iniciais ────────────────────────
_escrever(_origem / "main.py", "print('entry')\n")
_escrever(_origem / "mod_a.py", "VALOR = 1\n")
_escrever(_origem / "mod_b.py", "from mod_a import VALOR\nDOBRADO = VALOR * 2\n")
_escrever(_origem / "web" / "index.html", "<html>v1</html>\n")
_escrever(_origem / "assets" / "audio" / "rnnoise_bd.rnnn", "modelo-rnnoise-v1\n")
_escrever(_origem / "assets" / "audio" / "silero_vad.onnx", "modelo-silero-v1\n")
_escrever(_origem / "memoria_unificada" / "__init__.py", "VERSAO = 1\n")
_escrever(_origem / "memoria_unificada" / "config.py", "ATIVA = True\n")
_escrever(_origem / "emily_cloud" / "__init__.py", "ATIVA = True\n")
_escrever(_origem / "atualizador_emily.py",
          (Path(__file__).resolve().parent.parent / "atualizador_emily.py").read_text(
              encoding="utf-8"))
_escrever(_origem / "requirements.txt", "pacote-a==1.0\n")

hash_main = hashlib.md5((_origem / "main.py").read_bytes()).hexdigest()
_escrever(_pacote / "_internal" / "_atualizacao_base.json", json.dumps({
    "modulos": {}, "main_atualizavel": True, "entrypoint": "emily_bootstrap.py",
}))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atualizador_emily as at  # noqa: E402

# Simula o modo empacotado apontando pras pastas de teste.
at._caminho_pacote = lambda: _pacote
at._caminho_internal = lambda: _pacote / "_internal"
at.em_pacote = lambda: True

# 1) Registro ausente: recupera pelo ambiente e persiste para os próximos boots.
os.environ["EMILY_PROJECT_DIR"] = str(_origem)
checar("origem ausente é recuperada", at.origem_projeto() == _origem)
registro = _pacote / "_internal" / "origem_projeto.txt"
checar("origem recuperada fica registrada", registro.is_file()
       and registro.read_text(encoding="utf-8").splitlines()[0] == str(_origem))
os.environ.pop("EMILY_PROJECT_DIR", None)

# 2) Primeira aplicação: tudo é novo.
r = at.aplicar_atualizacao(reiniciar=False)
checar("aplicar #1 confirma", r.startswith("OK"), r)
checar("main.py caiu em _internal",
       (_pacote / "_internal" / "main.py").read_text(encoding="utf-8") == "print('entry')\n")
checar("mod_a.py caiu em _internal",
       (_pacote / "_internal" / "mod_a.py").read_text(encoding="utf-8") == "VALOR = 1\n")
checar("web/index.html caiu",
       (_pacote / "_internal" / "web" / "index.html").exists())
checar("modelos de áudio caíram em assets/audio",
       (_pacote / "_internal" / "assets" / "audio" / "rnnoise_bd.rnnn").exists()
       and (_pacote / "_internal" / "assets" / "audio" / "silero_vad.onnx").exists())
checar("pacote memoria_unificada caiu em _internal",
       (_pacote / "_internal" / "memoria_unificada" / "__init__.py").exists()
       and (_pacote / "_internal" / "memoria_unificada" / "config.py").exists())
checar("pacote emily_cloud caiu em _internal",
       (_pacote / "_internal" / "emily_cloud" / "__init__.py").exists())
checar("requirements.txt caiu em _internal",
       (_pacote / "_internal" / "requirements.txt").exists())
checar("manifesto gravado", bool(at._ler_manifesto().get("arquivos")))

# 2) Estado vira "tudo em dia".
st = at.estado_atualizacao()
checar("estado: nada a aplicar depois", st["quantos"] == 0, str(st["quantos"]))
checar("estado: pode desfazer", st["pode_desfazer"])

# 3) Mudança na origem → diff + backup no re-apply.
_escrever(_origem / "mod_a.py", "VALOR = 42\n")
_escrever(_origem / "assets" / "audio" / "rnnoise_bd.rnnn", "modelo-rnnoise-v2\n")
st = at.estado_atualizacao()
checar("diff detecta mod_a alterado", "mod_a.py" in st["mudados"],
       str(st["mudados"]))
checar("diff detecta modelo RNNoise alterado",
       "assets/audio/rnnoise_bd.rnnn" in st["assets"], str(st["assets"]))
r = at.aplicar_atualizacao(reiniciar=False)
checar("aplicar #2 confirma", r.startswith("OK"), r)
checar("novo valor aplicado",
       (_pacote / "_internal" / "mod_a.py").read_text(encoding="utf-8") == "VALOR = 42\n")
checar("modelo RNNoise v2 aplicado",
       (_pacote / "_internal" / "assets" / "audio" / "rnnoise_bd.rnnn").read_text(
           encoding="utf-8") == "modelo-rnnoise-v2\n")
backup_a = _pacote / "_internal" / "_atualizacao_backup" / "mod_a.py"
checar("backup da versão anterior existe",
       backup_a.exists() and backup_a.read_text(encoding="utf-8") == "VALOR = 1\n")
backup_modelo = (_pacote / "_internal" / "_atualizacao_backup" / "assets"
                 / "audio" / "rnnoise_bd.rnnn")
checar("backup do modelo anterior existe",
       backup_modelo.exists()
       and backup_modelo.read_text(encoding="utf-8") == "modelo-rnnoise-v1\n")

# 4) Desfazer → volta pra v1.
r = at.desfazer_atualizacao(reiniciar=False)
checar("desfazer confirma", r.startswith("OK"), r)
checar("mod_a voltou pra v1",
       (_pacote / "_internal" / "mod_a.py").read_text(encoding="utf-8") == "VALOR = 1\n")
checar("modelo RNNoise voltou pra v1",
       (_pacote / "_internal" / "assets" / "audio" / "rnnoise_bd.rnnn").read_text(
           encoding="utf-8") == "modelo-rnnoise-v1\n")
checar("manifesto limpo após desfazer", not at._ler_manifesto().get("arquivos"))

# 5) Erro de sintaxe → recusa total, nada aplicado.
_escrever(_origem / "mod_quebrado.py", "def x(:\n")
r = at.aplicar_atualizacao(reiniciar=False)
checar("sintaxe quebrada é recusada", not r.startswith("OK"), r)
checar("recusa não aplicou o módulo",
       not (_pacote / "_internal" / "mod_quebrado.py").exists())
checar("staging limpo após recusa",
       not (_pacote / "_internal" / "_staging_atualizacao").exists())
(_origem / "mod_quebrado.py").unlink()

# 6) Biblioteca inexistente → preflight falha → aviso de recompilação.
_escrever(_origem / "mod_lib_nova.py",
          "import biblioteca_que_nao_existe_9x7\n")
r = at.aplicar_atualizacao(reiniciar=False)
checar("lib nova recusada com aviso de recompilação",
       not r.startswith("OK") and "RECOMPILA" in r.upper(), r)
checar("recusa não aplicou o módulo da lib",
       not (_pacote / "_internal" / "mod_lib_nova.py").exists())
(_origem / "mod_lib_nova.py").unlink()

# 7) Módulo removido da origem → fantasma apagado no apply.
_escrever(_origem / "mod_temp.py", "TEMP = 1\n")
at.aplicar_atualizacao(reiniciar=False)
checar("mod_temp aplicado", (_pacote / "_internal" / "mod_temp.py").exists())
(_origem / "mod_temp.py").unlink()
r = at.aplicar_atualizacao(reiniciar=False)
checar("apply de remoção confirma", r.startswith("OK"), r)
checar("fantasma removido do pacote",
       not (_pacote / "_internal" / "mod_temp.py").exists())

# 8) main.py e requirements mudados → entram pelo mesmo botão no build novo.
_escrever(_origem / "main.py", "print('entry v2')\n")
_escrever(_origem / "requirements.txt", "pacote-a==2.0\n")
_escrever(_origem / "mod_a.py", "VALOR = 43\n")
st = at.estado_atualizacao()
checar("main novo aparece como arquivo alterado", "main.py" in st["mudados"],
       str(st["mudados"]))
checar("build com bootstrap não pede recompilação pelo main", not st["main_mudou"])
checar("requirements alterado é detectado", "requirements.txt" in st["assets"],
       str(st["assets"]))
r = at.aplicar_atualizacao(reiniciar=False)
checar("apply de main confirma sem pedir recompilação",
       r.startswith("OK") and "recompilação" not in r.lower(), r)
checar("main v2 aplicado",
       (_pacote / "_internal" / "main.py").read_text(encoding="utf-8") == "print('entry v2')\n")
checar("mod_a 43 aplicado mesmo com main mudado",
       (_pacote / "_internal" / "mod_a.py").read_text(encoding="utf-8") == "VALOR = 43\n")
checar("requirements v2 aplicado",
       (_pacote / "_internal" / "requirements.txt").read_text(encoding="utf-8") == "pacote-a==2.0\n")

# 9) Compatibilidade: manifesto sem flag representa pacote antigo. O main fica
# fora do override e a UI pede só a recompilação única de migração.
(_pacote / "_internal" / "main.py").unlink()
_escrever(_pacote / "_internal" / "_atualizacao_base.json",
          json.dumps({"modulos": {"main": hash_main}}))
at._base_cache.clear()
st = at.estado_atualizacao()
checar("pacote legado detecta main congelado diferente", st["main_mudou"])
checar("pacote legado não tenta sobrescrever main", "main.py" not in st["mudados"]
       and "main.py" not in st["novos"])

print()
if falhas:
    print(f"FALHOU: {len(falhas)} teste(s): {falhas}")
    sys.exit(1)
print("Tudo certo.")
