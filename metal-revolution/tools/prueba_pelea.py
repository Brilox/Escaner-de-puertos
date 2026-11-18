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
        self.s.sendto(pk, (HOST, PUERTO - 1))                  # el juego hace el ping al puerto del relay MENOS UNO
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


def pelea(match_id, lados, n=120, perder=(3, 4, 40), puestos=1):
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
    if puestos > 1:
        # 3v3 en solitario: cada input llega marcado con los 3 puestos del emisor, y al emisor le vuelve para los puestos 1 y 2
        def por_puesto(buf):
            r = {}
            for i in range(0, len(buf) - 8, 9):
                if buf[i] == 14:
                    fr, lado, pos, bot = struct.unpack_from('<iBBH', buf, i + 1); r.setdefault((lado, pos), []).append((fr, bot))
            return r
        rb, ra = por_puesto(en_b), por_puesto(en_a)
        de_a = [(f, f & 0xFF) for f in range(n)]; de_b = [(f, 0x100 | (f & 0xFF)) for f in range(n)]
        ok(all(rb.get((lados[0], q)) == de_a for q in range(puestos)), '3v3: el rival recibe cada input marcado para los %d puestos del emisor' % puestos)
        ok(all(ra.get((lados[1], q)) == de_b for q in range(puestos)), '3v3: lo mismo en el otro sentido')
        ok((lados[0], 0) not in ra and all(ra.get((lados[0], q)) == de_a for q in range(1, puestos)),
           '3v3: al emisor le vuelven sus inputs para los puestos 1 y 2 (sus otros personajes), no para el 0')
        ua.fiable(b'\x01'); ub.fiable(b'\x01'); ua.bombear(0.1); ub.bombear(0.1)
        return ua, ub
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


def resultado(a, b, ganador=0, pantalla=(True, True)):
    """Como el telefono real: cada uno sube su resultado (con la lista de rondas, que viaja como lista de numeros) y, al
    abrirse su pantalla de resultados, pide los puntos de los dos (QueryPlayerRankReq). pantalla=False simula un telefono
    cuya pantalla de resultados nunca se abre (lo que le pasaba al que perdia en la sala)."""
    datos = {'WinnerSide': ganador, 'LeftWinRound': 2, 'RightWinRound': 1, 'LeftRoundResults': [16, 48, 16], 'RightRoundResults': [48, 16, 48],
             'SnapshotHash': 'abc', 'Interrupted': False}
    a.pedir('UploadBattleResult', datos, ver=False)
    ra = de(a.recibir(0.2) + a.avisos, 'BattleResult'); antes = de(b.recibir(0.2), 'BattleResult')
    ok(antes is None, 'al que todavia no sube su resultado NO se le manda antes de tiempo (si no, se queda esperando)')
    r = b.pedir('UploadBattleResult', datos, ver=False); rb = de(r + b.recibir(0.2), 'BattleResult')
    ok(bool(ra and rb and rb['LastBattleLog']['WinnerSide'] == ganador and rb['LastBattleLog']['LeftWinRound'] == 2),
       'los dos reciben el resultado (BattleResult) con el ganador correcto, cada uno tras subir el suyo')
    bl = (rb or {}).get('LastBattleLog', {})
    ok(bl.get('TotalRounds') == 3 and bl.get('LeftRoundResults') == [16, 48, 16] and bl.get('RightRoundResults') == [48, 16, 48],
       'el resultado trae las rondas (sin ellas la pantalla de resultados del juego falla)')
    for c, abre in zip((a, b), pantalla):
        if abre: c.pedir('QueryPlayerRankReq', {'Uid': 0, 'RankType': 32}, ver=False)
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
    seleccion(a, b, (0, 1)); escenario_y_carga(a, b, (0, 1)); a.avisos.clear(); b.avisos.clear()
    pelea(mid, (0, 1), n=10, perder=()); resultado(a, b, 0, pantalla=(True, False))
    r = a.pedir('RefightReq', {}, ver=False)
    vb = de(b.recibir(0.3), 'NotifyGameHallMatchCreated')
    ok(de(r, 'RefightRsp')['FightStarted'] is False and de(r + a.recibir(0.2), 'NotifyOtherBackToCharSelect') is not None and
       bool(vb and vb['MatchState']['Phase'] == 1),
       'si la pantalla de resultados del que pierde no se abre, la revancha manda a los dos a elegir personaje (no se queda pegado)')
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
    print('\n=== CLASIFICATORIA 3v3 (cada jugador elige 3 personajes y los ordena) ===')
    a, uid_a = entrar_al_juego('Carla'); b, uid_b = entrar_al_juego('Dani')
    r = a.pedir('StartSearchMatchReq', {'MatchMakingType': 3}, ver=False)
    ok((de(r, 'StartSearchMatchRsp') or {}).get('LastSearchTime', 0) > 0, 'la busqueda arranca (LastSearchTime)')
    b.pedir('StartSearchMatchReq', {'MatchMakingType': 3}, ver=False)
    ea = de(a.recibir(0.3), 'NotifySearchMatchRivalFound'); eb = de(b.recibir(0.3) + b.avisos, 'NotifySearchMatchRivalFound')
    ok(bool(ea and eb and len(ea['MatchState']['LeftMembers']) == 3 and ea['MatchState']['RelayServerInfo']['Port'] == PUERTO),
       'rival encontrado: 3 huecos por lado y datos del relay')
    mid = ea['MatchState']['MatchId']; a.avisos.clear(); b.avisos.clear()
    seleccion(a, b, (0, 1), slots=3)
    # fase de ordenar: cada uno llena el puesto 0 y luego el 1; el 2 queda decidido solo
    r = a.pedir('ChangeCharOrderReq', {'SrcPos': 2, 'TargetPos': 0}, ver=False)
    ok((de(r, 'ChangeCharOrderRsp') or {}).get('OrderingIndex') == 1, 'ordenar: tras el primer puesto el servidor contesta el puesto siguiente (1)')
    av = de(b.recibir(0.2), 'NotifyOtherRequestChangeCharOrder')
    ok(bool(av and av['SourceUid'] == uid_a and av['TargetUid'] == 0 and av['SrcPos'] == 2 and av['TargetPos'] == 0),
       'el rival recibe el cambio de orden con TargetUid=0 (si no, su telefono lo ignora y se desincroniza)')
    r = a.pedir('ChangeCharOrderReq', {'SrcPos': 1, 'TargetPos': 0}, ver=False)
    ok((de(r, 'ChangeCharOrderRsp') or {}).get('OrderingIndex') == 1, 'un pedido para un puesto ya ocupado no avanza el orden')
    r = a.pedir('ChangeCharOrderReq', {'SrcPos': 2, 'TargetPos': 1}, ver=False); b.recibir(0.2)
    ok((de(r, 'ChangeCharOrderRsp') or {}).get('OrderingIndex') == 3, 'con el penultimo puesto el ultimo queda solo: se contesta 3 (orden terminado)')
    ok(de(a.recibir(0.2), 'NotifyFinishReorderChar') is None, 'con un solo lado ordenado todavia no se pasa al escenario')
    b.pedir('ChangeCharOrderReq', {'SrcPos': 0, 'TargetPos': 0}, ver=False)
    r = b.pedir('ChangeCharOrderReq', {'SrcPos': 1, 'TargetPos': 1}, ver=False)
    fa = de(a.recibir(0.3) + a.avisos, 'NotifyFinishReorderChar'); fb = de(r + b.avisos, 'NotifyFinishReorderChar')
    ok(fa is not None and fb is not None, 'cuando los dos ordenaron, ambos reciben NotifyFinishReorderChar (a elegir escenario)')
    a.avisos.clear(); b.avisos.clear()
    escenario_y_carga(a, b, (0, 1)); pelea(mid, (0, 1), n=40, perder=(2,), puestos=3)
    rb = resultado(a, b, 0)
    ok(rb['LeftPlayerChanges'][0]['WinPoint'] > rb['RightPlayerChanges'][0]['WinPoint'], 'el ganador sube puntos y el perdedor baja')
    a.pedir('ExitMatchReq', {}, ver=False); b.pedir('ExitMatchReq', {}, ver=False)
    r = a.pedir('QueryBattleDataReq', {'Uid': uid_a, 'DetailLevel': 1}, ver=False)
    ok((de(r, 'PlayerBattleData') or {}).get('DetailLevel') == 1, 'las estadisticas vuelven con el nivel de detalle pedido (sin bucle)')
    print('   (esperando %d s: resultado de alguien que nunca lo sube)' % 11)
    # partida rapida: cada uno elige su personaje ANTES de buscar y el juego va directo a la carga
    a.pedir('ChangeFavCharReq', {'CharId': 8, 'MatchMakingType': 2}, ver=False); b.pedir('ChangeFavCharReq', {'CharId': 16, 'MatchMakingType': 2}, ver=False)
    a.pedir('StartSearchMatchReq', {'MatchMakingType': 2}, ver=False); b.pedir('StartSearchMatchReq', {'MatchMakingType': 2}, ver=False)
    ea = de(a.recibir(0.3) + a.avisos, 'NotifySearchMatchRivalFound')
    ms = (ea or {}).get('MatchState', {})
    ok(bool(ea and len(ms['LeftMembers']) == 1), 'la busqueda rapida 1v1 (normal) tambien encuentra rival')
    ok([m['CharId'] for m in ms.get('LeftMembers', []) + ms.get('RightMembers', [])] == [8, 16] and ms.get('StageConfirmed') and ms.get('StageId') in (1, 2, 3, 4),
       'partida rapida: el servidor ya manda el personaje favorito de cada uno y el escenario (sin eso la carga se queda pegada)')
    a.avisos.clear(); b.avisos.clear(); b.recibir(0.2); b.avisos.clear()
    a.pedir('SyncLoadingProgressReq', {'Progress': 100, 'Side': 0, 'Pos': 0}, ver=False); b.pedir('SyncLoadingProgressReq', {'Progress': 100, 'Side': 1, 'Pos': 0}, ver=False)
    pelea(ms['MatchId'], (0, 1), n=10, perder=())
    a.pedir('UploadBattleResult', {'WinnerSide': 1, 'LeftWinRound': 0, 'RightWinRound': 2}, ver=False); b.avisos.clear()
    time.sleep(11); rb = de(b.recibir(0.5) + b.avisos, 'BattleResult')
    ok(bool(rb and rb['LastBattleLog']['WinnerSide'] == 1), 'si un telefono nunca sube su resultado, igual le llega a los 10 s')
    a.pedir('ExitMatchReq', {}, ver=False); b.avisos.clear()
    r = b.pedir('SyncLoadingProgressReq', {'Progress': 100, 'Side': 1, 'Pos': 0}, ver=False)
    ok(de(r + b.recibir(0.2), 'NotifyMatchCancelled') is not None, 'si un telefono vuelve a cargar una pelea que ya termino, se le cancela (no queda en bucle)')
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


def prueba_config():
    """Los modos de batalla se abren mandando al telefono una OpenSystemConfig sin limites de fecha ni de horario."""
    import json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
    from config_juego import como_lo_lee_el_telefono
    print('\n=== CONFIGURACION DEL JUEGO (modos de batalla abiertos) ===')
    c = Cliente('Ines', HOST, PUERTO)
    r = c.pedir('LoginRequest', {'OpenId': 'prueba-Ines', 'DeviceId': 'dev-Ines'}, ver=False)
    ok(de(r, 'LoginGameSvrRsp')['PlayerInfo']['BaseInfo']['Level'] == 1, 'el nivel informado es el real de la cuenta (ya no se fuerza a 10)')
    ok(len(de(r, 'LoginGameSvrRsp')['PlayerInfo']['Heroes']) >= 5, 'tiene al menos 5 personajes (otro requisito de la 1v1)')
    av = de(r, 'NotifySvrConfigReload')
    ok(bool(av and av['Reload'] and av['HashAll']), 'al entrar llega el aviso de configuracion nueva')
    pares = de(c.pedir('QueryAllConfigHashReq', {}, ver=False), 'QueryAllConfigHashRsp')['HashPairs']
    ok(any(p['FileName'] == 'OpenSystemConfig.json' for p in pares), 'la lista de archivos incluye OpenSystemConfig.json')
    cont = de(c.pedir('DownloadConfigReq', {'Key': 'OpenSystemConfig.json'}, ver=False), 'DownloadConfigRsp')['Content']
    cfg = {x['name']: x for x in json.loads(como_lo_lee_el_telefono(cont))['configList']}
    abiertos = all(k in cfg and not ({'beginTime', 'endTime', 'dayBeginTime', 'dayEndTime'} & set(cfg[k]))
                   for k in ('TeamBattle', 'RankMatch', 'RankSolo3v3', 'QuickSolo3v3'))
    ok(abiertos, '2v2, 1v1 clasificatoria y 3v3 quedan sin fechas ni horario (tal como lo lee el telefono)')
    c.pedir('FinishTutorialReq', {'Id': 'tuto-prueba', 'Finish': True}, ver=False)
    td = de(c.pedir('QueryTrainingDataReq', {}, ver=False), 'PlayerTrainingData') or {}
    hechos = {t['Id'] for t in td.get('TutorialFinishStates', []) if t.get('Finished')}
    ok({'tuto-prueba', 'e3482f25-a92e-4215-b1b4-946e22c12c39'} <= hechos, 'los tutoriales terminados se recuerdan (y el de la primera derrota ya viene hecho)')
    c.s.close()


if __name__ == '__main__':
    prueba_mesa(); prueba_clasificatoria(); prueba_2v2(); prueba_config()
    print('\n%s' % ('TODO BIEN' if not fallos else 'FALLARON %d COMPROBACIONES:\n  - %s' % (len(fallos), '\n  - '.join(fallos))))
    sys.exit(1 if fallos else 0)
