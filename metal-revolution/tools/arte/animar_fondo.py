#!/usr/bin/env python3
"""Fondo ANIMADO para la pantalla de inicio de sesion.

    python animar_fondo.py <mainbg_dontmove.bundle> <loginscreen.bundle> <carpeta_cuadros> <carpeta_salida> [--fps 12]

Como funciona en el juego: el fondo (objeto MainBg de gui/prefabs/loginscreen) tiene el componente UFOImageLoopUtil
(spriteAssets, changeInterval, randomFirst). En OnEnable hace InvokeRepeating("IvChangeSprite", intervalo, intervalo)
y cada vez pone en el Image el siguiente sprite de la lista (verificado en el codigo del juego). El original trae un
solo fondo y cambia cada 5 s; con varios cuadros y un intervalo de 1/fps, el fondo queda animado.

- mainbg_dontmove.bundle: el cuadro 0 reemplaza la imagen de MainBg_DontMove; los demas son copias exactas de su
  textura y su sprite (mismo formato ETC2, mismo tamano, misma malla) con nombre MainBg_DontMove_NN, cada una con su
  entrada doble en el indice del bundle (textura y sprite bajo la misma ruta, igual que el original).
- loginscreen.bundle: la lista spriteAssets del componente pasa a tener todos los cuadros, changeInterval = 1/fps y
  randomFirst = 0 (siempre empieza en el cuadro 0, que es el que ya existia).
Salida: <carpeta_salida>/AssetBundles/Android/gui/... con los dos bundles, lista para una actualizacion."""
import argparse, copy, glob, hashlib, os, random
import UnityPy
from PIL import Image

B_FONDO = 'gui/textures/arranged/settingsscreen_common/mainbg_dontmove'
RUTA = 'assets/ufo/gui/textures/arranged/settingsscreen_common/'


def nuevo_id(sf, usados):
    while True:
        i = random.randint(-2 ** 62, 2 ** 62)
        if i and i not in sf.objects and i not in usados: usados.add(i); return i


def poner_imagen(obj, img):
    tt = obj.read_typetree(); tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}; tt['m_MipCount'] = 1
    obj.save_typetree(tt); t = obj.read()
    if img.size != (t.m_Width, t.m_Height): img = img.resize((t.m_Width, t.m_Height), Image.LANCZOS)
    t.set_image(img.convert('RGBA'), target_format=t.m_TextureFormat, mipmap_count=1); t.save()


def armar(fondo_in, login_in, carpeta, salida, fps):
    cuadros = sorted(glob.glob(os.path.join(carpeta, '*.png')))
    if len(cuadros) < 2: raise SystemExit('hacen falta al menos 2 cuadros en ' + carpeta)
    # ---------------- bundle del fondo
    env = UnityPy.load(fondo_in); objs = list(env.objects); sf = objs[0].assets_file
    ab_r = next(o for o in objs if o.type.name == 'AssetBundle'); ab = ab_r.read_typetree()
    tex0 = next(o for o in objs if o.type.name == 'Texture2D')
    spr0 = next(o for o in objs if o.type.name == 'Sprite')
    base_t, base_s = tex0.read_typetree(), spr0.read_typetree()
    poner_imagen(tex0, Image.open(cuadros[0]))
    base_t = tex0.read_typetree()
    nombres = [base_s['m_Name']]; usados = set()
    for i, c in enumerate(cuadros[1:], 1):
        nombre = '%s_%02d' % (base_s['m_Name'], i)
        tid, sid = nuevo_id(sf, usados), nuevo_id(sf, usados)
        tr = copy.copy(tex0); tr.path_id = tid; sf.objects[tid] = tr
        t = copy.deepcopy(base_t); t['m_Name'] = nombre; tr.save_typetree(t); poner_imagen(tr, Image.open(c))
        sr = copy.copy(spr0); sr.path_id = sid; sf.objects[sid] = sr
        s = copy.deepcopy(base_s); s['m_Name'] = nombre; s['m_RD']['texture'] = {'m_FileID': 0, 'm_PathID': tid}
        g = hashlib.md5(nombre.encode()).digest()
        s['m_RenderDataKey'] = ({'data[%d]' % k: int.from_bytes(g[4 * k:4 * k + 4], 'little') for k in range(4)}, base_s['m_RenderDataKey'][1])
        sr.save_typetree(s)
        clave = RUTA + nombre.lower() + '.png'; idx = len(ab['m_PreloadTable'])
        ab['m_PreloadTable'] += [{'m_FileID': 0, 'm_PathID': tid}, {'m_FileID': 0, 'm_PathID': sid}]
        for a in (tid, sid):     # como el original: la textura y el sprite bajo la misma ruta
            ab['m_Container'].append((clave, {'preloadIndex': idx, 'preloadSize': 2, 'asset': {'m_FileID': 0, 'm_PathID': a}}))
        nombres.append(nombre)
    ab['m_Container'].sort(key=lambda kv: kv[0]); ab_r.save_typetree(ab)
    d_fondo = os.path.join(salida, 'AssetBundles', 'Android', *B_FONDO.split('/')[:-1]); os.makedirs(d_fondo, exist_ok=True)
    open(os.path.join(d_fondo, 'mainbg_dontmove.bundle'), 'wb').write(env.file.save(packer='original'))
    # ---------------- pantalla de inicio: lista de cuadros e intervalo
    env2 = UnityPy.load(login_in); hecho = False
    for o in env2.objects:
        if o.type.name != 'MonoBehaviour': continue
        try: t = o.read_typetree()
        except Exception: continue
        if 'spriteAssets' in t and 'changeInterval' in t and any(x.get('bundle') == B_FONDO for x in t['spriteAssets']):
            molde = next(x for x in t['spriteAssets'] if x.get('bundle') == B_FONDO)
            lista = [molde]
            for n in nombres[1:]:
                lista.append(dict(molde, assetId=hashlib.md5(('metalonline:' + n).encode()).hexdigest(), parentAssetName=n, assetName=n))
            t['spriteAssets'] = lista; t['changeInterval'] = round(1.0 / fps, 4); t['randomFirst'] = 0
            o.save_typetree(t); hecho = True
    if not hecho: raise SystemExit('no encontre el componente del fondo en ' + login_in)
    d_login = os.path.join(salida, 'AssetBundles', 'Android', 'gui', 'prefabs'); os.makedirs(d_login, exist_ok=True)
    open(os.path.join(d_login, 'loginscreen.bundle'), 'wb').write(env2.file.save(packer='original'))
    return nombres


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('fondo'); ap.add_argument('login'); ap.add_argument('cuadros'); ap.add_argument('salida')
    ap.add_argument('--fps', type=float, default=12)
    a = ap.parse_args()
    n = armar(a.fondo, a.login, a.cuadros, a.salida, a.fps)
    print('fondo animado: %d cuadros a %g fps (%s ... %s)' % (len(n), a.fps, n[0], n[-1]))
