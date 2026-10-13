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

LIGAR = {'liga', 'ligue', 'ligar', 'acende', 'acenda'}

# Cores faladas -> nome que o casa_inteligente conhece. Feminino e masculino.
CORES = {'vermelha': 'vermelho', 'vermelho': 'vermelho', 'laranja': 'laranja',
         'amarela': 'amarelo', 'amarelo': 'amarelo', 'verde': 'verde', 'ciano': 'ciano',
         'azul': 'azul', 'roxa': 'roxo', 'roxo': 'roxo', 'lilas': 'lilás', 'violeta': 'violeta',
         'rosa': 'rosa', 'pink': 'pink', 'magenta': 'magenta', 'branca': 'branca',
         'branco': 'branca', 'quente': 'quente', 'fria': 'fria', 'amarelada': 'amarelada'}

# Aparelhos que vão na tomada inteligente. Lista fechada de propósito: "liga a
# TV", "desliga a música" ou "liga o bluetooth" não podem virar corte de energia.
APARELHOS = {'ventilador': 'ventilador', 'air fryer': 'air fryer', 'airfryer': 'air fryer',
             'air fry': 'air fryer', 'fritadeira': 'air fryer', 'ar condicionado': 'ar condicionado',
             'aquecedor': 'aquecedor', 'cafeteira': 'cafeteira', 'chaleira': 'chaleira',
             'abajur': 'abajur', 'luminaria': 'luminária', 'umidificador': 'umidificador',
             'purificador': 'purificador'}


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
    luz = r'(?:a |minha |a minha )?(?:luz|lampada)(?: do (?:meu )?quarto)?'
    m = re.fullmatch(r'(liga|ligue|ligar|acende|acenda|desliga|desligue|desligar|apaga|apague) ' + luz, s)
    if m: return ('controlar_luz', {'acao': 'ligar' if m[1] in LIGAR else 'desligar'})
    # "luz azul", "deixa a luz roxa", "muda a luz pra verde", "luz quente"
    m = re.fullmatch(r'(?:(?:deixa|deixe|coloca|coloque|poe|ponha|muda|mude|troca|troque) )?' + luz
                     + r' (?:(?:em|pra|para|no|na) )?(' + '|'.join(CORES) + r')', s)
    if m: return ('controlar_luz', {'acao': 'cor', 'cor': CORES[m[1]]})
    # "luz no 40", "brilho da luz em 70%", "luz 30 por cento"
    m = re.fullmatch(r'(?:(?:deixa|deixe|coloca|coloque|poe|ponha|muda|mude) )?(?:(?:o )?brilho d)?' + luz
                     + r' (?:(?:em|pra|para|no|na) )?(\d{1,3}) ?(?:%|por cento)?', s)
    if m and 1 <= int(m[1]) <= 100: return ('controlar_luz', {'acao': 'brilho', 'brilho': int(m[1])})
    # Tomada: só aparelhos conhecidos e só ligar/desligar. O PC fica de fora
    # ("desliga o PC" desliga o sistema); a trava do PC mora em controlar_tomada.
    m = re.fullmatch(r'(liga|ligue|ligar|desliga|desligue|desligar) (?:o |a |meu |minha |o meu |a minha )?(' + '|'.join(APARELHOS) + r')', s)
    if m: return ('controlar_tomada', {'acao': 'ligar' if m[1] in LIGAR else 'desligar', 'aparelho': APARELHOS[m[2]]})
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
