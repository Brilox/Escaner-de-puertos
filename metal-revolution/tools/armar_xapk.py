#!/usr/bin/env python3
"""Arma UN solo archivo .xapk (APK + OBB) para repartir Metal Online a los jugadores.

    python armar_xapk.py <apk> <obb> [salida.xapk]

Ejemplo (en el PC del servidor, en la carpeta metal-revolution\\tools):
    python armar_xapk.py metal_online_v3.apk ..\\server\\main.1300.com.gtarcade.next.mrglo.obb MetalOnline.xapk

El .xapk es el formato de APKPure: un zip con el APK, el OBB en Android/obb/<paquete>/ y un manifest.json.
Se instala con una app instaladora de XAPK (APKPure, "XAPK Installer" o SAI), que copia el OBB a su carpeta;
en Android 11 o superior un explorador de archivos normal ya no puede hacerlo.
Solo usa la biblioteca estandar de Python (funciona en Windows sin instalar nada)."""
import json, os, sys, zipfile

PAQUETE = 'com.gtarcade.next.mrglo'
VERSION_CODE, VERSION_NAME = 1300, '1.0.23'
PERMISOS = ['android.permission.INTERNET', 'android.permission.ACCESS_NETWORK_STATE', 'android.permission.ACCESS_WIFI_STATE',
            'android.permission.CHANGE_WIFI_STATE', 'android.permission.READ_EXTERNAL_STORAGE', 'android.permission.WRITE_EXTERNAL_STORAGE',
            'android.permission.VIBRATE', 'android.permission.WAKE_LOCK', 'android.permission.FOREGROUND_SERVICE']


def icono(apk):
    """El PNG de icono mas grande del APK (opcional; solo para que el instalador lo muestre)."""
    try:
        z = zipfile.ZipFile(apk)
        c = [i for i in z.infolist() if i.filename.startswith('res/mipmap') and i.filename.endswith('.png') and 'icon' in i.filename.lower()]
        return z.read(max(c, key=lambda i: i.file_size).filename) if c else None
    except (OSError, zipfile.BadZipFile):
        return None


def armar(apk, obb, salida):
    for p in (apk, obb):
        if not os.path.isfile(p): sys.exit('no encuentro ' + p)
    if not zipfile.is_zipfile(apk): sys.exit('%s no parece un APK' % apk)
    nombre_obb = 'main.%d.%s.obb' % (VERSION_CODE, PAQUETE)
    ruta_obb = 'Android/obb/%s/%s' % (PAQUETE, nombre_obb)
    total = os.path.getsize(apk) + os.path.getsize(obb)
    manifest = dict(xapk_version=2, package_name=PAQUETE, name='Metal Online', version_code=str(VERSION_CODE),
                    version_name=VERSION_NAME, min_sdk_version='21', target_sdk_version='30', permissions=PERMISOS,
                    split_configs=[], total_size=total, icon='icon.png',
                    split_apks=[dict(file=PAQUETE + '.apk', id='base')],
                    expansions=[dict(file=ruta_obb, install_location='EXTERNAL_STORAGE', install_path=ruta_obb)])
    ico = icono(apk)
    if not ico: manifest.pop('icon')
    print('armando %s (%.0f MB)...' % (salida, total / 1e6))
    with zipfile.ZipFile(salida + '.tmp', 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        if ico: z.writestr('icon.png', ico)
        z.write(apk, PAQUETE + '.apk')          # sin comprimir: el APK y el OBB ya vienen comprimidos por dentro
        z.write(obb, ruta_obb)
    os.replace(salida + '.tmp', salida)
    with zipfile.ZipFile(salida) as z:
        malo = z.testzip()
        if malo: sys.exit('el archivo quedo danado: ' + malo)
    print('listo: %s (%.0f MB)' % (salida, os.path.getsize(salida) / 1e6))


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4): print(__doc__); sys.exit(2)
    armar(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else 'MetalOnline.xapk')
