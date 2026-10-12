"""Reconhecimento fechado: uma frase inteira, alvo conhecido, sem inferências.

O que não casar exatamente continua pelo agente normal; não é uma proibição.
Não recebe anexos/histórico como comandos. Não interpreta código, citações,
condições, referências vagas, múltiplas ações ou texto de terceiros.
"""
import re
import unicodedata

APPS = {'calculadora':'calculadora', 'discord':'discord', 'spotify':'spotify',
        'firefox':'firefox', 'brave':'brave', 'chrome':'chrome', 'obs':'obs',
        'steam':'steam', 'vlc':'vlc', 'terminal':'terminal'}


def normalize(text):
    text = unicodedata.normalize('NFD', text or '')
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn').lower()
    return re.sub(r'\s+', ' ', text).strip()


def parse(text):
    if any(c in (text or '') for c in '\n\r'): return None
    s = normalize(text)
    # An interrogative, quoted or compound command is deliberately left to LLM.
    if any(c in s for c in '?"\'`\n;:'): return None
    s = s.rstrip('.!').strip()
    s = re.sub(r'^(?:(?:oi|ola),? )?emily,? ', '', s)
    s = re.sub(r'^por favor,? ', '', s)
    s = re.sub(r' (?:agora|por favor|pra mim)$', '', s)
    m = re.fullmatch(r'(?:abre|abra|abrir) (?:o |a )?('+'|'.join(APPS)+r')(?: no (?:meu )?(?:pc|computador))?',s)
    if m: return ('abrir_app', {'nome':APPS[m[1]]})
    # Só a lâmpada. Energia do PC nunca é atalho: passa pelo agente e pela trava.
    m = re.fullmatch(r'(liga|ligue|ligar|acende|acenda|desliga|desligue|desligar|apaga|apague) (?:a |minha |a minha )?(?:luz|lampada)(?: do (?:meu )?quarto)?', s)
    if m: return ('controlar_luz', {'acao': 'ligar' if m[1] in {'liga','ligue','ligar','acende','acenda'} else 'desligar'})
    return None


def context_allows(history):
    recent = [m for m in (history or []) if m.get('role') in {'user','assistant'}][-2:]
    for message in recent:
        text = normalize(str(message.get('content','')))
        if (message.get('role') == 'assistant' and '?' in text) or re.search(
                r'\b(exemplo|citacao|hipotese|repita|digite|escreva)\b|(?:nome|texto|rotulo) (?:do|de um|desse) (?:botao|comando|campo)',text):
            return False
    return True


def try_execute(text, execute, progress=None, history=None):
    if not context_allows(history): return None
    action = parse(text)
    if action is None: return None
    name,args = action
    if progress: progress('ferramenta',dict(nome=name,args=args))
    # Always uses the existing permission/result pipeline. No fallback that
    # repeats an action if an executor times out or reports a failure.
    result = execute(name,args)
    if progress: progress('resultado',dict(nome=name,resultado=result.texto,ok=result.ok))
    return result.texto
