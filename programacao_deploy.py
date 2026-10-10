"""Publicação confiável de uma sessão já aplicada; executada fora do chat."""
import json
from pathlib import Path
import sys


def deploy(session_file):
    data=json.loads(Path(session_file).read_text())
    root=Path(data['projeto']);sys.path.insert(0,str(root))
    files=data['aplicacao']['arquivos']
    desktop=[name for name in files if not name.startswith(('EmilyAPP2/','tests/','testes/'))]
    if desktop:
        from publicar_windows_codigo import publicar, arquivos_publicaveis, DEST
        allowed={p.relative_to(root).as_posix() for p in arquivos_publicaveis(root)}
        selected=[name for name in desktop if name in allowed]
        old=json.loads((DEST/'latest.json').read_text())
        removed=[name for name in desktop if not (root/name).exists() and name in old.get('files',{})]
        if selected:
            path=publicar(int(old['version'])+1,old['installer'],root=root,selecionar=selected,retirar=removed)
            print('Código PC publicado:',path.name,flush=True)
        elif removed:
            raise ValueError('Publicação só de remoções exige incluir um arquivo de código existente.')
        else:
            print('Alterações não pertencem ao pacote PC (por exemplo documentação/testes).',flush=True)
    if any(name.startswith('EmilyAPP2/') for name in files):
        import importlib.util
        spec=importlib.util.spec_from_file_location('emily_apk_publish',root/'EmilyAPP2/publicar_atualizacao.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.publicar()
    print('Publicação concluída. Python entra em vigor após reiniciar; o APK está disponível para atualizar.',flush=True)


if __name__=='__main__':deploy(sys.argv[1])
