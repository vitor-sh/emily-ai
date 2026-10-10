import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests
from relay import create_app, make_pair, database, digest

class RelayTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg=dict(data_dir=self.tmp.name,public_base='https://example.com/bridge',pc_url='http://127.0.0.1:15000',pc_token='pc-secret',omni_url='http://127.0.0.1:20128/v1',omni_key='model-secret')
        self.app=create_app(self.cfg);self.c=self.app.test_client()
        code=make_pair(self.cfg)
        result=self.c.post('/pair/claim',json=dict(code=code,label='Teste')).get_json()
        self.token=result['token'];self.id=result['device_id'];self.h={'Authorization':'Bearer '+self.token}
    def test_authentication_and_revocation(self):
        self.assertEqual(self.c.get('/gateway/endpoint').status_code,401)
        self.assertEqual(self.c.get('/gateway/endpoint',headers=self.h).status_code,200)
        with database(self.cfg) as db:db.execute('UPDATE devices SET revoked=1 WHERE id=?',(self.id,))
        self.assertEqual(self.c.get('/gateway/endpoint',headers=self.h).status_code,401)
    def test_code_is_one_use_expiring_and_rate_limited(self):
        code=make_pair(self.cfg)
        self.assertEqual(self.c.post('/pair/claim',json=dict(code=code)).status_code,200)
        self.assertEqual(self.c.post('/pair/claim',json=dict(code=code)).status_code,400)
        code=make_pair(self.cfg)
        with database(self.cfg) as db:db.execute('UPDATE pairing SET expires=0 WHERE code_hash=?',(digest(code),))
        self.assertEqual(self.c.post('/pair/claim',json=dict(code=code)).status_code,400)
        for _ in range(10):r=self.c.post('/pair/claim',json=dict(code='wrong'))
        self.assertEqual(r.status_code,429)
    def test_update_and_range_work_with_pc_offline(self):
        folder=Path(self.tmp.name)/'updates';folder.mkdir();(folder/'emily-48.apk').write_bytes(b'0123456789')
        (folder/'latest.json').write_text(json.dumps(dict(version_code=48,size=10,sha256='a'*64)))
        self.assertEqual(self.c.get('/android/update',headers=self.h).get_json()['version_code'],48)
        with patch('relay.requests.request',side_effect=requests.ConnectionError):
            r=self.c.get('/pc/status',headers=self.h);self.assertEqual(r.status_code,503)
            r=self.c.get('/android/update/apk?version=48',headers={**self.h,'Range':'bytes=2-4'})
            self.assertEqual(r.status_code,206);self.assertEqual(r.data,b'234');r.close()
        self.assertEqual(self.c.get('/android/update/apk?version=../../etc/passwd',headers=self.h).status_code,404)
    def test_stream_and_upstream_credentials_are_separate(self):
        class Upstream:
            status_code=200;headers={'Content-Type':'text/event-stream'};closed=False
            def iter_content(self,chunk_size):yield b'data: one\n\n';yield b'data: [DONE]\n\n'
            def iter_lines(self,chunk_size):yield b'data: one';yield b'';yield b'data: [DONE]';yield b''
            def close(self):self.closed=True
        for path,key in [('/pc/status','pc-secret'),('/v1/chat/completions','model-secret')]:
            u=Upstream()
            with patch('relay.requests.request',return_value=u) as call:
                r=self.c.post(path,headers=self.h,json={}) if 'v1/' in path else self.c.get(path,headers=self.h)
                self.assertIn(b'[DONE]',r.data);r.close();self.assertTrue(u.closed)
                self.assertEqual(call.call_args.kwargs['headers']['Authorization'],'Bearer '+key)
                self.assertFalse(call.call_args.kwargs['allow_redirects'])
        self.assertEqual(self.c.get('/v1/api/providers',headers=self.h).status_code,404)

    def test_pc_action_offline_is_bounded_and_never_sent(self):
        with patch('relay.requests.get',side_effect=requests.ReadTimeout) as health, patch('relay.requests.request') as action:
            response=self.c.post('/pc/action',headers=self.h,json={'action':'preparar_energia'})
            self.assertEqual(response.status_code,503)
            self.assertIn('Nenhuma ação',response.get_json()['erro'])
            self.assertEqual(health.call_args.kwargs['timeout'],(1,2))
            action.assert_not_called()

    def test_pc_action_is_forwarded_only_once_after_health(self):
        from unittest.mock import MagicMock
        health=MagicMock();health.__enter__.return_value.status_code=200
        action=MagicMock(status_code=200,headers={'Content-Type':'application/json'})
        action.iter_content.return_value=iter([b'{"ok":true}'])
        with patch('relay.requests.get',return_value=health),patch('relay.requests.request',return_value=action) as forwarded:
            response=self.c.post('/pc/action',headers=self.h,json={'action':'apps_listar'})
            self.assertTrue(response.get_json()['ok']);response.close()
            self.assertEqual(forwarded.call_count,1)

    def test_sse_delivers_first_event_before_upstream_finishes(self):
        # Servidor HTTP real sem chunked: regressão que mocks de iter_content
        # não detectam. O segundo evento só sai DEPOIS de recebermos o primeiro.
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        release=threading.Event();finished=threading.Event()
        first=b'data: first\n\n';last=b'data: [DONE]\n\n'
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(first)+len(last)));self.end_headers()
                self.wfile.write(first);self.wfile.flush()
                release.wait(3)
                finished.set();self.wfile.write(last);self.wfile.flush()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            cfg={**self.cfg,'omni_url':f'http://127.0.0.1:{server.server_port}/v1'}
            response=create_app(cfg).test_client().post('/v1/chat/completions',headers=self.h,json={},buffered=False)
            stream=iter(response.response)
            self.assertEqual(next(stream),b'data: first\n')
            self.assertFalse(finished.is_set(),"SSE reteve o primeiro evento até o fim da resposta");release.set()
            self.assertIn(b'[DONE]',b''.join(stream));response.close()
        finally:
            release.set();server.shutdown();server.server_close();thread.join(3)

    def test_only_publisher_can_upload_and_signed_viewer_does_not_gain_owner_auth(self):
        self.cfg['upload_key']='publish-secret'
        app=create_app(self.cfg);client=app.test_client()
        path='/admin/uploads/'+'a'*64+'/0'
        self.assertEqual(client.post(path,headers=self.h,data=b'test').status_code,401)
        self.assertEqual(client.post(path,headers={'Authorization':'Bearer publish-secret'},data=b'test').status_code,200)
        self.assertEqual((Path(self.tmp.name)/'incoming'/('a'*64)/'0').read_bytes(),b'test')
        class Denied:
            status_code=401;headers={'Content-Type':'application/json'}
            def iter_content(self,chunk_size):yield b'{"erro":"token invalido"}'
            def close(self):pass
        with patch('relay.requests.request',return_value=Denied()) as forward:
            response=client.get('/cloud/content/item?sig='+'a'*64+'&exp=9999999999')
            self.assertEqual(response.status_code,401);response.close()
            self.assertNotIn('Authorization',forward.call_args.kwargs['headers'])
        self.assertEqual(client.get('/cloud/items?sig='+'a'*64+'&exp=9999999999').status_code,401)

    def test_two_simultaneous_claims_cannot_share_a_code(self):
        from concurrent.futures import ThreadPoolExecutor
        code=make_pair(self.cfg)
        def claim(_):
            with self.app.test_client() as client:return client.post('/pair/claim',json=dict(code=code)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(claim,range(2)))
        self.assertEqual(sorted(results),[200,400])

if __name__=='__main__':unittest.main()

class TurnCredentialTests(unittest.TestCase):
    def test_credentials_require_paired_device_and_expire_without_secret(self):
        import base64,hmac,hashlib,time
        with tempfile.TemporaryDirectory() as folder:
            cfg=dict(data_dir=folder,pc_url='http://127.0.0.1:1',pc_token='pc',public_base='https://test',
                     turn={'host':'163.176.97.174','secret':'private-test-secret'})
            client=create_app(cfg).test_client()
            assert client.get('/tela/rtc/config').status_code==401
            code=make_pair(cfg);key=client.post('/pair/claim',json={'code':code}).get_json()['token']
            response=client.get('/tela/rtc/config',headers={'Authorization':'Bearer '+key})
            data=response.get_json();server=data['ice_servers'][1]
            assert 3500<int(server['username'].split(':')[0])-time.time()<3700
            expected=base64.b64encode(hmac.new(b'private-test-secret',server['username'].encode(),hashlib.sha1).digest()).decode()
            assert server['credential']==expected
            assert b'private-test-secret' not in response.data
