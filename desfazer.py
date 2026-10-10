"""Sistema de desfazer (undo) das operações de arquivo e envio para a lixeira.

Saiu de automacao.py, que re-exporta _registrar_undo, desfazer_ultima_acao e
_enviar_para_lixeira.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# Mesmo valor de automacao._FOF_ALLOWUNDO (flag do SHFileOperation).
_FOF_ALLOWUNDO = 0x0040


def _enviar_para_lixeira(caminho: Path) -> bool:
    """Envia arquivo ou pasta para a Lixeira do Windows."""
    if os.name != "nt":
        # Linux/Mac: deleta direto mesmo
        try:
            caminho.unlink() if caminho.is_file() else shutil.rmtree(str(caminho))
            return True
        except Exception:
            return False

    import ctypes
    import ctypes.wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd",                  wt.HWND),
            ("wFunc",                 wt.UINT),
            ("pFrom",                 wt.LPCWSTR),
            ("pTo",                   wt.LPCWSTR),
            ("fFlags",                ctypes.c_ushort),
            ("fAnyOperationsAborted", wt.BOOL),
            ("hNameMappings",         ctypes.c_void_p),
            ("lpszProgressTitle",     wt.LPCWSTR),
        ]

    _FO_DELETE      = 0x0003
    _FOF_ALLOWUNDO  = 0x0040   # ← essa flag é o que manda pra Lixeira em vez de deletar direto
    _FOF_NOCONFIRM  = 0x0010
    _FOF_NOERRORUI  = 0x0400

    op = SHFILEOPSTRUCTW()
    op.hwnd   = None
    op.wFunc  = _FO_DELETE
    op.pFrom  = str(caminho) + "\0\0"
    op.pTo    = None
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRM | _FOF_NOERRORUI

    try:
        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return ret == 0 and not op.fAnyOperationsAborted
    except Exception as e:
        print(f"[DEBUG automacao] Erro ao enviar pra lixeira: {e}")
        return False


_historico_undo: list[dict] = []


_UNDO_MAX = 10  # guarda até 10 ações


def _registrar_undo(entrada: dict) -> None:
    """Empilha uma ação no histórico. Se passar de 10, limpa a mais antiga."""
    _historico_undo.append(entrada)
    if len(_historico_undo) > _UNDO_MAX:
        antiga = _historico_undo.pop(0)
        # Se era um delete com backup, limpa a pasta de backup
        if antiga.get("tipo") == "deletar":
            backup_dir = Path(antiga.get("backup_dir", ""))
            if backup_dir.exists():
                try:
                    shutil.rmtree(str(backup_dir))
                except Exception:
                    pass


def desfazer_ultima_acao() -> str:
    """Desfaz a última ação de arquivo registrada."""
    if not _historico_undo:
        return "Não tem nada pra desfazer, Vitor!"

    entrada = _historico_undo.pop()
    tipo = entrada.get("tipo")

    try:
        # ── Desfazer mover (arquivo único) ──
        if tipo == "mover":
            destino_atual = Path(entrada["destino_final"])
            origem_original = Path(entrada["origem_original"])
            if not destino_atual.exists():
                return f"Não achei '{destino_atual.name}' pra desfazer."
            origem_original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destino_atual), str(origem_original))
            return f"Desfiz! Movi '{destino_atual.name}' de volta pra '{origem_original.parent.name}'."

        # ── Desfazer mover (vários arquivos) ──
        elif tipo == "mover_varios":
            sucessos, erros = [], []
            for item in entrada["itens"]:
                dest = Path(item["destino_final"])
                orig = Path(item["origem_original"])
                try:
                    if dest.exists():
                        orig.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(dest), str(orig))
                        sucessos.append(dest.name)
                    else:
                        erros.append(dest.name)
                except Exception as e:
                    erros.append(f"{dest.name} ({e})")
            resp = f"Desfiz! Movi {len(sucessos)} arquivo(s) de volta."
            if erros:
                resp += f" Não consegui reverter: {', '.join(erros)}"
            return resp

        # ── Desfazer copiar ──
        elif tipo == "copiar":
            sucessos, erros = [], []
            for caminho_str in entrada["caminhos_copiados"]:
                p = Path(caminho_str)
                try:
                    if p.exists():
                        shutil.rmtree(str(p)) if p.is_dir() else p.unlink()
                        sucessos.append(p.name)
                except Exception as e:
                    erros.append(f"{p.name} ({e})")
            resp = f"Desfiz! Deletei {len(sucessos)} cópia(s)."
            if erros:
                resp += f" Problemas: {', '.join(erros)}"
            return resp

        # ── Desfazer deletar (restaura do backup) ──
        elif tipo == "deletar":
            backup_dir = Path(entrada["backup_dir"])
            sucessos, erros = [], []
            for item in entrada["arquivos_backup"]:
                bkp = Path(item["backup"])
                orig = Path(item["original"])
                try:
                    if bkp.exists():
                        orig.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(bkp), str(orig))
                        sucessos.append(orig.name)
                    else:
                        erros.append(orig.name)
                except Exception as e:
                    erros.append(f"{orig.name} ({e})")
        
        elif tipo == "criar":
            caminho = Path(entrada["caminho"])
            if not caminho.exists():
                return f"'{caminho.name}' não existe mais nada pra desfazer."
            _enviar_para_lixeira(caminho)
            return f"Desfiz! Mandei '{caminho.name}' pra lixeira."

        
            # limpa pasta de backup se ficou vazia
            try:
                if backup_dir.exists() and not any(backup_dir.iterdir()):
                    backup_dir.rmdir()
            except Exception:
                pass
            resp = f"Desfiz! Restaurei {len(sucessos)} arquivo(s)."
            if erros:
                resp += f" Não consegui restaurar: {', '.join(erros)}"
            return resp

        # ── Desfazer renomear (arquivo único) ──
        elif tipo == "renomear":
            nome_novo = Path(entrada["nome_novo"])
            nome_antigo = Path(entrada["nome_antigo"])
            if not nome_novo.exists():
                return f"Não achei '{nome_novo.name}' pra desfazer a renomeação."
            if nome_antigo.exists():
                return f"Já existe '{nome_antigo.name}' na pasta. Não consigo desfazer."
            nome_novo.rename(nome_antigo)
            return f"Desfiz! Renomeei de volta pra '{nome_antigo.name}'."

        # ── Desfazer renomear (vários arquivos) ──
        elif tipo == "renomear_varios":
            sucessos, erros = [], []
            for item in reversed(entrada["itens"]):
                nome_novo = Path(item["nome_novo"])
                nome_antigo = Path(item["nome_antigo"])
                try:
                    if nome_novo.exists() and not nome_antigo.exists():
                        nome_novo.rename(nome_antigo)
                        sucessos.append(nome_antigo.name)
                    else:
                        erros.append(nome_novo.name)
                except Exception as e:
                    erros.append(f"{nome_novo.name} ({e})")
            resp = f"Desfiz! Renomeei {len(sucessos)} arquivo(s) de volta."
            if erros:
                resp += f" Não consegui reverter: {', '.join(erros)}"
            return resp

    except Exception as e:
        return f"Deu erro ao tentar desfazer: {e}"

    return "Não sei como desfazer essa ação."
