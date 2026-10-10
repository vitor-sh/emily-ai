"""Imagens do editor: visão do modelo e recursos locais sem conteúdo executável."""
import base64
import io
import re
import warnings
from pathlib import Path
import threading
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

MAX_INPUT = 4 * 1024 * 1024
MAX_ASSET = 700000
_session = None
_session_lock = threading.Lock()


def remove_background(image):
    """U²-Net pequeno na CPU, modelo embarcado; não envia a imagem para um serviço."""
    global _session
    import hashlib
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageChops
    with _session_lock:
        if _session is None:
            model = Path(__file__).resolve().parent / 'assets/editor/u2netp.onnx'
            if hashlib.sha256(model.read_bytes()).hexdigest() != '309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8':
                raise ValueError('Modelo de remoção de fundo ausente ou inválido.')
            options = ort.SessionOptions(); options.intra_op_num_threads = 2
            _session = ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider'])
        array = np.asarray(image.convert('RGB').resize((320, 320), Image.Resampling.LANCZOS), dtype=np.float32)
        array /= max(float(array.max()), 1e-6)
        array = (array - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
        result = _session.run(None, {_session.get_inputs()[0].name: array.transpose(2, 0, 1)[None]})[0][0, 0]
        lo, hi = float(result.min()), float(result.max())
        mask = np.clip((result - lo) / max(hi - lo, 1e-6), 0, 1)
        mask = Image.fromarray((mask * 255).astype('uint8')).resize(image.size, Image.Resampling.LANCZOS)
    output = image.copy(); output.putalpha(ImageChops.multiply(output.getchannel('A'), mask))
    return output


def edit(image, operations, resolve):
    """Operações declarativas, sem executar código fornecido pelo modelo."""
    from PIL import Image, ImageOps, ImageFilter, ImageColor, ImageDraw, ImageFont
    import numpy as np
    if not isinstance(operations, list) or not 1 <= len(operations) <= 20:
        raise ValueError('Use de uma a vinte operações por edição.')
    def number(value, low, high):
        n = float(value)
        if not low <= n <= high: raise ValueError('Medida fora do intervalo permitido.')
        return n
    def dimensions(op):
        return tuple(int(number(op[k], 1, 4096)) for k in ('width', 'height'))
    image = image.convert('RGBA')
    for op in operations:
        kind = op.get('op')
        if kind == 'crop':
            box = op['box']
            if len(box) != 4: raise ValueError('Recorte deve ter [esquerda, topo, direita, base].')
            l,t,r,b = map(int,box)
            if not (0 <= l < r <= image.width and 0 <= t < b <= image.height): raise ValueError('Recorte fora da imagem.')
            image = image.crop((l,t,r,b))
        elif kind in {'resize', 'fit', 'contain'}:
            size = dimensions(op)
            image = (ImageOps.fit(image, size) if kind == 'fit' else ImageOps.contain(image,size) if kind == 'contain'
                     else image.resize(size, Image.Resampling.LANCZOS))
        elif kind == 'rotate': image = image.rotate(number(op['degrees'],-360,360), expand=True, resample=Image.Resampling.BICUBIC)
        elif kind == 'flip': image = ImageOps.mirror(image) if op.get('axis','horizontal')=='horizontal' else ImageOps.flip(image)
        elif kind in {'brightness','contrast','saturation','sharpness'}:
            alpha = image.getchannel('A'); rgb=image.convert('RGB')
            if kind=='brightness': base=Image.new('RGB',image.size,'black')
            elif kind=='saturation': base=rgb.convert('L').convert('RGB')
            elif kind=='sharpness': base=rgb.filter(ImageFilter.SMOOTH)
            else:
                mean=round(float(np.asarray(rgb.convert('L')).mean()));base=Image.new('RGB',image.size,(mean,mean,mean))
            image=Image.blend(base,rgb,number(op['factor'],0,5)).convert('RGBA');image.putalpha(alpha)
        elif kind == 'blur': image = image.filter(ImageFilter.GaussianBlur(number(op.get('radius',2),0,50)))
        elif kind == 'opacity': image.putalpha(image.getchannel('A').point(lambda x:round(x*number(op['factor'],0,1))))
        elif kind == 'tint':
            color = ImageColor.getrgb(op['color']); alpha=image.getchannel('A'); image=Image.new('RGBA',image.size,color);image.putalpha(alpha)
        elif kind == 'remove_background':
            if op.get('mode','auto') == 'color':
                color=np.array(ImageColor.getrgb(op.get('color','#ffffff'))[:3], dtype=float); pixels=np.array(image)
                distance=np.sqrt(np.sum((pixels[:,:,:3].astype(float)-color)**2,axis=2)); tolerance=number(op.get('tolerance',35),0,441)
                pixels[:,:,3] = np.where(distance<=tolerance,0,pixels[:,:,3]); image=Image.fromarray(pixels)
            else: image=remove_background(image)
        elif kind == 'trim':
            box=image.getchannel('A').getbbox()
            if box: image=image.crop(box)
        elif kind in {'canvas','composite'}:
            if kind=='canvas':
                canvas=Image.new('RGBA',dimensions(op),ImageColor.getcolor(op.get('color','#00000000'),'RGBA')); overlay=image
            else: canvas=image.copy();overlay=resolve(op['source']).convert('RGBA')
            if 'width' in op and kind=='composite': overlay=ImageOps.contain(overlay,dimensions(op))
            if 'opacity' in op: overlay.putalpha(overlay.getchannel('A').point(lambda x:round(x*number(op['opacity'],0,1))))
            x=int(number(op.get('x',0),-4096,4096));y=int(number(op.get('y',0),-4096,4096));canvas.alpha_composite(overlay,(x,y));image=canvas
        elif kind == 'text':
            size=int(number(op.get('size',24),6,240)); text=str(op.get('text',''))[:1000]
            try: font=ImageFont.truetype('DejaVuSans.ttf',size)
            except OSError: font=ImageFont.load_default(size=size)
            ImageDraw.Draw(image).text((number(op.get('x',0),-4096,4096),number(op.get('y',0),-4096,4096)),text,font=font,fill=ImageColor.getcolor(op.get('color','#ffffff'),'RGBA'))
        elif kind == 'border': image=ImageOps.expand(image,border=int(number(op.get('width',1),0,200)),fill=ImageColor.getcolor(op.get('color','#ffffff'),'RGBA'))
        else: raise ValueError('Operação de imagem desconhecida: '+str(kind))
        if image.width*image.height>16777216: raise ValueError('Imagem resultante grande demais.')
    out=io.BytesIO();image.save(out,'WEBP',quality=95,method=4)
    if len(out.getvalue())>MAX_ASSET: raise ValueError('Recurso maior que 700 KB; reduza antes de salvar.')
    return out.getvalue(),image.width,image.height


def raster(raw):
    from PIL import Image, ImageOps
    if not raw or len(raw) > MAX_INPUT:
        raise ValueError('Imagem maior que 4 MB.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in {'PNG', 'JPEG', 'WEBP', 'GIF', 'ICO'} or img.width * img.height > 20000000:
                raise ValueError('Use uma imagem PNG, JPEG, WebP, GIF ou ICO de até 20 megapixels.')
            img = ImageOps.exif_transpose(img).convert('RGBA')
            img.thumbnail((2048, 2048))
            out = io.BytesIO(); img.save(out, 'WEBP', quality=90, method=4)
            if len(out.getvalue()) > MAX_ASSET:
                out = io.BytesIO(); img.thumbnail((1400, 1400)); img.save(out, 'WEBP', quality=80)
            if len(out.getvalue()) > MAX_ASSET:
                raise ValueError('Imagem complexa demais; reduza a resolução.')
            return out.getvalue(), img.width, img.height


def attachments(items):
    if not isinstance(items, list) or len(items) > 4:
        raise ValueError('Envie no máximo quatro imagens por pedido.')
    result = []
    for i, item in enumerate(items):
        value = item.get('data', '') if isinstance(item, dict) else ''
        if not isinstance(value, str) or len(value) > MAX_INPUT * 4 // 3 + 200:
            raise ValueError('Imagem inválida ou maior que 4 MB.')
        if not re.fullmatch(r'data:image/(?:png|jpeg|webp|gif|x-icon|vnd.microsoft.icon);base64,[A-Za-z0-9+/=]+', value):
            raise ValueError('Envie um arquivo de imagem válido.')
        raw, width, height = raster(base64.b64decode(value.split(',', 1)[1], validate=True))
        result.append({'id': f'imagem{i+1}', 'name': str(item.get('name') or f'Imagem {i+1}')[:120],
                       'width': width, 'height': height, 'data': 'data:image/webp;base64,' + base64.b64encode(raw).decode('ascii')})
    return result


def safe_svg(raw):
    if len(raw) > MAX_ASSET or b'<!' in raw:
        raise ValueError('SVG inválido ou com declarações externas.')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('O arquivo não é SVG.')
    allowed = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line', 'defs',
               'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'title', 'desc', 'use'}
    for node in root.iter():
        if node.tag.split('}')[-1] not in allowed:
            raise ValueError('SVG contém conteúdo ativo ou não suportado.')
        for attr, value in node.attrib.items():
            attr = attr.split('}')[-1].lower()
            if attr.startswith('on') or attr == 'style' or (attr == 'href' and not value.startswith('#')):
                raise ValueError('SVG contém scripts, estilos ou referências externas.')
            if re.search(r'url\(\s*["\x27]?\s*(?!#)[^\s]', value, re.I):
                raise ValueError('SVG contém referência externa.')
    return ET.tostring(root, encoding='unicode')


def public_file(url):
    import requests
    from pesquisa import _validar_url_publica
    for _ in range(6):
        url = _validar_url_publica(url)
        with requests.get(url, timeout=(4, 12), allow_redirects=False, stream=True) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get('Location', '')); continue
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_content(32768):
                raw.extend(chunk)
                if len(raw) > MAX_INPUT: raise ValueError('Arquivo maior que 4 MB.')
            raw = bytes(raw)
            return raw, response.headers.get('Content-Type', '').lower(), url
    raise ValueError('Redirecionamentos demais ao baixar a imagem.')


def download(url):
    raw, mime, url = public_file(url)
    if 'svg' in mime or raw.lstrip().startswith((b'<svg', b'<?xml')):
        return safe_svg(raw), '.svg', url
    image, _, _ = raster(raw)
    return image, '.webp', url


def inspect_page(url):
    from bs4 import BeautifulSoup
    raw, mime, source = public_file(url)
    if 'html' not in mime: raise ValueError('O endereço precisa ser uma página HTML.')
    soup = BeautifulSoup(raw, 'html.parser')
    images=[]; vectors=[]
    for node in soup.select('img,link,a'):
        value=node.get('src') or node.get('href') or ''
        if node.name=='img' or re.search(r'\.(?:svg|png|jpe?g|webp|ico)(?:[?#]|$)',value,re.I):
            images.append({'url':urljoin(source,value),'label':str(node.get('alt') or node.get('title') or node.get_text(' ',strip=True))[:120]})
        if len(images)>=50: break
    for node in soup.select('svg')[:10]:
        try: svg=safe_svg(str(node).encode())
        except (ValueError,ET.ParseError): continue
        if len(svg)<16000: vectors.append(svg)
    return {'source':source,'images':images,'inline_svg':vectors}
