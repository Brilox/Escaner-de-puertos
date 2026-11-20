#!/usr/bin/env python3
"""Anota los marcos nuevos en las tablas de iconos y efectos del juego (dentro de global_info.bundle).

    python registrar_iconos.py <global_info.bundle> <marcos_nuevos.json> <salida.bundle>

El juego NO busca la imagen de un marco directamente en headframe.bundle: ItemIconSet.ApplyItemIcon busca el nombre
("chinese/common/headframe/<icono>") en la tabla ItemIconSet de global_info.bundle, que dice en que bundle esta y
como se llama el Sprite. Si el nombre no esta en la tabla, el marco queda vacio sin ningun error en el log (lo que
paso en la primera prueba). Los efectos animados funcionan igual con la tabla HeadFrameEffectSet (nombre del efecto ->
prefab en effects/prefab/ui/headframe/prefab).

Con el mod "Metal Offline V2" hay que partir del global_info.bundle DEL MOD (tools/actualizacion/extraer_mod.py),
no del original del OBB, para no perder sus cambios."""
import hashlib, json, os, sys
import UnityPy

B_IMG = 'gui/textures/items/chinese/common/headframe'
B_FX = 'effects/prefab/ui/headframe/prefab'


def asset_id(nombre):
    return hashlib.md5(('metalonline:' + nombre).encode('utf-8')).hexdigest()   # GUID inventado pero estable y unico


def registrar(bundle_in, spec, salida):
    env = UnityPy.load(bundle_in)
    iconos = efectos = None
    for o in env.objects:
        if o.type.name != 'MonoBehaviour': continue
        try: t = o.read_typetree()
        except Exception: continue
        if t.get('m_Name') == 'ItemIconSet' and 'itemIconsByLanguage' in t: iconos = (o, t)
        elif t.get('m_Name') == 'HeadFrameEffectSet' and 'goArr' in t: efectos = (o, t)
    if not iconos or not efectos: raise SystemExit('no encontre ItemIconSet o HeadFrameEffectSet en ' + bundle_in)
    (oi, ti), (oe, te) = iconos, efectos
    chino = next(x for x in ti['itemIconsByLanguage'] if x['language'].lower() == 'chinese')
    ya_i = {x['name'] for x in chino['itemIcons']}; ya_e = {x['name'] for x in te['goArr']}
    hechos = []
    for m in spec['marcos']:
        n = m['nombre'].lower()
        clave = 'chinese/common/headframe/' + n
        if clave not in ya_i:
            chino['itemIcons'].append(dict(name=clave, iconAsset=dict(assetId=asset_id(clave), bundle=B_IMG, parentAssetName=n,
                                                                        assetName=n, typeName='UnityEngine.Sprite')))
            hechos.append(clave)
        e = m.get('efecto') or {}
        fx = (n + '_fx') if (e.get('base') or e.get('animacion')) else None
        if fx and fx not in ya_e:
            te['goArr'].append(dict(name=fx, goAsset=dict(assetId=asset_id(fx), bundle=B_FX, parentAssetName=fx, assetName=fx,
                                                          typeName='UnityEngine.GameObject')))
            hechos.append(fx)
    oi.save_typetree(ti); oe.save_typetree(te)
    with open(salida, 'wb') as f: f.write(env.file.save(packer='original'))   # mismas banderas que el original (LZ4HC, sin 0x80)
    return hechos


def comprobar(bundle, spec):
    """Vuelve a abrir el bundle y confirma que estan todas las entradas."""
    env = UnityPy.load(bundle); nombres = set()
    for o in env.objects:
        if o.type.name != 'MonoBehaviour': continue
        try: t = o.read_typetree()
        except Exception: continue
        if t.get('m_Name') == 'ItemIconSet':
            for x in t['itemIconsByLanguage']: nombres |= {i['name'] for i in x['itemIcons']}
        if t.get('m_Name') == 'HeadFrameEffectSet': nombres |= {g['name'] for g in t['goArr']}
    faltan = [m['nombre'] for m in spec['marcos'] if 'chinese/common/headframe/' + m['nombre'].lower() not in nombres]
    if faltan: raise SystemExit('faltan en la tabla: %s' % faltan)
    return len(nombres)


if __name__ == '__main__':
    if len(sys.argv) != 4: print(__doc__); sys.exit(2)
    spec = json.load(open(sys.argv[2], encoding='utf-8'))
    for h in registrar(sys.argv[1], spec, sys.argv[3]): print('  anotado:', h)
    print('comprobado: %d nombres en las tablas' % comprobar(sys.argv[3], spec))
