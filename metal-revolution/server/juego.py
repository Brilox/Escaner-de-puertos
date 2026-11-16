#!/usr/bin/env python3
"""Logica de juego de la fase 2: cuentas, hall, mesas (salas), partidas y estadisticas.

Todo se expresa como diccionarios que el codec FlatBuffers (fb_codec) convierte a bytes.
Cada handler recibe (jugador, datos) y devuelve (nombre_de_tabla_respuesta, dict) o None para EmptyRsp.
Las notificaciones a otros jugadores se encolan con jugador.notificar(tipo, dict)."""
import json, os, sqlite3, time, logging, random

log = logging.getLogger('mr.juego')
HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_JUEGO = '1.0.23'
NUM_MESAS = 8
LEFT, RIGHT, OBSERVER, AUTO = 0, 1, 2, 3           # RoomPosType
GAMEHALL = 5                                        # MatchType
WAITING_ALL_READY, SELECTING_CHAR, ORDERING_CHAR, SELECTING_STAGE, LOADING_FIGHT, FIGHTING, WAITING_RESULT, END = range(8)

# ----------------------------------------------------------------- cuentas
class Cuentas:
    def __init__(self, ruta):
        self.db = sqlite3.connect(ruta); self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS jugadores (
            uid INTEGER PRIMARY KEY, openid TEXT UNIQUE, nombre TEXT NOT NULL DEFAULT '', creado INTEGER, ultimo_login INTEGER,
            victorias INTEGER DEFAULT 0, derrotas INTEGER DEFAULT 0, empates INTEGER DEFAULT 0, partidas INTEGER DEFAULT 0,
            nivel INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, dispositivo TEXT DEFAULT '')''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha INTEGER, uid_izq INTEGER, uid_der INTEGER, ganador INTEGER,
            rondas_izq INTEGER, rondas_der INTEGER, char_izq INTEGER, char_der INTEGER, escenario INTEGER)''')
        self.db.commit()
    def login(self, openid, dispositivo):
        r = self.db.execute('SELECT * FROM jugadores WHERE openid=?', (openid,)).fetchone()
        now = int(time.time())
        if r is None:
            cur = self.db.execute('INSERT INTO jugadores(openid,nombre,creado,ultimo_login,dispositivo) VALUES(?,?,?,?,?)', (openid, '', now, now, dispositivo))
            uid = cur.lastrowid if cur.lastrowid >= 1000001 else None
            if uid is None:
                self.db.execute('UPDATE jugadores SET uid=? WHERE rowid=?', (1000000 + cur.lastrowid, cur.lastrowid)); uid = 1000000 + cur.lastrowid
            self.db.commit(); log.info('cuenta nueva uid=%d openid=%s', uid, openid)
        else:
            uid = r['uid']; self.db.execute('UPDATE jugadores SET ultimo_login=? WHERE uid=?', (now, uid)); self.db.commit()
        return dict(self.db.execute('SELECT * FROM jugadores WHERE uid=?', (uid,)).fetchone())
    def get(self, uid):
        r = self.db.execute('SELECT * FROM jugadores WHERE uid=?', (uid,)).fetchone(); return dict(r) if r else None
    def poner_nombre(self, uid, nombre):
        nombre = nombre.strip()[:16]
        if not nombre: return False
        if self.db.execute('SELECT 1 FROM jugadores WHERE nombre=? AND uid<>?', (nombre, uid)).fetchone(): return False
        self.db.execute('UPDATE jugadores SET nombre=? WHERE uid=?', (nombre, uid)); self.db.commit(); return True
    def registrar_partida(self, uid_izq, uid_der, ganador, r_izq, r_der, c_izq, c_der, escenario):
        self.db.execute('INSERT INTO partidas(fecha,uid_izq,uid_der,ganador,rondas_izq,rondas_der,char_izq,char_der,escenario) VALUES(?,?,?,?,?,?,?,?,?)',
                        (int(time.time()), uid_izq, uid_der, ganador, r_izq, r_der, c_izq, c_der, escenario))
        for uid, side in ((uid_izq, LEFT), (uid_der, RIGHT)):
            col = 'empates' if ganador < 0 else ('victorias' if ganador == side else 'derrotas')
            self.db.execute(f'UPDATE jugadores SET {col}={col}+1, partidas=partidas+1, exp=exp+? WHERE uid=?', (30 if col == 'victorias' else 10, uid))
        self.db.commit()

# ----------------------------------------------------------------- estado en memoria
class Jugador:
    def __init__(self, sesion, cuenta):
        self.sesion = sesion; self.cuenta = cuenta; self.uid = cuenta['uid']
        self.hall = None; self.mesa = None; self.pos = OBSERVER; self.pvp_prefs = None
    @property
    def nombre(self): return self.cuenta['nombre']
    def notificar(self, tipo, datos): self.sesion.enviar_notificacion(tipo, datos)

class Mesa:
    def __init__(self, id_, titulo):
        self.id = id_; self.titulo = titulo; self.izq = None; self.der = None; self.observadores = []; self.partida = None
    def jugadores(self): return [p for p in (self.izq, self.der) if p] + self.observadores
    def detalle(self):
        return dict(RoomId=self.id, Title=self.titulo, DisplayTitle=self.titulo, HasPassword=False,
                    LeftPlayerId=self.izq.uid if self.izq else 0, RightPlayerId=self.der.uid if self.der else 0,
                    Hot=len(self.jugadores()), AllowObserve=True, IsArena=False, LoseCountRule=0, LeftLoseCount=0, RightLoseCount=0,
                    ObserverCount=len(self.observadores), HideCharSelection=False, HostSide=LEFT if self.izq else RIGHT)
    def quitar(self, p):
        if self.izq is p: self.izq = None
        if self.der is p: self.der = None
        if p in self.observadores: self.observadores.remove(p)

class Partida:
    def __init__(self, id_, mesa):
        self.id = id_; self.mesa = mesa; self.fase = SELECTING_CHAR; self.seed = random.randint(1, 2**31 - 1)
        self.miembros = {LEFT: self.miembro(mesa.izq, LEFT), RIGHT: self.miembro(mesa.der, RIGHT)}
        self.escenario = 1; self.escenario_confirmado = False; self.inicio = int(time.time()); self.relay = None
    @staticmethod
    def miembro(p, side):
        return dict(Uid=p.uid, CharId=0, RandomChar=False, CostumeId=0, AltColorIndex=0, CharConfirmed=False, InBattleStatus=0, Ready=False,
                    LoadingProgress=0, PendingSwitchOrderTeammateId=0, PvpPrefs=p.pvp_prefs, ShouldPunishForEarlyExit=False, BattleEndStatus=0,
                    Side=side, Pos=0, NetStatus=0, FakeWinPoint=0, AiControlledByUid=0, BePraisedCount=0)
    def estado(self):
        now = int(time.time())
        return dict(MatchType=GAMEHALL, MatchId=self.id, SubMatchId=0, Phase=self.fase, Version=VERSION_JUEGO,
                    LeftMembers=[self.miembros[LEFT]], RightMembers=[self.miembros[RIGHT]], StartTime=self.inicio, EndTime=0,
                    RandomSeed=self.seed, RefightRemainCount=3, LeftWonCount=0, RightWonCount=0, StageId=self.escenario, RandomStage=False,
                    StageConfirmed=self.escenario_confirmado, StartSelectCharTime=now, StartOrderCharTime=now, StartSelectStageTime=now,
                    StartWaitingReadyTime=now, SelectCharMaxTime=60, SelectStageMaxTime=30, WaitingReadyMaxTime=60, OrderCharMaxTime=30,
                    RelayServerInfo=self.relay, LeftOrderingIndex=0, RightOrderingIndex=0, AllowSameCharInTeam=True, AllowSameCharInMatch=True,
                    SkipReorderChar=True, SkipSelectStage=False)
    def jugadores(self): return [p for p in (self.mesa.izq, self.mesa.der) if p]

# ----------------------------------------------------------------- juego
class Juego:
    def __init__(self, host, puerto, puerto_relay, plantilla_login, nombre_automatico=False):
        self.host = host; self.puerto = puerto; self.puerto_relay = puerto_relay; self.plantilla = plantilla_login
        self.nombre_automatico = nombre_automatico
        self.cuentas = Cuentas(os.path.join(HERE, 'cuentas.db'))
        self.conectados = {}     # uid -> Jugador
        self.mesas = {i: Mesa(i, f'Mesa {i}') for i in range(1, NUM_MESAS + 1)}
        self.partidas = {}; self._next_match = 1
        self.handlers = {n[3:]: getattr(self, n) for n in dir(self) if n.startswith('on_')}

    # ---- utilidades
    def info_detallada(self, cuenta):
        import copy
        pi = copy.deepcopy(self.plantilla['PlayerInfo'])
        b = pi['BaseInfo']; b.update(Uid=cuenta['uid'], Name=cuenta['nombre'], Level=cuenta['nivel'], Exp=cuenta['exp'],
                                   RegisterTime=cuenta['creado'], OnlineState=1 if cuenta['uid'] in self.conectados else 0, GameVersion=VERSION_JUEGO)
        j = self.conectados.get(cuenta['uid'])
        if j: b['GameHallId'] = 1 if j.hall else 0; b['HallRoomId'] = j.mesa.id if j.mesa else 0
        pi['BattleData']['Uid'] = cuenta['uid']
        return pi
    def difundir_hall(self, tipo, datos, excepto=None):
        for p in self.conectados.values():
            if p.hall and p is not excepto: p.notificar(tipo, datos)
    def difundir_mesa(self, mesa, tipo, datos, excepto=None):
        for p in mesa.jugadores():
            if p is not excepto: p.notificar(tipo, datos)
    def estado_hall(self, j):
        mesa = j.mesa
        return dict(HallId=1, RoomId=mesa.id if mesa else 0, HallInfo=self.detalle_hall(), RoomDetail=mesa.detalle() if mesa else None,
                    MatchState=mesa.partida.estado() if mesa and mesa.partida else None)
    def detalle_hall(self):
        ocupadas = sum(1 for m in self.mesas.values() if m.jugadores())
        return dict(RoomNum=len(self.mesas), IsArena=False, Full=False, PlayerCount=sum(1 for p in self.conectados.values() if p.hall),
                    MinRoomId=1, MaxRoomId=len(self.mesas))

    # ---- conexion
    def desconectar(self, j):
        if j is None: return
        if j.mesa: self.salir_mesa(j, servidor=True)
        if j.hall: self.salir_hall(j)
        self.conectados.pop(j.uid, None)
    def salir_hall(self, j):
        j.hall = None; self.difundir_hall('NotifyPlayerExitHall', dict(Uid=j.uid), excepto=j)
    def salir_mesa(self, j, servidor=False):
        mesa = j.mesa
        if not mesa: return
        mesa.quitar(j); j.mesa = None; j.pos = OBSERVER
        self.difundir_mesa(mesa, 'NotifyPlayerExitHallRoom', dict(PlayerId=j.uid, RoomId=mesa.id, ServerExit=servidor))
        if mesa.partida:
            for p in mesa.partida.jugadores(): p.notificar('NotifyPlayerLeftInMatch', dict(Side=LEFT if mesa.izq is None else RIGHT, Pos=0))
            self.partidas.pop(mesa.partida.id, None); mesa.partida = None
        self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle())

    # ---- handlers: cuenta
    def on_LoginRequest(self, sesion, d):
        openid = d.get('OpenId') or d.get('DeviceId') or d.get('YzDeviceId') or 'anon-%s' % sesion.peer[0]
        cuenta = self.cuentas.login(openid, d.get('Model', ''))
        if not cuenta['nombre'] and self.nombre_automatico:
            self.cuentas.poner_nombre(cuenta['uid'], 'Jugador%d' % (cuenta['uid'] % 100000)); cuenta = self.cuentas.get(cuenta['uid'])
        j = Jugador(sesion, cuenta)
        viejo = self.conectados.get(j.uid)
        if viejo and viejo.sesion is not sesion:
            viejo.notificar('NotifyLoginByOther', dict()); self.desconectar(viejo)
        self.conectados[j.uid] = j; sesion.jugador = j
        log.info('login uid=%d nombre=%r openid=%s', j.uid, j.nombre, openid)
        rsp = dict(self.plantilla); rsp = dict(rsp, PlayerInfo=self.info_detallada(cuenta), UtcTimeOffset=0, GameServerId=1, PayZoneId=0)
        return 'LoginGameSvrRsp', rsp
    def on_CreateRoleReq(self, sesion, d):
        j = sesion.jugador
        if not j: return 'Error', dict(ErrCode=1, ErrMsg='sin login', ErrMsgEn='not logged in')
        if not self.cuentas.poner_nombre(j.uid, d.get('Name', '')):
            return 'Error', dict(ErrCode=2, ErrMsg='Nombre no disponible', ErrMsgEn='Name not available')
        j.cuenta = self.cuentas.get(j.uid); log.info('uid=%d ahora se llama %r', j.uid, j.nombre)
        return 'LoginGameSvrRsp', dict(self.plantilla, PlayerInfo=self.info_detallada(j.cuenta), UtcTimeOffset=0, GameServerId=1, PayZoneId=0)
    def on_QueryRoleIdByNameReq(self, sesion, d):
        r = self.cuentas.db.execute('SELECT uid FROM jugadores WHERE nombre=?', (d.get('Name', ''),)).fetchone()
        return 'QueryRoleIdByNameRsp', dict(Name=d.get('Name', ''), SrcUid=sesion.jugador.uid if sesion.jugador else 0, ResultUids=[r['uid']] if r else [])
    def on_QueryServerTimeReq(self, sesion, d): return 'QueryServerTimeRsp', dict(ServerTime=int(time.time()))
    def on_PlayerClientPing(self, sesion, d): return 'PlayerClientPong', dict(Timestamp=int(time.time() * 1000))
    def on_QueryPlayerInfoReq(self, sesion, d):
        c = self.cuentas.get(d.get('Uid', 0)); return 'QueryPlayerInfoRsp', dict(Result=self.info_detallada(c) if c else None)
    def on_BatchQueryPlayerInfoReq(self, sesion, d):
        res = [self.info_detallada(c) for c in (self.cuentas.get(u) for u in d.get('Uids', [])) if c]
        return 'BatchQueryPlayerInfoRsp', dict(Result=res)
    def on_LogoutGameSvrReq(self, sesion, d): self.desconectar(sesion.jugador); sesion.jugador = None; return None

    # ---- handlers: hall
    def on_PlayerGetHallListReq(self, sesion, d):
        return 'PlayerGetHallListRsp', dict(HallList=[dict(RankMin=0, RankMax=99999, HallId=1, ServerId=1, Ip=self.host, Port=self.puerto,
                                                           Name='Sala Principal', Zone='', IsArena=False, StartTime=0, EndTime=0)])
    def on_EnterHallReq(self, sesion, d):
        j = sesion.jugador; j.hall = 1
        self.difundir_hall('NotifyPlayerEnterHall', dict(Uid=j.uid, Index=len(self.conectados)), excepto=j)
        return 'EnterHallRsp', self.detalle_hall()
    def on_ExitHallReq(self, sesion, d):
        j = sesion.jugador
        if j.mesa: self.salir_mesa(j)
        self.salir_hall(j); return None
    def on_QueryPlayerListInHallReq(self, sesion, d):
        return 'QueryPlayerListInHallRsp', dict(OnlinePlayers=[p.uid for p in self.conectados.values() if p.hall])
    def on_QueryRoomListInHallReq(self, sesion, d):
        return 'QueryRoomListInHallRsp', dict(RoomInfos=[m.detalle() for m in self.mesas.values()])
    def on_SendHallChatReq(self, sesion, d):
        j = sesion.jugador; self.difundir_hall('NotifyGameHallChat', dict(Uid=j.uid, Content=d.get('Content', ''), Timestamp=int(time.time()))); return None

    # ---- handlers: mesa (sala)
    def sentar(self, j, mesa, pos):
        if pos == AUTO: pos = LEFT if mesa.izq is None else RIGHT if mesa.der is None else OBSERVER
        if pos == LEFT and (mesa.izq is None or mesa.izq is j): mesa.quitar(j); mesa.izq = j
        elif pos == RIGHT and (mesa.der is None or mesa.der is j): mesa.quitar(j); mesa.der = j
        else:
            pos = OBSERVER; mesa.quitar(j)
            if j not in mesa.observadores: mesa.observadores.append(j)
        j.pos = pos; j.mesa = mesa; return pos
    def on_EnterHallRoomReq(self, sesion, d):
        j = sesion.jugador; mesa = self.mesas.get(d.get('RoomId', 0))
        if mesa is None: return 'Error', dict(ErrCode=3, ErrMsg='Mesa inexistente', ErrMsgEn='Room not found')
        if j.mesa and j.mesa is not mesa: self.salir_mesa(j)
        j.pvp_prefs = d.get('PvpPrefs'); pos = self.sentar(j, mesa, d.get('Pos', AUTO))
        self.difundir_mesa(mesa, 'NotifyPlayerEnterHallRoom', dict(PlayerId=j.uid, RoomId=mesa.id, Pos=pos, ObIndex=len(mesa.observadores), WasObserver=False), excepto=j)
        self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle(), excepto=j)
        sesion.despues.append(('GameHallState', self.estado_hall(j)))
        self.comprobar_partida(mesa)
        return 'EnterHallRoomRsp', dict()
    def on_ChallengeInRoomReq(self, sesion, d):
        j = sesion.jugador; mesa = j.mesa
        if not mesa: return 'Error', dict(ErrCode=4, ErrMsg='No estas en una mesa', ErrMsgEn='Not in a room')
        pos = self.sentar(j, mesa, d.get('Pos', AUTO))
        self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle())
        for p in mesa.jugadores(): p.notificar('GameHallState', self.estado_hall(p))
        self.comprobar_partida(mesa)
        return None
    def on_ExitHallRoomReq(self, sesion, d): self.salir_mesa(sesion.jugador); return None
    def on_SendRoomChatReq(self, sesion, d):
        j = sesion.jugador
        if j.mesa: self.difundir_mesa(j.mesa, 'NotifyGameHallRoomChat', dict(Uid=j.uid, Content=d.get('Content', ''), Timestamp=int(time.time())), excepto=j)
        return 'SendRoomChatRsp', dict(Content=d.get('Content', ''))
    def comprobar_partida(self, mesa):
        if mesa.izq and mesa.der and not mesa.partida:
            p = Partida(self._next_match, mesa); self._next_match += 1; mesa.partida = p; self.partidas[p.id] = p
            log.info('partida %d creada en mesa %d: %s vs %s', p.id, mesa.id, mesa.izq.nombre, mesa.der.nombre)
            self.difundir_mesa(mesa, 'NotifyGameHallMatchCreated', dict(RoomDetail=mesa.detalle(), MatchState=p.estado()))

    # ---- handlers: partida (seleccion, carga, resultado)
    def partida_de(self, j): return j.mesa.partida if j and j.mesa else None
    def on_SelectCharReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p:
            m = p.miembros[j.pos] if j.pos in p.miembros else None
            if m: m.update(CharId=d.get('CharId', 0), RandomChar=d.get('Random', False), CostumeId=d.get('CostumeId', 0), CharConfirmed=False)
            self.difundir_mesa(j.mesa, 'NotifyOtherSelectChar', dict(Side=j.pos, Pos=0, CharId=d.get('CharId', 0), Random=d.get('Random', False), CostumeId=d.get('CostumeId', 0)), excepto=j)
        return 'SelectCharRsp', dict(CharId=d.get('CharId', 0), Random=d.get('Random', False), CostumeId=d.get('CostumeId', 0), Side=j.pos, Pos=0)
    def on_SelectCostumeReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p and j.pos in p.miembros: p.miembros[j.pos]['CostumeId'] = d.get('CostumeId', 0)
        return 'SelectCostumeRsp', dict(CostumeId=d.get('CostumeId', 0), Side=j.pos, Pos=0)
    def on_ConfirmSelectCharReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p and j.pos in p.miembros:
            p.miembros[j.pos].update(CharConfirmed=d.get('Confirm', True), CharId=d.get('CharId', p.miembros[j.pos]['CharId']))
            self.difundir_mesa(j.mesa, 'NotifyOtherConfirmSelectChar', dict(Side=j.pos, Pos=0, CharId=d.get('CharId', 0), Confirm=d.get('Confirm', True)), excepto=j)
            if all(m['CharConfirmed'] for m in p.miembros.values()):
                p.fase = SELECTING_STAGE; self.difundir_mesa(j.mesa, 'NotifyMatchState', dict(MatchState=p.estado(), MatchMakingType=0, Teammates=[]))
        return 'ConfirmSelectCharRsp', dict(Confirm=d.get('Confirm', True), Side=j.pos, Pos=0)
    def on_SelectStageReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p:
            p.escenario = d.get('StageId', 1)
            self.difundir_mesa(j.mesa, 'NotifyOtherSelectStage', dict(StageId=p.escenario, Random=d.get('Random', False)), excepto=j)
        return 'SelectStageRsp', dict(StageId=d.get('StageId', 1), Random=d.get('Random', False))
    def on_ConfirmSelectStageReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p:
            p.escenario_confirmado = True; p.fase = LOADING_FIGHT
            p.relay = dict(Id=1, Port=self.puerto_relay, KcpConv=p.id & 0xFFFF, RelayId=p.id, Host=self.host, NetCode=0, InnerHost=self.host,
                           InnerPort=self.puerto_relay, TcpInnerPort=self.puerto_relay, TcpOuterPort=self.puerto_relay, UseRudp=False)
            self.difundir_mesa(j.mesa, 'NotifyOtherConfirmSelectStage', dict(Confirm=True), excepto=j)
            self.difundir_mesa(j.mesa, 'NotifyMatchState', dict(MatchState=p.estado(), MatchMakingType=0, Teammates=[]))
        return None
    def on_SyncLoadingProgressReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p and j.pos in p.miembros:
            p.miembros[j.pos]['LoadingProgress'] = d.get('Progress', 0)
        return 'SyncLoadingProgressRsp', dict(LoadDone=d.get('Progress', 0) >= 100)
    def on_ReadyInMatchReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p and j.pos in p.miembros:
            p.miembros[j.pos]['Ready'] = d.get('Ready', True)
            self.difundir_mesa(j.mesa, 'NotifyOtherReadyInMatch', dict(Ready=d.get('Ready', True), Side=j.pos, Pos=0), excepto=j)
            if all(m['Ready'] for m in p.miembros.values()):
                p.fase = FIGHTING; self.difundir_mesa(j.mesa, 'NotifyMatchState', dict(MatchState=p.estado(), MatchMakingType=0, Teammates=[]))
        return None
    def on_BackToCharSelectReq(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p:
            p.fase = SELECTING_CHAR
            for m in p.miembros.values(): m.update(CharConfirmed=False, Ready=False, LoadingProgress=0)
            self.difundir_mesa(j.mesa, 'NotifyOtherBackToCharSelect', dict(Side=j.pos, Pos=0), excepto=j)
            self.difundir_mesa(j.mesa, 'NotifyMatchState', dict(MatchState=p.estado(), MatchMakingType=0, Teammates=[]))
        return 'BackToCharSelectRsp', dict()
    def on_UploadBattleResult(self, sesion, d):
        j = sesion.jugador; p = self.partida_de(j)
        if p and p.fase != END:
            w = d.get('WinnerSide', -1); mesa = j.mesa
            self.cuentas.registrar_partida(mesa.izq.uid, mesa.der.uid, w, d.get('LeftWinRound', 0), d.get('RightWinRound', 0),
                                           p.miembros[LEFT]['CharId'], p.miembros[RIGHT]['CharId'], p.escenario)
            log.info('resultado partida %d: ganador lado %d (%d-%d)', p.id, w, d.get('LeftWinRound', 0), d.get('RightWinRound', 0))
            p.fase = END; self.difundir_mesa(mesa, 'NotifyMatchState', dict(MatchState=p.estado(), MatchMakingType=0, Teammates=[]))
            for q in mesa.jugadores(): q.cuenta = self.cuentas.get(q.uid)
            mesa.partida = None; self.partidas.pop(p.id, None)
            for q in mesa.jugadores(): q.notificar('GameHallState', self.estado_hall(q))
        return None
    def on_ExitMatchReq(self, sesion, d):
        j = sesion.jugador
        if j.mesa and j.mesa.partida: self.salir_mesa(j)
        return None
    def on_RefightReq(self, sesion, d):
        j = sesion.jugador
        if j.mesa: self.comprobar_partida(j.mesa)
        return 'RefightRsp', dict(FightStarted=bool(j.mesa and j.mesa.partida))
