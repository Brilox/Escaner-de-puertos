#!/usr/bin/env python3
"""Canal de administracion del servidor: una API HTTP con JSON que usa el Panel de administracion (tools/admin).

Corre dentro del mismo bucle asyncio que el juego (sin hilos: no hace falta bloquear nada) y exige la clave de
administracion en la cabecera X-Clave. La clave se genera la primera vez en server/clave_admin.txt.

Por defecto solo escucha en 127.0.0.1 (el mismo PC). En un VPS se usa con un tunel SSH:
    ssh -L 8090:127.0.0.1:8090 usuario@IP-del-VPS
y el panel se conecta a http://127.0.0.1:8090 como si fuera local."""
import asyncio, json, logging, os, secrets, shutil, time
from urllib.parse import parse_qs, urlsplit, unquote

from config_juego import ConfigJuego, CARPETA as CARPETA_ACTIVOS

log = logging.getLogger('mr.admin')
HERE = os.path.dirname(os.path.abspath(__file__))
CARPETAS_CONFIG = {'activos': CARPETA_ACTIVOS, 'en_espera': os.path.join(HERE, 'config_juego', 'en_espera')}
INICIO = time.time()


def clave_admin():
    ruta = os.path.join(HERE, 'clave_admin.txt')
    if not os.path.exists(ruta):
        open(ruta, 'w').write(secrets.token_urlsafe(18) + '\n')
        log.info('clave de administracion nueva guardada en %s', ruta)
    return open(ruta).read().strip()


class Admin:
    def __init__(self, juego):
        self.juego = juego; self.cuentas = juego.cuentas; self.clave = clave_admin()

    # ------------------------------------------------------------------ HTTP minimo
    async def atender(self, reader, writer):
        try:
            cabecera = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
            lineas = cabecera.decode('latin-1').split('\r\n')
            metodo, ruta, _ = lineas[0].split(' ', 2)
            h = {k.strip().lower(): v.strip() for k, v in (l.split(':', 1) for l in lineas[1:] if ':' in l)}
            n = int(h.get('content-length', 0) or 0)
            cuerpo = json.loads((await reader.readexactly(n)).decode('utf-8')) if n else {}
            if not secrets.compare_digest(h.get('x-clave', ''), self.clave):
                codigo, datos = 401, dict(error='Clave de administracion incorrecta')
            else:
                u = urlsplit(ruta); q = {k: v[-1] for k, v in parse_qs(u.query).items()}
                codigo, datos = 200, self.ruta(metodo, [unquote(x) for x in u.path.strip('/').split('/')], q, cuerpo)
        except KeyError as e:
            codigo, datos = 404, dict(error='No existe: %s' % e)
        except (ValueError, AssertionError) as e:
            codigo, datos = 400, dict(error=str(e))
        except Exception as e:
            log.exception('error en la API de administracion'); codigo, datos = 500, dict(error=repr(e))
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode('utf-8')
        writer.write(b'HTTP/1.1 %d OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: %d\r\nConnection: close\r\n\r\n'
                     % (codigo, len(cuerpo)) + cuerpo)
        try: await writer.drain(); writer.close()
        except Exception: pass

    def ruta(self, metodo, partes, q, c):
        assert partes and partes[0] == 'api', 'ruta invalida'
        p = partes[1:] + ['', '', '']
        if p[0] == 'estado': return self.estado()
        if p[0] == 'jugadores': return self.jugadores(q.get('filtro', ''))
        if p[0] == 'jugador' and metodo == 'GET': return self.jugador(int(p[1]))
        if p[0] == 'jugador' and p[2] == 'accion': return self.accion(int(p[1]), c)
        if p[0] == 'jugador' and p[2] == 'desbloqueo':
            self.cuentas.poner_desbloqueo(int(p[1]), c['tipo'], int(c['id']), c.get('permitido')); self.refrescar(int(p[1]))
            return dict(ok=True)
        if p[0] == 'chat': return self.cuentas.buscar_chat(int(q['uid']) if q.get('uid') else None, q.get('texto'), int(q.get('limite', 500)))
        if p[0] == 'catalogo' and metodo == 'GET': return self.juego.catalogo()
        if p[0] == 'catalogo': return self.catalogo(c)
        if p[0] == 'ajustes' and metodo == 'GET': return self.cuentas.ajuste(p[1], None) if p[1] else self.todos_ajustes()
        if p[0] == 'ajustes': self.cuentas.poner_ajuste(p[1], c['valor']); return dict(ok=True)
        if p[0] == 'config': return self.config(metodo, p, c)
        if p[0] == 'anuncio': return self.anuncio(c['texto'])
        raise KeyError('/'.join(partes))

    # ------------------------------------------------------------------ estado y jugadores
    def estado(self):
        j = self.juego
        return dict(en_linea=len(j.conectados), cuentas=len(self.cuentas.todos()), en_el_salon=sum(1 for x in j.conectados.values() if x.hall),
                    peleas_activas=len(j.partidas), buscando=sum(len(c) for c in j.colas.values()),
                    mesas=[dict(id=m.id, izquierda=m.izq.nombre if m.izq else '', derecha=m.der.nombre if m.der else '',
                                observadores=len(m.observadores), peleando=bool(m.partida)) for m in j.mesas.values()],
                    configuraciones=[n for n, _, _ in j.config.archivos.values()], encendido_desde=int(INICIO))

    def jugadores(self, filtro=''):
        out = []; ahora = time.time()
        for c in self.cuentas.todos():
            if filtro and filtro.lower() not in (c['nombre'] or '').lower() and filtro != str(c['uid']): continue
            out.append(dict(uid=c['uid'], nombre=c['nombre'], en_linea=c['uid'] in self.juego.conectados, nivel=c['nivel'],
                            victorias=c['victorias'], partidas=c['partidas'], rol=c.get('rol') or '', ultimo_login=c['ultimo_login'],
                            creado=c['creado'], suspendido=(c.get('baneado_hasta') or 0) > ahora, silenciado=(c.get('silenciado_hasta') or 0) > ahora))
        return out

    def jugador(self, uid):
        c = self.cuentas.get(uid)
        if not c: raise KeyError(uid)
        r = self.juego.resumen(uid)
        return dict(cuenta=c, en_linea=uid in self.juego.conectados, por_tipo=r['tipos'], heroes=r['heroes'],
                    temporada=self.juego.temporada(uid), marcos=self.juego.marcos_desbloqueados(c),
                    desbloqueos=[dict(tipo=t, id=i, permitido=v) for (t, i), v in self.cuentas.desbloqueos(uid).items()],
                    clasificatoria=self.cuentas.rank(uid, 0), chat=self.cuentas.buscar_chat(uid, None, 100))

    def accion(self, uid, c):
        a = c['accion']; ahora = int(time.time()); horas = float(c.get('horas') or 0)
        hasta = ahora + int(horas * 3600) if horas > 0 else ahora + 100 * 365 * 86400      # sin horas = permanente
        j = self.juego.conectados.get(uid)
        if a == 'suspender':
            self.cuentas.poner_campo(uid, 'baneado_hasta', hasta); self.cuentas.poner_campo(uid, 'motivo', c.get('motivo', ''))
            if j: self.juego.mensaje_sistema(j, 'Tu cuenta fue suspendida. %s' % c.get('motivo', '')); self.expulsar(j)
        elif a == 'quitar_suspension': self.cuentas.poner_campo(uid, 'baneado_hasta', 0)
        elif a == 'silenciar':
            self.cuentas.poner_campo(uid, 'silenciado_hasta', hasta)
            if j: self.juego.mensaje_sistema(j, 'Fuiste silenciado en el chat. %s' % c.get('motivo', ''))
        elif a == 'quitar_silencio': self.cuentas.poner_campo(uid, 'silenciado_hasta', 0)
        elif a == 'expulsar':
            if j: self.juego.mensaje_sistema(j, 'Fuiste expulsado del servidor. %s' % c.get('motivo', '')); self.expulsar(j)
        elif a == 'renombrar':
            err = self.cuentas.poner_nombre(uid, c['nombre'])
            if err: raise ValueError(err)
        elif a == 'rol': self.cuentas.poner_campo(uid, 'rol', ','.join(sorted({r.strip() for r in c.get('rol', '').split(',') if r.strip()})))
        elif a == 'mensaje':
            if not j: raise ValueError('El jugador no esta conectado')
            self.juego.mensaje_sistema(j, '[Admin] ' + c['texto'])
        else: raise ValueError('accion desconocida: %s' % a)
        log.info('admin: %s a uid=%d %s', a, uid, {k: v for k, v in c.items() if k != 'accion'})
        self.refrescar(uid)
        return dict(ok=True)

    def expulsar(self, j):
        try: j.sesion.writer.close()
        except Exception: pass

    def refrescar(self, uid):
        """Vuelve a mandar la ficha al jugador conectado (se ven al momento sus heroes, skins, marcos y nombre)."""
        j = self.juego.conectados.get(uid)
        if j:
            j.cuenta = self.cuentas.get(uid)
            j.notificar('NotifyBasePlayerInfoChange', self.juego.info_detallada(j.cuenta))

    # ------------------------------------------------------------------ catalogo, ajustes, configuraciones
    def catalogo(self, c):
        """c: {tipo: heroe|skin|marco, id, bloqueado: bool} o {exclusivo: rol, tipo, id, activo: bool}
           o {nuevo_marco: id, nombre} o {nueva_skin: id, heroe} o {nombre_heroe: id, nombre}."""
        if 'nombre_heroe' in c:
            n = self.cuentas.ajuste('nombres_heroes', {}) or {}; n[str(c['nombre_heroe'])] = c['nombre']
            self.cuentas.poner_ajuste('nombres_heroes', n); return dict(ok=True)
        if 'nuevo_marco' in c:
            m = self.cuentas.ajuste('marcos_extra', []) or []
            m = [x for x in m if x['id'] != int(c['nuevo_marco'])] + [dict(id=int(c['nuevo_marco']), nombre=c.get('nombre', ''))]
            self.cuentas.poner_ajuste('marcos_extra', m); return dict(ok=True)
        if 'nueva_skin' in c:
            s = self.cuentas.ajuste('skins_extra', {}) or {}; s[str(int(c['nueva_skin']))] = int(c['heroe'])
            self.cuentas.poner_ajuste('skins_extra', s); return dict(ok=True)
        tipo, id_ = c['tipo'], int(c['id']); assert tipo in ('heroe', 'skin', 'marco'), 'tipo invalido'
        if 'exclusivo' in c:
            ex = self.cuentas.ajuste('exclusivos', {}) or {}; lista = ex.setdefault(c['exclusivo'], {}).setdefault(tipo, [])
            if c.get('activo') and id_ not in lista: lista.append(id_)
            if not c.get('activo') and id_ in lista: lista.remove(id_)
            self.cuentas.poner_ajuste('exclusivos', ex)
        else:
            bl = self.cuentas.ajuste('bloqueados', {}) or {}; lista = bl.setdefault(tipo, [])
            if c.get('bloqueado') and id_ not in lista: lista.append(id_)
            if not c.get('bloqueado') and id_ in lista: lista.remove(id_)
            self.cuentas.poner_ajuste('bloqueados', bl)
        for uid in list(self.juego.conectados): self.refrescar(uid)
        return dict(ok=True)

    def todos_ajustes(self):
        return {r['clave']: json.loads(r['valor']) for r in self.cuentas.db.execute('SELECT * FROM ajustes')}

    def config(self, metodo, p, c):
        """/api/config -> lista; GET /api/config/<carpeta>/<archivo> -> texto; POST guardar | mover | recargar | borrar."""
        if not p[1]:
            if metodo == 'POST' and c.get('recargar'):
                self.juego.config = ConfigJuego(); return dict(ok=True, activos=[n for n, _, _ in self.juego.config.archivos.values()])
            return {k: sorted(f for f in os.listdir(v) if not f.startswith(('.', '_')) and f.lower() != 'readme.md') if os.path.isdir(v) else []
                    for k, v in CARPETAS_CONFIG.items()}
        carpeta = CARPETAS_CONFIG[p[1]]; nombre = os.path.basename(p[2]); assert nombre, 'falta el archivo'
        ruta = os.path.join(carpeta, nombre)
        if metodo == 'GET': return dict(nombre=nombre, texto=open(ruta, encoding='utf-8-sig', errors='replace').read())
        if c.get('accion') == 'guardar':
            os.makedirs(carpeta, exist_ok=True); open(ruta, 'w', encoding='utf-8').write(c['texto'])
        elif c.get('accion') == 'mover':
            destino = CARPETAS_CONFIG[c['a']]; os.makedirs(destino, exist_ok=True); shutil.move(ruta, os.path.join(destino, nombre))
        elif c.get('accion') == 'borrar': os.remove(ruta)
        else: raise ValueError('accion de configuracion desconocida')
        self.juego.config = ConfigJuego()
        log.info('admin: configuracion %s %s/%s', c.get('accion'), p[1], nombre)
        return dict(ok=True, activos=[n for n, _, _ in self.juego.config.archivos.values()])

    def anuncio(self, texto):
        for j in list(self.juego.conectados.values()): self.juego.mensaje_sistema(j, '[Anuncio] ' + texto)
        log.info('admin: anuncio a %d jugadores: %s', len(self.juego.conectados), texto)
        return dict(ok=True, enviados=len(self.juego.conectados))


async def iniciar(juego, escucha, puerto):
    admin = Admin(juego)
    servidor = await asyncio.start_server(admin.atender, escucha, puerto)
    log.info('administracion: http://%s:%d (clave en server/clave_admin.txt)', escucha, puerto)
    return servidor
