#!/usr/bin/env python3
"""Servidor privado de Metal Revolution, fase 2.

Puerto TCP unico para dos clases de conexion (ver README):
  * TGCP (primer byte 0xAA o el prefijo "Cf"): handshake y directorio Pebble RPC, con respuestas grabadas.
  * Juego (primer byte 0x00): protocolo TLV del cliente. Cada peticion se decodifica con el esquema FlatBuffers,
    se despacha a juego.Juego (cuentas, hall, mesas, partidas) y se responde con FlatBuffers reales.
    Si no hay handler, se usa la respuesta grabada del mod para ese comando, y si tampoco hay, EmptyRsp.
Ademas un socket UDP (relay) que por ahora solo registra lo que llega, para la fase 3.

Uso: python3 mr_server.py --host <ip-publica> [--port 8080] [--debug] [--nombre-automatico]
"""
import argparse, asyncio, json, logging, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # usa la copia local de flatbuffers
from fb_codec import Codec
from juego import Juego

log = logging.getLogger('mr')
HERE = os.path.dirname(os.path.abspath(__file__))
REQUEST, RESPONSE, NOTICE = 1, 2, 3
DATATYPE_FLATBUFFERS = 2

# ---------------------------------------------------------------- framing
def be32(b, o): return struct.unpack_from('>I', b, o)[0]
def put_be32(b, o, v): struct.pack_into('>I', b, o, v)

def read_varint(b, i):
    v = sh = 0
    while True:
        c = b[i]; i += 1; v |= (c & 0x7f) << sh; sh += 7
        if not c & 0x80: return v, i

def encode_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7f; v >>= 7; out.append(b | (0x80 if v else 0))
        if not v: return bytes(out)

def tgcp_head(pkt):
    f = {}
    try:
        if pkt[5] != 0x15: return f
        hlen = be32(pkt, 6); i, end = 10, 10 + hlen
        while i < end:
            tag, i = read_varint(pkt, i); field, typ = tag >> 4, tag & 0xF
            if typ == 0: f[field], i = read_varint(pkt, i)
            elif typ == 1: f[field] = pkt[i]; i += 1
            elif typ == 5: ln = be32(pkt, i); i += 4 + ln
            else: break
    except (IndexError, struct.error): pass
    return f

def tgcp_set_extra_len(frame, new_len):
    frame = bytearray(frame); hlen = be32(frame, 6); i, end = 10, 10 + hlen
    while i < end:
        tag, j = read_varint(frame, i); field, typ = tag >> 4, tag & 0xF
        if typ == 0:
            v, k = read_varint(frame, j)
            if field == 9:
                enc = encode_varint(new_len); d = len(enc) - (k - j)
                frame[j:k] = enc; put_be32(frame, 6, hlen + d); put_be32(frame, 1, be32(frame, 1) + d); return bytes(frame)
            i = k
        elif typ == 1: i = j + 1
        elif typ == 5: i = j + 4 + be32(frame, j)
        else: break
    raise ValueError('cabecera TGCP sin campo 9')

def parse_direct(buf):
    """(total, tipo, seq, cmd, flag, payload) del primer paquete completo, o None si falta data."""
    if len(buf) < 6: return None
    if buf[0] != 0 or buf[1] not in (1, 2, 3): raise ValueError('prefijo invalido %s' % bytes(buf[:2]).hex())
    total = be32(buf, 2) + 6
    if len(buf) < total: return None
    seq = cmd = flag = None; payload = b''; i = 6
    while i < total:
        tag = struct.unpack_from('>H', buf, i)[0]; i += 2
        if tag == 5: flag = buf[i]; i += 1
        elif tag == 7: i += 1
        elif tag == 4: ln = be32(buf, i); i += 4; payload = bytes(buf[i:i + ln]); i += ln
        elif tag == 2: seq = be32(buf, i); i += 4
        elif tag == 6: cmd = be32(buf, i); i += 4
        else: raise ValueError('tag desconocido %d' % tag)
    return total, buf[1], seq, cmd, flag, payload

def build_direct(typ, seq, cmd, payload):
    body = b''
    if seq: body += struct.pack('>HI', 2, seq)
    if cmd: body += struct.pack('>HI', 6, cmd)
    body += struct.pack('>HB', 5, DATATYPE_FLATBUFFERS) + struct.pack('>HI', 4, len(payload)) + payload
    return struct.pack('>HI', typ, len(body)) + body

# ---------------------------------------------------------------- blobs grabados (fallback y directorio)
class Blobs:
    def __init__(self, d):
        self.raw = {fn[:-4]: open(os.path.join(d, fn), 'rb').read() for fn in os.listdir(d) if fn.endswith('.bin')}
        self.rsp = {}
        for name, b in sorted(self.raw.items(), key=lambda kv: (not kv[0].startswith(('mroffline', 'anon_')), kv[0])):
            if b[:2] == b'\x00\x02':
                p = parse_direct(b)
                if p and p[3] not in self.rsp: self.rsp[p[3]] = p[5]
        self.ack = self.raw['anon_kAck63']; self.authrsp = self.raw['anon_kAuthRsp54']; self.bingo = self.raw['anon_kBingo55']
    def dir_responses(self, host, port):
        def split(b): n = be32(b, 1); return b[:n], bytearray(b[n:])
        frame, qa = split(self.raw['mroffline_assets_kQueryAddrRsp169'])
        old = b'\x0b\x00\x01\x00\x00\x00\x09127.0.0.1\x08\x00\x02\x00\x00\x1f\x90'; i = qa.find(old); assert i >= 0
        qa[i:i + len(old)] = b'\x0b\x00\x01' + struct.pack('>I', len(host)) + host.encode() + b'\x08\x00\x02' + struct.pack('>I', port)
        queryaddr = tgcp_set_extra_len(frame, len(qa)) + bytes(qa)
        frame, ds = split(self.raw['mroffline_assets_kDirServiceLocalZoneRsp293'])
        oldj = b'{"hosts":[{"host":"127.0.0.1:8080","zone":"local"}]}'; newj = ('{"hosts":[{"host":"%s:%d","zone":"local"}]}' % (host, port)).encode()
        j = ds.find(oldj); delta = len(newj) - len(oldj)
        inner = ds.rfind(b'\xaa\x00\x00\x00', 0, j); p25 = ds.find(b'\x25\x00\x00\x00', inner) + 1; p15 = ds.find(b'\x15\x00\x00\x00', p25) + 1
        for pos in (inner - 4, inner + 1, p25, p15, j - 4): put_be32(ds, pos, be32(ds, pos) + delta)
        ds[j:j + len(oldj)] = newj
        dirsvc = tgcp_set_extra_len(frame, len(ds)) + bytes(ds)
        return {b'DirService:get_server_dirtree_by_id': dirsvc, b'QueryAddrSvr:QueryAddrInfo': queryaddr,
                b'VersionUpdate:ReqUpdateVersion': self.raw['mroffline_assets_kVersionUpdateNoUpdateRsp171']}

# ---------------------------------------------------------------- sesion de juego
class Sesion:
    def __init__(self, srv, cid, reader, writer):
        self.srv = srv; self.cid = cid; self.reader = reader; self.writer = writer
        self.peer = writer.get_extra_info('peername'); self.jugador = None; self.despues = []; self.en_handler = False; self.pendientes = []
    def enviar_notificacion(self, tipo, datos):
        if self.en_handler:                       # la respuesta a la peticion en curso debe salir antes que los avisos
            self.pendientes.append((tipo, datos)); return
        try:
            payload = self.srv.codec.encode('GameSvrNotice', dict(DataType=tipo, Data=datos or {}))
            cmd = self.srv.notice_ids[tipo]
            self.writer.write(build_direct(NOTICE, 0, cmd, payload))
            log.info('[%d] => aviso %s %s', self.cid, tipo, json.dumps(datos, ensure_ascii=False)[:300] if self.srv.debug else '')
        except Exception:
            log.exception('[%d] no pude codificar el aviso %s', self.cid, tipo)
    async def run(self, first):
        buf = bytearray(first)
        while True:
            data = await asyncio.wait_for(self.reader.read(65536), 600)
            if not data: return
            if self.srv.debug: log.info('[%d] RX %s', self.cid, data.hex())
            buf += data
            while True:
                try: p = parse_direct(buf)
                except ValueError as e:
                    log.warning('[%d] paquete invalido (%s): %s', self.cid, e, bytes(buf[:64]).hex()); return
                if not p: break
                total, typ, seq, cmd, flag, payload = p; del buf[:total]
                self.procesar(seq, cmd, payload)
            await self.writer.drain()
    def procesar(self, seq, cmd, payload):
        """Nunca deja caer la conexion: cualquier fallo termina en una respuesta EmptyRsp."""
        srv = self.srv; nombre = srv.req_names.get(cmd, '?'); como = ''
        try:
            try: req = srv.codec.decode('GameSvrRequest', payload)
            except Exception as e:
                req = None; log.warning('[%d] no pude decodificar cmd=%d %s: %s', self.cid, cmd, nombre, e)
            tipo = (req or {}).get('DataType') or nombre; datos = (req or {}).get('Data') or {}
            log.info('[%d] <- %s seq=%d %s', self.cid, tipo, seq, json.dumps(datos, ensure_ascii=False, default=str)[:400])
            handler = srv.juego.handlers.get(tipo); rsp_payload = None
            if handler and (self.jugador or tipo in srv.juego.PUBLICOS):
                self.en_handler = True
                try:
                    r = handler(self, datos) or ('EmptyRsp', {})
                    rsp_payload = srv.codec.encode('GameSvrRsp', dict(DataType=r[0], Data=r[1])); como = r[0]
                except Exception:
                    log.exception('[%d] error en handler %s', self.cid, tipo); rsp_payload = None
                finally:
                    self.en_handler = False
            if rsp_payload is None and cmd in srv.blobs.rsp:
                rsp_payload = bytearray(srv.blobs.rsp[cmd]); como = 'grabado'
                if cmd == 92:
                    i = rsp_payload.find(b'\xc0\x72\x5a\x63')
                    if i >= 0: struct.pack_into('<I', rsp_payload, i, int(time.time()))
            if rsp_payload is None: rsp_payload = srv.empty; como = 'EmptyRsp'
        except Exception:
            log.exception('[%d] error procesando cmd=%d', self.cid, cmd); rsp_payload = srv.empty; como = 'EmptyRsp (error)'
        self.writer.write(build_direct(RESPONSE, seq, cmd, bytes(rsp_payload)))
        log.info('[%d] -> %s (%d bytes)', self.cid, como, len(rsp_payload))
        pend = self.pendientes + self.despues; self.pendientes = []; self.despues = []
        for tipo_n, datos_n in pend:
            try:
                if tipo_n == '__emparejar__': srv.juego.emparejar(datos_n)
                elif tipo_n == '__estado__': srv.juego.estado_partida(datos_n)
                else: self.enviar_notificacion(tipo_n, datos_n)
            except Exception:
                log.exception('[%d] error enviando %s', self.cid, tipo_n)

# ---------------------------------------------------------------- servidor
class Server:
    def __init__(self, a):
        self.debug = a.debug; self.host = a.host; self.port = a.port
        self.codec = Codec(json.load(open(os.path.join(HERE, 'esquema_fb.json'))))
        self.req_names = {v: k for k, v in self.codec.E['GameSvrReqUnion']['values'].items()}
        self.notice_ids = self.codec.E['GameSvrNoticeUnion']['values']
        self.empty = self.codec.encode('GameSvrRsp', dict(DataType='EmptyRsp', Data={}))   # falla aqui si falta flatbuffers
        self.blobs = Blobs(a.blobs); self.dir = self.blobs.dir_responses(a.host, a.port)
        cat = json.load(open(os.path.join(HERE, '..', 'datos', 'catalogo_mensajes_grabados.json'), encoding='utf-8'))
        plantilla = cat['mroffline_assets_kGameLoginMikeKimSkinsRsp843']['msg']['Data']
        self.juego = Juego(a.host, a.port, a.port, plantilla, a.nombre_automatico); self.conns = 0
    async def handle(self, reader, writer):
        self.conns += 1; cid = self.conns; peer = writer.get_extra_info('peername'); ses = None
        log.info('[%d] conexion de %s', cid, peer)
        try:
            first = await asyncio.wait_for(reader.readexactly(1), 60)
            if first in (b'\xaa', b'\x43'): await self.tgcp(cid, reader, writer, first)
            elif first == b'\x00':
                ses = Sesion(self, cid, reader, writer); await ses.run(first)
            else:
                rest = await asyncio.wait_for(reader.read(4096), 5); log.warning('[%d] primer byte desconocido; datos: %s', cid, (first + rest).hex())
        except asyncio.TimeoutError: log.warning('[%d] sin datos, cierro', cid)
        except (asyncio.IncompleteReadError, ConnectionResetError) as e: log.info('[%d] cliente cerro (%s)', cid, type(e).__name__)
        except Exception: log.exception('[%d] error', cid)
        finally:
            if ses and ses.jugador: self.juego.desconectar(ses.jugador)
            writer.close(); log.info('[%d] cerrada', cid)
    async def tgcp(self, cid, reader, writer, first):
        n = 0
        while True:
            skipped = b''
            while first != b'\xaa':
                skipped += first
                if len(skipped) > 16: log.warning('[%d] TGCP desincronizado: %s', cid, skipped.hex()); return
                first = await asyncio.wait_for(reader.readexactly(1), 60)
            head = first + await asyncio.wait_for(reader.readexactly(4), 60); total = be32(head, 1)
            if not 5 <= total <= 65536: log.warning('[%d] TGCP largo invalido %d', cid, total); return
            pkt = head + await asyncio.wait_for(reader.readexactly(total - 5), 60)
            h = tgcp_head(pkt); extra = await asyncio.wait_for(reader.readexactly(h.get(9, 0)), 60) if h.get(9) else b''
            n += 1; cmd = h.get(4)
            log.info('[%d] TGCP #%d cmd=%s largo=%d datos=%d', cid, n, hex(cmd) if cmd is not None else '?', total, len(extra))
            if self.debug: log.info('[%d] RX %s %s', cid, pkt.hex(), extra.hex())
            if cmd == 0x1001: writer.write(self.blobs.ack); log.info('[%d] -> ACK63', cid)
            elif cmd == 0x2001: writer.write(self.blobs.authrsp + self.blobs.bingo); log.info('[%d] -> AUTHRSP54 + BINGO55', cid)
            else:
                for name, rsp in self.dir.items():
                    if name in extra or name in pkt: writer.write(rsp); log.info('[%d] -> %s', cid, name.decode()); break
                else:
                    if n == 1: writer.write(self.blobs.ack); log.info('[%d] -> ACK63 (por orden)', cid)
                    elif n == 2: writer.write(self.blobs.authrsp + self.blobs.bingo); log.info('[%d] -> AUTHRSP54 + BINGO55 (por orden)', cid)
                    elif cmd == 0x5001: log.info('[%d] TGCP fin de sesion', cid)
                    else: log.warning('[%d] TGCP sin respuesta: %s %s', cid, pkt.hex(), extra.hex())
            await writer.drain()
            if reader.at_eof(): return
            first = await asyncio.wait_for(reader.readexactly(1), 120)

class RelayUDP(asyncio.DatagramProtocol):
    """Fase 3 (pendiente): por ahora registra lo que llega para aprender el formato."""
    def __init__(self, srv): self.srv = srv; self.n = 0
    def connection_made(self, transport): self.transport = transport
    def datagram_received(self, data, addr):
        self.n += 1
        if self.n <= 200 or self.srv.debug: log.info('UDP %s %d bytes: %s', addr, len(data), data[:64].hex())

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', required=True); ap.add_argument('--port', type=int, default=8080); ap.add_argument('--listen', default='0.0.0.0')
    ap.add_argument('--blobs', default=os.path.join(HERE, 'blobs')); ap.add_argument('--log', default='mr_server.log')
    ap.add_argument('--debug', action='store_true'); ap.add_argument('--nombre-automatico', action='store_true', help='asigna JugadorNNN sin pedir nombre')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(a.log, encoding='utf-8')])
    srv = Server(a)
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: RelayUDP(srv), local_addr=(a.listen, a.port))
    server = await asyncio.start_server(srv.handle, a.listen, a.port)
    log.info('fase 2: escuchando TCP y UDP en %s:%d (los clientes usaran %s:%d); %d handlers', a.listen, a.port, a.host, a.port, len(srv.juego.handlers))
    async with server: await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
