# Historia, arquitectura y decisiones de Serviscraft

Este documento cuenta **cómo se hizo** Serviscraft: de dónde salió la idea, qué
decisiones se tomaron, qué problemas aparecieron por el camino y por qué el
código está organizado como está. No es un manual de uso (para eso está
[`uso.md`](uso.md)) ni un registro de cambios (para eso está el
[`%changelog`](../packaging/rpm/serviscraft.spec)); es la historia técnica que
explica el resultado.

## 1. De dónde salió la idea

La idea de partida era sencilla: **tener algo parecido a Aternos, pero en casa**.
Aternos es cómodo, pero el servidor no es tuyo: está en sus máquinas, con sus
límites, su publicidad y sus colas. Para un mundo con amigos bastaba con algo
que hiciera lo mismo en el ordenador de casa, sin renunciar a los datos.

Los objetivos concretos eran:

- **Un servidor de Minecraft de verdad**, con su mundo, sus plugins o mods, su
  consola y sus copias de seguridad. Nada de una capa que oculta el juego.
- **Sin `sudo` y sin un demonio con privilegios.** Podman rootless permitía
  ejecutar contenedores como el usuario normal, así que no había excusa para
  pedir la contraseña de administrador.
- **Fácil de usar para quien solo quiere jugar.** La persona que administra no
  tiene por qué saber qué es un `Dockerfile`, un `RCON` o un `tar.gz`.
- **Los datos, en casa.** Mundos, configuraciones y copias viven en
  `~/.local/share/serviscraft`, no en la nube de nadie.
- **Integración con KDE Plasma.** Una ventana nativa, en español, con tema claro
  y oscuro, que se pueda abrir desde el menú de aplicaciones.
- **Que no se rompa lo que ya funciona.** Actualizar la aplicación no puede
  borrar un mundo ni dejar tirado un servidor antiguo.

Ese último punto terminó siendo el más importante de todos: la mayor parte del
trabajo de las versiones 0.5 a 0.8 no fue añadir funciones, sino **hacer que las
funciones nuevas no rompieran las antiguas**.

## 2. Principios que no se negociaron

Antes de escribir la primera línea se fijaron unas reglas que se han mantenido
hasta la 0.8.0:

1. **Núcleo sin Qt.** `serviscraft/core/` no importa PySide6. Es lógica pura:
   Podman, ficheros, propiedades, copias, validación. Así se puede probar sin
   pantalla y la interfaz no puede colarse en la lógica.
2. **Una sola puerta a Podman.** La interfaz nunca ejecuta comandos. Todo pasa
   por `core.manager.ServerManager`, que a su vez usa `core.podman` con listas
   de argumentos, nunca con `shell=True`.
3. **Solo contenedores propios.** Serviscraft solo toca contenedores cuyo nombre
   empieza por `serviscraft`. Un contenedor ajeno del usuario es sagrado.
4. **Nada de `sudo`.** Ni para instalar, ni para arrancar, ni para arreglar
   permisos. Si algo necesita privilegios, se hace de otra forma o no se hace.
5. **La API de Podman no se expone por TCP.** Se usa el binario `podman` y su
   socket rootless, que ya está protegido por los permisos del usuario. Abrir un
   puerto para la API sería una puerta trasera innecesaria.
6. **Los datos no se borran sin confirmación.** Ni al desinstalar, ni al
   actualizar, ni al limpiar copias. Las copias automáticas tienen retención;
   las manuales, no.
7. **Español en la interfaz, español en los comentarios.** Sin acentos en las
   cadenas visibles (para evitar problemas de codificación en según qué
   entornos), con acentos en la documentación. Los nombres de variables y
   funciones también están en español cuando son de dominio.
8. **Validar todo lo que viene de fuera.** Nombres, puertos, rutas, `.zip`,
   `.jar`, iconos, respuestas HTTP. Un programa que ejecuta contenedores no
   puede confiar en una cadena que llega de un formulario.

## 3. Línea de tiempo

El proyecto se construyó en iteraciones muy rápidas entre el **18 y el 19 de
octubre de 2026**. Cada versión se probó, se empaquetó y se instaló antes de
pasar a la siguiente. Esta es la película de lo que fue pasando.

| Versión | Idea central |
| --- | --- |
| 0.1.0 | Esqueleto: crear servidores, consola, propiedades, mundos, copias, CPU/RAM. |
| 0.2.0 | Que crear un servidor funcione de verdad; catálogo de Modrinth; cambiar de versión. |
| 0.3.0 | Copias automáticas y programadas; jugadores por RCON; modpacks; reiniciar bien. |
| 0.4.0 | Mods, registros, unirse, ajustes por secciones; mods que faltan; tareas de fondo. |
| 0.5.0 | Reparar servidores antiguos; migraciones; Bedrock; iconos; ventanas estrechas. |
| 0.6.0 | Jugadores con cara; inventario; consola con personalidad; ayuda contextual. |
| 0.7.0 | DuckDNS; icono y MOTD; cabecera adaptable; auditoría de seguridad. |
| 0.8.0 | Texturas y skins; listas unificadas; renombrar copias; CPU/RAM; importar; estado real. |

### 0.1.0 — El esqueleto

La primera versión ya tenía lo imprescindible: crear un servidor con la imagen
`docker.io/itzg/minecraft-server`, arrancarlo y pararlo, ver la consola en
tiempo real, editar `server.properties`, instalar plugins o mods, gestionar
mundos, hacer copias de seguridad y ver CPU y memoria.

Detrás de esa lista había ya decisiones importantes:

- **Una imagen OCI universal** (`itzg/minecraft-server`) en vez de una imagen
  por tipo de servidor. La variable `TYPE` elige Vanilla, Paper, Fabric o Forge.
  Menos imágenes que mantener y menos sorpresas.
- **Un contenedor por servidor**, con nombre `serviscraft-<id>`, puerto de juego
  y puerto RCON propios, y un volumen para los datos.
- **`--userns=keep-id`** cuando hace falta, para que los ficheros del volumen
  sigan perteneciendo al usuario del host. Sin esto, el mundo acaba con dueños
  raros y las copias fallan.
- **RCON solo en `127.0.0.1`**, nunca publicado a la red. La consola y las
  órdenes de jugadores van por ahí.
- **Estadísticas por `podman stats --format json`**, no por la API. Es más
  lento, pero no hay que abrir nada.

El esqueleto se construyó con la idea de que **la interfaz fuera una capa
fina**: los botones llaman a métodos del `ServerManager`, y el `ServerManager`
hace el trabajo. Esa separación se ha mantenido y es la razón de que hoy haya
776 pruebas sin necesidad de un servidor real.

### 0.2.0 — Que crear un servidor funcione

La 0.1.0 tenía un fallo bochornoso: el asistente de creación no se abría. La
causa era un orden de inicialización: se comprobaba si el puerto estaba libre
**antes** de crear el botón «Crear servidor», y esa comprobación lanzaba una
excepción que impedía construir el resto del diálogo. Se reordenó la
construcción y se añadió una prueba que abre el asistente de verdad.

En esta versión también entraron:

- **Cambiar la versión de Minecraft** de un servidor existente, con el Java
  recomendado calculado automáticamente y un aviso de compatibilidad del mundo.
- **El catálogo de Modrinth**, con búsqueda, instalación con un clic y
  verificación **SHA-512** de cada descarga. No se instala un `.jar` si el hash
  no coincide.
- **Paper por defecto**, porque admite plugins y es lo que la mayoría quiere.
- Botones para abrir la carpeta de datos y la de copias en el gestor de
  archivos.

Aquí apareció una lección que se repetiría: **las pruebas de la interfaz no
basta con que construyan la ventana; tienen que pulsar los botones**. El fallo
del asistente no se veía creando el objeto, solo abriéndolo.

### 0.3.0 — Copias, jugadores y modpacks

La 0.3.0 fue la versión de la tranquilidad: por fin había copias automáticas.

- **Copia al detener**: cada parada ordenada guarda un `.tar.gz` antes de
  apagar. Si el servidor se cae, la copia programada es la red de seguridad.
- **Copias programadas** cada cierto número de minutos, con retención
  configurable. La limpieza **solo** afecta a las copias automáticas; una copia
  manual nunca se borra sola.
- **Origen visible** de cada copia: al detener, programada, manual, automática o
  importada. Saber de dónde salió una copia es la mitad de saber si sirve.
- **Pestaña Jugadores**: conectados, lista blanca, operadores y bloqueados, con
  OP, expulsión, bloqueo y perdón por RCON.
- **Modpacks de Modrinth** con su cargador (Fabric, Forge o Quilt) y un aviso
  claro cuando el pack solo existe para NeoForge.
- **Reiniciar = parada ordenada + arranque**, no un `restart` a lo bruto.
- **Dos copias en el mismo segundo ya no se pisan**: el nombre incluye un
  sufijo único si hace falta.

El detalle de las copias parece menor, pero fue uno de los primeros sitios donde
se vio que **el reloj no es un identificador**. Dos clics seguidos pueden caer
en el mismo segundo; si el nombre es solo la fecha, la segunda copia sobrescribe
la primera. Se corrigió antes de que alguien perdiera un mundo.

### 0.4.0 — Mods, registros y unirse

La 0.4.0 convirtió la ventana en algo que se puede usar sin leer la
documentación:

- **Selector de modpacks** con cargador, versiones de Minecraft, descargas y
  última actualización, con filtros por cargador y por lado (cliente/servidor).
- **Catálogo de mods y plugins** con los mismos datos, y solo contenido de los
  cargadores que el servidor entiende. Enseñar un mod de Fabric en un servidor
  Forge es una forma estupenda de hacer perder el tiempo.
- **Versiones de Minecraft de la lista publicada**, no un campo de texto libre.
  Un botón permite actualizar la lista cuando Mojang publica una nueva.
- **Ajustes por secciones**, con memoria y Java cambiables en un servidor ya
  creado. La memoria, con deslizador.
- **Pestaña Mods**: activar y desactivar sin borrar (se renombra el `.jar` a
  `.jar.desactivado`), eliminar, y añadir desde Modrinth, desde un `.jar` del
  equipo o desde una URL.
- **Pestaña Registros**, con filtro, seguimiento automático y un botón para
  buscar los mods que faltan.
- **Pestaña Unirse**, con la dirección y el puerto, y el cambio entre cuenta
  premium y sin licencia, con aviso y confirmación.
- **Detección de mods que el modpack no pudo descargar**: se leen del registro,
  se muestra su enlace de Modrinth, se marcan en verde cuando ya están y se
  copia el `.jar` descargado dentro del servidor.

También se corrigieron dos cosas pequeñas que molestaban mucho:

- Las **cajas de números** (memoria y puerto) mezclaban el valor anterior al
  escribir encima, y la rueda del ratón las cambiaba sin querer. Se reescribió
  el comportamiento.
- Las **tareas de fondo** avisaban a ventanas que ya se habían cerrado y
  provocaban errores en el registro. Se pasó a referencias débiles y a
  comprobar que el objeto sigue vivo.

### 0.5.0 — No romper lo viejo

La 0.5.0 fue la versión de la compatibilidad, y la que más miedo daba.

- **Reparación de servidores antiguos**: los que murieron por llevar el Java
  equivocado se reparan solos al arrancar. Se explica el motivo y se cambia la
  etiqueta de Java **sin tocar el mundo**.
- **Migración de datos**: los ficheros de versiones anteriores se migran
  conservando todas las claves. `META_VERSION` subió a 3; el código guarda las
  claves desconocidas en `_extra` en vez de tirarlas.
- **Seguimiento en vivo de la consola** activado por defecto y conmutable, sin
  bloquear la ventana.
- **Pestaña Unirse paso a paso**, con la IP pública y una guía para jugar desde
  fuera de casa.
- **Bedrock** (móvil, tablet y consola) con Geyser y Floodgate en servidores
  Paper, con puerto UDP propio y ajuste automático de Floodgate.
- **Iconos junto al nombre**: Java (césped) y Bedrock (piedra), y el icono real
  de cada mod o plugin en las listas.
- **Textos de ayuda adaptables** a ventanas estrechas, sin recortes ni
  solapamientos.

El aprendizaje de la 0.5.0 fue que **una actualización nunca puede ser un
borrado**. Cualquier cambio en el formato de datos se hizo con una migración
explícita y una prueba que carga un fichero antiguo de verdad. No se valida de
más: si una versión futura añade una clave, la actual la conserva.

### 0.6.0 — Jugadores, inventario y personalidad

La 0.6.0 fue la de «que se sienta como un servidor de verdad»:

- **Fichas de resumen** de jugadores: conectados, en lista blanca, operadores y
  bloqueados, con la cara del jugador en la tabla y colores en los «Sí».
- **Inventario del jugador**: una ventana con la mochila, la armadura y la barra
  rápida tal y como las ve el jugador, con vida, comida y nivel. Se lee del
  servidor por la consola (RCON), sin instalar nada ni tocar el mundo.
- **Consola con más personalidad**: punto de estado, leyenda de colores, filtro
  «Solo problemas» y «Copiar todo».
- **Botones «?»** con la explicación de cada sección en Consola, Jugadores, Mods
  y Unirse; etiquetas cortas y tooltips en las acciones de jugadores.

El inventario fue el primer sitio donde apareció la **descarga bajo demanda**:
las texturas de los objetos no se pueden incluir con el programa (son de
Mojang), así que se piden a un espejo, se validan y se guardan en caché. Si no
hay red, se usan iconos dibujados a mano. Ese patrón se reutilizó en la 0.8.0
para las skins.

### 0.7.0 — Un nombre, una imagen y una auditoría

La 0.7.0 tuvo tres frentes:

1. **DuckDNS**: en vez de dar una IP, se puede dar un nombre
   (`nombre.duckdns.org:puerto`). La aplicación comprueba que resuelve y
   actualiza la IP automáticamente al arrancar. Se descartó un dominio
   `.serviscraft` porque no existe como TLD y no se puede inventar. También se
   documentó el caso de CGNAT, donde no hay forma de abrir un puerto: para eso
   están playit.gg o Tailscale.
2. **Imagen y descripción del servidor**: el icono de 64×64 y las dos líneas de
   la lista de Minecraft, con los 16 colores del juego, vista previa y ocho
   bloques ya dibujados. El guardado es atómico y valida el PNG.
3. **Cabecera adaptable**: con poco ancho, los botones bajan a su propia línea
   para que el nombre del servidor nunca desaparezca.

Y, además, la **auditoría de seguridad** que se hizo antes de publicar: revisión
de rutas, enlaces simbólicos, redirecciones HTTP, secretos en el registro,
permisos de ficheros, límites de las copias y configuración de los contenedores.
De ahí salieron cambios como `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
`--pids-limit=1024`, permisos `0700` para las carpetas y `0600` para los
ficheros sensibles, y el filtrado de secretos en el registro.

### 0.8.0 — Texturas, listas, CPU y el estado real

La 0.8.0 es la versión de los detalles que hacen que la aplicación se sienta
terminada:

- **Texturas de objetos y skins de jugadores** en el inventario, con caché,
  validación de PNG, límite de tamaño y respaldo procedural.
- **Listas de jugadores unificadas**: una sola ventana con pestañas para lista
  blanca, bloqueados y operadores, y un interruptor para `white-list`. Cuando el
  servidor está apagado, las listas se editan **directamente en los ficheros**
  (`whitelist.json`, `ops.json`, `banned-players.json`) con el UUID offline de
  Java; solo `kick` exige el servidor encendido.
- **Renombrar copias de seguridad**: se cambia la etiqueta de la ficha `.json`;
  el `.tar.gz` no se toca.
- **Monitor de CPU y RAM** con aspecto de las barras de experiencia de
  Minecraft, y la CPU **nunca pasa del 100 %**.
- **«Detener todos»** que apaga de verdad todos los servidores.
- **Importar servidores** desde una carpeta o el `.zip` de Aternos, reconociendo
  el tipo, la versión, el mundo, los plugins/mods y el origen (Aternos,
  exaroton, Minehut…), sin descargar la imagen ni crear el contenedor hasta el
  primer inicio.
- **Estado real de ejecución**: la aplicación dejó de mostrar «en marcha» un
  servidor que ya estaba apagado.

Las tres historias técnicas de esta versión (la CPU, el estado y la
importación) están contadas en detalle en el apartado 5, porque son las que más
tiempo costaron.

## 4. Arquitectura

### 4.1. Dos capas y una frontera

```
┌──────────────────────────────────────────────────────────────┐
│  ui/  (PySide6)                                              │
│  Ventanas, diálogos, modelos de tabla, estilos, iconos.      │
│  No ejecuta comandos: llama al ServerManager.                │
└───────────────────────────┬──────────────────────────────────┘
                            │  métodos y dataclasses
┌───────────────────────────▼──────────────────────────────────┐
│  core/  (Python puro, sin Qt)                                │
│  manager, podman, store, backup, players, import_server,     │
│  textures, properties, validation, models, logs, ddns…       │
└───────────────────────────┬──────────────────────────────────┘
                            │  listas de argumentos
┌───────────────────────────▼──────────────────────────────────┐
│  podman rootless  →  contenedor itzg/minecraft-server         │
└──────────────────────────────────────────────────────────────┘
```

La frontera se comprueba con una prueba (`tests/test_arquitectura.py`): si
`core` importa Qt, la prueba falla. No es una convención oral; es una regla
ejecutable.

### 4.2. Estructura de carpetas

```
serviscraft/
├── app.py                  # argparse, arranque, --self-test
├── __main__.py             # python -m serviscraft
├── core/
│   ├── manager.py          # orquestador: crear, arrancar, parar, stats, RCON
│   ├── podman.py           # construcción segura de argumentos y ejecución
│   ├── store.py            # fichas de servidor, migraciones, META_VERSION
│   ├── models.py           # ServerSpec, ServerState, ServerStats, ServerView
│   ├── backup.py           # copias, retención, renombrar
│   ├── players.py          # listas, UUID offline, acciones
│   ├── import_server.py    # reconocer y copiar servidores existentes
│   ├── textures.py         # descarga/caché/validación de texturas y skins
│   ├── server_files.py     # server.properties, icono, MOTD, RCON
│   ├── mods.py             # manifiesto, activar/desactivar, faltantes
│   ├── modrinth.py         # catálogo, versiones, SHA-512
│   ├── bedrock.py          # Geyser/Floodgate
│   ├── ddns.py             # DuckDNS
│   ├── netinfo.py          # IP local/pública, puertos
│   ├── validation.py       # nombres, puertos, rutas, tamaños
│   ├── security.py         # permisos, secretos, redacción
│   └── …
├── ui/
│   ├── main_window.py      # ventana principal y cableado
│   ├── sidebar.py          # lista de servidores y estado
│   ├── console_panel.py    # consola, filtros, órdenes
│   ├── players_panel.py    # resumen y acceso a listas
│   ├── players_manager_dialog.py
│   ├── inventory_dialog.py # rejilla, texturas, skin
│   ├── skin_view.py        # composición de cara y cuerpo
│   ├── import_dialog.py    # importar carpeta/.zip
│   ├── create_dialog.py    # asistente
│   ├── mods_panel.py
│   ├── logs_panel.py
│   ├── join_panel.py
│   ├── settings_panel.py
│   ├── common.py           # FlowRow, WrappingLabel, MinecraftBar, TaskRunner
│   ├── theme.py            # QSS claro/oscuro a partir de la paleta de KDE
│   └── mc_icons.py         # iconos procedurales de Minecraft
├── tests/                  # 28 ficheros, 607 funciones, 776 casos
├── docs/                   # uso, desarrollo, seguridad, instalación, historia
├── packaging/              # RPM, DEB, AppImage, .desktop
└── Makefile
```

### 4.3. El viaje de una orden

Un ejemplo real, «Detener»:

1. La tarjeta del servidor emite una señal.
2. `MainWindow` pide confirmación y llama a `manager.stop(spec, backup=True)`.
3. `ServerManager` pide una copia a `BackupManager` (si está configurada).
4. `BackupManager` crea el `.tar.gz` en la carpeta del servidor y escribe la
   ficha `.json` con origen y fecha.
5. `ServerManager` ejecuta `podman stop --time 60` con una lista de argumentos.
6. Al terminar, `ServerManager` vuelve a leer el estado real y emite una vista
   nueva; la interfaz pinta «Detenido», no lo que creía antes.

Ese último paso es importante: **la interfaz no inventa el estado**. Lo lee de
Podman y de la ficha del servidor. Si no coincide, gana la realidad.

### 4.4. Dónde vive cada cosa

| Ruta | Contenido |
| --- | --- |
| `~/.local/share/serviscraft/servers/<id>/` | Datos del servidor (mundo, plugins, configuración). |
| `…/servers/<id>/.serviscraft.json` | Ficha: nombre, tipo, versión, puertos, memoria, Java, etc. |
| `…/servers/<id>/backups/` | Copias `.tar.gz` y sus fichas `.json`. |
| `~/.config/serviscraft/` | Preferencias de la aplicación. |
| `~/.cache/serviscraft/texturas/` | Texturas e iconos descargados. |
| `~/.cache/serviscraft/` | Registros y temporales. |

Todo se puede redirigir con `SERVISCRAFT_HOME` (útil para pruebas y para un
modo portátil).

### 4.5. Modelo de datos y migraciones

`ServerSpec` es una `dataclass` con los datos que definen un servidor. La ficha
se guarda como JSON con `meta_version`. Al cargar:

- Se leen las claves conocidas.
- Las desconocidas se guardan en `_extra` y se vuelven a escribir.
- Se aplican migraciones por versión.
- Si una ficha es inválida, **se ignora con un aviso**, no se tumba la lista
  entera.

Esa última regla se añadió después de un fallo real: una carpeta con un
identificador inválido hacía que `load_all()` abortara y la ventana se quedara
con una lista a medias. Ahora cada carpeta se carga de forma independiente; una
ficha rota no puede ocultar las demás.

## 5. Los problemas que hubo que resolver

Esta es la parte que no sale en el changelog: los diagnósticos, las hipótesis
falsas y los arreglos.

### 5.1. La CPU marcaba 0 % o 200 %

Al principio la CPU no aparecía, y cuando apareció, marcaba **200 %**. No era un
fallo de formato: Podman mide el uso **por núcleo**. Un proceso que satura dos
núcleos consume «200 %» en su escala, aunque para el equipo sea el 25 % si tiene
ocho núcleos.

La solución fue normalizar:

```
porcentaje_equipo = porcentaje_podman / núcleos_del_equipo
```

y acotar a 100 en la interfaz. El 200 % de un equipo de 8 núcleos se muestra
como 25 %. Además, `ServerStats` es `frozen=True`, así que la normalización no
puede mutar el objeto: se usa `dataclasses.replace`.

También se separó la **memoria asignada** de la memoria que informa Podman. La
barra de RAM se compara con `spec.memory_mb`, no con el límite del contenedor,
porque el límite incluye la sobrecarga de la JVM y no es lo que el usuario
eligió.

### 5.2. «Detener todos» no detenía todos

El síntoma era doble: la aplicación mostraba un servidor como «en marcha»
cuando ya estaba apagado, y «Detener todos» no lo tocaba. La causa estaba en una
carpeta llamada `Copia de prueba-b6822d`, con un identificador inválido.

`ServerStore.load_all()` recorría las carpetas y, al encontrar una ficha
inválida, lanzaba `ServiscraftError`. El método no lo capturaba, así que la
carga se interrumpía. La lista que veía la interfaz quedaba incompleta y el
estado se desincronizaba. La solución:

- Cada carpeta se carga por separado.
- Un `ServiscraftError` se registra como aviso y se salta esa carpeta.
- El resto de servidores se cargan y se pueden parar.

La carpeta inválida sigue en disco: **no se borra sin permiso**. Solo se ignora.

### 5.3. El servidor «en marcha» que ya estaba apagado

Relacionado con lo anterior, pero con otra causa: la interfaz se fiaba de la
última vista que había recibido y no volvía a preguntar. Ahora, después de
cualquier operación (arrancar, parar, reiniciar, detener todos) se consulta el
estado real y se emite una vista nueva. Si Podman dice que no hay contenedor, el
estado es `EXITED`, no `RUNNING`.

### 5.4. El Java equivocado mató servidores antiguos

La imagen `itzg/minecraft-server` publica etiquetas `java8`, `java17`, `java21`
y `java25`. Un servidor antiguo con Java 21 puede no arrancar si el mundo o el
modpack esperan Java 17. En la 0.5.0 se añadió una reparación al arrancar:

- Se detecta el Java configurado y la versión de Minecraft.
- Si no encaja, se explica el motivo y se cambia **solo la etiqueta de Java**.
- El mundo no se toca.

La reparación es conservadora: si no hay certeza, no se cambia nada y se avisa.

### 5.5. Dos copias en el mismo segundo

El nombre de una copia era `AAAA-MM-DD_HH-MM-SS`. Dos clics seguidos caben en el
mismo segundo y la segunda copia pisaba a la primera. Se añadió un sufijo único
y una prueba que crea dos copias seguidas y comprueba que ambas existen.

### 5.6. Ventanas estrechas, mosaicos y etiquetas de 0 píxeles

En KDE con un gestor de mosaico (Polonium, en este caso), una ventana puede
ignorar su tamaño mínimo y quedarse muy estrecha. Ahí aparecieron tres
problemas:

1. **Etiquetas que se comían el texto.** Un `QLabel` con `wordWrap` sabe
   ajustar el texto, pero algunos diseños de Qt le piden el alto una sola vez,
   con el ancho de su tamaño «ideal». Si el texto ocupa dos líneas, la segunda
   se corta. Se creó `WrappingLabel`, que reserva el alto que necesita.
2. **Botones que desaparecían.** La cabecera tenía el nombre del servidor y los
   botones en la misma línea; con poco ancho, el nombre se quedaba en 0 px. Se
   creó `FlowRow` y se pasó a dos líneas cuando no caben.
3. **La rejilla del inventario se estiraba.** Se fijó el tamaño de los huecos,
   se pegó la skin a la derecha y se añadió scroll horizontal en ventanas
   estrechas.

El mínimo usable quedó en **480×420**. Por debajo, la barra lateral se oculta y
se abre con `Ctrl+B`.

### 5.7. Iconos vacíos en algunos escritorios

Qt puede no encontrar los iconos del tema si no hay un tema de iconos completo
(por ejemplo, en un entorno mínimo o en las pruebas sin pantalla). En vez de
depender de nombres como `media-playback-start`, se dibujaron iconos
procedurales con `QPainter` (`ui/mc_icons.py`): bloques, herramientas, caras,
cubos. Se usan como respaldo cuando el tema no tiene el icono, y también para
los iconos de Minecraft, que no existen en los temas del sistema.

### 5.8. Las pruebas se quedaban colgadas en un diálogo modal

Las pruebas de la interfaz construyen la ventana real. Si había un servidor
`RUNNING`, `_check_orphans` abría un `QMessageBox` modal y la prueba se quedaba
esperando para siempre. La solución en las pruebas es parchear `QMessageBox.exec`
y `show_info`/`show_error`/`confirm`, pero el aprendizaje de diseño fue otro:
**las comprobaciones al arrancar no pueden bloquear la ventana**. Se movieron a
un `QTimer` y se convirtieron en avisos no modales cuando es posible.

### 5.9. Listas de jugadores con el servidor apagado

La primera versión de las listas solo sabía hablar por RCON. Si el servidor
estaba apagado, no había forma de añadir a un amigo. La solución fue escribir
directamente en los ficheros de Minecraft:

- `whitelist.json`, `ops.json`, `banned-players.json`.
- El UUID de un jugador sin licencia se calcula con el algoritmo **offline** de
  Java (`UUID.nameUUIDFromBytes("OfflinePlayer:<nombre>")`, MD5 con bits de
  versión 3).
- Se escribe de forma atómica y se conserva el resto del fichero.
- Solo `kick` (y el inventario) exigen el servidor encendido.

Así se puede preparar la lista blanca antes del primer arranque, que es justo
cuando hace falta.

### 5.10. Importar un Aternos sin romper nada

Importar no es copiar una carpeta y ya. Un `.zip` de Aternos puede traer:

- Enlaces simbólicos que apuntan fuera de la carpeta.
- Rutas con `..` (zip slip).
- Un `server.properties` con puertos y RCON que chocan con los del servidor
  nuevo.
- Un `eula.txt` sin aceptar.
- Carpetas enormes que no hacen falta (`libraries`, `logs`, `crash-reports`,
  `cache`, `versions`, `.fabric`).

`core/import_server.py` reconoce el tipo (Vanilla, Paper, Fabric, Forge), la
versión, el mundo, los plugins/mods y el origen (Aternos, exaroton, Minehut…).
Después copia **sin tocar el original**, omitiendo lo prescindible, y fuerza:

- Puertos de juego y RCON propios.
- `eula=true`.
- Conserva MOTD, `white-list`, `level-name` e icono.

No descarga la imagen ni crea el contenedor: eso ocurre en el primer arranque.
Si el `.zip` es inválido, se aborta antes de escribir nada.

### 5.11. Texturas y skins sin abrir la puerta de atrás

Las texturas son de Mojang y no se pueden incluir en el repositorio. Se
descargan bajo demanda, pero con reglas estrictas:

- Solo HTTPS.
- Hosts fijos: `raw.githubusercontent.com` y `mc-heads.net`.
- Redirecciones validadas (no se sigue una redirección a otro host).
- Máximo 256 KB y tiempo de espera de 4 s.
- Se valida la cabecera PNG antes de aceptar el fichero.
- Caché en `~/.cache/serviscraft/texturas/`.
- `SERVISCRAFT_OFFLINE=1` desactiva toda la red.
- Si algo falla, se usa un icono procedural; la ventana nunca se queda en
  blanco.

### 5.12. Empaquetar sin `sudo`, sin `dpkg-deb` y con espacios en la ruta

Tres obstáculos de empaquetado:

1. **RPM con espacios en la ruta.** `rpmbuild` no lleva bien un `_topdir` con
   espacios. El `Makefile` construye en `~/.cache/serviscraft-build` y copia el
   resultado a `dist/`.
2. **DEB sin `dpkg-deb`.** En la máquina de desarrollo no estaba instalado. El
   `.deb` se construye con `ar` y `tar`, que sí están, y se verifica con un
   script propio.
3. **AppImage.** Se empaqueta Python 3.12 de *python-build-standalone*,
   PySide6, el código y un `AppRun`. Podman **no** se incluye: es una
   dependencia del sistema.

El resultado se comprueba con `--self-test`, que responde con la versión y el
estado de las dependencias.

## 6. Seguridad

La seguridad se trató como una parte del diseño, no como un parche final. Los
puntos principales:

- **Rootless de principio a fin.** Podman sin `sudo`, sin demonio root y sin
  API TCP.
- **Contenedores con menos privilegios**: `--cap-drop=ALL`,
  `--security-opt=no-new-privileges`, `--pids-limit=1024`.
- **Solo contenedores propios**: prefijo `serviscraft`.
- **RCON en `127.0.0.1`**, no publicado.
- **Permisos**: `0700` para carpetas sensibles, `0600` para ficheros con
  secretos.
- **Secretos fuera del registro**: el logger redacta tokens, contraseñas y
  claves.
- **Validación de rutas**: nada de `..`, enlaces simbólicos fuera de la carpeta
  ni rutas absolutas inesperadas.
- **Descargas**: HTTPS, hosts permitidos, redirecciones validadas, tamaño
  máximo y hash cuando el catálogo lo ofrece.
- **Copias**: límites de tamaño y retención; las manuales no se borran.
- **Datos**: las actualizaciones no borran `data/`.

El detalle completo está en [`seguridad.md`](seguridad.md).

## 7. Pruebas

La suite es la red de seguridad del proyecto:

- **28 ficheros**, **607 funciones** y **776 casos** (con parametrización).
- Se ejecutan con `QT_QPA_PLATFORM=offscreen`, sin pantalla y sin lanzar
  contenedores reales.
- `tests/test_gui.py` construye la ventana completa, recorre pestañas, abre
  diálogos y comprueba tamaños, textos e iconos.
- `tests/test_arquitectura.py` verifica que `core` no importa Qt.
- Hay pruebas de migración con ficheros antiguos reales.
- Hay pruebas de seguridad para rutas, enlaces, redirecciones, secretos y
  límites.

Comando:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --tb=short
```

La lección más repetida: **una prueba de interfaz que solo construye la ventana
no prueba nada**. Hay que pulsar el botón, abrir el diálogo y comprobar el
resultado. El fallo del asistente de creación de la 0.2.0 es el ejemplo perfecto.

## 8. Empaquetado

| Formato | Cómo se construye | Notas |
| --- | --- | --- |
| RPM | `rpmbuild` en `~/.cache/serviscraft-build` | Para Fedora/KDE; depende de `python3-pyside6` y `podman`. |
| DEB | `ar` + `tar` | Para Debian/Ubuntu; mismas dependencias. |
| AppImage | Python standalone + PySide6 + `AppRun` | Portátil; Podman sigue siendo externo. |

`make packages` reconstruye los tres. `make install-user` instala el lanzador y
el `.desktop` en el perfil del usuario, sin `sudo`.

## 9. Interfaz y aspecto

- **Tema claro y oscuro** generado a partir de la paleta de KDE, no de colores
  fijos. Así la aplicación encaja con el escritorio.
- **Barras de CPU y RAM** con el aspecto de las barras de experiencia de
  Minecraft: fondo oscuro, degradado verde y marcas cada 6 px. Se pintan a mano
  (`MinecraftBar`) para no depender del estilo del sistema.
- **Iconos procedurales** para todo lo que un tema de escritorio no tiene:
  bloques, herramientas, caras, Java/Bedrock, mods y plugins.
- **Textos de ayuda contextual** con botones «?» en cada sección.
- **Diseño adaptable**: `FlowRow`, `WrappingLabel`, `ElidedLabel`, scroll
  horizontal y barra lateral ocultable.

## 10. Decisiones que se descartaron

- **Un panel web.** Habría que abrir un puerto y mantener una segunda interfaz.
  La ventana nativa es más segura y más cómoda en el escritorio.
- **La API REST de Podman.** Obliga a exponer un socket o un puerto. El binario
  `podman` con listas de argumentos es suficiente y no añade superficie.
- **Docker.** El demonio root y el grupo `docker` son un privilegio de facto.
  Rootless era un requisito, no un extra.
- **Un dominio `.serviscraft`.** No existe como TLD. DuckDNS resuelve el
  problema sin inventar nombres.
- **Incluir texturas de Minecraft.** Son de Mojang. Se descargan en tiempo de
  ejecución, con caché y respaldo.
- **Guardar el estado «en marcha» en la ficha.** El estado se pregunta a
  Podman; la ficha solo guarda la configuración. La realidad manda.

## 11. Lecciones

1. **El estado no se guarda, se consulta.** Los errores de «en marcha» cuando
   ya estaba apagado venían de creer a la interfaz en vez de a Podman.
2. **Una ficha rota no puede tumbar la lista.** Aislar errores por servidor es
   más importante que validar el conjunto.
3. **Los identificadores no son relojes.** Fechas con segundos, sufijos únicos
   y nombres de fichero que no colisionan.
4. **Normaliza las unidades en el borde.** Podman habla de porcentaje por
   núcleo; la interfaz habla de porcentaje del equipo. La conversión va en el
   núcleo, no en la vista.
5. **Las ventanas estrechas son un caso normal.** Un gestor de mosaico puede
   ignorar el tamaño mínimo; hay que diseñar para 480 px.
6. **Las descargas son una frontera de seguridad.** HTTPS, hosts fijos, tamaño,
   timeout, validación y caché.
7. **Una actualización no puede borrar.** Migraciones explícitas, claves
   desconocidas conservadas, copias manuales intactas.
8. **Prueba el flujo, no el constructor.** Abre el diálogo, pulsa el botón,
   comprueba el resultado.

## 12. Cómo seguir

Si quieres tocar el código:

1. Lee [`desarrollo.md`](desarrollo.md) para la estructura y las convenciones.
2. Ejecuta las pruebas antes y después de cada cambio.
3. Mantén `core` sin Qt.
4. Si cambias el formato de datos, sube `META_VERSION` y escribe una migración
   con una prueba que cargue un fichero antiguo.
5. Si añades una descarga, respeta las reglas de [`seguridad.md`](seguridad.md).
6. Si añades una ventana, pruébala a 480×420.

Serviscraft no pretende ser el gestor de servidores más completo del mundo.
Pretende ser **el que te deja jugar con tus amigos sin pedirte la contraseña de
administrador y sin llevarse tus mundos a otro sitio**. Todo lo demás se hizo
alrededor de esa idea.
