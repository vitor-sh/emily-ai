# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/web', 'web'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/static', 'static'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/img', 'img'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/emilyimage.png', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/emily.gif', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/.env', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/requirements.txt', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/assets', 'assets'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/memoria.json', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/agenda.json', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/vida_discord.json', '.'), ('/home/Hiucksam/My Projects/Projeto Emily/minha-ia/config.yaml', '.'), ('/home/Hiucksam/.cache/ms-playwright/chromium_headless_shell-1223', 'playwright-browsers/chromium_headless_shell-1223')]
binaries = []
hiddenimports = ['agenda', 'agente_estudo', 'agente_jogo', 'agente_ui', 'agente_ui_catalogo', 'android_editor', 'android_editor_instrument', 'android_editor_stream', 'atualizador_emily', 'audio_preprocessing', 'automacao', 'build_emily_windows', 'classificacao_ferramentas', 'cloud_runtime_client', 'cloud_runtime_server', 'comandos_rapidos', 'compat_imports', 'config_agente_visual', 'contexto_chat', 'contexto_ferramentas', 'controle_tv', 'conversas', 'cursor_agente', 'desktop_backend', 'diagnostico_execucao', 'disco', 'discord_admin', 'discord_bot', 'discord_monitor', 'editor_assets', 'editor_assistant', 'editor_interface', 'emily_code', 'emily_code_multi', 'emily_discord_publico', 'emily_gateway_service_push', 'emily_logs', 'emily_paths', 'emily_primeiro_inicio', 'emily_public', 'emily_remote', 'escuta_call', 'espiadinha', 'estilo_vitor', 'ferramentas', 'ferramentas_cloud', 'ferramentas_discord', 'ferramentas_imagem', 'ferramentas_vida', 'firebase_endpoint', 'fish_voz_texto', 'gateway_endpoint', 'gateway_windows_entry', 'github_api', 'gravar_voz', 'historico_dm', 'intencoes', 'interface', 'interface_web', 'laco_ferramentas', 'limites_modelos', 'limpar_armazenamento', 'livro_regras', 'llm', 'main', 'memoria', 'midia_navegador', 'migrar_memoria', 'modelo', 'moderacao', 'modo_demo', 'music_discovery', 'music_gateway', 'music_identify', 'music_letras', 'music_offline', 'music_player', 'music_player_parte1', 'music_sync', 'navegador', 'navegador_interno', 'normalizar_audio', 'notificacoes', 'orcamento_agente', 'orquestrador_voz', 'patch_dave', 'pc_apps', 'pc_apps_admin', 'pc_terminal', 'perfil_discord', 'personalidade_emily', 'pesquisa', 'pet_desktop_fedora', 'platform_compat', 'politica_agente', 'preferencias', 'preparar_music_android', 'preparar_pet_desktop', 'preparar_windows_fonte', 'programacao', 'programacao_ambiente', 'programacao_deploy', 'programacao_preview', 'programacao_worker', 'programacao_workspace', 'progresso_discord', 'prova_call', 'publicar_discord', 'publicar_windows', 'publicar_windows_codigo', 'resto_call', 'servicos_runtime', 'servidor', 'sincronizacao_desktop', 'snowflake_proxy', 'sprite_flutuante', 'suporte', 'tarefa_pendente', 'tecla_ptt', 'tela_stream', 'terminal', 'uso_codex', 'validador', 'vida_discord', 'visao', 'voz', 'voz_compat', 'windows_code_update', 'windows_update', 'xadrez_emily', 'xadrez_sons', 'xadrez_stockfish', 'memoria_unificada', 'emily_cloud', 'emily_cloud.core', 'emily_cloud.service', 'emily_cloud.integration', 'emily_cloud.routes', 'emily_cloud.archives', 'emily_cloud.location', 'emily_cloud.storage', 'hollow_knight_emily', 'hollow_knight_emily.python', 'hollow_knight_emily.python.hollow_knight_audio', 'hollow_knight_emily.python.hollow_knight_cerebro', 'hollow_knight_emily.python.hollow_knight_memoria', 'hollow_knight_emily.python.hollow_knight_modelos', 'hollow_knight_emily.python.hollow_knight_permanente', 'hollow_knight_emily.python.hollow_knight_politica', 'hollow_knight_emily.python.hollow_knight_protocolo', 'hollow_knight_emily.python.hollow_knight_ponte', 'personalidade_emily', 'webview.platforms.gtk', 'mss.linux', 'mss.tools', 'pyautogui', 'pyscreeze', 'pygetwindow', 'pynput._util', 'pynput._util.xorg', 'pynput.keyboard._xorg', 'pynput.mouse._xorg', 'dotenv', 'dotenv.main', 'selenium.webdriver.chrome.webdriver', 'selenium.webdriver.chrome.options', 'selenium.webdriver.chrome.service', 'selenium.webdriver.common.by']
tmp_ret = collect_all('discord')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('aiohttp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('watchdog')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('chromadb')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tokenizers')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['emily_bootstrap.py'],
    pathex=['/home/Hiucksam/My Projects/Projeto Emily/minha-ia'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['/home/Hiucksam/My Projects/Projeto Emily/minha-ia/pyi_rhook_emily.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Emily',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['*'],
    name='Emily',
)
