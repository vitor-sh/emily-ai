# Emily no Linux (Fedora)

Guia do estado atual. O plano original da migração está em
[PLANO_MIGRACAO_LINUX.md](PLANO_MIGRACAO_LINUX.md) e os relatórios de agosto
(`STATUS_FINAL.md`, `RESUMO_CORRECOES.md`, `INSTRUCOES_RAPIDAS.md`) ficaram
como registro histórico.

## Rodando pelo código-fonte

```bash
cd "/home/Hiucksam/My Projects/Projeto Emily/minha-ia"
pip install --user -r requirements.txt
./iniciar_emily.sh        # confere os imports de compatibilidade
python3 main.py
```

O `iniciar_emily.sh` só testa: carrega `platform_compat`, `compat_imports` e
`terminal`, e roda `testes_manuais/test_emily_init.py`. Ele não abre a Emily.

## Executável empacotado

```bash
python3 build_emily_linux.py
```

- Apaga `build/` e `dist/` e gera `dist/Emily/Emily` (onedir). Não importe
  esse script em outro código: importar já executa o build.
- O atalho do menu e o início automático (`~/.local/share/applications` e
  `~/.config/autostart`) apontam para `dist/Emily/Emily`. Para recriá-los,
  rode `dist/Emily/instalar_atalho.sh`.
- Rode com a sessão gráfica aberta. Sem display, o PyInstaller não coleta os
  submódulos do `pynput` e do `pystray`.
- O `.env` e o `config.yaml` são copiados para `_internal/` com permissão 600.
- Depois do build, o botão "Atualizar agora" das Configurações sincroniza os
  `.py` sem recompilar. Dependência nova ou nativa exige build novo.

## Ferramentas do sistema que o código usa

| Ferramenta | Para quê |
| --- | --- |
| `spectacle` | captura de tela no KDE Wayland |
| `ydotool` / `ydotoold` | mouse e teclado do agente visual (precisa de acesso ao uinput) |
| `kscreen-doctor` | geometria dos monitores |
| `wl-copy` / `wl-paste` | área de transferência |
| `gtk-launch`, `xdg-open`, `flatpak` | abrir apps e arquivos |
| `plasma-apply-cursortheme`, `kwriteconfig6` | cursor do agente (ver [CURSOR_AGENTE_KDE.md](CURSOR_AGENTE_KDE.md)) |
| `ffmpeg` | áudio e mídia |
| `webkit2gtk4.1` + `python3-gobject` | janela do pywebview (backend GTK) |

## Logs

Tudo vai para `~/.emily_log.txt` (ou `EMILY_LOG_PATH`). A tela inicial tem o
botão "Logs ao vivo".

## Testes

```bash
python3 -m pytest testes -q              # suíte automática
python3 testes_manuais/_teste_fluxo.py   # scripts de verificação manual
```

Parte da suíte precisa de display X/Wayland e de rede (pynput, pystray,
Playwright, gateway). Num terminal sem sessão gráfica, essas falhas são
esperadas.
