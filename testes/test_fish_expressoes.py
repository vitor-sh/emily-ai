import queue
import pytest
from fish_voz_texto import DirecaoDaFala, preparar_expressoes, remover_tags_fish, tag_fish_persistente

@pytest.mark.parametrize('tag', ['friendly, warm','empathetic, soft voice','emphasis','inhale','exhale','gasp','clears throat','short pause','low voice','voice rough from crying, trying to sound normal','professional broadcast tone','dead tired, end of a very long shift','whispering, curious'])
def test_tags_documentadas_ocultas_mas_preservadas_no_audio(tag):
    import modelo, interface_web
    bruto=f'[{tag}] Oi, veja [1] e [documentação].'
    assert f'[{tag}]' in modelo.limpar_para_tts(bruto)
    assert remover_tags_fish(bruto) == 'Oi, veja [1] e [documentação].'
    assert interface_web._texto_visual_sem_tags_de_voz(bruto).strip() == 'Oi, veja [1] e [documentação].'


def test_direcao_por_resposta_mantem_emocao_e_estilo_sem_repetir_eventos():
    d=DirecaoDaFala()
    assert d.aplicar('[scared] [whisper] Psiu.') == '[scared] [whispering] Psiu.'
    assert d.aplicar('[chuckling] Agora olha.') == '[scared] [whispering] [chuckling] Agora olha.'
    assert d.aplicar('[serious, calm] Vamos continuar.') == '[serious, calm] Vamos continuar.'
    assert d.aplicar('Isso é [emphasis] importante.') == '[serious, calm] Isso é [emphasis] importante.'
    assert d.aplicar('E depois reinicie.') == '[serious, calm] E depois reinicie.'
    assert DirecaoDaFala().aplicar('Outro turno.') == 'Outro turno.'
    assert not tag_fish_persistente('long pause')
    assert not tag_fish_persistente('emphasis')
    assert not tag_fish_persistente('gasp')


def test_risada_escrita_vira_acao_uma_vez_sem_duplicar_tag():
    assert preparar_expressoes('Poxa kkkkk, hahaha.') .count('[chuckling]') == 1
    assert preparar_expressoes('[laughs] Poxa kkkkk.') == '[laughing] Poxa .'


def test_deltas_nao_dividem_direcoes_e_nao_perdem_tom():
    from modelo import _AcumuladorDeFrases
    fila=queue.Queue();a=_AcumuladorDeFrases(fila)
    tag='[speaking slowly, almost hesitant]'
    for delta in (tag[:15],tag[15:]+ ' '+ 'palavra '*35, ' e mais uma parte para encerrar a resposta.'):
        a.adicionar(delta)
    a.finalizar();partes=[]
    while not fila.empty():partes.append(fila.get())
    assert len(partes)>=2
    assert all(p.startswith(tag) for p in partes)
    assert all(p.count('[')==p.count(']') for p in partes)


def test_apenas_direcao_nao_vira_request_de_audio():
    assert DirecaoDaFala().aplicar('[excited]') == ''


def test_stream_interrompido_na_tag_nao_pronuncia_direcao():
    import modelo
    assert modelo.limpar_para_tts('Tudo bem. [speaking slowly, almost') == 'Tudo bem.'
    assert modelo.limpar_para_tts('Veja [documentação') == 'Veja [documentação'
