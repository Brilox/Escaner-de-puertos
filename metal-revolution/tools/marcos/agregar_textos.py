#!/usr/bin/env python3
"""Agrega textos nuevos (nombres y descripciones de marcos) al bundle de idiomas del juego (I2 Localization).

    python agregar_textos.py <i2languages.bundle> <salida.bundle> <textos.json>

textos.json: {"item/name/52000": {"es": "...", "en": "..."}, ...}. Idiomas del juego: en, zh, de, fr, es, pt, ru, id,
th, pl, tr, it (en ese orden). Los que falten se llenan con el ingles. Un termino que ya existe se reemplaza.
El bundle es AssetBundles/Android/config/i2languages.bundle (Unity 2018.4.32f1)."""
import json, os, sys
import UnityPy

IDIOMAS = ['en', 'zh', 'de', 'fr', 'es', 'pt', 'ru', 'id', 'th', 'pl', 'tr', 'it']

def agregar(entrada, salida, textos):
    env = UnityPy.load(entrada)
    for o in env.objects:
        if o.type.name != 'MonoBehaviour': continue
        t = o.read_typetree()
        if 'mTerms' not in t: continue
        assert len(t['mLanguages']) == len(IDIOMAS), 'el juego tiene otros idiomas: revisar IDIOMAS'
        pos = {x['Term']: i for i, x in enumerate(t['mTerms'])}
        for termino, tr in textos.items():
            en = tr.get('en') or next(iter(tr.values()))
            fila = {'Term': termino, 'TermType': 0, 'Description': '', 'Languages': [tr.get(c, en) for c in IDIOMAS],
                    'Flags': [0] * len(IDIOMAS), 'Languages_Touch': []}
            if termino in pos: t['mTerms'][pos[termino]] = fila
            else: t['mTerms'].append(fila)
        o.save_typetree(t)
        open(salida, 'wb').write(env.file.save(packer='original'))
        print('%d textos -> %s (%d terminos)' % (len(textos), salida, len(t['mTerms'])))
        return
    raise SystemExit('no encontre los textos en ' + entrada)

if __name__ == '__main__':
    if len(sys.argv) != 4: print(__doc__); sys.exit(2)
    agregar(sys.argv[1], sys.argv[2], json.load(open(sys.argv[3], encoding='utf-8')))
