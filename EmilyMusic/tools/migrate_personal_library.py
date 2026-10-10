"""Owner-approved, local ADB migration. Never changes/uninstalls the original app."""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.private-migration'
OLD = 'com.example.emilyapp'
NEW = 'com.emily.music'


def command(serial, package, *args):
    return ['adb', '-s', serial, 'exec-out', 'run-as', package, *args]


def read(serial, package, path):
    return subprocess.check_output(command(serial, package, 'cat', path))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def export(serial):
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    prefs = ET.fromstring(read(serial, OLD, 'shared_prefs/music-account.xml'))
    uid = next((e.text for e in prefs if e.get('name') == 'approved-uid'), None)
    if not uid:
        raise RuntimeError('Entre na sua conta no Music da Emily original antes de copiar.')
    account = hashlib.sha256(uid.encode()).hexdigest()
    raw = read(serial, OLD, 'files/emily-music.json')
    if len(raw) > 32 * 1024 * 1024:
        raise RuntimeError('Biblioteca maior que o limite de importação; revisar antes de continuar.')
    library = json.loads(raw)
    if not isinstance(library.get('campos'), dict):
        raise RuntimeError('Biblioteca original inválida.')
    # Tree access grants belong to the original package and cannot be transferred.
    for field in ('folders', 'uploaded', 'scanCache', 'locals', 'sources', 'player'):
        library.pop(field, None)
    library['sources'] = {}
    library['scanCache'] = {}
    snapshot = PRIVATE / 'library.json'
    snapshot.write_text(json.dumps(library, ensure_ascii=False), encoding='utf-8')
    entries = [{'source': 'library.json', 'target': f'files/accounts/{account}/library.json', 'sha256': digest(snapshot)}]
    folders = [
        ('/storage/emulated/0/Android/data/' + OLD + '/files/Music/Emily Music', 'audio', f'/storage/emulated/0/Android/data/{NEW}/files/Music/Emily Music/{account}', re.compile(r'(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})\.mp3')),
        ('files/music-covers', 'covers', f'files/accounts/{account}/covers', re.compile(r'(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64}|playlist-[a-f0-9]{64})\.(?:jpg|png|webp|noart)')),
    ]
    for folder, category, destination, pattern in folders:
        listed = subprocess.run(command(serial, OLD, 'sh', '-c', 'find ' + shlex.quote(folder) + ' -maxdepth 1 -type f'), capture_output=True)
        if listed.returncode != 0:
            continue
        for source in listed.stdout.decode().splitlines():
            name = Path(source).name
            if not pattern.fullmatch(name):
                continue
            target = PRIVATE / category / name
            target.parent.mkdir(exist_ok=True, mode=0o700)
            with target.open('wb') as output:
                subprocess.run(command(serial, OLD, 'cat', source), stdout=output, check=True)
            entries.append({'source': f'{category}/{name}', 'target': f'{destination}/{name}', 'sha256': digest(target)})
    (PRIVATE / 'manifest.json').write_text(json.dumps({'account': account, 'entries': entries}), encoding='utf-8')
    print(f'Exportação local concluída: biblioteca e {len(entries)-1} arquivos; original preservada.')


def restore(serial):
    manifest = json.loads((PRIVATE / 'manifest.json').read_text())
    account = manifest['account']
    if not re.fullmatch(r'[a-f0-9]{64}', account):
        raise RuntimeError('Destino inválido.')
    target_library = f'files/accounts/{account}/library.json'
    exists = subprocess.check_output(command(serial, NEW, 'sh', '-c', 'if [ -f ' + shlex.quote(target_library) + ' ]; then printf present; fi')).strip() == b'present'
    if exists:
        raise RuntimeError('Já existe uma biblioteca de destino. Não será sobrescrita; precisa de mesclagem.')
    roots = [f'files/accounts/{account}/', f'/storage/emulated/0/Android/data/{NEW}/files/Music/Emily Music/{account}/']
    # Validate the entire snapshot before any write.
    for entry in manifest['entries']:
        source = (PRIVATE / entry['source']).resolve()
        if not source.is_relative_to(PRIVATE.resolve()) or digest(source) != entry['sha256']:
            raise RuntimeError('Snapshot local mudou; exporte novamente.')
        target = entry['target']
        if not any(target.startswith(root) for root in roots) or '..' in target.split('/'):
            raise RuntimeError('Caminho de destino inválido.')
    # Data first, library last: a interrupted import can be repeated safely.
    for entry in reversed(manifest['entries']):
        source = PRIVATE / entry['source']
        target = entry['target']
        script = 'mkdir -p ' + shlex.quote(str(Path(target).parent)) + ' && cat > ' + shlex.quote(target + '.import') + ' && mv ' + shlex.quote(target + '.import') + ' ' + shlex.quote(target)
        with source.open('rb') as stream:
            subprocess.run(['adb','-s',serial,'shell','-T',shlex.join(['run-as',NEW,'sh','-c',script])], stdin=stream, check=True, timeout=60)
        actual = subprocess.check_output(command(serial, NEW, 'sha256sum', target)).decode().split()[0]
        if actual != entry['sha256']:
            raise RuntimeError('Cópia incompleta; integridade não confere.')
    print(f'Importação verificada: biblioteca e {len(manifest["entries"])-1} arquivos, somente na conta do proprietário.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['export', 'import'])
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    (export if args.action == 'export' else restore)(args.serial)
