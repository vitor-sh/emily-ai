#!/usr/bin/env bash
set -euo pipefail

PASTA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="$HOME/.config/systemd/user/emily-gateway.service"
UNIT_NGROK="$HOME/.config/systemd/user/emily-ngrok.service"
UNIT_OMNI="$HOME/.config/systemd/user/omniroute-emily.service"
UNIT_TELA="$HOME/.config/systemd/user/tela-pc.service"
PASTA_TELA="$PASTA/../tela-pc-service"

python3 -c 'import flask, requests, websockets' >/dev/null
python3 -c 'import dbus, gi; gi.require_version("Gst", "1.0"); from gi.repository import GLib, Gst' >/dev/null
install -d -m 700 "$HOME/.config/systemd/user"
install -m 644 "$PASTA/emily-gateway.service" "$UNIT"
install -m 644 "$PASTA/omniroute-emily.service" "$UNIT_OMNI"
install -m 644 "$PASTA_TELA/tela-pc.service" "$UNIT_TELA"
if [[ -x /var/lib/snapd/snap/bin/ngrok ]]; then
    install -m 644 "$PASTA/emily-ngrok.service" "$UNIT_NGROK"
fi
chmod 755 "$PASTA/emily_gateway.py"
chmod 755 "$PASTA_TELA/tela_pc_service.py"
systemctl --user daemon-reload
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR \
  DBUS_SESSION_BUS_ADDRESS XDG_SESSION_TYPE XDG_CURRENT_DESKTOP 2>/dev/null || true
systemctl --user enable omniroute-emily.service
systemctl --user enable --now tela-pc.service
systemctl --user enable emily-gateway.service
systemctl --user restart emily-gateway.service
if [[ -f "$UNIT_NGROK" ]]; then
    systemctl --user enable --now emily-ngrok.service
fi
systemctl --user --no-pager --full status emily-gateway.service tela-pc.service