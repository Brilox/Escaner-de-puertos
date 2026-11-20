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
esta vacio. Para CAMBIAR los textos ya publicados (editando el mensaje del bot, sin duplicar):
    python crear_servidor.py <ID-del-servidor> --actualizar
El token NUNCA se escribe en archivos ni se sube a GitHub."""
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
Servidor privado hecho por fans de Metal Revolution, sin fines de lucro. Jugar es y será gratis.

🛠️ **Estamos en beta cerrada**: el servidor todavía **no está abierto al público**. Avisaremos en <#anuncios> cuando abra.

1. Lee <#reglas> y reacciona con ✅ para entrar.
2. Revisa <#cómo-jugar> (ahí avisaremos cuándo se puede descargar).
3. Mientras tanto: conversa en <#general>, deja ideas en <#sugerencias> y sigue el avance en <#estado-del-servidor>.""",
'reglas': """📜 **Reglas de Metal Online**
1. **Respeto.** Nada de insultos, racismo, acoso, amenazas ni contenido sexual. Picarse sano sí; humillar o perseguir, no.
2. **Nombres decentes**, en el juego y en Discord.
3. **Sin trampas.** Prohibido usar APK modificadas distintas a la oficial del servidor, aprovechar errores a propósito o arreglar resultados.
4. **No abandones peleas.** Salir a mitad de pelea cuenta como derrota; hacerlo seguido se sanciona.
5. **Una persona, una cuenta en clasificatoria.**
6. **Sin spam ni publicidad** de otros servidores, ventas o enlaces sospechosos.
7. **Nada se vende.** Prohibido comprar o vender cuentas, personajes u objetos por dinero.
8. **Reporta los errores** en <#reportar-errores> en vez de aprovecharlos.
9. **No compartas el juego por tu cuenta**: la descarga oficial se publica solo aquí.
Sanciones: advertencia → silencio o suspensión de 1 a 7 días → expulsión permanente (trampas, acoso grave o venta de cuentas).
**Reacciona con ✅ para aceptar y entrar al servidor.**""",
'cómo-jugar': """⚠️ **NOTA IMPORTANTE: el servidor todavía NO está online.**
Estamos en beta cerrada haciendo pruebas y cambios casi todos los días. **La descarga se publicará aquí cuando el servidor esté online**, así no tienes que reinstalar ni actualizar nada mientras tanto. Activa las notificaciones de <#anuncios> para enterarte primero.

🎮 **Cómo será la instalación** (cuando abramos)
1. Descargas **un solo archivo** `MetalOnline.xapk` desde el enlace oficial que publicaremos aquí.
2. Lo instalas con una app instaladora de XAPK (**APKPure** o **SAI**); ella copia todo en su lugar.
3. Abres el juego: la primera vez prepara sus archivos (tarda un poco) y **se actualiza solo** desde nuestro servidor.
4. Entras, eliges tu nombre, tu avatar y tu marco.

🔄 **Actualizaciones automáticas**: los cambios (marcos, imágenes, ajustes) se descargan solos al abrir el juego. No hace falta reinstalar.

**Preguntas frecuentes**
**¿Es gratis?** Sí, siempre.
**¿Puedo perder mi cuenta?** Hoy la cuenta queda ligada al teléfono: si desinstalas o borras los datos del juego se crea otra. Estamos preparando un registro con usuario y contraseña para que no pase.
**¿Las cuentas de la beta se mantienen?** No: al abrir el servidor todas las cuentas empiezan de cero, para que nadie parta con ventaja.
**¿Por qué el 3v3 está cerrado?** Está en reparación; avisaremos en <#anuncios>.
¿Problemas? Escribe en <#ayuda> con una captura.""",
'donaciones-y-objetos': """💰 **Monedas, objetos y donaciones**
• Todo lo del juego se conseguirá **jugando**. **Nada se vende con dinero real.**
• 🛠️ La tienda, las monedas, el pase de batalla y las misiones están **en desarrollo**; publicaremos los precios y premios cuando estén listos.
• **Marcos que se ganan jugando**: por rango de clasificatoria, por victorias con cada personaje y por nivel.
• **Marcos de la beta** (Founder, Bug Hunter, Beta Vanguard, Elite Patcher y Revolution Hero): exclusivos para quienes prueben la beta.
• **Campeón**: marco y skins especiales solo para ganadores de torneos oficiales.

❤️ **Donaciones**: voluntarias y solo para pagar el servidor. Cada mes publicaremos cuánto entró y en qué se gastó. Donar **no da ventajas en las peleas** (ni monedas ni personajes). Como agradecimiento, quien ayuda recibe el rol **Colaborador** y objetos solo de apariencia según su nivel:
• **Bronce**: marco de Colaborador.
• **Plata**: otro marco y 1 skin a elección.
• **Oro**: otro marco y 3 skins a elección.
• **Leyenda**: todas las skins.""",
'estado-del-servidor': """🛰️ **Estado del servidor: BETA CERRADA (no abierto al público)**

✅ **Funcionando**
• Partida rápida 1v1 y **clasificatoria 1v1** con puntos (hasta 2 revanchas).
• **Salón** con mesas, espectadores y revancha.
• Perfil con estadísticas reales, temporada, avatar, marcos y "me gusta".
• **Actualizaciones automáticas** del juego desde nuestro servidor.
• Panel de administración (moderación, chat, suspensiones).

🧪 **En pruebas**
• Marcos nuevos de la beta, con efectos animados.
• Nueva pantalla de inicio **Metal Online** con fondo animado.

🛠️ **En desarrollo**
• Tienda, monedas, pase de batalla y misiones.
• Registro de cuentas con usuario y contraseña.
• 3v3 (cerrado por ahora).

📅 La fecha de apertura se anunciará en <#anuncios>.""",
'torneos-info': """🏆 **Torneos**
Cuando abra el servidor organizaremos torneos oficiales. Formato: eliminación directa, 1v1, al mejor de 3 peleas. Inscripción en <#inscripciones> con tu nombre del juego.
El campeón recibe el rol **Campeón** y un marco o skin exclusivo del torneo.""",
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


async def armar(cliente, guild_id, actualizar=False):
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
        for nombre_ref, ref in canales.items():
            texto = texto.replace('<#%s>' % nombre_ref, ref.mention)
        assert len(texto) <= 2000, 'el texto de #%s pasa el limite de Discord (%d caracteres)' % (nombre, len(texto))
        mensajes = [m async for m in canal.history(limit=50)]
        propio = next((m for m in mensajes if m.author == cliente.user), None)   # el ultimo mensaje del bot en el canal
        if propio and actualizar:
            if propio.content != texto:
                await propio.edit(content=texto); print('  texto ACTUALIZADO en #' + nombre)
            else:
                print('  #%s ya estaba al dia' % nombre)
            continue
        if mensajes and not actualizar: continue                          # ya tiene mensajes: no se repite
        msg = await canal.send(texto)
        if nombre == 'reglas': await msg.add_reaction('✅')
        print('  texto publicado en #' + nombre + ('  (el texto viejo no era del bot: borralo a mano)' if mensajes else ''))
    print('\nListo. Falta: AutoMod, Carl-bot (rol Jugador con la reaccion de #reglas) y Ticket Tool (ver el documento).')


def main():
    token = os.environ.get('DISCORD_TOKEN')
    if len(sys.argv) < 2 or not token:
        print(__doc__); return 2
    guild_id = int(sys.argv[1]); actualizar = '--actualizar' in sys.argv
    cliente = discord.Client(intents=discord.Intents.default())

    @cliente.event
    async def on_ready():
        try: await armar(cliente, guild_id, actualizar)
        finally: await cliente.close()

    cliente.run(token)


if __name__ == '__main__':
    sys.exit(main())
