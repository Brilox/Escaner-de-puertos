#!/usr/bin/env python3
"""Arma datos/catalogo_cosmeticos.json (personajes, skins y marcos con su nombre) desde la configuracion del OBB.

    python tools/ifs/extraer.py main.obb salida              # saca config_txt/ (necesita UnityPy)
    python tools/extraer_cosmeticos.py salida [idioma]       # idioma por defecto: Spanish

Lee config_txt/ItemConfig.csv (objetos: personajes y skins), config_txt/HeadFrameConfig.json (marcos) y los textos
del juego en archivos/AssetBundles/Android/config/i2languages.bundle (I2 Localization).
Solo guarda las skins permanentes (expireDay 0): las de 1, 3 o 7 dias son las mismas skins en version de prueba."""
import csv, json, os, re, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, '..', 'datos', 'catalogo_cosmeticos.json')

def textos(carpeta, idioma):
    import UnityPy
    ruta = os.path.join(carpeta, 'archivos', 'AssetBundles', 'Android', 'config', 'i2languages.bundle')
    for o in UnityPy.load(ruta).objects:
        if o.type.name != 'MonoBehaviour': continue
        t = o.read_typetree()
        if 'mTerms' not in t: continue
        langs = [l.get('Name') for l in t['mLanguages']]; i = langs.index(idioma)
        return {x['Term']: ((x['Languages'][i] or x['Languages'][0] or '').strip()) for x in t['mTerms']}
    raise SystemExit('no encontre los textos en ' + ruta)

def main():
    if len(sys.argv) < 2: print(__doc__); return 2
    carpeta = sys.argv[1]; idioma = sys.argv[2] if len(sys.argv) > 2 else 'Spanish'
    cfg = os.path.join(carpeta, 'config_txt'); tx = textos(carpeta, idioma)
    filas = list(csv.DictReader(open(os.path.join(cfg, 'ItemConfig.csv'), encoding='utf-8-sig')))
    heroes = {int(f['param1']): tx.get(f['name'], '') for f in filas if f['type'] == 'hero' and f['param1']}
    skins = {}
    for f in filas:
        if f['type'] != 'skin' or not f['jsonParam1']: continue
        j = json.loads(f['jsonParam1'])
        if j.get('expireDay'): continue
        clave = (j['heroID'], j['skinID']); oculto = bool(f['skinHide'])
        if clave not in skins or (skins[clave]['oculto'] and not oculto):   # prefiere la fila visible en la tienda
            skins[clave] = dict(heroe=j['heroID'], skin=j['skinID'], nombre=tx.get(f['name'], ''),
                                calidad=int(f['quality'] or 0), oculto=oculto)
    texto = open(os.path.join(cfg, 'HeadFrameConfig.json'), encoding='utf-8-sig').read()
    marcos = json.loads(re.sub(r',\s*([\]}])', r'\1', texto))['headFrames']      # el json del juego trae comas sobrantes
    out = dict(
        personajes={str(k): v for k, v in sorted(heroes.items())},
        skins=sorted(skins.values(), key=lambda s: (s['heroe'], s['skin'])),
        marcos=[dict(id=m['id'], condicion=m['conditionType'], parametros=m['conditionParams'],
                     nombre=tx.get(m['headName'], ''), descripcion=tx.get(m['desc'], '')) for m in marcos])
    json.dump(out, open(SALIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('%d personajes, %d skins, %d marcos -> %s' % (len(heroes), len(skins), len(marcos), os.path.normpath(SALIDA)))

if __name__ == '__main__':
    sys.exit(main())
