"""Instrumentação preservando argumentos e ações existentes do Compose.
Executada em desenvolvimento; as chaves gravadas no código permanecem estáveis.
"""
from pathlib import Path
import json,re,shutil
KINDS={'Text','Icon','Image','AsyncImage','Button','IconButton','TextButton','OutlinedButton','FilledTonalButton','FloatingActionButton','ExtendedFloatingActionButton','Box','Row','Column','Card','OutlinedCard','Surface','Spacer','Switch','Slider','TextField','OutlinedTextField','LazyColumn','LazyRow'}

def mask(s):
    out=list(s);i=0
    while i<len(s):
        if s.startswith('//',i):end=s.find('\n',i);end=len(s) if end<0 else end
        elif s.startswith('/*',i):
            n=1;end=i+2
            while end<len(s) and n:
                if s.startswith('/*',end):n+=1;end+=2
                elif s.startswith('*/',end):n-=1;end+=2
                else:end+=1
        elif s.startswith('"""',i):end=s.find('"""',i+3);end=len(s) if end<0 else end+3
        elif s[i] in '\"\'':
            q=s[i];end=i+1
            while end<len(s):
                if s[end]=='\\':end+=2
                elif s[end]==q:end+=1;break
                else:end+=1
        else:i+=1;continue
        for k in range(i,min(end,len(s))):
            if out[k]!='\n':out[k]=' '
        i=end
    return ''.join(out)

def arguments(m,start):
    depth=0;begin=start;parts=[]
    for i in range(start,len(m)):
        c=m[i]
        if c in '([{':depth+=1
        elif c in ')]}':
            if depth==0:parts.append((begin,i));return parts,i
            depth-=1
        elif c==',' and depth==0:parts.append((begin,i));begin=i+1
    raise ValueError('Parênteses incompletos')

def instrument(path,backup):
    s=path.read_text();m=mask(s);edits=[];catalog=[];counts={}
    for hit in re.finditer(r'(?<![\w.])('+ '|'.join(sorted(KINDS))+r')\s*\(',m):
        if re.search(r'\bfun\s*$',m[max(0,hit.start()-15):hit.start()]):continue
        kind=hit.group(1);parts,end=arguments(m,hit.end());args={};position=[]
        for a,b in parts:
            raw=s[a:b];match=re.match(r'\s*(\w+)\s*=',m[a:b])
            if match:args[match.group(1)]=(a+match.end(),b)
            elif raw.strip():position.append((a,b))
        # Preserve positional modifiers; adding another named modifier breaks overloads.
        slot=({'Text':1,'Icon':2,'Image':2,'AsyncImage':2,'Switch':2,'Slider':2,'TextField':2,'OutlinedTextField':2,'IconButton':1,'Button':1,'TextButton':1,'OutlinedButton':1,'FilledTonalButton':1,'FloatingActionButton':1,'ExtendedFloatingActionButton':1}.get(kind,0))
        if 'modifier' not in args and len(position)>slot:
            a,b=position[slot]
            if kind in {'Spacer','Box','Row','Column','LazyColumn','LazyRow','Surface','Card','OutlinedCard'} or s[a:b].strip().startswith('Modifier'):
                args['modifier']=(a,b)
        counts[kind]=counts.get(kind,0)+1
        key=f'{path.stem}:{kind}:{counts[kind]:04d}'
        if 'modifier' in args and 'UiEditor.mod(' in s[slice(*args['modifier'])]:
            found=re.search(r'UiEditor.mod\("([^"]+)"',s[slice(*args['modifier'])]);key=found.group(1) if found else key
        elif 'modifier' in args:
            a,b=args['modifier'];edits.append((a,b,f'UiEditor.mod("{key}", {s[a:b].strip()}, "{kind}")'))
        else:
            existing=any(s[a:b].strip() for a,b in parts);comma='' if not existing or s[:end].rstrip().endswith(',') else ','
            edits.append((end,end,f'{comma} modifier = UiEditor.mod("{key}", Modifier, "{kind}")'))
        label='';text=args.get('text') or (position[0] if kind=='Text' and position else None)
        if kind=='Text' and text:
            a,b=text;raw=s[a:b].strip();label=raw[:160]
            if not raw.startswith('UiEditor.text('):edits.append((a,b,f'UiEditor.text("{key}", {raw})'))
            for param,helper,default in [('color','color','androidx.compose.ui.graphics.Color.Unspecified'),('fontSize','font','androidx.compose.ui.unit.TextUnit.Unspecified')]:
                if param in args:
                    a,b=args[param];raw=s[a:b].strip()
                    if not raw.startswith(f'UiEditor.{helper}('):edits.append((a,b,f'UiEditor.{helper}("{key}", {raw})'))
                elif 'UiEditor.mod(' not in s[max(0,hit.start()):end]:
                    # Insertion joins other zero-length edits at the same position.
                    edits.append((end,end,f', {param} = UiEditor.{helper}("{key}", {default})'))
        if kind in {'Button','IconButton','TextButton','OutlinedButton','FilledTonalButton','FloatingActionButton','ExtendedFloatingActionButton'}:
            click=args.get('onClick') or (position[0] if position else None)
            if click:
                a,b=click;raw=s[a:b].strip()
                if not raw.startswith('UiEditor.action(') and not re.search(r'return@'+kind+r'\b',raw):edits.append((a,b,f'UiEditor.action("{key}", {raw})'))
        catalog.append({'key':key,'kind':kind,'file':path.name,'line':s.count('\n',0,hit.start())+1,'label':label})
    if edits:
        backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup)
        # Apply nested argument patches in descending order; zero-length inserts ordered explicitly.
        for a,b,v in sorted(edits,key=lambda t:(t[0],t[1]),reverse=True):s=s[:a]+v+s[b:]
        path.write_text(s)
    return catalog

if __name__=='__main__':
    root=Path(__file__).resolve().parent;src=root/'EmilyAPP2/app/src/main/java/com/example/emilyapp';catalog=[]
    names=['MainActivity','SettingsScreen','ChatConversationScreen','EmilyOverlayVisual','InAppVoiceFullScreen','EmilyCloudScreen','EmilyMusicScreen','MusicWelcomeScreen']
    for name in names:
        p=src/(name+'.kt');catalog+=instrument(p,root/'output/android-editor-2026-10-07/backups'/p.relative_to(root))
    assets=root/'EmilyAPP2/app/src/main/assets';assets.mkdir(exist_ok=True)
    (assets/'editor-catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
    print('Elementos instrumentados:',len(catalog))
