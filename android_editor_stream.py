"""Continuous USB video with a private, bounded localhost MJPEG transport."""
import secrets, subprocess, threading, time, shutil, re, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class PreviewStream:
    def __init__(self, adb, serial):
        self.adb,self.serial=adb,serial
        self.token=secrets.token_urlsafe(32);self.condition=threading.Condition()
        self.frame=None;self.sequence=0;self.stopped=threading.Event();self.processes=[]
        self.error=None;self.started=time.monotonic();self.server=None
    def start(self):
        if not shutil.which('ffmpeg'):raise ValueError('FFmpeg indisponível para vídeo contínuo.')
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path!='/'+owner.token:
                    self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=emily-frame')
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                previous=-1
                try:
                    while not owner.stopped.is_set():
                        with owner.condition:
                            owner.condition.wait_for(lambda:owner.sequence!=previous or owner.stopped.is_set(),timeout=2)
                            if owner.stopped.is_set():break
                            data,previous=owner.frame,owner.sequence
                        if not data:continue
                        self.wfile.write(b'--emily-frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n');self.wfile.flush()
                except (OSError,ConnectionError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        threading.Thread(target=self._capture,daemon=True).start()
        return self
    @property
    def url(self):return 'http://127.0.0.1:%s/%s'%(self.server.server_port,self.token)
    def _capture(self):
        while not self.stopped.is_set():
            recorder=decoder=None
            try:
                recorder=subprocess.Popen([self.adb,'-s',self.serial,'exec-out','screenrecord','--output-format=h264','--bit-rate','6000000','--time-limit','175','-'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                decoder=subprocess.Popen([shutil.which('ffmpeg'),'-loglevel','error','-probesize','32','-analyzeduration','1','-fpsprobesize','0','-flags','low_delay','-f','h264','-i','pipe:0','-an','-vf','setpts=N/(30*TB)','-fps_mode','passthrough','-c:v','mjpeg','-q:v','4','-threads','1','-f','image2pipe','pipe:1'],stdin=recorder.stdout,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                recorder.stdout.close();self.processes=[recorder,decoder]
                buffer=bytearray()
                while not self.stopped.is_set():
                    block=decoder.stdout.read1(65536)
                    if not block:break
                    buffer.extend(block)
                    while True:
                        start=buffer.find(b'\xff\xd8');end=buffer.find(b'\xff\xd9',max(0,start))
                        if start<0 or end<0:break
                        data=bytes(buffer[start:end+2]);del buffer[:end+2]
                        with self.condition:self.frame=data;self.sequence+=1;self.error=None;self.condition.notify_all()
                    if len(buffer)>8_000_000:raise ValueError('Quadro de vídeo inválido.')
                if not self.stopped.is_set() and not self.frame:self.error='O celular não iniciou o vídeo. Usando capturas como alternativa.'
            except Exception as exc:self.error=str(exc)
            finally:
                for process in (recorder,decoder):
                    if process and process.poll() is None:
                        process.terminate()
                        try:process.wait(timeout=2)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
                self.processes=[]
            self.stopped.wait(.25)
    def close(self):
        self.stopped.set()
        with self.condition:self.condition.notify_all()
        for p in self.processes:
            if p.poll() is None:p.terminate()
        if self.server:self.server.shutdown();self.server.server_close()


class NativePreviewStream:
    """Forward the app's private PixelCopy stream. No video decoder or frame RPC."""
    def __init__(self,adb,serial,metadata):
        if not 1<=int(metadata['port'])<=65535 or not re.fullmatch(r'[a-zA-Z0-9-]{20,100}',metadata['path']):raise ValueError('Metadados de vídeo inválidos.')
        self.adb,self.serial=adb,serial;self.metadata=metadata;self.frame=None;self.sequence=0
        result=subprocess.run([adb,'-s',serial,'forward','tcp:0','tcp:'+str(int(metadata['port']))],capture_output=True,text=True,timeout=10,check=True)
        self.port=int(result.stdout.strip());self.url='http://127.0.0.1:%s/%s'%(self.port,metadata['path'])
        try:
            with urllib.request.urlopen(self.url,timeout=3) as response:
                if response.status!=200:raise ValueError('Vídeo indisponível.')
        except Exception:
            self.close();raise
    def close(self):
        subprocess.run([self.adb,'-s',self.serial,'forward','--remove','tcp:'+str(self.port)],capture_output=True,timeout=5)
