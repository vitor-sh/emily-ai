"""Bootstrap a separate Python 3.11 even when Colab's kernel uses 3.13+."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys


def run(command, root, label):
    """Stream real diagnostics and retain a complete log on failure."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    print(f"\n--- {label} ---", flush=True)
    tail = []
    with (root / "setup.log").open("a", encoding="utf-8") as log:
        log.write(f"\n--- {label} ---\n")
        with subprocess.Popen([str(part) for part in command], cwd=root,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, text=True, errors="replace", bufsize=1) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
                tail = (tail + [line])[-30:]
            status = process.wait()
    if status:
        raise RuntimeError(f"Falhou: {label} (código {status}). "
                           f"Log completo: {root / 'setup.log'}\n" + "".join(tail))


def ensure_python(root):
    root = Path(root).resolve()
    bootstrap = root / ".bootstrap"
    uv = bootstrap / "bin/uv"
    python = root / ".training-venv/bin/python"
    if not uv.exists():
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "--target", bootstrap, "uv==0.8.22"], root, "Instalar gerenciador de Python")
    os.environ["UV_PYTHON_INSTALL_DIR"] = str(root / ".managed-python")
    os.environ["UV_CACHE_DIR"] = str(root / ".uv-cache")
    os.environ["UV_NATIVE_TLS"] = "true"
    if not python.exists():
        run([uv, "venv", "--managed-python", "--python", "3.11", "--seed", python.parent.parent],
            root, "Criar Python 3.11 separado do kernel do Colab")
    run([python, "-c", "import sys; print('Python de treinamento:', sys.version); "
         "assert sys.version_info[:2] == (3, 11), 'Ambiente incompatível; use uma sessão nova.'"],
        root, "Conferir versão do treinamento")
    return python


def setup(root):
    root = Path(root).resolve()
    python = ensure_python(root)
    run([python, "-m", "pip", "install", "--disable-pip-version-check",
         "-r", "requirements-training.txt"], root, "Instalar dependências compatíveis")
    # CUDA packages live only in this virtual environment, not the Colab kernel.
    if shutil.which("nvidia-smi"):
        run([python, "-m", "pip", "install", "--disable-pip-version-check",
             "tensorflow[and-cuda]==2.18.1"], root, "Preparar bibliotecas da GPU")
        # Only one ORT distribution may own the module. This is the isolated venv.
        run([python, '-m', 'pip', 'uninstall', '-y', 'onnxruntime', 'onnxruntime-gpu'],
            root, 'Preparar ONNX Runtime único')
        run([python, '-m', 'pip', 'install', 'onnxruntime-gpu==1.22.0'],
            root, 'Habilitar síntese Kokoro na GPU')
        library_root = python.parent.parent / 'lib/python3.11/site-packages/nvidia'
        libraries = sorted(str(p) for p in library_root.glob('*/lib') if p.is_dir())
        os.environ['LD_LIBRARY_PATH'] = ':'.join(libraries + [os.environ.get('LD_LIBRARY_PATH', '')])
    run([python, "-m", "pip", "install", "--no-deps", "attrs==25.4.0"],
        root, "Compatibilidade do audio-metadata")
    if not (root / "upstream/.git").exists():
        run(["git", "clone", "https://github.com/kahrendt/microWakeWord.git", "upstream"],
            root, "Baixar microWakeWord")
    commit = json.loads((root / "voices.json").read_text())["upstream_commit"]
    run(["git", "-C", "upstream", "checkout", commit], root, "Fixar revisão testada")
    run([python, "-m", "pip", "install", "--no-deps", "-e", "upstream"],
        root, "Instalar microWakeWord completo")
    run([python, "-m", "unittest", "-v", "test_lab"], root, "Testar preparação")
    run([python, "-c", "import tensorflow as tf; "
         "print('TensorFlow:', tf.__version__); "
         "print('GPU disponível:', tf.config.list_physical_devices('GPU'))"],
        root, "Conferir TensorFlow e GPU")
    return python
