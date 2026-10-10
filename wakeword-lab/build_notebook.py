"""Create a portable notebook from an explicit allowlist. No private audio/secrets."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def diagnostic_files(work):
    """Explicit model-only allowlist; never include checkpoints, audio or secrets."""
    trained = work / 'trained'
    paths = [trained / name for name in (
        'best_weights.weights.h5', 'last_weights.weights.h5', 'training_config.yaml')]
    saved = trained / 'stream_state_internal'
    paths.extend(saved / name for name in (
        'saved_model.pb', 'fingerprint.pb', 'variables/variables.index',
        'variables/variables.data-00000-of-00001'))
    return [path for path in paths if path.is_file()]


def build():
    cells = []
    def markdown(source):
        cells.append(dict(cell_type="markdown", metadata={}, source=source.splitlines(True)))
    def code(source):
        cells.append(dict(cell_type="code", metadata={}, execution_count=None, outputs=[], source=source.splitlines(True)))
    markdown("""# Ei, Emily — protótipo microWakeWord em português

**Experimento, não atualização pronta do Android.** Não requer suas gravações, API key ou plano pago.

1. No Colab, escolha **Ambiente de execução → Alterar tipo → T4 GPU**, se disponível gratuitamente.
2. Escolha **Ambiente de execução → Executar tudo**. Confirme apenas a execução deste notebook.
3. No final baixe o ZIP e devolva ao desenvolvimento da Emily para avaliação.

Esta segunda rodada usa **32 perfis sintéticos (Piper + Kokoro)**, incluindo femininos e masculinos. São sete perfis brasileiros e 25 estrangeiros sintetizados com fonemas pt-br; não são 32 falantes brasileiros reais. Perfis estrangeiros podem ter sotaque ou pronúncia inadequada; as prévias permitem conferir isso. Não usamos misturas de perfis para inflar o número de vozes.

Gera também frases parecidas, menções à Emily em conversas, silêncio e ruído. A duração mínima é balanceada entre classes, e a chamada inteira fica dentro da janela de treino. Vozes de validação/teste ficam separadas das de treino; não há garantia de independência de pessoas nos perfis internos do Kokoro. Resultados sintéticos não comprovam funcionamento para qualquer pessoa. Ainda faltam conversas reais longas, integração e consumo no Android. O seu áudio do WhatsApp não está incluído e não será enviado.

O Colab gratuito pode interromper a sessão ou não oferecer GPU. Nenhum plano pago é ativado. A geração salva progresso por perfil e as etapas concluídas são reutilizadas enquanto os arquivos da sessão ainda existirem. Se o Colab apagar a máquina temporária, o progresso é perdido; não conectamos seu Google Drive automaticamente.
""")
    files = {name: (ROOT / name).read_text() for name in ("lab.py", "diversity.py", "run_upstream.py", "colab_setup.py", "voices.json", "requirements-training.txt", "test_lab.py", "build_notebook.py")}
    code("from pathlib import Path\nimport json, os, subprocess, sys\n"
         "root = Path('/content/emily-wakeword')\nroot.mkdir(exist_ok=True)\n"
         f"files = json.loads({json.dumps(json.dumps(files, ensure_ascii=False), ensure_ascii=False)})\n"
         "for name, contents in files.items(): (root / name).write_text(contents)\n"
         "os.chdir(root)\n"
         "sys.path.insert(0, str(root))\n"
         "os.environ['OMP_NUM_THREADS'] = '2'\n"
         "os.environ['OPENBLAS_NUM_THREADS'] = '2'\n"
         "os.environ['TF_NUM_INTRAOP_THREADS'] = '2'\n"
         "os.environ['TF_NUM_INTEROP_THREADS'] = '1'\n"
         "from colab_setup import setup\n"
         "training_python = str(setup(root))\n")
    markdown("## Geração e treinamento\nNão instale o resultado no celular ainda. A escolha do limiar usa somente validação; a voz de teste permanece separada.")
    code("# Ajustáveis sem mexer na instalação da Emily.\nREPETITIONS = 96\nSTEPS = 6000\n"
         "work = root / 'work-v2-diverse'\n"
         "import hashlib, shutil\n"
         "work.mkdir(exist_ok=True)\n"
         "signature = hashlib.sha256(json.dumps({'files': files, 'repetitions': REPETITIONS, 'steps': STEPS}, sort_keys=True).encode()).hexdigest()\n"
         "signature_path = work/'pipeline-signature.txt'\n"
         "if signature_path.exists() and signature_path.read_text() != signature:\n"
         "    raise RuntimeError('Pipeline alterado: use uma sessão nova para evitar misturar resultados.')\n"
         "signature_path.write_text(signature)\n"
         "for stage, options in [('generate', ['--repetitions', str(REPETITIONS)]), ('features', []), ('train', ['--steps', str(STEPS)]), ('evaluate', [])]:\n"
         "    done = work/(stage+'.done')\n"
         "    if done.is_file():\n"
         "        print('Etapa já concluída:', stage, flush=True)\n"
         "        continue\n"
         "    if stage == 'features' and (work/'features').exists():\n"
         "        shutil.rmtree(work/'features')  # Apenas derivados incompletos desta sessão isolada.\n"
         "    print('Etapa:', stage, flush=True)\n"
         "    subprocess.run([training_python, 'lab.py', stage, '--work', str(work), *options], check=True)\n"
         "    done.write_text(signature)\n"
         "    if stage == 'generate':\n"
         "        from IPython.display import Audio, display\n"
         "        rows = [json.loads(line) for line in (work/'samples.jsonl').read_text().splitlines()]\n"
         "        for voice in json.loads(Path('voices.json').read_text())['voices']:\n"
         "            example = next(r for r in rows if r['voice'] == voice['id'] and r['positive'])\n"
         "            print('Amostra de pronúncia:', voice['id'])\n"
         "            display(Audio(filename=str(work/example['path'])))\n")
    markdown("## Resultado para avaliação\nO ZIP contém o modelo candidato, pesos e modelo original para comparar a conversão, relatório, origens/licenças e hashes. Não inclui gravações suas, arquivos da Emily ou vozes completas do Piper. A avaliação sintética não é autorização para distribuir o detector.")
    code("import zipfile\nfrom google.colab import files as colab_files\n"
         "from build_notebook import diagnostic_files\n"
         "result = root / 'ei-emily-diverse-v2-candidate.zip'\n"
         "model = work / 'trained/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite'\n"
         "with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:\n"
         "    for path in [model, work/'report.json', work/'resolved_sources.json', work/'samples.jsonl', work/'training.yaml']:\n"
         "        archive.write(path, str(path.relative_to(work)))\n"
         "    for path in diagnostic_files(work):\n"
         "        archive.write(path, str(path.relative_to(work)))\n"
         "    for path in (work/'voices').glob('*/MODEL_CARD'):\n"
         "        archive.write(path, str(path.relative_to(work)))\n"
         "    for name in ('README.md', 'VOICES.md'):\n"
         "        path = work/'kokoro'/name\n"
         "        if path.is_file(): archive.write(path, str(path.relative_to(work)))\n"
         "    archive.write('upstream/LICENSE', 'licenses/microwakeword-APACHE-2.0.txt')\n"
         "print((work/'report.json').read_text())\ncolab_files.download(str(result))\n")
    result = dict(nbformat=4, nbformat_minor=5, cells=cells,
                  metadata=dict(kernelspec=dict(display_name="Python 3", language="python", name="python3"),
                                language_info=dict(name="python"), colab=dict(name="ei-emily-colab.ipynb")))
    for index, cell in enumerate(cells): cell["id"] = f"emily-{index}"
    destination = ROOT / "ei-emily-colab.ipynb"
    destination.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    for cell in cells:
        if cell["cell_type"] == "code": compile("".join(cell["source"]), str(destination), "exec")
    print(destination)


if __name__ == "__main__": build()
