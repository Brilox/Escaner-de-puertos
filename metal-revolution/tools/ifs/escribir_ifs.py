#!/usr/bin/env python3
"""Crea archivos IFS ("nifs") de Tencent GCloud, el mismo formato que first_source.png dentro del OBB.

    python escribir_ifs.py <salida.ifs> <carpeta>          empaqueta todos los archivos de <carpeta>
                                                            (las rutas dentro del IFS son relativas a <carpeta>)

Formato (verificado byte a byte contra el OBB 1.0.23, ver ANALISIS.md):
  cabecera (0xAC bytes)  'nifs', 0xAC, version 0, sector_shift 5 (sectores de 16 KB), tamano del archivo sin las tablas
                         finales, posiciones y tamanos de BET, HET, tabla MD5 y bitmap, tamano de trozo MD5 (16 KB) x2,
                         32 bytes en cero, MD5(BET), MD5(HET), MD5(cabecera[0:0x9C]).
  datos                  por archivo: tabla de sectores (u32, n+1 entradas) + sectores (1 byte de tipo 2 + zlib, o el
                         sector tal cual si comprimir no ahorra) + MD5 de cada trozo de 16 KB de lo guardado.
                         El (listfile) va cifrado (MPQ) con la clave de '(listfile)'.
  HET y BET              tablas MPQ v4 cifradas, cada una seguida de los MD5 de sus trozos de 16 KB.
  relleno                hasta un multiplo de 16 KB (= archive_size).
  tabla MD5              MD5 de cada trozo de 16 KB de [0, archive_size) + MD5 de esa misma tabla.
  bitmap                 un byte 1 por trozo.
Entradas BET (304 bits): posicion 30, tamano 25, comprimido 25, flags 32 (0x80000200 archivo, 0x88000000 carpeta,
0x80010200 listfile), MD5 de los datos sin comprimir 128, hash de 64 bits de la carpeta padre 64. Las carpetas
(incluida la raiz, nombre vacio) tienen entrada propia."""
import hashlib, os, struct, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ifs import hashlittle2
from mpq import hash_str, CT

SECTOR = 0x4000
TROZO = 0x4000
F_ARCHIVO, F_CARPETA, F_LISTFILE = 0x80000200, 0x88000000, 0x80010200


def encrypt(data, key):
    n = len(data) // 4; w = struct.unpack('<%dI' % n, data[:n * 4]); s2 = 0xEEEEEEEE; out = []
    for y in w:
        s2 = (s2 + CT[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        out.append((y ^ ((key + s2) & 0xFFFFFFFF)) & 0xFFFFFFFF)
        key = ((((~key) << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF; s2 = (y + s2 + (s2 << 5) + 3) & 0xFFFFFFFF
    return struct.pack('<%dI' % n, *out) + data[n * 4:]


def hash64(nombre):
    """Hash Jenkins de 64 bits de un nombre (minusculas, con '\\'), como lo guarda el IFS."""
    c, b = hashlittle2(nombre.replace('/', '\\').lower().encode('utf-8'), 2, 1)
    return (b << 32) | c


def md5_trozos(datos):
    return b''.join(hashlib.md5(datos[k:k + TROZO]).digest() for k in range(0, len(datos), TROZO)) if datos else b''


def guardar_datos(datos, clave=None):
    """Tabla de sectores + sectores (zlib si ahorra). Con clave: cifrado MPQ (tabla con clave-1, sector k con clave+k)."""
    ns = (len(datos) + SECTOR - 1) // SECTOR
    sectores = []
    for k in range(ns):
        s = datos[k * SECTOR:(k + 1) * SECTOR]; z = zlib.compress(s, 9)
        sectores.append(b'\x02' + z if len(z) + 1 < len(s) else s)
    offs = [4 * (ns + 1)]
    for s in sectores: offs.append(offs[-1] + len(s))
    tabla = struct.pack('<%dI' % (ns + 1), *offs)
    if clave is not None:
        tabla = encrypt(tabla, (clave - 1) & 0xFFFFFFFF)
        sectores = [encrypt(s, (clave + k) & 0xFFFFFFFF) for k, s in enumerate(sectores)]
    return tabla + b''.join(sectores)


class Bits:
    def __init__(self, nbits): self.v = 0; self.n = nbits
    def poner(self, pos, nbits, valor): self.v |= (valor & ((1 << nbits) - 1)) << pos
    def bytes(self): return self.v.to_bytes((self.n + 7) // 8, 'little')


def tabla_het(hashes, entradas=None):
    """hashes[i] = hash64 del nombre de la entrada BET i. Devuelve los datos de la HET sin cifrar."""
    entradas = entradas or len(hashes); total = entradas * 4 // 3
    bits_idx = max(1, (len(hashes)).bit_length()) if len(hashes) > 1 else 1
    bits_idx = max(bits_idx, (entradas).bit_length())
    hb = bytearray(total); idx = [(1 << bits_idx) - 1] * total
    for i, h in enumerate(hashes):
        h |= 1 << 63; s = h % total
        while hb[s]: s = (s + 1) % total
        hb[s] = h >> 56; idx[s] = i
    t = Bits(total * bits_idx)
    for s, v in enumerate(idx): t.poner(s * bits_idx, bits_idx, v)
    tb = bytearray(t.bytes()); sobra = len(tb) * 8 - total * bits_idx
    if sobra: tb[-1] |= (0xFF << (8 - sobra)) & 0xFF        # bits sobrantes en 1 (la tabla se inicia con 0xFF)
    tb = bytes(tb)
    cuerpo = struct.pack('<8I', 0, entradas, total, 64, bits_idx, 0, bits_idx, len(tb)) + bytes(hb) + tb
    return struct.pack('<I', len(cuerpo)) + cuerpo[4:]


def tabla_bet(entradas):
    """entradas: dicts con pos, size, csize, flags, md5 (16 bytes o None), dirhash, hash (64 bits del nombre)."""
    n = len(entradas); eb = 304
    e = Bits(eb * n)
    for i, x in enumerate(entradas):
        o = i * eb
        e.poner(o + 0, 30, x['pos']); e.poner(o + 30, 25, x['size']); e.poner(o + 55, 25, x['csize'])
        e.poner(o + 80, 32, x['flags']); e.poner(o + 112, 128, int.from_bytes(x['md5'] or b'\0' * 16, 'little'))
        e.poner(o + 240, 64, x['dirhash'])
    h = Bits(56 * n)
    for i, x in enumerate(entradas): h.poner(i * 56, 56, x['hash'] | (1 << 63))
    eb_bytes, h_bytes = e.bytes(), h.bytes()
    cab = struct.pack('<21I', 0, n, eb, 0, 30, 55, 80, 112, 112, 30, 25, 25, 32, 128, 0, 56, 0, 56, len(h_bytes), 240, 64)
    cuerpo = cab + eb_bytes + h_bytes
    return struct.pack('<I', len(cuerpo)) + cuerpo[4:]


def crear(archivos, salida=None):
    """archivos: lista de (ruta dentro del IFS con '\\' o '/', bytes). Devuelve los bytes del IFS (y lo guarda)."""
    archivos = [(r.replace('/', '\\').strip('\\'), d) for r, d in archivos]
    carpetas = []
    for r, _ in archivos:
        p = r.split('\\')
        for k in range(1, len(p)):
            c = '\\'.join(p[:k])
            if c not in carpetas: carpetas.append(c)
    padre = lambda r: r.rsplit('\\', 1)[0] if '\\' in r else ''
    entradas = [dict(nombre='', flags=F_CARPETA, datos=None, dirhash=0)]
    entradas += [dict(nombre=c, flags=F_CARPETA, datos=None, dirhash=hash64(padre(c))) for c in carpetas]
    entradas += [dict(nombre=r, flags=F_ARCHIVO, datos=d, dirhash=hash64(padre(r))) for r, d in archivos]
    lista = ''.join(x + '\r\n' for x in [''] + carpetas + [r for r, _ in archivos]).encode('utf-8')   # como el original
    entradas.append(dict(nombre='(listfile)', flags=F_LISTFILE, datos=lista, dirhash=hash64('')))
    out = bytearray(0xAC)
    for x in entradas:
        x['hash'] = hash64(x['nombre'])
        if x['datos'] is None:
            x.update(pos=0, size=0, csize=0, md5=None); continue
        g = guardar_datos(x['datos'], hash_str('(listfile)', 3) if x['flags'] == F_LISTFILE else None)
        x.update(pos=len(out), size=len(x['datos']), csize=len(g), md5=hashlib.md5(x['datos']).digest())
        out += g + md5_trozos(g)
    het = tabla_het([x['hash'] for x in entradas]); bet = tabla_bet(entradas)
    het_c = b'HET\x1a' + struct.pack('<II', 1, len(het)) + encrypt(het, hash_str('(hash table)', 3))
    bet_c = b'BET\x1a' + struct.pack('<II', 1, len(bet)) + encrypt(bet, hash_str('(block table)', 3))
    het_pos = len(out); out += het_c + md5_trozos(het_c)
    bet_pos = len(out); out += bet_c + md5_trozos(bet_c)
    out += b'\0' * (-len(out) % TROZO)
    tam = len(out); npz = tam // TROZO
    md5_pos = tam; md5_size = 16 * (npz + 1); bm_pos = md5_pos + md5_size
    cab = struct.pack('<4sIHHQQQQQQQQQII', b'nifs', 0xAC, 0, 5, tam, bet_pos, het_pos, md5_pos, bm_pos,
                      len(het_c), len(bet_c), md5_size, npz, TROZO, TROZO) + b'\0' * 32
    cab += hashlib.md5(bet_c).digest() + hashlib.md5(het_c).digest()
    cab += hashlib.md5(cab).digest()
    assert len(cab) == 0xAC
    out[0:0xAC] = cab
    tabla = b''.join(hashlib.md5(out[k:k + TROZO]).digest() for k in range(0, tam, TROZO))
    out += tabla + hashlib.md5(tabla).digest() + b'\x01' * npz
    if salida: open(salida, 'wb').write(out)
    return bytes(out)


def main():
    if len(sys.argv) != 3: print(__doc__); return 2
    salida, carpeta = sys.argv[1:]
    archivos = []
    for raiz, _, fs in os.walk(carpeta):
        for f in sorted(fs):
            p = os.path.join(raiz, f); archivos.append((os.path.relpath(p, carpeta), open(p, 'rb').read()))
    d = crear(archivos, salida)
    print('%s: %d archivos, %d bytes' % (salida, len(archivos), len(d)))


if __name__ == '__main__':
    sys.exit(main())
