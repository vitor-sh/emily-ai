"""Direções Fish S2.1 compartilhadas pelo prompt, TTS e apresentação."""
import re

CONTROLE_VOZ = """
<controle_de_voz_fish_audio>
Sua fala usa Fish Audio S2.1 Pro. Escreva português brasileiro conversacional,
com pontuação e ritmo naturais, mantendo sua personalidade. Ao responder por voz,
direcione a interpretação com uma tag curta quando ela melhorar o sentido:
[warm, conversational], [playful], [curious], [confident], [excited],
[empathetic, soft voice], [relieved] ou [serious, calm]. Escolha pelo contexto;
um aviso sério não ganha risada, e uma dúvida técnica não precisa de euforia.

As direções ficam entre colchetes, imediatamente ANTES do trecho que afetam.
Prefira estas formas documentadas: [whispering], [soft voice], [laughing],
[chuckling], [sigh], [gasp], [short pause], [pause], [long pause], [emphasis].
Descrições curtas também funcionam, como [speaking slowly, almost hesitant].
Combine um estilo físico com uma emoção coerente só quando útil, por exemplo
[whispering, curious]. Comece simples: normalmente uma ou duas direções numa
resposta curta, acrescentando outra apenas quando houver mudança real de tom.
Não junte ordens contraditórias nem transforme a conversa numa encenação.

Risadas e suspiros são eventos pontuais; não repita em toda frase. [emphasis]
afeta a palavra seguinte. Uma direção de tom vale para o trecho seguinte; se
mudar de sentimento, marque o novo tom, por exemplo [serious, calm]. Toda tag
precisa de texto depois: nunca termine só com uma tag. Para rir na fala use
[chuckling] ou [laughing], em vez de escrever kkkkk/hahaha para o sintetizador.
Não narre ações com asteriscos, não use maiúsculas para tentar gritar, e não
pronuncie nem explique as tags. Elas são instruções do áudio, ocultas no chat.

Exemplos de interpretação, não frases a repetir:
[curious] Pera, o que aconteceu depois?
[playful] Você conseguiu quebrar isso de novo? [chuckling] Tá, vamos arrumar.
[excited] Agora sim, funcionou!
[empathetic, soft voice] Poxa, eu entendo. Vamos com calma.
[whispering, curious] Psiu, olha isso aqui.
Deixa eu pensar... [short pause] acho que encontrei o problema.
Isso precisa ser feito [emphasis] antes de reiniciar.
</controle_de_voz_fish_audio>
""".strip()

CONHECIDAS = set('excited sad angry nervous scared curious confident surprised whisper whispering shouting screaming laughs laughing chuckling sigh sighing pause sobbing emphasis inhale exhale gasp panting giggle crying groan relieved embarrassed grateful empathetic friendly conversational breathy soft tender tired'.split()) | {'short pause', 'long pause', 'soft voice', 'loud voice', 'low voice', 'clear throat', 'clears throat', 'speaking slowly', 'in a hurry tone'}
LIVRE = re.compile(r'^(?:speaking|sighing|sighs|sigh|sobbing|chuckling|gasping|hesitating|breathing|pausing|pause|whispering|whisper|shouting|screaming|laughing|laughs|laugh|crying|smiling|nodding|tilting|exclaiming|mumbling|sniffling|stuttering|trailing|curious|cheerful|excited|sad|angry|nervous|scared|confident|surprised|calm|sarcastic|teasing|warm|cold|soft|firm|gentle|serious|playful|mocking|smooth|friendly|empathetic|relieved|grateful|embarrassed|conversational|breathy|tender|tired|dead tired|professional|low voice|loud voice|voice breaking|voice rough|pitch up|pitch down|short pause|long pause|emphasis|inhale|exhale|gasp|panting|giggle|groan|clear throat|clears throat|falando|rindo|hesitando|sussurrando|gritando|chorando|suspirando|pausa|calma|com (?:um |uma )?tom|(?:with|in) (?:a |an )?.*tone\b|(?:emotion|tone|style|mood|voice)\s*[:=])\b', re.I)
TAG = re.compile(r'\[([^\]\r\n]{1,80})\]')
ALIASES = {'whisper':'whispering', 'laugh':'laughing', 'laughs':'laughing', 'sighs':'sigh', 'sighing':'sigh', 'gasping':'gasp'}
EVENTOS = ('pause', 'short pause', 'long pause', 'pausa', 'laugh', 'rindo', 'chuckling', 'giggle', 'sigh', 'suspirando', 'gasp', 'inhale', 'exhale', 'panting', 'breathing', 'clear throat', 'clears throat', 'groan', 'nodding', 'tilting', 'smiling', 'hesitating', 'hesitando', 'emphasis')


def eh_tag_fish(conteudo):
    tag = (conteudo or '').strip().lower()
    return 0 < len(tag) <= 80 and (tag in CONHECIDAS or bool(LIVRE.match(tag)))


def tag_fish_persistente(conteudo):
    tag = (conteudo or '').strip().lower()
    return eh_tag_fish(tag) and not tag.startswith(EVENTOS)


def normalizar_tags(texto):
    return TAG.sub(lambda m: '[' + ALIASES.get(m[1].strip().lower(), m[1].strip()) + ']' if eh_tag_fish(m[1]) else m[0], texto or '')


def remover_tags_fish(texto):
    limpo = TAG.sub(lambda m: '' if eh_tag_fish(m[1]) else m[0], texto or '')
    return re.sub(r'\s+([,.!?…])', r'\1', re.sub(r'[ \t]{2,}', ' ', limpo)).strip()


def preparar_expressoes(texto):
    texto = normalizar_tags(texto)
    # Um stream interrompido pode terminar dentro de uma direção.
    aberto = texto.rfind('[')
    if aberto > texto.rfind(']') and eh_tag_fish(texto[aberto+1:]):
        texto = texto[:aberto].rstrip()
    # Risada escrita vira um evento, sem somar duas risadas se já há direção.
    tem_risada = any(m[1].strip().lower().startswith(('laugh', 'chuckling', 'giggle', 'rindo')) for m in TAG.finditer(texto))
    convertido = False
    def risada(_):
        nonlocal convertido
        if tem_risada or convertido:
            return ''
        convertido = True
        return '[chuckling]'
    return re.sub(r'\b(?:k{2,}|(?:ha){2,}h?|(?:rs){2,})\b', risada, texto, flags=re.I)


class DirecaoDaFala:
    """Estado por resposta, antes do prefetch; nunca compartilhado entre turnos."""
    def __init__(self):
        self.ativas = []

    def aplicar(self, texto):
        texto = normalizar_tags(texto).strip()
        if not remover_tags_fish(texto):
            return ''
        original = texto
        tags = [m for m in TAG.finditer(original) if eh_tag_fish(m[1])]
        inicio = []
        restante = texto
        while (m := TAG.match(restante)) and eh_tag_fish(m[1]):
            inicio.append(m[1]); restante = restante[m.end():].lstrip()
        if self.ativas and not any(tag_fish_persistente(t) for t in inicio):
            texto = ' '.join('['+t+']' for t in self.ativas) + ' ' + texto
        grupo = []
        fim = None
        for m in tags:
            if tag_fish_persistente(m[1]):
                # Adjacent emotion/style directives belong to the same direction.
                if fim is not None and original[fim:m.start()].strip():
                    grupo = []
                grupo.append(m[1].strip())
                self.ativas = grupo[-2:]
                fim = m.end()
        return texto

