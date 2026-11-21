# Configuraciones del juego que manda el servidor

El juego trae sus configuraciones (qué modos están abiertos y a qué hora, la tienda, las misiones, los objetos...)
dentro del OBB, pero **acepta versiones nuevas que le mande el servidor**: era el mecanismo que usaba el servidor
oficial para cambiar cosas sin sacar una actualización. Este servidor lo implementa (`../config_juego.py`).

- `activos/`: lo que se manda a **todos** los teléfonos al entrar:
  - `OpenSystemConfig.json`: abre la 1v1 clasificatoria y la 2v2 sin fechas ni horario. El 3v3 (clasificatoria y
    rápida) queda **cerrado** con una fecha vencida hasta resolver su desincronización: para abrirlo, borra sus
    líneas `beginTime` y `endTime`.
  - `RankMatchConfig.json` (el de la versión 1.0.23): igual al original salvo `limitLevel` = 1 (antes pedía nivel 8
    para la 1v1 clasificatoria).
- `en_espera/`: archivos listos pero **apagados** (no se mandan). Para encender uno: moverlo a `activos/` y
  reiniciar el servidor. Para apagarlo: sacarlo de `activos/`.

El nombre del archivo tiene que ser el mismo que usa el juego (por ejemplo `OpenSystemConfig.json`,
`ShoppingMallConfig.csv`), con mayúsculas y minúsculas iguales.

## Cómo lo recibe el teléfono

1. Al entrar, el teléfono recibe el aviso, pide la lista y descarga lo que cambió (se ve en el log:
   `descarga la configuracion OpenSystemConfig.json`).
2. Lo guarda en su memoria y **desde ese momento usa esa versión**, también sin servidor.
3. **La primera vez hay que cerrar el juego del todo y volver a abrirlo**: el menú principal puede haber leído la
   configuración vieja antes de que terminara la descarga.

Para volver a la configuración de fábrica en un teléfono: borrar los datos de la app (o reinstalar), o mandar
desde `activos/` el archivo original sin cambios.

## De dónde sacar los archivos originales (para modificarlos)

Con la herramienta `tools/ifs/extraer.py` y el OBB **de tu propio teléfono** (así coincide con tu versión del juego):

```
pip install UnityPy cryptography
python tools/ifs/extraer.py main.1300.com.gtarcade.next.mrglo.obb salida
```

En `salida/config_txt/` quedan los ~87 archivos (`ShoppingMallConfig.csv`, `ItemConfig.csv`, `RankMatchConfig.json`,
`GameMisc.json`...). Copia el que quieras cambiar a `en_espera/`, edítalo y, cuando esté listo, muévelo a `activos/`.

Ojo:
- Los JSON pueden llevar comentarios `//` (el juego los quita igual que el servidor).
- Un CSV con barras invertidas (`\n`, `\t`...) no se manda: el teléfono las convertiría y quedaría roto.
- Cambiar la tienda en la configuración solo cambia lo que **se ve**; comprar necesita que el servidor responda a
  las compras, y eso se irá agregando por partes.
