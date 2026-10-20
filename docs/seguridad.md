# Seguridad

Serviscraft está diseñado para administrar servidores de Minecraft **sin
privilegios**. Este documento describe el modelo de seguridad, qué garantiza la
aplicación y qué decisiones son responsabilidad tuya.

## Resumen

| Garantía | Cómo se aplica |
| --- | --- |
| Nunca se usa `sudo` | Toda la aplicación invoca `podman` como tu usuario. Si Podman no es rootless, la aplicación no arranca. |
| La API de Podman no se expone por TCP | Se usa la CLI de Podman, nunca el socket REST. Se eliminan `CONTAINER_HOST`, `DOCKER_HOST` y `CONTAINER_CONNECTION` del entorno de cada proceso hijo. |
| El cortafuegos no se modifica | Serviscraft nunca ejecuta `firewalld`, `ufw`, `iptables` ni `nft`. |
| No se abren puertos sin consentimiento | El puerto del juego solo se publica en la red si activas *Acceso desde la red*; RCON siempre se publica únicamente en `127.0.0.1`. El puerto UDP de Bedrock solo se publica si activas los jugadores de Bedrock. |
| Las descargas se acotan | Las URLs de mods y los iconos de los proyectos solo pueden ser `http`/`https`, con tamaño máximo; los iconos y las texturas nunca se ejecutan, solo se dibujan. Las texturas y las skins, además, solo se piden a dos servidores fijos por `https`. |
| Ninguna acción destructiva sin confirmación | Borrar servidores, mundos o copias exige un diálogo explícito; borrar datos exige escribir el nombre del servidor. |
| Los servidores no arrancan solos | Al abrir la aplicación, los servidores permanecen detenidos salvo que tú los inicies. |
| Sin inyección de comandos | Todas las órdenes a Podman se construyen como listas de argumentos; nunca se usa `shell=True`. |
| Sin fugas por enlaces simbólicos | Ninguna lectura, escritura o borrado de un fichero del servidor sigue un enlace simbólico; el destino tiene que quedar dentro de la carpeta del servidor. |
| El contenedor no gana privilegios | Además de `no-new-privileges`, el contenedor se crea con `--cap-drop=ALL` y un límite de procesos (`--pids-limit`). |

## Contenedores

Cada servidor se ejecuta en un contenedor Podman **rootless** creado así:

| Opción | Motivo |
| --- | --- |
| `--userns=keep-id:uid=…,gid=…` | Conserva tu UID dentro del contenedor para que los mundos sigan siendo tuyos. |
| `-v <datos>:/data:Z` | El volumen usa la etiqueta SELinux `:Z`, de modo que el contenedor solo accede a **su** carpeta. |
| `--security-opt=no-new-privileges` | El proceso no puede ganar privilegios adicionales. |
| `--cap-drop=ALL` | Sin capacidades del núcleo: la imagen no necesita ninguna para servir el juego. |
| `--pids-limit=1024` | Un mod o un plugin descontrolado no puede llenar la tabla de procesos del equipo. |
| `--restart=no` | Nada se reinicia solo tras un reinicio del equipo. |
| `--memory <heap + sobrecarga>m` | El contenedor queda limitado; no puede consumir toda la RAM del sistema. |
| Etiquetas `serviscraft.managed=true` y `serviscraft.id=<id>` | Solo se manipulan contenedores creados por Serviscraft: nunca contenedores ajenos. |
| Publicación de puertos | El juego en `0.0.0.0:<puerto>` (si activas red) o `127.0.0.1:<puerto>`; RCON **siempre** en `127.0.0.1:<puerto>` con contraseña. Bedrock (Geyser) publica su **UDP** solo si lo activas expresamente. |

La contraseña de RCON se genera aleatoriamente al crear el servidor y nunca se
publica fuera del bucle local.

## El cortafuegos es cosa tuya

Serviscraft **no** toca el cortafuegos. Si activas *Acceso desde la red*, el
puerto del juego queda escuchando en tu interfaz de red, pero el cortafuegos del
sistema puede seguir bloqueándolo. Abrirlo es una decisión y una acción que debes
hacer tú, conscientemente.

En Fedora con `firewalld`, por ejemplo:

```bash
# Abre el puerto 25565 solo en tu zona LAN (ejemplo; revisa tu zona real).
sudo firewall-cmd --zone=public --add-port=25565/tcp
# De forma permanente para que sobreviva a los reinicios:
sudo firewall-cmd --zone=public --add-port=25565/tcp --permanent
```

Recomendaciones:

- No expongas el servidor a Internet si no sabes protegerlo.
- Prefiere `online-mode=true` (por defecto) para que Mojang valide las cuentas.
- Comprueba con `ss -tlnp | grep 25565` qué está escuchando y dónde.
- Si no necesitas acceso remoto, deja *Acceso desde la red* desactivado: en ese
  caso el puerto solo escucha en `127.0.0.1` y nada es accesible desde fuera.

## Cuentas premium y `online-mode`

El servidor de Minecraft comprueba las cuentas con Mojang cuando
`online-mode=true`, que es el valor por defecto. La pestaña **Unirse** permite
desactivarlo (para que entren clientes sin licencia) y lo trata como una decisión
de seguridad, no como un ajuste cualquiera:

- Al desactivarlo aparece un **aviso permanente** en la pestaña: sin verificación,
  cualquiera puede conectarse **suplantando el nombre de otro jugador**, incluido
  el de un operador, y hacerse con sus permisos.
- Antes de guardarlo se pide **confirmación** explicando ese riesgo.
- El cambio se escribe en `server.properties` (`online-mode`) y **se aplica al
  reiniciar**; Serviscraft no reinicia nada por su cuenta.
- El aviso desaparece en cuanto se vuelve a activar.

Regla práctica: `online-mode=false` solo tiene sentido en un servidor privado, en
tu red de confianza o detrás de un proxy que ya autentique (LuckPerms, AuthMe…).
En cuanto el puerto esté expuesto a Internet, vuelve a activarlo.

## Validación de entradas

Toda la entrada del usuario se valida antes de usarse:

- **Nombres**: se normalizan (se recortan y colapsan los espacios) y tienen
  longitud limitada; el identificador interno solo admite `[a-z0-9-]`.
- **Puertos**: rango 1024–65535, y se comprueba que estén libres antes de asignar.
- **Memoria**: entre 512 MB y 32 GB.
- **Rutas**: cualquier operación sobre archivos se resuelve dentro de la carpeta
  del servidor; el *path traversal* (`../`) se rechaza.
- **Credenciales**: los nombres de archivo no pueden contener separadores de ruta.
- **Comandos del servidor**: se envía una única línea al RCON, sin saltos de
  línea, con longitud limitada.
- **Acciones sobre jugadores**: no se escribe ningún comando a mano; el panel de
  jugadores usa una lista cerrada de órdenes y el nombre pasa antes por la misma
  validación (letras, números y guion bajo, hasta 32 caracteres), así que un
  nombre con espacios o símbolos se rechaza sin llegar a la consola.

### La imagen y la descripción del servidor

- **La descripción** (MOTD) se valida antes de escribirla: dos líneas como
  máximo, 45 caracteres útiles por línea y ningún tabulador. Solo se admiten los
  **códigos de color de Minecraft** (`§0`–`§f`, `§l`, `§o`, `§n`, `§m`, `§k`,
  `§r`); un `§` suelto se descarta. El texto se guarda **escapado** en
  `server.properties`, de modo que no puede inyectar nuevas propiedades.
- **La imagen** tiene que ser un **PNG real** de **64×64** y como mucho 64 KiB:
  se comprueban la firma del fichero y la cabecera (`IHDR`), no la extensión. Un
  fichero que dice ser `.png` pero no lo es se rechaza. La ventana redimensiona
  las imágenes que elijas antes de guardarlas, así que el límite no molesta.

### Descargas por URL

El diálogo de descarga de plugins/mods solo acepta `http`/`https` y rechaza:

- direcciones con **credenciales** incrustadas (`https://usuario:clave@…`),
- destinos **locales**: `localhost`, `127.0.0.1` y `::1`.

Además, se limita el tamaño máximo de descarga y se verifica que el archivo sea
un `.jar` válido antes de instalarlo.

> **Matiz importante y deliberado:** se permiten direcciones de **red privada**
> (p. ej. `192.168.1.50`) y no se resuelven los nombres DNS para comprobar su
> destino. Es decir, esta validación **no** es una defensa completa contra
> *SSRF*: un nombre de host que resuelva a una dirección de bucle local no se
> bloquea. Si ese riesgo te importa en tu entorno, no uses la descarga por URL.

### Redirecciones, escrituras y secretos

- **Redirecciones de descarga**: al descargar un mod o un plugin se siguen las
  redirecciones (muchos servidores de descargas las usan), pero **cada salto se
  vuelve a validar** con las mismas reglas que la dirección original. Una
  redirección a `file://`, a un destino local o con credenciales se corta.
- **Escrituras atómicas**: los ficheros que gestiona la aplicación
  (`server.properties`, `meta.json`, el icono del servidor…) se escriben en un
  temporal con nombre impredecible y se mueven a su sitio con `os.replace`. Un
  corte de luz no deja un fichero a medias.
- **Enlaces simbólicos**: si dentro de la carpeta de un servidor aparece un
  enlace (por ejemplo `data/server-icon.png` apuntando a `~/.ssh/id_rsa`),
  Serviscraft **no lo sigue**: al leerlo lo ignora y al borrarlo se niega. Los
  listados de ficheros tampoco enseñan enlaces que se salgan de la carpeta.
- **Secretos en el registro**: la contraseña de RCON, el token de DuckDNS y las
  direcciones con credenciales se escriben como `***` en el registro y en los
  mensajes de error. El token de DuckDNS se guarda con permisos **0600**.
- **Tope en las respuestas RCON**: una respuesta anómala (un plugin que responde
  sin fin) se corta al llegar a un tamaño máximo en vez de llenar la memoria.
- **Variables del contenedor**: las variables extra de un servidor pasan por una
  lista de nombres permitidos; las que la aplicación usa para gobernar el
  contenedor (`EULA`, `TYPE`, `VERSION`, `MEMORY`, RCON, `SERVER_PORT`, `UID`,
  `GID`…) no se pueden sobrescribir desde ahí.
- **Copias de seguridad acotadas**: al restaurar o importar se comprueba el
  tamaño y que las rutas del archivo queden dentro de la carpeta de destino
  (un `.tar` malicioso no puede escribir fuera).

### Iconos de los proyectos

La lista de mods, el catálogo y el de modpacks enseñan el icono de cada proyecto
(el que Modrinth publica en `icon_url`). Para no pedirlo en cada búsqueda, se
descarga **una vez** y se guarda en `~/.cache/serviscraft/iconos/`. La descarga:

- solo acepta `http`/`https` (nunca `file://`, que permitiría leer ficheros del
  equipo),
- tiene un **tamaño máximo** (`MAX_ICON_BYTES`), de modo que un servidor remoto no
  pueda llenar el disco ni colgar la aplicación,
- **nunca lanza**: si algo falla, se usa el icono genérico dibujado por la
  aplicación.

Los iconos **no se ejecutan** ni se interpretan como código: se convierten a una
imagen y, si el fichero no es una imagen válida, se descarta. Se pueden borrar en
cualquier momento (por ejemplo `rm -rf ~/.cache/serviscraft/iconos`): se vuelven
a descargar cuando hagan falta.

### Texturas de objetos y skins

El inventario enseña la textura de cada objeto y la skin del jugador. Para no
depender de la red (ni pedir nada raro), `core/textures.py` impone:

- **Dos servidores y nada más**, siempre por `https`:
  `raw.githubusercontent.com` (espejo de los recursos del juego) y
  `mc-heads.net` (skins). Una dirección con otro host, `http`, `file://` o
  credenciales se rechaza **antes** de abrir la conexión.
- **Redirecciones limitadas**: cada salto se comprueba; si lleva a otro host o a
  otro esquema, se corta.
- **Tamaño máximo** (`MAX_TEXTURE_BYTES`) y **tiempo de espera** corto.
- **Validación del PNG**: firma y cabecera `IHDR`, con medidas concretas
  (16×16 o 32×32 para objetos; 64×64 o 64×32 para skins). Cualquier otra cosa se
  descarta y no se guarda.
- **Caché en disco** (`~/.cache/serviscraft/texturas`) y respaldo dibujado: sin
  conexión, el inventario sigue siendo legible con los iconos de
  `ui/mc_icons.py` y un jugador genérico. `SERVISCRAFT_OFFLINE=1` desactiva toda
  descarga.

Las imágenes no se interpretan como código: se convierten a un `QPixmap` y se
dibujan. Se pueden borrar en cualquier momento (`rm -rf
~/.cache/serviscraft/texturas`).

### Importar un servidor

Importar copia ficheros que vienen de fuera, así que se trata como entrada no
confiable:

- la carpeta o el `.zip` se leen **sin seguir enlaces simbólicos** (ni los de la
  carpeta ni los declarados dentro del `.zip`);
- se rechazan rutas absolutas, con `..` o con letra de unidad; cada fichero se
  escribe comprobando que su destino queda dentro de la carpeta del servidor
  nuevo;
- hay un máximo de ficheros, de tamaño por fichero y de tamaño total; un `.zip`
  que se expande sin control (bomba) se corta;
- si la carpeta elegida contiene **varios servidores**, se pide elegir uno en vez
  de adivinar;
- el destino es una carpeta **nueva**: nunca se sobrescribe un servidor
  existente. Si la copia falla o se cancela, se borra únicamente lo que se acaba
  de crear;
- del servidor original **no se modifica nada**: solo se lee. Al importado se le
  ajustan los puertos internos y la contraseña de RCON (los necesita la
  aplicación) y se escribe `eula=true`, porque el servidor ya venía funcionando.

### Jugadores de Bedrock (Geyser y Floodgate)

Al activar **Permitir jugadores de Bedrock** se publica un puerto **UDP** (19132
por defecto) además del de Java, y la imagen descarga los plugins oficiales de
GeyserMC. Dos consecuencias que conviene tener claras:

- Es **un puerto más expuesto**: si el servidor es accesible desde internet, el
  UDP 19132 también lo será. Ábrelo en el router solo si de verdad quieres que
  entren jugadores de móvil o consola.
- Geyser usa cuentas de **Xbox Live**, no de Java. Con Floodgate activado,
  cualquiera con una cuenta de Xbox Live puede entrar (respeta el mismo
  `online-mode` del servidor para los jugadores de Java). Si quieres limitarlo,
  usa listas de acceso (`whitelist`) o un plugin de permisos.

Serviscraft solo parchea la línea `auth-type` del `config.yml` que **Geyser ha
creado**: si el fichero no existe, no se inventa nada y se reintenta en el
siguiente arranque.

## El nombre para entrar (DuckDNS)

Poner un nombre no cambia el modelo de seguridad: el puerto sigue siendo el
mismo y hay que abrirlo en el router igualmente.

- Serviscraft habla solo con `https://www.duckdns.org/update`, con el nombre y el
  token que tú das. No se envía nada más.
- El **token** se guarda en el `meta.json` del servidor (permisos 0600) y se
  redacta en el registro.
- La **comprobación** del nombre usa el sistema de nombres del equipo; no sale a
  internet ni manda tu IP a ningún sitio.
- La **IP pública** solo se consulta cuando pulsas el botón, contra un servicio
  de IP y sin identificarte.
- El nombre `.duckdns.org` es de DuckDNS, no de Serviscraft: si quieres tu propio
  dominio, la aplicación no lo gestiona.

## Permisos de archivos

- La configuración y la definición de cada servidor se escriben con permisos
  **0600** (solo tu usuario) y las carpetas con **0700**.
- Los datos, mundos y copias quedan en tu carpeta personal, propiedad de tu
  usuario (gracias a `--userns=keep-id`).
- El icono del servidor (`data/server-icon.png`) se escribe con permisos
  **0600**, como el resto de ficheros que crea la aplicación. El proceso de
  Minecraft puede leerlo porque el contenedor corre con tu mismo UID
  (`--userns=keep-id`).
- Serviscraft no escribe fuera de `~/.local/share/serviscraft`,
  `~/.config/serviscraft` y `~/.cache/serviscraft` (o las rutas XDG equivalentes,
  o las que indiques con `--data-dir` / `SERVISCRAFT_HOME`).

## Servidores que quedaron en ejecución

Si al abrir la aplicación se detectan contenedores de Serviscraft aún en marcha
(de una sesión anterior), se muestra un aviso con la lista y **se pregunta** qué
hacer: detenerlos todos o dejarlos funcionando. La aplicación no decide por ti.

El estado que se enseña es siempre el que devuelve Podman, no el último que se
vio: si un servidor se apagó solo, deja de aparecer como «En ejecución» y
**Detener todos** actúa sobre lo que está vivo de verdad. Una carpeta de
servidores con un nombre inválido (por ejemplo, una copia restaurada a mano) se
ignora con un aviso en el registro en vez de impedir que se lean los demás
servidores.

## Copias de seguridad

- Crear una copia nunca modifica los datos originales.
- Restaurar es **transaccional**: se prepara el reemplazo y, si algo falla, se
  revierte al estado anterior.
- Los archivos temporales (`.part`) se limpian si la operación se cancela.
- Restaurar está deshabilitado con el servidor en marcha, para no sobrescribir un
  mundo en uso.
- Las copias automáticas (al detener el servidor y las programadas) tienen un
  límite de conservación configurable, de modo que no llenan el disco sin
  control. Las copias **manuales**, las de **antes de restaurar o eliminar** y
  las **importadas** nunca se borran solas.

## Registro y diagnóstico

Todo lo relevante se registra en
`~/.local/share/serviscraft/logs/serviscraft.log`, incluido el detalle técnico de
los errores. Se puede consultar desde la propia aplicación (*Ver → Ver registro de
Serviscraft*).

El registro **puede contener la contraseña de RCON** en trazas de depuración. Si
vas a compartirlo públicamente (por ejemplo en un informe de error), revísalo
antes.

## Qué NO hace Serviscraft

- No instala ni configura Podman por ti.
- No modifica reglas del cortafuegos.
- No expone la API de Podman por TCP ni crea `podman.socket`.
- No ejecuta nada como `root` ni pide tu contraseña.
- No elimina datos sin confirmación explícita.

## Cómo informar de un problema de seguridad

Si encuentras una vulnerabilidad, describe el caso con el mayor detalle posible
(pasos, versión de Serviscraft, versión de Podman y del sistema) sin publicar
datos personales. No adjuntes el registro sin revisarlo antes.
