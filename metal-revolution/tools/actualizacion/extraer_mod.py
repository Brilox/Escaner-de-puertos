#!/usr/bin/env python3
"""Saca del APK del mod "Metal Offline V2" los archivos del juego que el mod modifica (tabla MRRES001 de libgame.so).

    python extraer_mod.py <apk> <carpeta_salida>

Deja en <carpeta_salida> los bundles con la misma ruta que en el telefono (AssetBundles/Android/...), listos para
entrar en una actualizacion (crear_actualizacion.py --mod-apk lo hace solo). Asi el actualizador de Tencent no
vuelve a poner los originales encima de los del mod. apollo_reslist.flist NO se saca: esa lista la escribe el
actualizador y no se reemplaza nunca.

Formato de la tabla (verificado con SHA-256): 'MRRES001', u32 cantidad, y por entrada: u16 largo de la ruta,
u32 tamano, SHA-256 del original (32), SHA-256 del archivo del mod (32), ruta, datos."""
import hashlib, os, struct, sys, zipfile

def entradas(lib):
    k = 0
    while True:
        p = lib.find(b'MRRES001', k)
        if p < 0: raise SystemExit('no encontre la tabla MRRES001 en libgame.so')
        q = p + 8; n = struct.unpack_from('<I', lib, q)[0]; q += 4; out = []
        try:
            for _ in range(n):
                pl, sz = struct.unpack_from('<HI', lib, q); q += 6
                so, sm = lib[q:q + 32], lib[q + 32:q + 64]; q += 64
                ruta = lib[q:q + pl].decode('utf-8'); q += pl; datos = lib[q:q + sz]; q += sz
                if hashlib.sha256(datos).digest() != sm: raise ValueError
                out.append((ruta, datos))
            return out
        except (ValueError, UnicodeDecodeError, struct.error):
            k = p + 1

def extraer(apk, salida):
    lib = zipfile.ZipFile(apk).read('lib/arm64-v8a/libgame.so')
    hechos = []
    for ruta, datos in entradas(lib):
        if not ruta.startswith('AssetBundles/'): continue
        p = os.path.join(salida, *ruta.split('/')); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(datos); hechos.append(ruta)
    return hechos

if __name__ == '__main__':
    if len(sys.argv) != 3: print(__doc__); sys.exit(2)
    for r in extraer(*sys.argv[1:]): print(r)
