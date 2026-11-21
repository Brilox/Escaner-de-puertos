#!/usr/bin/env python3
"""Panel de administracion de Metal Online (Windows, Linux o Mac; solo necesita Python, sin instalar nada).

    python panel_admin.py

Se conecta a la API de administracion del servidor (server/admin.py). Pide la direccion (por defecto
http://127.0.0.1:8090) y la clave, que esta en server/clave_admin.txt del PC o VPS donde corre el servidor.
Si el servidor esta en un VPS, primero abre el tunel:  ssh -L 8090:127.0.0.1:8090 usuario@IP-del-VPS"""
import json, os, time, urllib.error, urllib.parse, urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

AJUSTES_LOCALES = os.path.join(os.path.expanduser('~'), '.metal_online_admin.json')
CONDICIONES = {1: 'Puntos de clasificatoria', 2: 'Victorias con personaje', 3: 'Objeto', 4: 'Nivel', 99: 'Especial / nuevo'}
ROLES = ('colaborador', 'campeon')
ECONOMIA_INICIAL = {
    'monedas_por_victoria': 20, 'monedas_por_derrota': 8, 'maximo_monedas_diario': 60,
    'personajes_gratis_al_empezar': 5, 'precio_personaje': 100, 'precio_avatar': 150, 'precio_marco': 200, 'precio_skin': 300,
    'tienda_activa': False, 'pase_de_batalla_activo': False,
}


def fecha(t):
    return time.strftime('%d/%m/%Y %H:%M', time.localtime(t)) if t else ''


class Api:
    def __init__(self, url, clave): self.url = url.rstrip('/'); self.clave = clave

    def llamar(self, ruta, datos=None, metodo=None, espera=8):
        cuerpo = json.dumps(datos).encode('utf-8') if datos is not None else None
        req = urllib.request.Request(self.url + ruta, data=cuerpo, method=metodo or ('POST' if datos is not None else 'GET'),
                                     headers={'X-Clave': self.clave, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=espera) as r: return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try: msg = json.loads(e.read().decode('utf-8')).get('error')
            except Exception: msg = str(e)
            raise RuntimeError(msg)
        except urllib.error.URLError as e:
            raise RuntimeError('No hay conexion con el servidor (%s). Revisa que este encendido y la direccion.' % e.reason)


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Metal Online - Panel de administracion'); self.geometry('1180x720'); self.minsize(980, 600)
        ttk.Style(self).theme_use('clam')
        self.api = None; self.cat = {}
        if not self.conectar(): self.destroy(); return
        nb = ttk.Notebook(self); nb.pack(fill='both', expand=True, padx=6, pady=6)
        for titulo, fn in (('Estado', self.pest_estado), ('Jugadores', self.pest_jugadores), ('Chat', self.pest_chat),
                           ('Héroes y skins', self.pest_heroes), ('Marcos', self.pest_marcos),
                           ('Configuración del juego', self.pest_config), ('Actualizaciones', self.pest_actualizaciones),
                           ('Economía y tienda', self.pest_economia)):
            f = ttk.Frame(nb, padding=8); nb.add(f, text=titulo); fn(f)
        self.estado_barra = ttk.Label(self, text='', anchor='w'); self.estado_barra.pack(fill='x', padx=8, pady=(0, 4))
        self.refrescar_estado(); self.refrescar_jugadores(); self.cargar_catalogo(); self.refrescar_act()

    # ------------------------------------------------------------------ conexion
    def conectar(self):
        try: guard = json.load(open(AJUSTES_LOCALES))
        except Exception: guard = {}
        while True:
            url = simpledialog.askstring('Conectar', 'Dirección del servidor:', initialvalue=guard.get('url', 'http://127.0.0.1:8090'), parent=self)
            if not url: return False
            clave = simpledialog.askstring('Conectar', 'Clave de administración (server/clave_admin.txt):',
                                           initialvalue=guard.get('clave', ''), show='*', parent=self)
            if clave is None: return False
            self.api = Api(url, clave)
            try:
                self.api.llamar('/api/estado')
                json.dump(dict(url=url, clave=clave), open(AJUSTES_LOCALES, 'w')); return True
            except RuntimeError as e:
                if not messagebox.askretrycancel('No se pudo conectar', str(e)): return False

    def llamar(self, ruta, datos=None, metodo=None, aviso=None, espera=8):
        try:
            r = self.api.llamar(ruta, datos, metodo, espera)
            if aviso: self.estado_barra.config(text='✔ ' + aviso + '  (' + time.strftime('%H:%M:%S') + ')')
            return r
        except RuntimeError as e:
            messagebox.showerror('Error', str(e)); return None

    @staticmethod
    def tabla(padre, columnas, anchos, alto=18):
        marco = ttk.Frame(padre)
        t = ttk.Treeview(marco, columns=columnas, show='headings', height=alto)
        for c, w in zip(columnas, anchos): t.heading(c, text=c); t.column(c, width=w, anchor='w')
        sb = ttk.Scrollbar(marco, orient='vertical', command=t.yview); t.configure(yscrollcommand=sb.set)
        t.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        return marco, t

    # ------------------------------------------------------------------ Actualizaciones
    def pest_actualizaciones(self, f):
        self.lbl_act = ttk.Label(f, text='', font=('Segoe UI', 11), justify='left'); self.lbl_act.pack(anchor='w', pady=(0, 6))
        bot = ttk.Frame(f); bot.pack(fill='x', pady=(0, 6))
        ttk.Button(bot, text='Subir actualización (.mrupd)…', command=self.subir_act).pack(side='left', padx=2)
        self.act_obligatoria = tk.BooleanVar(value=False)
        ttk.Checkbutton(bot, text='Obligatoria (sin actualizar no se puede entrar)', variable=self.act_obligatoria,
                        command=lambda: self.llamar('/api/actualizaciones', dict(accion='obligatoria', valor=self.act_obligatoria.get()),
                                                    aviso='Obligatoria: %s' % ('sí' if self.act_obligatoria.get() else 'no'))).pack(side='left', padx=10)
        ttk.Button(bot, text='Retirar (no ofrecer ninguna)', command=lambda: messagebox.askyesno('Retirar', '¿Dejar de ofrecer la actualización?')
                   and self.llamar('/api/actualizaciones', dict(accion='retirar'), aviso='Actualización retirada') and self.refrescar_act(False)).pack(side='left', padx=2)
        ttk.Button(bot, text='Actualizar', command=lambda: self.refrescar_act(False)).pack(side='left', padx=2)
        cuerpo = ttk.PanedWindow(f, orient='vertical'); cuerpo.pack(fill='both', expand=True)
        arriba = ttk.Frame(cuerpo); cuerpo.add(arriba, weight=1)
        izq = ttk.LabelFrame(arriba, text='Versiones instaladas en el servidor', padding=4); izq.pack(side='left', fill='both', expand=True)
        m, self.t_vers = self.tabla(izq, ('Versión', 'Nombre', 'Archivos', 'Tamaño', 'Creada'), (60, 200, 70, 80, 120), 6); m.pack(fill='both', expand=True)
        b2 = ttk.Frame(izq); b2.pack(fill='x')
        ttk.Button(b2, text='Publicar esta versión', command=self.activar_act).pack(side='left', padx=2)
        ttk.Button(b2, text='Borrar', command=self.borrar_act).pack(side='left', padx=2)
        der = ttk.LabelFrame(arriba, text='Teléfonos que preguntaron (por IP)', padding=4); der.pack(side='left', fill='both', expand=True, padx=(6, 0))
        m, self.t_cli = self.tabla(der, ('IP', 'Versión que reporta', 'Archivos bajados', 'Al día', 'Última consulta'), (110, 120, 100, 60, 120), 6)
        m.pack(fill='both', expand=True)
        abajo = ttk.LabelFrame(cuerpo, text='Registro: lo que pide cada teléfono (para seguir la prueba junto con adb logcat)', padding=4)
        cuerpo.add(abajo, weight=2)
        self.txt_act = tk.Text(abajo, height=12, wrap='none', font=('Consolas', 9)); self.txt_act.pack(fill='both', expand=True)

    def refrescar_act(self, auto=True):
        e = self.api and self.api_silenciosa('/api/actualizaciones')
        if e:
            v = e.get('vigente')
            self.lbl_act.config(text=('Publicada: versión %s — %s  (%s)' % (v['version'], v.get('nombre', ''), 'OBLIGATORIA' if e['obligatoria'] else 'opcional')
                                      if v else 'No hay ninguna actualización publicada: los teléfonos reciben "sin actualización".') +
                                     ('\nPaquete para los teléfonos: %s' % (e.get('preparacion', {}).get(str(v['version']), {}).get('texto', '—')) if v else '') +
                                     '\nOBB del juego: %s' % (e.get('obb') or 'NO ENCONTRADO: copia el .obb en la carpeta server') +
                                     '\nDescargas para los teléfonos: %s   (abre ese puerto TCP en el firewall)' % e['url_descargas'])
            self.act_obligatoria.set(e['obligatoria'])
            self.t_vers.delete(*self.t_vers.get_children())
            for x in e['instaladas']:
                self.t_vers.insert('', 'end', iid=str(x['version']), values=(x['version'], x.get('nombre', ''), len(x.get('telefono', [])),
                                   '%.1f MB' % (sum(a['tamano'] for a in x.get('telefono', [])) / 1e6), fecha(x.get('creado'))))
            self.t_cli.delete(*self.t_cli.get_children())
            for c in e['clientes']:
                self.t_cli.insert('', 'end', values=(c['ip'], c['version'] or '?', len(c['descargados']), 'sí' if c['al_dia'] else 'NO', fecha(c['ultima_consulta'])))
            self.txt_act.delete('1.0', 'end')
            for r in reversed(e['registro']):
                self.txt_act.insert('end', '%s  %-7s %-15s %s\n' % (time.strftime('%H:%M:%S', time.localtime(r['fecha'])), r['tipo'], r['ip'], r['texto']))
        if auto: self.after(5000, self.refrescar_act)

    def api_silenciosa(self, ruta):
        try: return self.api.llamar(ruta)
        except RuntimeError: return None

    def subir_act(self):
        ruta = filedialog.askopenfilename(title='Archivo de actualización', filetypes=[('Actualización de Metal Online', '*.mrupd'), ('Todos', '*.*')])
        if not ruta: return
        import base64
        datos = base64.b64encode(open(ruta, 'rb').read()).decode('ascii')
        self.estado_barra.config(text='Subiendo %s (%.1f MB)…' % (os.path.basename(ruta), os.path.getsize(ruta) / 1e6)); self.update()
        r = self.llamar('/api/actualizaciones', dict(accion='subir', nombre=os.path.basename(ruta), datos_b64=datos), aviso='Actualización subida y publicada', espera=300)
        if r: messagebox.showinfo('Actualización', 'Versión %s publicada: %s' % (r['version'], r.get('nombre', ''))); self.refrescar_act(False); self.cargar_catalogo()

    def activar_act(self):
        s = self.t_vers.selection()
        if s and self.llamar('/api/actualizaciones', dict(accion='activar', version=int(s[0])), aviso='Versión %s publicada' % s[0]): self.refrescar_act(False); self.cargar_catalogo()

    def borrar_act(self):
        s = self.t_vers.selection()
        if s and messagebox.askyesno('Borrar', '¿Borrar la versión %s del servidor?' % s[0]) and \
                self.llamar('/api/actualizaciones', dict(accion='borrar', version=int(s[0])), aviso='Versión %s borrada' % s[0]): self.refrescar_act(False)

    # ------------------------------------------------------------------ Estado
    def pest_estado(self, f):
        self.lbl_estado = ttk.Label(f, text='', font=('Segoe UI', 11), justify='left'); self.lbl_estado.pack(anchor='w', pady=(0, 8))
        m, self.t_mesas = self.tabla(f, ('Mesa', 'Izquierda', 'Derecha', 'Observadores', 'Peleando'), (60, 220, 220, 100, 90), 9)
        m.pack(fill='x')
        caja = ttk.LabelFrame(f, text='Anuncio a todos los jugadores conectados', padding=8); caja.pack(fill='x', pady=10)
        self.e_anuncio = ttk.Entry(caja); self.e_anuncio.pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(caja, text='Enviar', command=self.enviar_anuncio).pack(side='left')
        ttk.Button(f, text='Actualizar', command=self.refrescar_estado).pack(anchor='w')

    def refrescar_estado(self, auto=True):
        e = self.api and self.llamar('/api/estado')
        if e:
            self.lbl_estado.config(text='Conectados: %(en_linea)d    Cuentas: %(cuentas)d    En el salón: %(en_el_salon)d    '
                                        'Peleas en curso: %(peleas_activas)d    Buscando rival: %(buscando)d' % e +
                                        '\nEncendido desde: %s    Configuraciones activas: %s' % (fecha(e['encendido_desde']), ', '.join(e['configuraciones']) or '-'))
            self.t_mesas.delete(*self.t_mesas.get_children())
            for m in e['mesas']:
                self.t_mesas.insert('', 'end', values=(m['id'], m['izquierda'], m['derecha'], m['observadores'], 'sí' if m['peleando'] else ''))
        if auto: self.after(10000, self.refrescar_estado)

    def enviar_anuncio(self):
        t = self.e_anuncio.get().strip()
        if t and self.llamar('/api/anuncio', dict(texto=t), aviso='Anuncio enviado'): self.e_anuncio.delete(0, 'end')

    # ------------------------------------------------------------------ Jugadores
    def pest_jugadores(self, f):
        arriba = ttk.Frame(f); arriba.pack(fill='x', pady=(0, 6))
        ttk.Label(arriba, text='Buscar (nombre o UID):').pack(side='left')
        self.e_filtro = ttk.Entry(arriba, width=30); self.e_filtro.pack(side='left', padx=6)
        self.e_filtro.bind('<Return>', lambda e: self.refrescar_jugadores(False))
        self.solo_online = tk.BooleanVar(value=False)
        ttk.Checkbutton(arriba, text='Solo en línea', variable=self.solo_online, command=lambda: self.refrescar_jugadores(False)).pack(side='left')
        ttk.Button(arriba, text='Actualizar', command=lambda: self.refrescar_jugadores(False)).pack(side='left', padx=6)
        cols = ('UID', 'Nombre', 'Estado', 'Nivel', 'Peleas', 'Victorias', 'Rol', 'Sanción', 'Último ingreso')
        m, self.t_jug = self.tabla(f, cols, (80, 170, 80, 50, 60, 70, 140, 140, 130)); m.pack(fill='both', expand=True)
        self.t_jug.bind('<Double-1>', lambda e: self.ver_jugador())
        bot = ttk.Frame(f); bot.pack(fill='x', pady=6)
        for texto, fn in (('Ver ficha', self.ver_jugador), ('Mensaje', lambda: self.accion('mensaje')),
                          ('Silenciar', lambda: self.accion('silenciar')), ('Quitar silencio', lambda: self.accion('quitar_silencio')),
                          ('Suspender', lambda: self.accion('suspender')), ('Quitar suspensión', lambda: self.accion('quitar_suspension')),
                          ('Expulsar', lambda: self.accion('expulsar')), ('Renombrar', lambda: self.accion('renombrar')),
                          ('Roles', lambda: self.accion('rol'))):
            ttk.Button(bot, text=texto, command=fn).pack(side='left', padx=2)

    def refrescar_jugadores(self, auto=True):
        datos = self.api and self.llamar('/api/jugadores?' + urllib.parse.urlencode(dict(filtro=self.e_filtro.get().strip())))
        if datos is not None:
            sel = self.uid_sel()
            self.t_jug.delete(*self.t_jug.get_children())
            for j in sorted(datos, key=lambda j: (not j['en_linea'], -(j['ultimo_login'] or 0))):
                if self.solo_online.get() and not j['en_linea']: continue
                sancion = ' '.join(x for x, v in (('SUSPENDIDO', j['suspendido']), ('silenciado', j['silenciado'])) if v)
                self.t_jug.insert('', 'end', iid=str(j['uid']), values=(j['uid'], j['nombre'], '🟢 en línea' if j['en_linea'] else 'offline',
                                  j['nivel'], j['partidas'], j['victorias'], j['rol'], sancion, fecha(j['ultimo_login'])))
            if sel and self.t_jug.exists(str(sel)): self.t_jug.selection_set(str(sel))
        if auto: self.after(10000, self.refrescar_jugadores)

    def uid_sel(self):
        s = self.t_jug.selection() if hasattr(self, 't_jug') else ()
        return int(s[0]) if s else None

    def accion(self, accion):
        uid = self.uid_sel()
        if not uid: messagebox.showinfo('Jugadores', 'Elige un jugador de la lista.'); return
        d = dict(accion=accion)
        if accion in ('silenciar', 'suspender'):
            h = simpledialog.askstring(accion.capitalize(), 'Horas (vacío = permanente):', parent=self)
            if h is None: return
            d['horas'] = float(h) if h.strip() else 0
            d['motivo'] = simpledialog.askstring(accion.capitalize(), 'Motivo (lo verá el jugador):', parent=self) or ''
        elif accion == 'expulsar': d['motivo'] = simpledialog.askstring('Expulsar', 'Motivo:', parent=self) or ''
        elif accion == 'mensaje':
            d['texto'] = simpledialog.askstring('Mensaje', 'Texto para el jugador:', parent=self)
            if not d['texto']: return
        elif accion == 'renombrar':
            d['nombre'] = simpledialog.askstring('Renombrar', 'Nombre nuevo:', parent=self)
            if not d['nombre']: return
        elif accion == 'rol':
            actual = self.t_jug.set(str(uid), 'Rol')
            d['rol'] = simpledialog.askstring('Roles', 'Roles separados por coma (%s), vacío para quitar todos:' % ', '.join(ROLES),
                                              initialvalue=actual, parent=self)
            if d['rol'] is None: return
        if self.llamar('/api/jugador/%d/accion' % uid, d, aviso='%s aplicado al jugador %d' % (accion, uid)): self.refrescar_jugadores(False)

    def ver_jugador(self):
        uid = self.uid_sel()
        if not uid: return
        d = self.llamar('/api/jugador/%d' % uid)
        if not d: return
        c = d['cuenta']; v = tk.Toplevel(self); v.title('Ficha de %s (%d)' % (c['nombre'], uid)); v.geometry('900x620')
        nb = ttk.Notebook(v); nb.pack(fill='both', expand=True, padx=6, pady=6)
        g = ttk.Frame(nb, padding=8); nb.add(g, text='Cuenta')
        t = d['temporada']['SeasonDatas'][0]; rk = d['clasificatoria']
        lineas = [('Nombre', c['nombre']), ('UID', uid), ('Estado', 'en línea' if d['en_linea'] else 'offline'), ('Nivel / exp', '%s / %s' % (c['nivel'], c['exp'])),
                  ('Creada', fecha(c['creado'])), ('Último ingreso', fecha(c['ultimo_login'])), ('Dispositivo', c.get('dispositivo', '')),
                  ('Rol', c.get('rol') or '-'), ('Suspendido hasta', fecha(c.get('baneado_hasta')) if (c.get('baneado_hasta') or 0) > time.time() else '-'),
                  ('Silenciado hasta', fecha(c.get('silenciado_hasta')) if (c.get('silenciado_hasta') or 0) > time.time() else '-'),
                  ('Motivo', c.get('motivo') or '-'), ('Clasificatoria 1v1', '%s puntos (máx %s), %s-%s' % (rk['puntos'], rk['max_puntos'], rk['victorias'], rk['derrotas'])),
                  ('Victorias (temporada)', '%.0f %%' % (100 * (t.get('WinRate') or 0))), ('Puntaje', t.get('Score', 0)),
                  ('Avatar / marco', '%s / %s' % (c.get('cabeza'), c.get('marco'))), ('Me gusta recibidos', c.get('elogios', 0)),
                  ('Marcos desbloqueados', ', '.join(map(str, d['marcos'])))]
        for i, (k, val) in enumerate(lineas):
            ttk.Label(g, text=k + ':', font=('Segoe UI', 9, 'bold')).grid(row=i, column=0, sticky='w', pady=1)
            ttk.Label(g, text=str(val), wraplength=600).grid(row=i, column=1, sticky='w', padx=8)
        h = ttk.Frame(nb, padding=8); nb.add(h, text='Estadísticas')
        m, tt = self.tabla(h, ('Personaje', 'Modo', 'Peleas', 'Victorias', 'Mejor racha', 'Daño total', 'Combo máx'), (160, 70, 70, 80, 90, 100, 90)); m.pack(fill='both', expand=True)
        nombres = self.cat.get('nombres', {})
        for x in d['heroes']:
            st = x.get('InBattleStats') or {}
            tt.insert('', 'end', values=(nombres.get(str(x['HeroId']), x['HeroId']), x['BattleMode'], x['TotalCount'], x['WinCount'],
                                         x['MaxContinueWinCount'], st.get('TotalDamage', ''), st.get('MaxCombo', '')))
        ch = ttk.Frame(nb, padding=8); nb.add(ch, text='Chat reciente')
        m, tc = self.tabla(ch, ('Fecha', 'Canal', 'Destino', 'Texto'), (130, 70, 70, 560)); m.pack(fill='both', expand=True)
        for x in d['chat']: tc.insert('', 'end', values=(fecha(x['fecha']), x['canal'], x['destino'], x['texto']))
        db = ttk.Frame(nb, padding=8); nb.add(db, text='Desbloqueos propios')
        ttk.Label(db, text='Ajustes solo para este jugador (ganan sobre los bloqueos globales y los exclusivos).').pack(anchor='w')
        m, td = self.tabla(db, ('Tipo', 'ID', 'Permitido'), (100, 100, 100), 10); m.pack(fill='both', expand=True, pady=6)
        for x in d['desbloqueos']: td.insert('', 'end', values=(x['tipo'], x['id'], 'sí' if x['permitido'] else 'NO'))
        def poner(permitido):
            tipo = simpledialog.askstring('Desbloqueo', 'Tipo (heroe, skin o marco):', parent=v)
            if tipo not in ('heroe', 'skin', 'marco'): return
            id_ = simpledialog.askinteger('Desbloqueo', 'ID:', parent=v)
            if id_ is None: return
            if self.llamar('/api/jugador/%d/desbloqueo' % uid, dict(tipo=tipo, id=id_, permitido=permitido), aviso='Desbloqueo guardado'):
                v.destroy(); self.ver_jugador()
        fila = ttk.Frame(db); fila.pack(fill='x')
        ttk.Button(fila, text='Dar (desbloquear)', command=lambda: poner(True)).pack(side='left', padx=2)
        ttk.Button(fila, text='Quitar (bloquear)', command=lambda: poner(False)).pack(side='left', padx=2)
        ttk.Button(fila, text='Volver a lo normal', command=lambda: poner(None)).pack(side='left', padx=2)

    # ------------------------------------------------------------------ Chat
    def pest_chat(self, f):
        arriba = ttk.Frame(f); arriba.pack(fill='x', pady=(0, 6))
        ttk.Label(arriba, text='UID:').pack(side='left'); self.e_chat_uid = ttk.Entry(arriba, width=12); self.e_chat_uid.pack(side='left', padx=4)
        ttk.Label(arriba, text='Texto contiene:').pack(side='left'); self.e_chat_txt = ttk.Entry(arriba, width=30); self.e_chat_txt.pack(side='left', padx=4)
        ttk.Button(arriba, text='Buscar', command=self.buscar_chat).pack(side='left', padx=4)
        ttk.Button(arriba, text='Exportar a .txt', command=self.exportar_chat).pack(side='left')
        m, self.t_chat = self.tabla(f, ('Fecha', 'UID', 'Nombre', 'Canal', 'Destino', 'Texto'), (130, 80, 140, 70, 70, 560)); m.pack(fill='both', expand=True)
        ttk.Label(f, text='Se guarda todo el chat: salón, mesas, privados y peleas. Úsalo para investigar reportes de abuso o acoso.').pack(anchor='w', pady=4)

    def buscar_chat(self):
        q = {k: v for k, v in (('uid', self.e_chat_uid.get().strip()), ('texto', self.e_chat_txt.get().strip()), ('limite', 2000)) if v}
        datos = self.llamar('/api/chat?' + urllib.parse.urlencode(q))
        if datos is None: return
        self.t_chat.delete(*self.t_chat.get_children()); self._chat = datos
        for x in datos: self.t_chat.insert('', 'end', values=(fecha(x['fecha']), x['uid'], x['nombre'], x['canal'], x['destino'], x['texto']))
        self.estado_barra.config(text='%d mensajes' % len(datos))

    def exportar_chat(self):
        datos = getattr(self, '_chat', None)
        if not datos: messagebox.showinfo('Chat', 'Primero haz una búsqueda.'); return
        ruta = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Texto', '*.txt')])
        if ruta:
            with open(ruta, 'w', encoding='utf-8') as fh:
                for x in reversed(datos): fh.write('%s  [%s]  %s (%s) -> %s: %s\n' % (fecha(x['fecha']), x['canal'], x['nombre'], x['uid'], x['destino'], x['texto']))

    # ------------------------------------------------------------------ Catalogo: heroes, skins, marcos
    def cargar_catalogo(self):
        cat = self.llamar('/api/catalogo')
        if not cat: return
        self.cat = cat; self.pintar_heroes(); self.pintar_marcos()

    def estado_item(self, tipo, id_):
        ex = [r for r, cosas in self.cat.get('exclusivos', {}).items() if id_ in (cosas.get(tipo) or [])]
        if ex: return 'Exclusivo: ' + ', '.join(ex)
        return 'BLOQUEADO para todos' if id_ in (self.cat.get('bloqueados', {}).get(tipo) or []) else 'normal'

    def cambiar(self, tipo, id_, modo):
        if modo in ROLES:
            activo = id_ not in ((self.cat.get('exclusivos', {}).get(modo) or {}).get(tipo) or [])
            d = dict(tipo=tipo, id=id_, exclusivo=modo, activo=activo)
        else:
            d = dict(tipo=tipo, id=id_, bloqueado=modo == 'bloquear')
        if self.llamar('/api/catalogo', d, aviso='%s %s actualizado (los jugadores conectados lo ven al momento)' % (tipo, id_)): self.cargar_catalogo()

    def pest_heroes(self, f):
        m, self.t_her = self.tabla(f, ('Tipo', 'ID', 'Nombre / personaje', 'Estado'), (90, 90, 260, 260), 20); m.pack(fill='both', expand=True)
        bot = ttk.Frame(f); bot.pack(fill='x', pady=6)
        def sel():
            s = self.t_her.selection()
            if not s: messagebox.showinfo('Héroes', 'Elige un héroe o una skin.'); return None
            tipo, id_ = s[0].split(':'); return tipo, int(id_)
        for texto, modo in (('Bloquear para todos', 'bloquear'), ('Desbloquear', 'desbloquear'),
                            ('Exclusivo de colaborador (sí/no)', 'colaborador'), ('Exclusivo de campeón (sí/no)', 'campeon')):
            ttk.Button(bot, text=texto, command=lambda m=modo: (lambda x: x and self.cambiar(x[0], x[1], m))(sel())).pack(side='left', padx=2)
        def nombrar():
            x = sel()
            if not x or x[0] != 'heroe': return
            n = simpledialog.askstring('Nombre', 'Nombre para el héroe %d:' % x[1], parent=self)
            if n and self.llamar('/api/catalogo', dict(nombre_heroe=x[1], nombre=n)): self.cargar_catalogo()
        def nueva_skin():
            h = simpledialog.askinteger('Agregar skin', 'ID del héroe:', parent=self); s = h and simpledialog.askinteger('Agregar skin', 'ID de la skin:', parent=self)
            if h and s and self.llamar('/api/catalogo', dict(nueva_skin=s, heroe=h), aviso='Skin agregada'): self.cargar_catalogo()
        ttk.Button(bot, text='Poner nombre', command=nombrar).pack(side='left', padx=8)
        ttk.Button(bot, text='Agregar skin', command=nueva_skin).pack(side='left')
        ttk.Label(f, text='Bloquear un héroe o una skin lo quita a todas las cuentas; exclusivo = solo para quienes tienen ese rol. '
                          'En la ficha de cada jugador puedes darle o quitarle algo solo a él.', wraplength=1000).pack(anchor='w')

    def pintar_heroes(self):
        self.t_her.delete(*self.t_her.get_children()); nombres = self.cat.get('nombres', {})
        for h, skins in sorted(self.cat['heroes'].items(), key=lambda x: int(x[0])):
            h = int(h)
            self.t_her.insert('', 'end', iid='heroe:%d' % h, values=('Héroe', h, nombres.get(str(h), ''), self.estado_item('heroe', h)), open=True)
            for s in skins:
                self.t_her.insert('', 'end', iid='skin:%d' % s, values=('   skin', s, '  de ' + (nombres.get(str(h)) or str(h)), self.estado_item('skin', s)))

    def pest_marcos(self, f):
        m, self.t_mar = self.tabla(f, ('ID', 'Cómo se gana', 'Parámetros', 'Estado'), (70, 220, 200, 300), 20); m.pack(fill='both', expand=True)
        bot = ttk.Frame(f); bot.pack(fill='x', pady=6)
        def sel():
            s = self.t_mar.selection()
            if not s: messagebox.showinfo('Marcos', 'Elige un marco.'); return None
            return int(s[0])
        for texto, modo in (('Bloquear para todos', 'bloquear'), ('Desbloquear', 'desbloquear'),
                            ('Exclusivo de colaborador (sí/no)', 'colaborador'), ('Exclusivo de campeón (sí/no)', 'campeon')):
            ttk.Button(bot, text=texto, command=lambda m=modo: (lambda x: x and self.cambiar('marco', x, m))(sel())).pack(side='left', padx=2)
        def nuevo():
            i = simpledialog.askinteger('Marco nuevo', 'ID del marco nuevo (el mismo que tiene en HeadFrameConfig):', parent=self)
            n = i and simpledialog.askstring('Marco nuevo', 'Nombre (para reconocerlo):', parent=self)
            if i and self.llamar('/api/catalogo', dict(nuevo_marco=i, nombre=n or ''), aviso='Marco %d agregado' % i): self.cargar_catalogo()
        ttk.Button(bot, text='Agregar marco nuevo', command=nuevo).pack(side='left', padx=8)
        ttk.Button(bot, text='Actualizar lista', command=self.cargar_catalogo).pack(side='left', padx=2)
        ttk.Label(f, text='Los marcos de "puntos", "victorias" y "nivel" se ganan jugando. Los de "objeto" y "especial" solo los tiene '
                          'quien los recibe (rol o desbloqueo propio). Un marco nuevo necesita también su entrada en '
                          'HeadFrameConfig.json (pestaña Configuración) y su imagen en el juego.', wraplength=1000).pack(anchor='w')

    def pintar_marcos(self):
        self.t_mar.delete(*self.t_mar.get_children())
        for mm in sorted(self.cat['marcos'], key=lambda x: x['id']):
            desc = CONDICIONES.get(mm['condicion'], str(mm['condicion'])) + ((' - ' + mm['nombre']) if mm.get('nombre') else '')
            self.t_mar.insert('', 'end', iid=str(mm['id']), values=(mm['id'], desc, mm['parametros'], self.estado_item('marco', mm['id'])))

    # ------------------------------------------------------------------ Configuracion del juego
    def pest_config(self, f):
        izq = ttk.Frame(f); izq.pack(side='left', fill='y')
        ttk.Label(izq, text='ACTIVOS (se mandan a los teléfonos)').pack(anchor='w')
        self.l_act = tk.Listbox(izq, width=34, height=12, exportselection=False); self.l_act.pack(pady=(0, 8))
        ttk.Label(izq, text='EN ESPERA (listos, apagados)').pack(anchor='w')
        self.l_esp = tk.Listbox(izq, width=34, height=12, exportselection=False); self.l_esp.pack()
        for lb, carpeta in ((self.l_act, 'activos'), (self.l_esp, 'en_espera')):
            lb.bind('<<ListboxSelect>>', lambda e, lb=lb, c=carpeta: self.abrir_config(lb, c))
        der = ttk.Frame(f); der.pack(side='left', fill='both', expand=True, padx=(10, 0))
        self.lbl_cfg = ttk.Label(der, text='Elige un archivo'); self.lbl_cfg.pack(anchor='w')
        self.txt_cfg = tk.Text(der, wrap='none', font=('Consolas', 10), undo=True); self.txt_cfg.pack(fill='both', expand=True)
        bot = ttk.Frame(der); bot.pack(fill='x', pady=6)
        for texto, fn in (('Guardar', self.guardar_config), ('Activar / desactivar', self.mover_config), ('Archivo nuevo', self.nuevo_config),
                          ('Importar archivo…', self.importar_config), ('Borrar', self.borrar_config), ('Actualizar lista', self.listar_config)):
            ttk.Button(bot, text=texto, command=fn).pack(side='left', padx=2)
        ttk.Label(der, text='Los teléfonos descargan los cambios al entrar y los aplican al volver a abrir el juego. '
                            'Los archivos originales se sacan del OBB con tools/ifs/extraer.py.', wraplength=700).pack(anchor='w')
        self.cfg_actual = None; self.listar_config()

    def listar_config(self):
        d = self.llamar('/api/config')
        if not d: return
        for lb, k in ((self.l_act, 'activos'), (self.l_esp, 'en_espera')):
            lb.delete(0, 'end')
            for n in d[k]: lb.insert('end', n)

    def abrir_config(self, lb, carpeta):
        s = lb.curselection()
        if not s: return
        nombre = lb.get(s[0]); d = self.llamar('/api/config/%s/%s' % (carpeta, urllib.parse.quote(nombre)))
        if d:
            self.cfg_actual = (carpeta, nombre); self.lbl_cfg.config(text='%s / %s' % (carpeta, nombre))
            self.txt_cfg.delete('1.0', 'end'); self.txt_cfg.insert('1.0', d['texto'])

    def guardar_config(self):
        if not self.cfg_actual: return
        texto = self.txt_cfg.get('1.0', 'end-1c')
        if self.cfg_actual[1].lower().endswith('.json'):
            try:
                import re
                json.loads(re.sub(r'\s+//[^\n]*', '', re.sub(r'\s+/\*.*?\*/', '', ' ' + texto, flags=re.S)))
            except ValueError as e:
                if not messagebox.askyesno('JSON con errores', 'El JSON tiene un error (%s). ¿Guardar igual?' % e): return
        c, n = self.cfg_actual
        self.llamar('/api/config/%s/%s' % (c, urllib.parse.quote(n)), dict(accion='guardar', texto=texto), aviso='%s guardado' % n)

    def mover_config(self):
        if not self.cfg_actual: return
        c, n = self.cfg_actual; a = 'en_espera' if c == 'activos' else 'activos'
        if self.llamar('/api/config/%s/%s' % (c, urllib.parse.quote(n)), dict(accion='mover', a=a), aviso='%s pasado a %s' % (n, a)):
            self.cfg_actual = (a, n); self.listar_config()

    def nuevo_config(self):
        n = simpledialog.askstring('Archivo nuevo', 'Nombre (igual que en el juego, ej. ShoppingMallConfig.csv):', parent=self)
        if n and self.llamar('/api/config/en_espera/%s' % urllib.parse.quote(n), dict(accion='guardar', texto=''), aviso='%s creado en espera' % n):
            self.listar_config()

    def importar_config(self):
        ruta = filedialog.askopenfilename(filetypes=[('Configuración', '*.json *.csv *.txt'), ('Todos', '*.*')])
        if not ruta: return
        texto = open(ruta, encoding='utf-8-sig', errors='replace').read()
        n = os.path.basename(ruta)
        if self.llamar('/api/config/en_espera/%s' % urllib.parse.quote(n), dict(accion='guardar', texto=texto), aviso='%s importado (en espera)' % n):
            self.listar_config()

    def borrar_config(self):
        if self.cfg_actual and messagebox.askyesno('Borrar', '¿Borrar %s?' % self.cfg_actual[1]):
            c, n = self.cfg_actual
            if self.llamar('/api/config/%s/%s' % (c, urllib.parse.quote(n)), dict(accion='borrar'), aviso='%s borrado' % n):
                self.cfg_actual = None; self.txt_cfg.delete('1.0', 'end'); self.listar_config()

    # ------------------------------------------------------------------ Economia
    def pest_economia(self, f):
        ttk.Label(f, text='Precios y monedas (moneda del juego, nunca dinero real). Quedan guardados en el servidor; la tienda y el '
                          'pase de batalla los usarán cuando estén implementados.', wraplength=1000).pack(anchor='w', pady=(0, 8))
        self.campos_eco = {}
        grid = ttk.Frame(f); grid.pack(anchor='w')
        eco = dict(ECONOMIA_INICIAL); eco.update(self.llamar('/api/ajustes/economia') or {})
        for i, (k, v) in enumerate(eco.items()):
            ttk.Label(grid, text=k.replace('_', ' ').capitalize() + ':').grid(row=i, column=0, sticky='w', pady=2)
            if isinstance(v, bool):
                var = tk.BooleanVar(value=v); ttk.Checkbutton(grid, variable=var).grid(row=i, column=1, sticky='w')
            else:
                var = tk.StringVar(value=str(v)); ttk.Entry(grid, textvariable=var, width=12).grid(row=i, column=1, sticky='w')
            self.campos_eco[k] = var
        ttk.Button(f, text='Guardar economía', command=self.guardar_economia).pack(anchor='w', pady=10)

    def guardar_economia(self):
        eco = {}
        for k, var in self.campos_eco.items():
            v = var.get()
            if isinstance(v, bool): eco[k] = v
            else:
                try: eco[k] = int(v)
                except ValueError: messagebox.showerror('Economía', '"%s" debe ser un número.' % k); return
        self.llamar('/api/ajustes/economia', dict(valor=eco), aviso='Economía guardada')


if __name__ == '__main__':
    Panel().mainloop()
