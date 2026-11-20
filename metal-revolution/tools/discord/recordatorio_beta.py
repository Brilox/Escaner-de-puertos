#!/usr/bin/env python3
"""Recordatorio de la beta en #general: invita a inscribirse en el sorteo, con el bot de siempre ("Constructor").

    set DISCORD_TOKEN=el-token-de-tu-bot
    python recordatorio_beta.py <ID-del-servidor> [--cada 4] [--min-mensajes 10] [--hasta 2026-12-05] [--canal general]
    python recordatorio_beta.py <ID-del-servidor> --una-vez        (publica el aviso ahora y termina: para probar)

Como funciona (para no llenar el chat):
- Mantiene UN solo aviso en el canal: antes de publicar uno nuevo, borra el anterior del bot.
- Cada --cada horas (4 por defecto) revisa el canal y publica de nuevo SOLO si desde el ultimo aviso la gente escribio
  al menos --min-mensajes mensajes (10 por defecto), es decir, si el aviso ya quedo tapado. Si el chat esta quieto, no
  publica nada.
- El aviso lleva el enlace directo al mensaje de inscripcion y cuantas personas y paises van inscritos.
- --hasta FECHA: deja de publicar desde ese dia (por ejemplo, el dia del sorteo) y borra su ultimo aviso.
La ventana de la consola tiene que quedar abierta (o, en el VPS, correr como servicio). Ctrl+C para detenerlo.
Necesita "Server Members Intent" activado en el portal del bot (igual que el sorteo)."""
import argparse, asyncio, datetime, os, sys

import discord

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sorteo_beta

MARCA = 'Inscripciones abiertas para la beta'             # asi reconoce sus propios avisos
MARCA_INSCRIPCION = 'Inscripción para la prueba beta'


def texto_aviso(canales, inscritos, paises, enlace):
    m = lambda n: canales[n].mention if n in canales else '#' + n
    cuenta = ''
    if inscritos:
        cuenta = 'Ya %s **%d %s** de **%d %s**. ' % ('hay' if inscritos == 1 else 'van', inscritos, 'inscrito' if inscritos == 1 else 'inscritos',
                                                    paises, 'país' if paises == 1 else 'países')
    return ('📣 **%s de Metal Online** 🥊\n'
            'Buscamos **10 jugadores de distintos países** para probar el servidor antes de abrirlo. %s'
            'Los elegidos reciben el rol **Beta Tester** y los **marcos exclusivos de la beta**.\n\n'
            '**¿Cómo me inscribo?**\n'
            '1. Lee las reglas del sorteo en %s.\n'
            '2. Reacciona con **la bandera de tu país** en el mensaje de inscripción: %s\n'
            '3. Lee qué hay que hacer el día de la prueba en %s.\n\n'
            'La fecha del sorteo se anuncia en %s.'
            % (MARCA, cuenta, m('postulación-beta'), enlace or m('postulación-beta'),
               m('instrucciones-beta'), m('anuncios')))


async def buscar_inscripcion(cliente, guild):
    canal = discord.utils.get(guild.text_channels, name='postulación-beta')
    if canal is None: return None
    async for msg in canal.history(limit=100):
        if msg.author == cliente.user and MARCA_INSCRIPCION in msg.content: return msg
    return None


async def contar(msg):
    """Personas (sin bots) que reaccionaron con alguna bandera, y cuantos paises distintos."""
    gente, paises = set(), set()
    for reac in msg.reactions:
        info = sorteo_beta.POR_EMOJI.get(str(reac.emoji))
        if not info: continue
        async for u in reac.users():
            if not u.bot: gente.add(u.id); paises.add(info[0])
    return len(gente), len(paises)


async def ronda(cliente, guild, a, forzar=False):
    canal = discord.utils.get(guild.text_channels, name=a.canal)
    if canal is None: print('no encuentro #%s' % a.canal); return
    propios, de_gente = [], 0
    async for msg in canal.history(limit=200):                  # del mas nuevo al mas viejo
        if msg.author == cliente.user and MARCA in msg.content: propios.append(msg); break
        if not msg.author.bot: de_gente += 1
    hoy = datetime.date.today()
    if a.hasta and hoy >= a.hasta:
        for p in propios:
            try: await p.delete()
            except discord.HTTPException: pass
        print('%s: inscripciones cerradas (--hasta %s): no publico mas' % (hoy, a.hasta)); return 'fin'
    if propios and not forzar and de_gente < a.min_mensajes:
        print('%s: el aviso sigue a la vista (%d mensajes despues): no publico' % (datetime.datetime.now().strftime('%H:%M'), de_gente))
        return
    insc = await buscar_inscripcion(cliente, guild)
    n, p = await contar(insc) if insc else (0, 0)
    canales = {c.name: c for c in guild.text_channels}
    texto = texto_aviso(canales, n, p, insc.jump_url if insc else None)
    for viejo in propios:
        try: await viejo.delete()
        except discord.HTTPException as e: print('no pude borrar el aviso anterior:', e)
    await canal.send(texto, suppress_embeds=True)
    print('%s: aviso publicado en #%s (%d inscritos, %d paises)' % (datetime.datetime.now().strftime('%H:%M'), canal.name, n, p))


def main():
    if len(sys.argv) > 1 and not sys.argv[1].isdigit() and not sys.argv[1].startswith('-'):
        print('ERROR: el primer dato tiene que ser el ID del servidor (un numero largo: clic derecho en el servidor -> Copiar ID).')
        if '.' in sys.argv[1] and len(sys.argv[1]) > 50:
            print('Pusiste el TOKEN del bot: va en  set DISCORD_TOKEN=...  y como quedo a la vista, cambialo con Reset Token.')
        sys.exit(2)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('servidor', type=int)
    ap.add_argument('--canal', default='general')
    ap.add_argument('--cada', type=float, default=4.0, help='horas entre revisiones (4 por defecto)')
    ap.add_argument('--min-mensajes', type=int, default=10, help='mensajes de la gente para volver a publicar (10)')
    ap.add_argument('--hasta', type=datetime.date.fromisoformat, help='AAAA-MM-DD: desde ese dia ya no publica')
    ap.add_argument('--una-vez', action='store_true', help='publica el aviso ahora y termina')
    a = ap.parse_args()
    token = os.environ.get('DISCORD_TOKEN')
    if not token: sys.exit('ERROR: falta el token. Escribe antes:  set DISCORD_TOKEN=el-token-de-tu-bot')
    intents = discord.Intents.default(); intents.members = True
    cliente = discord.Client(intents=intents)

    @cliente.event
    async def on_ready():
        if getattr(cliente, '_andando', False): return              # on_ready se repite al reconectar
        cliente._andando = True
        guild = cliente.get_guild(a.servidor) or await cliente.fetch_guild(a.servidor)
        print('Recordatorio de la beta en %s / #%s: revisa cada %g h, publica si hubo %d mensajes nuevos%s. Ctrl+C para salir.'
              % (guild.name, a.canal, a.cada, a.min_mensajes, (', hasta el %s' % a.hasta) if a.hasta else ''))
        try:
            if a.una_vez:
                await ronda(cliente, guild, a, forzar=True); return
            primera = True
            while True:
                try:
                    if await ronda(cliente, guild, a, forzar=primera) == 'fin': return
                except discord.HTTPException as e:
                    print('error de Discord (lo intento en la proxima vuelta):', e)
                primera = False
                await asyncio.sleep(a.cada * 3600)
        finally:
            await cliente.close()

    cliente.run(token)


if __name__ == '__main__':
    main()
