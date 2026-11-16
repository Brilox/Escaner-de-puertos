#!/usr/bin/env python3
"""Cliente de prueba que habla el protocolo del juego. Sirve para probar el servidor sin telefonos.
Uso como libreria:  c = Cliente('A', host, puerto); c.pedir('LoginRequest', {'OpenId': 'x'})"""
import json, os, socket, struct, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
from fb_codec import Codec
C = Codec(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server', 'esquema_fb.json'))))
REQ = C.E['GameSvrReqUnion']['values']

def be32(b, o): return struct.unpack_from('>I', b, o)[0]

class Cliente:
    def __init__(self, nombre, host='127.0.0.1', puerto=8080):
        self.n = nombre; self.s = socket.create_connection((host, puerto), timeout=3); self.seq = 0; self.buf = b''; self.avisos = []
    def enviar(self, tipo, datos):
        self.seq += 1; p = C.encode('GameSvrRequest', dict(DataType=tipo, Data=datos))
        body = struct.pack('>HI', 2, self.seq) + struct.pack('>HI', 6, REQ[tipo]) + struct.pack('>HB', 5, 2) + struct.pack('>HI', 4, len(p)) + p
        self.s.sendall(struct.pack('>HI', 1, len(body)) + body)
    def recibir(self, espera=0.5):
        self.s.settimeout(espera); out = []
        while True:
            try: self.buf += self.s.recv(65536)
            except socket.timeout: break
            except OSError: break
        while len(self.buf) >= 6 and len(self.buf) >= be32(self.buf, 2) + 6:
            total = be32(self.buf, 2) + 6; f = self.buf[:total]; self.buf = self.buf[total:]; i = 6; payload = b''
            while i < total:
                tag = struct.unpack_from('>H', f, i)[0]; i += 2
                if tag == 5: i += 1
                elif tag == 4: ln = be32(f, i); payload = f[i + 4:i + 4 + ln]; i += 4 + ln
                else: i += 4
            d = C.decode('GameSvrRsp' if f[1] == 2 else 'GameSvrNotice', payload)
            out.append(('RSP' if f[1] == 2 else 'AVISO', d['DataType'], d['Data']))
        self.avisos += [o for o in out if o[0] == 'AVISO']
        return out
    def pedir(self, tipo, datos=None, ver=True):
        self.enviar(tipo, datos or {}); r = self.recibir()
        if ver:
            print(f'{self.n} -> {tipo} {json.dumps(datos or {}, ensure_ascii=False)[:90]}')
            for k, t, d in r: print(f'     {k:5} {t}: {json.dumps(d, ensure_ascii=False, default=str)[:170]}')
        return r
    def ver_avisos(self):
        r = self.recibir()
        for k, t, d in r: print(f'  [{self.n}] {k:5} {t}: {json.dumps(d, ensure_ascii=False, default=str)[:170]}')
        return r
