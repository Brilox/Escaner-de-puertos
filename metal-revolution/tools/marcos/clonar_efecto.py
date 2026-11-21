#!/usr/bin/env python3
"""Crea un efecto de marco NUEVO clonando uno del juego, con otro nombre, otro color y (opcional) una animacion propia.

    python clonar_efecto.py <prefab.bundle> <salida.bundle> <efecto_base> <efecto_nuevo> [--tinte RRGGBB]
                            [--cuadros hoja.png COLUMNAS FILAS NOMBRE_PARTICULA [VUELTAS]]

El bundle es AssetBundles/Android/effects/prefab/ui/headframe/prefab.bundle (Unity 2018.4.32f1). Los efectos son
prefabs sin scripts: una raiz con Animator, mallas de brillo (flow/glow, animadas con curvas de material) y
particulas. Se copian todos los objetos del prefab (GameObjects, Transforms, componentes, materiales, mallas,
controlador y clips de animacion) con ids nuevos, se rehacen las referencias internas y se registra en el indice
como assets/ufo/effects/prefab/ui/headframe/prefab/<efecto_nuevo>.prefab. Los shaders y texturas de otros bundles
se siguen usando tal cual. El juego carga el efecto por el campo "effect" de HeadFrameConfig.

--tinte cambia el color de todos los materiales (_TintColor) y el color inicial de las particulas.
--cuadros pone una hoja de animacion cuadro por cuadro (Texture Sheet Animation) en la particula indicada:
  crea una textura nueva dentro del bundle, un material propio y ajusta la grilla y las vueltas por vida."""
import argparse, copy, os, random, sys
import UnityPy
from PIL import Image

RUTA = 'assets/ufo/effects/prefab/ui/headframe/prefab/'

def es_ref(x): return isinstance(x, dict) and set(x) == {'m_FileID', 'm_PathID'}

def refs(x, out):
    if es_ref(x):
        if x['m_FileID'] == 0 and x['m_PathID']: out.add(x['m_PathID'])
    elif isinstance(x, dict):
        for v in x.values(): refs(v, out)
    elif isinstance(x, list):
        for v in x: refs(v, out)
    elif isinstance(x, tuple):
        for v in x: refs(v, out)
    return out

def remap(x, m):
    if es_ref(x):
        return {'m_FileID': 0, 'm_PathID': m[x['m_PathID']]} if x['m_FileID'] == 0 and x['m_PathID'] in m else x
    if isinstance(x, dict): return {k: remap(v, m) for k, v in x.items()}
    if isinstance(x, list): return [remap(v, m) for v in x]
    if isinstance(x, tuple): return tuple(remap(v, m) for v in x)
    return x

def hex_rgb(h): h = h.lstrip('#'); return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

def clonar(entrada, salida, base, nuevo, tinte=None, cuadros=None):
    env = UnityPy.load(entrada); O = {o.path_id: o for o in env.objects}; sf = next(iter(O.values())).assets_file
    ab_r = next(o for o in O.values() if o.type.name == 'AssetBundle'); ab = ab_r.read_typetree()
    cont = dict(ab['m_Container']); nuevo = nuevo.lower()
    kb = RUTA + base.lower() + '.prefab'; kn = RUTA + nuevo + '.prefab'
    if kb not in cont: raise SystemExit('no existe el efecto ' + base)
    if kn in cont: raise SystemExit('ya existe el efecto ' + nuevo)
    ent = cont[kb]
    # 1) todos los objetos internos alcanzables desde la raiz del prefab (por referencias con FileID 0)
    trees, pend = {}, [ent['asset']['m_PathID']]
    while pend:
        pid = pend.pop()
        if pid in trees or pid not in O or O[pid].type.name == 'AssetBundle': continue
        trees[pid] = O[pid].read_typetree(); pend += list(refs(trees[pid], set()) - set(trees))
    usados = set()
    def nid():
        while True:
            i = random.randint(-2**62, 2**62)
            if i and i not in O and i not in usados: usados.add(i); return i
    m = {pid: nid() for pid in trees}
    tipos = {}
    for pid, t in trees.items(): tipos[O[pid].type.name] = tipos.get(O[pid].type.name, 0) + 1
    print('copiando', len(trees), 'objetos de', base, dict(sorted(tipos.items())))
    nuevos = {}
    for pid, t in trees.items():
        t = remap(copy.deepcopy(t), m)
        if O[pid].type.name == 'GameObject' and pid == ent['asset']['m_PathID']: t['m_Name'] = nuevo
        nuevos[m[pid]] = (O[pid], t)
    # 2) color
    if tinte:
        r, g, b = hex_rgb(tinte)
        for nid_, (src, t) in nuevos.items():
            if src.type.name == 'Material':
                t['m_Name'] = t['m_Name'] + '_' + nuevo
                t['m_SavedProperties']['m_Colors'] = [(k, dict(v, r=r * max(v['r'], v['g'], v['b']) / max(r, g, b, 1e-6),
                                                             g=g * max(v['r'], v['g'], v['b']) / max(r, g, b, 1e-6),
                                                             b=b * max(v['r'], v['g'], v['b']) / max(r, g, b, 1e-6))
                                                       if k in ('_TintColor', '_Color') else v)
                                                      for k, v in t['m_SavedProperties']['m_Colors']]
            if src.type.name == 'ParticleSystem':
                sc = t['InitialModule']['startColor']
                for c in ('maxColor', 'minColor'):
                    if c in sc: sc[c] = dict(sc[c], r=r, g=g, b=b)
    # 3) animacion cuadro por cuadro en una particula
    extra = []
    if cuadros:
        hoja, cols, filas, part, vueltas = cuadros
        go = next((k for k, (s, t) in nuevos.items() if s.type.name == 'GameObject' and t['m_Name'] == part), None)
        if go is None: raise SystemExit('no hay una particula llamada ' + part + ' en ' + base)
        comp = [c['component']['m_PathID'] for c in nuevos[go][1]['m_Component']]
        ps = next(c for c in comp if nuevos[c][0].type.name == 'ParticleSystem')
        pr = next(c for c in comp if nuevos[c][0].type.name == 'ParticleSystemRenderer')
        uv = nuevos[ps][1]['UVModule']; uv.update(enabled=True, tilesX=int(cols), tilesY=int(filas), cycles=float(vueltas))
        if 'mode' in uv: uv['mode'] = 0
        # textura nueva (clon de una textura del juego) y material propio que la usa
        tex_src = next(o for o in O.values() if o.type.name == 'Texture2D')
        tid = nid(); tr = copy.copy(tex_src); tr.path_id = tid; sf.objects[tid] = tr
        tt = tex_src.read_typetree(); img = Image.open(hoja).convert('RGBA')
        tt.update(m_Name=nuevo + '_cuadros', m_Width=img.width, m_Height=img.height, m_MipCount=1, m_StreamData={'offset': 0, 'size': 0, 'path': ''})
        tr.save_typetree(tt); tx = tr.read(); tx.m_Name = nuevo + '_cuadros'; tx.set_image(img, target_format=47, mipmap_count=1); tx.save()
        rend = nuevos[pr][1]; mat_ref = rend['m_Materials'][0]
        if mat_ref['m_FileID'] == 0 and mat_ref['m_PathID'] in nuevos:
            mt = nuevos[mat_ref['m_PathID']][1]
        else:
            # material de otro bundle: se copia un material de particulas de este bundle (mismo tipo de shader)
            plantilla = None
            for o in O.values():
                if o.type.name == 'ParticleSystemRenderer':
                    mr = o.read_typetree()['m_Materials']
                    if mr and mr[0]['m_FileID'] == 0 and mr[0]['m_PathID'] in O: plantilla = O[mr[0]['m_PathID']]; break
            if plantilla is None: raise SystemExit('no hay materiales de particulas en este bundle para copiar')
            mid = nid(); mt = plantilla.read_typetree(); mt['m_Name'] = nuevo + '_cuadros'
            nuevos[mid] = (plantilla, mt); rend['m_Materials'][0] = {'m_FileID': 0, 'm_PathID': mid}; extra.append(mid)
            print('material de particula copiado de', plantilla.read_typetree()['m_Name'])
        mt['m_SavedProperties']['m_TexEnvs'] = [(k, dict(v, m_Texture={'m_FileID': 0, 'm_PathID': tid}) if k == '_MainTex' else v)
                                                for k, v in mt['m_SavedProperties']['m_TexEnvs']]
        mt['m_SavedProperties']['m_Colors'] = [(k, dict(v, r=1.0, g=1.0, b=1.0) if k in ('_TintColor', '_Color') else v)
                                               for k, v in mt['m_SavedProperties']['m_Colors']]
        sc = nuevos[ps][1]['InitialModule']['startColor']
        for c in ('maxColor', 'minColor'):
            if c in sc: sc[c] = dict(sc[c], r=1.0, g=1.0, b=1.0)
        extra.append(tid)
        print('cuadros: %s (%dx%d) en la particula %s, %s vueltas por vida' % (os.path.basename(hoja), int(cols), int(filas), part, vueltas))
    # 4) escribir objetos nuevos e indice
    for pid, (src, t) in nuevos.items():
        r = copy.copy(src); r.path_id = pid; sf.objects[pid] = r; r.save_typetree(t)
    pre = ab['m_PreloadTable'][ent['preloadIndex']:ent['preloadIndex'] + ent['preloadSize']]
    pre = [remap(p, m) for p in pre] + [{'m_FileID': 0, 'm_PathID': t} for t in extra]
    ab['m_Container'].append((kn, {'preloadIndex': len(ab['m_PreloadTable']), 'preloadSize': len(pre),
                                   'asset': {'m_FileID': 0, 'm_PathID': m[ent['asset']['m_PathID']]}}))
    ab['m_PreloadTable'] += pre
    ab['m_Container'].sort(key=lambda kv: kv[0]); ab_r.save_typetree(ab)
    open(salida, 'wb').write(env.file.save(packer='original'))
    print('efecto', nuevo, 'agregado ->', salida, os.path.getsize(salida), 'bytes')

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('entrada'); ap.add_argument('salida'); ap.add_argument('base'); ap.add_argument('nuevo')
    ap.add_argument('--tinte'); ap.add_argument('--cuadros', nargs='+', metavar='X')
    a = ap.parse_args()
    cu = None
    if a.cuadros:
        if len(a.cuadros) not in (4, 5): ap.error('--cuadros hoja.png COLUMNAS FILAS NOMBRE_PARTICULA [VUELTAS]')
        cu = (a.cuadros[0], a.cuadros[1], a.cuadros[2], a.cuadros[3], a.cuadros[4] if len(a.cuadros) == 5 else 3)
    clonar(a.entrada, a.salida, a.base, a.nuevo, a.tinte, cu)
