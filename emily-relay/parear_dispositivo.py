"""Gera somente um código temporário; credenciais permanentes não são exibidas."""
from pathlib import Path
import subprocess

def gerar_codigo():
    command=['ssh','-i',str(Path.home()/'.ssh/emily-oracle-ed25519'),'-o','BatchMode=yes','-o','ConnectTimeout=8','ubuntu@163.176.97.174',
        '/home/ubuntu/emily-relay/.venv/bin/python /home/ubuntu/emily-relay/relay.py pair']
    result=subprocess.run(command,capture_output=True,text=True,timeout=15,check=True)
    code=result.stdout.strip()
    if len(code)!=8 or not code.isalnum():raise ValueError('Resposta de pareamento inválida')
    return code

if __name__=='__main__':
    try:
        code=gerar_codigo()
        print('\nCódigo para conectar à Emily: '+code[:4]+'-'+code[4:])
        print('Válido por 10 minutos, para um dispositivo.\nNo celular: Configurações → Emily do PC → Código de conexão.\n')
    except Exception:
        print('Não foi possível gerar o código. Verifique a conexão com a internet e a Oracle.')
    input('Pressione Enter para fechar. ')
