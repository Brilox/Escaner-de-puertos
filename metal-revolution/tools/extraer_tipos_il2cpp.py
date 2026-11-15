#!/usr/bin/env python3
"""Lista clases, campos y metodos de Assembly-CSharp a partir de global-metadata.dat (IL2CPP, layout 24.1 / Unity 2018.4).

Uso: python3 -I extraer_tipos_il2cpp.py <ruta/global-metadata.dat> <salida.json>
No requiere Il2CppDumper ni .NET. Solo nombres (no codigo): sirve para mapear el protocolo.
"""
import struct, json, sys

def main(path, out):
    d = open(path, 'rb').read()
    H = struct.unpack_from('<50I', d, 0)
    assert H[0] == 0xFAB11BAF, 'no es un global-metadata.dat'
    str_off = H[6]; m_off = H[12]; f_off = H[24]
    td_off, td_cnt = H[40], H[41]; img_off, img_cnt = H[44], H[45]
    TD, MD, FD, IM = 100, 52, 12, 40   # tamanos de struct en la variante 24.1
    assert td_cnt % TD == 0 and img_cnt % IM == 0, 'layout distinto: ajustar tamanos'

    def cstr(idx):
        o = str_off + idx; return d[o:d.index(b'\0', o)].decode('utf-8', 'replace')
    def typedef(i):
        f = struct.unpack_from('<19I8H2I', d, td_off + i * TD)
        return dict(name=cstr(f[0]), ns=cstr(f[1]), fieldStart=f[11], methodStart=f[12],
                    method_count=f[19], field_count=f[21])
    def method(i): return cstr(struct.unpack_from('<I', d, m_off + i * MD)[0])
    def field(i):  return cstr(struct.unpack_from('<I', d, f_off + i * FD)[0])

    result = {}
    for i in range(img_cnt // IM):
        f = struct.unpack_from('<10I', d, img_off + i * IM)
        name, start, count = cstr(f[0]), f[2], f[3]
        rows = []
        for t in range(start, start + count):
            td = typedef(t)
            td['methods'] = [method(td['methodStart'] + k) for k in range(td['method_count'])] if td['methodStart'] < 0xFFFFFFF0 else []
            td['fields']  = [field(td['fieldStart'] + k) for k in range(td['field_count'])] if td['fieldStart'] < 0xFFFFFFF0 else []
            rows.append(td)
        result[name] = rows
    json.dump(result, open(out, 'w'))
    print(f"{sum(len(v) for v in result.values())} tipos en {len(result)} ensamblados -> {out}")

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
