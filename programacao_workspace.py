"""Comparação e atualização em três versões, preservando a cópia e o original."""
import difflib
from pathlib import Path
import time


def merge(base, local, remote, binary=False):
    if local == base: return remote
    if remote == base or local == remote: return local
    if binary: return None, 'recurso binário alterado nas duas versões'
    if None in (base,local,remote): return None, 'criação/remoção concorrente'
    try:
        old=base.decode('utf-8').splitlines(True)
        ours=local.decode('utf-8').splitlines(True)
        theirs=remote.decode('utf-8').splitlines(True)
    except UnicodeError: return None, 'recurso binário alterado nas duas versões'
    def edits(lines):
        return [(i,j,lines[a:b]) for op,i,j,a,b in difflib.SequenceMatcher(None,old,lines,autojunk=False).get_opcodes() if op!='equal']
    left,right=edits(ours),edits(theirs)
    for a in left:
        for b in right:
            if a==b: continue
            overlap=max(a[0],b[0]) < min(a[1],b[1])
            insertion=(a[0]==a[1] and b[0]<=a[0]<=b[1]) or (b[0]==b[1] and a[0]<=b[0]<=a[1])
            if overlap or insertion: return None, 'trechos sobrepostos; escolha uma resolução explícita'
    combined=left+[e for e in right if e not in left]
    for start,end,replacement in sorted(combined,key=lambda e:(e[0],e[1]),reverse=True):
        old[start:end]=replacement
    return ''.join(old).encode('utf-8')


def _read(path):
    return path.read_bytes() if path.is_file() else None


def _write(path, raw):
    if raw is None: path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)


def fingerprint(raw, p): return p.digest(raw) if raw is not None else 'ausente'


def compare(folder,data,p,name=''):
    source=Path(data['projeto']);work=folder/'workspace'
    specific=bool(name)
    names=[name] if name else sorted(set(data['base']) | set(p.files(source)) | set(p.files(work)))
    rows=[]
    for name in names:
        base=_read(p.safe(folder/'originals',name));local=_read(p.safe(work,name));remote=_read(p.safe(source,name))
        if remote==base and not specific: continue
        candidate=merge(base,local,remote,Path(name).suffix.lower() in p.BINARY)
        conflict=isinstance(candidate,tuple)
        row={'arquivo':name,'sha_original':fingerprint(remote,p),'sha_copia':fingerprint(local,p),
             'alterado_na_copia':local!=base,'alterado_no_original':remote!=base,
             'conflito':conflict,'motivo':candidate[1] if conflict else ''}
        if len(names)==1:
            for key,raw in [('base',base),('copia',local),('original',remote)]:
                row[key]=raw.decode('utf-8',errors='replace')[:24000] if raw is not None else None
        rows.append(row)
    return rows


def _editable(folder,data,p):
    if data.get('aplicacao'): raise ValueError('Sessão já aplicada; inicie outra para novas mudanças.')
    for jid in data['jobs']:
        if p.status(folder,data,jid)['estado'] in {'iniciando','executando'}:
            raise ValueError('Aguarde os testes ou cancele a prévia antes de atualizar a cópia.')


def refresh(folder,data,p):
    _editable(folder,data,p)
    source=Path(data['projeto']);work=folder/'workspace';updated=[];conflicts=[]
    backup=folder/'refresh-backups'/str(time.time_ns())
    for name in sorted(set(data['base']) | set(p.files(source)) | set(p.files(work))):
        base=_read(p.safe(folder/'originals',name));local=_read(p.safe(work,name));remote=_read(p.safe(source,name))
        if remote==base: continue
        result=merge(base,local,remote,Path(name).suffix.lower() in p.BINARY)
        if isinstance(result,tuple):
            conflicts.append({'arquivo':name,'motivo':result[1],'sha_original':fingerprint(remote,p),'sha_copia':fingerprint(local,p)})
            continue
        if local is not None: _write(p.safe(backup,name),local)
        _write(p.safe(work,name),result)
        _write(p.safe(folder/'originals',name),remote)
        if remote is None: data['base'].pop(name,None)
        else: data['base'][name]=p.digest(remote)
        updated.append(name)
    p.event(folder,data,'Cópia atualizada; conflitos preservados: '+', '.join(c['arquivo'] for c in conflicts),'codigo')
    return {'ok':True,'atualizados':updated,'conflitos':conflicts,'backup':str(backup),
            'revisao':p.revision(folder,data),'mensagem':'O original não foi alterado. Resolva os conflitos restantes, rode os testes novamente e só depois aplique.'}


def resolve(folder,data,p,args):
    _editable(folder,data,p)
    name=args.get('arquivo');source=p.safe(Path(data['projeto']),name);work=p.safe(folder/'workspace',name)
    remote,local=_read(source),_read(work)
    if fingerprint(remote,p)!=args.get('sha_original') or fingerprint(local,p)!=args.get('sha_copia'):
        raise ValueError('Original ou cópia mudou desde a comparação. Use comparar antes de resolver; nada foi sobrescrito.')
    choice=args.get('escolha')
    if choice=='manter_copia': result=local
    elif choice=='usar_original': result=remote
    elif choice=='mesclar':
        text=args.get('conteudo')
        if not isinstance(text,str) or len(text.encode())>700000: raise ValueError('Conteúdo de resolução inválido.')
        result=text.encode()
    else: raise ValueError('Escolha de resolução inválida.')
    backup=folder/'refresh-backups'/str(time.time_ns())
    if local is not None: _write(p.safe(backup,name),local)
    _write(work,result);_write(p.safe(folder/'originals',name),remote)
    if remote is None: data['base'].pop(name,None)
    else: data['base'][name]=p.digest(remote)
    p.event(folder,data,'Conflito resolvido na cópia: '+name,'codigo')
    return {'ok':True,'arquivo':name,'backup':str(backup),'revisao':p.revision(folder,data),
            'mensagem':'Resolução preparada na cópia. O original não mudou. Execute os testes novamente antes de aplicar.'}
