#!/usr/bin/env python3
"""Construye el paquete de marcos NUEVOS a partir de una sola descripcion en JSON.

    python construir.py <marcos_nuevos.json> <carpeta del juego extraida> <salida>

<carpeta del juego extraida>: la salida de tools/ifs/extraer.py con --todo (o al menos con estos tres bundles y
config_txt/HeadFrameConfig.json):
    archivos/AssetBundles/Android/gui/textures/items/chinese/common/headframe.bundle
    archivos/AssetBundles/Android/effects/prefab/ui/headframe/prefab.bundle
    archivos/AssetBundles/Android/config/i2languages.bundle

<salida> queda con la misma estructura que la carpeta del juego en el telefono
(Android/data/com.gtarcade.next.mrglo/files/), mas lo que va al servidor:
    AssetBundles/Android/gui/textures/items/chinese/common/headframe.bundle   imagenes (originales + nuevas)
    AssetBundles/Android/effects/prefab/ui/headframe/prefab.bundle            efectos (originales + nuevos)
    AssetBundles/Android/config/i2languages.bundle                            textos (originales + nuevos)
    servidor/HeadFrameConfig.json      lista completa de marcos: va a server/config_juego/activos/
    servidor/marcos.json               reglas para el servidor: va a datos/marcos.json

marcos_nuevos.json (ver datos/marcos_beta/marcos_nuevos.json):
    {"marcos": [{"id": 100, "nombre": "beta_founder", "imagen": "juego/founder_256.png",
                 "titulo": {"es": "...", "en": "..."}, "descripcion": {...}, "bloqueado": {...},
                 "efecto": {"base": "bp_max", "tinte": "ff8a3a",
                            "cuadros": {"hoja": "arana.png", "columnas": 4, "filas": 2, "particula": "1111", "vueltas": 4}}}]}
"efecto" puede ser: {"animacion": {"carpeta": "cuadros/x", "fps": 24, "columnas": 16}} (animacion EXACTA, hoja de cuadros
exportada con exportar_animaciones.js), {"base": ..., "tinte": ...} (efecto del juego copiado y recoloreado) o
{"usar": "nck_001_max"} (un efecto del juego tal cual). "calibracion": {"tamano": 1.38, "x": 0, "y": 0} ajusta el
tamano y la posicion de las animaciones exactas (ver el marco de calibracion).
Las rutas de imagenes son relativas al archivo JSON. Los marcos nuevos quedan con condicion 99 (no se ganan
jugando): se entregan desde el servidor con colaboradores.py."""
import json, os, re, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agregar_marcos, clonar_efecto, agregar_textos, efecto_cuadros

B_IMG = 'AssetBundles/Android/gui/textures/items/chinese/common/headframe.bundle'
B_FX = 'AssetBundles/Android/effects/prefab/ui/headframe/prefab.bundle'
B_TXT = 'AssetBundles/Android/config/i2languages.bundle'
ID_TEXTO = 52000                                                 # los textos del juego llegan a item/name/51081

def leer_json_juego(ruta):
    return json.loads(re.sub(r',\s*([\]}])', r'\1', open(ruta, encoding='utf-8-sig').read()))   # el juego deja comas sobrantes

def construir(spec_ruta, juego, salida):
    spec = json.load(open(spec_ruta, encoding='utf-8')); base_dir = os.path.dirname(os.path.abspath(spec_ruta))
    arch = os.path.join(juego, 'archivos')
    cfg = leer_json_juego(os.path.join(juego, 'config_txt', 'HeadFrameConfig.json'))
    ids = {f['id'] for f in cfg['headFrames']}
    for d in (B_IMG, B_FX, B_TXT): os.makedirs(os.path.dirname(os.path.join(salida, d)), exist_ok=True)
    os.makedirs(os.path.join(salida, 'servidor'), exist_ok=True)
    tmp = tempfile.mkdtemp()
    # 1) imagenes
    agregar_marcos.agregar(os.path.join(arch, B_IMG), os.path.join(salida, B_IMG),
                           [(m['nombre'], os.path.join(base_dir, m['imagen'])) for m in spec['marcos']],
                           solo_cuerpo={m['nombre'].lower() for m in spec['marcos'] if (m.get('efecto') or {}).get('animacion')
                                        and not (m['efecto']['animacion'].get('escala'))})
    # 2) efectos (uno detras de otro sobre el mismo bundle)
    actual = os.path.join(arch, B_FX); n = 0
    cal = spec.get('calibracion', {})
    for m in spec['marcos']:
        e = m.get('efecto') or {}
        if not (e.get('base') or e.get('animacion')): continue
        sig = os.path.join(tmp, 'fx%d.bundle' % n); n += 1
        if e.get('animacion'):                          # animacion exacta: hoja de cuadros exportada del motor
            an = e['animacion']
            efecto_cuadros.crear(actual, sig, m['nombre'] + '_fx', os.path.join(base_dir, an['carpeta']), an['fps'],
                                 an.get('columnas', 16), cal.get('tamano', 1.38) * an.get('escala', 1.0), cal.get('x', 0.0), cal.get('y', 0.0))
        else:                                           # efecto del juego copiado y recoloreado
            cu = e.get('cuadros')
            cu = (os.path.join(base_dir, cu['hoja']), cu['columnas'], cu['filas'], cu['particula'], cu.get('vueltas', 3)) if cu else None
            clonar_efecto.clonar(actual, sig, e['base'], m['nombre'] + '_fx', e.get('tinte'), cu)
        actual = sig
    shutil.copyfile(actual, os.path.join(salida, B_FX))
    # 3) textos y 4) configuracion
    textos = {}
    for i, m in enumerate(spec['marcos']):
        if m['id'] in ids: raise SystemExit('el id %d ya lo usa un marco del juego' % m['id'])
        k = ID_TEXTO + i
        textos['item/name/%d' % k] = m['titulo']; textos['item/desc/%d' % k] = m['descripcion']
        textos['item/lockdesc/%d' % k] = m.get('bloqueado', m['descripcion'])
        e = m.get('efecto') or {}
        fila = {'id': m['id'], 'headName': 'item/name/%d' % k, 'conditionType': 99, 'conditionParams': [],
                'desc': 'item/desc/%d' % k, 'lockDesc': 'item/lockdesc/%d' % k, 'icon': 'common/HeadFrame/' + m['nombre'].lower()}
        efecto = (m['nombre'].lower() + '_fx') if (e.get('base') or e.get('animacion')) else e.get('usar')
        if efecto: fila['effect'] = efecto
        cfg['headFrames'].append(fila)
    json.dump(textos, open(os.path.join(tmp, 'textos.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    agregar_textos.agregar(os.path.join(arch, B_TXT), os.path.join(salida, B_TXT), textos)
    json.dump(cfg, open(os.path.join(salida, 'servidor', 'HeadFrameConfig.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    reglas = [[f['id'], f['conditionType'], f['conditionParams']] for f in cfg['headFrames']]
    json.dump(reglas, open(os.path.join(salida, 'servidor', 'marcos.json'), 'w'))
    shutil.rmtree(tmp)
    print('\nlisto: %d marcos nuevos (%s) en %s' % (len(spec['marcos']), ', '.join(str(m['id']) for m in spec['marcos']), salida))

if __name__ == '__main__':
    if len(sys.argv) != 4: print(__doc__); sys.exit(2)
    construir(*sys.argv[1:])
