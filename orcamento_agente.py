"""Continuidade orientada a atividade, sem teto total para tarefas em progresso."""
import json
import time


def trabalho_ativo(nome, texto):
    # Só o status estruturado do executor conta como espera. Texto livre,
    # uma prévia aberta ou uma promessa do modelo não renovam o orçamento.
    if nome not in {'programacao_status', 'pc_programacao_status'}:
        return False
    try:
        dados = json.loads(texto)
        dados = dados.get('publicacao') or dados
        return (dados.get('ok') is True and bool(dados.get('trabalho'))
                and dados.get('estado') in {'iniciando', 'executando'})
    except (ValueError, TypeError, AttributeError):
        return False


class OrcamentoAgente:
    def __init__(self, *, clock=time.monotonic, repeticoes=8, inatividade=600):
        self.clock = clock
        self.repeticoes = repeticoes
        self.inatividade = inatividade
        self.ultima_atividade = clock()
        self.vistas = set()
        self.sem_avanco = 0

    def registrar(self, evidencias, *, aguardando=False):
        novas = set(evidencias) - self.vistas
        self.vistas.update(evidencias)
        if novas or aguardando:
            self.sem_avanco = 0
            self.ultima_atividade = self.clock()
        else:
            self.sem_avanco += 1
        return bool(novas)

    def interromper(self):
        return (self.sem_avanco >= self.repeticoes or
                self.clock() - self.ultima_atividade >= self.inatividade)

    @property
    def motivo(self):
        if self.sem_avanco >= self.repeticoes:
            return 'As mesmas tentativas se repetiram sem nova evidência ou processo ativo.'
        return 'Não houve atividade confirmada durante a janela de recuperação.'
