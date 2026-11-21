#!/usr/bin/env python3
"""Resuelve direcciones de metodos C# y offsets de campos en libil2cpp.so (arm64, IL2CPP 24.1) sin Il2CppDumper.

Uso: python3 -I resolver_direcciones_il2cpp.py <libil2cpp.so> <global-metadata.dat> <salida.json>
Requiere: pip install pyelftools numpy
Hace: aplica relocaciones R_AARCH64_RELATIVE, localiza Il2CppMetadataRegistration (fieldOffsetsCount == typeDefinitionsCount
repetido) y Il2CppCodeRegistration (methodPointersCount == max methodIndex + 1), y escribe {direccion: [nombres]}.
Hallazgo de este juego: la tabla de offsets de campos esta ofuscada con XOR 0xB6B6B6B6.
Con capstone (pip install capstone) se puede desensamblar un metodo: ver ANALISIS.md.
"""
import struct, json, sys
from elftools.elf.elffile import ELFFile

def main(lib, meta, out):
    data = bytearray(open(lib, 'rb').read()); elf = ELFFile(open(lib, 'rb'))
    segs = [(s['p_vaddr'], s['p_offset'], s['p_filesz']) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    def va2off(va):
        for v, o, fs in segs:
            if v <= va < v + fs: return o + (va - v)
    for sec in elf.iter_sections():
        if sec['sh_type'] == 'SHT_RELA':
            for r in sec.iter_relocations():
                if r['r_info_type'] == 1027:
                    off = va2off(r['r_offset'])
                    if off is not None: struct.pack_into('<Q', data, off, r['r_addend'])
    md = open(meta, 'rb').read(); H = struct.unpack_from('<50I', md, 0)
    strOff, tdOff, tdCnt, mOff, mCnt = H[6], H[40], H[41] // 100, H[12], H[13] // 52
    cstr = lambda i: md[strOff + i:md.index(b'\0', strOff + i)].decode('utf-8', 'replace')
    midx = [struct.unpack_from('<I', md, mOff + i * 52 + 20)[0] for i in range(mCnt)]
    maxidx = max(x for x in midx if x != 0xFFFFFFFF)
    datasecs = [s for s in elf.iter_sections() if s.name in ('.data.rel.ro', '.data', '.data.rel.ro.local')]
    metareg = codereg = None
    for s in datasecs:
        base, off, size = s['sh_addr'], s['sh_offset'], s['sh_size']
        for i in range(0, size - 64, 8):
            v = struct.unpack_from('<Q', data, off + i)[0]
            if v == tdCnt and struct.unpack_from('<Q', data, off + i + 16)[0] == tdCnt and not metareg: metareg = base + i - 80
            if v == maxidx + 1 and not codereg:
                p = struct.unpack_from('<Q', data, off + i + 8)[0]
                if p and va2off(p): codereg = (base + i, p)
    print('MetadataRegistration', hex(metareg), 'CodeRegistration', [hex(x) for x in codereg])
    mp = struct.unpack_from(f'<{maxidx + 1}Q', data, va2off(codereg[1]))
    tnames = []
    for t in range(tdCnt):
        f = struct.unpack_from('<2I', md, tdOff + t * 100); ns = cstr(f[1]); tnames.append((ns + '.' if ns else '') + cstr(f[0]))
    table = {}
    for i in range(mCnt):
        f = struct.unpack_from('<11I', md, mOff + i * 52)
        if f[5] == 0xFFFFFFFF: continue
        a = mp[f[5]]
        if a: table.setdefault(hex(a), []).append(f'{tnames[f[1]]}::{cstr(f[0])}')
    json.dump(table, open(out, 'w')); print(len(table), 'direcciones ->', out)

if __name__ == '__main__':
    main(*sys.argv[1:4])
