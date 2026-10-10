"""Relaciona apenas fontes autorizadas com os monitores físicos do KDE."""
import json
import subprocess

def physical_outputs():
    try:
        data=json.loads(subprocess.check_output(['kscreen-doctor','-j'],timeout=3))
        outputs=[]
        for o in data['outputs']:
            if not o.get('enabled') or not o.get('connected') or o.get('name','').lower().startswith('virtual'):continue
            scale=max(.1,float(o.get('scale',1)))
            w=round(o['size']['width']/scale);h=round(o['size']['height']/scale)
            if o.get('rotation') in (2,8): w,h=h,w
            outputs.append({'nome':o['name'],'posicao':(o['pos']['x'],o['pos']['y']),'tamanho':(w,h)})
        return sorted(outputs,key=lambda o:o['posicao'])
    except Exception:
        return []

def authorized_sources(streams, outputs=None):
    ordered=sorted(streams,key=lambda s:s.get('posicao',(9999999,9999999)))
    outputs=physical_outputs() if outputs is None else outputs
    if len(outputs)>1:
        left=min(o['posicao'][0] for o in outputs);top=min(o['posicao'][1] for o in outputs)
        right=max(o['posicao'][0]+o['tamanho'][0] for o in outputs)
        bottom=max(o['posicao'][1]+o['tamanho'][1] for o in outputs)
        # KDE's all-screens source is the bounding rectangle in logical pixels.
        composite=next((s for s in ordered if s.get('tamanho')==(right-left,bottom-top)),None)
        if composite:
            result=[]
            for i,o in enumerate(outputs,1):
                x,y=o['posicao'];w,h=o['tamanho']
                result.append({**composite,'indice':i,'nome':f"Monitor {i} · {o['nome']}",
                    'origem_tamanho':composite['tamanho'],'tamanho':(w,h),
                    'crop':(x-left,y-top,right-(x+w),bottom-(y+h))})
            return result
    return [{**s,'indice':i,'nome':f'Monitor {i}'} for i,s in enumerate(ordered,1)]

def crop_pipeline(source):
    crop=source.get('crop')
    if not crop:return ''
    left,top,right,bottom=crop
    return f'videocrop left={left} top={top} right={right} bottom={bottom} ! '
