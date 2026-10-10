import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

import preparar
import verificar
import backup as backup_module

ROOT = Path(__file__).resolve().parent


class ConfigTest(unittest.TestCase):
    def test_segredos_privados_e_nao_sobrescritos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preparar.preparar(root, 'Modelos.Example.com')
            path = root / '.env'
            original = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn(b'DOMAIN=modelos.example.com', original)
            with self.assertRaises(FileExistsError):
                preparar.preparar(root, 'outro.example.com')
            self.assertEqual(path.read_bytes(), original)

    def test_dominios_invalidos_nao_criam_arquivo(self):
        for domain in ['https://example.com', 'example.com/x', 'example.com:443',
                       '127.0.0.1', '-app.example.com', 'example.com\nJWT_SECRET=evil']:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    preparar.preparar(Path(tmp), domain)
                self.assertFalse((Path(tmp) / '.env').exists())

    def test_verificacao_rejeita_api_sem_autenticacao(self):
        def response(base, path, key=None, payload=None):
            if path == '/healthz':
                return 200, b'{}'
            if path.startswith('/v1/'):
                return 200, b'{"data": []}'
            return 404, b''
        with patch.object(verificar, 'consultar', side_effect=response):
            with self.assertRaisesRegex(AssertionError, 'Autenticação'):
                verificar.verificar('https://example.com', 'test')

    def test_backup_retoma_apos_falha_e_nao_deixa_arquivo_parcial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text('segredo')
            calls = []
            def compose(*args):
                calls.append(args)
                return 'container-teste' if args[0] == 'ps' else ''
            with patch.object(backup_module, 'ROOT', root), \
                    patch.object(backup_module, 'compose', side_effect=compose), \
                    patch.object(subprocess, 'check_output', return_value='true'), \
                    patch.object(subprocess, 'run', side_effect=RuntimeError('copia falhou')):
                with self.assertRaises(RuntimeError):
                    backup_module.backup()
            self.assertIn(('stop', 'omniroute'), calls)
            self.assertEqual(calls[-1], ('start', 'omniroute'))
            self.assertEqual(list((root / 'backups').glob('*.tar.gz')), [])


@unittest.skipUnless(os.environ.get('CLOUD_CONTAINER_TEST'), 'Ative CLOUD_CONTAINER_TEST=podman ou docker')
class ContainerTest(unittest.TestCase):
    def test_proxy_real_auth_painel_e_reinicio(self):
        engine = os.environ['CLOUD_CONTAINER_TEST']
        name = 'emily-cloud-test-' + uuid.uuid4().hex[:10]
        network, omni, proxy = name + '-net', name + '-omni', name + '-proxy'
        def run(*args):
            return subprocess.check_output([engine, *args], text=True, stderr=subprocess.PIPE).strip()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preparar.preparar(root, 'modelos.example.com')
            conf = root / 'Caddyfile'
            conf.write_text((ROOT / 'Caddyfile').read_text().replace('{$DOMAIN}', ':80'))
            try:
                run('network', 'create', network)
                run('run', '-d', '--name', omni, '--network', network, '--network-alias', 'omniroute',
                    '--env-file', str(root / '.env'), '-e', 'REQUIRE_API_KEY=true',
                    '-e', 'DATA_DIR=/app/data', '-e', 'PORT=20128', '-e', 'HOSTNAME=0.0.0.0',
                    '-e', 'NODE_OPTIONS=--max-old-space-size=1024',
                    'docker.io/diegosouzapw/omniroute:3.8.51')
                run('run', '-d', '--name', proxy, '--network', network, '-p', '127.0.0.1::80',
                    '-v', f'{conf}:/etc/caddy/Caddyfile:ro,Z', 'docker.io/library/caddy:2.10.2-alpine')
                address = run('port', proxy, '80/tcp')
                base = 'http://' + address
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        if verificar.consultar(base, '/healthz')[0] == 200:
                            break
                    except OSError:
                        pass
                    time.sleep(1)
                self.assertEqual(verificar.consultar(base, '/healthz')[0], 200)
                for path in ['/', '/dashboard', '/api/settings', '/api/providers']:
                    self.assertEqual(verificar.consultar(base, path)[0], 404)
                for key in [None, 'invalid-test-key']:
                    status, _ = verificar.consultar(base, '/v1/chat/completions', key, {
                        'model': 'test', 'messages': [{'role': 'user', 'content': 'test'}]})
                    self.assertIn(status, [401, 403])
                run('restart', '--time', '45', omni)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if verificar.consultar(base, '/healthz')[0] == 200:
                        break
                    time.sleep(1)
                self.assertEqual(verificar.consultar(base, '/healthz')[0], 200)
            finally:
                for container in [proxy, omni]:
                    subprocess.run([engine, 'rm', '-f', '-v', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([engine, 'network', 'rm', network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
