#!/usr/bin/env python3
"""Prepara somente esta pasta; não toca na instalação local da Emily."""
import argparse
import os
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parent


def validar_dominio(value):
    value = value.strip().lower().rstrip('.')
    labels = value.split('.')
    if (len(labels) < 2 or len(value) > 253 or
            all(label.isdigit() for label in labels) or
            any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                for label in labels)):
        raise ValueError('Informe apenas um domínio DNS, sem https, porta ou caminho.')
    return value


def preparar(root, domain):
    domain = validar_dominio(domain)
    content = '\n'.join([
        f'DOMAIN={domain}',
        f'JWT_SECRET={secrets.token_hex(48)}',
        f'API_KEY_SECRET={secrets.token_hex(32)}',
        f'STORAGE_ENCRYPTION_KEY={secrets.token_hex(32)}',
        'STORAGE_ENCRYPTION_KEY_VERSION=v1',
        f'INITIAL_PASSWORD={secrets.token_hex(24)}', '',
    ])
    # O_EXCL impede sobrescrever os segredos e perder acesso ao banco existente.
    fd = os.open(root / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dominio')
    args = parser.parse_args()
    try:
        preparar(ROOT, args.dominio)
    except (ValueError, FileExistsError) as error:
        parser.exit(1, f'Não foi alterado nada: {error}\n')
    print('Configuração criada com permissão 600. Segredos não foram exibidos.')
    print('Próximo passo: docker compose config --quiet && docker compose up -d')
