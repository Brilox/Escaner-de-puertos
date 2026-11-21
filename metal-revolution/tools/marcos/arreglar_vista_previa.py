#!/usr/bin/env python3
"""Corrige un error del juego original: en la pantalla de marcos, la vista previa de la derecha nunca muestra el efecto
(brillo) del marco elegido, ni con los marcos originales.

    python arreglar_vista_previa.py <headframescreen.bundle> <salida.bundle>

El bundle es AssetBundles/Android/gui/prefabs/headframeprefab/headframescreen.bundle (sacarlo del OBB con
tools/ifs/extraer.py). Por que pasa (verificado en el codigo del juego, APK 1.0.23):
- HeadFrameItem.Fresh crea el efecto y lo registra con ScrollItemVisibleMono.AddObj(transform.parent, efecto,
  "ForHeadEffect", 0.1, 0.9). Ese componente es para las filas de una lista con scroll: si el padre no lo tiene, se lo
  agrega, y en cada Update calcula
      y  = padre.anchoredPosition.y + propio.anchoredPosition.y
      oculto si  y > alto_propio * 0.1   o   -(y - alto_propio * 0.9) > alto_del_abuelo
  y apaga el efecto (SetActive(false)) cuando da "oculto".
- En la vista previa "propio" es el contenedor Right (centro y = -458.5, alto 917.8) y el padre es Frame (y = 7.7):
  -(7.7 - 458.5 - 826) = 1276.8, mas que el alto de la pantalla: el efecto queda SIEMPRE apagado.
Arreglo: Right no dibuja nada (solo tiene RectTransform) y todos sus hijos estan anclados a su centro. Se le pone
alto 200 y el punto de referencia arriba (pivot y = 1), con el mismo centro: nada se mueve en la pantalla y la cuenta da
-(7.7 - 358.5 - 180) = 530.8, menor que cualquier alto de pantalla, asi que el efecto queda visible.
Requiere UnityPy."""
import sys
import UnityPy

ALTO = 200.0


def arreglar(entrada, salida):
    env = UnityPy.load(entrada)
    O = {o.path_id: o for o in env.objects}
    nombre = {o.path_id: o.read_typetree()['m_Name'] for o in env.objects if o.type.name == 'GameObject'}
    hecho = 0
    for o in env.objects:
        if o.type.name != 'RectTransform': continue
        t = o.read_typetree()
        if nombre.get(t['m_GameObject']['m_PathID']) != 'Right': continue
        padre = t['m_Father']['m_PathID']
        if not padre or nombre.get(O[padre].read_typetree()['m_GameObject']['m_PathID']) != 'Frame': continue
        if t['m_AnchorMin'] != t['m_AnchorMax']: raise SystemExit('Right no tiene anclas en un punto: el bundle no es el esperado')
        for h in t['m_Children']:                       # los hijos tienen que estar anclados al centro para no moverse
            ht = O[h['m_PathID']].read_typetree()
            if (ht['m_AnchorMin']['y'], ht['m_AnchorMax']['y']) != (0.5, 0.5):
                raise SystemExit('un hijo de Right no esta anclado al centro: no se toca')
        alto, py, y = t['m_SizeDelta']['y'], t['m_Pivot']['y'], t['m_AnchoredPosition']['y']
        centro = y + (0.5 - py) * alto
        t['m_SizeDelta'] = dict(t['m_SizeDelta'], y=ALTO)
        t['m_Pivot'] = dict(t['m_Pivot'], y=1.0)
        t['m_AnchoredPosition'] = dict(t['m_AnchoredPosition'], y=centro + ALTO / 2)
        o.save_typetree(t); hecho += 1
        print('Right: alto %.1f -> %.1f, pivot y %.2f -> 1, posicion y %.1f -> %.1f (centro %.1f, sin cambios)'
              % (alto, ALTO, py, y, centro + ALTO / 2, centro))
    if hecho != 1: raise SystemExit('no encontre el contenedor Right de la vista previa (%d)' % hecho)
    open(salida, 'wb').write(env.file.save(packer='original'))


if __name__ == '__main__':
    if len(sys.argv) != 3: print(__doc__); sys.exit(2)
    arreglar(sys.argv[1], sys.argv[2])
