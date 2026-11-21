#!/usr/bin/env python3
"""Archivos de configuracion del juego que el servidor reemplaza en los telefonos.

El juego trae sus configuraciones (que modos estan abiertos y a que hora, la tienda, las misiones...) dentro del OBB,
pero acepta versiones nuevas que le mande el servidor. Es el mecanismo que usaba el servidor oficial para cambiar
cosas sin sacar una actualizacion. El flujo (leido del codigo del juego, ConfigHashNetworkHandler / ConfigManager):

  1. Servidor -> NotifySvrConfigReload{Reload=true, HashAll}   (si HashAll es distinto del que tiene guardado el telefono)
  2. Telefono -> QueryAllConfigHashReq
     Servidor -> QueryAllConfigHashRsp{HashPairs=[{FileName, Hash}]}
     Para cada archivo, si Hash no coincide ni con su copia original ni con la que ya descargo, lo pide:
  3. Telefono -> DownloadConfigReq{Key=FileName}
     Servidor -> DownloadConfigRsp{Content}
     El telefono lo guarda en su carpeta de datos y desde entonces lo usa en vez del original.

FileName es el nombre corto del archivo (sin carpeta), por ejemplo "OpenSystemConfig.json".

Detalle importante: antes de guardar, el telefono "desescapa" el texto (StringUtils.JsonFromServer): cambia \\" por ",
\\\\ por \\, \\n por salto de linea, \\r, \\b, \\f y \\t. Por eso los JSON se mandan sin ninguna de esas secuencias
(se reescriben con \\u00XX, que el lector JSON del juego entiende igual).

Uso: los archivos que esten en config_juego/activos/ se mandan a todos los telefonos al entrar.
Los de config_juego/en_espera/ estan listos pero NO se mandan: para activarlos basta moverlos a activos/ y
reiniciar el servidor. Si activos/ esta vacio, el servidor no manda nada y el juego usa sus archivos originales."""
import hashlib, json, logging, os, re

log = logging.getLogger('mr.config')
HERE = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(HERE, 'config_juego', 'activos')
EXTENSIONES = ('.json', '.csv', '.txt')
_ESCAPE = re.compile(r'\\(["\\/bfnrt])')
_PELIGRO = re.compile(r'\\["\\nrbft]')


def json_para_telefono(obj):
    """JSON sin secuencias que JsonFromServer alteraria: \\" \\\\ \\n ... pasan a \\u00XX."""
    texto = json.dumps(obj, ensure_ascii=False, indent='\t')
    return _ESCAPE.sub(lambda m: '\\u%04x' % ord(json.loads('"\\%s"' % m.group(1))), texto)


def quitar_comentarios(texto):
    """Los JSON del juego llevan comentarios // y /* */; el juego los quita asi (ConfigManager.lua) antes de leerlos."""
    if texto.startswith('/'): texto = ' ' + texto
    texto = re.sub(r'\s+/\*.*?\*/', '', texto, flags=re.S)
    return re.sub(r'\s+//[^\n]*', '', texto)


def como_lo_lee_el_telefono(contenido):
    """Lo mismo que hace StringUtils.JsonFromServer en el telefono (para las pruebas)."""
    for a, b in (('\\"', '"'), ('\\\\', '\\'), ('\\n', '\n'), ('\\r', '\r'), ('\\b', '\b'), ('\\f', '\f'), ('\\t', '\t')):
        contenido = contenido.replace(a, b)
    return contenido


class ConfigJuego:
    def __init__(self, carpeta=CARPETA):
        self.carpeta = carpeta
        self.archivos = {}                                   # nombre en minusculas -> (nombre, contenido, hash)
        if os.path.isdir(carpeta):
            for nombre in sorted(os.listdir(carpeta)):
                if nombre.startswith(('.', '_')) or not nombre.lower().endswith(EXTENSIONES): continue
                self._cargar(nombre)
        self.hash_total = hashlib.md5(''.join('%s=%s;' % (n, h) for n, _, h in self.archivos.values()).encode()).hexdigest()
        if self.archivos:
            log.info('configuraciones que se mandan a los telefonos: %s', ', '.join(n for n, _, _ in self.archivos.values()))

    def _cargar(self, nombre):
        ruta = os.path.join(self.carpeta, nombre)
        try:
            crudo = open(ruta, 'rb').read()
            try: texto = crudo.decode('utf-8-sig')
            except UnicodeDecodeError:          # algunos csv traen notas en chino en otra codificacion: el juego las lee igual de mal
                texto = crudo.decode('utf-8-sig', 'replace'); log.warning('%s no es UTF-8: se manda con los caracteres raros reemplazados', nombre)
            if nombre.lower().endswith('.json'):
                contenido = json_para_telefono(json.loads(quitar_comentarios(texto)))
            else:
                contenido = texto.replace('\r\n', '\n')
                if _PELIGRO.search(contenido):
                    log.error('%s tiene barras invertidas (\\n, \\t, \\"...) que el telefono cambiaria: no se manda', nombre); return
        except Exception as e:
            log.error('no pude leer la configuracion %s: %s (no se manda)', nombre, e); return
        h = hashlib.md5(contenido.encode('utf-8')).hexdigest()
        self.archivos[nombre.lower()] = (nombre, contenido, h)

    def aviso(self):
        """El aviso que se manda al entrar, o None si no hay nada que reemplazar."""
        return dict(Reload=True, HashAll=self.hash_total) if self.archivos else None

    def pares(self):
        return [dict(FileName=n, Hash=h) for n, _, h in self.archivos.values()]

    def contenido(self, clave):
        """clave puede venir con o sin carpeta y con otra capitalizacion."""
        corto = (clave or '').replace('\\', '/').rsplit('/', 1)[-1].lower()
        a = self.archivos.get(corto)
        return a[1] if a else None
