#!/usr/bin/env python3
"""Reemplaza la imagen de una textura que ya existe en un bundle del juego (fondo de inicio de sesion, logo...).

    python reemplazar_imagen.py <entrada.bundle> <salida.bundle> <nombre_textura>=<imagen.png> [...]

Se mantiene todo igual (nombre, tamano, formato de compresion, sprites que la usan): solo cambian los pixeles, asi el
juego la sigue encontrando donde siempre. La imagen se ajusta al tamano de la textura original si no coincide.
Usado para la pantalla de inicio de sesion de Metal Online:
  gui/textures/arranged/settingsscreen_common/mainbg_dontmove.bundle  MainBg_DontMove (1920x1080, ETC2 RGB)
  gui/prefabs/logo.bundle                                             logo_中文_FullPixel y logo_英文_FullPixel (512x181)"""
import sys
import UnityPy
from PIL import Image


def reemplazar(entrada, salida, cambios):
    env = UnityPy.load(entrada); hechos = []
    for o in env.objects:
        if o.type.name != 'Texture2D': continue
        t = o.read()
        if t.m_Name not in cambios: continue
        img = Image.open(cambios[t.m_Name]).convert('RGBA')
        if img.size != (t.m_Width, t.m_Height): img = img.resize((t.m_Width, t.m_Height), Image.LANCZOS)
        fmt = t.m_TextureFormat
        tt = o.read_typetree(); tt['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}; tt['m_MipCount'] = 1
        o.save_typetree(tt); t = o.read()
        t.set_image(img, target_format=fmt, mipmap_count=1); t.save()
        hechos.append((t.m_Name, t.m_Width, t.m_Height, fmt))
    faltan = set(cambios) - {h[0] for h in hechos}
    if faltan: raise SystemExit('no encontre estas texturas en %s: %s' % (entrada, sorted(faltan)))
    open(salida, 'wb').write(env.file.save(packer='original'))
    return hechos


if __name__ == '__main__':
    if len(sys.argv) < 4: print(__doc__); sys.exit(2)
    cambios = dict(a.split('=', 1) for a in sys.argv[3:])
    for h in reemplazar(sys.argv[1], sys.argv[2], cambios): print('  reemplazada %s %dx%d formato %s' % h)
