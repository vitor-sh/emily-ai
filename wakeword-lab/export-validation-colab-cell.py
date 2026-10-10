from pathlib import Path
import zipfile
from google.colab import files
work = Path('/content/emily-wakeword/work-v2-diverse')
folders = [work/'features/0/validation', work/'features/1/validation']
for folder in folders:
    if not folder.is_dir():
        raise RuntimeError('Os dados da validação não estão mais nesta sessão.')
folders.append(work/'trained/logs')
result = Path('/content/ei-emily-v2-validation-details.zip')
with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
    for folder in folders:
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('Link inesperado no pacote de avaliação.')
            if path.is_file():
                archive.write(path, str(path.relative_to(work)))
print('Pacote da validação:', round(result.stat().st_size/1024/1024, 1), 'MB')
files.download(str(result))
