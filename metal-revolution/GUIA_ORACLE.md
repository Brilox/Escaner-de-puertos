# Guía: el servidor de Metal Revolution en Oracle Cloud (gratis)

Al terminar tendrás el servidor funcionando en internet las 24 horas, con una IP pública fija, sin abrir nada en el
router de tu casa. Después me pasas esa IP y te genero el APK que apunta ahí.

Tiempo estimado: 30–45 minutos la primera vez. Todo se hace desde el navegador del PC más una ventana de PowerShell.

> Oracle cambia a veces los nombres de los botones de su consola. Si algo no coincide exactamente, busca el nombre
> parecido o mándame una captura y te digo dónde está.

**Resumen de lo que vamos a hacer**

| Paso | Dónde | Qué |
|---|---|---|
| 1 | Consola de Oracle | Ver en qué región está tu cuenta |
| 2 | Consola de Oracle | Revisar la instancia que creaste ayer (¿sirve o hay que rehacerla?) |
| 3 | Consola de Oracle | Crear una red con salida a internet |
| 4 | Consola de Oracle | Abrir los puertos del juego (TCP 8080, UDP 8079–8080) |
| 5 | Consola de Oracle | Crear la máquina (instancia) con IP pública |
| 6 | PowerShell en tu PC | Conectarte a la máquina |
| 7 | La máquina | Instalar el servidor con un solo comando |
| 8 | PowerShell en tu PC | Comprobar que los tres puertos llegan |
| 9 | Aquí conmigo | Te genero el APK con la IP nueva |

---

## Paso 1: entrar y ver tu región

1. Entra a **https://cloud.oracle.com** e inicia sesión (te pide el "Cloud Account Name" que elegiste al registrarte
   y luego tu correo y contraseña).
2. Arriba a la derecha aparece la región en la que estás, por ejemplo *Chile Central (Santiago)* o
   *Brazil East (Sao Paulo)*.
3. Para estar seguro de cuál es tu **región principal** (la única donde las máquinas gratis son gratis): menú de
   tu perfil (el ícono de persona arriba a la derecha) → **Tenancy: …** → campo **Home Region**.
   Enlace directo: **https://cloud.oracle.com/tenancy**

Trabaja siempre en esa región (selector de arriba a la derecha). Dime cuál es: con eso te digo qué ping esperar
desde Chile, Argentina, Perú, etc.

---

## Paso 2: la instancia que creaste ayer

Que no te dejara marcar "IP pública" casi siempre significa que la instancia quedó en una **subred privada**
(o en una red sin salida a internet). Vamos a comprobarlo.

1. Ve a **https://cloud.oracle.com/compute/instances** (menú ☰ → *Compute* → *Instances*).
   Si la lista sale vacía, revisa a la izquierda que el *Compartment* sea el principal (el que tiene el nombre de tu cuenta, con "(root)").
2. Entra a tu instancia. En la página de detalles busca **Primary VNIC** / pestaña **Networking** y mira:
   - **Public IPv4 address**: si ya tiene una, ¡perfecto, salta al paso 3 (solo para revisar la red) y luego al 4!
   - **Subnet**: haz clic en el nombre de la subred. En la página de la subred mira **Subnet access** (o *Subnet type*):
     dice **Public** o **Private**.

**Si la subred es pública**, puedes darle IP pública ahora mismo:

1. Vuelve a la instancia → pestaña **Networking** → sección **Attached VNICs** → clic en la VNIC (la *primary*).
2. Pestaña **IP administration** (en la consola antigua: *IPv4 Addresses*, abajo a la izquierda en *Resources*).
3. En la fila de la IP privada, menú **⋮** → **Edit**.
4. En **Public IP type** elige **Ephemeral public IP** → **Update**.
5. Ya aparece la **Public IPv4 address**. Anótala. Sigue en el paso 3 para revisar que la red tenga salida a internet.

**Si la subred es privada**, Oracle no permite cambiar eso después. Lo más rápido (5 minutos) es **borrar la
instancia y crear otra** siguiendo los pasos 3 a 5:
instancia → botón **More actions** (o *Actions*) → **Terminate** → marca *Permanently delete the attached boot volume* → **Terminate instance**.

**Otra razón para rehacerla:** si al crearla no descargaste la **clave privada SSH** (un archivo `.key`), no vas a
poder entrar a ella. En ese caso también conviene borrarla y crear una nueva.

**Y si es Oracle Linux en vez de Ubuntu:** también sirve; el script del paso 7 funciona en las dos (el usuario para
entrar es `opc` en vez de `ubuntu`).

---

## Paso 3: una red con salida a internet

Si ya tienes una red creada por el asistente de instancias, igual revisa este paso; el asistente a veces crea solo
una subred privada.

1. Ve a **https://cloud.oracle.com/networking/vcns** (menú ☰ → *Networking* → *Virtual cloud networks*).
2. Botón **Actions** → **Start VCN Wizard** (o el botón *Start VCN Wizard* directamente).
3. Elige **Create VCN with Internet Connectivity** → **Start VCN Wizard**.
4. Nombre: `red-metal`. Deja el resto como viene (crea una subred pública, una privada, el *Internet Gateway* y las
   rutas). **Next** → **Create**. Espera a que todo salga en verde → **View VCN**.

Si quieres revisar una red que ya tenías: en la VCN, pestaña **Subnets** debe haber una subred con
*Subnet access: Public*, y en **Gateways** / *Internet Gateways* debe haber uno. Si no, crea una nueva con el asistente.

---

## Paso 4: abrir los puertos del juego en Oracle

Oracle bloquea todo lo que entra salvo SSH. Hay que abrir: **TCP 8080** (el juego), **UDP 8079** (el ping antes de
la pelea) y **UDP 8080** (la pelea).

1. En tu VCN (`red-metal`), pestaña **Security** (consola antigua: *Security Lists* en *Resources*).
2. Abre **Default Security List for red-metal**.
3. Pestaña **Security rules** → **Add Ingress Rules**. Crea la primera regla:
   - *Stateless*: sin marcar
   - *Source Type*: **CIDR**
   - *Source CIDR*: `0.0.0.0/0`
   - *IP Protocol*: **TCP**
   - *Source Port Range*: vacío
   - *Destination Port Range*: `8080`
   - *Description*: `Metal Revolution juego`
4. Pulsa **+ Another Ingress Rule** y crea la segunda:
   - *Source CIDR*: `0.0.0.0/0`
   - *IP Protocol*: **UDP**
   - *Destination Port Range*: `8079-8080`
   - *Description*: `Metal Revolution pelea`
5. **Add Ingress Rules**. Deben quedar en la lista, junto a la regla de SSH (puerto 22) que ya venía.

(Si en el paso 2 te quedaste con tu instancia y su red es otra, haz esto en la *Security List* de **esa** subred.)

---

## Paso 5: crear la máquina

1. Ve a **https://cloud.oracle.com/compute/instances** → **Create instance**.
2. **Name**: `servidor-metal`. Compartment y *Availability domain*: como vengan.
3. **Image and shape** → **Edit** / **Change image**:
   - Imagen: **Ubuntu** → **Canonical Ubuntu 24.04** (o 22.04). Que diga *Always Free-eligible*. → *Select image*.
   - **Change shape**: hay dos opciones gratis.
     - **Ampere** → `VM.Standard.A1.Flex` con **1 OCPU y 6 GB**. Es la mejor, pero a veces Oracle dice
       *"Out of capacity"*.
     - **Specialty and previous generation** → `VM.Standard.E2.1.Micro` (AMD, 1 GB). Más chica pero casi siempre
       disponible, y para nuestro servidor alcanza de sobra.
4. **Networking** (*Primary VNIC*):
   - *Primary network*: **Select existing virtual cloud network** → `red-metal`.
   - *Subnet*: **Select existing subnet** → la que se llama **public subnet-red-metal** (¡la pública!).
   - **Automatically assign public IPv4 address**: **activado**. Si está gris, es que elegiste la subred privada.
5. **Add SSH keys**: **Generate a key pair for me** → pulsa **Download private key** (y si quieres también la
   pública). Se baja un archivo tipo `ssh-key-2026-11-17.key`. **Guárdalo bien: sin él no podrás entrar.**
   Muévelo a `C:\mr\oracle.key` para que los comandos de abajo sean cortos.
6. **Boot volume**: déjalo como viene.
7. **Create**. En 1–2 minutos el estado pasa a **Running** (verde).
8. En los detalles de la instancia copia **Public IPv4 address**. Esa es **tu IP pública**.

> **"Out of capacity"**: prueba otro *Availability domain* (si tu región tiene varios), la otra forma (E2.1.Micro),
> o vuelve a intentarlo más tarde.

### (Opcional) que la IP nunca cambie

La IP que te dio Oracle (*ephemeral*) se mantiene aunque reinicies o apagues la máquina; solo se pierde si **borras** la
instancia. Si quieres que sobreviva incluso a eso, puedes cambiarla por una **reservada**
(menú ☰ → *Networking* → *IP management* → *Reserved public IPs* → *Reserve public IP address*, y luego en la VNIC
→ *Edit* → *Reserved public IP*). Hazlo **antes** de que te genere el APK, porque la IP cambia una vez al hacerlo.
No es necesario para la prueba.

---

## Paso 6: conectarte desde tu PC (PowerShell)

1. Tecla Windows → escribe `PowerShell` → Enter.
2. Arregla los permisos de la clave (Windows se queja si otros usuarios pueden leerla). Copia y pega:
   ```powershell
   icacls C:\mr\oracle.key /inheritance:r
   icacls C:\mr\oracle.key /grant:r "$($env:USERNAME):(R)"
   ```
3. Conéctate (cambia `TU.IP.PUBLICA` por la del paso 5):
   ```powershell
   ssh -i C:\mr\oracle.key ubuntu@TU.IP.PUBLICA
   ```
   La primera vez pregunta *"Are you sure you want to continue connecting"*: escribe `yes` y Enter.
   Si todo va bien, el texto de la ventana cambia a algo como `ubuntu@servidor-metal:~$`. Ya estás dentro de la máquina.
   (Con Oracle Linux el usuario es `opc` en vez de `ubuntu`.)

---

## Paso 7: instalar el servidor (un solo comando)

Dentro de la máquina (la ventana que dice `ubuntu@servidor-metal`), copia y pega estas dos líneas:

```bash
curl -fsSLO https://raw.githubusercontent.com/Brilox/Escaner-de-puertos/claude/metal-revolution-multiplayer-server-kode3a/metal-revolution/server/instalar_oracle.sh
sudo bash instalar_oracle.sh
```

El script hace todo solo: instala lo necesario, descarga el servidor desde tu GitHub, averigua la IP pública, abre los
puertos en el cortafuegos interno de la máquina (Oracle tiene **dos** cortafuegos: el del paso 4 y este) y deja el
servidor como **servicio**: arranca solo al encender la máquina y se reinicia si se cae. Al final debe decir:

```
LISTO: el servidor esta funcionando en TU.IP.PUBLICA (TCP 8080, UDP 8079 y 8080).
```

Ya puedes cerrar PowerShell: el servidor sigue funcionando en Oracle.

---

## Paso 8: comprobar desde tu PC

En PowerShell **de tu PC** (no dentro de la máquina), con la carpeta del proyecto descargada en `C:\mr`:

```powershell
cd C:\mr\metal-revolution\tools
python comprobar_conexion.py TU.IP.PUBLICA
```

Debe salir:

```
  OK     TCP 8080  (juego: login, salas, chat)
  OK     UDP 8079  (ping antes de la pelea)  ping 35 ms
  OK     UDP 8080  (la pelea en tiempo real)
```

Si algo dice **FALLA**, casi siempre es una regla del paso 4 (protocolo o puerto equivocado, o puesta en la
*Security List* de otra subred). El mismo comando lo puede correr un amigo de otro país para ver su ping
(solo necesita Python y la carpeta `tools`).

---

## Paso 9: el APK

Mándame la IP pública y te genero el APK que apunta a ella (igual que hicimos con la IP de tu casa). Tú y tu hijo lo
instalan y entran como siempre. Ya no hace falta tener el PC encendido ni estar en la misma Wi-Fi.

---

## Uso diario

Siempre conectándote primero con `ssh -i C:\mr\oracle.key ubuntu@TU.IP.PUBLICA`:

| Para… | Comando |
|---|---|
| Ver el log en vivo (Ctrl+C para salir) | `tail -f ~/mr-servidor/metal-revolution/server/mr_server.log` |
| Ver si está corriendo | `sudo systemctl status metal-revolution` |
| Reiniciarlo | `sudo systemctl restart metal-revolution` |
| Apagarlo / encenderlo | `sudo systemctl stop metal-revolution` / `sudo systemctl start metal-revolution` |
| **Actualizarlo** a la última versión que yo suba | `sudo bash ~/mr-servidor/metal-revolution/server/instalar_oracle.sh` |

Las cuentas y estadísticas están en `~/mr-servidor/metal-revolution/server/cuentas.db`; actualizar **no** las borra.

**Traer el log a tu PC** para mandármelo (en PowerShell de tu PC):
```powershell
scp -i C:\mr\oracle.key ubuntu@TU.IP.PUBLICA:mr-servidor/metal-revolution/server/mr_server.log C:\mr\
```
Queda en `C:\mr\mr_server.log`.

---

## Problemas comunes

- **No me deja marcar la IP pública al crear la instancia**: elegiste una subred privada. En el paso 5 elige la
  *public subnet*. Si tu red no tiene ninguna, créala con el asistente del paso 3.
- **`ssh` dice "Permission denied (publickey)"**: usuario equivocado (`ubuntu` para Ubuntu, `opc` para Oracle Linux)
  o clave equivocada (cada instancia tiene la suya).
- **`ssh` dice "UNPROTECTED PRIVATE KEY FILE"**: repite los dos comandos `icacls` del paso 6.
- **`ssh` se queda pensando y da *timeout***: la instancia no tiene IP pública, o la subred no tiene *Internet Gateway*
  (paso 3), o falta la regla del puerto 22 en la *Security List*.
- **El comprobador dice FALLA en UDP pero OK en TCP**: falta la regla UDP `8079-8080` del paso 4.
- **Todo FALLA**: mira si el servicio corre (`sudo systemctl status metal-revolution`); si no, vuelve a ejecutar el
  instalador y mándame lo que muestre.
- **Un día la máquina aparece detenida (Stopped)**: Oracle puede detener las máquinas gratuitas que pasan muchos días
  casi sin uso. Instancia → **Start**. La IP se mantiene y el servidor arranca solo.

## Seguridad, en corto

- Tu casa no queda expuesta: todo vive en la máquina de Oracle.
- En Oracle solo quedan abiertos el 22 (SSH, que solo acepta tu clave) y los tres puertos del juego.
- Tu repositorio de GitHub es **público**: cualquiera puede ver el código del servidor (no pasa nada) y también la
  clave con la que firmamos el APK (`tools/mr.keystore`). Para las pruebas con amigos da igual; si algún día lo abres
  a más gente, lo pasamos a privado o cambiamos esa clave.
