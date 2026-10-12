"""Pesquisa e controle interno do mesmo bot Discord, sem sessão gráfica."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import threading
from flask import Flask, jsonify, request

STATE = Path(os.environ.get('EMILY_DATA_DIR', '.'))/'discord-call-state.json'
_resume_attempted = False
_stopping = False

def salvar_call(channel_id):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'channel_id': int(channel_id or 0)}))
    tmp.chmod(0o600)
    os.replace(tmp, STATE)

async def retomar_call():
    global _resume_attempted
    if _resume_attempted: return
    _resume_attempted = True
    import discord_bot as bot
    try:
        channel = int(json.loads(STATE.read_text()).get('channel_id', 0))
    except (OSError, ValueError, TypeError): channel = 0
    if channel:
        if not await bot._conectar_voz(channel):
            print('[Oracle] Call anterior indisponível; chat continua ativo.', flush=True)

def registrar_estado_voz(channel):
    if not _stopping:
        salvar_call(channel.id if channel else 0)

async def acompanhar_call():
    import discord_bot as bot
    while True:
        if bot._pronto and _resume_attempted and not _stopping:
            vc = bot._voice_client
            if vc is None: salvar_call(0)
            elif vc.is_connected() and vc.channel: salvar_call(vc.channel.id)
            # Uma reconexão transitória não apaga o canal salvo.
        await asyncio.sleep(2)

def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 12*1024*1024

    @app.before_request
    def auth():
        cfg = json.loads(Path(os.environ['EMILY_RELAY_CONFIG']).read_text())
        expected = 'Bearer '+cfg['upload_key']
        if not hmac.compare_digest(request.headers.get('Authorization', ''), expected):
            return jsonify(erro='Não autorizado'), 401

    @app.get('/health')
    def health():
        import discord_bot as bot
        return jsonify(ok=True, discord_online=bot._client.is_ready(),
                       release=Path(__file__).resolve().parent.name,
                       voice_connected=bool(bot._voice_client and bot._voice_client.is_connected()))

    @app.post('/usage')
    def usage():
        import uso_codex
        return jsonify(uso_codex.cloud_usage())

    @app.post('/context')
    def context():
        import contexto_chat
        data=request.get_json(silent=True) or {}
        try:
            operation=data.get('operation','prepare')
            if operation=='recover':return jsonify(contexto_chat.recover(**data['args']))
            if operation=='read':return jsonify(contexto_chat.read_message(**data['args']))
            if operation=='profile':return jsonify(contexto_chat.profile(data.get('model')))
            if operation!='prepare' or not isinstance(data.get('messages'),list):raise ValueError('Pedido inválido')
            model=data.get('model','')
            if not isinstance(model,str) or len(model)>120:raise ValueError('Modelo inválido')
            messages,state=contexto_chat.prepare(data['messages'],data.get('tools',[]),model,data.get('output',10000))
            return jsonify(ok=True,messages=messages,context=state)
        except Exception as exc:
            return jsonify(ok=False,error=str(exc) if isinstance(exc,(ValueError,contexto_chat.ContextoCheio)) else 'Contexto indisponível; original preservado.'),422

    @app.post('/search')
    def search():
        data = request.get_json(silent=True)
        if not isinstance(data, dict): return jsonify(erro='Pedido inválido'), 400
        query = data.get('query', '')
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1500:
            return jsonify(erro='Consulta vazia ou grande demais'), 400
        try: count = max(1, min(10, int(data.get('max', 5))))
        except (ValueError, TypeError): count = 5
        import pesquisa
        if not pesquisa.BRAVE_API_KEY: return jsonify(erro='Pesquisa não configurada'), 503
        try:
            response = pesquisa._brave_get(pesquisa._BRAVE_WEB_URL,
                params={'q': query.strip(), 'count': count, 'country': 'BR'}, timeout=(5, 20))
            try:
                if not response.ok: return jsonify(erro=f'Busca respondeu {response.status_code}'), 502
                results = (response.json().get('web') or {}).get('results') or []
                return jsonify(ok=True, resultados=[{'titulo': r.get('title') or r.get('url', ''),
                    'url': r.get('url', ''), 'resumo': r.get('description', '')} for r in results])
            finally: response.close()
        except Exception:
            return jsonify(erro='Pesquisa indisponível no momento'), 502

    @app.post('/casa')
    def casa():
        """Lâmpada e tomada pela nuvem da Tuya, para o Android funcionar com o PC desligado."""
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('args', {}), dict):
            return jsonify(ok=False, mensagem='Pedido inválido'), 400
        import casa_inteligente as casa
        from ferramentas import _pc_responde
        operation, args = data.get('operation'), data.get('args', {})
        try:
            if not casa.configurada():
                return jsonify(ok=False, mensagem='A casa ainda não está configurada na Oracle.'), 503
            if operation == 'estado':
                result = casa.estado()
                for item in result.get('dispositivos', []): item.pop('hsv', None)
                return jsonify({**result, 'ok': True, 'mensagem': casa.descrever_estado(result)})
            if operation == 'luz':
                allowed = {'acao', 'cor', 'brilho', 'temperatura', 'alvo'}
                if not set(args) <= allowed or not isinstance(args.get('acao'), str):
                    return jsonify(ok=False, mensagem='Argumentos inválidos'), 400
                return jsonify(casa.controlar_luz(args['acao'], alvo=str(args.get('alvo') or ''),
                    cor=str(args.get('cor') or ''), brilho=args.get('brilho'), temperatura=args.get('temperatura')))
            if operation == 'tomada':
                allowed = {'acao', 'aparelho', 'aguardar_pc'}
                if not set(args) <= allowed or not isinstance(args.get('acao'), str):
                    return jsonify(ok=False, mensagem='Argumentos inválidos'), 400
                return jsonify(casa.controlar_tomada(args['acao'], str(args.get('aparelho') or ''),
                    pc_online=_pc_responde, aguardar_pc=args.get('aguardar_pc') is True))
            if operation == 'energia_pc':
                acao = args.get('acao')
                if acao not in {'estado', 'ligar', 'desligar', 'confirmar_desligar', 'cancelar'}:
                    return jsonify(ok=False, mensagem='Ação de energia inválida'), 400
                return jsonify(casa.energia_pc(acao, pc_online=_pc_responde,
                    aguardar_pc=args.get('aguardar_pc') is True,
                    confirmation_id=str(args.get('confirmation_id') or '')))
            return jsonify(ok=False, mensagem='Operação desconhecida'), 400
        except casa.CasaErro as exc:
            return jsonify(ok=False, mensagem=str(exc)), 502
        except Exception:
            return jsonify(ok=False, mensagem='A casa não respondeu agora. Tente de novo.'), 502

    @app.post('/discord/rpc')
    def rpc():
        import discord_bot as bot
        from cloud_runtime_client import REMOTE_METHODS
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('args', {}), dict):
            return jsonify(erro='Pedido inválido'), 400
        method, args = data.get('method'), data.get('args', {})
        if method == 'status':
            return jsonify(ok=True, result={'online': bot._client.is_ready(),
                'monitor': bot._escuta_discord_ativa.is_set(),
                'call': int(bot._voice_client.channel.id) if bot._voice_client and bot._voice_client.is_connected() else 0})
        if method == 'monitor':
            if set(args) != {'ligado'} or not isinstance(args['ligado'], bool):
                return jsonify(erro='Estado inválido'), 400
            import preferencias, discord_monitor
            preferencias.definir(discord_cloud_escuta=args['ligado'])
            return jsonify(ok=True, result=discord_monitor.aplicar() == args['ligado'])
        if method == 'voice_probe':
            # Diagnóstico privado: adota a call atual ou entra em um canal vazio.
            # Não envia texto nem áudio para pessoas durante o teste.
            async def probe():
                vc = bot._voice_client
                started = False
                if vc is None or not vc.is_connected():
                    channels = [c for g in bot._client.guilds for c in g.voice_channels
                        if not c.members and c.permissions_for(g.me).connect and c.permissions_for(g.me).speak]
                    if not channels:
                        return {'connected':False, 'reason':'nenhum_canal_vazio'}
                    if not await bot._conectar_voz(channels[0].id):
                        return {'connected':False, 'reason':'conexao_falhou'}
                    vc = bot._voice_client
                    started = True
                import escuta_call, patch_dave
                salvar_call(vc.channel.id)
                return {'connected':vc.is_connected(), 'listening':escuta_call.pretendo_ouvir(),
                    'dave_patch':patch_dave.aplicado(), 'channel':vc.channel.id, 'started':started}
            try:
                result = asyncio.run_coroutine_threadsafe(probe(),bot._loop).result(timeout=50)
                return jsonify(ok=True,result=result)
            except Exception:
                return jsonify(ok=False,erro='Diagnóstico de voz indisponível'),502
        if method == 'tool':
            from ferramentas import CATALOGO, executar_estruturado
            from cloud_runtime_client import ferramenta_local_na_nuvem
            from dataclasses import asdict
            name, arguments = args.get('nome'), args.get('argumentos', {})
            f = CATALOGO.get(name) if isinstance(name, str) else None
            if f is None or not ferramenta_local_na_nuvem(f) or not isinstance(arguments, dict):
                return jsonify(erro='Ferramenta não permitida'),400
            import discord_admin
            discord_admin.definir_sessao(nivel='dono', autor_id=int(bot._config.get('usuario_id',0)), origem='local')
            try:
                result = executar_estruturado(name, arguments, args.get('contexto') or {})
                return jsonify(ok=True, result=asdict(result))
            finally: discord_admin.limpar_sessao()
        if method not in REMOTE_METHODS: return jsonify(erro='Método não permitido'), 400
        if not bot._client.is_ready(): return jsonify(ok=False, erro='Bot reconectando'), 503
        try:
            return jsonify(ok=True, result=getattr(bot, method)(**args))
        except TypeError: return jsonify(erro='Argumentos inválidos'), 400
        except Exception: return jsonify(ok=False, erro='Operação do Discord indisponível'), 502

    return app

async def run_bot():
    import discord_bot as bot
    bot._config = bot._carregar_config()
    bot._loop = asyncio.get_running_loop()
    token = bot._config.get('token', '')
    if not token or token == 'COLE_SEU_TOKEN_AQUI': raise RuntimeError('Bot não configurado')
    import signal
    async def stop():
        global _stopping
        _stopping = True
        vc = bot._voice_client
        if vc and vc.channel: salvar_call(vc.channel.id)
        await bot._client.close()
    for sig in (signal.SIGTERM, signal.SIGINT):
        bot._loop.add_signal_handler(sig, lambda: asyncio.create_task(stop()))
    state_task = asyncio.create_task(acompanhar_call())
    try: await bot._client.start(token)
    finally: state_task.cancel()

def main(preflight=False):
    global STATE
    import dotenv
    config_path = os.environ['EMILY_CONFIG_FILE']
    dotenv.load_dotenv(config_path, override=True)
    os.environ['EMILY_CONFIG_FILE'] = config_path
    STATE = Path(os.environ['EMILY_DATA_DIR'])/'discord-call-state.json'
    import time
    time.tzset()
    os.environ['PYNPUT_BACKEND'] = 'dummy'
    import modelo, voz, discord_bot, escuta_call, resto_call, audio_preprocessing
    import discord.opus
    if not discord.opus.is_loaded(): discord.opus.load_opus('libopus.so.0')
    modelo.atualizar_memoria(__import__('memoria').carregar_memoria())
    import llm, preferencias
    prefs = preferencias.carregar()
    if prefs.get('provedor'):
        llm.definir_provedor_e_modelo(prefs['provedor'], prefs.get('modelo', ''))
    else:
        llm.definir_modelo_conversa(prefs.get('modelo', ''))
    llm.definir_raciocinio_conversa(prefs.get('raciocinio', ''))
    if preflight:
        print('Preflight da pesquisa, texto e voz aprovado.', flush=True)
        return
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 15100, create_app(), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    asyncio.run(run_bot())

if __name__ == '__main__':
    import sys
    sys.modules.setdefault('cloud_runtime_server', sys.modules[__name__])
    main('--preflight' in sys.argv)
