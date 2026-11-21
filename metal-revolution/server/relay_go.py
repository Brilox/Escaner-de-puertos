#!/usr/bin/env python3
"""Relay de las peleas escrito en Go (relay_go/), como proceso aparte: mismo protocolo que relay.py pero mucho mas
rapido (no pasa por el interprete de Python ni comparte el GIL con el resto del servidor).

mr_server.py lo arranca si encuentra el ejecutable (server/bin/relay_go.exe en Windows, server/bin/relay_go en
Linux); si no, usa relay.py. Control por la entrada/salida estandar (lineas JSON, ver relay_go/cmd/relay/main.go).
Ademas registra la red de cada pelea (ping que informa cada telefono, paquetes y reenvios) en red_partidas.csv."""
import csv, json, logging, os, subprocess, sys, threading, time

log = logging.getLogger('mr.relay')
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, 'red_partidas.csv')
COLUMNAS = ['fecha', 'pelea', 'tipo', 'lado', 'pos', 'jugador', 'ip', 'ping_prom', 'ping_min', 'ping_max', 'muestras',
            'recibidos', 'enviados', 'reenvios', 'segundos']


def ejecutable():
    import platform
    if os.name == 'nt': nombre = 'relay_go.exe'
    elif platform.machine().lower() in ('aarch64', 'arm64'): nombre = 'relay_go_arm64'   # Oracle Ampere (ARM) y similares
    else: nombre = 'relay_go'
    p = os.path.join(HERE, 'bin', nombre)
    return p if os.path.isfile(p) else None


class RelayGo:
    """Misma interfaz que relay.Relay para mr_server.py: puerto, puerto_ping, start(), parar()."""

    def __init__(self, escucha, puerto, al_empezar=None, info_partida=None, puerto_ping=None):
        self.exe = ejecutable(); self.puerto = puerto
        self.puerto_ping = puerto - 1 if puerto_ping is None else puerto_ping
        self.args = [self.exe, '-escucha', escucha, '-puerto', str(puerto), '-puerto-ping', str(self.puerto_ping)]
        self.al_empezar = al_empezar; self.info_partida = info_partida or (lambda mid: {})
        self.proc = None; self.lock = threading.Lock(); self.activo = True

    def start(self):
        self.proc = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     bufsize=1, text=True, encoding='utf-8', errors='replace')
        threading.Thread(target=self._eventos, name='relay-go-eventos', daemon=True).start()
        threading.Thread(target=self._registro, name='relay-go-log', daemon=True).start()
        log.info('relay Go en marcha (%s)', self.exe)

    def parar(self):
        self.activo = False
        try: self.proc.stdin.close(); self.proc.wait(3)
        except Exception:
            try: self.proc.kill()
            except Exception: pass

    def _mandar(self, **m):
        with self.lock:
            try: self.proc.stdin.write(json.dumps(m) + '\n'); self.proc.stdin.flush()
            except (OSError, ValueError, AttributeError): log.error('relay Go: no pude mandarle %s', m)

    def esperados(self, mid, n): self._mandar(t='esperados', id=int(mid), n=int(n))
    def fin(self, mid): self._mandar(t='fin', id=int(mid))

    def _registro(self):
        for linea in self.proc.stderr:
            linea = linea.rstrip()
            if linea: log.info('%s', linea)

    def _eventos(self):
        for linea in self.proc.stdout:
            try: e = json.loads(linea)
            except ValueError: continue
            if e.get('t') == 'empezo' and self.al_empezar:
                try: self.al_empezar(int(e['id']))
                except Exception: log.exception('al_empezar')
            elif e.get('t') == 'red':
                try: self._anotar_red(e)
                except Exception: log.exception('registro de red')
        if self.activo:
            codigo = self.proc.poll()
            if codigo:  log.error('relay Go: el proceso termino con error (codigo %s)', codigo)
            else:       log.info('relay Go: el proceso se cerro (al apagar el servidor es normal)')

    def _anotar_red(self, e):
        info = self.info_partida(int(e['id'])) or {}
        fila = dict(fecha=time.strftime('%Y-%m-%d %H:%M:%S'), pelea=e['id'], tipo=info.get('tipo', ''), lado=e['lado'], pos=e['pos'],
                    jugador=info.get('nombres', {}).get((int(e['lado']), int(e['pos'])), ''), ip=e.get('ip', ''),
                    **{k: e.get(k, '') for k in COLUMNAS[7:]})
        log.info('red: pelea %s %s (%s) ping prom=%s min=%s max=%s reenvios=%s en %ss', fila['pelea'], fila['jugador'] or '?',
                 fila['tipo'], fila['ping_prom'], fila['ping_min'], fila['ping_max'], fila['reenvios'], fila['segundos'])
        nuevo = not os.path.exists(CSV)
        with open(CSV, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS)
            if nuevo: w.writeheader()
            w.writerow(fila)
