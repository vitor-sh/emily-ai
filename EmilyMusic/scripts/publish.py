#!/usr/bin/env python3
"""Publish only the standalone client, its clean source and immutable release metadata."""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, urllib.request, zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
CLOUD=ROOT.parent/'music-cloud'
REPO='vitor-sh/emily-music-releases'
GH=shutil.which('gh') or str(pathlib.Path.home()/'.local/bin/gh')
def run(*args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)
def source_package(destination):
    paths=['app/src','app/build.gradle.kts','build.gradle.kts','settings.gradle.kts','gradle.properties','gradle','gradlew','gradlew.bat','version.properties','COPYING','THIRD_PARTY_NOTICES.md','licenses','SOURCE_README.md','ANDROID_AUTO.md','scripts/package_icon.py','scripts/test_search_progress.js','design/icon-variants/emily-music-symbolic-neon-v1.png','design/icon-variants/SYMBOLIC-NEON-PROMPT.md']
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in paths:
            base=ROOT/name
            files=base.rglob('*') if base.is_dir() else [base]
            for path in files:
                if path.is_file():archive.write(path,'EmilyMusic/'+str(path.relative_to(ROOT)))
    with zipfile.ZipFile(destination) as archive:
        assert not any(any(part in n for part in ['local.properties','google-services.json','.keystore','.signing/','library.json']) for n in archive.namelist())
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--version',type=int);parser.add_argument('--notes',type=pathlib.Path,required=True);parser.add_argument('--package-only',action='store_true')
    args=parser.parse_args();version=args.version or int((ROOT/'version.properties').read_text())+1
    if version<int((ROOT/'version.properties').read_text()):raise SystemExit('Não diminuir a versão.')
    (ROOT/'version.properties').write_text(str(version)+'\n')
    run('node',str(ROOT/'scripts/test_search_progress.js'))
    run(str(ROOT/'gradlew'),'-p',str(ROOT),'--max-workers=1','testDebugUnitTest','assembleRelease')
    output=ROOT/'output'/'releases'/f'0.1.{version}';output.mkdir(parents=True,exist_ok=True)
    apk=output/f'EmilyMusic-0.1.{version}.apk';shutil.copy2(ROOT/'app/build/outputs/apk/release/app-release.apk',apk)
    source=output/f'EmilyMusic-0.1.{version}-source.zip';source_package(source)
    third=output/'NewPipeExtractor-v0.26.5-source.zip'
    if not third.exists():urllib.request.urlretrieve('https://github.com/TeamNewPipe/NewPipeExtractor/archive/refs/tags/v0.26.5.zip',third)
    fallback=output/'youtubedl-android-0.18.1-source.zip'
    if not fallback.exists():urllib.request.urlretrieve('https://codeload.github.com/yausername/youtubedl-android/zip/refs/tags/0.18.1',fallback)
    digest=hashlib.sha256(apk.read_bytes()).hexdigest()
    metadata={'version_code':version,'version_name':f'0.1.{version}','size':apk.stat().st_size,'sha256':digest,'url':f'https://github.com/{REPO}/releases/download/v0.1.{version}/{apk.name}'}
    manifest=output/'update.json';manifest.write_text(json.dumps(metadata,indent=2)+'\n')
    (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in [apk,source,third,fallback]))
    if args.package_only:print(output);return
    run(GH,'release','create',f'v0.1.{version}',str(apk),str(source),str(third),str(fallback),str(output/'SHA256SUMS.txt'),str(manifest),'--repo',REPO,'--title',f'Emily Music 0.1.{version}','--notes-file',str(args.notes.resolve()))
    # Only point clients at a version after the actual public binary is reachable.
    with urllib.request.urlopen(metadata['url']) as response:
        hasher=hashlib.sha256();size=0
        while data:=response.read(1024*1024):hasher.update(data);size+=len(data)
        assert size==metadata['size'] and hasher.hexdigest()==digest
    run('npx','wrangler','secret','put','MUSIC_UPDATE_JSON',cwd=CLOUD,input=json.dumps(metadata),text=True)
    import sys
    subprocess.run([sys.executable, str(ROOT.parent/"limpar_armazenamento.py"), "--apply"], check=False)
    print(f'https://github.com/{REPO}/releases/tag/v0.1.{version}')
if __name__=='__main__':main()
