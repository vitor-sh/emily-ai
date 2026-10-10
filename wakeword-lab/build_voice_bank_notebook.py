"""Build a self-contained, isolated source-quality pilot, not a detector update."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent

def build():
    files={name:(ROOT/name).read_text() for name in ['voice_bank_pilot.py','test_voice_bank_pilot.py',
                                                    'setup_voice_bank.py','voice_gpu_probe.py','requirements-voice-pilot.txt']}
    install=("from pathlib import Path\nimport json, os, subprocess\n"
             "root = Path('/content/emily-voice-source-pilot')\nroot.mkdir(exist_ok=True)\n"
             f"sources = json.loads({json.dumps(json.dumps(files,ensure_ascii=False),ensure_ascii=False)})\n"
             "for name, contents in sources.items(): (root/name).write_text(contents)\n"
             "os.chdir(root)\nimport sys\nsys.path.insert(0,str(root))\n"
             "import importlib, setup_voice_bank\nimportlib.reload(setup_voice_bank)\n"
             "from setup_voice_bank import setup\npython, env = setup(root)\n")
    run=("# Piloto de qualidade: não ampliar antes de ouvir/analisar o resultado.\n"
         "PROFILES = 12\nwork = root/'work-source-pilot-12-audit2'\n"
         "for stage in ['reference','phrases','audit']:\n"
         "    print('Etapa:',stage,flush=True)\n"
         "    subprocess.run([python,str(root/'voice_bank_pilot.py'),stage,'--work',str(work),\n"
         "                    '--profiles',str(PROFILES)],cwd=root,env=env,check=True)\n"
         "from IPython.display import Audio, display\n"
         "report = json.loads((work/'audit.json').read_text())\n"
         "print('Requer avaliação humana; não é um modelo do Android.')\n"
         "for profile in report['profiles']:\n"
         "    print(profile['requested_region'],profile['requested_gender'],'— sotaque solicitado, não confirmado')\n"
         "    example = next(row for row in report['records'] if row['voice']==profile['id'] and row['kind']=='call-emily')\n"
         "    display(Audio(filename=str(work/example['path']), normalize=False))\n"
         "from google.colab import files\nfiles.download(str(work.with_suffix('.zip')))\n")
    intro='''# Ei, Emily — novo banco de vozes (piloto)

**Teste de uma nova fonte de áudio; não instala nada nem treina outro detector ainda.**

1. No Colab, selecione GPU **T4** e execute tudo.
2. Baixe o ZIP ao terminar e devolva para avaliação.

Gera 12 perfis solicitados em português brasileiro, com descrições de seis regiões, adultos de idades diferentes e timbres variados. Qwen3-TTS VoiceDesign cria referências sintéticas; Qwen3-TTS Base 0.6B reutiliza cada referência para duas chamadas e dois negativos. Não usa sua gravação, nem clona pessoas reais. **São perfis sintéticos: sotaques e diferenças entre vozes precisam ser confirmados ouvindo; não são 12 falantes reais comprovados.**

Whisper auxilia a transcrição; alertas de duração, prefixo ausente, nomes isolados e embeddings muito semelhantes ficam no relatório. ASR e embeddings não comprovam pronúncia correta ou diversidade real. A amostra é deliberadamente pequena antes de gastar horas com até 200 perfis.

O ambiente fica em `/content/emily-voice-source-pilot`, separado do treinamento anterior. Cada modelo é carregado em um processo independente. Na T4 usamos FP32 para evitar problemas de FP16; a síntese pode demorar. O tempo real fica registrado no ZIP, permitindo estimar se centenas de perfis cabem no Colab gratuito. Não ativa cobrança nem conecta Google Drive. Se o Colab interromper, execute novamente para aproveitar os WAVs concluídos, enquanto a máquina temporária existir. Não é necessário reexecutar o treinamento v2/v3.

As versões dos modelos estão fixadas e sua licença é Apache-2.0. O resultado contém apenas áudios sintéticos e seus registros. Ainda faltam sons/conversas reais para treinar e avaliar falsos acionamentos.
'''
    cells=[dict(cell_type='markdown',metadata={},source=intro.splitlines(True))]
    for source in [install,run]:
        compile(source,'notebook-cell','exec')
        cells.append(dict(cell_type='code',metadata={},execution_count=None,outputs=[],source=source.splitlines(True)))
    notebook=dict(cells=cells,metadata=dict(colab=dict(name='ei-emily-voice-source-pilot.ipynb'),
                                          kernelspec=dict(name='python3',display_name='Python 3'),accelerator='GPU'),
                  nbformat=4,nbformat_minor=5)
    (ROOT/'ei-emily-voice-source-pilot.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=1))
    (ROOT/'voice-source-colab-cell.py').write_text(install+'\n'+run)
    print('Notebook e célula única gerados; nenhum modelo foi baixado localmente.')

if __name__=='__main__':build()
