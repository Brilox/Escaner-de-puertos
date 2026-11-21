#!/usr/bin/env python3
"""Crea un efecto de marco NUEVO que reproduce una animacion cuadro por cuadro EXACTA (hoja de cuadros) en el juego.

    python efecto_cuadros.py <prefab.bundle> <salida.bundle> <nombre_efecto> <carpeta_cuadros> --fps 24
                             [--columnas 16] [--tamano 1.38] [--x 0] [--y 0]

<carpeta_cuadros>: PNG numerados (000.png, 001.png...) del mismo tamano y cuadrados, con fondo transparente. Es lo que
exporta el motor de animacion de los marcos (datos/marcos_beta/motor.js, modo bucle): el ultimo cuadro empalma con
el primero.

Como queda el efecto (todo con piezas que el juego ya usa, Unity 2018.4.32f1):
- una raiz y un hijo con UNA particula que vive para siempre, sin movimiento, del tamano del marco;
- la particula muestra la hoja con Texture Sheet Animation en modo FPS (cuadros por segundo fijos, en bucle);
- material con el shader del juego "UFOEffect/Alpha Blended" (mezcla alfa normal). Ese shader calcula
  2 x color de particula x _TintColor x textura: con particula blanca y _TintColor 0.5 sale la textura tal cual;
- textura ETC2 RGBA8 (el formato de las texturas del juego) dentro del mismo bundle.

Tamano: en los efectos del juego el lienzo cuadrado de la imagen del marco mide ~1.38 unidades (medido con las mascaras
de borde de bp, xc, tq, qw y sjl contra sus imagenes: entre 1.34 y 1.42). --tamano, --x e --y permiten corregirlo
despues de verlo en un telefono con el marco de calibracion."""
import argparse, copy, glob, math, os, random
import UnityPy
from PIL import Image

RUTA = 'assets/ufo/effects/prefab/ui/headframe/prefab/'
SHADER_ALPHA = 202270012880735913          # UFOEffect/Alpha Blended en shader.bundle
SHADER_CAB = 'cab-e5fc7a25e9a94a712de99f5b6bbb82a6'
PLANTILLA = 'tq_high'                       # efecto simple: raiz + una particula (star_side) + un brillo
BLANCO = {'r': 1.0, 'g': 1.0, 'b': 1.0, 'a': 1.0}

def curva(v):
    return {'minMaxState': 0, 'scalar': float(v), 'minScalar': float(v),
            'maxCurve': {'m_Curve': [], 'm_PreInfinity': 2, 'm_PostInfinity': 2, 'm_RotationOrder': 4},
            'minCurve': {'m_Curve': [], 'm_PreInfinity': 2, 'm_PostInfinity': 2, 'm_RotationOrder': 4}}

def hoja(carpeta, columnas):
    cuadros = sorted(glob.glob(os.path.join(carpeta, '*.png')))
    if not cuadros: raise SystemExit('no hay cuadros en ' + carpeta)
    a = Image.open(cuadros[0]); px = a.width
    n = len(cuadros); filas = math.ceil(n / columnas)
    if columnas * filas != n: raise SystemExit('%d cuadros no llenan una grilla de %d columnas: usar otro numero' % (n, columnas))
    img = Image.new('RGBA', (columnas * px, filas * px), (0, 0, 0, 0))
    for i, f in enumerate(cuadros):
        img.paste(Image.open(f).convert('RGBA'), ((i % columnas) * px, (i // columnas) * px))
    return img, columnas, filas, n

def compensar_lineal(img):
    """El juego mezcla en espacio de color LINEAL (PlayerSettings m_ActiveColorSpace = 1) y el navegador/video en gamma.
    Sobre fondo oscuro, el video muestra a*c (sRGB); el juego muestra lineal(a'*lineal(c)). Se elige el alfa a' que da
    lo mismo: a' = sum(lin(a*c)) / sum(lin(c)) (por luminancia). Los pixeles opacos no cambian."""
    import numpy as np
    x = np.asarray(img, dtype=np.float64) / 255.0; c, a = x[..., :3], x[..., 3:4]
    lin = lambda v: np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    num = lin(a * c).sum(-1, keepdims=True); den = lin(c).sum(-1, keepdims=True)
    a2 = np.where(den > 1e-4, num / np.maximum(den, 1e-6), a)
    a2 = np.where(a >= 0.999, a, np.clip(a2, 0, 1))
    return Image.fromarray(np.dstack([x[..., :3], a2]).__mul__(255).round().astype('uint8'), 'RGBA')

def crear(entrada, salida, nombre, carpeta, fps, columnas=16, tamano=1.38, x=0.0, y=0.0, lineal=True):
    env = UnityPy.load(entrada); O = {o.path_id: o for o in env.objects}; sf = next(iter(O.values())).assets_file
    ext = [e.path.split('/')[-1].lower() for e in sf.externals]
    fid_shader = ext.index(SHADER_CAB) + 1
    ab_r = next(o for o in O.values() if o.type.name == 'AssetBundle'); ab = ab_r.read_typetree()
    cont = dict(ab['m_Container']); nombre = nombre.lower(); clave = RUTA + nombre + '.prefab'
    if clave in cont: raise SystemExit('ya existe el efecto ' + nombre)
    usados = set()
    def nid():
        while True:
            i = random.randint(-2**62, 2**62)
            if i and i not in O and i not in usados: usados.add(i); return i
    def agregar(src, pid, tree):
        r = copy.copy(src); r.path_id = pid; sf.objects[pid] = r; r.save_typetree(tree); return r
    # ---- plantillas del efecto simple del juego
    raiz_go = O[cont[RUTA + PLANTILLA + '.prefab']['asset']['m_PathID']]
    rgt = raiz_go.read_typetree()
    comp = {O[c['component']['m_PathID']].type.name: O[c['component']['m_PathID']] for c in rgt['m_Component']}
    raiz_tr = comp['Transform']; rtt = raiz_tr.read_typetree()
    hijo = None
    for ch in rtt['m_Children']:
        t = O[ch['m_PathID']]
        g = O[t.read_typetree()['m_GameObject']['m_PathID']]
        cs = {O[c['component']['m_PathID']].type.name: O[c['component']['m_PathID']] for c in g.read_typetree()['m_Component']}
        if 'ParticleSystem' in cs: hijo = (g, t, cs['ParticleSystem'], cs['ParticleSystemRenderer'])
    g_src, rt_src, ps_src, psr_src = hijo
    mat_src = None
    for o in O.values():                              # un material de particulas de este bundle, como molde
        if o.type.name == 'ParticleSystemRenderer':
            m = o.read_typetree()['m_Materials'][0]
            if m['m_FileID'] == 0 and m['m_PathID'] in O: mat_src = O[m['m_PathID']]; break
    tex_src = next(o for o in O.values() if o.type.name == 'Texture2D')
    ids = {k: nid() for k in ('go', 'tr', 'hgo', 'hrt', 'ps', 'psr', 'mat', 'tex')}
    ref = lambda k: {'m_FileID': 0, 'm_PathID': ids[k]}
    # ---- textura con la hoja de cuadros
    img, cols, filas, n = hoja(carpeta, columnas)
    if lineal: img = compensar_lineal(img)
    tt = tex_src.read_typetree()
    tt.update(m_Name=nombre + '_hoja', m_Width=img.width, m_Height=img.height, m_MipCount=1, m_IsReadable=False,
              m_StreamData={'offset': 0, 'size': 0, 'path': ''})
    tr = agregar(tex_src, ids['tex'], tt); tx = tr.read(); tx.m_Name = nombre + '_hoja'
    tx.set_image(img, target_format=47, mipmap_count=1); tx.save()
    # ---- material: shader de mezcla alfa normal del juego, la textura tal cual
    mt = mat_src.read_typetree()
    mt['m_Name'] = nombre + '_mat'; mt['m_Shader'] = {'m_FileID': fid_shader, 'm_PathID': SHADER_ALPHA}; mt['m_ShaderKeywords'] = ''
    sp = mt['m_SavedProperties']
    sp['m_TexEnvs'] = [(k, dict(v, m_Texture=ref('tex') if k == '_MainTex' else {'m_FileID': 0, 'm_PathID': 0},
                                m_Scale={'x': 1.0, 'y': 1.0}, m_Offset={'x': 0.0, 'y': 0.0})) for k, v in sp['m_TexEnvs']]
    if not any(k == '_MainTex' for k, _ in sp['m_TexEnvs']):
        sp['m_TexEnvs'].append(('_MainTex', {'m_Texture': ref('tex'), 'm_Scale': {'x': 1.0, 'y': 1.0}, 'm_Offset': {'x': 0.0, 'y': 0.0}}))
    sp['m_Colors'] = [(k, {'r': .5, 'g': .5, 'b': .5, 'a': .5} if k == '_TintColor' else v) for k, v in sp['m_Colors']]
    sp['m_Floats'] = [(k, 0.0 if k in ('_EnableHDR', '_EnableTextureRotate') else (1.0 if k == '_ColorScale' else v)) for k, v in sp['m_Floats']]
    agregar(mat_src, ids['mat'], mt)
    # ---- sistema de particulas: una sola, eterna, quieta, del tamano del marco, mostrando la hoja a fps fijos
    p = ps_src.read_typetree(); p['m_GameObject'] = ref('hgo')
    p.update(lengthInSec=1000.0, looping=True, prewarm=False, playOnAwake=True, autoRandomSeed=True, simulationSpeed=1.0,
             startDelay=curva(0), moveWithTransform=0)
    im = p['InitialModule']
    im.update(startLifetime=curva(1e6), startSpeed=curva(0), startSize=curva(tamano), startRotation=curva(0),
              maxNumParticles=1, gravityModifier=curva(0), size3D=False, rotation3D=False, randomizeRotationDirection=0.0)
    im['startColor'] = dict(im['startColor'], minMaxState=0, maxColor=BLANCO, minColor=BLANCO)
    em = p['EmissionModule']
    em.update(rateOverTime=curva(0), rateOverDistance=curva(0), m_BurstCount=1,
              m_Bursts=[{'time': 0.0, 'countCurve': curva(1), 'cycleCount': 1, 'repeatInterval': 1000.0, 'probability': 1.0}])
    for k, v in p.items():
        if k.endswith('Module') and k not in ('InitialModule', 'EmissionModule', 'UVModule') and isinstance(v, dict) and 'enabled' in v:
            v['enabled'] = False
    uv = p['UVModule']
    uv.update(enabled=True, mode=0, timeMode=2, fps=float(fps), tilesX=cols, tilesY=filas, animationType=0, rowIndex=0,
              cycles=1.0, flipU=0.0, flipV=0.0, startFrame=curva(0))
    agregar(ps_src, ids['ps'], p)
    r = psr_src.read_typetree(); r['m_GameObject'] = ref('hgo'); r['m_Materials'] = [ref('mat')]
    r.update(m_RenderMode=0, m_RenderAlignment=0, m_Enabled=True)
    if 'm_MaxParticleSize' in r: r['m_MaxParticleSize'] = max(5.0, r['m_MaxParticleSize'])
    agregar(psr_src, ids['psr'], r)
    # ---- objetos: hijo (RectTransform en z -2 como las particulas del juego) y raiz sin Animator
    hg = g_src.read_typetree(); hg['m_Name'] = 'cuadros'
    hg['m_Component'] = [{'component': ref('hrt')}, {'component': ref('ps')}, {'component': ref('psr')}]
    agregar(g_src, ids['hgo'], hg)
    hr = rt_src.read_typetree(); hr['m_GameObject'] = ref('hgo'); hr['m_Father'] = ref('tr'); hr['m_Children'] = []
    hr['m_LocalRotation'] = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}
    hr['m_LocalPosition'] = {'x': float(x), 'y': float(y), 'z': -2.0}; hr['m_LocalScale'] = {'x': 1.0, 'y': 1.0, 'z': 1.0}
    # En un RectTransform Unity ubica el objeto con m_AnchoredPosition (no con m_LocalPosition). La plantilla (star_side de
    # tq_high) esta en el borde de arriba (y = 0.491): sin esto el efecto salia media altura de marco mas arriba.
    if 'm_AnchoredPosition' in hr: hr['m_AnchoredPosition'] = {'x': float(x), 'y': float(y)}
    agregar(rt_src, ids['hrt'], hr)
    rg = copy.deepcopy(rgt); rg['m_Name'] = nombre; rg['m_Component'] = [{'component': ref('tr')}]
    agregar(raiz_go, ids['go'], rg)
    rr = copy.deepcopy(rtt); rr['m_GameObject'] = ref('go'); rr['m_Children'] = [ref('hrt')]
    agregar(raiz_tr, ids['tr'], rr)
    # ---- indice
    pre = [ref(k) for k in ('go', 'tr', 'hgo', 'hrt', 'ps', 'psr', 'mat', 'tex')] + [{'m_FileID': fid_shader, 'm_PathID': SHADER_ALPHA}]
    ab['m_Container'].append((clave, {'preloadIndex': len(ab['m_PreloadTable']), 'preloadSize': len(pre), 'asset': ref('go')}))
    ab['m_PreloadTable'] += pre
    ab['m_Container'].sort(key=lambda kv: kv[0]); ab_r.save_typetree(ab)
    open(salida, 'wb').write(env.file.save(packer='original'))
    print('efecto %s: %d cuadros (%dx%d, hoja %dx%d) a %s fps = bucle de %.2f s, tamano %.3f -> %s'
          % (nombre, n, cols, filas, img.width, img.height, fps, n / fps, tamano, salida))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('entrada'); ap.add_argument('salida'); ap.add_argument('nombre'); ap.add_argument('cuadros')
    ap.add_argument('--fps', type=float, required=True); ap.add_argument('--columnas', type=int, default=16)
    ap.add_argument('--tamano', type=float, default=1.38); ap.add_argument('--x', type=float, default=0.0); ap.add_argument('--y', type=float, default=0.0)
    a = ap.parse_args()
    crear(a.entrada, a.salida, a.nombre, a.cuadros, a.fps, a.columnas, a.tamano, a.x, a.y)
