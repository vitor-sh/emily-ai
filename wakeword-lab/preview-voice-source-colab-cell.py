# Ouvir o piloto já gerado: não instala, gera ou treina nada.
from pathlib import Path
import json
from IPython.display import Audio, display
root = Path('/content/emily-voice-source-pilot/work-source-pilot-12')
if not (root/'audit.json').is_file():
    raise RuntimeError('O piloto não está mais nesta sessão. Abra listening.html do ZIP extraído no PC.')
report = json.loads((root/'audit.json').read_text())
for profile in report['profiles']:
    print(profile['requested_region'], profile['requested_gender'], '— perfil sintético, sotaque não confirmado')
    for kind in ['call-emily', 'call-emili']:
        row = next(r for r in report['records'] if r['voice']==profile['id'] and r['kind']==kind)
        print(row['expected_text'], 'Transcrição auxiliar:', row['transcript'], 'Alertas:', row['audit_flags'])
        display(Audio(filename=str(root/row['path']), normalize=False))
