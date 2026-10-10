#!/usr/bin/env bash
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOTNET="$RAIZ/.tools/dotnet/dotnet"
PROJETO="$RAIZ/hollow_knight_emily/mod/EmilyCompanion.csproj"

export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1

"$DOTNET" build "$PROJETO" -c Release "$@"