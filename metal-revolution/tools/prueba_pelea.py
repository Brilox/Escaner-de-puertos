#!/usr/bin/env python3
"""Prueba de punta a punta SIN telefonos: dos clientes simulados hacen todo el recorrido contra un servidor en marcha.

    python mr_server.py --host 127.0.0.1 --port 18080 --nombre-automatico        (en una ventana)
    python ../tools/prueba_pelea.py 127.0.0.1 18080                               (en otra)

Comprueba: sala de espera en la mesa, entrada simultanea a la seleccion de personaje, confirmaciones, escenario, carga,
ping UDP, entrada al relay (KCP), reenvio de inputs con perdida de paquetes, resultado, revancha, abandono y la
clasificatoria 3v3. El KCP de este archivo esta escrito aparte del que usa el servidor, a proposito, para que la prueba
no se limite a comparar el servidor consigo mismo."""
import os, socket, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cliente_prueba import Cliente

HOST = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
PUERTO = int(sys.argv[2]) if len(sys.argv) > 2 else 18080
fallos = []


def ok(cond, texto):
    print(('   OK   ' if cond else '   FALLA ') + texto)
    if not cond: fallos.append(texto)


def de(r, tipo):
    """Primer mensaje del tipo dado en una lista de recibidos."""
    for k, t, d in r:
        if t == tipo: return d
    return None


class TelefonoUDP:
    """Lo minimo que hace el juego por UDP: ping TLV, KCP a mano y el canal rapido."""

    def __init__(self, conv=6666, perder=()):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); self.s.settimeout(0.02); self.conv = conv
        self.sn = 0; self.rcv_nxt = 0; self.sin_ack = {}; self.fuera = {}; self.mensajes = []; self.rapidos = []
        self.perder = set(perder); self.acks_recibidos = 0; self.t0 = time.monotonic()

    def ahora(self): return int((time.monotonic() - self.t0) * 1000)

    def ping(self):
        cuerpo = struct.pack('>HI', 2, 7) + struct.pack('>HI', 6, 1) + struct.pack('>HB', 5, 2) + struct.pack('>HI', 4, 8) + struct.pack('<q', 123456789)
        pk = struct.pack('>HI', 1, len(cuerpo)) + cuerpo
        self.s.sendto(pk, (HOST, PUERTO))
        try: r, _ = self.s.recvfrom(4096)
        except socket.timeout: return False
        return r == b'\x00\x02' + pk[2:]

    def _seg(self, cmd, sn, ts, datos=b''):
        return struct.pack('<IBBHIIII', self.conv, cmd, 0, 128, ts & 0xFFFFFFFF, sn, self.rcv_nxt, len(datos)) + datos

    def fiable(self, datos):
        sn = self.sn; self.sn += 1; self.sin_ack[sn] = datos
        if sn in self.perder: return                       # simula un paquete perdido: llegara por reenvio
        self.s.sendto(self._seg(81, sn, self.ahora(), datos), (HOST, PUERTO))

    def rapido(self, datos):
        self.s.sendto(b'\0\0\0\0' + datos, (HOST, PUERTO))

    def bombear(self, segundos=0.15):
        fin = time.monotonic() + segundos; ult = 0
        while time.monotonic() < fin:
            try: d, _ = self.s.recvfrom(4096)
            except socket.timeout: d = None
            if d:
                if d[:4] == b'\0\0\0\0': self.rapidos.append(d[4:])
                else:
                    i = 0; acks = b''
                    while len(d) - i >= 24:
                        conv, cmd, frg, wnd, ts, sn, una, ln = struct.unpack_from('<IBBHIIII', d, i); i += 24
                        assert conv == self.conv, 'conv distinto'
                        for k in [k for k in self.sin_ack if k < una]: del self.sin_ack[k]
                        if cmd == 82: self.sin_ack.pop(sn, None); self.acks_recibidos += 1
                        elif cmd == 81:
                            if sn >= self.rcv_nxt: self.fuera[sn] = d[i:i + ln]
                            while self.rcv_nxt in self.fuera: self.mensajes.append(self.fuera.pop(self.rcv_nxt)); self.rcv_nxt += 1
                            acks += self._seg(82, sn, ts)
                        i += ln
                    if acks: self.s.sendto(acks, (HOST, PUERTO))
            if time.monotonic() - ult > 0.06:              # reenvio de lo no confirmado
                ult = time.monotonic()
                for sn, datos in list(self.sin_ack.items()): self.s.sendto(self._seg(81, sn, self.ahora(), datos), (HOST, PUERTO))

    def entrar(self, match_id, lado, pos, reentra=False, equipo=1):
        self.fiable(struct.pack('<BiHBBBB', 0, match_id, 0, lado, pos, int(reentra), equipo))


def entrar_al_juego(nombre):
    c = Cliente(nombre, HOST, PUERTO)
    r = c.pedir('LoginRequest', {'OpenId': 'prueba-' + nombre, 'DeviceId': 'dev-' + nombre}, ver=False)
    uid = de(r, 'LoginGameSvrRsp')['PlayerInfo']['BaseInfo']['Uid']
    c.pedir('EnterHallReq', {}, ver=False)
    return c, uid


def seleccion(a, b, lados, slots=1):
    """Los dos eligen y confirman personaje como lo hace el telefono (sin mandar el campo Confirm)."""
    for c, otro, lado in ((a, b, lados[0]), (b, a, lados[1])):
        for pos in range(slots):
            c.pedir('SelectCharReq', {'CharId': 5 + pos + lado, 'Side': lado, 'Pos': pos}, ver=False)
            r = c.pedir('ConfirmSelectCharReq', {'CharId': 5 + pos + lado, 'Side': lado, 'Pos': pos}, ver=False)
            rsp = de(r, 'ConfirmSelectCharRsp'); av = de(otro.recibir(0.2), 'NotifyOtherConfirmSelectChar')
            ok(bool(rsp and rsp['Confirm'] and av and av['Confirm'] and av['Side'] == lado and av['Pos'] == pos),
               '%s confirma personaje lado %d pos %d y el rival lo ve confirmado' % (c.n, lado, pos))


def escenario_y_carga(a, b, lados):
    a.pedir('SelectStageReq', {'StageId': 3}, ver=False)
    r = a.pedir('ConfirmSelectStageReq', {}, ver=False)
    av = de(b.recibir(0.2), 'NotifyOtherConfirmSelectStage')
    ok(bool(de(r, 'ConfirmSelectStageRsp') and av and av['Confirm']), 'escenario confirmado: el rival recibe el aviso y pasa a cargar')
    a.pedir('SyncLoadingProgressReq', {'Progress': 100, 'Side': lados[0], 'Pos': 0}, ver=False)
    av = de(b.recibir(0.2), 'NotifyOtherSyncLoadingProgress')
    ok(bool(av and av['Progress'] == 100 and av['Side'] == lados[0]), 'el rival ve el progreso de carga')
    b.pedir('SyncLoadingProgressReq', {'Progress': 100, 'Side': lados[1], 'Pos': 0}, ver=False); a.recibir(0.1)


def pelea(match_id, lados, n=120, perder=(3, 4, 40)):
    """Los dos entran al relay y se mandan n inputs por el canal fiable (con paquetes perdidos) y unos pocos por el rapido."""
    ua = TelefonoUDP(perder=perder); ub = TelefonoUDP()
    ok(ua.ping() and ub.ping(), 'ping UDP previo contestado')
    ua.entrar(match_id, lados[0], 0); ua.bombear(0.2)
    ok(ua.mensajes == [], 'con un solo telefono en el relay la pelea NO empieza')
    ub.entrar(match_id, lados[1], 0); ub.bombear(0.2); ua.bombear(0.2)
    ok(ua.mensajes == [b'\x00'] and ub.mensajes == [b'\x00'], 'al entrar el segundo, los dos reciben la salida (AllPlayerEnterRoom)')
    ua.mensajes.clear(); ub.mensajes.clear()
    for f in range(n):
        ua.fiable(struct.pack('<BiH', 14, f, f & 0xFF)); ub.fiable(struct.pack('<BiH', 14, f, 0x100 | (f & 0xFF)))
        if f % 30 == 0:
            ua.fiable(struct.pack('<BiH', 15, f, 42)); ua.rapido(struct.pack('<BiH', 16, f, 7))
        if f % 10 == 9: ua.bombear(0.02); ub.bombear(0.02)
    for _ in range(6): ua.bombear(0.1); ub.bombear(0.1)
    en_b = b''.join(ub.mensajes); en_a = b''.join(ua.mensajes)
    esperado_a = b''.join(struct.pack('<BiBBH', 14, f, lados[1], 0, 0x100 | (f & 0xFF)) for f in range(n))
    inputs_b = b''.join(en_b[i:i + 9] for i in range(0, len(en_b), 9) if en_b[i] == 14)
    esperado_b = b''.join(struct.pack('<BiBBH', 14, f, lados[0], 0, f & 0xFF) for f in range(n))
    ok(en_a == esperado_a, 'A recibe los %d inputs de B, en orden y con lado/pos del emisor' % n)
    ok(inputs_b == esperado_b, 'B recibe los %d inputs de A en orden pese a %d paquetes perdidos' % (n, len(perder)))
    ok(en_b.count(struct.pack('<BiBBH', 15, 0, lados[0], 0, 42)) == 1, 'SyncPing reenviado con lado/pos')
    ok(any(struct.pack('<BiBBH', 16, 0, lados[0], 0, 7) in r for r in ub.rapidos), 'canal rapido (sin KCP) reenviado')
    ok(not ua.sin_ack and not ub.sin_ack, 'el servidor confirmo (ACK) todo lo enviado')
    ua.fiable(b'\x01'); ub.fiable(b'\x01'); ua.bombear(0.1); ub.bombear(0.1)
    return ua, ub


def resultado(a, b, ganador=0):
    a.pedir('UploadBattleResult', {'WinnerSide': ganador, 'LeftWinRound': 2, 'RightWinRound': 1}, ver=False)
    ra = de(a.recibir(0.2) + a.avisos, 'BattleResult'); rb = de(b.recibir(0.2), 'BattleResult')
    b.pedir('UploadBattleResult', {'WinnerSide': ganador, 'LeftWinRound': 2, 'RightWinRound': 1}, ver=False)
    ok(bool(ra and rb and rb['LastBattleLog']['WinnerSide'] == ganador and rb['LastBattleLog']['LeftWinRound'] == 2),
       'los dos reciben el resultado (BattleResult) con el ganador correcto')
    a.avisos.clear(); b.avisos.clear()
    return rb


def prueba_mesa():
    print('\n=== MESA: sala de espera, seleccion a la vez, pelea, revancha, salida ===')
    a, uid_a = entrar_al_juego('Ana'); b, uid_b = entrar_al_juego('Beto')
    r = a.pedir('EnterHallRoomReq', {'RoomId': 1, 'Pos': 0, 'Password': 0}, ver=False); v = de(r, 'GameHallMatchCreated')
    ok(bool(v and v['RoomDetail']['LeftPlayerId'] == 0 and v['RoomDetail']['RightPlayerId'] == 0 and v['MatchState']['Phase'] == 0),
       'el primer jugador queda en la SALA DE ESPERA (no pasa solo a elegir personaje)')
    r = b.pedir('QueryRoomListInHallReq', {'FromRoomId': 1, 'ToRoomId': 8}, ver=False)
    ok(de(r, 'QueryRoomListInHallRsp')['RoomInfos'][0]['LeftPlayerId'] == uid_a, 'el segundo jugador ve la mesa con el primero sentado')
    b.avisos.clear(); a.recibir(0.1); a.avisos.clear()
    r = b.pedir('EnterHallRoomReq', {'RoomId': 1, 'Pos': 1, 'Password': 0}, ver=False); vb = de(r, 'GameHallMatchCreated')
    va = de(a.recibir(0.3), 'NotifyGameHallMatchCreated')
    ok(bool(vb and va and all(x['RoomDetail']['LeftPlayerId'] == uid_a and x['RoomDetail']['RightPlayerId'] == uid_b and
                              x['MatchState']['Phase'] == 1 for x in (va, vb))), 'al sentarse el segundo, LOS DOS pasan a la vez a elegir personaje')
    rel = vb['MatchState'].get('RelayServerInfo') or {}
    ok(rel.get('Port') == PUERTO and rel.get('RelayId') == vb['MatchState']['MatchId'] and rel.get('UseRudp') is True,
       'el estado de la pelea ya trae los datos del relay (puerto %s)' % rel.get('Port'))
    mid = vb['MatchState']['MatchId']
    seleccion(a, b, (0, 1)); escenario_y_carga(a, b, (0, 1)); pelea(mid, (0, 1)); resultado(a, b, 0)
    r = a.pedir('RefightReq', {}, ver=False); ok(de(r, 'RefightRsp')['FightStarted'] is False, 'revancha: con uno solo no arranca')
    av = de(b.recibir(0.2), 'NotifyOtherRequestRefight'); ok(bool(av and av['Side'] == 0), 'el rival ve que le piden revancha')
    r = b.pedir('RefightReq', {}, ver=False); ok(de(r, 'RefightRsp')['FightStarted'] is True, 'revancha: cuando la piden los dos, arranca')
    a.recibir(0.2); a.avisos.clear(); b.avisos.clear()
    pelea(mid, (0, 1), n=30, perder=()); resultado(a, b, 1)
    a.pedir('BackToCharSelectReq', {}, ver=False)
    ok(de(b.recibir(0.2), 'NotifyOtherBackToCharSelect') is not None, 'volver a elegir personaje: el rival recibe el aviso')
    seleccion(a, b, (0, 1)); b.avisos.clear(); a.avisos.clear()
    b.pedir('ExitHallRoomReq', {}, ver=False); va = de(a.recibir(0.3), 'NotifyGameHallMatchCreated')
    ok(bool(va and va['RoomDetail']['LeftPlayerId'] == 0 and va['MatchState']['Phase'] == 0), 'si el rival se va de la mesa, el que queda vuelve a la sala de espera')
    r = b.pedir('EnterHallRoomReq', {'RoomId': 1, 'Pos': 0, 'Password': 0}, ver=False); vb = de(r, 'GameHallMatchCreated')
    ok(bool(vb and vb['RoomDetail']['LeftPlayerId'] == uid_a and vb['RoomDetail']['RightPlayerId'] == uid_b),
       'vuelve a entrar pidiendo un asiento ya ocupado: se le da el otro y arranca otra pelea')
    a.recibir(0.2); mid2 = vb['MatchState']['MatchId']
    seleccion(a, b, (0, 1)); escenario_y_carga(a, b, (0, 1)); a.avisos.clear(); b.avisos.clear()
    ua = TelefonoUDP(); ub = TelefonoUDP(); ua.entrar(mid2, 0, 0); ub.entrar(mid2, 1, 0); ua.bombear(0.2); ub.bombear(0.2)
    b.s.close(); time.sleep(0.4); r = a.recibir(0.4)
    ok(de(r, 'NotifyPlayerLeftInMatch') is not None and (de(r, 'BattleResult') or {}).get('LastBattleLog', {}).get('WinnerSide') == 0,
       'si al rival se le cae la conexion en plena pelea, el otro gana por abandono')
    a.s.close()


def prueba_clasificatoria():
    print('\n=== CLASIFICATORIA 3v3 (cada jugador lleva 3 personajes) ===')
    a, uid_a = entrar_al_juego('Carla'); b, uid_b = entrar_al_juego('Dani')
    r = a.pedir('StartSearchMatchReq', {'MatchMakingType': 3}, ver=False)
    ok((de(r, 'StartSearchMatchRsp') or {}).get('LastSearchTime', 0) > 0, 'la busqueda arranca (LastSearchTime)')
    b.pedir('StartSearchMatchReq', {'MatchMakingType': 3}, ver=False)
    ea = de(a.recibir(0.3), 'NotifySearchMatchRivalFound'); eb = de(b.recibir(0.3) + b.avisos, 'NotifySearchMatchRivalFound')
    ok(bool(ea and eb and len(ea['MatchState']['LeftMembers']) == 3 and ea['MatchState']['RelayServerInfo']['Port'] == PUERTO),
       'rival encontrado: 3 huecos por lado y datos del relay')
    mid = ea['MatchState']['MatchId']; a.avisos.clear(); b.avisos.clear()
    seleccion(a, b, (0, 1), slots=3); escenario_y_carga(a, b, (0, 1)); pelea(mid, (0, 1), n=40, perder=(2,))
    rb = resultado(a, b, 0)
    ok(rb['LeftPlayerChanges'][0]['WinPoint'] > rb['RightPlayerChanges'][0]['WinPoint'], 'el ganador sube puntos y el perdedor baja')
    a.pedir('ExitMatchReq', {}, ver=False); b.pedir('ExitMatchReq', {}, ver=False)
    r = a.pedir('StartSearchMatchReq', {'MatchMakingType': 0}, ver=False)
    ok(de(r, 'StartSearchMatchRsp') is not None, 'despues de la pelea se puede volver a buscar rival')
    a.s.close(); b.s.close()


def prueba_2v2():
    print('\n=== CLASIFICATORIA 2v2 (cuatro telefonos) ===')
    cs = [entrar_al_juego(n)[0] for n in ('Eva', 'Fran', 'Gabi', 'Hugo')]
    for c in cs: c.pedir('StartSearchMatchReq', {'MatchMakingType': 1}, ver=False)
    est = [de(c.recibir(0.3) + c.avisos, 'NotifySearchMatchRivalFound') for c in cs]
    ok(all(e and len(e['MatchState']['LeftMembers']) == 2 and len(e['MatchState']['RightMembers']) == 2 for e in est), 'los cuatro reciben la pelea 2 contra 2')
    mid = est[0]['MatchState']['MatchId']; us = [TelefonoUDP() for _ in cs]; sitios = [(0, 0), (0, 1), (1, 0), (1, 1)]
    for u, (lado, pos) in zip(us[:3], sitios): u.entrar(mid, lado, pos, equipo=2)
    for u in us[:3]: u.bombear(0.1)
    ok(all(u.mensajes == [] for u in us[:3]), 'con tres de cuatro en el relay la pelea no empieza')
    us[3].entrar(mid, 1, 1, equipo=2)
    for _ in range(2):
        for u in us: u.bombear(0.1)
    ok(all(u.mensajes == [b'\x00'] for u in us), 'con los cuatro dentro, todos reciben la salida')
    for u in us: u.mensajes.clear()
    us[0].fiable(struct.pack('<BiH', 14, 1, 9))
    for _ in range(2):
        for u in us: u.bombear(0.1)
    ok(us[0].mensajes == [] and all(u.mensajes == [struct.pack('<BiBBH', 14, 1, 0, 0, 9)] for u in us[1:]), 'un input llega a los otros tres y no vuelve al emisor')
    for c in cs: c.s.close()


if __name__ == '__main__':
    prueba_mesa(); prueba_clasificatoria(); prueba_2v2()
    print('\n%s' % ('TODO BIEN' if not fallos else 'FALLARON %d COMPROBACIONES:\n  - %s' % (len(fallos), '\n  - '.join(fallos))))
    sys.exit(1 if fallos else 0)
