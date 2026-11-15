#!/usr/bin/env python3
"""Extrae los mensajes grabados (request/response) incrustados en libgame.so del mod 'Metal Offline V2'.

Uso: python3 -I extraer_blobs_mod.py <lib/arm64-v8a/libgame.so> <directorio_salida>
Requiere binutils (nm, readelf). La libreria del mod no esta 'stripped': cada blob tiene simbolo y tamano.

Formato del canal de juego (TCP, puerto 8080 en el mod), big-endian:
  u16 tipo (1=request, 2=response) | u32 largo_restante | TLV: u16 tag + valor
  tag 2 = seq (u32) | tag 6 = cmd (u32) | tag 5 = flag (u8) | tag 4 = largo payload (u32) + payload FlatBuffers
"""
import subprocess, re, struct, os, sys

def main(lib, out):
    os.makedirs(out, exist_ok=True)
    syms = subprocess.run(['nm', '-S', '--defined-only', '-C', lib], capture_output=True, text=True).stdout
    secs = []
    for m in re.finditer(r'\]\s+(\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)',
                         subprocess.run(['readelf', '-S', '-W', lib], capture_output=True, text=True).stdout):
        secs.append((int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16)))
    def va2off(va):
        for a, o, s in secs:
            if a <= va < a + s: return o + (va - a)
    d = open(lib, 'rb').read()
    n = 0
    for line in syms.splitlines():
        m = re.match(r'([0-9a-f]+)\s+([0-9a-f]+)\s+(\w)\s+(.*)', line)
        if not m or m.group(3) not in 'VvRrDd': continue
        name = m.group(4)
        if not re.match(r'mr\w*::(k|request|response)', name): continue
        va, size = int(m.group(1), 16), int(m.group(2), 16)
        b = d[va2off(va):va2off(va) + size]
        open(os.path.join(out, re.sub(r'\W+', '_', name) + '.bin'), 'wb').write(b)
        n += 1
    print(f'{n} blobs -> {out}')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
