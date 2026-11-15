#!/usr/bin/env python3
"""Apunta el APK "Metal Offline V2" a nuestro servidor y lo firma.

Cambia, dentro de assets/bin/Data/sharedassets0.assets (objeto GCloudConfig, entrada del mercado 643839105),
las tres cadenas "127.0.0.1" (updateUrlRelease, tDirUrlPreview, tDirUrlRelease) por el host indicado.
Luego reconstruye el APK sin las firmas antiguas, lo alinea y lo firma con un keystore propio.

Uso: python3 parchear_cliente.py <apk_del_mod> <host> <apk_salida> [--keystore mr.keystore] [--pass clave]
Requiere: pip install UnityPy ; apt install zipalign apksigner (o Android build-tools).
"""
import argparse, os, shutil, struct, subprocess, sys, tempfile, zipfile
import UnityPy

ASSET = 'assets/bin/Data/sharedassets0.assets'

def ustr(s):
    b = s.encode('utf-8'); return struct.pack('<I', len(b)) + b + b'\0' * (-len(b) % 4)

def patch_asset(data, host):
    env = UnityPy.load(data)
    sf = next(iter(env.files.values()))
    for obj in sf.objects.values():
        if obj.type.name != 'MonoBehaviour': continue
        raw = obj.get_raw_data()
        if b'GCloudConfig' not in raw[:64] and b'127.0.0.1' not in raw: continue
        old = ustr('127.0.0.1'); n = raw.count(old)
        if n == 0: continue
        new = raw.replace(old, ustr(host))
        obj.set_raw_data(new)
        print(f'  objeto path_id={obj.path_id}: {n} cadenas 127.0.0.1 -> {host}')
        return sf.save()
    sys.exit('no se encontro el objeto GCloudConfig con 127.0.0.1 (¿es el APK del mod?)')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('apk'); ap.add_argument('host'); ap.add_argument('salida')
    ap.add_argument('--keystore', default='mr.keystore'); ap.add_argument('--pass', dest='pw', default='metalrevolution')
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(); unsigned = os.path.join(tmp, 'unsigned.apk'); aligned = os.path.join(tmp, 'aligned.apk')
    with zipfile.ZipFile(a.apk) as zin, zipfile.ZipFile(unsigned, 'w') as zout:
        for info in zin.infolist():
            n = info.filename
            if n.startswith('META-INF/') and n.upper().endswith(('.MF', '.SF', '.RSA', '.DSA', '.EC')): continue
            payload = zin.read(n)
            if n == ASSET:
                print('parcheando', n); payload = patch_asset(payload, a.host)
            zi = zipfile.ZipInfo(n, date_time=info.date_time); zi.compress_type = info.compress_type; zi.external_attr = info.external_attr
            zout.writestr(zi, payload)
    subprocess.check_call(['zipalign', '-p', '-f', '4', unsigned, aligned])
    if not os.path.exists(a.keystore):
        print('creando keystore', a.keystore)
        subprocess.check_call(['keytool', '-genkeypair', '-keystore', a.keystore, '-storepass', a.pw, '-keypass', a.pw, '-alias', 'mr',
                               '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-dname', 'CN=Metal Revolution Privado'])
    subprocess.check_call(['apksigner', 'sign', '--ks', a.keystore, '--ks-pass', 'pass:' + a.pw, '--ks-key-alias', 'mr', '--out', a.salida, aligned])
    subprocess.check_call(['apksigner', 'verify', a.salida])
    shutil.rmtree(tmp); print('listo:', a.salida)

if __name__ == '__main__':
    main()
