#!/usr/bin/env python3
"""Arma UN archivo de actualizacion (.mrupd) con todo lo que cambia: archivos del telefono y cambios del servidor.

    python crear_actualizacion.py <salida.mrupd> --version N --nombre "Marcos beta" --mensaje "Texto para los jugadores"
                                  --telefono <carpeta> [--servidor <carpeta>] [--marcos-nuevos marcos_nuevos.json]
                                  [--opcional]

--telefono: carpeta con la misma estructura que la del juego en el telefono
            (Android/data/com.gtarcade.next.mrglo/files/). Todo lo que haya dentro va al paquete, por ejemplo
            AssetBundles/Android/gui/textures/items/chinese/common/headframe.bundle
--servidor: carpeta con configuraciones para los telefonos (*.json, *.csv que van a config_juego/activos) y, si esta,
            marcos.json (reglas de los marcos del servidor)
--marcos-nuevos: el JSON de tools/marcos/construir.py; registra los marcos nuevos (id y nombre) en el catalogo del panel.
--mod-apk: el APK del mod; agrega al paquete los bundles que el mod modifica (extraer_mod.py), para que el
            actualizador no los reemplace por los originales del OBB. Usarlo SIEMPRE con el mod "Metal Offline V2".
Por defecto la actualizacion es obligatoria; --opcional la deja como opcional.

Con tools/marcos/construir.py la salida ya trae las dos carpetas: <salida>/AssetBundles (telefono) y <salida>/servidor:
    python crear_actualizacion.py marcos_beta.mrupd --version 1 --nombre "Marcos beta" --mensaje "..." \\
        --telefono <salida_construir> --servidor <salida_construir>/servidor --marcos-nuevos datos/marcos_beta/marcos_nuevos.json
(de --telefono se toma solo lo que no esta dentro de servidor/). El formato esta descrito en server/actualizaciones.py."""
import argparse, hashlib, json, os, sys, time, zipfile

def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def crear(salida, version, nombre, mensaje, telefono, servidor=None, marcos_nuevos=None, obligatoria=True, mod_apk=None):
    archivos = []
    if mod_apk:
        import tempfile
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import extraer_mod
        tmp = tempfile.mkdtemp()
        hechos = extraer_mod.extraer(mod_apk, tmp)
        gi = 'AssetBundles/Android/config/global_info.bundle'
        if marcos_nuevos and gi in hechos:
            # los marcos nuevos tienen que estar anotados en las tablas de iconos y efectos de global_info.bundle
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'marcos'))
            import registrar_iconos
            ruta_gi = os.path.join(tmp, *gi.split('/')); spec = json.load(open(marcos_nuevos, encoding='utf-8'))
            n = registrar_iconos.registrar(ruta_gi, spec, ruta_gi + '.nuevo'); os.replace(ruta_gi + '.nuevo', ruta_gi)
            registrar_iconos.comprobar(ruta_gi, spec); print('  global_info.bundle: %d entradas nuevas en las tablas de iconos y efectos' % len(n))
        elif marcos_nuevos:
            print('  OJO: hay marcos nuevos pero no se pudo anotarlos en global_info.bundle (usa --mod-apk)')
        for r in hechos:
            archivos.append((r, os.path.join(tmp, *r.split('/')))); print('  del mod:', r)
    serv_abs = os.path.abspath(servidor) if servidor else None
    for raiz, dirs, fs in os.walk(telefono):
        if serv_abs and os.path.abspath(raiz).startswith(serv_abs): continue
        for f in sorted(fs):
            p = os.path.join(raiz, f); ruta = os.path.relpath(p, telefono).replace(os.sep, '/')
            if ruta.lower().endswith(('.txt', '.md')) and '/' not in ruta: continue      # LEEME sueltos
            archivos.append((ruta, p))
    if not archivos: raise SystemExit('no hay archivos para el telefono en ' + telefono)
    sv = {}
    m = dict(formato=1, version=int(version), nombre=nombre, mensaje=mensaje, obligatoria=bool(obligatoria), creado=int(time.time()),
             telefono=[dict(ruta=r, md5=md5(p), tamano=os.path.getsize(p)) for r, p in sorted(archivos)], servidor=sv)
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as z:
        for r, p in sorted(archivos): z.write(p, 'telefono/' + r)
        if servidor:
            cfg = [f for f in sorted(os.listdir(servidor)) if f.lower().endswith(('.json', '.csv', '.txt')) and f != 'marcos.json']
            for f in cfg: z.write(os.path.join(servidor, f), 'servidor/config/' + f)
            if cfg: sv['config'] = cfg
            if os.path.exists(os.path.join(servidor, 'marcos.json')):
                z.write(os.path.join(servidor, 'marcos.json'), 'servidor/marcos.json'); sv['marcos'] = True
        if marcos_nuevos:
            spec = json.load(open(marcos_nuevos, encoding='utf-8'))
            sv['marcos_extra'] = [dict(id=x['id'], nombre=(x.get('titulo') or {}).get('es') or x['nombre']) for x in spec['marcos']]
        z.writestr('manifest.json', json.dumps(m, ensure_ascii=False, indent=1))
    total = sum(f['tamano'] for f in m['telefono'])
    print('%s: version %d, %d archivos para el telefono (%.1f MB), servidor: %s, %s'
          % (salida, m['version'], len(m['telefono']), total / 1e6, json.dumps(sv, ensure_ascii=False)[:200], 'OBLIGATORIA' if obligatoria else 'opcional'))
    for f in m['telefono']: print('   ', f['ruta'], f['tamano'], f['md5'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('salida'); ap.add_argument('--version', type=int, required=True)
    ap.add_argument('--nombre', required=True); ap.add_argument('--mensaje', default='')
    ap.add_argument('--telefono', required=True); ap.add_argument('--servidor'); ap.add_argument('--marcos-nuevos')
    ap.add_argument('--opcional', action='store_true'); ap.add_argument('--mod-apk')
    a = ap.parse_args()
    crear(a.salida, a.version, a.nombre, a.mensaje, a.telefono, a.servidor, a.marcos_nuevos, not a.opcional, a.mod_apk)
