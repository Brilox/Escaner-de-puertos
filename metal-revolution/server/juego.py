#!/usr/bin/env python3
"""Logica de juego: cuentas, hall y mesas, busqueda de rival (1v1, 2v2, 3v3), clasificatoria, equipos, chat.

Todo se expresa como diccionarios que el codec FlatBuffers (fb_codec) convierte a bytes.
Cada handler on_<Peticion>(sesion, datos) devuelve (TipoRespuesta, dict) o None (EmptyRsp).
Los avisos a otros jugadores se mandan con jugador.notificar(TipoAviso, dict)."""
import copy, json, logging, os, random, sqlite3, time

log = logging.getLogger('mr.juego')
HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_JUEGO = '1.0.23'
NUM_MESAS = 8
LEFT, RIGHT, OBSERVER, AUTO = 0, 1, 2, 3                       # RoomPosType
WAITING_ALL_READY, SELECTING_CHAR, ORDERING_CHAR, SELECTING_STAGE, LOADING_FIGHT, FIGHTING, WAITING_RESULT, END = range(8)

# MatchMakingType (lo que pide el cliente al buscar) -> MatchType (el tipo de partida) y reglas
RANKING, RANKING_2V2, RANKING_NORMAL, RANKING_SOLO_3V3, QUICK_SOLO_3V3 = range(5)
MODOS = {
    RANKING:          dict(nombre='Clasificatoria 1v1', match_type=0, por_lado=1, slots=1, puntua=True),
    RANKING_2V2:      dict(nombre='Clasificatoria 2v2', match_type=7, por_lado=2, slots=1, puntua=True),
    RANKING_NORMAL:   dict(nombre='Normal 1v1',         match_type=1, por_lado=1, slots=1, puntua=False),
    RANKING_SOLO_3V3: dict(nombre='Clasificatoria 3v3', match_type=8, por_lado=1, slots=3, puntua=True),
    QUICK_SOLO_3V3:   dict(nombre='Normal 3v3',         match_type=9, por_lado=1, slots=3, puntua=False),
}
GAMEHALL = 5                                                    # MatchType de las mesas del hall
PUNTOS_INICIALES, PUNTOS_GANAR, PUNTOS_PERDER = 1000, 25, 20
ANUNCIO = ('Bienvenido a Metal Online', 'Servidor privado sin fines de lucro, hecho por fans. '
           'Escribe /nombre TuNombre en el chat del hall para cambiar tu nombre.')

# ----------------------------------------------------------------- base de datos
class Cuentas:
    def __init__(self, ruta):
        self.db = sqlite3.connect(ruta, check_same_thread=False); self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS jugadores (
            uid INTEGER PRIMARY KEY, openid TEXT UNIQUE, nombre TEXT NOT NULL DEFAULT '', creado INTEGER, ultimo_login INTEGER,
            victorias INTEGER DEFAULT 0, derrotas INTEGER DEFAULT 0, empates INTEGER DEFAULT 0, partidas INTEGER DEFAULT 0,
            nivel INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, dispositivo TEXT DEFAULT '');
          CREATE TABLE IF NOT EXISTS ranking (
            uid INTEGER, modo INTEGER, puntos INTEGER DEFAULT 1000, max_puntos INTEGER DEFAULT 1000, victorias INTEGER DEFAULT 0,
            derrotas INTEGER DEFAULT 0, racha INTEGER DEFAULT 0, mejor_racha INTEGER DEFAULT 0, PRIMARY KEY (uid, modo));
          CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha INTEGER, modo TEXT, ganador INTEGER,
            izquierda TEXT, derecha TEXT, rondas_izq INTEGER, rondas_der INTEGER, personajes TEXT, escenario INTEGER);''')
        cols = [r[1] for r in self.db.execute('PRAGMA table_info(partidas)')]
        if 'modo' not in cols:   # base creada por la version anterior
            self.db.execute('ALTER TABLE partidas RENAME TO partidas_v1'); self.__init__(ruta); return
        self.db.commit()

    def login(self, openid, dispositivo):
        now = int(time.time()); r = self.db.execute('SELECT uid FROM jugadores WHERE openid=?', (openid,)).fetchone()
        if r is None:
            nuevo = (self.db.execute('SELECT MAX(uid) FROM jugadores').fetchone()[0] or 1000000) + 1
            self.db.execute('INSERT INTO jugadores(uid,openid,creado,ultimo_login,dispositivo) VALUES(?,?,?,?,?)', (nuevo, openid, now, now, dispositivo))
            self.db.commit(); log.info('cuenta nueva uid=%d', nuevo); return self.get(nuevo)
        self.db.execute('UPDATE jugadores SET ultimo_login=? WHERE uid=?', (now, r['uid'])); self.db.commit()
        return self.get(r['uid'])

    def get(self, uid):
        r = self.db.execute('SELECT * FROM jugadores WHERE uid=?', (uid,)).fetchone(); return dict(r) if r else None

    def poner_nombre(self, uid, nombre):
        nombre = ' '.join((nombre or '').split())[:16]
        if len(nombre) < 2: return 'El nombre debe tener al menos 2 caracteres'
        if self.db.execute('SELECT 1 FROM jugadores WHERE lower(nombre)=lower(?) AND uid<>?', (nombre, uid)).fetchone():
            return 'Ese nombre ya esta en uso'
        self.db.execute('UPDATE jugadores SET nombre=? WHERE uid=?', (nombre, uid)); self.db.commit(); return None

    def rank(self, uid, modo):
        r = self.db.execute('SELECT * FROM ranking WHERE uid=? AND modo=?', (uid, modo)).fetchone()
        return dict(r) if r else dict(uid=uid, modo=modo, puntos=PUNTOS_INICIALES, max_puntos=PUNTOS_INICIALES, victorias=0, derrotas=0, racha=0, mejor_racha=0)

    def top(self, modo, n=100):
        return [dict(r) for r in self.db.execute('SELECT * FROM ranking WHERE modo=? ORDER BY puntos DESC, victorias DESC LIMIT ?', (modo, n))]

    def posicion(self, uid, modo):
        mio = self.rank(uid, modo)['puntos']
        return 1 + self.db.execute('SELECT COUNT(*) FROM ranking WHERE modo=? AND puntos>?', (modo, mio)).fetchone()[0]

    def registrar(self, modo_txt, modo_rank, izquierda, derecha, ganador, r_izq, r_der, personajes, escenario):
        """izquierda/derecha: listas de uid. ganador: 0, 1 o -1 (empate). modo_rank: MatchMakingType que puntua o None."""
        self.db.execute('INSERT INTO partidas(fecha,modo,ganador,izquierda,derecha,rondas_izq,rondas_der,personajes,escenario) VALUES(?,?,?,?,?,?,?,?,?)',
                        (int(time.time()), modo_txt, ganador, json.dumps(izquierda), json.dumps(derecha), r_izq, r_der, json.dumps(personajes), escenario))
        for lado, uids in ((LEFT, izquierda), (RIGHT, derecha)):
            for uid in uids:
                col = 'empates' if ganador not in (LEFT, RIGHT) else ('victorias' if ganador == lado else 'derrotas')
                exp = 30 if col == 'victorias' else 10
                self.db.execute(f'UPDATE jugadores SET {col}={col}+1, partidas=partidas+1, exp=exp+?, nivel=1+(exp+?)/100 WHERE uid=?', (exp, exp, uid))
                if modo_rank is not None and ganador in (LEFT, RIGHT):
                    r = self.rank(uid, modo_rank); gana = ganador == lado
                    r['puntos'] = max(0, r['puntos'] + (PUNTOS_GANAR if gana else -PUNTOS_PERDER)); r['max_puntos'] = max(r['max_puntos'], r['puntos'])
                    r['victorias' if gana else 'derrotas'] += 1; r['racha'] = r['racha'] + 1 if gana else 0; r['mejor_racha'] = max(r['mejor_racha'], r['racha'])
                    self.db.execute('INSERT OR REPLACE INTO ranking VALUES(:uid,:modo,:puntos,:max_puntos,:victorias,:derrotas,:racha,:mejor_racha)', r)
        self.db.commit()

# ----------------------------------------------------------------- estado en memoria
class Jugador:
    def __init__(self, sesion, cuenta):
        self.sesion = sesion; self.cuenta = cuenta; self.uid = cuenta['uid']
        self.hall = None; self.mesa = None; self.asiento = OBSERVER
        self.partida = None; self.lado = None; self.slots = []          # slots (pos) que controla en la partida
        self.equipo = None; self.buscando = None; self.inicio_busqueda = 0; self.pvp_prefs = None
    @property
    def nombre(self): return self.cuenta['nombre'] or 'Jugador%d' % (self.uid % 100000)
    def notificar(self, tipo, datos): self.sesion.enviar_notificacion(tipo, datos)

class Mesa:
    def __init__(self, id_):
        self.id = id_; self.titulo = 'Mesa %d' % id_; self.clave = 0; self.observable = True; self.ocultar_seleccion = False
        self.izq = None; self.der = None; self.observadores = []; self.partida = None; self.anfitrion = None
    def jugadores(self): return [p for p in (self.izq, self.der) if p] + self.observadores
    def detalle(self):
        return dict(RoomId=self.id, Title=self.titulo, DisplayTitle=self.titulo, HasPassword=bool(self.clave),
                    LeftPlayerId=self.izq.uid if self.izq else 0, RightPlayerId=self.der.uid if self.der else 0,
                    Hot=len(self.jugadores()), AllowObserve=self.observable, IsArena=False, LoseCountRule=0, LeftLoseCount=0,
                    RightLoseCount=0, ObserverCount=len(self.observadores), HideCharSelection=self.ocultar_seleccion,
                    HostSide=RIGHT if self.anfitrion is not None and self.anfitrion is self.der else LEFT)
    def quitar(self, p):
        if self.izq is p: self.izq = None
        if self.der is p: self.der = None
        if p in self.observadores: self.observadores.remove(p)
        if self.anfitrion is p: self.anfitrion = self.izq or self.der
    def reiniciar(self):
        self.titulo = 'Mesa %d' % self.id; self.clave = 0; self.observable = True; self.ocultar_seleccion = False

class Equipo:
    def __init__(self, lider, modo): self.lider = lider; self.modo = modo; self.miembros = [lider]

class Partida:
    """Una pelea. lados[LEFT] y lados[RIGHT] son listas de Jugador; cada jugador controla `slots` personajes."""
    def __init__(self, id_, match_type, izquierda, derecha, slots=1, mesa=None, modo_mm=None):
        self.id = id_; self.match_type = match_type; self.mesa = mesa; self.modo_mm = modo_mm
        self.lados = {LEFT: izquierda, RIGHT: derecha}; self.fase = SELECTING_CHAR; self.seed = random.randint(1, 2**31 - 1)
        self.escenario = 1; self.escenario_confirmado = False; self.inicio = int(time.time()); self.relay = None; self.resultado = None
        self.miembros = {LEFT: [], RIGHT: []}
        for lado, jugadores in self.lados.items():
            pos = 0
            for j in jugadores:
                j.partida = self; j.lado = lado; j.slots = []
                for _ in range(slots):
                    self.miembros[lado].append(self.miembro(j, lado, pos)); j.slots.append(pos); pos += 1
    @staticmethod
    def miembro(j, lado, pos):
        return dict(Uid=j.uid, CharId=0, RandomChar=False, CostumeId=0, AltColorIndex=0, CharConfirmed=False, InBattleStatus=0,
                    Ready=False, LoadingProgress=0, PendingSwitchOrderTeammateId=0, PvpPrefs=j.pvp_prefs, ShouldPunishForEarlyExit=False,
                    BattleEndStatus=0, Side=lado, Pos=pos, NetStatus=0, FakeWinPoint=0, AiControlledByUid=0, BePraisedCount=0)
    def jugadores(self): return self.lados[LEFT] + self.lados[RIGHT]
    def todos_los_miembros(self): return self.miembros[LEFT] + self.miembros[RIGHT]
    def slot(self, j, d):
        """El miembro al que se refiere una peticion: por (Side, Pos) si es del jugador, si no su primer slot."""
        pos = d.get('Pos', None)
        if pos is not None and pos in j.slots: return self.miembros[j.lado][pos]
        return self.miembros[j.lado][j.slots[0]] if j.slots else None
    def estado(self):
        now = int(time.time())
        return dict(MatchType=self.match_type, MatchId=self.id, SubMatchId=0, Phase=self.fase, Version=VERSION_JUEGO,
                    LeftMembers=self.miembros[LEFT], RightMembers=self.miembros[RIGHT], StartTime=self.inicio, EndTime=0,
                    RandomSeed=self.seed, RefightRemainCount=3, LeftWonCount=0, RightWonCount=0, StageId=self.escenario,
                    RandomStage=False, StageConfirmed=self.escenario_confirmado, StartSelectCharTime=now, StartOrderCharTime=now,
                    StartSelectStageTime=now, StartWaitingReadyTime=now, SelectCharMaxTime=60, SelectStageMaxTime=30,
                    WaitingReadyMaxTime=60, OrderCharMaxTime=30, RelayServerInfo=self.relay, LeftOrderingIndex=0, RightOrderingIndex=0,
                    AllowSameCharInTeam=True, AllowSameCharInMatch=True, SkipReorderChar=True, SkipSelectStage=False)

# ----------------------------------------------------------------- juego
class Juego:
    PUBLICOS = {'LoginRequest', 'PlayerClientPing', 'QueryServerTimeReq', 'AnalyticsBeforeLoginReq'}

    def __init__(self, host, puerto, puerto_relay, plantilla_login, nombre_automatico=False):
        self.host = host; self.puerto = puerto; self.puerto_relay = puerto_relay; self.plantilla = plantilla_login
        self.nombre_automatico = nombre_automatico
        self.cuentas = Cuentas(os.path.join(HERE, 'cuentas.db'))
        self.conectados = {}                                         # uid -> Jugador
        self.mesas = {i: Mesa(i) for i in range(1, NUM_MESAS + 1)}
        self.partidas = {}; self._sig_partida = 1
        self.colas = {m: [] for m in MODOS}                          # modo -> [lista de grupos (listas de Jugador)]
        self.chat_hall = []                                          # ultimos mensajes del hall
        self.handlers = {n[3:]: getattr(self, n) for n in dir(self) if n.startswith('on_')}

    # ================================================================= utilidades
    def info_detallada(self, cuenta):
        pi = copy.deepcopy(self.plantilla['PlayerInfo']); uid = cuenta['uid']; j = self.conectados.get(uid)
        pi['BaseInfo'].update(Uid=uid, Name=cuenta['nombre'], Level=cuenta['nivel'], Exp=cuenta['exp'], RegisterTime=cuenta['creado'] or 0,
                              OnlineState=1 if j else 0, GameVersion=VERSION_JUEGO, ClientVersion=VERSION_JUEGO,
                              GameHallId=1 if j and j.hall else 0, HallRoomId=j.mesa.id if j and j.mesa else 0, TotalLoginDay=1)
        pi['BattleData'] = self.datos_batalla(cuenta)
        return pi

    def datos_batalla(self, cuenta):
        uid = cuenta['uid']; mm = []
        for modo in range(len(MODOS)):
            r = self.cuentas.rank(uid, modo)
            mm.append(dict(Happiness=0, RankPoint=r['puntos'], WinPoint=r['puntos'], MaxWinPoint=r['max_puntos'], ContinueRewardAiCount=0,
                           FavorHeroId=0, ExitInBattleCountToday=0, ForbidMatchUntilTime=0))
        total = dict(WinCount=cuenta['victorias'], TotalCount=cuenta['partidas'], ContinueWinCount=0, MaxContinueWinCount=0)
        return dict(Uid=uid, DetailLevel=0, PreferNetCode=0, CommonBattleStats=[total], MatchMakingBattleStats=mm)

    def respuesta_login(self, cuenta):
        return 'LoginGameSvrRsp', dict(self.plantilla, PlayerInfo=self.info_detallada(cuenta), UtcTimeOffset=0, GameServerId=1, PayZoneId=0)

    def difundir_hall(self, tipo, datos, excepto=None):
        for p in list(self.conectados.values()):
            if p.hall and p is not excepto: p.notificar(tipo, datos)
    def difundir(self, jugadores, tipo, datos, excepto=None):
        for p in jugadores:
            if p is not excepto: p.notificar(tipo, datos)
    def estado_partida(self, p): self.difundir(p.jugadores() + (p.mesa.observadores if p.mesa else []), 'NotifyMatchState', dict(MatchState=p.estado(), MatchMakingType=p.modo_mm or 0, Teammates=[]))

    def detalle_hall(self):
        return dict(RoomNum=len(self.mesas), IsArena=False, Full=False, PlayerCount=sum(1 for p in self.conectados.values() if p.hall),
                    MinRoomId=1, MaxRoomId=len(self.mesas))
    def estado_hall(self, j):
        m = j.mesa
        return dict(HallId=1, RoomId=m.id if m else 0, HallInfo=self.detalle_hall(), RoomDetail=m.detalle() if m else None,
                    MatchState=m.partida.estado() if m and m.partida else None)
    def mensaje_sistema(self, j, texto):
        j.notificar('NotifyGameHallChat', dict(Uid=0, Content=texto, Timestamp=int(time.time())))

    # ================================================================= conexion
    def desconectar(self, j):
        if j is None or self.conectados.get(j.uid) is not j: return
        self.cancelar_busqueda(j, avisar=False); self.salir_equipo(j)
        if j.partida and not j.mesa: self.abandonar_partida(j)
        if j.mesa: self.salir_mesa(j, servidor=True)
        if j.hall: self.salir_hall(j)
        self.conectados.pop(j.uid, None); log.info('desconectado uid=%d %s', j.uid, j.nombre)

    # ================================================================= cuenta
    def on_AnalyticsBeforeLoginReq(self, sesion, d): return None
    def on_LoginRequest(self, sesion, d):
        openid = d.get('OpenId') or d.get('DeviceId') or d.get('YzDeviceId') or 'anon-%s' % sesion.peer[0]
        cuenta = self.cuentas.login(openid, d.get('Model', ''))
        if not cuenta['nombre'] and self.nombre_automatico:
            self.cuentas.poner_nombre(cuenta['uid'], 'Jugador%d' % (cuenta['uid'] % 100000)); cuenta = self.cuentas.get(cuenta['uid'])
        viejo = self.conectados.get(cuenta['uid'])
        if viejo and viejo.sesion is not sesion:
            viejo.notificar('NotifyLoginByOther', dict(Param=dict(DeviceId=d.get('DeviceId', ''), ProcessId=0, DataVersion=0)))
            self.desconectar(viejo); viejo.sesion.jugador = None
        j = Jugador(sesion, cuenta); self.conectados[j.uid] = j; sesion.jugador = j
        log.info('login uid=%d nombre=%r (%s)', j.uid, cuenta['nombre'], 'pedira nombre' if not cuenta['nombre'] else 'ok')
        return self.respuesta_login(cuenta)
    def on_CreateRoleReq(self, sesion, d):
        j = sesion.jugador; err = self.cuentas.poner_nombre(j.uid, d.get('Name', ''))
        if err: return 'Error', dict(ErrCode=2, ErrMsg=err, ErrMsgEn=err)
        j.cuenta = self.cuentas.get(j.uid); log.info('uid=%d crea su jugador: %r', j.uid, j.nombre)
        return self.respuesta_login(j.cuenta)
    def on_UseNameCardReq(self, sesion, d):
        return self.renombrar(sesion.jugador, d.get('NewName', ''))
    def renombrar(self, j, nombre):
        err = self.cuentas.poner_nombre(j.uid, nombre)
        if err: self.mensaje_sistema(j, err); return 'Error', dict(ErrCode=2, ErrMsg=err, ErrMsgEn=err)
        j.cuenta = self.cuentas.get(j.uid); log.info('uid=%d ahora se llama %r', j.uid, j.nombre)
        j.notificar('NotifyBasePlayerInfoChange', self.info_detallada(j.cuenta)); self.mensaje_sistema(j, 'Ahora te llamas ' + j.nombre)
        return None
    def on_NameCardCdReq(self, sesion, d): return 'NameCardCdRsp', dict(TimeLeft=0)
    def on_QueryRoleIdByNameReq(self, sesion, d):
        r = self.cuentas.db.execute('SELECT uid FROM jugadores WHERE lower(nombre)=lower(?)', (d.get('Name', ''),)).fetchone()
        return 'QueryRoleIdByNameRsp', dict(Name=d.get('Name', ''), SrcUid=sesion.jugador.uid, ResultUids=[r['uid']] if r else [])
    def on_QueryServerTimeReq(self, sesion, d): return 'QueryServerTimeRsp', dict(ServerTime=int(time.time()), TimeOffset=0, ServerTimeOffset=0)
    def on_PlayerClientPing(self, sesion, d): return 'PlayerClientPong', dict(Timestamp=d.get('Timestamp') or int(time.time() * 1000))
    def on_QueryPlayerInfoReq(self, sesion, d):
        c = self.cuentas.get(d.get('Uid', 0)); return 'QueryPlayerInfoRsp', dict(Result=self.info_detallada(c) if c else None)
    def on_BatchQueryPlayerInfoReq(self, sesion, d):
        return 'BatchQueryPlayerInfoRsp', dict(Result=[self.info_detallada(c) for c in (self.cuentas.get(u) for u in d.get('Uids', [])) if c])
    def on_QueryBattleDataReq(self, sesion, d):
        c = self.cuentas.get(d.get('Uid') or sesion.jugador.uid); return ('PlayerBattleData', self.datos_batalla(c)) if c else None
    def on_QueryServerAnnounceReq(self, sesion, d):
        return 'QueryServerAnnounceRsp', dict(AnnounceList=[dict(Id=1, Title=ANUNCIO[0], Content=ANUNCIO[1], ShowOnce=False)])
    def on_QueryPveDataReq(self, sesion, d): return 'PlayerPveData', dict(CurFightingStage=0, CurRivalIndexInStage=0)
    def on_LogoutGameSvrReq(self, sesion, d): self.desconectar(sesion.jugador); sesion.jugador = None; return None

    # ================================================================= ranking
    def on_QueryTopRankReq(self, sesion, d):
        modo = d.get('RankType', 0) if d.get('RankType', 0) in MODOS else RANKING
        if d.get('QueryType', 0) == 1:
            r = self.cuentas.rank(sesion.jugador.uid, modo)
            return 'QueryTopRankRsp', dict(RankData=[dict(Uid=sesion.jugador.uid, Rank=self.cuentas.posicion(sesion.jugador.uid, modo), Score=r['puntos'])])
        return 'QueryTopRankRsp', dict(RankData=[dict(Uid=r['uid'], Rank=i + 1, Score=r['puntos']) for i, r in enumerate(self.cuentas.top(modo))])
    def on_QueryPlayerRankReq(self, sesion, d):
        modo = d.get('RankType', 0) if d.get('RankType', 0) in MODOS else RANKING; uid = d.get('Uid') or sesion.jugador.uid
        return 'QueryPlayerRankRsp', dict(Rank=self.cuentas.posicion(uid, modo), Score=self.cuentas.rank(uid, modo)['puntos'])
    def on_QueryRankRewardTimeReq(self, sesion, d): return 'QueryRankRewardTimeRsp', dict(Time=int(time.time()) + 30 * 86400)

    # ================================================================= chat
    def on_SendHallChatReq(self, sesion, d):
        j = sesion.jugador; texto = (d.get('Content') or '').strip()
        if texto.lower().startswith('/nombre '): self.renombrar(j, texto[8:]); return None
        msg = dict(Uid=j.uid, Content=texto[:200], Timestamp=int(time.time()))
        self.chat_hall = (self.chat_hall + [msg])[-50:]; self.difundir_hall('NotifyGameHallChat', msg); return None
    def on_QueryRecentChatReq(self, sesion, d):
        return 'QueryRecentChatRsp', dict(MsgType=0, ChatList=[dict(SenderUid=m['Uid'], TargetUid=0, Time=m['Timestamp'], Content=m['Content']) for m in self.chat_hall[-30:]])
    def on_SendRoomChatReq(self, sesion, d):
        j = sesion.jugador; texto = (d.get('Content') or '').strip()[:200]
        if texto.lower().startswith('/nombre '): self.renombrar(j, texto[8:]); return 'SendRoomChatRsp', dict(Content=texto)
        if j.mesa: self.difundir(j.mesa.jugadores(), 'NotifyGameHallRoomChat', dict(Uid=j.uid, Content=texto, Timestamp=int(time.time())), excepto=j)
        return 'SendRoomChatRsp', dict(Content=texto)
    def on_SendChatReq(self, sesion, d):
        j = sesion.jugador; dest = self.conectados.get(d.get('TargetUid', 0))
        rsp = dict(Req=d, SenderUid=j.uid, SenderName=j.nombre, SendTime=int(time.time()))
        if dest: dest.notificar('RecvChat', rsp)
        return 'SendChatRsp', rsp
    def on_ChatInMatchReq(self, sesion, d):
        j = sesion.jugador
        if j.partida:
            self.difundir(j.partida.jugadores(), 'NotifyOtherChatInMatch', dict(Sender=j.uid, Content=d.get('Content', ''), MatchType=j.partida.match_type,
                          Range=d.get('Range', 0)), excepto=j)
        return None

    # ================================================================= hall y mesas
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
    def salir_hall(self, j):
        if j.hall: j.hall = None; self.difundir_hall('NotifyPlayerExitHall', dict(Uid=j.uid), excepto=j)
    def on_QueryPlayerListInHallReq(self, sesion, d):
        return 'QueryPlayerListInHallRsp', dict(OnlinePlayers=[p.uid for p in self.conectados.values() if p.hall])
    def on_QueryRoomListInHallReq(self, sesion, d):
        return 'QueryRoomListInHallRsp', dict(RoomInfos=[m.detalle() for m in self.mesas.values()])

    def sentar(self, j, mesa, pos):
        if pos == AUTO: pos = LEFT if mesa.izq is None else RIGHT if mesa.der is None else OBSERVER
        if pos == LEFT and mesa.izq in (None, j): mesa.quitar(j); mesa.izq = j
        elif pos == RIGHT and mesa.der in (None, j): mesa.quitar(j); mesa.der = j
        else:
            pos = OBSERVER; mesa.quitar(j)
            if j not in mesa.observadores: mesa.observadores.append(j)
        if mesa.anfitrion is None and pos != OBSERVER: mesa.anfitrion = j
        j.asiento = pos; j.mesa = mesa; return pos
    def on_EnterHallRoomReq(self, sesion, d):
        j = sesion.jugador; mesa = self.mesas.get(d.get('RoomId', 0))
        if mesa is None: return 'Error', dict(ErrCode=3, ErrMsg='La mesa no existe', ErrMsgEn='Room not found')
        if mesa.clave and d.get('Password', 0) != mesa.clave and not mesa.jugadores():
            mesa.reiniciar()
        if mesa.clave and d.get('Password', 0) != mesa.clave:
            return 'Error', dict(ErrCode=5, ErrMsg='Clave incorrecta', ErrMsgEn='Wrong password')
        if j.mesa and j.mesa is not mesa: self.salir_mesa(j)
        j.pvp_prefs = d.get('PvpPrefs'); pos = self.sentar(j, mesa, d.get('Pos', AUTO))
        self.difundir(mesa.jugadores(), 'NotifyPlayerEnterHallRoom', dict(PlayerId=j.uid, RoomId=mesa.id, Pos=pos, ObIndex=len(mesa.observadores), WasObserver=False), excepto=j)
        self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle(), excepto=j)
        sesion.despues.append(('GameHallState', self.estado_hall(j)))
        self.comprobar_mesa(mesa)
        return 'EnterHallRoomRsp', dict()
    def on_ChallengeInRoomReq(self, sesion, d):
        j = sesion.jugador; mesa = j.mesa
        if not mesa: return 'Error', dict(ErrCode=4, ErrMsg='No estas en una mesa', ErrMsgEn='Not in a room')
        if mesa.partida: return 'Error', dict(ErrCode=6, ErrMsg='Ya hay una pelea en curso', ErrMsgEn='Fight in progress')
        pos = self.sentar(j, mesa, d.get('Pos', AUTO))
        self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle())
        for p in mesa.jugadores(): p.notificar('GameHallState', self.estado_hall(p))
        self.comprobar_mesa(mesa); return None
    def on_SetRoomPasswordReq(self, sesion, d):
        j = sesion.jugador; mesa = j.mesa
        if mesa and mesa.anfitrion in (None, j):
            mesa.clave = d.get('Password', 0) or 0; mesa.observable = d.get('AllowOb', True)
            mesa.ocultar_seleccion = d.get('HideCharSelection', False); titulo = (d.get('Title') or '').strip()
            if titulo: mesa.titulo = titulo[:20]
            self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle())
        return None
    def on_ExitHallRoomReq(self, sesion, d): self.salir_mesa(sesion.jugador); return None
    def on_QueryRoomObserverListReq(self, sesion, d):
        m = sesion.jugador.mesa
        return 'QueryRoomObserverListRsp', dict(Uids=[p.uid for p in m.observadores] if m else [])
    def salir_mesa(self, j, servidor=False):
        mesa = j.mesa
        if not mesa: return
        if mesa.partida and j in mesa.partida.jugadores(): self.abandonar_partida(j)
        mesa.quitar(j); j.mesa = None; j.asiento = OBSERVER
        self.difundir(mesa.jugadores(), 'NotifyPlayerExitHallRoom', dict(PlayerId=j.uid, RoomId=mesa.id, ServerExit=servidor))
        if not mesa.jugadores(): mesa.reiniciar()
        self.difundir_hall('NotifyRoomDetailInfoUpdate', mesa.detalle())
    def comprobar_mesa(self, mesa):
        if mesa.izq and mesa.der and not mesa.partida:
            p = self.crear_partida(GAMEHALL, [mesa.izq], [mesa.der], mesa=mesa)
            log.info('mesa %d: pelea %d %s vs %s', mesa.id, p.id, mesa.izq.nombre, mesa.der.nombre)
            self.difundir(mesa.jugadores(), 'NotifyGameHallMatchCreated', dict(RoomDetail=mesa.detalle(), MatchState=p.estado()))

    # ================================================================= busqueda de rival y equipos
    def on_StartSearchMatchReq(self, sesion, d):
        j = sesion.jugador; modo = d.get('MatchMakingType', RANKING)
        if modo not in MODOS: return 'Error', dict(ErrCode=7, ErrMsg='Modo no disponible', ErrMsgEn='Mode not available')
        if j.partida: return 'Error', dict(ErrCode=6, ErrMsg='Ya estas en una pelea', ErrMsgEn='Already in a match')
        j.pvp_prefs = d.get('PvpPrefs')
        grupo = j.equipo.miembros if j.equipo and j.equipo.lider is j and j.equipo.modo == modo else [j]
        if len(grupo) > MODOS[modo]['por_lado']: grupo = [j]
        self.cancelar_busqueda(j, avisar=False)
        ahora = int(time.time())
        for p in grupo:
            p.buscando = modo; p.inicio_busqueda = ahora
            if p is not j: p.notificar('NotifyTeammateStartSearchMatch', dict(StarterUid=j.uid, LastSearchTime=ahora, MatchMakingType=modo))
        self.colas[modo].append(grupo)
        log.info('%s busca %s (grupo de %d); en cola: %d grupos', j.nombre, MODOS[modo]['nombre'], len(grupo), len(self.colas[modo]))
        sesion.despues.append(('__emparejar__', modo))
        return 'StartSearchMatchRsp', dict(LastSearchTime=ahora)
    def cancelar_busqueda(self, j, avisar=True):
        modo = j.buscando
        if modo is None: return
        for grupo in list(self.colas[modo]):
            if j in grupo:
                self.colas[modo].remove(grupo)
                for p in grupo:
                    p.buscando = None
                    if avisar and p is not j: p.notificar('NotifySearchCanceled', dict())
        j.buscando = None
    def emparejar(self, modo):
        n = MODOS[modo]['por_lado']; cola = self.colas[modo]
        while True:
            lados = [[], []]; usados = []
            for grupo in cola:
                for lado in lados:
                    if len(lado) + len(grupo) <= n and not (lado is lados[1] and len(lados[0]) < n):
                        lado.extend(grupo); usados.append(grupo); break
                if len(lados[0]) == n and len(lados[1]) == n: break
            if len(lados[0]) < n or len(lados[1]) < n: return
            for g in usados: cola.remove(g)
            for p in lados[0] + lados[1]: p.buscando = None
            cfg = MODOS[modo]
            p = self.crear_partida(cfg['match_type'], lados[0], lados[1], slots=cfg['slots'], modo_mm=modo)
            log.info('%s: pelea %d %s vs %s', cfg['nombre'], p.id, [x.nombre for x in lados[0]], [x.nombre for x in lados[1]])
            self.difundir(p.jugadores(), 'NotifySearchMatchRivalFound', dict(MatchState=p.estado()))
    def on_ExitMatchReq(self, sesion, d):
        j = sesion.jugador
        if j.buscando is not None: self.cancelar_busqueda(j); return None
        if j.partida:
            if j.mesa: self.salir_mesa(j)
            else: self.abandonar_partida(j)
        return None

    def on_EnterInviteRoomReq(self, sesion, d):
        j = sesion.jugador; modo = d.get('MatchMakingType', RANKING_2V2)
        if not j.equipo: j.equipo = Equipo(j, modo)
        j.equipo.modo = modo; return None
    def on_InvitePlayerToRoomReq(self, sesion, d):
        j = sesion.jugador; dest = self.conectados.get(d.get('TargetUid', 0))
        if not dest: return 'Error', dict(ErrCode=8, ErrMsg='Ese jugador no esta conectado', ErrMsgEn='Player offline')
        if not j.equipo: j.equipo = Equipo(j, RANKING_2V2)
        dest.notificar('NotifyOtherInviteYouToRoom', dict(Inviter=j.uid, MatchMakingType=j.equipo.modo)); return None
    def on_AcceptInviteReq(self, sesion, d):
        j = sesion.jugador; lider = self.conectados.get(d.get('Inviter', 0)); acepta = d.get('Accept', False)
        if not lider or not lider.equipo:
            return 'Error', dict(ErrCode=9, ErrMsg='La invitacion ya no es valida', ErrMsgEn='Invite expired')
        eq = lider.equipo
        if acepta:
            if len(eq.miembros) >= MODOS.get(eq.modo, MODOS[RANKING_2V2])['por_lado']:
                return 'Error', dict(ErrCode=10, ErrMsg='El equipo esta lleno', ErrMsgEn='Team is full')
            self.salir_equipo(j); eq.miembros.append(j); j.equipo = eq; j.pvp_prefs = d.get('PvpPrefs')
        self.difundir(eq.miembros, 'NotifyOtherAcceptYourInvite', dict(Uid=j.uid, Accept=acepta, MatchMakingType=eq.modo), excepto=j)
        if not acepta: lider.notificar('NotifyOtherAcceptYourInvite', dict(Uid=j.uid, Accept=False, MatchMakingType=eq.modo))
        return 'AcceptInviteRsp', dict(Team=[p.uid for p in eq.miembros] if acepta else [])
    def on_ExitInviteRoomReq(self, sesion, d): self.salir_equipo(sesion.jugador); return None
    def salir_equipo(self, j):
        eq = j.equipo
        if not eq: return
        self.cancelar_busqueda(j)
        if j in eq.miembros: eq.miembros.remove(j)
        j.equipo = None
        self.difundir(eq.miembros, 'NotifyOtherLeaveTeam', dict(Uid=j.uid, MatchMakingType=eq.modo))
        if eq.lider is j and eq.miembros: eq.lider = eq.miembros[0]

    # ================================================================= partida
    def crear_partida(self, match_type, izq, der, slots=1, mesa=None, modo_mm=None):
        p = Partida(self._sig_partida, match_type, izq, der, slots, mesa, modo_mm); self._sig_partida += 1
        self.partidas[p.id] = p
        if mesa: mesa.partida = p
        return p
    def cerrar_partida(self, p):
        for j in p.jugadores():
            if j.partida is p: j.partida = None; j.lado = None; j.slots = []
        if p.mesa and p.mesa.partida is p: p.mesa.partida = None
        self.partidas.pop(p.id, None)
    def abandonar_partida(self, j):
        p = j.partida
        if not p: return
        lado = j.lado; rival = RIGHT if lado == LEFT else LEFT
        for pos in j.slots: self.difundir(p.jugadores(), 'NotifyPlayerLeftInMatch', dict(Side=lado, Pos=pos), excepto=j)
        if p.fase in (LOADING_FIGHT, FIGHTING, WAITING_RESULT) and p.resultado is None:
            self.guardar_resultado(p, rival, 0, 0, abandono=True)
        elif p.resultado is None:      # aun eligiendo personajes: se cancela sin puntos para nadie
            self.difundir(p.jugadores(), 'NotifyMatchCancelled', dict(MatchId=p.id, Side=lado, Pos=j.slots[0] if j.slots else 0), excepto=j)
        self.cerrar_partida(p)
        if p.mesa:
            for q in p.mesa.jugadores(): q.notificar('GameHallState', self.estado_hall(q))

    def on_SelectCharReq(self, sesion, d):
        j = sesion.jugador; p = j.partida; m = p.slot(j, d) if p else None
        if m:
            m.update(CharId=d.get('CharId', 0), RandomChar=d.get('Random', False), CostumeId=d.get('CostumeId', 0), CharConfirmed=False)
            self.difundir(p.jugadores(), 'NotifyOtherSelectChar', dict(Side=m['Side'], Pos=m['Pos'], CharId=m['CharId'], Random=m['RandomChar'], CostumeId=m['CostumeId']), excepto=j)
        return 'SelectCharRsp', dict(CharId=d.get('CharId', 0), Random=d.get('Random', False), CostumeId=d.get('CostumeId', 0),
                                     Side=m['Side'] if m else 0, Pos=m['Pos'] if m else 0)
    def on_SelectCostumeReq(self, sesion, d):
        j = sesion.jugador; p = j.partida; m = p.slot(j, d) if p else None
        if m: m['CostumeId'] = d.get('CostumeId', 0)
        return 'SelectCostumeRsp', dict(CostumeId=d.get('CostumeId', 0), Side=m['Side'] if m else 0, Pos=m['Pos'] if m else 0)
    def on_ConfirmSelectCharReq(self, sesion, d):
        j = sesion.jugador; p = j.partida; m = p.slot(j, d) if p else None
        if m:
            m['CharConfirmed'] = d.get('Confirm', True)
            if d.get('CharId'): m['CharId'] = d['CharId']
            self.difundir(p.jugadores(), 'NotifyOtherConfirmSelectChar', dict(Confirm=m['CharConfirmed'], Side=m['Side'], Pos=m['Pos']), excepto=j)
            if all(x['CharConfirmed'] for x in p.todos_los_miembros()):
                p.fase = SELECTING_STAGE; sesion.despues.append(('__estado__', p))
        return 'ConfirmSelectCharRsp', dict(Confirm=d.get('Confirm', True), Side=m['Side'] if m else 0, Pos=m['Pos'] if m else 0)
    def on_ChangeCharOrderReq(self, sesion, d): return 'ChangeCharOrderRsp', dict()
    def on_SelectStageReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p:
            p.escenario = d.get('StageId', 1)
            self.difundir(p.jugadores(), 'NotifyOtherSelectStage', dict(StageId=p.escenario, Random=d.get('Random', False), Side=j.lado, Pos=j.slots[0]), excepto=j)
        return 'SelectStageRsp', dict(StageId=d.get('StageId', 1), Random=d.get('Random', False))
    def on_ConfirmSelectStageReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p and not p.escenario_confirmado:
            p.escenario_confirmado = True; p.fase = LOADING_FIGHT
            p.relay = dict(Id=1, Port=self.puerto_relay, KcpConv=p.id & 0xFFFF, RelayId=p.id, Host=self.host, NetCode=0, InnerHost=self.host,
                           InnerPort=self.puerto_relay, TcpInnerPort=self.puerto_relay, TcpOuterPort=self.puerto_relay, UseRudp=False)
            self.difundir(p.jugadores(), 'NotifyOtherConfirmSelectStage', dict(Confirm=True, Side=j.lado, Pos=j.slots[0]), excepto=j)
            sesion.despues.append(('__estado__', p))
        return None
    def on_SyncLoadingProgressReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p:
            for pos in j.slots: p.miembros[j.lado][pos]['LoadingProgress'] = min(100, d.get('Progress', 0))
        return 'SyncLoadingProgressRsp', dict(LoadDone=d.get('Progress', 0) >= 100)
    def on_ReadyInMatchReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p:
            for pos in j.slots: p.miembros[j.lado][pos]['Ready'] = d.get('Ready', True)
            self.difundir(p.jugadores(), 'NotifyOtherReadyInMatch', dict(Ready=d.get('Ready', True), Side=j.lado, Pos=j.slots[0]), excepto=j)
            if all(x['Ready'] for x in p.todos_los_miembros()):
                p.fase = FIGHTING; sesion.despues.append(('__estado__', p))
        return None
    def on_BackToCharSelectReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p:
            p.fase = SELECTING_CHAR; p.escenario_confirmado = False
            for m in p.todos_los_miembros(): m.update(CharConfirmed=False, Ready=False, LoadingProgress=0)
            self.difundir(p.jugadores(), 'NotifyOtherBackToCharSelect', dict(Side=j.lado, Pos=j.slots[0]), excepto=j)
            sesion.despues.append(('__estado__', p))
        return 'BackToCharSelectRsp', dict()
    def guardar_resultado(self, p, ganador, r_izq, r_der, abandono=False):
        p.resultado = ganador
        modo_rank = p.modo_mm if p.modo_mm is not None and MODOS[p.modo_mm]['puntua'] else None
        nombre_modo = MODOS[p.modo_mm]['nombre'] if p.modo_mm is not None else 'Mesa %d' % p.mesa.id if p.mesa else 'Pelea'
        personajes = {str(m['Uid']) + ':' + str(m['Pos']): m['CharId'] for m in p.todos_los_miembros()}
        self.cuentas.registrar(nombre_modo + (' (abandono)' if abandono else ''), modo_rank, [x.uid for x in p.lados[LEFT]],
                               [x.uid for x in p.lados[RIGHT]], ganador, r_izq, r_der, personajes, p.escenario)
        for x in p.jugadores():
            x.cuenta = self.cuentas.get(x.uid)
        log.info('resultado pelea %d (%s): gana lado %s %d-%d%s', p.id, nombre_modo, ganador, r_izq, r_der, ' por abandono' if abandono else '')
    def on_UploadBattleResult(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p and p.resultado is None:
            self.guardar_resultado(p, d.get('WinnerSide', -1), d.get('LeftWinRound', 0), d.get('RightWinRound', 0))
            p.fase = END; self.estado_partida(p)
            for x in p.jugadores(): x.notificar('NotifyBasePlayerInfoChange', self.info_detallada(x.cuenta))
            mesa = p.mesa; self.cerrar_partida(p)
            if mesa:
                for q in mesa.jugadores(): q.notificar('GameHallState', self.estado_hall(q))
        return None
    def on_RefightReq(self, sesion, d):
        j = sesion.jugador
        if j.mesa: self.comprobar_mesa(j.mesa)
        return 'RefightRsp', dict(FightStarted=bool(j.mesa and j.mesa.partida))
    def on_RemoteFightDataReq(self, sesion, d): return 'RemoteFightDataRsp', dict()
