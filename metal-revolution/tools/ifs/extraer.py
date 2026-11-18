#!/usr/bin/env python3
"""Extrae el contenido de first_source.png (archivo IFS de Tencent) y descifra los scripts Lua del juego.

    python extraer.py <main.obb | first_source.png> <carpeta_salida> [--todo]

Sin --todo solo saca la lista de archivos, los scripts Lua (descifrados y separados uno por archivo) y la
configuracion. Con --todo saca los ~8.700 archivos (unos 840 MB).

Notas del formato (ver ANALISIS.md): MPQ v4 modificado ("nifs"); tablas HET/BET cifradas con las claves MPQ
estandar; nombres en el (listfile), que es el unico archivo cifrado; cada archivo = tabla de sectores + sectores
con 1 byte de tipo (2 = zlib). lua/lua.bytes va cifrado con AES-256-CBC (ver luacrypt.py)."""
import os, struct, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ifs import IFS
from luacrypt import descifrar

def abrir(ruta):
    """Devuelve (archivo, desplazamiento) del IFS, tanto si se pasa el .obb (zip) como el first_source.png suelto."""
    f = open(ruta, 'rb')
    if f.read(4) == b'nifs': return f, 0
    z = zipfile.ZipFile(ruta); i = z.getinfo('assets/first_source.png')
    if i.compress_type != 0: raise SystemExit('first_source.png esta comprimido dentro del obb; extraelo primero')
    f.seek(i.header_offset); h = f.read(30); n, e = struct.unpack_from('<HH', h, 26)
    return f, i.header_offset + 30 + n + e

def main():
    if len(sys.argv) < 3: print(__doc__); return 2
    f, base = abrir(sys.argv[1]); out = sys.argv[2]; todo = '--todo' in sys.argv
    a = IFS(f, base); nombres = [n for n in a.read_listfile() if n.strip()]
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'listfile.txt'), 'w', encoding='utf-8').write('\n'.join(nombres))
    n = 0
    for nombre in nombres:
        e = a.find(nombre)
        if not e or e['size'] == 0: continue
        bajo = nombre.lower()
        if not (todo or bajo.startswith(('lua\\', 'config\\')) or '\\config\\' in bajo or bajo == 'desc.txt'): continue
        dest = os.path.join(out, 'archivos', *nombre.split('\\')); os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, 'wb').write(a.read(e)); n += 1
    print(n, 'archivos extraidos de', len(nombres))
    lb = os.path.join(out, 'archivos', 'lua', 'lua.bytes')
    if os.path.exists(lb):
        texto = descifrar(open(lb, 'rb').read()).decode('utf-8')
        k = 0
        for parte in texto.split('\nlua/')[1:]:
            ruta, _, cuerpo = parte.partition('\n')
            dest = os.path.join(out, 'lua', *ruta.split('/')); os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, 'w', encoding='utf-8').write(cuerpo); k += 1
        print(k, 'scripts Lua descifrados en', os.path.join(out, 'lua'))

if __name__ == '__main__':
    sys.exit(main())
