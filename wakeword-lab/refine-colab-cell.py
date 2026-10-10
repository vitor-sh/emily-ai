# Cole em uma célula NOVA do notebook que ainda está aberto, sem rodar tudo novamente.
from pathlib import Path
import os, subprocess, zipfile, hashlib, datetime
from google.colab import files
root = Path('/content/emily-wakeword')
source = root/'work-v2-diverse'
python = root/'.training-venv/bin/python'
if not (source/'features/1/training/samples_mmap').is_dir() or not python.is_file():
    raise RuntimeError('A sessão anterior e as características precisam continuar disponíveis.')
print('Selecione ei-emily-v3-refinement-tools.zip (somente ferramentas, não é o ZIP do modelo).')
uploaded = files.upload()
if len(uploaded) != 1:
    raise RuntimeError('Envie somente o pacote de ferramentas.')
blob = next(iter(uploaded.values()))
if hashlib.sha256(blob).hexdigest() != '08d584b21b74edbbcaea21898391422ef89577d7687dc5ce633d08ad13ab707a':
    raise RuntimeError('Pacote diferente do preparado; não executar.')
tools = root/'refinement-tools-v3'
tools.mkdir(exist_ok=True)
import io
with zipfile.ZipFile(io.BytesIO(blob)) as z:
    for name in ['refine_streaming.py','lab.py','run_upstream.py','test_refinement.py']:
        (tools/name).write_bytes(z.read(name))
output = root/('work-v3-streaming-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
env = os.environ.copy()
env['PYTHONPATH'] = str(root/'work/upstream')+':'+str(tools)
env['OMP_NUM_THREADS'] = '2'
env['OPENBLAS_NUM_THREADS'] = '2'
env['TF_NUM_INTRAOP_THREADS'] = '2'
env['TF_NUM_INTEROP_THREADS'] = '1'
libraries = [str(p) for p in (root/'.training-venv/lib/python3.11/site-packages/nvidia').glob('*/lib')]
env['LD_LIBRARY_PATH'] = ':'.join(libraries+[env.get('LD_LIBRARY_PATH','')])
subprocess.run([str(python),'-m','unittest','test_refinement'],cwd=tools,env=env,check=True)
subprocess.run([str(python),str(tools/'refine_streaming.py'),'--source',str(source),
                '--output',str(output),'--steps','1500','--interval','250','--require-gpu'],
               cwd=tools,env=env,check=True)
print('As duas variantes ainda são experimentais; não instalar no Android.')
files.download(str(output.with_suffix('.zip')))
