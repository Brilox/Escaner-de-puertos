#!/usr/bin/env python3
"""Agrega marcos NUEVOS (imagenes) al bundle de marcos del juego, sin quitar ni cambiar los que ya estan.

    python agregar_marcos.py <headframe.bundle original> <salida.bundle> <nombre>=<imagen.png> [<nombre>=<imagen.png> ...]

El bundle es AssetBundles/Android/gui/textures/items/chinese/common/headframe.bundle (Unity 2018.4.32f1).
Por cada marco crea una textura propia (ETC2 RGBA8, el formato del atlas original) y un Sprite rectangular, y los
registra en el indice del bundle como assets/ufo/gui/textures/items/chinese/common/headframe/<nombre>.png.
El juego busca la imagen de un marco por el campo "icon" de HeadFrameConfig: "common/HeadFrame/<nombre>"
(MetalFury.ItemIconSet.ApplyItemIcon arma la ruta en minusculas), asi que el nombre va en minusculas y sin espacios.
Requiere UnityPy (pip install UnityPy) y Pillow."""
import copy, os, random, struct, sys
import UnityPy
from PIL import Image

RUTA = 'assets/ufo/gui/textures/items/chinese/common/headframe/'
PPU = 100.0                                                       # pixeles por unidad, como los sprites originales

def nuevo_id(sf):
    while True:
        i = random.randint(-2**62, 2**62)
        if i and i not in sf.objects: return i

def clonar(sf, reader, pid):
    r = copy.copy(reader); r.path_id = pid; sf.objects[pid] = r
    return r

def quad(w, h):
    """Malla de 4 vertices (posicion float3 en el flujo 0, uv float2 en el flujo 1) y 6 indices uint16."""
    x0, x1, y0, y1 = -w / 2 / PPU, w / 2 / PPU, -h / 2 / PPU, h / 2 / PPU
    pos = [(x0, y1), (x1, y1), (x0, y0), (x1, y0)]; uv = [(0, 1), (1, 1), (0, 0), (1, 0)]
    s0 = b''.join(struct.pack('<3f', x, y, 0) for x, y in pos)
    s1 = b''.join(struct.pack('<2f', u, v) for u, v in uv)
    pad = (-len(s0)) % 16
    datos = s0 + b'\0' * pad + s1
    idx = struct.pack('<6H', 0, 1, 2, 2, 1, 3)
    return datos, list(idx), len(s0) + pad

def agregar(entrada, salida, marcos, solo_cuerpo=()):
    env = UnityPy.load(entrada)
    objs = list(env.objects); sf = objs[0].assets_file
    ab_r = next(o for o in objs if o.type.name == 'AssetBundle')
    tex_r = next(o for o in objs if o.type.name == 'Texture2D')
    spr_r = next(o for o in objs if o.type.name == 'Sprite')
    ab = ab_r.read_typetree(); base_tex = tex_r.read_typetree(); base_spr = spr_r.read_typetree()
    existentes = {k for k, _ in ab['m_Container']}
    for nombre, png in marcos:
        nombre = nombre.lower(); clave = RUTA + nombre + '.png'
        if clave in existentes: raise SystemExit('ya existe un marco llamado ' + nombre)
        img = Image.open(png).convert('RGBA'); w, h = img.size
        if nombre in solo_cuerpo:                     # marco con animacion exacta: el resplandor lo pone la animacion
            al = img.getchannel('A').point(lambda v: v if v >= 217 else 0); img.putalpha(al)
        # ---- textura: se clona la del atlas y se le pone la imagen nueva (datos dentro del objeto, sin .resS)
        tid = nuevo_id(sf); tr = clonar(sf, tex_r, tid)
        t = copy.deepcopy(base_tex)
        t.update(m_Name=nombre + '_tex', m_Width=w, m_Height=h, m_IsReadable=False, m_MipCount=1,
                 m_StreamData={'offset': 0, 'size': 0, 'path': ''})
        tr.save_typetree(t)
        tex = tr.read(); tex.m_Name = nombre + '_tex'; tex.set_image(img, target_format=tex.m_TextureFormat, mipmap_count=1); tex.save()
        # ---- sprite rectangular que usa esa textura
        sid = nuevo_id(sf); sr = clonar(sf, spr_r, sid)
        s = copy.deepcopy(base_spr); rd = s['m_RD']
        datos, idx, off1 = quad(w, h)
        s.update(m_Name=nombre, m_Rect={'x': 0.0, 'y': 0.0, 'width': float(w), 'height': float(h)},
                 m_Offset={'x': 0.0, 'y': 0.0}, m_Pivot={'x': .5, 'y': .5}, m_IsPolygon=False, m_PhysicsShape=[],
                 m_AtlasTags=[], m_SpriteAtlas={'m_FileID': 0, 'm_PathID': 0})
        s['m_RenderDataKey'] = [{'data[0]': random.getrandbits(32), 'data[1]': random.getrandbits(32),
                                 'data[2]': random.getrandbits(32), 'data[3]': random.getrandbits(32)}, 21300000]
        rd['texture'] = {'m_FileID': 0, 'm_PathID': tid}
        rd['m_SubMeshes'] = [dict(rd['m_SubMeshes'][0], indexCount=6, vertexCount=4, firstByte=0, baseVertex=0, firstVertex=0)]
        rd['m_IndexBuffer'] = idx
        vd = rd['m_VertexData']; vd['m_VertexCount'] = 4; vd['m_DataSize'] = datos
        vd['m_Channels'][4] = {'stream': 1, 'offset': 0, 'format': 0, 'dimension': 2}
        rd['textureRect'] = {'x': 0.0, 'y': 0.0, 'width': float(w), 'height': float(h)}
        rd['textureRectOffset'] = {'x': 0.0, 'y': 0.0}; rd['atlasRectOffset'] = {'x': -1.0, 'y': -1.0}
        rd['settingsRaw'] = 0                                      # sin empaquetar, malla rectangular
        rd['uvTransform'] = {'x': PPU, 'y': w / 2, 'z': PPU, 'w': h / 2}
        sr.save_typetree(s)
        # ---- indice del bundle: la ruta apunta al sprite y precarga sprite + textura
        ab['m_PreloadTable'] += [{'m_FileID': 0, 'm_PathID': sid}, {'m_FileID': 0, 'm_PathID': tid}]
        ab['m_Container'].append((clave, {'preloadIndex': len(ab['m_PreloadTable']) - 2, 'preloadSize': 2,
                                          'asset': {'m_FileID': 0, 'm_PathID': sid}}))
        print('agregado', clave, '%dx%d' % (w, h))
    ab['m_Container'].sort(key=lambda kv: kv[0])                   # Unity lo guarda ordenado (multimap)
    ab_r.save_typetree(ab)
    open(salida, 'wb').write(env.file.save(packer='original'))
    print('guardado', salida, os.path.getsize(salida), 'bytes')

if __name__ == '__main__':
    if len(sys.argv) < 4: print(__doc__); sys.exit(2)
    agregar(sys.argv[1], sys.argv[2], [a.split('=', 1) for a in sys.argv[3:]])
