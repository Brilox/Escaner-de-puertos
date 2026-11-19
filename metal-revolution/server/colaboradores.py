#!/usr/bin/env python3
"""Colaboradores: marcos y skins de agradecimiento para quien dona al servidor, por niveles.

Los niveles estan en colaboradores.json (que da cada uno). Lo que tiene cada jugador se guarda en cuentas.db:
  colaboradores(uid, nivel, desde, nota)          nivel de colaborador de cada jugador
  regalos(uid, tipo, id, origen, fecha, nota)     marcos y skins dados uno por uno (a eleccion, campeones, eventos)
  skins_en_uso(uid, heroe, skin)                  skin elegida por el jugador para cada personaje

Uso (con el servidor encendido o apagado; el jugador ve los cambios al volver a entrar al juego):
  python colaboradores.py nivel  <uid|nombre> <nivel> [--nota "Ko-fi noviembre"]
  python colaboradores.py quitar <uid|nombre> [--todo]      quita el nivel (--todo: tambien los regalos sueltos)
  python colaboradores.py skin   <uid|nombre> <skin> [--regalo]   skin a eleccion (usa el cupo del nivel) o regalo
  python colaboradores.py marco  <uid|nombre> <marco>      marco suelto (campeones, eventos)
  python colaboradores.py sacar  <uid|nombre> skin|marco <id>
  python colaboradores.py ver    <uid|nombre>
  python colaboradores.py lista
  python colaboradores.py niveles
  python colaboradores.py catalogo skins [personaje] | marcos"""
import argparse, json, os, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUTA_NIVELES = os.path.join(HERE, 'colaboradores.json')
RUTA_CATALOGO = os.path.join(HERE, '..', 'datos', 'catalogo_cosmeticos.json')
CALIDADES = {0: 'por defecto', 1: 'comun', 2: 'rara', 3: 'epica', 4: 'legendaria'}

def cargar_catalogo():
    try: c = json.load(open(RUTA_CATALOGO, encoding='utf-8'))
    except (OSError, ValueError): c = dict(personajes={}, skins=[], marcos=[])
    c['heroe_de_skin'] = {s['skin']: s['heroe'] for s in c['skins']}
    c['skin'] = {s['skin']: s for s in c['skins']}
    c['marco'] = {m['id']: m for m in c['marcos']}
    return c

def cargar_niveles(ruta=RUTA_NIVELES):
    try: return sorted(json.load(open(ruta, encoding='utf-8'))['niveles'], key=lambda n: n['nivel'])
    except (OSError, ValueError, KeyError): return []

class Colaboradores:
    def __init__(self, db, niveles=None, catalogo=None):
        self.db = db; self.niveles = cargar_niveles() if niveles is None else niveles
        self.cat = cargar_catalogo() if catalogo is None else catalogo
        db.executescript('''
          CREATE TABLE IF NOT EXISTS colaboradores (uid INTEGER PRIMARY KEY, nivel INTEGER NOT NULL, desde INTEGER, nota TEXT DEFAULT '');
          CREATE TABLE IF NOT EXISTS regalos (uid INTEGER, tipo TEXT, id INTEGER, origen TEXT DEFAULT 'regalo', fecha INTEGER,
                                              nota TEXT DEFAULT '', PRIMARY KEY (uid, tipo, id));
          CREATE TABLE IF NOT EXISTS skins_en_uso (uid INTEGER, heroe INTEGER, skin INTEGER, PRIMARY KEY (uid, heroe));''')
        db.commit()

    # ---- consultas (las usa el servidor)
    def nivel(self, uid):
        r = self.db.execute('SELECT nivel FROM colaboradores WHERE uid=?', (uid,)).fetchone(); return r[0] if r else 0
    def nombre_nivel(self, nivel):
        return next((n['nombre'] for n in self.niveles if n['nivel'] == nivel), '')
    def ventajas(self, nivel):
        """Lo que da un nivel, sumando los anteriores: (marcos, skins, cupo de skins a eleccion, todas_las_skins).
        El cupo no se suma: es el total del nivel mas alto (Oro con 3 = 3 skins en total, no 1 + 3)."""
        marcos, skins, cupo, todas = set(), set(), 0, False
        for n in self.niveles:
            if n['nivel'] > nivel: break
            marcos.update(n.get('marcos', [])); skins.update(n.get('skins', []))
            cupo = max(cupo, n.get('skins_a_eleccion', 0)); todas = todas or bool(n.get('todas_las_skins'))
        return marcos, skins, cupo, todas
    def regalos(self, uid, tipo):
        return {r[0] for r in self.db.execute('SELECT id FROM regalos WHERE uid=? AND tipo=?', (uid, tipo))}
    def marcos(self, uid):
        return self.ventajas(self.nivel(uid))[0] | self.regalos(uid, 'marco')
    def skins(self, uid):
        """{heroe: {skins}} de todo lo que tiene por colaborador y por regalos."""
        _, fijas, _, todas = self.ventajas(self.nivel(uid))
        ids = set(self.cat['heroe_de_skin']) if todas else fijas | self.regalos(uid, 'skin')
        out = {}
        for s in ids:
            h = self.cat['heroe_de_skin'].get(s)
            if h is not None: out.setdefault(h, set()).add(s)
        return out
    def skin_en_uso(self, uid, heroe):
        r = self.db.execute('SELECT skin FROM skins_en_uso WHERE uid=? AND heroe=?', (uid, heroe)).fetchone(); return r[0] if r else 0
    def skins_en_uso(self, uid):
        return dict(self.db.execute('SELECT heroe, skin FROM skins_en_uso WHERE uid=?', (uid,)).fetchall())
    def usar_skin(self, uid, heroe, skin):
        self.db.execute('INSERT OR REPLACE INTO skins_en_uso VALUES(?,?,?)', (uid, heroe, skin)); self.db.commit()

    # ---- cambios (los usa el staff desde la linea de comandos)
    def poner_nivel(self, uid, nivel, nota=''):
        if not any(n['nivel'] == nivel for n in self.niveles): raise ValueError('no existe el nivel %d (ver colaboradores.json)' % nivel)
        self.db.execute('INSERT INTO colaboradores(uid,nivel,desde,nota) VALUES(?,?,?,?) ON CONFLICT(uid) DO UPDATE SET nivel=excluded.nivel, '
                        "nota=CASE WHEN excluded.nota<>'' THEN excluded.nota ELSE colaboradores.nota END", (uid, nivel, int(time.time()), nota))
        self.db.commit()
    def quitar(self, uid, todo=False):
        self.db.execute('DELETE FROM colaboradores WHERE uid=?', (uid,))
        if todo: self.db.execute('DELETE FROM regalos WHERE uid=?', (uid,))
        else: self.db.execute("DELETE FROM regalos WHERE uid=? AND origen='eleccion'", (uid,))
        self.db.commit()
    def cupo_libre(self, uid):
        usados = self.db.execute("SELECT COUNT(*) FROM regalos WHERE uid=? AND tipo='skin' AND origen='eleccion'", (uid,)).fetchone()[0]
        return self.ventajas(self.nivel(uid))[2] - usados
    def dar(self, uid, tipo, id_, origen='regalo', nota=''):
        if tipo == 'skin':
            s = self.cat['skin'].get(id_)
            if not s: raise ValueError('la skin %d no esta en el catalogo' % id_)
            if s['calidad'] == 0: raise ValueError('la skin %d es la de por defecto: ya la tienen todos' % id_)
            if origen == 'eleccion' and self.cupo_libre(uid) <= 0: raise ValueError('no le quedan skins a eleccion en su nivel (usa --regalo para darla igual)')
        elif id_ not in self.cat['marco']: raise ValueError('el marco %d no esta en el catalogo' % id_)
        self.db.execute('INSERT OR REPLACE INTO regalos(uid,tipo,id,origen,fecha,nota) VALUES(?,?,?,?,?,?)', (uid, tipo, id_, origen, int(time.time()), nota))
        self.db.commit()
    def sacar(self, uid, tipo, id_):
        self.db.execute('DELETE FROM regalos WHERE uid=? AND tipo=? AND id=?', (uid, tipo, id_)); self.db.commit()

# ----------------------------------------------------------------- linea de comandos
def main(argv=None):
    ap = argparse.ArgumentParser(description='Marcos y skins de colaboradores', formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--db', default=os.path.join(HERE, 'cuentas.db'))
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('nivel'); p.add_argument('jugador'); p.add_argument('nivel', type=int); p.add_argument('--nota', default='')
    p = sub.add_parser('quitar'); p.add_argument('jugador'); p.add_argument('--todo', action='store_true')
    p = sub.add_parser('skin'); p.add_argument('jugador'); p.add_argument('id', type=int); p.add_argument('--regalo', action='store_true'); p.add_argument('--nota', default='')
    p = sub.add_parser('marco'); p.add_argument('jugador'); p.add_argument('id', type=int); p.add_argument('--nota', default='')
    p = sub.add_parser('sacar'); p.add_argument('jugador'); p.add_argument('tipo', choices=('skin', 'marco')); p.add_argument('id', type=int)
    p = sub.add_parser('ver'); p.add_argument('jugador')
    sub.add_parser('lista'); sub.add_parser('niveles')
    p = sub.add_parser('catalogo'); p.add_argument('que', choices=('skins', 'marcos')); p.add_argument('personaje', nargs='?')
    a = ap.parse_args(argv)

    db = sqlite3.connect(a.db); db.row_factory = sqlite3.Row
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='jugadores'").fetchone():
        if a.cmd not in ('niveles', 'catalogo'): raise SystemExit('%s no tiene jugadores (arranca el servidor una vez primero)' % a.db)
    col = Colaboradores(db); cat = col.cat

    def buscar(j):
        r = db.execute('SELECT uid, nombre FROM jugadores WHERE uid=? OR lower(nombre)=lower(?)', (int(j) if j.isdigit() else -1, j)).fetchone()
        if not r: raise SystemExit('no encontre al jugador %r (usa su uid o su nombre exacto)' % j)
        return r['uid'], r['nombre']
    def nom_skin(s):
        x = cat['skin'].get(s); return '%d %s (%s, %s)' % (s, x['nombre'], cat['personajes'].get(str(x['heroe']), x['heroe']), CALIDADES.get(x['calidad'])) if x else str(s)
    def nom_marco(m):
        x = cat['marco'].get(m); return '%d %s' % (m, x['nombre']) if x else str(m)

    try:
        if a.cmd == 'niveles':
            for n in col.niveles:
                m, s, cupo, todas = col.ventajas(n['nivel'])
                print('%d  %s\n   marcos: %s\n   skins: %s%s' % (n['nivel'], n['nombre'], ', '.join(nom_marco(x) for x in sorted(m)) or '-',
                      'TODAS' if todas else (', '.join(nom_skin(x) for x in sorted(s)) or '-'), '' if todas else '  + %d a eleccion' % cupo))
        elif a.cmd == 'catalogo':
            if a.que == 'marcos':
                tipos = {1: 'clasificatoria', 2: 'victorias con personaje', 3: 'especial (no se gana jugando)', 4: 'dias de juego', 99: 'especial (no se gana jugando)'}
                for m in cat['marcos']: print('%3d  %-45s %s' % (m['id'], m['nombre'], tipos.get(m['condicion'], m['condicion'])))
            else:
                for s in cat['skins']:
                    pj = cat['personajes'].get(str(s['heroe']), str(s['heroe']))
                    if s['calidad'] and (not a.personaje or a.personaje.lower() in pj.lower() or a.personaje == str(s['heroe'])):
                        print('%5d  %-22s %-32s %s' % (s['skin'], pj, s['nombre'], CALIDADES.get(s['calidad'])))
        elif a.cmd == 'lista':
            for r in db.execute('SELECT c.uid, j.nombre, c.nivel, c.desde, c.nota FROM colaboradores c LEFT JOIN jugadores j USING(uid) ORDER BY c.nivel DESC, c.desde'):
                print('%d  %-16s nivel %d %-20s desde %s  %s' % (r['uid'], r['nombre'] or '?', r['nivel'], col.nombre_nivel(r['nivel']),
                      time.strftime('%Y-%m-%d', time.localtime(r['desde'] or 0)), r['nota'] or ''))
        else:
            uid, nombre = buscar(a.jugador)
            if a.cmd == 'nivel': col.poner_nivel(uid, a.nivel, a.nota); print('%s (%d) ahora es %s' % (nombre, uid, col.nombre_nivel(a.nivel)))
            elif a.cmd == 'quitar': col.quitar(uid, a.todo); print('%s (%d) ya no es colaborador' % (nombre, uid))
            elif a.cmd == 'skin':
                col.dar(uid, 'skin', a.id, 'regalo' if a.regalo else 'eleccion', a.nota); print('%s recibe la skin %s' % (nombre, nom_skin(a.id)))
            elif a.cmd == 'marco': col.dar(uid, 'marco', a.id, 'regalo', a.nota); print('%s recibe el marco %s' % (nombre, nom_marco(a.id)))
            elif a.cmd == 'sacar': col.sacar(uid, a.tipo, a.id); print('quitado %s %d a %s' % (a.tipo, a.id, nombre))
            if a.cmd != 'quitar':
                nv = col.nivel(uid); _, _, cupo, todas = col.ventajas(nv)
                print('\n%s (%d): %s' % (nombre, uid, ('nivel %d, %s' % (nv, col.nombre_nivel(nv))) if nv else 'sin nivel de colaborador'))
                print('  marcos: %s' % (', '.join(nom_marco(m) for m in sorted(col.marcos(uid))) or '-'))
                sk = sorted(s for v in col.skins(uid).values() for s in v)
                print('  skins: %s' % ('TODAS (%d)' % len(sk) if todas else (', '.join(nom_skin(s) for s in sk) or '-')))
                if not todas and cupo: print('  skins a eleccion libres: %d de %d' % (col.cupo_libre(uid), cupo))
    except ValueError as e:
        raise SystemExit('error: %s' % e)

if __name__ == '__main__':
    main()
