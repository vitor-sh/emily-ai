"""Comparação opt-in com modelo real; somente imagens sintéticas, sem cliques.

Chamadas consomem a cota do provedor configurado. Não muda preferências salvas.
Uso: python3 testes/benchmark_agente_ui_latencia.py --baseline CAMINHO/modelo.py --output resultado.jsonl
"""
import argparse
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_agente_visual_gpt6 as bench
import config_agente_visual
import modelo


def carregar_decisor_anterior(path):
    arvore = ast.parse(path.read_text())
    funcao = next(no for no in arvore.body if isinstance(no, ast.FunctionDef) and no.name == 'decidir_proxima_acao_ui')
    # Reutiliza as dependências atuais: compara apenas a montagem antiga do prompt.
    ambiente = dict(vars(modelo))
    exec(compile(ast.Module(body=[funcao], type_ignores=[]), str(path), 'exec'), ambiente)
    return ambiente['decidir_proxima_acao_ui']


def executar(baseline, output):
    atual = modelo.decidir_proxima_acao_ui
    anterior = carregar_decisor_anterior(baseline)
    config = config_agente_visual.configuracao()
    if config['provedor'] != 'openai':
        raise RuntimeError('Este benchmark usa o adaptador OpenAI; não muda o provedor escolhido.')
    resultados = []
    try:
        for rodada in range(2):
            # Alterna a ordem para reduzir viés de aquecimento/carga do provedor.
            fases = [('before', anterior), ('after', atual)]
            if rodada:
                fases.reverse()
            for caso in ['calendario', 'micro', 'verificacao_micro']:
                for fase, decisor in fases:
                    modelo.decidir_proxima_acao_ui = decisor
                    if caso == 'verificacao_micro':
                        dado = bench.executar_verificacao(config['modelo'], config['raciocinio'])
                    else:
                        dado = bench.executar(caso, config['modelo'], config['raciocinio'])
                    dado.update(phase=fase,round=rodada)
                    resultados.append(dado)
                    with output.open('a') as arq:
                        arq.write(json.dumps(dado, ensure_ascii=False) + '\n')
                    print(json.dumps(dado, ensure_ascii=False), flush=True)
    finally:
        modelo.decidir_proxima_acao_ui = atual
    return resultados


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    executar(args.baseline, args.output)
