#!/usr/bin/env bash
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOGO="${EMILY_HK_DIR:-$HOME/.local/share/Steam/steamapps/common/Hollow Knight}"
ORIGEM="$RAIZ/hollow_knight_emily/mod/bin/Release/net472/EmilyCompanion.dll"
DESTINO="$JOGO/hollow_knight_Data/Managed/Mods/EmilyCompanion"

if pgrep -f '(^|[/ ])hollow_knight(\.exe)?([[:space:]]|$)' >/dev/null; then
  echo "Feche o Hollow Knight antes de instalar o mod." >&2
  exit 1
fi
test -f "$ORIGEM"
mkdir -p "$DESTINO"

# A ponte permanente mantém o catálogo do upstream real nesta pasta. Não
# sobrescrevê-lo com o catálogo do desktop: a rota/modelo pode ser diferente.
# Na primeira instalação (serviço ainda desligado), gerar um catálogo provisório
# sem segredos; a ponte o substituirá assim que iniciar.
if [ ! -f "$RAIZ/hollow_knight_emily/runtime/modelos.json" ]; then
  (
    cd "$RAIZ"
    python - <<'PY'
from pathlib import Path
from hollow_knight_emily.python.hollow_knight_modelos import gravar_catalogo
gravar_catalogo(Path("hollow_knight_emily/runtime/modelos.json"))
PY
  ) || echo "Aviso: catálogo de modelos será criado quando a Emily iniciar." >&2
fi

cp -f "$ORIGEM" "$DESTINO/EmilyCompanion.dll"
cp -f "$RAIZ/hollow_knight_emily/mod/ModDependencies.txt" "$DESTINO/ModDependencies.txt"
if [ -f "$RAIZ/hollow_knight_emily/runtime/token.txt" ]; then
  cp -f "$RAIZ/hollow_knight_emily/runtime/token.txt" "$DESTINO/emily-hk-token.txt"
  chmod 600 "$DESTINO/emily-hk-token.txt" 2>/dev/null || true
fi
if [ -f "$RAIZ/hollow_knight_emily/runtime/modelos.json" ]; then
  cp -f "$RAIZ/hollow_knight_emily/runtime/modelos.json" "$DESTINO/emily-hk-modelos.json"
fi
echo "Mod instalado em: $DESTINO"