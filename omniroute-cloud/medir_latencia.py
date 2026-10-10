#!/usr/bin/env python3
"""Comparação exploratória sequencial, sem registrar chaves ou conversas pessoais."""
import argparse
import json
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.request


def medir(base, key, model, prompt):
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': True,
        'max_tokens': 128,
        'reasoning_effort': 'low',
    }
    req = urllib.request.Request(base.rstrip('/') + '/chat/completions',
        data=json.dumps(payload).encode(), headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
        })
    start = time.perf_counter()
    first = None
    chars = 0
    finished = False
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            for line in response:
                if not line.startswith(b'data:'):
                    continue
                data = line[5:].strip()
                if data == b'[DONE]':
                    finished = True
                    break
                event = json.loads(data)
                if event.get('error'):
                    return {'ok': False, 'error': 'erro no stream do provedor'}
                for choice in event.get('choices', []):
                    text = choice.get('delta', {}).get('content')
                    if isinstance(text, str) and text:
                        if first is None:
                            first = time.perf_counter() - start
                        chars += len(text)
                    if choice.get('finish_reason'):
                        finished = True
        return {'ok': bool(chars and finished), 'first_text_s': first,
                'total_s': time.perf_counter() - start, 'chars': chars,
                'finished': finished}
    except urllib.error.HTTPError as error:
        return {'ok': False, 'error': f'HTTP {error.code}'}
    except (OSError, ValueError) as error:
        return {'ok': False, 'error': type(error).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-env', type=Path, required=True)
    parser.add_argument('--cloud-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    env = {}
    for line in args.local_env.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    targets = {
        'local': (env['EMILY_PROVEDOR_OPENAI_BASE'], env['EMILY_PROVEDOR_OPENAI_CHAVE']),
        'nuvem': ('https://emily-hiucksam.duckdns.org/v1',
                  json.loads(args.cloud_key.read_text())['key']),
    }
    prompts = [
        'Em português e em até 35 palavras, explique por que o céu parece azul.',
        'Em português e em até 35 palavras, explique como um cache ajuda um aplicativo.',
        'Em português e em até 35 palavras, sugira uma pausa rápida para relaxar após estudar.',
    ]
    rows = []
    for model in ['cx/gpt-6-sol', 'cx/gpt-6-luna', 'cx/gpt-6-astra']:
        for index, prompt in enumerate(prompts):
            order = ['local', 'nuvem'] if index % 2 == 0 else ['nuvem', 'local']
            for target in order:
                base, key = targets[target]
                result = {'model': model, 'target': target, 'round': index + 1,
                          **medir(base, key, model, prompt)}
                rows.append(result)
                args.output.write_text(json.dumps(rows, indent=2))
                print(json.dumps(result), flush=True)
                if not result['ok']:
                    # Um bloqueio de conta/modelo não deve consumir repetidamente a cota.
                    break
    print('MEDIANAS (amostra pequena; esforço low; novas conexões):', flush=True)
    for model in sorted({r['model'] for r in rows}):
        for target in targets:
            sample = [r for r in rows if r['model'] == model and r['target'] == target and r['ok']]
            if sample:
                print(model, target, 'n=', len(sample),
                      'primeiro texto=', round(statistics.median(r['first_text_s'] for r in sample), 3),
                      'total=', round(statistics.median(r['total_s'] for r in sample), 3), flush=True)


if __name__ == '__main__':
    main()
