#!/usr/bin/env python3
"""Relay de la pelea en tiempo real (UDP).

Durante la pelea los dos (o cuatro) telefonos no se hablan entre ellos: cada uno manda sus botones al servidor
y el servidor los reenvia a los demas. Este modulo hace ese trabajo. Protocolo (leido del codigo del juego):

  * Ping previo: datagrama con el mismo formato TLV del canal TCP (empieza por 00 01). Se contesta igual, con tipo 00 02.
    OJO: el juego manda este ping al puerto del relay MENOS UNO (RelayServerInfo.Port - 1, p. ej. 8079 si el relay es 8080).
    Si ese puerto no contesta, el juego se queda en la carga (~88 %) y a los pocos segundos se reconecta.
  * Canal fiable: KCP estandar (cabecera de 24 bytes little-endian: conv, cmd, frg, wnd, ts, sn, una, len).
  * Canal rapido: datagrama que empieza por 4 bytes a cero y despues los mensajes tal cual, sin garantia de entrega.
  * Mensajes (el primer byte es el tipo, todo little-endian, pueden venir varios seguidos):
        0  EnterRoom   matchId i32, subMatchId u16, side u8, pos u8, reEnter u8, teamSize u8      (11 bytes)
        1  ExitRoom, 2 HeartBeat                                                                   (1 byte)
        14 Input       frame i32, botones u16          -> a los demas: frame, side, pos, botones   (7 -> 9)
        15 SyncPing    frame i32, ping u16             -> igual                                    (7 -> 9)
        16 CheckSync   frame i32, hash u16             -> igual                                    (7 -> 9)
        17 Emoji       frame i32, emoji u32            -> igual                                    (9 -> 11)
        18 Item        frame i32, item u32, x i32, y i32 -> igual                                  (17 -> 19)
    Del servidor al cliente, el tipo 0 (un solo byte) significa "ya entraron todos, empieza la pelea".

Corre en un hilo propio con un socket normal: asi funciona igual en Windows y Linux y no compite con el resto del
servidor. No usa ninguna libreria externa."""
import collections, logging, select, socket, struct, threading, time

log = logging.getLogger('mr.relay')
CMD_PUSH, CMD_ACK, CMD_WASK, CMD_WINS = 81, 82, 83, 84
CABECERA = 24
MTU = 1200
TAM = {0: 11, 1: 1, 2: 1, 14: 7, 15: 7, 16: 7, 17: 9, 18: 17}      # tamano de cada mensaje cliente -> servidor
NOMBRE = {0: 'EnterRoom', 1: 'ExitRoom', 2: 'HeartBeat', 14: 'Input', 15: 'SyncPing', 16: 'CheckSync', 17: 'Emoji', 18: 'Item'}
INACTIVO = 20.0                                                      # segundos sin recibir nada para dar por perdido a un jugador


def ms():
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


class _Seg:
    __slots__ = ('sn', 'frg', 'datos', 'xmit', 'rto', 'resendts', 'fastack')

    def __init__(self, frg, datos):
        self.sn = 0; self.frg = frg; self.datos = datos; self.xmit = 0; self.rto = 0; self.resendts = 0; self.fastack = 0


class Kcp:
    """KCP minimo (ARQ sobre UDP) compatible con el del juego: nodelay, intervalo 10 ms, reenvio rapido a los 2 ACK
    saltados, sin control de congestion, ventanas de 128."""

    def __init__(self, conv, salida):
        self.conv = conv; self.salida = salida
        self.snd_una = 0; self.snd_nxt = 0; self.rcv_nxt = 0
        self.snd_wnd = 128; self.rcv_wnd = 128; self.rmt_wnd = 128
        self.mss = MTU - CABECERA
        self.cola_envio = collections.deque(); self.sin_confirmar = []
        self.fuera_de_orden = {}; self.cola_recibo = collections.deque()
        self.acks = []
        self.srtt = 0; self.rttvar = 0; self.rto = 100; self.rto_min = 30
        self.reenvio_rapido = 2; self.responder_ventana = False; self.sig_sondeo = 0
        self.muerto = False; self.reenvios = 0

    # ---- entrada
    def input(self, data, ahora):
        pos = 0; maxack = None; n = len(data)
        while n - pos >= CABECERA:
            conv, cmd, frg, wnd, ts, sn, una, ln = struct.unpack_from('<IBBHIIII', data, pos); pos += CABECERA
            if conv != self.conv or cmd not in (CMD_PUSH, CMD_ACK, CMD_WASK, CMD_WINS) or n - pos < ln: return False
            self.rmt_wnd = wnd
            while self.sin_confirmar and self.sin_confirmar[0].sn < una: self.sin_confirmar.pop(0)
            if cmd == CMD_ACK:
                rtt = (ahora - ts) & 0xFFFFFFFF
                if rtt < 60000: self._rtt(rtt)
                for i, s in enumerate(self.sin_confirmar):
                    if s.sn == sn: del self.sin_confirmar[i]; break
                    if s.sn > sn: break
                if maxack is None or sn > maxack: maxack = sn
            elif cmd == CMD_PUSH:
                if sn < self.rcv_nxt + self.rcv_wnd:
                    self.acks.append((sn, ts))
                    if sn >= self.rcv_nxt and sn not in self.fuera_de_orden:
                        self.fuera_de_orden[sn] = (frg, bytes(data[pos:pos + ln])); self._ordenar()
            elif cmd == CMD_WASK:
                self.responder_ventana = True
            pos += ln
        self.snd_una = self.sin_confirmar[0].sn if self.sin_confirmar else self.snd_nxt
        if maxack is not None:
            for s in self.sin_confirmar:
                if s.sn >= maxack: break
                s.fastack += 1
        return True

    def _ordenar(self):
        while self.rcv_nxt in self.fuera_de_orden and len(self.cola_recibo) < self.rcv_wnd:
            self.cola_recibo.append(self.fuera_de_orden.pop(self.rcv_nxt)); self.rcv_nxt += 1

    def _rtt(self, rtt):
        if self.srtt == 0: self.srtt = rtt; self.rttvar = rtt // 2
        else:
            self.rttvar = (3 * self.rttvar + abs(rtt - self.srtt)) // 4; self.srtt = max(1, (7 * self.srtt + rtt) // 8)
        self.rto = min(max(self.rto_min, self.srtt + max(10, 4 * self.rttvar)), 5000)

    def recv(self):
        """Devuelve el siguiente mensaje completo o None."""
        n = 0
        for frg, _ in self.cola_recibo:
            n += 1
            if frg == 0: break
        else:
            return None
        partes = [self.cola_recibo.popleft()[1] for _ in range(n)]
        self._ordenar()
        return partes[0] if n == 1 else b''.join(partes)

    # ---- salida
    def send(self, datos):
        trozos = [datos[i:i + self.mss] for i in range(0, len(datos), self.mss)] or [b'']
        for i, t in enumerate(trozos): self.cola_envio.append(_Seg(len(trozos) - 1 - i, t))

    def pendiente(self):
        return bool(self.acks or self.cola_envio or self.sin_confirmar or self.responder_ventana)

    def flush(self, ahora):
        wnd = max(0, self.rcv_wnd - len(self.cola_recibo)); una = self.rcv_nxt; out = []; tam = 0

        def emitir(cmd, frg, ts, sn, datos=b''):
            nonlocal out, tam
            if tam + CABECERA + len(datos) > MTU and out:
                self.salida(b''.join(out)); out = []; tam = 0
            out.append(struct.pack('<IBBHIIII', self.conv, cmd, frg, wnd, ts & 0xFFFFFFFF, sn, una, len(datos))); out.append(datos)
            tam += CABECERA + len(datos)

        for sn, ts in self.acks: emitir(CMD_ACK, 0, ts, sn)
        self.acks = []
        if self.rmt_wnd == 0 and ahora >= self.sig_sondeo:
            emitir(CMD_WASK, 0, 0, 0); self.sig_sondeo = ahora + 1000
        if self.responder_ventana:
            emitir(CMD_WINS, 0, 0, 0); self.responder_ventana = False
        tope = self.snd_una + max(1, min(self.snd_wnd, self.rmt_wnd))
        while self.cola_envio and self.snd_nxt < tope:
            s = self.cola_envio.popleft(); s.sn = self.snd_nxt; self.snd_nxt += 1; self.sin_confirmar.append(s)
        for s in self.sin_confirmar:
            if s.xmit == 0:
                s.rto = self.rto; s.resendts = ahora + s.rto
            elif ahora >= s.resendts:
                s.rto += max(s.rto, self.rto) // 2; s.resendts = ahora + s.rto; self.reenvios += 1
            elif s.fastack >= self.reenvio_rapido:
                s.resendts = ahora + s.rto; self.reenvios += 1
            else:
                continue
            s.xmit += 1; s.fastack = 0
            if s.xmit > 40: self.muerto = True
            emitir(CMD_PUSH, s.frg, ahora, s.sn, s.datos)
        if out: self.salida(b''.join(out))


class Par:
    """Un telefono conectado al relay."""

    def __init__(self, addr, kcp):
        self.addr = addr; self.kcp = kcp; self.sala = None; self.lado = 0; self.pos = 0; self.sub = 0
        self.esperando = False; self.ultimo = time.monotonic(); self.rapido = []; self.recibidos = 0; self.enviados = 0


class Sala:
    def __init__(self, id_):
        self.id = id_; self.pares = {}; self.completa = False; self.inputs = 0; self.inicio = 0.0


class Relay(threading.Thread):
    """esperados(match_id) -> cuantos telefonos tienen que entrar antes de empezar (None si la partida no existe).
    al_empezar(match_id) y al_salir(match_id, lado, pos) se llaman desde el hilo del relay."""

    def __init__(self, escucha, puerto, esperados=None, al_empezar=None, puerto_ping=None):
        super().__init__(name='relay', daemon=True)
        self.sock = self._socket(escucha, puerto); self.puerto = self.sock.getsockname()[1]
        if puerto_ping is None: puerto_ping = self.puerto - 1
        self.sock_ping = self._socket(escucha, puerto_ping) if puerto_ping and puerto_ping != self.puerto else None
        self.puerto_ping = self.sock_ping.getsockname()[1] if self.sock_ping else self.puerto
        self.socks = [x for x in (self.sock, self.sock_ping) if x]
        self.esperados = esperados or (lambda mid: 2); self.al_empezar = al_empezar
        self.pares = {}; self.salas = {}; self.sucios = set(); self.activo = True
        self.pings = 0; self.raros = 0; self._ult_tick = 0.0; self._ult_limpieza = 0.0

    @staticmethod
    def _socket(escucha, puerto):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, 'SIO_UDP_CONNRESET'):          # Windows: que un telefono que se fue no rompa la lectura
            try: s.ioctl(socket.SIO_UDP_CONNRESET, False)
            except (OSError, ValueError): pass
        s.bind((escucha, puerto)); s.setblocking(False); return s

    def parar(self):
        self.activo = False

    # ---- bucle
    def run(self):
        log.info('relay UDP escuchando: pelea en el puerto %d, ping previo en el puerto %d', self.puerto, self.puerto_ping)
        while self.activo:
            try: listos, _, _ = select.select(self.socks, [], [], 0.005)
            except (OSError, ValueError): listos = []
            for s in listos:
                for _ in range(64):                  # vacia lo que haya en el socket
                    try: data, addr = s.recvfrom(4096)
                    except (BlockingIOError, InterruptedError): break
                    except OSError: break            # en Windows un envio a un puerto cerrado aparece aqui como error
                    try: self.datagrama(data, addr, s)
                    except Exception: log.exception('error en el relay (se ignora el paquete)')
            try:
                t = time.monotonic()
                if t - self._ult_tick >= 0.01: self._ult_tick = t; self.tick(t)
            except Exception:
                log.exception('error en el relay')
        for s in self.socks: s.close()

    def _enviar_udp(self, data, addr):
        try: self.sock.sendto(data, addr)
        except OSError: pass

    def datagrama(self, data, addr, sock=None):
        if len(data) >= 6 and data[0] == 0 and data[1] == 1:          # ping TLV previo a la conexion
            self.pings += 1
            if self.pings <= 5 or self.pings % 500 == 0:
                log.info('relay: ping UDP de %s:%d al puerto %d (%d en total)', addr[0], addr[1], (sock or self.sock).getsockname()[1], self.pings)
            try: (sock or self.sock).sendto(b'\x00\x02' + data[2:], addr)
            except OSError: pass
            return
        if sock is not None and sock is self.sock_ping:               # en el puerto del ping solo se esperan pings
            self.raros += 1
            if self.raros <= 10: log.warning('relay: datagrama desconocido en el puerto del ping de %s:%d: %s', addr[0], addr[1], data[:48].hex())
            return
        if len(data) < 5: return
        par = self.pares.get(addr)
        if data[:4] == b'\0\0\0\0':                                     # canal rapido, sin KCP
            if par is None:
                par = self.pares[addr] = Par(addr, Kcp(6666, lambda b, a=addr: self._enviar_udp(b, a)))
                log.info('relay: nuevo telefono %s:%d (canal rapido)', addr[0], addr[1])
            par.ultimo = time.monotonic(); self.mensajes(par, data[4:], False)
        else:
            conv = struct.unpack_from('<I', data)[0]
            if par is None or (par.kcp.conv != conv and par.kcp.snd_nxt == 0 and par.kcp.rcv_nxt == 0):
                if len(data) < CABECERA or data[4] not in (CMD_PUSH, CMD_ACK, CMD_WASK, CMD_WINS):
                    self.raros += 1
                    if self.raros <= 10: log.warning('relay: datagrama desconocido de %s:%d: %s', addr[0], addr[1], data[:48].hex())
                    return
                viejo = par
                par = self.pares[addr] = Par(addr, Kcp(conv, lambda b, a=addr: self._enviar_udp(b, a)))
                if viejo and viejo.sala: self.quitar(viejo, borrar=False)
                log.info('relay: nuevo telefono %s:%d (KCP conv=%d)', addr[0], addr[1], conv)
            par.ultimo = time.monotonic()
            if not par.kcp.input(data, ms()):
                self.raros += 1
                if self.raros <= 10: log.warning('relay: KCP invalido de %s:%d: %s', addr[0], addr[1], data[:48].hex())
                return
            while True:
                m = par.kcp.recv()
                if m is None: break
                self.mensajes(par, m, True)
            self.sucios.add(par)
        ahora = ms()
        for p in self.sucios:
            if p.rapido: self._enviar_udp(b'\0\0\0\0' + b''.join(p.rapido), p.addr); p.rapido = []
            p.kcp.flush(ahora)
        self.sucios.clear()

    def tick(self, t):
        ahora = ms()
        for p in self.pares.values():
            if p.kcp.pendiente(): p.kcp.flush(ahora)
        if t - self._ult_limpieza >= 2.0:
            self._ult_limpieza = t
            for p in list(self.pares.values()):
                if t - p.ultimo > INACTIVO or p.kcp.muerto:
                    log.info('relay: %s:%d sin respuesta, se retira', p.addr[0], p.addr[1]); self.quitar(p)

    # ---- mensajes
    def enviar(self, par, datos, fiable):
        if fiable: par.kcp.send(datos)
        else: par.rapido.append(datos)
        par.enviados += 1; self.sucios.add(par)

    def mensajes(self, par, buf, fiable):
        i = 0; n = len(buf)
        while i < n:
            t = buf[i]; tam = TAM.get(t)
            if tam is None or i + tam > n:
                self.raros += 1
                if self.raros <= 20: log.warning('relay: mensaje desconocido tipo=%d de %s:%d: %s', t, par.addr[0], par.addr[1], bytes(buf[i:i + 40]).hex())
                return
            m = buf[i:i + tam]; i += tam; par.recibidos += 1
            if t == 0: self.entrar(par, m)
            elif t == 1: self.salir(par)
            elif t == 2: pass
            elif par.sala is not None:
                rsp = m[:5] + bytes((par.lado, par.pos)) + m[5:]
                if t == 14: par.sala.inputs += 1
                for otro in par.sala.pares.values():
                    if otro is not par: self.enviar(otro, rsp, fiable)

    def entrar(self, par, m):
        _, mid, sub, lado, pos, reentra, equipo = struct.unpack('<BiHBBBB', m)
        sala = self.salas.get(mid)
        if sala is None: sala = self.salas[mid] = Sala(mid)
        for otro in list(sala.pares.values()):                      # el mismo jugador desde otra conexion: la vieja sobra
            if otro is not par and (otro.lado, otro.pos) == (lado, pos): self.quitar(otro)
        if par.sala is not None and par.sala is not sala: self.quitar(par, borrar=False)
        par.sala = sala; par.lado = lado; par.pos = pos; par.sub = sub; par.esperando = True; sala.pares[par.addr] = par
        esperados = self.esperados(mid) or 2
        log.info('relay: pelea %d: entra lado=%d pos=%d desde %s:%d (%d de %d)%s', mid, lado, pos, par.addr[0], par.addr[1],
                 sum(1 for o in sala.pares.values() if o.esperando), esperados, ' [reconexion]' if reentra else '')
        if reentra and sala.completa:
            par.esperando = False; self.enviar(par, b'\x00', True); return
        listos = [o for o in sala.pares.values() if o.esperando]
        if len(listos) >= esperados and len(listos) == len(sala.pares):
            sala.completa = True; sala.inputs = 0; sala.inicio = time.monotonic()
            for o in listos: o.esperando = False; self.enviar(o, b'\x00', True)
            log.info('relay: pelea %d: estan todos, EMPIEZA LA PELEA', mid)
            if self.al_empezar:
                try: self.al_empezar(mid)
                except Exception: log.exception('al_empezar')

    def salir(self, par):
        if par.sala is not None:
            log.info('relay: pelea %d: sale lado=%d pos=%d (recibidos=%d enviados=%d reenvios=%d)', par.sala.id, par.lado, par.pos,
                     par.recibidos, par.enviados, par.kcp.reenvios)
        self.quitar(par, borrar=False)

    def quitar(self, par, borrar=True):
        sala = par.sala
        if sala is not None:
            if sala.pares.get(par.addr) is par: del sala.pares[par.addr]
            par.sala = None; par.esperando = False
            if not sala.pares:
                if sala.completa:
                    log.info('relay: pelea %d terminada: %d inputs reenviados en %.0f s', sala.id, sala.inputs, time.monotonic() - sala.inicio)
                self.salas.pop(sala.id, None)
        if borrar and self.pares.get(par.addr) is par: del self.pares[par.addr]
        self.sucios.discard(par)
