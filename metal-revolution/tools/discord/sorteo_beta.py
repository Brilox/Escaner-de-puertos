#!/usr/bin/env python3
"""Sorteo de los probadores de la beta con cupos por pais (con el mismo bot de crear_servidor.py).

1) Publicar la inscripcion (un mensaje con las banderas; la gente reacciona con la de su pais):
    python sorteo_beta.py <ID-servidor> publicar [--canal anuncios]

2) Hacer el sorteo (lee las reacciones de ese mensaje):
    python sorteo_beta.py <ID-servidor> sortear --mensaje <ID-del-mensaje> [--cupos 10] [--max-pais 2]
                         [--minimo MX=1] [--minimo US=1] [--suplentes 5] [--prueba]

Con --prueba solo muestra el resultado en pantalla (no publica ni entrega roles): usalo primero.
Sin --prueba publica el resultado en el mismo canal y da el rol "Beta Tester" a los elegidos.

Reglas del sorteo (se publican junto al resultado):
- Cuenta una sola inscripcion por persona; quien reacciono con varias banderas queda con UNA elegida al azar.
- No participan los bots ni el staff (Admin y Moderador), salvo con --incluir-staff.
- Primero se cumplen los minimos por pais (--minimo), despues se reparte por turnos entre paises para que haya la
  mayor variedad posible, sin pasar --max-pais por pais. El orden es al azar, con una semilla que se publica: cualquiera
  puede repetir el sorteo y obtener lo mismo.
Antes: en el portal de desarrolladores de Discord, activa "Server Members Intent" en la pagina del bot.
El token va en la variable DISCORD_TOKEN, nunca en archivos."""
import argparse, asyncio, os, random, sys, time

import discord

PAISES = [('🇨🇱', 'CL', 'Chile'), ('🇲🇽', 'MX', 'México'), ('🇦🇷', 'AR', 'Argentina'), ('🇵🇪', 'PE', 'Perú'),
          ('🇨🇴', 'CO', 'Colombia'), ('🇻🇪', 'VE', 'Venezuela'), ('🇪🇨', 'EC', 'Ecuador'), ('🇺🇾', 'UY', 'Uruguay'),
          ('🇧🇴', 'BO', 'Bolivia'), ('🇵🇾', 'PY', 'Paraguay'), ('🇧🇷', 'BR', 'Brasil'), ('🇨🇷', 'CR', 'Costa Rica'),
          ('🇬🇹', 'GT', 'Guatemala'), ('🇺🇸', 'US', 'Estados Unidos'), ('🇪🇸', 'ES', 'España'), ('🌎', 'OT', 'Otro país')]
POR_EMOJI = {e: (c, n) for e, c, n in PAISES}
ROL_BETA = 'Beta Tester'

TEXTO_INSCRIPCION = """🧪 **¡Inscripción para la prueba beta de Metal Online!**
Buscamos **10 jugadores de distintos países** para probar el servidor y medir el lag entre países (lee <#instrucciones-beta>).

**Para participar, reacciona con la bandera de TU país** (una sola). Si tu país no está, usa 🌎.
El sorteo es al azar, con cupos para que haya jugadores de varios países, y se publica con su semilla para que cualquiera lo pueda comprobar.
Los elegidos reciben el rol **Beta Tester** y los **marcos exclusivos de la beta**. 🥊"""


def sortear(inscritos, cupos, max_pais, minimos, semilla, suplentes):
    """inscritos: {user_id: [codigos de pais]}. Devuelve (elegidos, suplentes) como listas de (user_id, pais)."""
    rnd = random.Random(semilla)
    gente = sorted(inscritos)                                   # orden fijo antes de mezclar: el resultado se puede repetir
    pais_de = {u: rnd.choice(sorted(inscritos[u])) for u in gente}
    rnd.shuffle(gente)
    por_pais = {}
    for u in gente: por_pais.setdefault(pais_de[u], []).append(u)
    elegidos, cuenta = [], {}
    def tomar(p):
        if por_pais.get(p) and cuenta.get(p, 0) < max_pais and len(elegidos) < cupos:
            u = por_pais[p].pop(0); elegidos.append((u, p)); cuenta[p] = cuenta.get(p, 0) + 1; return True
        return False
    for p, n in minimos.items():
        for _ in range(n): tomar(p)
    orden = sorted(por_pais); rnd.shuffle(orden)
    while len(elegidos) < cupos and any(tomar(p) for p in orden): pass
    resto = [(u, p) for p in orden for u in por_pais[p]]; rnd.shuffle(resto)
    return elegidos, resto[:suplentes]


async def publicar(cliente, guild, a):
    canal = discord.utils.get(guild.text_channels, name=a.canal)
    if canal is None: sys.exit('no encuentro el canal #' + a.canal)
    texto = TEXTO_INSCRIPCION
    ib = discord.utils.get(guild.text_channels, name='instrucciones-beta')
    if ib: texto = texto.replace('<#instrucciones-beta>', ib.mention)
    msg = await canal.send(texto)
    for e, _, _ in PAISES: await msg.add_reaction(e)
    print('inscripcion publicada en #%s. ID del mensaje (para el sorteo): %d' % (canal.name, msg.id))


async def hacer_sorteo(cliente, guild, a):
    msg = None
    for canal in guild.text_channels:
        try: msg = await canal.fetch_message(a.mensaje); break
        except (discord.NotFound, discord.Forbidden, discord.HTTPException): continue
    if msg is None: sys.exit('no encontre el mensaje %d' % a.mensaje)
    staff = {r.id for r in guild.roles if r.name in ('Admin', 'Moderador')}
    inscritos, miembros = {}, {}
    for reac in msg.reactions:
        info = POR_EMOJI.get(str(reac.emoji))
        if not info: continue
        async for u in reac.users():
            if u.bot: continue
            m = miembros.get(u.id) or guild.get_member(u.id)
            if m is None:
                try: m = await guild.fetch_member(u.id)
                except discord.HTTPException: continue              # ya no esta en el servidor
            miembros[u.id] = m
            if not a.incluir_staff and any(r.id in staff for r in m.roles): continue
            inscritos.setdefault(u.id, set()).add(info[0])
    minimos = dict(x.split('=') for x in a.minimo); minimos = {k.upper(): int(v) for k, v in minimos.items()}
    semilla = a.semilla or str(int(time.time()))
    elegidos, sup = sortear(inscritos, a.cupos, a.max_pais, minimos, semilla, a.suplentes)
    nombre = {c: n for _, c, n in PAISES}; bandera = {c: e for e, c, _ in PAISES}
    linea = lambda u, p: '%s %s (%s)' % (bandera[p], miembros[u].mention, nombre[p])
    texto = ('🎉 **Resultado del sorteo de la beta**\nInscritos: %d · Semilla: `%s` · Cupos: %d (máximo %d por país%s)\n\n**Elegidos:**\n%s'
             % (len(inscritos), semilla, a.cupos, a.max_pais,
                ''.join(', mínimo %d de %s' % (n, nombre.get(p, p)) for p, n in minimos.items()),
                '\n'.join(linea(u, p) for u, p in elegidos) or '(nadie)'))
    if sup: texto += '\n\n**Suplentes** (en este orden, si alguien no puede):\n' + '\n'.join(linea(u, p) for u, p in sup)
    texto += '\n\nLos elegidos ya tienen el rol **%s**. ¡Gracias a todos por inscribirse! 🥊' % ROL_BETA
    print(texto.replace('**', ''))
    if a.prueba:
        print('\n(--prueba: no se publico nada ni se dieron roles)'); return
    rol = discord.utils.get(guild.roles, name=ROL_BETA) or await guild.create_role(name=ROL_BETA, colour=discord.Colour(0x00BCD4), hoist=True)
    for u, _ in elegidos:
        try: await miembros[u].add_roles(rol, reason='sorteo beta')
        except discord.HTTPException as e: print('no pude dar el rol a', miembros[u], e)
    await msg.channel.send(texto)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('servidor', type=int); ap.add_argument('accion', choices=('publicar', 'sortear'))
    ap.add_argument('--canal', default='anuncios'); ap.add_argument('--mensaje', type=int)
    ap.add_argument('--cupos', type=int, default=10); ap.add_argument('--max-pais', type=int, default=2)
    ap.add_argument('--minimo', action='append', default=[], help='PAIS=N, por ejemplo MX=1 (se puede repetir)')
    ap.add_argument('--suplentes', type=int, default=5); ap.add_argument('--semilla')
    ap.add_argument('--incluir-staff', action='store_true'); ap.add_argument('--prueba', action='store_true')
    a = ap.parse_args()
    token = os.environ.get('DISCORD_TOKEN')
    if not token: sys.exit('falta la variable DISCORD_TOKEN con el token del bot')
    if a.accion == 'sortear' and not a.mensaje: sys.exit('falta --mensaje <ID del mensaje de inscripcion>')
    intents = discord.Intents.default(); intents.members = True
    cliente = discord.Client(intents=intents)

    @cliente.event
    async def on_ready():
        try:
            guild = cliente.get_guild(a.servidor) or await cliente.fetch_guild(a.servidor)
            await (publicar if a.accion == 'publicar' else hacer_sorteo)(cliente, guild, a)
        finally:
            await cliente.close()
    cliente.run(token)


if __name__ == '__main__':
    main()
