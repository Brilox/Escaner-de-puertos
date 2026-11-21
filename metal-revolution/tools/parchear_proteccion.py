#!/usr/bin/env python3
"""Corrige la proteccion de recursos del mod "Metal Offline V2" para que el juego acepte las actualizaciones automaticas.

    python parchear_proteccion.py <apk_entrada> <apk_salida> [--keystore tools/mr.keystore] [--pass clave]

Que hace el mod (lib/arm64-v8a/libgame.so, ver ANALISIS.md): engancha init_assets del juego y, antes de cargar los
recursos, revisa 4 archivos de la carpeta del juego (global_info.bundle, bjx.bundle, jdj.bundle y apollo_reslist.flist,
la lista de archivos del actualizador de Tencent). Si alguno no es ni el original ni la version del mod, cierra el
juego con _exit(74). Toda actualizacion de Tencent reescribe apollo_reslist.flist, asi que con el mod tal cual
cualquier actualizacion deja el juego sin poder abrir.

El parche cambia UNA instruccion en observed_init_assets: el salto "si la revision fallo -> _exit(74)" pasa a ser un
NOP. La revision se sigue haciendo (y sigue instalando los archivos del mod cuando puede), pero ya no cierra el juego.
Las actualizaciones del servidor incluyen las versiones del mod de esos 3 bundles, asi que quedan iguales que antes.

El APK se vuelve a firmar con la MISMA clave que el APK instalado (tools/mr.keystore): se instala encima sin perder
la cuenta ni los datos."""
import argparse, os, shutil, subprocess, sys, tempfile, zipfile

LIB = 'lib/arm64-v8a/libgame.so'
PARCHES = [
    # (desplazamiento en el archivo, bytes originales, bytes nuevos, descripcion)
    # 0x4a1544 (memoria) = 0x4a0544 (archivo): tbnz w23, #0, 0x4a1588  ->  nop
    (0x4a0544, None, bytes.fromhex('1f2003d5'), 'observed_init_assets: no cerrar el juego si la revision de recursos falla'),
]
CONTEXTO = (0x4a053c, bytes.fromhex('f703362a'))     # mvn w23, w22 (dos instrucciones antes): confirma que es la version esperada


def tbnz_original():
    """Codifica 'tbnz w23, #0, +0x44' (de 0x4a1544 a 0x4a1588), la instruccion que se reemplaza."""
    imm14 = (0x4a1588 - 0x4a1544) // 4
    return (0x37000000 | (imm14 << 5) | 23).to_bytes(4, 'little')


def parchear_lib(datos):
    d = bytearray(datos)
    off, ctx = CONTEXTO
    if d[off:off + 4] != ctx:
        raise SystemExit('libgame.so no es la version esperada del mod (no encuentro la instruccion a cambiar)')
    for off, orig, nuevo, desc in PARCHES:
        orig = orig or tbnz_original()
        if d[off:off + 4] == nuevo:
            print('  ya estaba parcheado:', desc); continue
        if d[off:off + 4] != orig:
            raise SystemExit('bytes inesperados en 0x%x: %s' % (off, d[off:off + 4].hex()))
        d[off:off + 4] = nuevo; print('  parcheado:', desc)
    return bytes(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('apk'); ap.add_argument('salida')
    ap.add_argument('--keystore', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mr.keystore'))
    ap.add_argument('--pass', dest='pw', default='metalrevolution')
    a = ap.parse_args()
    if not os.path.exists(a.keystore): sys.exit('no encuentro la clave de firma %s (sin ella el APK no se instala encima)' % a.keystore)
    tmp = tempfile.mkdtemp(); unsigned = os.path.join(tmp, 'unsigned.apk'); aligned = os.path.join(tmp, 'aligned.apk')
    with zipfile.ZipFile(a.apk) as zin, zipfile.ZipFile(unsigned, 'w') as zout:
        for info in zin.infolist():
            n = info.filename
            if n.startswith('META-INF/') and n.upper().endswith(('.MF', '.SF', '.RSA', '.DSA', '.EC')): continue
            payload = zin.read(n)
            if n == LIB:
                print('parcheando', n); payload = parchear_lib(payload)
            zi = zipfile.ZipInfo(n, date_time=info.date_time); zi.compress_type = info.compress_type; zi.external_attr = info.external_attr
            zout.writestr(zi, payload)
    subprocess.check_call(['zipalign', '-p', '-f', '4', unsigned, aligned])
    subprocess.check_call(['apksigner', 'sign', '--ks', a.keystore, '--ks-pass', 'pass:' + a.pw, '--ks-key-alias', 'mr', '--out', a.salida, aligned])
    subprocess.check_call(['apksigner', 'verify', a.salida])
    shutil.rmtree(tmp); print('listo:', a.salida)


if __name__ == '__main__':
    main()
