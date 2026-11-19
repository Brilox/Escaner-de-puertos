#!/usr/bin/env python3
"""Arma el servidor de Discord de Metal Online: roles, categorias, canales (con sus permisos) y los textos fijos.

Uso (en tu PC, una sola vez):
    pip install discord.py
    set DISCORD_TOKEN=el-token-de-tu-bot          (Windows; en Linux/Mac: export DISCORD_TOKEN=...)
    python crear_servidor.py <ID-del-servidor>

Antes: crea el servidor en Discord, activa "Comunidad" (Ajustes del servidor -> Habilitar comunidad), crea un bot en
https://discord.com/developers/applications (Bot -> Reset Token para copiar el token) e invitalo con el permiso
"Administrator" (OAuth2 -> URL Generator -> bot + Administrator). Cuando termine, puedes quitarle el permiso o expulsarlo.

Se puede volver a ejecutar: lo que ya existe (mismo nombre) no se duplica. Los textos solo se publican si el canal
esta vacio. El token NUNCA se escribe en archivos ni se sube a GitHub."""
import asyncio, os, sys

import discord

ROLES = [  # nombre, color, permisos extra (de mayor a menor)
    ('Admin', 0xE53935, dict(administrator=True)),
    ('Moderador', 0xFB8C00, dict(manage_messages=True, moderate_members=True, kick_members=True, ban_members=True,
                                 manage_threads=True, mention_everyone=True, view_audit_log=True)),
    ('Campeón', 0xFFC107, {}),
    ('Colaborador', 0x8E24AA, {}),
    ('Jugador', 0x1E88E5, {}),
]

# categoria -> [(canal, tipo, quien escribe)]; tipo: texto | anuncios | foro | voz. Escribe: staff | jugadores | bot
ESTRUCTURA = [
    ('📌 INFORMACIÓN', [('bienvenida', 'texto', 'staff'), ('reglas', 'texto', 'staff'), ('anuncios', 'anuncios', 'staff'),
                        ('cómo-jugar', 'texto', 'staff'), ('donaciones-y-objetos', 'texto', 'staff'),
                        ('estado-del-servidor', 'texto', 'staff')]),
    ('💬 COMUNIDAD', [('general', 'texto', 'jugadores'), ('presentaciones', 'texto', 'jugadores'),
                      ('clips-y-capturas', 'texto', 'jugadores'), ('sugerencias', 'foro', 'jugadores')]),
    ('⚔️ BATALLAS', [('buscar-rival', 'texto', 'jugadores'), ('mesa-1', 'texto', 'jugadores'), ('mesa-2', 'texto', 'jugadores'),
                     ('mesa-3', 'texto', 'jugadores'), ('Mesa 1', 'voz', 'jugadores'), ('Mesa 2', 'voz', 'jugadores'),
                     ('Mesa 3', 'voz', 'jugadores'), ('clasificatoria', 'texto', 'jugadores')]),
    ('🏆 TORNEOS', [('torneos-info', 'texto', 'staff'), ('inscripciones', 'texto', 'jugadores'), ('resultados', 'texto', 'staff')]),
    ('🛠️ SOPORTE', [('ayuda', 'foro', 'jugadores'), ('reportar-errores', 'foro', 'jugadores'), ('abrir-ticket', 'texto', 'bot')]),
    ('🔒 STAFF', [('staff-chat', 'texto', 'staff'), ('registro-moderación', 'texto', 'bot')]),
]
VISIBLES_SIN_REGLAS = {'bienvenida', 'reglas'}       # lo unico que ve quien todavia no acepto las reglas

TEXTOS = {
'bienvenida': """👊 **Bienvenido a Metal Online**
Servidor privado de Metal Revolution, hecho por fans y sin fines de lucro. Jugar es gratis.
1. Lee <#reglas> y reacciona con ✅ para entrar.
2. Sigue <#cómo-jugar> para instalar el juego.
3. Busca rival en <#buscar-rival> y nos vemos en las mesas.""",
'reglas': """📜 **Reglas de Metal Online**
1. **Respeto.** Nada de insultos, racismo, acoso, amenazas ni contenido sexual. Picarse sano sí; humillar o perseguir, no.
2. **Nombres decentes**, en el juego y en Discord.
3. **Sin trampas.** Prohibido usar APK modificadas para tener ventaja, aprovechar errores a propósito o arreglar resultados.
4. **No abandones peleas.** Salir a mitad de pelea cuenta como derrota; hacerlo seguido se sanciona.
5. **Una persona, una cuenta en clasificatoria.**
6. **Sin spam ni publicidad** de otros servidores, ventas o enlaces sospechosos.
7. **Nada se vende.** Prohibido comprar o vender cuentas, personajes u objetos por dinero.
8. **Reporta los errores** en <#reportar-errores> en vez de aprovecharlos.
Sanciones: advertencia → silencio o suspensión de 1 a 7 días → expulsión permanente (trampas, acoso grave o venta de cuentas).
**Reacciona con ✅ para aceptar y entrar al servidor.**""",
'cómo-jugar': """🎮 **Cómo jugar**
1. Descarga el APK y el OBB del enlace que entrega el staff (pídelo en <#abrir-ticket>).
2. Instala el APK. Copia el OBB en `Android/obb/com.gtarcade.next.mrglo/`.
3. Abre el juego, entra como invitado y elige tu nombre.
4. Elige tu avatar y tu marco en el perfil.
5. Para jugar: **Rápida 1v1**, **Clasificatoria** (1v1 con puntos) o el **Salón** (mesas 1 a 8).
¿Problemas? Escribe en <#ayuda> con una captura.

**Preguntas frecuentes**
**¿Es gratis?** Sí, siempre.
**¿Se pierde mi cuenta si reinstalo?** Si desinstalas el juego o borras sus datos, el teléfono crea otra cuenta. Para actualizar, instala el APK nuevo encima del anterior.
**Tengo lag.** Usa WiFi de 5 GHz o datos móviles estables y desactiva el ahorro de batería.
**¿Por qué el 3v3 está cerrado?** Está en reparación; avisaremos en <#anuncios>.""",
'donaciones-y-objetos': """💰 **Monedas, objetos y donaciones**
• Todo se consigue jugando con la moneda del juego. **Nada se vende con dinero real.**
• Monedas por pelea online: 20 al ganar, 8 al perder (máximo 60 al día).
• Al empezar eliges 5 personajes gratis; los demás cuestan 100 monedas cada uno.
• Avatares 150, marcos 200 y skins 300 monedas.
• Marcos que se ganan jugando: por rango de clasificatoria, por victorias con un personaje y por nivel.
• Skins de **Campeón**: solo para ganadores de torneos oficiales.
• **Donaciones:** voluntarias y solo para pagar el servidor (unos US$6 al mes). Cada mes publicamos cuánto entró y en qué se gastó. Donar no da monedas, personajes ni ventajas en la pelea: solo cosas que se ven. Como agradecimiento, quien ayuda al servidor recibe el rol **Colaborador** y, según su nivel:
  🥉 **Bronce:** marco *Heraldo metálico*.
  🥈 **Plata:** + marco *Mentor de Metal* y 1 skin a elección.
  🥇 **Oro:** + marco *Carnaval navideño* y 3 skins a elección.
  💎 **Leyenda:** todas las skins del juego.
  Pide tu skin al staff con tu nombre del juego.""",
'torneos-info': """🏆 **Torneos**
Formato: eliminación directa, 1v1, al mejor de 3 peleas. Inscripción en <#inscripciones> con tu nombre del juego.
El campeón recibe el rol **Campeón** y una skin o marco exclusivo con la fecha del torneo.""",
}


def permisos(guild, roles, nombre, escribe):
    """Overwrites de un canal: @everyone no ve nada (salvo bienvenida y reglas), Jugador ve y escribe donde toca."""
    staff = [roles['Admin'], roles['Moderador']]
    ver_todos = nombre in VISIBLES_SIN_REGLAS
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=ver_todos, send_messages=False if ver_todos else None,
                                                          add_reactions=True if nombre == 'reglas' else None)}
    if nombre in ('staff-chat', 'registro-moderación'):
        ow[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        for r in ('Jugador', 'Campeón', 'Colaborador'): ow[roles[r]] = discord.PermissionOverwrite(view_channel=False)
    else:
        for r in ('Jugador', 'Campeón', 'Colaborador'):
            ow[roles[r]] = discord.PermissionOverwrite(view_channel=True, send_messages=(escribe == 'jugadores'),
                                                       send_messages_in_threads=(escribe == 'jugadores'),
                                                       create_public_threads=(escribe == 'jugadores'), connect=True, speak=True)
    for r in staff: ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
    return ow


async def armar(cliente, guild_id):
    guild = cliente.get_guild(guild_id) or await cliente.fetch_guild(guild_id)
    if guild is None: sys.exit('No encuentro ese servidor: revisa el ID y que el bot este invitado')
    print('Servidor:', guild.name)
    roles = {r.name: r for r in guild.roles}
    for nombre, color, extra in ROLES:
        if nombre not in roles:
            roles[nombre] = await guild.create_role(name=nombre, colour=discord.Colour(color), hoist=nombre != 'Jugador',
                                                    permissions=discord.Permissions(**extra), mentionable=nombre in ('Moderador',))
            print('  rol creado:', nombre)
    # @everyone sin permiso de mencionar a todos ni de enviar enlaces o archivos fuera de lo que se permita por canal
    base = guild.default_role.permissions; base.update(mention_everyone=False)
    await guild.default_role.edit(permissions=base)

    categorias = {c.name: c for c in guild.categories}
    canales = {c.name: c for c in guild.channels}
    for cat_nombre, lista in ESTRUCTURA:
        cat = categorias.get(cat_nombre) or await guild.create_category(cat_nombre)
        for nombre, tipo, escribe in lista:
            if nombre in canales: continue
            ow = permisos(guild, roles, nombre, escribe)
            if tipo == 'voz':
                canales[nombre] = await guild.create_voice_channel(nombre, category=cat, overwrites=ow)
            elif tipo == 'foro':
                canales[nombre] = await guild.create_forum(nombre, category=cat, overwrites=ow)
            else:
                try:
                    canales[nombre] = await guild.create_text_channel(nombre, category=cat, overwrites=ow, news=(tipo == 'anuncios'))
                except discord.HTTPException:   # sin "Comunidad" activada no hay canales de anuncios: queda como texto
                    canales[nombre] = await guild.create_text_channel(nombre, category=cat, overwrites=ow)
            print('  canal creado:', cat_nombre, '/', nombre)

    for nombre, texto in TEXTOS.items():
        canal = canales.get(nombre)
        if not isinstance(canal, discord.TextChannel): continue
        if [m async for m in canal.history(limit=1)]: continue          # ya tiene mensajes: no se repite
        for nombre_ref, ref in canales.items():
            texto = texto.replace('<#%s>' % nombre_ref, ref.mention)
        msg = await canal.send(texto)
        if nombre == 'reglas': await msg.add_reaction('✅')
        print('  texto publicado en #' + nombre)
    print('\nListo. Falta: AutoMod, Carl-bot (rol Jugador con la reaccion de #reglas) y Ticket Tool (ver el documento).')


def main():
    token = os.environ.get('DISCORD_TOKEN')
    if len(sys.argv) < 2 or not token:
        print(__doc__); return 2
    guild_id = int(sys.argv[1])
    cliente = discord.Client(intents=discord.Intents.default())

    @cliente.event
    async def on_ready():
        try: await armar(cliente, guild_id)
        finally: await cliente.close()

    cliente.run(token)


if __name__ == '__main__':
    sys.exit(main())
