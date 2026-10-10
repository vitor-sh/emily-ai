#!/usr/bin/env python3
"""Confere HTTPS, painel fechado e autenticação antes de migrar a Emily."""
import argparse
import getpass
import json
import urllib.error
import urllib.parse
import urllib.request


def consultar(base, path, key=None, payload=None):
    headers = {'Accept': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read()


def verificar(base, key, model=None):
    assert consultar(base, '/healthz')[0] == 200, 'Servidor não está pronto'
    for path in ['/', '/dashboard', '/api/settings', '/api/providers']:
        assert consultar(base, path)[0] == 404, 'Painel/administração expostos'
    for invalid in [None, 'chave-invalida-de-teste']:
        status, _ = consultar(base, '/v1/chat/completions', invalid, {
            'model': model or 'teste-autenticacao',
            'messages': [{'role': 'user', 'content': 'teste'}],
        })
        assert status in (401, 403), f'Autenticação não rejeitou acesso ({status})'
    status, body = consultar(base, '/v1/models', key)
    assert status == 200, f'Consulta autenticada falhou ({status})'
    assert isinstance(json.loads(body).get('data'), list), 'Resposta de modelos inválida'
    if model:
        status, body = consultar(base, '/v1/chat/completions', key, {
            'model': model, 'messages': [{'role': 'user', 'content': 'Responda apenas OK.'}],
            'max_tokens': 16, 'stream': False,
        })
        assert status == 200 and json.loads(body).get('choices'), f'Modelo falhou ({status})'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--modelo', help='Opcional: faz uma geração curta, consumindo cota do provedor')
    args = parser.parse_args()
    url = args.url.rstrip('/')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        parser.exit(1, 'Informe uma origem HTTPS válida, sem caminho ou credenciais.\n')
    try:
        key = getpass.getpass('Chave de API criada no painel (não será exibida): ')
        if not key.strip():
            raise ValueError('Chave vazia')
        verificar(url, key, args.modelo)
    except (AssertionError, ValueError, OSError, urllib.error.URLError) as error:
        parser.exit(1, f'Verificação falhou: {error}\n')
    print('Verificação concluída. HTTPS, isolamento do painel e API conferidos.')
