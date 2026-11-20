#!/usr/bin/env python3
"""Actualizaciones del juego desde el servidor (marcos, skins, imagenes, configuracion...): un solo archivo .mrupd.

FORMATO DEL PAQUETE (.mrupd = zip), siempre el mismo sin importar lo que traiga:
    manifest.json
        {"formato": 1, "version": 1, "nombre": "Marcos beta", "mensaje": "texto para los jugadores",
         "obligatoria": true, "creado": 1763600000,
         "telefono": [{"ruta": "AssetBundles/Android/.../headframe.bundle", "md5": "...", "tamano": 123}],
         "servidor": {"config": ["HeadFrameConfig.json"], "marcos": true, "marcos_extra": [{"id": 100, "nombre": "Founder"}]}}
    telefono/<ruta>        archivos que van a la carpeta del juego en el telefono
                           (Android/data/com.gtarcade.next.mrglo/files/<ruta>)
    servidor/config/<x>    configuraciones que el servidor manda a los telefonos (config_juego/activos)
    servidor/marcos.json   reglas de los marcos (datos/marcos.json)
Se arma con tools/actualizacion/crear_actualizacion.py y se sube desde el panel (pestana Actualizaciones).

COMO LLEGA AL TELEFONO (sin modificar el cliente):
el juego trae el actualizador de Tencent (GCloud Dolphin) y el mod lo apunta a este servidor (updateUrlRelease).
Al abrir el juego pregunta por TGCP / Pebble RPC "VersionUpdate:ReqUpdateVersion". Antes se respondia siempre
"sin actualizacion" con un mensaje grabado; ahora, si hay una actualizacion publicada, se responde con la version
nueva, update_type = 2 (obligatoria) y http_url hacia el servidor HTTP de descargas (este modulo).
Estructura Thrift (reconstruida de libgcloud.so, funciones write de version_service):
    ResVersionUpdate   {1: i32 result, 2: UpdateCommInfo comm_info, 3: VersionUpdateInfo update_info, 4: string app_id,
                        5: i32 region_id, 6: CustomCfg custom_cfg, 7: VersionAttr src_attr}
    VersionUpdateInfo  {1: VersionPackageInfo package_info, 2: i32 update_type (0 no, 1 opcional, 2 obligatoria),
                        3: i32 verify_signature}
    VersionPackageInfo {1: i64 version, 2: string name, 3: string description, 4: string http_url, 5: string md5sum,
                        6: string custom_str}
    La version es de 4 numeros de 16 bits: 1.0.21.1116 = 0x0001_0000_0015_045C (la del juego). La actualizacion N
    publica la version de recursos 1.0.0.(1 + N) (el telefono reporta res 1.0.0.1).
El actualizador pregunta dos veces: etapa 1 (programa/APK, siempre "sin actualizacion") y etapa 2 (recursos).
En la etapa 2 se responde: name = "filelist.json", http_url = .../filelist.json y md5sum = MD5 de esa lista
(el telefono la descarga y comprueba el MD5). La lista (formato leido de libgcloud.so, listfile_parser):
    {"filelist": [{"url": ..., "bkurl": ..., "md5": ..., "filename": ..., "filesize": N, "ver": "1.0.0.2"}]}
apunta a un IFS COMPLETO (el first_source.png del OBB con los archivos cambiados, tools/ifs/escribir_ifs.py).
El telefono compara el MD5 de cada archivo con los que ya tiene y descarga por rangos (HTTP Range) solo lo que
cambio. El IFS se arma en el servidor al publicar, a partir del OBB (--obb, o un .obb en la carpeta del servidor).

BLOQUEO DE ENTRADA: con "obligatoria" activado en el panel, quien no tenga la ultima version no entra al juego
(LoginRequest -> Error con el mensaje). Se considera actualizado al telefono (por IP) que pidio la version y
reporto la nueva, o que descargo todos los archivos del paquete."""
import asyncio, hashlib, json, logging, os, shutil, struct, time, zipfile
from collections import deque
from urllib.parse import unquote, urlsplit

log = logging.getLogger('mr.actualizaciones')
HERE = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(HERE, 'actualizaciones')
VERSION_BASE = (1, 0, 0, 1)                           # version de RECURSOS del juego ("res v: 1.0.0.1" en el logcat)
VERSION_APP = (1, 0, 21, 1116)                        # version del programa (APK): nunca se ofrece una nueva
ETAPA_PROGRAMA, ETAPA_RECURSOS = 1, 2                 # campo 3 de la peticion (m_update_type 20 y 21 en el telefono)

def version_i64(n):
    a, b, c, d = VERSION_BASE; d += n
    return (a << 48) | (b << 32) | (c << 16) | d
def version_txt(v):
    return '%d.%d.%d.%d' % ((v >> 48) & 0xFFFF, (v >> 32) & 0xFFFF, (v >> 16) & 0xFFFF, v & 0xFFFF)

# ---------------------------------------------------------------------------------------------- Thrift binario
class T:
    STOP, BOOL, BYTE, I16, I32, I64, STRING, STRUCT, LIST = 0, 2, 3, 6, 8, 10, 11, 12, 15
def t_campo(tipo, fid, valor):
    h = struct.pack('>bh', tipo, fid)
    if tipo == T.I32: return h + struct.pack('>i', valor)
    if tipo == T.I64: return h + struct.pack('>q', valor)
    if tipo == T.STRING: b = valor.encode('utf-8'); return h + struct.pack('>i', len(b)) + b
    if tipo == T.STRUCT: return h + valor + b'\x00'
    raise ValueError(tipo)

def t_leer(b, i=0, prof=0):
    """Lee un struct Thrift binario a un dict {id: valor} (para anotar lo que manda el telefono)."""
    out = {}
    while i < len(b):
        tipo = b[i]; i += 1
        if tipo == T.STOP: return out, i
        fid = struct.unpack_from('>h', b, i)[0]; i += 2
        v, i = t_valor(b, i, tipo, prof)
        out[fid] = v
    return out, i
def t_valor(b, i, tipo, prof):
    if tipo == T.BOOL or tipo == T.BYTE: return b[i], i + 1
    if tipo == T.I16: return struct.unpack_from('>h', b, i)[0], i + 2
    if tipo == T.I32: return struct.unpack_from('>i', b, i)[0], i + 4
    if tipo == T.I64: return struct.unpack_from('>q', b, i)[0], i + 8
    if tipo == 4: return struct.unpack_from('>d', b, i)[0], i + 8
    if tipo == T.STRING:
        n = struct.unpack_from('>i', b, i)[0]; s = b[i + 4:i + 4 + n]
        try: s = s.decode('utf-8')
        except UnicodeDecodeError: s = s.hex()
        return s, i + 4 + n
    if tipo == T.STRUCT: return t_leer(b, i, prof + 1)
    if tipo in (T.LIST, 14):
        et = b[i]; n = struct.unpack_from('>i', b, i + 1)[0]; i += 5; l = []
        for _ in range(n): v, i = t_valor(b, i, et, prof); l.append(v)
        return l, i
    if tipo == 13:
        kt, vt = b[i], b[i + 1]; n = struct.unpack_from('>i', b, i + 2)[0]; i += 6; m = {}
        for _ in range(n): k, i = t_valor(b, i, kt, prof); v, i = t_valor(b, i, vt, prof); m[str(k)] = v
        return m, i
    raise ValueError('tipo Thrift %d' % tipo)

METODO = b'VersionUpdate:ReqUpdateVersion'

def leer_peticion(extra):
    """Del paquete TGCP de la peticion saca el struct de argumentos (ReqVersionUpdate) como dict, si se puede."""
    k = extra.find(METODO)
    if k < 0: return None
    i = k + len(METODO) + 1 + 8                                   # tipo de mensaje + secuencia (como la respuesta grabada)
    for salto in (0, -4, 4):                                      # por si la secuencia no mide 8 bytes
        try:
            d, _ = t_leer(extra, i + salto)
            if d: return d
        except Exception: pass
    return None

# ---------------------------------------------------------------------------------------------- gestor
class Actualizaciones:
    def __init__(self, juego, host, puerto_http, blob_sin_actualizacion, tgcp_set_extra_len, obb=None):
        self.juego = juego; self.host = host; self.puerto_http = puerto_http; self.obb = obb
        self.preparacion = {}                                     # version -> dict(estado, texto)
        self.plantilla = blob_sin_actualizacion; self.set_extra = tgcp_set_extra_len
        self.clientes = {}                                        # ip -> estado del telefono
        self.registro = deque(maxlen=400)                          # peticiones HTTP y de version, para el panel
        os.makedirs(CARPETA, exist_ok=True)
        self.reaplicar()
        v = self.ajuste('vigente', 0)
        if v: self.preparar(int(v))

    # ---- IFS completo para el actualizador de Tencent (etapa de recursos)
    def buscar_obb(self):
        if self.obb: return self.obb if os.path.isfile(self.obb) else None
        for d in (HERE, os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')):
            try: cands = sorted(f for f in os.listdir(d) if f.lower().endswith('.obb'))
            except OSError: continue
            if cands: return os.path.abspath(os.path.join(d, cands[0]))
        return None

    def archivos_recursos(self, v):
        d = os.path.join(CARPETA, str(v), 'recursos')
        return d, os.path.join(d, 'metalonline_res_%d.ifs' % v), os.path.join(d, 'filelist.json')

    def preparar(self, v):
        """Arma (en segundo plano) el IFS completo y la lista para la version v, si no estan ya."""
        d, ifs, lista = self.archivos_recursos(v)
        if os.path.isfile(lista) and os.path.isfile(ifs):
            self.preparacion[v] = dict(estado='listo', texto='paquete listo (%.0f MB)' % (os.path.getsize(ifs) / 1e6)); return
        if self.preparacion.get(v, {}).get('estado') == 'construyendo': return
        import threading
        self.preparacion[v] = dict(estado='construyendo', texto='armando el paquete del juego...')
        threading.Thread(target=self._construir, args=(v,), daemon=True).start()

    def _construir(self, v):
        d, ifs, lista = self.archivos_recursos(v)
        try:
            obb = self.buscar_obb()
            if not obb: raise RuntimeError('no encuentro el OBB del juego: copia main.1300.com.gtarcade.next.mrglo.obb en la carpeta server '
                                           '(o arranca con --obb <ruta>) y vuelve a publicar')
            m = json.load(open(os.path.join(CARPETA, str(v), 'manifest.json'), encoding='utf-8'))
            sys_path = os.path.join(HERE, '..', 'tools', 'ifs')
            import sys
            if sys_path not in sys.path: sys.path.insert(0, sys_path)
            from extraer import abrir
            from ifs import IFS
            import escribir_ifs
            reemplazos = {}
            for f in m.get('telefono', []):
                reemplazos[f['ruta']] = open(os.path.join(CARPETA, str(v), 'telefono', *f['ruta'].split('/')), 'rb').read()
            os.makedirs(d, exist_ok=True)
            fh, base = abrir(obb)
            try:
                original = IFS(fh, base)
                t0 = time.time(); log.info('actualizacion %d: armando el paquete completo desde %s', v, obb)
                r = escribir_ifs.rehacer(original, reemplazos, ifs + '.tmp')
            finally:
                fh.close()
            os.replace(ifs + '.tmp', ifs)
            url = 'http://%s:%d/mo/actualizacion/%d/%s' % (self.host, self.puerto_http, v, os.path.basename(ifs))
            item = dict(url=url, bkurl=url, md5=r['md5'], filename=os.path.basename(ifs), filesize=r['tamano'],
                        ver=version_txt(version_i64(v)))
            open(lista + '.tmp', 'w', encoding='utf-8').write(json.dumps(dict(filelist=[item]), ensure_ascii=False))
            os.replace(lista + '.tmp', lista)
            self.preparacion[v] = dict(estado='listo', texto='paquete listo (%.0f MB, %.0f s)' % (r['tamano'] / 1e6, time.time() - t0))
            log.info('actualizacion %d: paquete listo %s (%d bytes, md5 %s)', v, ifs, r['tamano'], r['md5'])
        except Exception as e:
            self.preparacion[v] = dict(estado='error', texto=str(e)); log.error('actualizacion %d: no pude armar el paquete: %s', v, e)

    def reaplicar(self):
        """Al arrancar vuelve a poner la parte del servidor de las versiones ya instaladas (HeadFrameConfig.json en
        config_juego/activos, datos/marcos.json...). Asi, reemplazar la carpeta del servidor por una version nueva del
        repositorio no borra los marcos nuevos: basta conservar cuentas.db y la carpeta actualizaciones/."""
        for v in self.ajuste('aplicadas', []) or []:
            try: self.aplicar_servidor(int(v), silencioso=True)
            except Exception as e: log.warning('no pude volver a aplicar la actualizacion %s: %s', v, e)

    # ---- estado guardado en los ajustes del servidor (cuentas.db)
    def ajuste(self, clave, defecto=None): return self.juego.cuentas.ajuste('actualizacion_' + clave, defecto)
    def poner(self, clave, valor): self.juego.cuentas.poner_ajuste('actualizacion_' + clave, valor)
    def publicada(self):
        """La actualizacion vigente (manifest) o None."""
        v = self.ajuste('vigente', 0)
        if not v: return None
        try: return json.load(open(os.path.join(CARPETA, str(v), 'manifest.json'), encoding='utf-8'))
        except (OSError, ValueError): return None
    def instaladas(self):
        out = []
        for d in sorted(os.listdir(CARPETA), key=lambda x: int(x) if x.isdigit() else 0):
            try: out.append(json.load(open(os.path.join(CARPETA, d, 'manifest.json'), encoding='utf-8')))
            except (OSError, ValueError): pass
        return out
    def anotar(self, tipo, ip, texto):
        self.registro.append(dict(fecha=int(time.time()), tipo=tipo, ip=ip, texto=texto)); log.info('actualizacion %s %s %s', tipo, ip, texto)

    # ---- instalar un paquete .mrupd
    def instalar(self, ruta_zip, activar=True):
        with zipfile.ZipFile(ruta_zip) as z:
            m = json.loads(z.read('manifest.json').decode('utf-8'))
            assert m.get('formato') == 1, 'formato de actualizacion desconocido'
            v = int(m['version']); assert v > 0, 'version invalida'
            destino = os.path.join(CARPETA, str(v))
            if os.path.exists(destino): shutil.rmtree(destino)
            for n in z.namelist():
                if n.endswith('/'): continue
                assert not n.startswith('/') and '..' not in n.split('/'), 'ruta peligrosa en el paquete: ' + n
                p = os.path.join(destino, *n.split('/')); os.makedirs(os.path.dirname(p), exist_ok=True)
                with z.open(n) as src, open(p, 'wb') as dst: shutil.copyfileobj(src, dst)
        for f in m.get('telefono', []):                              # comprobar que esta todo y sano
            p = os.path.join(destino, 'telefono', *f['ruta'].split('/'))
            assert os.path.getsize(p) == f['tamano'], 'tamano distinto: ' + f['ruta']
            assert md5(p) == f['md5'], 'md5 distinto: ' + f['ruta']
        log.info('actualizacion %d instalada: %s (%d archivos para el telefono)', v, m.get('nombre'), len(m.get('telefono', [])))
        if activar: self.activar(v)
        return m

    def activar(self, v):
        """Publica la version v: el servidor aplica su parte y empieza a ofrecerla a los telefonos."""
        m = self.aplicar_servidor(v)
        self.poner('vigente', v)
        if 'obligatoria' in m and self.ajuste('obligatoria') is None: self.poner('obligatoria', bool(m['obligatoria']))
        log.info('actualizacion %d publicada (version de recursos %s)', v, version_txt(version_i64(v)))
        self.preparar(v)

    def aplicar_servidor(self, v, silencioso=False):
        """Solo la parte del servidor de la version v (configuraciones, reglas de marcos, catalogo). "Retirar" no la deshace."""
        destino = os.path.join(CARPETA, str(v)); m = json.load(open(os.path.join(destino, 'manifest.json'), encoding='utf-8'))
        sv = m.get('servidor', {})
        import config_juego, juego as modjuego
        for nombre in sv.get('config', []):
            os.makedirs(config_juego.CARPETA, exist_ok=True)
            shutil.copyfile(os.path.join(destino, 'servidor', 'config', nombre), os.path.join(config_juego.CARPETA, nombre))
        if sv.get('marcos'):
            shutil.copyfile(os.path.join(destino, 'servidor', 'marcos.json'), os.path.join(HERE, '..', 'datos', 'marcos.json'))
            modjuego.MARCOS[:] = [tuple(x) for x in json.load(open(os.path.join(HERE, '..', 'datos', 'marcos.json')))]
        if sv.get('marcos_extra'):
            extra = {x['id']: x for x in (self.juego.cuentas.ajuste('marcos_extra', []) or [])}
            for x in sv['marcos_extra']: extra[int(x['id'])] = dict(id=int(x['id']), nombre=x.get('nombre', ''))
            self.juego.cuentas.poner_ajuste('marcos_extra', sorted(extra.values(), key=lambda x: x['id']))
        self.juego.config = config_juego.ConfigJuego()
        aplicadas = [int(x) for x in self.ajuste('aplicadas', []) or [] if int(x) != v] + [v]
        if not silencioso: self.poner('aplicadas', aplicadas)
        if silencioso: log.info('actualizacion %d: parte del servidor aplicada otra vez', v)
        return m

    def retirar(self):
        self.poner('vigente', 0); log.info('actualizaciones retiradas: los telefonos ya no reciben ninguna')

    # ---- estado de cada telefono
    def cliente(self, ip):
        return self.clientes.setdefault(ip, dict(ip=ip, version=None, descargados=set(), ultima_consulta=0, peticion=None))
    def al_dia(self, ip):
        m = self.publicada()
        if not m: return True
        c = self.clientes.get(ip)
        if not c: return False
        return c['version'] is not None and c['version'] >= version_i64(int(m['version']))

    def bloquear_login(self, ip):
        """Mensaje de error si el telefono debe actualizar antes de entrar, o None."""
        m = self.publicada()
        if not m or not self.ajuste('obligatoria', False) or self.al_dia(ip): return None
        return (m.get('mensaje') or 'Hay una actualizacion obligatoria.') + \
            ' Cierra el juego y vuelve a abrirlo para descargarla (version %s).' % version_txt(version_i64(int(m['version'])))

    # ---- respuesta al actualizador de Tencent
    def respuesta_version(self, ip, pkt, extra):
        """Bytes de respuesta a VersionUpdate:ReqUpdateVersion (o la grabada "sin actualizacion")."""
        c = self.cliente(ip); c['ultima_consulta'] = int(time.time())
        pet = leer_peticion(extra); c['peticion'] = pet
        # la peticion llega como {1: {1: {1:?, 2:servicio 10003, 3:etapa, 4:?, 5:version app, 6:version recursos, 7:uuid, 8:juego}, 2:''}}
        com = (pet or {}).get(1, {})
        if isinstance(com, dict) and isinstance(com.get(1), dict): com = com[1]
        if not isinstance(com, dict): com = {}
        etapa = com.get(3); version_app = com.get(5); version_cliente = com.get(6)
        txt = lambda v: version_txt(v) if isinstance(v, int) and v else v
        self.anotar('version', ip, 'peticion: etapa=%s (%s) app=%s recursos=%s' % (
            etapa, {1: 'programa/APK', 2: 'recursos'}.get(etapa, '?'), txt(version_app), txt(version_cliente)))
        m = self.publicada()
        # Etapa 1 = actualizacion del PROGRAMA (APK). Si aqui se ofrece algo, el telefono lo trata como una APK nueva y
        # muestra "Connection Error. Please Get the Latest Version of the App" (prueba real del 19/11). Nunca se ofrece.
        if etapa != ETAPA_RECURSOS:
            return self.plantilla
        if isinstance(version_cliente, int) and version_cliente: c['version'] = version_cliente
        if not m or self.al_dia(ip):
            return self.plantilla
        n = int(m['version']); v = version_i64(n)
        prep = self.preparacion.get(n, {})
        if prep.get('estado') != 'listo':
            self.anotar('version', ip, 'actualizacion %d todavia no esta lista (%s): respondo sin actualizacion' % (n, prep.get('texto', '?')))
            return self.plantilla
        _, _, lista = self.archivos_recursos(n)
        url = 'http://%s:%d/mo/actualizacion/%d/filelist.json' % (self.host, self.puerto_http, n)
        paquete = (t_campo(T.I64, 1, v) + t_campo(T.STRING, 2, 'filelist.json') +
                   t_campo(T.STRING, 3, m.get('mensaje', '')) + t_campo(T.STRING, 4, url) +
                   t_campo(T.STRING, 5, md5(lista)) + t_campo(T.STRING, 6, ''))
        info = t_campo(T.STRUCT, 1, paquete) + t_campo(T.I32, 2, 2 if self.ajuste('obligatoria', False) else 1)
        res = t_campo(T.I32, 1, 0) + t_campo(T.STRUCT, 3, info)
        cuerpo = t_campo(T.STRUCT, 0, res) + b'\x00'                # VersionUpdate_ReqUpdateVersion_result {0: success}
        # cabecera TGCP + Pebble de la respuesta grabada, con el Thrift nuevo
        n = struct.unpack_from('>I', self.plantilla, 1)[0]; frame, ex = self.plantilla[:n], self.plantilla[n:]
        k = ex.find(METODO); ini = k + len(METODO) + 1 + 8
        nuevo = ex[:ini] + cuerpo
        self.anotar('version', ip, 'respuesta: actualizacion %s obligatoria=%s url=%s' % (version_txt(v), bool(self.ajuste('obligatoria', False)), url))
        return self.set_extra(frame, len(nuevo)) + nuevo

    # ---- servidor HTTP de descargas (solo lectura)
    async def http(self, reader, writer):
        ip = (writer.get_extra_info('peername') or ('?',))[0]
        try:
            cab = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 20)
            lineas = cab.decode('latin-1').split('\r\n'); metodo, ruta, _ = (lineas[0].split(' ') + ['', ''])[:3]
            h = {k.strip().lower(): v.strip() for k, v in (l.split(':', 1) for l in lineas[1:] if ':' in l)}
            self.anotar('http', ip, '%s %s range=%s ua=%s' % (metodo, ruta, h.get('range', ''), h.get('user-agent', '')[:80]))
            codigo, tipo, datos = self.servir(ip, unquote(urlsplit(ruta).path), h)
            archivo = datos if isinstance(datos, str) else None          # ruta de un archivo grande: se manda por partes
            total = os.path.getsize(archivo) if archivo else len(datos); a, b = 0, total - 1; parcial = ''
            if codigo == 200 and h.get('range', '').startswith('bytes='):
                ra, _, rb = h['range'][6:].split(',')[0].strip().partition('-')
                if ra == '': a, b = max(0, total - int(rb)), total - 1                 # "bytes=-N": los ultimos N
                else: a = int(ra); b = min(int(rb), total - 1) if rb else total - 1
                codigo = 206; parcial = 'Content-Range: bytes %d-%d/%d\r\n' % (a, b, total)
            largo = max(0, b - a + 1)
            writer.write(('HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nAccept-Ranges: bytes\r\n%sConnection: close\r\n\r\n'
                          % (codigo, {200: 'OK', 206: 'Partial Content'}.get(codigo, 'Not Found'), tipo, largo, parcial)).encode())
            if metodo != 'HEAD':
                if archivo:
                    with open(archivo, 'rb') as fa:
                        fa.seek(a); falta = largo
                        while falta > 0:
                            trozo = fa.read(min(1 << 20, falta))
                            if not trozo: break
                            writer.write(trozo); falta -= len(trozo); await writer.drain()
                    self.cliente(ip)['descargados'].add('%s [%d-%d]' % (os.path.basename(archivo), a, b))
                else:
                    writer.write(datos[a:b + 1])
            await writer.drain()
        except Exception as e:
            log.info('http %s: %s', ip, e)
        finally:
            try: writer.close()
            except Exception: pass

    def servir(self, ip, ruta, h):
        partes = [p for p in ruta.split('/') if p]
        if len(partes) >= 3 and partes[:2] == ['mo', 'actualizacion'] and partes[2].isdigit():
            base = os.path.join(CARPETA, partes[2]); resto = partes[3:]
            if not resto or resto == ['manifest.json']:
                return 200, 'application/json', open(os.path.join(base, 'manifest.json'), 'rb').read()
            if len(resto) == 1 and partes[2].isdigit():
                _, ifs, lista = self.archivos_recursos(int(partes[2]))
                if resto[0] == 'filelist.json' and os.path.isfile(lista):
                    return 200, 'application/json', open(lista, 'rb').read()
                if resto[0] == os.path.basename(ifs) and os.path.isfile(ifs):
                    return 200, 'application/octet-stream', ifs
            if resto[0] == 'telefono' and '..' not in resto:
                p = os.path.join(base, *resto)
                if os.path.isfile(p):
                    self.cliente(ip)['descargados'].add('/'.join(resto[1:]))
                    return 200, 'application/octet-stream', open(p, 'rb').read()
        self.anotar('http', ip, 'NO EXISTE %s (el telefono pide algo que todavia no servimos)' % ruta)
        return 404, 'text/plain', b'no existe'

    def estado(self):
        m = self.publicada()
        return dict(vigente=m, obligatoria=bool(self.ajuste('obligatoria', False)), instaladas=self.instaladas(),
                    preparacion={str(k): x for k, x in self.preparacion.items()}, obb=self.buscar_obb(),
                    url_descargas='http://%s:%d/mo/actualizacion/' % (self.host, self.puerto_http),
                    clientes=[dict(c, descargados=sorted(c['descargados']), al_dia=self.al_dia(c['ip']),
                                   version=version_txt(c['version']) if isinstance(c['version'], int) else None)
                              for c in self.clientes.values()],
                    registro=list(self.registro)[-200:])

def md5(ruta):
    h = hashlib.md5()
    with open(ruta, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

async def iniciar(gestor, escucha, puerto):
    s = await asyncio.start_server(gestor.http, escucha, puerto)
    log.info('descargas de actualizaciones: http://%s:%d/mo/actualizacion/ (abre este puerto TCP en el firewall)', gestor.host, puerto)
    return s
