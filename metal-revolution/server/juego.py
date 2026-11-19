#!/usr/bin/env python3
"""Logica de juego: cuentas, hall y mesas, busqueda de rival (1v1, 2v2, 3v3), clasificatoria, equipos, chat, pelea y resultado.

Todo se expresa como diccionarios que el codec FlatBuffers (fb_codec) convierte a bytes.
Cada handler on_<Peticion>(sesion, datos) devuelve (TipoRespuesta, dict) o None (EmptyRsp).
Los avisos a otros jugadores se mandan con jugador.notificar(TipoAviso, dict)."""
import asyncio, copy, json, logging, os, random, sqlite3, time
from config_juego import ConfigJuego
from colaboradores import Colaboradores

log = logging.getLogger('mr.juego')
HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_JUEGO = '1.0.23'
NUM_MESAS = 8
LEFT, RIGHT, OBSERVER, AUTO = 0, 1, 2, 3                       # RoomPosType
WAITING_ALL_READY, SELECTING_CHAR, ORDERING_CHAR, SELECTING_STAGE, LOADING_FIGHT, FIGHTING, WAITING_RESULT, END = range(8)

# MatchMakingType (lo que pide el cliente al buscar) -> MatchType (el tipo de partida) y reglas
RANKING, RANKING_2V2, RANKING_NORMAL, RANKING_SOLO_3V3, QUICK_SOLO_3V3 = range(5)
MODOS = {
    # Clasificatoria 1v1 (boton 1v1 del panel de clasificatoria): igual que la rapida (personaje elegido antes de buscar,
    # ChangeFavCharReq con MatchMakingType 0) pero suma o resta puntos de clasificatoria.
    RANKING:          dict(nombre='Clasificatoria 1v1', match_type=0, por_lado=1, slots=1, puntua=True, directo=True),
    RANKING_2V2:      dict(nombre='Clasificatoria 2v2', match_type=7, por_lado=2, slots=1, puntua=True, pantalla_equipo=True),
    # Partida rapida: el juego NO muestra seleccion de personaje; usa el favorito elegido antes de buscar (ChangeFavCharReq)
    # y pasa directo a la carga. El servidor tiene que mandar ya el personaje de cada uno y el escenario.
    RANKING_NORMAL:   dict(nombre='Normal 1v1',         match_type=1, por_lado=1, slots=1, puntua=False, directo=True),
    # El boton "Clasificatoria" del menu abre el modo 3v3 en solitario (asi viene de fabrica en esta version):
    # cada jugador elige 3 personajes, los ordena y pelean por relevos.
    RANKING_SOLO_3V3: dict(nombre='Clasificatoria 3v3', match_type=8, por_lado=1, slots=3, puntua=True, pantalla_equipo=True),
    QUICK_SOLO_3V3:   dict(nombre='Rapida 3v3',         match_type=9, por_lado=1, slots=3, puntua=False, pantalla_equipo=True),
}
TIPOS_ONLINE = (0, 1, 5, 7, 8, 9)                               # MatchType de peleas contra personas (sin IA ni local)
TIPOS_CLASIFICATORIA = (0, 7, 8)
STATS_MAXIMOS = ('MaxRoundTime', 'MaxCombo')                    # en InBattleStats: estos se guardan como maximo, el resto se suma
try:
    MARCOS = [tuple(x) for x in json.load(open(os.path.join(HERE, '..', 'datos', 'marcos.json')))]   # (id, condicion, parametros)
except (OSError, ValueError):
    MARCOS = []
AVATARES = range(1, 19)                                         # PlayerHead.csv: un avatar por personaje
TIPOS_DE_PELEA = 11                                             # MatchType.COUNT
GAMEHALL = 5                                                    # MatchType de las mesas del hall
PUNTOS_INICIALES, PUNTOS_GANAR, PUNTOS_PERDER = 1000, 25, 20
MAX_REVANCHAS = 2                                               # revanchas seguidas con el mismo rival (fuera de la sala)
# Tutoriales que se dan por hechos en todas las cuentas. e3482f25 es la guia de entrenamiento que el juego lanza despues
# de la primera derrota: se metia encima de la pantalla de resultados del que pierde.
TUTORIALES_HECHOS = ('e3482f25-a92e-4215-b1b4-946e22c12c39',)
SEGUNDOS_ORDEN = 30                                             # tiempo para ordenar personajes (3v3 y 2v2)
ESCENARIOS = (1, 2, 3, 4)                                       # escenarios vistos en las peleas reales (para la partida rapida)
PERSONAJE_POR_DEFECTO = 5                                       # si alguien busca partida rapida sin haber elegido personaje
SEGUNDOS_RESCATE = 12                                           # sala: si un telefono no abre la pantalla de resultados
SEGUNDOS_RESULTADO = 10                                         # si un telefono no sube su resultado, se le manda igual tras este tiempo
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
          CREATE TABLE IF NOT EXISTS favoritos (uid INTEGER, modo INTEGER, personaje INTEGER, PRIMARY KEY (uid, modo));
          CREATE TABLE IF NOT EXISTS tutoriales (uid INTEGER, id TEXT, PRIMARY KEY (uid, id));
          CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha INTEGER, modo TEXT, ganador INTEGER,
            izquierda TEXT, derecha TEXT, rondas_izq INTEGER, rondas_der INTEGER, personajes TEXT, escenario INTEGER);''')
        cj = [r[1] for r in self.db.execute('PRAGMA table_info(jugadores)')]
        for col, defecto in (('cabeza', '1'), ('marco', '0'), ('elogios', '0'), ('rol', "''"), ('baneado_hasta', '0'),
                             ('silenciado_hasta', '0'), ('motivo', "''")):
            if col not in cj: self.db.execute(f'ALTER TABLE jugadores ADD COLUMN {col} DEFAULT {defecto}')
        # administracion: historial de chat, desbloqueos por jugador y ajustes globales (JSON)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS chat (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha INTEGER, uid INTEGER, nombre TEXT,
                                           canal TEXT, destino TEXT, texto TEXT);
          CREATE INDEX IF NOT EXISTS chat_uid ON chat(uid);
          CREATE TABLE IF NOT EXISTS desbloqueos (uid INTEGER, tipo TEXT, id INTEGER, permitido INTEGER, PRIMARY KEY (uid, tipo, id));
          CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT);''')
        # una fila por jugador, personaje y pelea; stats = las estadisticas que sube su telefono (InBattleStats)
        self.db.execute('CREATE TABLE IF NOT EXISTS registros (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, fecha INTEGER, '
                        'tipo INTEGER, heroe INTEGER, resultado INTEGER, stats TEXT)')
        self.db.execute('CREATE INDEX IF NOT EXISTS registros_uid ON registros(uid)')
        if not self.db.execute('SELECT 1 FROM registros LIMIT 1').fetchone():
            self._rellenar_registros()
        cols = [r[1] for r in self.db.execute('PRAGMA table_info(partidas)')]
        if 'modo' not in cols:   # base creada por la version anterior
            self.db.execute('ALTER TABLE partidas RENAME TO partidas_v1'); self.__init__(ruta); return
        self.db.commit()

    def _rellenar_registros(self):
        """Una sola vez: pasa las peleas guardadas antes (tabla partidas) al registro del perfil, sin estadisticas detalladas."""
        try: filas = self.db.execute('SELECT fecha, modo, ganador, izquierda, derecha, personajes FROM partidas ORDER BY id').fetchall()
        except sqlite3.Error: return
        tipos = {'Clasificatoria 1v1': 0, 'Normal 1v1': 1, 'Clasificatoria 2v2': 7, 'Clasificatoria 3v3': 8, 'Rapida 3v3': 9}
        n = 0
        for f in filas:
            modo = (f['modo'] or '').replace(' (abandono)', '')
            tipo = 5 if modo.startswith('Mesa') else tipos.get(modo)
            if tipo is None: continue
            try: lados = (json.loads(f['izquierda']), json.loads(f['derecha'])); pj = json.loads(f['personajes'] or '{}')
            except ValueError: continue
            for lado, uids in enumerate(lados):
                for uid in uids:
                    res = 2 if f['ganador'] not in (0, 1) else (1 if f['ganador'] == lado else 0)
                    for clave, heroe in pj.items():
                        if clave.split(':')[0] == str(uid):
                            self.db.execute('INSERT INTO registros(uid,fecha,tipo,heroe,resultado) VALUES(?,?,?,?,?)', (uid, f['fecha'], tipo, heroe, res)); n += 1
        if n: logging.getLogger('mr.juego').info('perfil: %d peleas antiguas pasadas al registro de estadisticas', n)

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

    def favorito(self, uid, modo):
        r = self.db.execute('SELECT personaje FROM favoritos WHERE uid=? AND modo=?', (uid, modo)).fetchone(); return r[0] if r else 0
    def poner_favorito(self, uid, modo, personaje):
        self.db.execute('INSERT OR REPLACE INTO favoritos VALUES(?,?,?)', (uid, modo, personaje)); self.db.commit()

    # ---- perfil: avatar, marco, me gusta y registro de peleas
    def poner(self, uid, columna, valor):
        assert columna in ('cabeza', 'marco')
        self.db.execute(f'UPDATE jugadores SET {columna}=? WHERE uid=?', (valor, uid)); self.db.commit()
    def elogiar(self, uid):
        self.db.execute('UPDATE jugadores SET elogios=elogios+1 WHERE uid=?', (uid,)); self.db.commit()
    def nuevo_registro(self, uid, tipo, heroe, resultado):
        c = self.db.execute('INSERT INTO registros(uid,fecha,tipo,heroe,resultado) VALUES(?,?,?,?,?)', (uid, int(time.time()), tipo, heroe, resultado))
        self.db.commit(); return c.lastrowid
    def stats_registro(self, fila, stats):
        self.db.execute('UPDATE registros SET stats=? WHERE id=?', (json.dumps(stats), fila)); self.db.commit()
    def registros(self, uid):
        return [dict(r) for r in self.db.execute('SELECT tipo, heroe, resultado, stats FROM registros WHERE uid=? ORDER BY id', (uid,))]

    # ---- administracion
    def ajuste(self, clave, defecto=None):
        r = self.db.execute('SELECT valor FROM ajustes WHERE clave=?', (clave,)).fetchone()
        return json.loads(r[0]) if r else defecto
    def poner_ajuste(self, clave, valor):
        self.db.execute('INSERT OR REPLACE INTO ajustes VALUES(?,?)', (clave, json.dumps(valor, ensure_ascii=False))); self.db.commit()
    def anotar_chat(self, uid, nombre, canal, destino, texto):
        self.db.execute('INSERT INTO chat(fecha,uid,nombre,canal,destino,texto) VALUES(?,?,?,?,?,?)',
                        (int(time.time()), uid, nombre, canal, str(destino or ''), texto)); self.db.commit()
    def buscar_chat(self, uid=None, texto=None, limite=500):
        q = 'SELECT * FROM chat WHERE 1=1'; a = []
        if uid: q += ' AND (uid=? OR destino=?)'; a += [uid, str(uid)]
        if texto: q += ' AND texto LIKE ?'; a.append('%' + texto + '%')
        return [dict(r) for r in self.db.execute(q + ' ORDER BY id DESC LIMIT ?', a + [limite])]
    def desbloqueos(self, uid):
        return {(r['tipo'], r['id']): bool(r['permitido']) for r in self.db.execute('SELECT * FROM desbloqueos WHERE uid=?', (uid,))}
    def poner_desbloqueo(self, uid, tipo, id_, permitido):
        if permitido is None: self.db.execute('DELETE FROM desbloqueos WHERE uid=? AND tipo=? AND id=?', (uid, tipo, id_))
        else: self.db.execute('INSERT OR REPLACE INTO desbloqueos VALUES(?,?,?,?)', (uid, tipo, id_, int(bool(permitido))))
        self.db.commit()
    def poner_campo(self, uid, campo, valor):
        assert campo in ('rol', 'baneado_hasta', 'silenciado_hasta', 'motivo', 'nombre', 'nivel', 'exp')
        self.db.execute(f'UPDATE jugadores SET {campo}=? WHERE uid=?', (valor, uid)); self.db.commit()
    def todos(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM jugadores ORDER BY ultimo_login DESC')]

    def tutoriales(self, uid):
        return [r[0] for r in self.db.execute('SELECT id FROM tutoriales WHERE uid=?', (uid,))]
    def terminar_tutorial(self, uid, id_):
        self.db.execute('INSERT OR IGNORE INTO tutoriales VALUES(?,?)', (uid, id_)); self.db.commit()

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
        self.ultima_pelea = None; self.cancelada_avisada = None          # (id, lado, pos) de su ultima pelea
        # El nivel que ve el telefono no cambia durante la sesion: subir de nivel justo al terminar una pelea dejaba
        # el telefono sin abrir la pantalla de resultados (paso en la sala). El nivel nuevo se ve al volver a entrar.
        self.nivel_sesion = cuenta['nivel']
    @property
    def nombre(self): return self.cuenta['nombre'] or 'Jugador%d' % (self.uid % 100000)
    def notificar(self, tipo, datos): self.sesion.enviar_notificacion(tipo, datos)

class Mesa:
    def __init__(self, id_):
        self.id = id_; self.titulo = 'Mesa %d' % id_; self.clave = 0; self.observable = True; self.ocultar_seleccion = False
        self.izq = None; self.der = None; self.observadores = []; self.partida = None; self.anfitrion = None
    def jugadores(self): return [p for p in (self.izq, self.der) if p] + self.observadores
    def completa(self): return self.izq is not None and self.der is not None
    def detalle(self, para=None):
        """Ficha de la mesa. Mientras solo hay un jugador sentado, a ESE jugador se le dice que los dos asientos estan
        libres: asi su telefono se queda en la sala de espera en vez de pasar solo a elegir personaje contra la maquina
        (que es lo que hace el juego original cuando te sientas sin rival)."""
        solo = para is not None and not self.completa() and para in (self.izq, self.der)
        return dict(RoomId=self.id, Title=self.titulo, DisplayTitle=self.titulo, HasPassword=bool(self.clave),
                    LeftPlayerId=self.izq.uid if self.izq and not solo else 0, RightPlayerId=self.der.uid if self.der and not solo else 0,
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
        self.rondas = (0, 0); self.revancha = set(); self.peleas = 0; self.revanchas = 0; self.puntos_antes = {}; self.puntos_despues = {}
        self.orden = {LEFT: 0, RIGHT: 0}; self.temporizador_orden = None
        self.datos_resultado = None; self.notificados = set(); self.temporizador_resultado = None
        self.pantalla_fin = set()                                       # telefonos que llegaron a la pantalla de resultados
        self.rondas_detalle = ([], [])                                  # resultado de cada ronda (lista de RoundResult por lado)
        self.miembros = {LEFT: [], RIGHT: []}
        for lado, jugadores in self.lados.items():
            pos = 0
            for j in jugadores:
                j.partida = self; j.lado = lado; j.slots = []; j.ultima_pelea = (id_, lado, pos)
                for _ in range(slots):
                    self.miembros[lado].append(self.miembro(j, lado, pos)); j.slots.append(pos); pos += 1
    @staticmethod
    def miembro(j, lado, pos):
        return dict(Uid=j.uid, CharId=0, RandomChar=False, CostumeId=0, AltColorIndex=0, CharConfirmed=False, InBattleStatus=0,
                    Ready=False, LoadingProgress=0, PendingSwitchOrderTeammateId=0, PvpPrefs=j.pvp_prefs, ShouldPunishForEarlyExit=False,
                    BattleEndStatus=0, Side=lado, Pos=pos, NetStatus=0, FakeWinPoint=0, AiControlledByUid=0, BePraisedCount=0)
    def en_curso(self): return self.resultado is None and self.fase in (LOADING_FIGHT, FIGHTING, WAITING_RESULT)
    def peleando(self): return self.resultado is None and self.fase in (FIGHTING, WAITING_RESULT)
    def orden_terminado(self, lado): return self.orden[lado] >= len(self.miembros[lado]) - 1
    def limpiar_resultado(self):
        self.resultado = None; self.datos_resultado = None; self.notificados = set(); self.rondas_detalle = ([], []); self.pantalla_fin = set()
        if self.temporizador_resultado: self.temporizador_resultado.cancel(); self.temporizador_resultado = None
    def volver_a_seleccion(self):
        self.fase = SELECTING_CHAR; self.escenario_confirmado = False; self.limpiar_resultado(); self.revancha.clear()
        self.orden = {LEFT: 0, RIGHT: 0}
        for m in self.todos_los_miembros(): m.update(CharConfirmed=False, Ready=False, LoadingProgress=0)
    def jugadores(self): return self.lados[LEFT] + self.lados[RIGHT]
    def todos_los_miembros(self): return self.miembros[LEFT] + self.miembros[RIGHT]
    def slot(self, j, d):
        """El miembro al que se refiere una peticion: por (Side, Pos) si es del jugador, si no su primer slot."""
        pos = d.get('Pos', None)
        if pos is not None and pos in j.slots and d.get('Side', j.lado) == j.lado: return self.miembros[j.lado][pos]
        return self.miembros[j.lado][j.slots[0]] if j.slots else None
    def estado(self):
        now = int(time.time())
        return dict(MatchType=self.match_type, MatchId=self.id, SubMatchId=0, Phase=self.fase, Version=VERSION_JUEGO,
                    LeftMembers=self.miembros[LEFT], RightMembers=self.miembros[RIGHT], StartTime=self.inicio, EndTime=0,
                    RandomSeed=self.seed, RefightRemainCount=99 if self.mesa else MAX_REVANCHAS, LeftWonCount=0, RightWonCount=0, StageId=self.escenario,
                    RandomStage=False, StageConfirmed=self.escenario_confirmado, StartSelectCharTime=now, StartOrderCharTime=now,
                    StartSelectStageTime=now, StartWaitingReadyTime=now, SelectCharMaxTime=60, SelectStageMaxTime=30,
                    WaitingReadyMaxTime=60, OrderCharMaxTime=SEGUNDOS_ORDEN, RelayServerInfo=self.relay, LeftOrderingIndex=0, RightOrderingIndex=0,
                    AllowSameCharInTeam=True, AllowSameCharInMatch=True, SkipReorderChar=True, SkipSelectStage=False)

# ----------------------------------------------------------------- juego
class Juego:
    PUBLICOS = {'LoginRequest', 'PlayerClientPing', 'QueryServerTimeReq', 'AnalyticsBeforeLoginReq'}

    def __init__(self, host, puerto, puerto_relay, plantilla_login, nombre_automatico=False):
        self.host = host; self.puerto = puerto; self.puerto_relay = puerto_relay; self.plantilla = plantilla_login
        self.nombre_automatico = nombre_automatico
        self.cuentas = Cuentas(os.path.join(HERE, 'cuentas.db'))
        self.colab = Colaboradores(self.cuentas.db)                  # marcos y skins de agradecimiento (colaboradores.json)
        self.conectados = {}                                         # uid -> Jugador
        self.mesas = {i: Mesa(i) for i in range(1, NUM_MESAS + 1)}
        self.partidas = {}; self._sig_partida = 1
        self.colas = {m: [] for m in MODOS}                          # modo -> [lista de grupos (listas de Jugador)]
        self.chat_hall = []                                          # ultimos mensajes del hall
        self.en_hall = []                                            # jugadores en el hall, en orden de llegada (Index)
        self.config = ConfigJuego()                                  # archivos de config que se reemplazan en los telefonos
        self.handlers = {n[3:]: getattr(self, n) for n in dir(self) if n.startswith('on_')}

    # ================================================================= utilidades
    def info_detallada(self, cuenta):
        pi = copy.deepcopy(self.plantilla['PlayerInfo']); uid = cuenta['uid']; j = self.conectados.get(uid)
        pi['BaseInfo'].update(Uid=uid, Name=cuenta['nombre'], Level=j.nivel_sesion if j else cuenta['nivel'], Exp=cuenta['exp'], RegisterTime=cuenta['creado'] or 0,
                              OnlineState=1 if j else 0, GameVersion=VERSION_JUEGO, ClientVersion=VERSION_JUEGO,
                              GameHallId=1 if j and j.hall else 0, HallRoomId=j.mesa.id if j and j.mesa else 0, TotalLoginDay=1)
        self.aplicar_permisos(cuenta, pi)
        pi['BaseInfo'].update(CurPlayerHead=cuenta.get('cabeza') or 1, CurHeadFrame=cuenta.get('marco') or 0,
                              BePraisedCount=cuenta.get('elogios') or 0, UnlockedHeadFrames=self.marcos_desbloqueados(cuenta))
        pi['Heroes'] = self.heroes(cuenta, pi['Heroes'])
        pi['BattleData'] = self.datos_batalla(cuenta)
        return pi

    def heroes(self, cuenta, base=None):
        """Personajes con las skins de cada jugador: las que permite el panel (catalogo, bloqueos, exclusivos y ajustes
        por jugador, ver aplicar_permisos) mas las de colaborador y regalos (colaboradores.py), y la skin que eligio
        para cada uno (UseSkinId)."""
        if base is None:
            pi = dict(Heroes=copy.deepcopy(self.plantilla['PlayerInfo'].get('Heroes', []))); self.aplicar_permisos(cuenta, pi); base = pi['Heroes']
        uid = cuenta['uid']; extra = self.colab.skins(uid); en_uso = self.colab.skins_en_uso(uid); out = []
        for h in copy.deepcopy(base):
            skins = sorted(set(h.get('UnlockedSkins') or []) | extra.get(h['Id'], set()))
            if skins: h['UnlockedSkins'] = skins
            usa = en_uso.get(h['Id'], 0)
            if usa in skins: h['UseSkinId'] = h['ShowSkinId'] = usa
            out.append(h)
        return out
    def skins_de(self, uid, heroe):
        c = self.cuentas.get(uid); h = next((x for x in self.heroes(c) if x['Id'] == heroe), None) if c else None
        return set(h.get('UnlockedSkins') or []) if h else set()

    def datos_batalla(self, cuenta, nivel=1):
        uid = cuenta['uid']; mm = []
        for modo in range(len(MODOS)):
            r = self.cuentas.rank(uid, modo)
            mm.append(dict(Happiness=0, RankPoint=r['puntos'], WinPoint=r['puntos'], MaxWinPoint=r['max_puntos'], ContinueRewardAiCount=0,
                           FavorHeroId=self.cuentas.favorito(uid, modo), ExitInBattleCountToday=0, ForbidMatchUntilTime=0))
        r = self.resumen(uid)
        total = r['tipos'].get('online') or dict(WinCount=0, TotalCount=0, ContinueWinCount=0, MaxContinueWinCount=0)
        vacio = dict(WinCount=0, TotalCount=0, ContinueWinCount=0, MaxContinueWinCount=0)
        # CommonBattleStats va indexada por MatchType (0..10). Al llegar el resultado, el telefono suma la pelea en
        # CommonBattleStats[BattleLog.Type]: con una lista mas corta (antes iba 1 solo elemento) lanza
        # ArgumentOutOfRangeException en PlayerBattleDataWrapper.ApplyLastBattleStats y NUNCA abre la pantalla de
        # resultados. Le paso en la sala (tipo 5); visto en el registro del telefono (adb logcat).
        comun = [r['tipos'].get(t) or dict(vacio) for t in range(TIPOS_DE_PELEA)]
        return dict(Uid=uid, DetailLevel=nivel, PreferNetCode=0, CommonBattleStats=comun, MatchMakingBattleStats=mm,
                    HeroBattleDatas=r['heroes'])

    # ================================================================= perfil
    def resumen(self, uid):
        """Todo lo del perfil calculado del registro de peleas: por tipo de pelea, por personaje y la temporada."""
        def racha(lista):
            act = mejor = 0
            for g in lista:
                act = act + 1 if g == 1 else 0; mejor = max(mejor, act)
            return act, mejor
        def bloque(lista):
            act, mejor = racha(lista)
            return dict(WinCount=sum(1 for g in lista if g == 1), TotalCount=len(lista), ContinueWinCount=act, MaxContinueWinCount=mejor)
        filas = self.cuentas.registros(uid)
        por_tipo, por_heroe, stats_heroe, online = {}, {}, {}, []
        for f in filas:
            por_tipo.setdefault(f['tipo'], []).append(f['resultado'])
            por_heroe.setdefault((f['heroe'], f['tipo']), []).append(f['resultado'])
            if f['tipo'] in TIPOS_ONLINE: online.append(f)
            if f['stats']:
                acc = stats_heroe.setdefault((f['heroe'], f['tipo']), {})
                for k, v in json.loads(f['stats']).items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        acc[k] = max(acc.get(k, 0), v) if k in STATS_MAXIMOS else acc.get(k, 0) + v
        tipos = {t: bloque(l) for t, l in por_tipo.items()}
        tipos['online'] = bloque([f['resultado'] for f in online])
        heroes = []
        for (h, t), l in sorted(por_heroe.items()):
            d = dict(HeroId=h, BattleMode=t, **bloque(l))
            st = stats_heroe.get((h, t))
            if st: d['InBattleStats'] = {k: (int(v) if k != 'MoveDistance' else float(v)) for k, v in st.items()}
            heroes.append(d)
        return dict(tipos=tipos, heroes=heroes, online=online)

    def temporada(self, uid):
        """PlayerSeasonData para la pestana de combate del perfil. Cada habilidad es un puntaje de 0 a 20 (lo que dibuja el
        radar) calculado de las estadisticas que suben los telefonos; Score es el total sobre 100."""
        online = self.resumen(uid)['online']
        def una(filas, indice=1):
            if not filas: return dict(Index=indice)
            st = {}
            for f in filas:
                for k, v in (json.loads(f['stats']) if f['stats'] else {}).items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool): st[k] = st.get(k, 0) + v
            con_stats = sum(1 for f in filas if f['stats']) or 1
            rondas = max(1, st.get('TotalRounds', 0)); tiempo = max(1, st.get('TotalRoundTime', 0))
            golpes = st.get('AllHitCastCount', 0); bloqueados = st.get('HitBeBlockedCount', 0) + st.get('HitBeParriedCount', 0)
            defensas = st.get('BlockCount', 0) + st.get('GroundParryCount', 0) + st.get('AirParryCount', 0) + st.get('TechThrowCount', 0)
            recibidos = st.get('BeHitConfirmCount', 0)
            tecnica = (st.get('WinByPerfectKo', 0) + st.get('CounterCount', 0) + st.get('CrossUpCount', 0) + st.get('ComboFinishCount', 0)
                       + st.get('WinByUltimate', 0) + st.get('ThrowHitConfirmedCount', 0)) / rondas
            tope = lambda x: round(max(0.0, min(20.0, x)), 2)
            dps = tope(st.get('TotalDamage', 0) / tiempo / 60 * 20)                  # ~60 de dano por segundo = 20
            mov = tope(st.get('MoveDistance', 0) / rondas / 100 * 20)
            combo = tope(st.get('TotalCombo', 0) / rondas / 25 * 20)
            ataque = tope((golpes - bloqueados) / golpes * 20 if golpes else 0)
            defensa = tope(defensas / (defensas + recibidos) * 20 if defensas + recibidos else 0)
            tec = tope(tecnica / 8 * 20)
            ganadas = sum(1 for f in filas if f['resultado'] == 1)
            clasif = [f for f in filas if f['tipo'] in TIPOS_CLASIFICATORIA]
            return dict(Index=indice, TopRate=0.0, Score=round((dps + mov + combo + ataque + defensa + tec) / 120 * 100, 1),
                        WinRate=ganadas / len(filas), WinRateRank=(sum(1 for f in clasif if f['resultado'] == 1) / len(clasif)) if clasif else 0.0,
                        Dps=dps, MoveDistance=mov, Combo=combo, AttackRate=ataque, TechniqueScore=tec, DefendRate=defensa,
                        MvpCount=0, AssistScore=0.0)
        return dict(SeasonDatas=[una([f for f in online if f['tipo'] != 7])], Season2v2Datas=[una([f for f in online if f['tipo'] == 7])])

    # ================================================================= permisos de heroes, skins y marcos
    def catalogo(self):
        """Todo lo que existe: heroes y sus skins (de la ficha de login + las agregadas a mano) y marcos (del juego + nuevos)."""
        heroes = {}
        for h in self.plantilla['PlayerInfo']['Heroes']:
            heroes[h['Id']] = sorted(set(h.get('UnlockedSkins') or []))
        for skin, heroe in (self.cuentas.ajuste('skins_extra', {}) or {}).items():
            heroes.setdefault(int(heroe), [])
            if int(skin) not in heroes[int(heroe)]: heroes[int(heroe)].append(int(skin))
        marcos = [dict(id=m, condicion=c, parametros=list(p)) for m, c, p in MARCOS]
        for m in self.cuentas.ajuste('marcos_extra', []) or []:
            if not any(x['id'] == m['id'] for x in marcos): marcos.append(dict(id=m['id'], condicion=99, parametros=[], nombre=m.get('nombre', '')))
        return dict(heroes=heroes, marcos=marcos, nombres=self.cuentas.ajuste('nombres_heroes', {}) or {},
                    bloqueados=self.cuentas.ajuste('bloqueados', {}) or {}, exclusivos=self.cuentas.ajuste('exclusivos', {}) or {})
    def permitido(self, cuenta, tipo, id_, por_defecto, cat=None, propios=None):
        """Orden: ajuste a mano del jugador > exclusivo de un rol (solo quien lo tiene) > bloqueado para todos > lo normal."""
        cat = cat or self.catalogo(); propios = self.cuentas.desbloqueos(cuenta['uid']) if propios is None else propios
        if (tipo, id_) in propios: return propios[(tipo, id_)]
        roles = {r for r in (cuenta.get('rol') or '').split(',') if r}
        exclusivo_de = [r for r, cosas in cat['exclusivos'].items() if id_ in (cosas.get(tipo) or [])]
        if exclusivo_de: return any(r in roles for r in exclusivo_de)
        if id_ in (cat['bloqueados'].get(tipo) or []): return False
        return por_defecto
    def aplicar_permisos(self, cuenta, pi):
        cat = self.catalogo(); propios = self.cuentas.desbloqueos(cuenta['uid'])
        presentes = {h['Id'] for h in pi['Heroes']}
        for (tipo, id_), ok in propios.items():                  # heroes dados a mano que no vienen en la ficha
            if tipo == 'heroe' and ok and id_ not in presentes:
                pi['Heroes'].append(dict(Id=id_, Unlock=True, UseSkinId=0, ShowSkinId=0, ExpireTime=0, ExpireCount=0)); presentes.add(id_)
        for h in pi['Heroes']:
            h['Unlock'] = self.permitido(cuenta, 'heroe', h['Id'], True, cat, propios)
            skins = [sk for sk in cat['heroes'].get(h['Id'], []) if self.permitido(cuenta, 'skin', sk, True, cat, propios)]
            h['UnlockedSkins'] = skins
            if h.get('UseSkinId') and h['UseSkinId'] not in skins: h['UseSkinId'] = 0; h['ShowSkinId'] = 0

    def marcos_desbloqueados(self, cuenta):
        """Marcos que se ganan jugando, segun las reglas del juego (HeadFrameConfig): 1 = puntos maximos de clasificatoria,
        2 = victorias con un personaje, 4 = nivel. Los de tipo 3 y 99 (objetos/especiales) quedan para torneos y
        colaboradores: no se desbloquean solos, se dan con colaboradores.py."""
        uid = cuenta['uid']; puntos = max(self.cuentas.rank(uid, m)['max_puntos'] for m in (RANKING, RANKING_SOLO_3V3))
        victorias = {}
        for f in self.cuentas.registros(uid):
            if f['resultado'] == 1 and f['tipo'] in TIPOS_ONLINE: victorias[f['heroe']] = victorias.get(f['heroe'], 0) + 1
        out = []; cat = self.catalogo(); propios = self.cuentas.desbloqueos(uid)
        for m in cat['marcos']:
            mid, cond, par = m['id'], m['condicion'], m['parametros']
            normal = bool((cond == 1 and par and puntos >= par[0]) or (cond == 2 and len(par) == 2 and victorias.get(par[0], 0) >= par[1])
                          or (cond == 4 and par and cuenta['nivel'] >= par[0]))
            if self.permitido(cuenta, 'marco', mid, normal, cat, propios): out.append(mid)
        # ademas, los de colaborador y regalos (colaboradores.py), si el marco existe en el juego o en el panel
        validos = {m['id'] for m in cat['marcos']}
        return sorted(set(out) | {m for m in self.colab.marcos(uid) if m in validos})

    def respuesta_login(self, cuenta):
        return 'LoginGameSvrRsp', dict(self.plantilla, PlayerInfo=self.info_detallada(cuenta), UtcTimeOffset=0, GameServerId=1, PayZoneId=0)

    def difundir_hall(self, tipo, datos, excepto=None):
        for p in list(self.conectados.values()):
            if p.hall and p is not excepto: p.notificar(tipo, datos)
    def difundir(self, jugadores, tipo, datos, excepto=None):
        for p in jugadores:
            if p is not excepto: p.notificar(tipo, datos)

    def detalle_hall(self):
        return dict(RoomNum=len(self.mesas), IsArena=False, Full=False, PlayerCount=sum(1 for p in self.conectados.values() if p.hall),
                    MinRoomId=1, MaxRoomId=len(self.mesas))
    def estado_hall(self, j):
        m = j.mesa
        return dict(HallId=1, RoomId=m.id if m else 0, HallInfo=self.detalle_hall(), RoomDetail=m.detalle(j) if m else None,
                    MatchState=self.estado_mesa(m) if m else None)
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
        if (cuenta.get('baneado_hasta') or 0) > time.time():
            hasta = time.strftime('%d/%m/%Y %H:%M', time.localtime(cuenta['baneado_hasta']))
            log.info('login rechazado: uid=%d %r suspendido hasta %s', cuenta['uid'], cuenta['nombre'], hasta)
            texto = 'Cuenta suspendida hasta %s. %s' % (hasta, cuenta.get('motivo') or '')
            return 'Error', dict(ErrCode=14, ErrMsg=texto, ErrMsgEn=texto)
        act = getattr(self, 'actualizaciones', None)
        bloqueo = act.bloquear_login(sesion.peer[0] if sesion.peer else '?') if act else None
        if bloqueo:                                                # actualizacion obligatoria pendiente
            log.info('login rechazado: uid=%d %r sin la actualizacion obligatoria', cuenta['uid'], cuenta['nombre'])
            return 'Error', dict(ErrCode=15, ErrMsg=bloqueo, ErrMsgEn=bloqueo)
        if not cuenta['nombre'] and self.nombre_automatico:
            self.cuentas.poner_nombre(cuenta['uid'], 'Jugador%d' % (cuenta['uid'] % 100000)); cuenta = self.cuentas.get(cuenta['uid'])
        viejo = self.conectados.get(cuenta['uid'])
        if viejo and viejo.sesion is not sesion:
            viejo.notificar('NotifyLoginByOther', dict(Param=dict(DeviceId=d.get('DeviceId', ''), ProcessId=0, DataVersion=0)))
            self.desconectar(viejo); viejo.sesion.jugador = None
        j = Jugador(sesion, cuenta); self.conectados[j.uid] = j; sesion.jugador = j
        log.info('login uid=%d nombre=%r (%s)', j.uid, cuenta['nombre'], 'pedira nombre' if not cuenta['nombre'] else 'ok')
        aviso = self.config.aviso()
        if aviso: sesion.despues.append(('NotifySvrConfigReload', aviso))   # el telefono pedira las configuraciones nuevas
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
    # ---- configuraciones que el servidor reemplaza (ver config_juego.py)
    def on_QueryAllConfigHashReq(self, sesion, d):
        return 'QueryAllConfigHashRsp', dict(HashPairs=self.config.pares())
    def on_DownloadConfigReq(self, sesion, d):
        contenido = self.config.contenido(d.get('Key', ''))
        if contenido is None:
            log.warning('el telefono pidio la configuracion %r, que no tengo', d.get('Key'))
            return 'Error', dict(ErrCode=11, ErrMsg='Configuracion no disponible', ErrMsgEn='Config not available')
        log.info('uid=%d descarga la configuracion %s', sesion.jugador.uid, d.get('Key'))
        return 'DownloadConfigRsp', dict(Content=contenido)
    # ---- tutoriales: se recuerda cuales termino cada cuenta (antes se contestaba siempre "ninguno" y volvian a salir)
    def on_QueryTrainingDataReq(self, sesion, d):
        hechos = sorted(set(TUTORIALES_HECHOS) | set(self.cuentas.tutoriales(sesion.jugador.uid)))
        return 'PlayerTrainingData', dict(TutorialFinishStates=[dict(Id=t, Finished=True) for t in hechos], LastTrainingCharId=0)
    def on_FinishTutorialReq(self, sesion, d):
        if d.get('Id') and d.get('Finish', True): self.cuentas.terminar_tutorial(sesion.jugador.uid, d['Id'])
        return None
    def on_NameCardCdReq(self, sesion, d): return 'NameCardCdRsp', dict(TimeLeft=0)
    def on_QueryRoleIdByNameReq(self, sesion, d):
        r = self.cuentas.db.execute('SELECT uid FROM jugadores WHERE lower(nombre)=lower(?)', (d.get('Name', ''),)).fetchone()
        return 'QueryRoleIdByNameRsp', dict(Name=d.get('Name', ''), SrcUid=sesion.jugador.uid, ResultUids=[r['uid']] if r else [])
    def on_QueryServerTimeReq(self, sesion, d): return 'QueryServerTimeRsp', dict(ServerTime=int(time.time()), TimeOffset=0, ServerTimeOffset=0)
    def on_PlayerClientPing(self, sesion, d): return 'PlayerClientPong', dict(Timestamp=d.get('Timestamp') or int(time.time() * 1000))
    def on_QueryPlayerInfoReq(self, sesion, d):
        c = self.cuentas.get(d.get('Uid', 0))
        if not c: return 'QueryPlayerInfoRsp', dict(Result=None)
        info = self.info_detallada(c)
        if d.get('QuerySeason'): info['SeasonInfo'] = self.temporada(c['uid'])     # perfil de OTRO jugador: su pestana de combate
        return 'QueryPlayerInfoRsp', dict(Result=info)

    # ---- perfil propio: temporada (pestana de combate), avatar, marco, me gusta
    def on_QuerySeasonInfoReq(self, sesion, d):
        return 'PlayerSeasonData', self.temporada(sesion.jugador.uid)
    def on_PlayerHeadReq(self, sesion, d):
        c = sesion.jugador.cuenta
        return 'PlayerHeadRsp', dict(CurrHead=c.get('cabeza') or 1, UnlockHead=[dict(Id=i, Read=1) for i in AVATARES])
    def on_PlayerHeadChangeReq(self, sesion, d):
        j = sesion.jugador; nuevo = d.get('Id', 1)
        if nuevo in AVATARES:
            self.cuentas.poner(j.uid, 'cabeza', nuevo); j.cuenta = self.cuentas.get(j.uid)
            log.info('%s cambia su avatar a %d', j.nombre, nuevo)
            sesion.despues.append(('NotifyBasePlayerInfoChange', self.info_detallada(j.cuenta)))
        return self.on_PlayerHeadReq(sesion, d)
    def on_PlayerHeadMarkRead(self, sesion, d): return None
    def on_ChangeHeadFrameReq(self, sesion, d):
        j = sesion.jugador; nuevo = d.get('HeadFrameId', 0)
        if nuevo and nuevo not in self.marcos_desbloqueados(j.cuenta):
            return 'Error', dict(ErrCode=13, ErrMsg='Ese marco todavia esta bloqueado', ErrMsgEn='Frame locked')
        self.cuentas.poner(j.uid, 'marco', nuevo); j.cuenta = self.cuentas.get(j.uid)
        log.info('%s cambia su marco a %d', j.nombre, nuevo)
        sesion.despues.append(('NotifyBasePlayerInfoChange', self.info_detallada(j.cuenta)))
        return None
    def on_ChangeHeroSkinReq(self, sesion, d):
        """Elegir skin en la pantalla del personaje. SkinId 0 = la de por defecto. Se guarda para el login y para la
        partida rapida, donde el servidor pone la skin (CostumeId = id de skin) porque no hay pantalla de seleccion."""
        j = sesion.jugador; heroe = d.get('HeroId', 0); skin = d.get('SkinId', 0)
        if skin and skin not in self.skins_de(j.uid, heroe):
            return 'Error', dict(ErrCode=13, ErrMsg='Esa skin todavia esta bloqueada', ErrMsgEn='Skin locked')
        self.colab.usar_skin(j.uid, heroe, skin); log.info('%s usa la skin %d con el personaje %d', j.nombre, skin, heroe)
        return None
    def on_PraiseOtherReq(self, sesion, d):
        j = sesion.jugador; destino = d.get('TargetUid', 0); c = self.cuentas.get(destino)
        if not c or destino == j.uid: return None
        self.cuentas.elogiar(destino); total = (c.get('elogios') or 0) + 1
        sesion.despues.append(('NotifyPraiseOther', dict(TargetUid=destino, BePraisedCount=total)))
        otro = self.conectados.get(destino)
        if otro: otro.notificar('NotifyBePraised', dict(FromUid=j.uid, FromName=j.nombre)); otro.cuenta = self.cuentas.get(destino)
        return None
    def on_BatchQueryPlayerInfoReq(self, sesion, d):
        return 'BatchQueryPlayerInfoRsp', dict(Result=[self.info_detallada(c) for c in (self.cuentas.get(u) for u in d.get('Uids', [])) if c])
    def on_QueryBattleDataReq(self, sesion, d):
        """Hay que devolver el mismo DetailLevel que se pide: si se devuelve uno menor, el telefono cree que los datos
        estan incompletos y los vuelve a pedir sin parar (bucle de cientos de peticiones por segundo)."""
        c = self.cuentas.get(d.get('Uid') or sesion.jugador.uid)
        return ('PlayerBattleData', self.datos_batalla(c, d.get('DetailLevel', 1))) if c else None
    def on_ChangeFavCharReq(self, sesion, d):
        j = sesion.jugador; modo = d.get('MatchMakingType', 0); personaje = d.get('CharId', 0)
        if self.cuentas.favorito(j.uid, modo) != personaje:
            self.cuentas.poner_favorito(j.uid, modo, personaje); log.info('%s: personaje favorito %d en modo %d', j.nombre, personaje, modo)
        return None
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
        self.marcar_pantalla_fin(sesion.jugador)          # la pantalla de resultados pide esto apenas se abre
        modo = d.get('RankType', 0) if d.get('RankType', 0) in MODOS else RANKING; uid = d.get('Uid') or sesion.jugador.uid
        return 'QueryPlayerRankRsp', dict(Rank=self.cuentas.posicion(uid, modo), Score=self.cuentas.rank(uid, modo)['puntos'])
    def on_QueryRankRewardTimeReq(self, sesion, d): return 'QueryRankRewardTimeRsp', dict(Time=int(time.time()) + 30 * 86400)

    # ================================================================= chat
    def silenciado(self, j, canal, destino, texto):
        """Anota el mensaje en el historial y dice si el jugador esta silenciado (entonces no se reparte)."""
        self.cuentas.anotar_chat(j.uid, j.nombre, canal, destino, texto)
        hasta = j.cuenta.get('silenciado_hasta') or 0
        if hasta > time.time():
            self.mensaje_sistema(j, 'Estas silenciado hasta %s' % time.strftime('%d/%m %H:%M', time.localtime(hasta))); return True
        return False
    def on_SendHallChatReq(self, sesion, d):
        j = sesion.jugador; texto = (d.get('Content') or '').strip()
        if texto.lower().startswith('/nombre '): self.renombrar(j, texto[8:]); return None
        if self.silenciado(j, 'hall', '', texto[:200]): return None
        msg = dict(Uid=j.uid, Content=texto[:200], Timestamp=int(time.time()))
        self.chat_hall = (self.chat_hall + [msg])[-50:]; self.difundir_hall('NotifyGameHallChat', msg); return None
    def on_QueryRecentChatReq(self, sesion, d):
        return 'QueryRecentChatRsp', dict(MsgType=0, ChatList=[dict(SenderUid=m['Uid'], TargetUid=0, Time=m['Timestamp'], Content=m['Content']) for m in self.chat_hall[-30:]])
    def on_SendRoomChatReq(self, sesion, d):
        j = sesion.jugador; texto = (d.get('Content') or '').strip()[:200]
        if texto.lower().startswith('/nombre '): self.renombrar(j, texto[8:]); return 'SendRoomChatRsp', dict(Content=texto)
        if self.silenciado(j, 'mesa', j.mesa.id if j.mesa else '', texto): return 'SendRoomChatRsp', dict(Content=texto)
        if j.mesa: self.difundir(j.mesa.jugadores(), 'NotifyGameHallRoomChat', dict(Uid=j.uid, Content=texto, Timestamp=int(time.time())), excepto=j)
        return 'SendRoomChatRsp', dict(Content=texto)
    def on_SendChatReq(self, sesion, d):
        j = sesion.jugador; dest = self.conectados.get(d.get('TargetUid', 0))
        rsp = dict(Req=d, SenderUid=j.uid, SenderName=j.nombre, SendTime=int(time.time()))
        if self.silenciado(j, 'privado', d.get('TargetUid', 0), str(d.get('Content') or d.get('Msg') or json.dumps(d, ensure_ascii=False))[:300]):
            return 'SendChatRsp', rsp
        if dest: dest.notificar('RecvChat', rsp)
        return 'SendChatRsp', rsp
    def on_ChatInMatchReq(self, sesion, d):
        j = sesion.jugador
        if self.silenciado(j, 'pelea', j.partida.id if j.partida else '', str(d.get('Content', ''))): return None
        if j.partida:
            self.difundir(j.partida.jugadores(), 'NotifyOtherChatInMatch', dict(Sender=j.uid, Content=d.get('Content', ''), MatchType=j.partida.match_type,
                          Range=d.get('Range', 0)), excepto=j)
        return None

    # ================================================================= hall y mesas
    def on_PlayerGetHallListReq(self, sesion, d):
        return 'PlayerGetHallListRsp', dict(HallList=[dict(RankMin=0, RankMax=99999, HallId=1, ServerId=1, Ip=self.host, Port=self.puerto,
                                                           Name='Sala Principal', Zone='', IsArena=False, StartTime=0, EndTime=0)])
    def on_EnterHallReq(self, sesion, d):
        j = sesion.jugador
        if j not in self.en_hall: self.en_hall.append(j)
        j.hall = 1
        self.difundir_hall('NotifyPlayerEnterHall', dict(Uid=j.uid, Index=self.en_hall.index(j)), excepto=j)
        return 'EnterHallRsp', self.detalle_hall()
    def on_ExitHallReq(self, sesion, d):
        j = sesion.jugador
        if j.mesa: self.salir_mesa(j)
        self.salir_hall(j); return None
    def salir_hall(self, j):
        if j in self.en_hall: self.en_hall.remove(j)
        if j.hall: j.hall = None; self.difundir_hall('NotifyPlayerExitHall', dict(Uid=j.uid), excepto=j)
    def on_QueryPlayerListInHallReq(self, sesion, d):
        """El cliente pide la lista por tramos [StartIndex, EndIndex], ambos incluidos, segun el Index de NotifyPlayerEnterHall."""
        ini = max(0, d.get('StartIndex', 0)); fin = d.get('EndIndex', ini)
        return 'QueryPlayerListInHallRsp', dict(OnlinePlayers=[p.uid for p in self.en_hall[ini:fin + 1]])
    def on_QueryRoomListInHallReq(self, sesion, d):
        ini = d.get('FromRoomId', 1) or 1; fin = d.get('ToRoomId', NUM_MESAS) or NUM_MESAS
        return 'QueryRoomListInHallRsp', dict(RoomInfos=[m.detalle(sesion.jugador) for m in self.mesas.values() if ini <= m.id <= fin])

    def sentar(self, j, mesa, pos):
        if pos == AUTO: pos = LEFT if mesa.izq is None else RIGHT if mesa.der is None else OBSERVER
        if pos == LEFT and mesa.izq not in (None, j) and mesa.der in (None, j): pos = RIGHT      # ese asiento ya esta tomado: el otro
        elif pos == RIGHT and mesa.der not in (None, j) and mesa.izq in (None, j): pos = LEFT
        if pos == LEFT and mesa.izq in (None, j): mesa.quitar(j); mesa.izq = j
        elif pos == RIGHT and mesa.der in (None, j): mesa.quitar(j); mesa.der = j
        else:
            pos = OBSERVER; mesa.quitar(j)
            if j not in mesa.observadores: mesa.observadores.append(j)
        if mesa.anfitrion is None and pos != OBSERVER: mesa.anfitrion = j
        j.asiento = pos; j.mesa = mesa; return pos

    def estado_espera(self, mesa):
        """Mesa sin pelea armada: lo mismo que respondia el servidor local del mod (un hueco vacio a la izquierda)."""
        vacio = dict(Uid=0, CharId=0, RandomChar=False, CostumeId=0, AltColorIndex=0, CharConfirmed=False, InBattleStatus=0, Ready=False,
                     LoadingProgress=0, PendingSwitchOrderTeammateId=0, ShouldPunishForEarlyExit=False, BattleEndStatus=0, Side=LEFT, Pos=0,
                     NetStatus=0, FakeWinPoint=0, AiControlledByUid=0, BePraisedCount=0)
        return dict(MatchType=GAMEHALL, MatchId=mesa.id, SubMatchId=0, Phase=WAITING_ALL_READY, Version=VERSION_JUEGO, LeftMembers=[vacio],
                    RightMembers=[], AllowSameCharInTeam=False, AllowSameCharInMatch=True, SkipReorderChar=True, SkipSelectStage=False)
    def estado_mesa(self, mesa):
        return mesa.partida.estado() if mesa.partida else self.estado_espera(mesa)
    def vista_mesa(self, mesa, j):
        """Lo que ve el jugador j de su mesa: ficha + estado de la pelea (o de la espera)."""
        return dict(RoomDetail=mesa.detalle(j), MatchState=self.estado_mesa(mesa))
    def avisar_hall_mesa(self, mesa):
        # Aqui va la ficha REAL (con el asiento del que espera ocupado), tambien para el que espera solo: asi su
        # telefono muestra su avatar en la sala de espera. Lo que lo mantiene ahi en vez de mandarlo a pelear contra la
        # maquina es el GameHallMatchCreated (vista_mesa), que sigue diciendole que los asientos estan libres.
        for p in list(self.conectados.values()):
            if p.hall: p.notificar('NotifyRoomDetailInfoUpdate', mesa.detalle())
    def avisar_mesa(self, mesa, excepto=None):
        """Recoloca a todos los que estan en la mesa (sala de espera, seleccion de personaje...) y actualiza la ficha en el hall."""
        for p in mesa.jugadores():
            if p is not excepto: p.notificar('NotifyGameHallMatchCreated', self.vista_mesa(mesa, p))
        self.avisar_hall_mesa(mesa)

    def tras_sentarse(self, j, mesa, pos):
        """Si con este jugador se completan los dos asientos, nace la pelea y los dos pasan A LA VEZ a elegir personaje.
        Si no, el jugador queda en la sala de espera hasta que llegue un rival."""
        if mesa.completa() and mesa.partida is None:
            p = self.crear_partida(GAMEHALL, [mesa.izq], [mesa.der], mesa=mesa)
            log.info('mesa %d: %s vs %s -> los dos a elegir personaje (pelea %d)', mesa.id, mesa.izq.nombre, mesa.der.nombre, p.id)
            self.avisar_mesa(mesa, excepto=j)
        else:
            if pos == OBSERVER:
                self.difundir(mesa.jugadores(), 'NotifyPlayerEnterHallRoom', dict(PlayerId=j.uid, RoomId=mesa.id, Pos=OBSERVER,
                              ObIndex=len(mesa.observadores) - 1, WasObserver=False), excepto=j)
            else:
                log.info('mesa %d: %s espera rival', mesa.id, j.nombre)
            self.avisar_hall_mesa(mesa)
        return 'GameHallMatchCreated', self.vista_mesa(mesa, j)

    def on_EnterHallRoomReq(self, sesion, d):
        j = sesion.jugador; mesa = self.mesas.get(d.get('RoomId', 0))
        if mesa is None: return 'Error', dict(ErrCode=3, ErrMsg='La mesa no existe', ErrMsgEn='Room not found')
        if mesa.clave and not mesa.jugadores(): mesa.reiniciar()
        if mesa.clave and d.get('Password', 0) != mesa.clave and j not in mesa.jugadores():
            return 'Error', dict(ErrCode=5, ErrMsg='Clave incorrecta', ErrMsgEn='Wrong password')
        if j.mesa and j.mesa is not mesa: self.salir_mesa(j)
        if j.partida and not j.mesa: self.abandonar_partida(j)
        self.cancelar_busqueda(j)
        j.pvp_prefs = d.get('PvpPrefs')
        if mesa.partida and j in mesa.partida.jugadores(): return 'GameHallMatchCreated', self.vista_mesa(mesa, j)
        pedido = d.get('Pos', AUTO)
        if mesa.partida and j not in mesa.partida.jugadores(): pedido = OBSERVER          # ya hay dos jugando: solo mirar
        pos = self.sentar(j, mesa, pedido)
        log.info('%s entra a la mesa %d (%s)', j.nombre, mesa.id, {LEFT: 'izquierda', RIGHT: 'derecha'}.get(pos, 'observa'))
        return self.tras_sentarse(j, mesa, pos)
    def on_ChallengeInRoomReq(self, sesion, d):
        j = sesion.jugador; mesa = j.mesa
        if not mesa: return 'Error', dict(ErrCode=4, ErrMsg='No estas en una mesa', ErrMsgEn='Not in a room')
        if mesa.partida and j not in mesa.partida.jugadores():
            return 'Error', dict(ErrCode=6, ErrMsg='Los dos asientos estan ocupados', ErrMsgEn='Both seats are taken')
        if mesa.partida: return 'GameHallMatchCreated', self.vista_mesa(mesa, j)
        pos = self.sentar(j, mesa, d.get('Pos', AUTO))
        log.info('%s pide asiento en la mesa %d (%s)', j.nombre, mesa.id, {LEFT: 'izquierda', RIGHT: 'derecha'}.get(pos, 'observa'))
        return self.tras_sentarse(j, mesa, pos)
    def on_SetRoomPasswordReq(self, sesion, d):
        j = sesion.jugador; mesa = j.mesa
        if mesa and mesa.anfitrion in (None, j):
            mesa.clave = d.get('Password', 0) or 0; mesa.observable = d.get('AllowOb', True)
            mesa.ocultar_seleccion = d.get('HideCharSelection', False); titulo = (d.get('Title') or '').strip()
            if titulo: mesa.titulo = titulo[:20]
            self.avisar_hall_mesa(mesa)
        return None
    def on_ExitHallRoomReq(self, sesion, d): self.salir_mesa(sesion.jugador); return None
    def on_QueryRoomObserverListReq(self, sesion, d):
        m = sesion.jugador.mesa
        return 'QueryRoomObserverListRsp', dict(Uids=[p.uid for p in m.observadores] if m else [])
    def salir_mesa(self, j, servidor=False):
        mesa = j.mesa
        if not mesa: return
        p = mesa.partida; jugaba = p is not None and j in p.jugadores(); en_pelea = jugaba and p.peleando()
        if en_pelea: self.abandonar_partida(j)                  # en plena pelea: pierde por abandono y al rival le sale el resultado
        elif jugaba and p.en_curso(): self.abandonar_partida(j) # cargando: se cancela (sin puntos) y el otro vuelve a la mesa
        elif jugaba: self.cerrar_partida(p)                     # eligiendo personaje o ya terminada: simplemente se deshace
        mesa.quitar(j); j.mesa = None; j.asiento = OBSERVER
        log.info('%s sale de la mesa %d', j.nombre, mesa.id)
        if not mesa.jugadores(): mesa.reiniciar()
        if jugaba and not en_pelea:
            self.avisar_mesa(mesa)                              # el que se queda vuelve a la sala de espera
        else:
            self.difundir(mesa.observadores if jugaba else mesa.jugadores(), 'NotifyPlayerExitHallRoom',
                          dict(PlayerId=j.uid, RoomId=mesa.id, ServerExit=servidor))
            self.avisar_hall_mesa(mesa)

    # ================================================================= busqueda de rival y equipos
    def on_StartSearchMatchReq(self, sesion, d):
        j = sesion.jugador; modo = d.get('MatchMakingType', RANKING)
        if modo not in MODOS: return 'Error', dict(ErrCode=7, ErrMsg='Modo no disponible', ErrMsgEn='Mode not available')
        if j.mesa: self.salir_mesa(j)
        if j.partida: self.abandonar_partida(j)                  # restos de una pelea anterior (terminada o a medio elegir)
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
            if cfg.get('directo'):
                # sin seleccion: cada uno pelea con su favorito de este modo, en un escenario al azar, directo a la carga
                for m in p.todos_los_miembros():
                    m.update(CharId=self.cuentas.favorito(m['Uid'], modo) or PERSONAJE_POR_DEFECTO, CharConfirmed=True)
                    skin = self.colab.skin_en_uso(m['Uid'], m['CharId'])
                    m['CostumeId'] = skin if skin in self.skins_de(m['Uid'], m['CharId']) else 0
                p.escenario = random.choice(ESCENARIOS); p.escenario_confirmado = True; p.fase = LOADING_FIGHT
                log.info('pelea %d: directo a la carga con personajes %s en el escenario %d', p.id,
                         [m['CharId'] for m in p.todos_los_miembros()], p.escenario)
            self.difundir(p.jugadores(), 'NotifySearchMatchRivalFound', dict(MatchState=p.estado()))
    def on_ExitMatchReq(self, sesion, d):
        j = sesion.jugador
        if j.buscando is not None: self.cancelar_busqueda(j); return None
        if j.partida and not j.mesa: self.abandonar_partida(j)   # en las mesas se sale con ExitHallRoomReq
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
    def info_relay(self, p):
        """Donde se juega la pelea: el relay UDP de este mismo servidor. NetCode 0 = rollback; UseRudp = canal fiable (KCP)."""
        return dict(Id=1, Port=self.puerto_relay, KcpConv=6666, RelayId=p.id, Host=self.host, NetCode=0, InnerHost=self.host,
                    InnerPort=self.puerto_relay, TcpInnerPort=self.puerto_relay, TcpOuterPort=self.puerto_relay, UseRudp=True)
    def crear_partida(self, match_type, izq, der, slots=1, mesa=None, modo_mm=None):
        p = Partida(self._sig_partida, match_type, izq, der, slots, mesa, modo_mm); self._sig_partida += 1
        p.relay = self.info_relay(p); self.partidas[p.id] = p
        if mesa: mesa.partida = p
        return p
    def cerrar_partida(self, p):
        if p.temporizador_orden: p.temporizador_orden.cancel(); p.temporizador_orden = None
        for j in p.jugadores():
            if j.partida is p: j.partida = None; j.lado = None; j.slots = []
        if p.mesa and p.mesa.partida is p: p.mesa.partida = None
        self.partidas.pop(p.id, None)
    def puestos_relay(self, match_id, lado, pos):
        """Todos los puestos que maneja el telefono que entro al relay con (lado, pos): en el 3v3 en solitario, sus 3."""
        # Probado con telefonos: marcar los inputs con los puestos 1 y 2 hace que el juego lance NullReferenceException en
        # RollbackNetCodeDriver.OnRecvRelayMsg con cada mensaje (no tiene lectores para esos puestos). Queda desactivado.
        return [pos]
    def jugadores_en_relay(self, match_id):
        """Cuantos telefonos deben conectarse al relay antes de dar la salida (lo consulta el hilo del relay)."""
        p = self.partidas.get(match_id); return len(p.jugadores()) if p else None
    def pelea_iniciada(self, match_id):
        p = self.partidas.get(match_id)
        if p and p.resultado is None:
            p.fase = FIGHTING; p.inicio = int(time.time()); log.info('pelea %d en marcha', p.id)
    def abandonar_partida(self, j):
        """El jugador se va (o se le cae la conexion). En plena pelea pierde; antes de pelear se cancela sin puntos."""
        p = j.partida
        if not p: return
        lado = j.lado; rival = RIGHT if lado == LEFT else LEFT; mesa = p.mesa
        if p.temporizador_orden: p.temporizador_orden.cancel(); p.temporizador_orden = None
        if p.peleando():
            for pos in j.slots: self.difundir(p.jugadores(), 'NotifyPlayerLeftInMatch', dict(Side=lado, Pos=pos), excepto=j)
            self.guardar_resultado(p, rival, 0, 0, abandono=True); self.avisar_resultado(p, excepto=j)
            self.cerrar_partida(p)
        elif p.resultado is None:
            self.difundir(p.jugadores(), 'NotifyMatchCancelled', dict(MatchId=p.id, Side=lado, Pos=j.slots[0] if j.slots else 0), excepto=j)
            log.info('pelea %d cancelada: %s se fue antes de empezar a pelear', p.id, j.nombre); self.cerrar_partida(p)
        else:                                                     # ya habia terminado: solo se desengancha
            if j in p.lados.get(lado, []): p.lados[lado].remove(j)
            j.partida = None; j.lado = None; j.slots = []
            if not p.jugadores() or mesa is None: self.cerrar_partida(p)

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
        """El telefono manda Confirm solo cuando es falso (en FlatBuffers lo que vale su valor por defecto no viaja):
        si no viene, es que confirma. Cuando todos confirmaron, cada telefono pasa solo a elegir escenario."""
        j = sesion.jugador; p = j.partida; m = p.slot(j, d) if p else None; confirma = bool(d.get('Confirm', True))
        if m:
            m['CharConfirmed'] = confirma
            if d.get('CharId'): m['CharId'] = d['CharId']
            self.difundir(p.jugadores(), 'NotifyOtherConfirmSelectChar', dict(Confirm=confirma, Side=m['Side'], Pos=m['Pos']), excepto=j)
            if p.fase in (WAITING_ALL_READY, SELECTING_CHAR) and all(x['CharConfirmed'] for x in p.todos_los_miembros()):
                elegidos = [[x['CharId'] for x in p.miembros[LEFT]], [x['CharId'] for x in p.miembros[RIGHT]]]
                if max(len(p.miembros[LEFT]), len(p.miembros[RIGHT])) > 1:
                    # Con varios personajes por lado (3v3, 2v2) el juego pasa a ORDENARLOS antes del escenario
                    p.fase = ORDERING_CHAR; p.orden = {LEFT: 0, RIGHT: 0}
                    log.info('pelea %d: personajes listos %s -> a ordenarlos', p.id, elegidos)
                    self.programar_fin_orden(p)
                elif p.modo_mm is not None and MODOS[p.modo_mm].get('pantalla_equipo'):
                    # Pantalla de equipo con un solo personaje: no hay nada que ordenar, pero esa pantalla espera el aviso
                    # NotifyFinishReorderChar para pasar al escenario.
                    p.fase = ORDERING_CHAR; log.info('pelea %d: personajes listos %s -> a elegir escenario', p.id, elegidos)
                    sesion.despues.append(('__orden__', p))
                else:
                    p.fase = SELECTING_STAGE; log.info('pelea %d: personajes listos %s -> a elegir escenario', p.id, elegidos)
        return 'ConfirmSelectCharRsp', dict(Confirm=confirma, Side=m['Side'] if m else 0, Pos=m['Pos'] if m else 0)

    # ----------------------------------------------------------------- orden de los personajes (3v3, 2v2)
    def on_ChangeCharOrderReq(self, sesion, d):
        """Fase de ordenar: el telefono va llenando el puesto OrderingIndex (0, 1, ...) con el personaje SrcPos.
        Hay que contestarle el puesto siguiente; el ultimo se completa solo. Al rival se le avisa del cambio para que
        vea el mismo orden. Cuando los dos lados terminaron, NotifyFinishReorderChar los manda a elegir escenario."""
        j = sesion.jugador; p = j.partida
        if not p or p.fase != ORDERING_CHAR: return 'ChangeCharOrderRsp', dict(OrderingIndex=0)
        lado = j.lado; miembros = p.miembros[lado]; n = len(miembros)
        companero = d.get('TargetTeammateId', 0)
        if companero and companero != j.uid:                     # 2v2: pedir al companero cambiar de puesto
            otro = next((x for x in p.lados[lado] if x.uid == companero), None)
            if otro: otro.notificar('NotifyOtherRequestChangeCharOrder', dict(SourceUid=j.uid, TargetUid=companero,
                                                                              SrcPos=d.get('SrcPos', 0), TargetPos=d.get('TargetPos', 0)))
            return 'ChangeCharOrderRsp', dict(OrderingIndex=p.orden[lado])
        src = d.get('SrcPos', 0); dst = d.get('TargetPos', 0)
        if dst != p.orden[lado] or not (0 <= src < n and 0 <= dst < n):
            log.info('pelea %d: %s pide orden %d->%d pero toca el puesto %d', p.id, j.nombre, src, dst, p.orden[lado])
            return 'ChangeCharOrderRsp', dict(OrderingIndex=p.orden[lado])
        if src != dst:
            a = next(x for x in miembros if x['Pos'] == src); b = next(x for x in miembros if x['Pos'] == dst)
            a['Pos'], b['Pos'] = dst, src; miembros.sort(key=lambda x: x['Pos'])
        p.orden[lado] = dst + 1
        if p.orden_terminado(lado): p.orden[lado] = n           # el ultimo puesto queda decidido solo
        log.info('pelea %d: %s pone el personaje %d en el puesto %d -> orden %s', p.id, j.nombre, src, dst, [x['CharId'] for x in miembros])
        # TargetUid = 0 significa "reordena sus propios personajes". Con TargetUid = el mismo jugador, el telefono del rival
        # lo toma como un pedido entre companeros que no aplica, NO cambia el orden y la pelea se desincroniza.
        self.difundir(p.jugadores(), 'NotifyOtherRequestChangeCharOrder', dict(SourceUid=j.uid, TargetUid=0, SrcPos=src, TargetPos=dst), excepto=j)
        if p.orden_terminado(LEFT) and p.orden_terminado(RIGHT): sesion.despues.append(('__orden__', p))
        # El telefono pone su OrderingIndex = el que le contestamos (sin autocompletar el ultimo puesto): hay que mandarle
        # el mismo que lleva el servidor, para que los dos vean la fase de orden terminada a la vez.
        return 'ChangeCharOrderRsp', dict(OrderingIndex=p.orden[lado])
    def on_AcceptChangeCharOrderReq(self, sesion, d):
        """2v2: el companero acepta intercambiar puestos."""
        j = sesion.jugador; p = j.partida; otro_uid = d.get('SourceTeammateId', 0)
        if p and p.fase == ORDERING_CHAR:
            ma = next((x for x in p.miembros[j.lado] if x['Uid'] == j.uid), None); mb = next((x for x in p.miembros[j.lado] if x['Uid'] == otro_uid), None)
            if ma and mb:
                ma['Pos'], mb['Pos'] = mb['Pos'], ma['Pos']; p.miembros[j.lado].sort(key=lambda x: x['Pos'])
                for x in p.jugadores():
                    if x.uid == otro_uid: x.slots = [mb['Pos']]
                j.slots = [ma['Pos']]
                self.difundir(p.jugadores(), 'NotifyOtherAcceptChangeCharOrder', dict(SourceUid=otro_uid, TargetUid=j.uid))
        return None
    def programar_fin_orden(self, p):
        """Por si alguien no termina de ordenar (o el telefono no lo pide), el servidor cierra la fase al acabar el tiempo."""
        try:
            p.temporizador_orden = asyncio.get_running_loop().call_later(SEGUNDOS_ORDEN + 3, self.terminar_orden, p, True)
        except RuntimeError:
            p.temporizador_orden = None
    def terminar_orden(self, p, por_tiempo=False):
        if p.temporizador_orden: p.temporizador_orden.cancel(); p.temporizador_orden = None
        if p.fase != ORDERING_CHAR or self.partidas.get(p.id) is not p: return
        p.fase = SELECTING_STAGE; p.orden = {LEFT: len(p.miembros[LEFT]), RIGHT: len(p.miembros[RIGHT])}
        log.info('pelea %d: orden terminado%s %s -> a elegir escenario', p.id, ' (por tiempo)' if por_tiempo else '',
                 [[x['CharId'] for x in p.miembros[LEFT]], [x['CharId'] for x in p.miembros[RIGHT]]])
        self.difundir(p.jugadores(), 'NotifyFinishReorderChar', dict())
    def on_SelectStageReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p:
            p.escenario = d.get('StageId', 1)
            self.difundir(p.jugadores(), 'NotifyOtherSelectStage', dict(StageId=p.escenario, Random=d.get('Random', False), Side=j.lado, Pos=j.slots[0]), excepto=j)
        return 'SelectStageRsp', dict(StageId=d.get('StageId', 1), Random=d.get('Random', False))
    def on_ConfirmSelectStageReq(self, sesion, d):
        """Basta con que uno confirme el escenario: todos pasan a la pantalla de carga."""
        j = sesion.jugador; p = j.partida; confirma = bool(d.get('Confirm', True))
        if p and confirma and not p.escenario_confirmado and p.resultado is None:
            p.escenario_confirmado = True; p.fase = LOADING_FIGHT; p.peleas += 1
            for m in p.todos_los_miembros(): m['LoadingProgress'] = 0
            log.info('pelea %d: escenario %d confirmado por %s -> cargando', p.id, p.escenario, j.nombre)
            self.difundir(p.jugadores(), 'NotifyOtherConfirmSelectStage', dict(Confirm=True, Side=j.lado, Pos=j.slots[0]), excepto=j)
        return 'ConfirmSelectStageRsp', dict(Confirm=confirma)
    def on_SyncLoadingProgressReq(self, sesion, d):
        j = sesion.jugador; p = j.partida; progreso = min(100, d.get('Progress', 0))
        if (p is None or p.fase == END) and j.ultima_pelea and j.cancelada_avisada != j.ultima_pelea[0]:
            mid, lado, pos = j.ultima_pelea; j.cancelada_avisada = mid
            log.info('%s carga otra vez la pelea %d, que ya termino: se la cancelo para que vuelva al menu', j.nombre, mid)
            sesion.despues.append(('NotifyMatchCancelled', dict(MatchId=mid, Side=lado, Pos=pos)))
            return 'SyncLoadingProgressRsp', dict(LoadDone=False)
        if p:
            m = p.slot(j, d)
            for pos in j.slots: p.miembros[j.lado][pos]['LoadingProgress'] = progreso
            self.difundir(p.jugadores(), 'NotifyOtherSyncLoadingProgress', dict(Progress=progreso, Side=m['Side'], Pos=m['Pos'], LoadDone=progreso >= 100), excepto=j)
        return 'SyncLoadingProgressRsp', dict(LoadDone=progreso >= 100)
    def on_ReadyInMatchReq(self, sesion, d):
        j = sesion.jugador; p = j.partida; listo = bool(d.get('Ready', True))
        if p:
            for pos in j.slots: p.miembros[j.lado][pos]['Ready'] = listo
            self.difundir(p.jugadores(), 'NotifyOtherReadyInMatch', dict(Ready=listo, Side=j.lado, Pos=j.slots[0]), excepto=j)
            if p.fase == WAITING_ALL_READY and all(x['Ready'] for x in p.todos_los_miembros()): p.fase = SELECTING_CHAR
        return None
    def on_BackToCharSelectReq(self, sesion, d):
        j = sesion.jugador; p = j.partida
        if p and p.lados[LEFT] and p.lados[RIGHT] and not p.en_curso():
            self.marcar_pantalla_fin(j); atascados = self.atascados(p, j)
            if p.fase != SELECTING_CHAR: log.info('pelea %d: %s pide volver a elegir personaje', p.id, j.nombre)
            p.volver_a_seleccion()
            self.difundir([x for x in p.jugadores() if x not in atascados], 'NotifyOtherBackToCharSelect', dict(Side=j.lado, Pos=j.slots[0]), excepto=j)
            for x in atascados: self.rescatar(p, x)
        elif not p and j.mesa: sesion.despues.append(('__mesa__', j.mesa))
        return 'BackToCharSelectRsp', dict()

    # ---- telefonos que se quedan pegados al terminar la pelea
    SIN_SENAL = {'PlayerClientPing', 'UploadBattleInputDataReq', 'UploadBattleResult', 'AnalyticsBeforeLoginReq'}
    def actividad(self, j, tipo):
        """Cualquier peticion de verdad despues del resultado = la pantalla de resultados de ese telefono funciona."""
        if tipo not in self.SIN_SENAL: self.marcar_pantalla_fin(j)
    def marcar_pantalla_fin(self, j):
        p = j and j.partida
        if p and p.datos_resultado is not None and j in p.notificados: p.pantalla_fin.add(j)
    def atascados(self, p, excepto=None):
        """En la sala: jugadores a los que les llego el resultado pero cuya pantalla de resultados nunca se abrio
        (el telefono no pidio nada mas). Les pasa sobre todo al que pierde."""
        if not p.mesa or p.datos_resultado is None: return []
        return [x for x in p.jugadores() if x is not excepto and x in p.notificados and x not in p.pantalla_fin]
    def rescate_mesa(self, p, pelea):
        """Sala: si pasado el plazo algun telefono sigue sin abrir la pantalla de resultados, los dos vuelven a elegir
        personaje (es la revancha que el telefono pegado no puede pedir)."""
        if self.partidas.get(p.id) is not p or p.peleas != pelea or p.fase != END or not p.mesa: return
        pegados = self.atascados(p)
        if not pegados: return
        log.info('pelea %d: %s sin pantalla de resultados tras %d s -> los dos a elegir personaje', p.id,
                 [x.nombre for x in pegados], SEGUNDOS_RESCATE)
        p.volver_a_seleccion()
        for x in p.jugadores(): x.notificar('NotifyGameHallMatchCreated', self.vista_mesa(p.mesa, x))
    def rescatar(self, p, x):
        """Se le vuelve a mandar la mesa entera (como al armarse la pelea): el telefono sale de donde quedo y pasa a la
        seleccion de personaje junto con el rival."""
        log.info('pelea %d: el telefono de %s no abrio la pantalla de resultados; lo paso a elegir personaje', p.id, x.nombre)
        x.notificar('NotifyGameHallMatchCreated', self.vista_mesa(p.mesa, x))

    # ----------------------------------------------------------------- resultado
    def guardar_resultado(self, p, ganador, r_izq, r_der, abandono=False):
        p.resultado = ganador; p.rondas = (r_izq, r_der); p.fase = END
        modo_rank = p.modo_mm if p.modo_mm is not None and MODOS[p.modo_mm]['puntua'] else None
        nombre_modo = MODOS[p.modo_mm]['nombre'] if p.modo_mm is not None else 'Mesa %d' % p.mesa.id if p.mesa else 'Pelea'
        personajes = {str(m['Uid']) + ':' + str(m['Pos']): m['CharId'] for m in p.todos_los_miembros()}
        modo_pts = p.modo_mm if p.modo_mm is not None else RANKING
        p.puntos_antes = {x.uid: self.cuentas.rank(x.uid, modo_pts)['puntos'] for x in p.jugadores()}
        self.cuentas.registrar(nombre_modo + (' (abandono)' if abandono else ''), modo_rank, [x.uid for x in p.lados[LEFT]],
                               [x.uid for x in p.lados[RIGHT]], ganador, r_izq, r_der, personajes, p.escenario)
        p.puntos_despues = {x.uid: self.cuentas.rank(x.uid, modo_pts)['puntos'] for x in p.jugadores()}
        p.filas = {}
        for x in p.jugadores():
            res = 2 if ganador not in (LEFT, RIGHT) else (1 if ganador == x.lado else 0)
            for pos in x.slots:
                m = p.miembros[x.lado][pos]
                fila = self.cuentas.nuevo_registro(x.uid, p.match_type, m['CharId'], res)
                p.filas.setdefault(x.uid, fila)                  # las estadisticas del telefono van en su primer personaje
        for x in p.jugadores():
            x.cuenta = self.cuentas.get(x.uid)
        log.info('RESULTADO pelea %d (%s): gana el lado %s, rondas %d-%d%s', p.id, nombre_modo,
                 {LEFT: 'izquierdo', RIGHT: 'derecho'}.get(ganador, 'ninguno (empate)'), r_izq, r_der, ' por abandono' if abandono else '')
    def resultado_batalla(self, p):
        """El aviso BattleResult que cierra la pelea en los telefonos (pantalla de victoria/derrota)."""
        ahora = int(time.time()); g = p.resultado if p.resultado in (LEFT, RIGHT) else -1
        def infos(lado):
            return [dict(PlayerId=m['Uid'], HeroId=m['CharId'], ReplayId='', WinPointBefore=p.puntos_antes.get(m['Uid'], PUNTOS_INICIALES),
                         WinPointAfter=p.puntos_despues.get(m['Uid'], PUNTOS_INICIALES), Rating=0, Side=lado, Pos=m['Pos']) for m in p.miembros[lado]]
        def cambios(lado):
            out = []
            for m in p.miembros[lado]:
                c = self.cuentas.get(m['Uid']) or {}; antes = p.puntos_antes.get(m['Uid'], PUNTOS_INICIALES); despues = p.puntos_despues.get(m['Uid'], antes)
                out.append(dict(Uid=m['Uid'], NetStatus=0, CoinChange=0, ExpChange=30 if g == lado else 10, WinPoint=despues, RankPoint=despues,
                                Happiness=0, BattleCount=c.get('partidas', 0), ContinueWin=0, BaseWinPointChange=despues - antes,
                                AdjustWinPointChange=0, ExitInBattleCountToday=0, ForbidMatchUntilTime=0, GamesvrId=1, PunishWinPoint=0))
            return out
        # OJO: la pantalla de resultados recorre TotalRounds rondas leyendo LeftRoundResults[i] y RightRoundResults[i];
        # si TotalRounds es mayor que esas listas, la pantalla falla y el juego se queda en la imagen del ganador.
        izq, der = p.rondas_detalle; total = min(len(izq), len(der))
        registro = dict(Id='%d-%d' % (p.id, p.peleas), Type=p.match_type, StartTime=p.inicio, EndTime=ahora, WinnerSide=g, WinSideLastPlayerIndex=0,
                        LeftWinRound=p.rondas[0], RightWinRound=p.rondas[1], Stage=p.escenario, Unsynced=False, Interrupted=False,
                        Version=VERSION_JUEGO, AiType=-1, LeftPlayerInfos=infos(LEFT), RightPlayerInfos=infos(RIGHT), TotalRounds=total,
                        LeftRoundResults=izq[:total], RightRoundResults=der[:total])
        return dict(LastBattleLog=registro, LeftPlayerChanges=cambios(LEFT), RightPlayerChanges=cambios(RIGHT), MatchId=p.id, SubMatchId=0 if p.mesa else p.revanchas + 1,
                    SaveBattleLogOnGamesvrId=1)
    def enviar_resultado(self, p, x):
        """BattleResult a un jugador, una sola vez por pelea."""
        if x in p.notificados or p.datos_resultado is None: return
        p.notificados.add(x); x.notificar('BattleResult', p.datos_resultado); x.notificar('NotifyBasePlayerInfoChange', self.info_detallada(x.cuenta))
    def avisar_resultado(self, p, excepto=None):
        if p.datos_resultado is None: p.datos_resultado = self.resultado_batalla(p)
        for x in p.jugadores():
            if x is not excepto: self.enviar_resultado(p, x)
    def resultado_pendiente(self, p):
        """Pasado el plazo, el resultado se manda tambien a quien no subio el suyo (se colgo, cerro el juego...)."""
        p.temporizador_resultado = None
        faltan = [x for x in p.jugadores() if x not in p.notificados]
        if faltan: log.info('pelea %d: %s no subio su resultado; se le manda igual', p.id, [x.nombre for x in faltan])
        for x in faltan: self.enviar_resultado(p, x)
    def on_UploadBattleResult(self, sesion, d):
        """Cada telefono sube su resultado al terminar la pelea; vale el primero que llega.
        OJO: a cada telefono se le manda BattleResult solo DESPUES de que el mismo sube el suyo. Si le llega antes (cuando
        aun no termina de mostrar la pelea), lo descarta y luego se queda para siempre en 'esperando resultado'."""
        j = sesion.jugador; p = j.partida
        ganador = d.get('WinnerSide', -1); rondas = (d.get('LeftWinRound', 0), d.get('RightWinRound', 0))
        if not p or p.fase < LOADING_FIGHT: return None
        primero = p.resultado is None
        if primero:
            p.rondas_detalle = (list(d.get('LeftRoundResults') or []), list(d.get('RightRoundResults') or []))
            self.guardar_resultado(p, ganador, rondas[0], rondas[1]); p.datos_resultado = self.resultado_batalla(p)
            # (en la sala NO se manda NotifyRoomDetailInfoUpdate aqui: los asientos no cambian y, si le llega al telefono
            #  justo antes del resultado, se queda en la imagen del ganador sin revancha ni salir)
            try:
                p.temporizador_resultado = asyncio.get_running_loop().call_later(SEGUNDOS_RESULTADO, self.resultado_pendiente, p)
                if p.mesa: asyncio.get_running_loop().call_later(SEGUNDOS_RESCATE, self.rescate_mesa, p, p.peleas)
            except RuntimeError: pass
        if d.get('BattleStats') and getattr(p, 'filas', {}).get(j.uid):
            self.cuentas.stats_registro(p.filas[j.uid], d['BattleStats'])
        if primero: pass
        elif (p.resultado, p.rondas) != (ganador if ganador in (LEFT, RIGHT) else p.resultado, rondas):
            log.warning('pelea %d: %s subio un resultado distinto (lado %s, %s) al registrado (lado %s, %s): posible desincronizacion',
                        p.id, j.nombre, ganador, rondas, p.resultado, p.rondas)
        else:
            log.info('pelea %d: %s confirma el mismo resultado', p.id, j.nombre)
        self.enviar_resultado(p, j)
        return None
    def on_RefightReq(self, sesion, d):
        """Revancha directa con los mismos personajes: arranca cuando los dos la piden."""
        j = sesion.jugador; p = j.partida
        if not p or not (p.lados[LEFT] and p.lados[RIGHT]) or p.en_curso():
            if not p and j.mesa: sesion.despues.append(('__mesa__', j.mesa))      # el rival ya se fue: de vuelta a la sala de espera
            return 'RefightRsp', dict(FightStarted=False)
        self.marcar_pantalla_fin(j); atascados = self.atascados(p, j)
        if atascados:
            # el rival no puede aceptar (su telefono quedo pegado): en vez de esperar para siempre, los dos a elegir personaje
            log.info('pelea %d: %s pide revancha pero el rival no puede contestar -> los dos a elegir personaje', p.id, j.nombre)
            p.volver_a_seleccion()
            otro = atascados[0]
            j.notificar('NotifyOtherBackToCharSelect', dict(Side=otro.lado, Pos=otro.slots[0] if otro.slots else 0))
            for x in atascados: self.rescatar(p, x)
            return 'RefightRsp', dict(FightStarted=False)
        if not p.mesa and p.revanchas >= MAX_REVANCHAS:
            log.info('pelea %d: %s pide revancha pero ya se jugaron las %d', p.id, j.nombre, MAX_REVANCHAS)
            return 'Error', dict(ErrCode=12, ErrMsg='Ya no quedan revanchas con este rival', ErrMsgEn='No rematches left')
        p.revancha.add(j); todos = all(x in p.revancha for x in p.jugadores())
        self.difundir(p.jugadores(), 'NotifyOtherRequestRefight', dict(FightStarted=todos, Side=j.lado, Pos=j.slots[0]), excepto=j)
        if todos:
            p.limpiar_resultado(); p.fase = LOADING_FIGHT; p.revancha.clear(); p.peleas += 1; p.revanchas += 1
            for m in p.todos_los_miembros(): m['LoadingProgress'] = 0
            log.info('pelea %d: revancha aceptada por todos', p.id)
        return 'RefightRsp', dict(FightStarted=todos)
    def on_RemoteFightDataReq(self, sesion, d): return 'RemoteFightDataRsp', dict()
