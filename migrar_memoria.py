#!/usr/bin/env python3
"""Fase 6 — migra as memórias antigas da Emily para a memória unificada.

Fontes (100% READ-ONLY, nenhuma é alterada):
  memoria      → memoria.json (fatos curados do Vitor) — entram DIRETO
  conversas    → ~/.emily_conversas.json (chats web) — eventos → extração
  code         → ~/.emily_code_conversas.json (Emily Code) — pool "code"
  discord      → memoria_discord.json (fatos curados por membro + contexto)
  dms          → ~/.emily_dm_historico.json — namespace discord:<id> por pessoa

Idempotente: IDs determinísticos; rodar de novo não duplica nada.

Uso:
  python migrar_memoria.py --dry-run                 # só mostra o plano
  python migrar_memoria.py --executar                # migra tudo
  python migrar_memoria.py --executar --fontes memoria dms
  python migrar_memoria.py --executar --limite-eventos 400
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migra memórias antigas para a memória unificada.")
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--dry-run", action="store_true",
                      help="mostra o que seria migrado, sem gravar nada")
    modo.add_argument("--executar", action="store_true",
                      help="migra de verdade (idempotente)")
    parser.add_argument(
        "--fontes", nargs="+", default=None, metavar="FONTE",
        help="memoria conversas code discord dms (padrão: todas)")
    parser.add_argument(
        "--limite-eventos", type=int, default=None,
        help="teto de eventos por fonte; mantém os mais recentes")
    args = parser.parse_args()

    # Import tardio: argparse/erros não precisam abrir Chroma nem config.
    from memoria_unificada.migracao import MigradorMemoria

    migrador = MigradorMemoria()
    habilitada = bool(getattr(migrador.config, "habilitada", False))
    relatorio = migrador.executar(
        fontes=args.fontes,
        seco=args.dry_run,
        limite_eventos=args.limite_eventos,
    )

    print("=" * 62)
    print("MIGRAÇÃO PARA A MEMÓRIA UNIFICADA"
          + ("  (dry-run — nada foi gravado)" if relatorio["seco"] else ""))
    print("=" * 62)
    print(f"dono: {relatorio['dono']}"
          f" | discord id do dono: {relatorio['dono_discord_id'] or '??'}")
    for fonte, contagem in relatorio["fontes"].items():
        print(f"  {fonte:11} {contagem}")
    print(f"fatos diretos (curados): {relatorio['fatos_diretos']}")
    print(f"eventos (vão pra extração): {relatorio['eventos']}")
    if not relatorio["seco"]:
        print(f"fatos gravados: {relatorio['fatos_gravados']}"
              f" (já existiam: {relatorio['fatos_ja_existiam']})")
        print(f"lotes de extração processados: {relatorio['lotes_extracao']}")

    if relatorio["erros"]:
        print("ERROS:")
        for erro in relatorio["erros"]:
            print(f"  - {erro}")

    if not habilitada and not relatorio["seco"]:
        print("\nAviso: EMILY_MEMORIA_UNIFICADA está desligada. Os dados foram"
              " gravados na pasta da memória nova, mas a Emily só passa a"
              " usá-los quando você ligar a flag no .env.")

    return 1 if relatorio["erros"] else 0


if __name__ == "__main__":
    sys.exit(main())
