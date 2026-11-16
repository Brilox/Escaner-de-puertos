#!/usr/bin/env python3
"""Servidor privado experimental para Metal Revolution (cliente "Metal Offline V2").

Fase 1: reproduce las respuestas grabadas del servidor original (las mismas que usa el mod en su servidor
local 127.0.0.1:8080) pero escuchando en una IP publica, para que varios telefonos lleguen al mismo servidor.

Dos clases de conexion llegan al mismo puerto:
  * TGCP (primer byte 0xAA): handshake SYN/ACK, AUTH/AUTHRSP+BINGO y luego peticiones Pebble RPC del
    directorio (DirService, QueryAddrSvr, VersionUpdate). Respondemos con los blobs grabados, parcheando
    la direccion del servidor de juego para que apunte a --host.
  * DIRECTO (primer byte 0x00): protocolo del juego: u16 tipo | u32 largo | TLV(seq, cmd, flag, payload FlatBuffers).
    Respondemos con el blob grabado para ese cmd, copiando el seq de la peticion. Si no hay blob, EmptyRsp.

Uso: python3 mr_server.py --host <ip-o-dominio-publico> [--port 8080] [--blobs blobs]
"""
import argparse, asyncio, json, logging, os, struct, time

log = logging.getLogger('mr')
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- utilidades de protocolo
def be32(b, o): return struct.unpack_from('>I', b, o)[0]
def put_be32(b, o, v): struct.pack_into('>I', b, o, v)

def read_varint(b, i):
    v = sh = 0
    while True:
        c = b[i]; i += 1; v |= (c & 0x7f) << sh; sh += 7
        if not c & 0x80: return v, i

def tgcp_head(pkt):
    """Campos de la cabecera TGCP (tag 0x15): {campo: valor}. Campo 4 = comando, campo 9 = bytes de datos que siguen al paquete."""
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
    except (IndexError, struct.error):
        pass
    return f

def encode_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7f; v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v: return bytes(out)

def tgcp_set_extra_len(frame, new_len):
    """Reescribe el campo 9 de la cabecera (largo de los datos que siguen) ajustando los largos del paquete."""
    frame = bytearray(frame); hlen = be32(frame, 6); i, end = 10, 10 + hlen
    while i < end:
        tag, j = read_varint(frame, i); field, typ = tag >> 4, tag & 0xF
        if typ == 0:
            v, k = read_varint(frame, j)
            if field == 9:
                enc = encode_varint(new_len); d = len(enc) - (k - j)
                frame[j:k] = enc; put_be32(frame, 6, hlen + d); put_be32(frame, 1, be32(frame, 1) + d)
                return bytes(frame)
            i = k
        elif typ == 1: i = j + 1
        elif typ == 5: i = j + 4 + be32(frame, j)
        else: break
    raise ValueError('cabecera TGCP sin campo 9')

def parse_direct(buf):
    """Devuelve (total, seq, cmd, flag, payload) del primer paquete del juego en buf, o None si esta incompleto."""
    if len(buf) < 6: return None
    if buf[0] != 0 or buf[1] not in (1, 2): raise ValueError('prefijo invalido %s' % buf[:2].hex())
    total = be32(buf, 2) + 6
    if len(buf) < total: return None
    seq = cmd = flag = None; payload = b''; i = 6
    while i < total:
        tag = struct.unpack_from('>H', buf, i)[0]; i += 2
        if tag == 5: flag = buf[i]; i += 1
        elif tag == 4: ln = be32(buf, i); i += 4; payload = buf[i:i + ln]; i += ln
        elif tag == 2: seq = be32(buf, i); i += 4
        elif tag == 6: cmd = be32(buf, i); i += 4
        else: raise ValueError('tag desconocido %d' % tag)
    return total, seq, cmd, flag, payload

def build_direct(typ, seq, cmd, flag, payload):
    body = struct.pack('>HIHIHB', 2, seq, 6, cmd, 5, flag) + struct.pack('>HI', 4, len(payload)) + payload
    return struct.pack('>HI', typ, len(body)) + body

# ---------------------------------------------------------------- blobs grabados
class Blobs:
    def __init__(self, d):
        self.raw = {fn[:-4]: open(os.path.join(d, fn), 'rb').read() for fn in os.listdir(d) if fn.endswith('.bin')}
        self.rsp = {}   # cmd -> payload de respuesta grabada (con su flag)
        prefer = ('mroffline', 'anon_')  # prioridad al nombre
        for name, b in sorted(self.raw.items(), key=lambda kv: (not kv[0].startswith(prefer), kv[0])):
            if b[:2] == b'\x00\x02':
                p = parse_direct(b)
                if p and p[2] not in self.rsp:
                    self.rsp[p[2]] = (p[3], p[4], name)
        self.ack = self.raw['anon_kAck63']; self.authrsp = self.raw['anon_kAuthRsp54']; self.bingo = self.raw['anon_kBingo55']
        self.empty_payload = self.rsp[123][1]  # ChangeHeroSkinRsp = EmptyRsp (tipo de union 2)

    def dir_responses(self, host, port):
        """Las tres respuestas del directorio con la direccion del servidor de juego parcheada.
        Cada blob es: paquete TGCP (aa + largo) seguido de un mensaje Pebble/Thrift de 'campo 9' bytes."""
        def split(b):
            n = be32(b, 1); return b[:n], bytearray(b[n:])
        frame, qa = split(self.raw['mroffline_assets_kQueryAddrRsp169'])
        old = b'\x0b\x00\x01\x00\x00\x00\x09127.0.0.1\x08\x00\x02\x00\x00\x1f\x90'
        i = qa.find(old); assert i >= 0
        qa[i:i + len(old)] = b'\x0b\x00\x01' + struct.pack('>I', len(host)) + host.encode() + b'\x08\x00\x02' + struct.pack('>I', port)
        queryaddr = tgcp_set_extra_len(frame, len(qa)) + bytes(qa)
        frame, ds = split(self.raw['mroffline_assets_kDirServiceLocalZoneRsp293'])
        oldj = b'{"hosts":[{"host":"127.0.0.1:8080","zone":"local"}]}'
        newj = ('{"hosts":[{"host":"%s:%d","zone":"local"}]}' % (host, port)).encode()
        j = ds.find(oldj); assert j >= 0; delta = len(newj) - len(oldj)
        inner = ds.rfind(b'\xaa\x00\x00\x00', 0, j)          # blob TDR interno (aa + largo)
        p25 = ds.find(b'\x25\x00\x00\x00', inner) + 1          # struct f2
        p15 = ds.find(b'\x15\x00\x00\x00', p25) + 1            # struct f1
        for pos in (inner - 4, inner + 1, p25, p15, j - 4):      # largos que envuelven al JSON
            put_be32(ds, pos, be32(ds, pos) + delta)
        ds[j:j + len(oldj)] = newj
        assert be32(ds, j - 4) == len(newj) and be32(ds, inner + 1) == len(ds) - inner - (len(ds) - ds.find(b'\x0f\x00\x03', j))
        dirsvc = tgcp_set_extra_len(frame, len(ds)) + bytes(ds)
        return {b'DirService:get_server_dirtree_by_id': dirsvc, b'QueryAddrSvr:QueryAddrInfo': queryaddr,
                b'VersionUpdate:ReqUpdateVersion': self.raw['mroffline_assets_kVersionUpdateNoUpdateRsp171']}

# ---------------------------------------------------------------- servidor
class Server:
    def __init__(self, blobs, host, port, names, debug=False):
        self.debug = debug; self.b = blobs; self.dir = blobs.dir_responses(host, port); self.names = names; self.conns = 0

    async def handle(self, reader, writer):
        peer = writer.get_extra_info('peername'); self.conns += 1; cid = self.conns
        log.info('[%d] conexion de %s', cid, peer)
        try:
            first = await asyncio.wait_for(reader.readexactly(1), 60)
            log.info('[%d] primer byte %s -> modo %s', cid, first.hex(), 'TGCP' if first == b'\xaa' else 'DIRECTO' if first == b'\x00' else '?')
            if first == b'\xaa': await self.tgcp(cid, reader, writer, first)
            elif first == b'\x00': await self.direct(cid, reader, writer, first)
            else:
                rest = await asyncio.wait_for(reader.read(4096), 5)
                log.warning('[%d] primer byte desconocido; datos: %s', cid, (first + rest).hex())
        except asyncio.TimeoutError:
            log.warning('[%d] sin datos durante 60 s, cierro', cid)
        except (asyncio.IncompleteReadError, ConnectionResetError) as e:
            log.info('[%d] cliente cerro la conexion (%s)', cid, type(e).__name__)
        except Exception:
            log.exception('[%d] error', cid)
        finally:
            writer.close(); log.info('[%d] cerrada', cid)

    async def tgcp(self, cid, reader, writer, first):
        n = 0
        while True:
            if first != b'\xaa':
                junk = first + await asyncio.wait_for(reader.read(4096), 5)
                log.warning('[%d] TGCP desincronizado, bytes: %s', cid, junk.hex())
                return
            head = first + await asyncio.wait_for(reader.readexactly(4), 60); first = b''
            total = be32(head, 1)
            if not 5 <= total <= 65536:
                log.warning('[%d] TGCP largo invalido %d (cabecera %s)', cid, total, head.hex()); return
            pkt = head + await asyncio.wait_for(reader.readexactly(total - 5), 60)
            h = tgcp_head(pkt); extra = await asyncio.wait_for(reader.readexactly(h.get(9, 0)), 60) if h.get(9) else b''
            n += 1; cmd = h.get(4)
            log.info('[%d] TGCP #%d cmd=%s largo=%d datos=%d cabecera=%s', cid, n, hex(cmd) if cmd is not None else '?', total, len(extra), h)
            if self.debug: log.info('[%d] RX %s %s', cid, pkt.hex(), extra.hex())
            for name, rsp in self.dir.items():
                if name in pkt or name in extra:
                    writer.write(rsp); log.info('[%d] -> %s (%d bytes)', cid, name.decode(), len(rsp)); break
            else:
                if cmd == 0x1001 or n == 1:
                    writer.write(self.b.ack); log.info('[%d] -> ACK63', cid)
                elif cmd == 0x2001 or n == 2:
                    writer.write(self.b.authrsp + self.b.bingo); log.info('[%d] -> AUTHRSP54 + BINGO55', cid)
                else:
                    log.warning('[%d] TGCP sin respuesta: %s %s', cid, pkt.hex(), extra.hex())
            await writer.drain()
            if reader.at_eof(): return
            first = await asyncio.wait_for(reader.readexactly(1), 120)

    async def direct(self, cid, reader, writer, first):
        buf = bytearray(first)
        while True:
            data = await asyncio.wait_for(reader.read(65536), 300)
            if not data: return
            if self.debug: log.info('[%d] RX %s', cid, data.hex())
            buf += data
            while True:
                try: p = parse_direct(buf)
                except ValueError as e:
                    log.warning('[%d] paquete directo invalido (%s): %s', cid, e, bytes(buf[:64]).hex()); return
                if not p: break
                total, seq, cmd, flag, payload = p; del buf[:total]
                name = self.names.get(cmd, '?')
                rsp = self.response(cmd, seq, flag, payload)
                writer.write(rsp)
                log.info('[%d] <- cmd=%d %s seq=%d (%d bytes)  -> %d bytes', cid, cmd, name, seq, len(payload), len(rsp))
            await writer.drain()

    def response(self, cmd, seq, flag, payload):
        if cmd in self.b.rsp:
            rflag, rpayload, _ = self.b.rsp[cmd]; rpayload = bytearray(rpayload)
            if cmd == 92:   # QueryServerTimeRsp: hora unix (u32 LE) en el campo grabado
                i = rpayload.find(b'\xc0\x72\x5a\x63'); struct.pack_into('<I', rpayload, i, int(time.time()))
            elif cmd == 47:  # PlayerClientPong: milisegundos (u64 LE)
                i = rpayload.find(b'\x91\xcd\xea\x48\xa0\x01\x00\x00'); struct.pack_into('<Q', rpayload, i, int(time.time() * 1000))
            return build_direct(2, seq, cmd, rflag, bytes(rpayload))
        return build_direct(2, seq, cmd, flag if flag is not None else 2, self.b.empty_payload)

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', required=True, help='IP o dominio publico que veran los clientes')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--listen', default='0.0.0.0')
    ap.add_argument('--blobs', default=os.path.join(HERE, 'blobs'))
    ap.add_argument('--log', default='mr_server.log', help='archivo donde se guarda una copia del log')
    ap.add_argument('--debug', action='store_true', help='registra en hexadecimal todo lo recibido')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(a.log, encoding='utf-8')])
    proto = json.load(open(os.path.join(HERE, 'protocolo.json')))
    names = {i: n for i, n in enumerate(proto['GameSvrReqUnion'])}
    blobs = Blobs(a.blobs)
    log.info('%d respuestas grabadas para %d comandos', len(blobs.raw), len(blobs.rsp))
    srv = Server(blobs, a.host, a.port, names, a.debug)
    server = await asyncio.start_server(srv.handle, a.listen, a.port)
    log.info('escuchando en %s:%d (los clientes usaran %s:%d)', a.listen, a.port, a.host, a.port)
    async with server: await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
