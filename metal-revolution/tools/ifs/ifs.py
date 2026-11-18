"""Lector de archivos IFS ("nifs") de Tencent GCloud: un MPQ v4 modificado (HET/BET + tabla MD5 + bitmap)."""
import struct, zlib, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from mpq import hash_str, decrypt

def rot(x, k): return ((x << k) | (x >> (32 - k))) & 0xFFFFFFFF
def hashlittle2(data, pc=0, pb=0):
    """Bob Jenkins lookup3 hashlittle2 (como StormLib)."""
    length = len(data); a = b = c = (0xdeadbeef + length + pc) & 0xFFFFFFFF; c = (c + pb) & 0xFFFFFFFF
    k = data; i = 0
    while length > 12:
        a = (a + struct.unpack_from('<I', k, i)[0]) & 0xFFFFFFFF; b = (b + struct.unpack_from('<I', k, i + 4)[0]) & 0xFFFFFFFF
        c = (c + struct.unpack_from('<I', k, i + 8)[0]) & 0xFFFFFFFF
        a = (a - c) & 0xFFFFFFFF; a ^= rot(c, 4); c = (c + b) & 0xFFFFFFFF
        b = (b - a) & 0xFFFFFFFF; b ^= rot(a, 6); a = (a + c) & 0xFFFFFFFF
        c = (c - b) & 0xFFFFFFFF; c ^= rot(b, 8); b = (b + a) & 0xFFFFFFFF
        a = (a - c) & 0xFFFFFFFF; a ^= rot(c, 16); c = (c + b) & 0xFFFFFFFF
        b = (b - a) & 0xFFFFFFFF; b ^= rot(a, 19); a = (a + c) & 0xFFFFFFFF
        c = (c - b) & 0xFFFFFFFF; c ^= rot(b, 4); b = (b + a) & 0xFFFFFFFF
        length -= 12; i += 12
    if length == 0: return c, b
    tail = k[i:i + length] + b'\0' * (12 - length)
    a = (a + struct.unpack_from('<I', tail, 0)[0]) & 0xFFFFFFFF; b = (b + struct.unpack_from('<I', tail, 4)[0]) & 0xFFFFFFFF
    c = (c + struct.unpack_from('<I', tail, 8)[0]) & 0xFFFFFFFF
    c ^= b; c = (c - rot(b, 14)) & 0xFFFFFFFF; a ^= c; a = (a - rot(c, 11)) & 0xFFFFFFFF
    b ^= a; b = (b - rot(a, 25)) & 0xFFFFFFFF; c ^= b; c = (c - rot(b, 16)) & 0xFFFFFFFF
    a ^= c; a = (a - rot(c, 4)) & 0xFFFFFFFF; b ^= a; b = (b - rot(a, 14)) & 0xFFFFFFFF
    c ^= b; c = (c - rot(b, 24)) & 0xFFFFFFFF
    return c, b

def jenkins64(name):
    n = name.replace('/', '\\').lower().encode('utf-8', 'replace')
    s, p = hashlittle2(n, 1, 2)      # (secondary, primary) como StormLib: hashlittle2(name, &secondary=1, &primary=2)
    return (p << 32) | s

def bits(buf, idx, n):
    v = int.from_bytes(buf[idx // 8: (idx + n + 7) // 8 + 1], 'little') >> (idx % 8)
    return v & ((1 << n) - 1)

class IFS:
    def __init__(self, f, base=0):
        self.f = f; self.base = base
        h = self.rd(0, 0x5C)
        (self.magic, self.hsize, self.version, self.sector_shift, self.archive_size, self.bet_pos, self.het_pos, self.md5_pos,
         self.bitmap_pos, self.het_size, self.bet_size, self.md5_size, self.bitmap_size, self.md5_piece, self.raw_chunk) = struct.unpack('<4sIHHQQQQQQQQQII', h)
        assert self.magic == b'nifs', self.magic
        self._het(); self._bet()

    def rd(self, pos, n): self.f.seek(self.base + pos); return self.f.read(n)

    def _het(self):
        sig, ver, ds = struct.unpack('<4sII', self.rd(self.het_pos, 12)); d = decrypt(self.rd(self.het_pos + 12, ds), hash_str('(hash table)', 3))
        (self.het_tsize, self.het_entries, self.het_total, self.het_hashbits, self.het_idxtotal, self.het_idxextra, self.het_idx, self.het_idxtable) = struct.unpack_from('<8I', d, 0)
        p = 32; self.het_hashes = d[p:p + self.het_total]; p += self.het_total
        self.het_indexes = d[p:p + self.het_idxtable]

    def _bet(self):
        sig, ver, ds = struct.unpack('<4sII', self.rd(self.bet_pos, 12)); d = decrypt(self.rd(self.bet_pos + 12, ds), hash_str('(block table)', 3))
        v = struct.unpack_from('<21I', d, 0)
        (self.bet_tsize, self.count, self.entry_bits, self.bi_pos, self.bi_size, self.bi_cmp, self.bi_flag, self.bi_md5, _rep,
         self.bc_pos, self.bc_size, self.bc_cmp, self.bc_flag, self.bc_md5, _z, self.hash_total, self.hash_extra, self.hash_bits, _p1, _p2, self.extra_bits) = v
        p = 84; nbytes = (self.entry_bits * self.count + 7) // 8
        ent = d[p:p + nbytes]; p += nbytes; hashes = d[p:]     # hash del nombre, 56 bits por archivo
        self.files = []
        for i in range(self.count):
            o = i * self.entry_bits
            self.files.append(dict(i=i, pos=bits(ent, o + self.bi_pos, self.bc_pos), size=bits(ent, o + self.bi_size, self.bc_size),
                                   csize=bits(ent, o + self.bi_cmp, self.bc_cmp), flags=bits(ent, o + self.bi_flag, self.bc_flag),
                                   hash2=bits(hashes, i * self.hash_total, self.hash_total),
                                   dirhash=bits(ent, o + self.bi_md5 + self.bc_md5, 64)))
        self.by_hash2 = {}
        for e in self.files: self.by_hash2.setdefault(e['hash2'], []).append(e)

    @staticmethod
    def name_hash(name):
        """Hash del nombre en IFS: Jenkins lookup3 hashlittle2 del nombre en minusculas con '\\', semillas (2, 1),
        (b << 32) | c, recortado a 56 bits. (Las carpetas guardan el hash completo de 64 bits en otro campo.)"""
        c, b = hashlittle2(name.replace('/', '\\').lower().encode('utf-8'), 2, 1)
        return ((b << 32) | c) & ((1 << 56) - 1)

    def find(self, name):
        c = self.by_hash2.get(self.name_hash(name))
        return c[0] if c else None

    def read_listfile(self):
        """El (listfile) es el unico archivo cifrado: cifrado MPQ estandar con la clave de '(listfile)'."""
        e = self.find('(listfile)') or next(x for x in self.files if x['flags'] & 0x10000)
        return self.read(e, key=hash_str('(listfile)', 3)).decode('utf-8', 'replace').splitlines()

    def read(self, e, key=None):
        """Datos del archivo: tabla de sectores (u32) y luego cada sector = 1 byte de tipo + datos (2 = zlib)."""
        if e['size'] == 0: return b''
        raw = self.rd(e['pos'], e['csize'])
        if key is not None:                       # archivo cifrado (MPQ): tabla con key-1, sector k con key+k
            nsec = (e['size'] + (512 << self.sector_shift) - 1) // (512 << self.sector_shift)
            tab = decrypt(raw[:(nsec + 1) * 4], (key - 1) & 0xFFFFFFFF); offs = struct.unpack('<%dI' % (nsec + 1), tab)
            out = bytearray()
            for k in range(nsec):
                sec = decrypt(raw[offs[k]:offs[k + 1]], (key + k) & 0xFFFFFFFF)
                out += zlib.decompress(sec[1:]) if sec[0] == 2 else sec[1:]
            return bytes(out)
        first = struct.unpack_from('<I', raw, 0)[0]
        if first % 4 or first > len(raw) or first < 8:
            return raw                            # sin tabla de sectores: guardado tal cual
        n = first // 4
        offs = struct.unpack_from('<%dI' % n, raw, 0)
        out = bytearray(); sector = 512 << self.sector_shift
        for k in range(n - 1):
            chunk = raw[offs[k]:offs[k + 1]]
            if not chunk: continue
            esperado = min(sector, e['size'] - k * sector)
            if len(chunk) == esperado:            # como en MPQ: si comprimir no ahorra nada, va tal cual y sin byte de tipo
                out += chunk; continue
            t = chunk[0]; body = chunk[1:]
            if t == 2:
                try: out += zlib.decompress(body)
                except zlib.error: out += chunk
            else:
                out += body if t in (0, 1) else chunk
        return bytes(out)
