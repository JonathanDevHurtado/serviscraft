# Desarrollo

## Filosofía

Serviscraft separa tajantemente **núcleo** y **interfaz**:

- `serviscraft/core/` **no importa Qt**. Es lógica pura, fácil de probar sin
  pantalla: Podman, ficheros, propiedades, copias, validación…
- `serviscraft/ui/` es la capa Qt (PySide6). No ejecuta comandos directamente:
  todo pasa por `core.manager.ServerManager`.

Esta separación permite probar toda la lógica con `pytest` sin arrancar la
interfaz, y tiene una prueba que verifica que `core` no arrastra Qt.

Además:

- Todas las cadenas de cara al usuario están **en español**.
- Los comentarios y *docstrings* están **en español**.
- Las llamadas a Podman se hacen con listas de argumentos, **nunca** con shell.

## Estructura

```
serviscraft/
├── app.py                     # argparse, arranque de la aplicación, --self-test
├── __main__.py                # permite `python -m serviscraft`
├── core/
│   ├── paths.py               # rutas XDG y constantes globales
│   ├── errors.py              # excepciones propias
│   ├── logging_setup.py       # registro a fichero y excepthook
│   ├── validation.py          # validación de entradas y rutas seguras
│   ├── models.py              # ServerSpec, ServerType, ServerState, ServerStats
│   ├── appconfig.py           # preferencias globales
│   ├── store.py               # persistencia de servidores (meta.json)
│   ├── podman.py              # cliente de la CLI de Podman
│   ├── rcon.py                # cliente RCON en Python puro
│   ├── properties.py          # server.properties (lectura/escritura)
│   ├── server_files.py        # ficheros, plugins, mods y mundos
│   ├── backup.py              # copias de seguridad
│   ├── players.py             # jugadores: nombres, RCON, fichas y listas sin servidor
│   ├── inventory.py           # inventario del jugador (NBT de ``data get entity``)
│   ├── textures.py            # texturas de objetos y skins: descarga, caché y validación
│   ├── import_server.py       # reconocer y copiar un servidor que ya existía
│   ├── versions.py            # versiones de Minecraft y Java recomendado
│   ├── diagnostics.py         # por qué un servidor murió al arrancar
│   ├── bedrock.py             # Geyser/Floodgate: ajustes para jugadores de Bedrock
│   ├── netinfo.py             # IP local y pública (para explicar cómo se conectan)
│   ├── ddns.py                # nombre para entrar (DuckDNS): validar, resolver y mantener
│   ├── appearance.py          # icono de la lista y MOTD con colores (§)
│   ├── icons.py               # caché en disco de los iconos de los proyectos
│   ├── modrinth.py            # catálogo de plugins, mods y modpacks (Modrinth)
│   ├── mods.py                # mods instalados: listar, activar, borrar y añadir
│   ├── logs.py                # registros del servidor: listar y leer el final
│   ├── missing_mods.py        # mods que faltan, leídos del registro
│   └── manager.py             # orquestador (une todo lo anterior)
├── ui/
│   ├── theme.py               # QSS sobre la paleta de KDE (claro/oscuro)
│   ├── tasks.py               # tareas en segundo plano (QThreadPool)
│   ├── common.py              # componentes reutilizables (SectionCard, Chip, «?»…)
│   ├── server_preview.py      # vista previa de la entrada de la lista de Minecraft
│   ├── mc_icons.py            # iconos dibujados (Java, Bedrock, mods, plugins y objetos)
│   ├── skin_view.py           # cara y cuerpo del jugador a partir de su skin
│   ├── dialogs.py             # confirmaciones, avisos y detalles
│   ├── console_panel.py       # consola en vivo, filtro y envío de comandos
│   ├── properties_panel.py    # editor de server.properties
│   ├── files_panel.py         # plugins, mods, mundos y ficheros
│   ├── catalog_dialog.py      # buscar e instalar plugins/mods (Modrinth)
│   ├── modpack_dialog.py      # buscar y elegir un modpack (Modrinth)
│   ├── players_panel.py       # jugadores: conectados, lista blanca y bloqueos
│   ├── players_manager_dialog.py  # lista blanca, bloqueados y operadores en una ventana
│   ├── inventory_dialog.py    # mochila del jugador con la forma del juego
│   ├── mods_panel.py          # mods instalados y mods que faltan
│   ├── logs_panel.py          # registros con filtro y seguimiento
│   ├── join_panel.py          # cómo se conectan los jugadores (Java y Bedrock)
│   ├── ddns_dialog.py         # poner o cambiar el nombre para entrar
│   ├── appearance_dialog.py   # imagen y descripción del servidor, con vista previa
│   ├── backups_panel.py       # copias de seguridad
│   ├── details_panel.py       # ficha técnica y mantenimiento
│   ├── create_dialog.py       # asistente de creación
│   ├── import_dialog.py       # importar la carpeta o el .zip de un servidor existente
│   ├── settings_dialog.py     # ajustes del servidor y preferencias
│   ├── server_list.py         # barra lateral
│   └── main_window.py         # ventana principal
└── resources/icons/           # icono de la aplicación
```

## Entorno de desarrollo

```bash
make venv          # .venv con --system-site-packages (reutiliza PySide6)
make run           # inicia la aplicación
make debug         # inicia con registro detallado
make self-test     # comprueba Python, PySide6 y Podman
make test          # todas las pruebas
make test-gui      # solo las pruebas de interfaz
make lint          # ruff (si está instalado)
```

## Pruebas

Las pruebas viven en `tests/` y usan `pytest` (+ `pytest-qt`). Todo se ejecuta
en una carpeta temporal: **nunca** tocan los datos reales del usuario. La
integración de directorios se fuerza con `SERVISCRAFT_HOME`,
`SERVISCRAFT_CONFIG_HOME` y `XDG_CACHE_HOME`, y se eliminan del entorno
`CONTAINER_HOST`, `DOCKER_HOST` y `CONTAINER_CONNECTION`.

```bash
.venv/bin/python -m pytest           # todo
.venv/bin/python -m pytest -m gui    # solo interfaz
.venv/bin/python -m pytest tests/test_backup.py
```

Las pruebas de interfaz usan la plataforma `offscreen` de Qt, construyen la
ventana completa y recorren sus pestañas. Los cuadros de diálogo modales
(`show_error`, `show_info`, `confirm`…) se sustituyen por dobles que no bloquean.

Las pruebas del gestor (`tests/test_manager.py`) sustituyen la descarga de la
imagen y la creación del contenedor por dobles: comprueban el flujo real
(crear, guardar ajustes y cambiar de versión) sin lanzar Podman. Además de la
interfaz, se prueba el **flujo principal completo**: abrir el asistente, rellenar
los datos, crear el servidor y cambiar su versión. Cualquier función nueva debe
tener una prueba que la use como lo haría una persona, no solo una prueba de que
«se construye».

Módulos de prueba con más recorrido:

| Fichero | Qué cubre |
| --- | --- |
| `tests/test_manager.py` | Ciclo de vida del servidor, copia automática al detener, copia programada, retención, jugadores y cambio de versión. |
| `tests/test_backup.py` | Crear, restaurar, exportar, importar, limpiar y **que dos copias del mismo segundo no se pisen**. |
| `tests/test_players.py` | Validación de nombres, análisis de las respuestas RCON (`list`, `whitelist`) y lectura de `whitelist.json`, `ops.json` y `banned-players.json`. |
| `tests/test_inventory.py` | Lectura del inventario NBT: compuestos anidados, claves con y sin comillas, respuestas recortadas y datos sueltos (vida, comida, nivel). |
| `tests/test_textures.py` | Texturas y skins: nombres válidos, PNG del tamaño esperado, caché, sin conexión y direcciones fuera de la lista blanca. |
| `tests/test_import_server.py` | Importar: detección de tipo, versión y origen (Aternos), carpetas anidadas, `.zip` con rutas que se salen o enlaces simbólicos, cancelación y limpieza. |
| `tests/test_modrinth.py` | Búsqueda en el catálogo (cargadores, versiones, lado y fecha), verificación de descargas y elección de versión de un modpack (incluido el caso NeoForge). |
| `tests/test_mods.py` | Inventario de mods, activar/desactivar sin borrar, manifiesto, registros del servidor y análisis de los mods que faltan. |
| `tests/test_tasks.py` | Ciclo de vida de las tareas de fondo: progreso, fallos y apagado sin avisar a ventanas destruidas. |
| `tests/test_versions.py` | Tabla de requisitos de Java y elección de la etiqueta recomendada por versión de Minecraft. |
| `tests/test_diagnostics.py` | Motivos de fallo al arrancar (log del contenedor) y reparación de la etiqueta de Java. |
| `tests/test_migraciones.py` | `meta.json` de versiones anteriores: se migra sin perder claves y sin validar de más. |
| `tests/test_icons.py` | Caché de iconos: clave por dirección, extensión, tamaño máximo, `file://` rechazado y limpieza. |
| `tests/test_bedrock.py` | Geyser/Floodgate, puerto UDP, manifiesto de proyectos y activar Bedrock sin tocar los datos. |
| `tests/test_gui.py` | Recorrido de la ventana real: pestañas, diálogos, pestañas Mods/Registros/Unirse, iconos de plataforma y de contenido, ancho estrecho y estado vacío. |
| `tests/test_ddns.py` | Nombre para entrar: validación de nombres y token, resolución, comprobación y actualización en DuckDNS, migración del modelo y auto-actualización al arrancar. |
| `tests/test_aspecto.py` | Descripción con colores: códigos `§`/`&`, escapes de `server.properties`, límites de Minecraft, tramos con estilo e icono de 64×64 (PNG, tamaño y enlaces simbólicos). |
| `tests/test_seguridad.py` | Endurecimiento: rutas que se salen de la carpeta, enlaces simbólicos, redirecciones de descarga, secretos en el registro y límites de las copias. |

### Mods, registros y mods que faltan

- El manifiesto `.serviscraft-mods.json` (dentro de `data/`) anota los ficheros
  añadidos desde Serviscraft. En un servidor con modpack, un fichero que no está en
  el manifiesto se muestra como **del modpack**; en cualquier otro servidor todo es
  **personalizado**. Si el manifiesto se pierde, lo único que cambia es esa
  etiqueta informativa.
- Desactivar un mod **nunca borra**: se renombra a `.jar.desactivado`.
- Los registros se leen siempre por el **final** del fichero (2 MiB como mucho) y
  la ruta se valida contra la carpeta del servidor (`ensure_within`).
- `missing_mods.parse_missing_mods()` entiende el bloque de dependencias de Fabric
  y Forge (`Missing or unsupported mandatory dependencies` + `Mod ID:`), los
  enlaces de Modrinth en líneas de error y las frases de descarga fallida. Cualquier
  patrón nuevo necesita una prueba con un registro real.

### Reglas para las pruebas de interfaz

- Las pruebas de interfaz se ejecutan en `offscreen` y **no** deben abrir diálogos
  modales: se sustituyen `show_error`, `show_info` y `confirm`.
- Para saber si un widget «se vería», se usa `isHidden()` en lugar de
  `isVisible()`: cuando la página de contenido está oculta (por ejemplo, sin
  servidores) `isVisible()` siempre da `False` y no distingue nada.
- Cualquier `QLabel` nuevo pasa por `test_ninguna_etiqueta_normal_se_recorta`
  (que mide anchos) y por `test_el_texto_ajustado_cabe_en_su_altura` (que mide
  altos a 480, 560, 700, 900 y 1280 px de ancho). Si necesita recortarse, debe ser
  un `ElidedLabel`; si el texto puede ocupar varias líneas, un `hint_label` o un
  `WrappingLabel`.
- La barra de pestañas lleva **nueve** pestañas: se navega con las flechas de la
  propia barra (`setElideMode(ElideNone)` + `setUsesScrollButtons(True)`) en vez de
  recortar los títulos. Para localizar una pestaña en las pruebas, usa
  `_indice_pestana(ventana, "Nombre")`, nunca un índice fijo.
- Cada panel vive dentro de una `PaginaDesplazable` (`QScrollArea` que fija el
  ancho al de la ventana y el alto al mínimo del panel, o al de la ventana si hay
  sitio). Sin ella, en una ventana baja Qt comprime el panel por debajo de su
  mínimo y una `FlowRow` se dibuja encima del texto siguiente. Para obtener el
  panel de una pestaña usa `ventana._panel_de(ventana.tabs.widget(i))`, no
  `tabs.widget(i)` directamente.
- Las tareas de fondo se apagan con `TaskRunner.shutdown()` al cerrar la ventana.
  Las señales se emiten con `anunciar(...)` y las conexiones guardan una
  **referencia débil** a la tarea: así una tarea que termina tarde no avisa a un
  objeto ya destruido ("Signal source has been deleted").

## Flujo de trabajo

1. Crea una rama para el cambio.
2. Escribe primero la prueba que falla (TDD).
3. Implementa lo mínimo para pasarla.
4. `make test` y `make lint` en verde.
5. Verifica manualmente la parte visible con `make run`.
6. Si el cambio afecta al empaquetado, ejecuta `make packages` y comprueba que
   los tres artefactos se generan.

## Empaquetado

```
packaging/
├── serviscraft.desktop        # entrada de menú (fuente de verdad)
├── build-rpm.sh               # construye dist/*.rpm
├── build-deb.sh               # construye dist/*.deb (con ar + tar)
├── build-appimage.sh          # construye dist/*.AppImage
├── rpm/serviscraft.spec       # especificación RPM
└── deb/{control.in,postinst}  # plantilla de control y script de instalación
```

```bash
make rpm deb appimage     # o: make packages
```

### Detalles relevantes

- **RPM**: `BuildArch: noarch`. Los `.pyc` los genera Fedora automáticamente al
  final de `%install`. Depende de `python3-pyside6` y `podman`.
- **DEB**: se construye con `ar` + `tar` porque `dpkg-deb` puede no estar
  instalado; el resultado es un `.deb` estándar (`Architecture: all`). Instala
  en `/usr/lib/python3/dist-packages`.
- **AppImage**: empaqueta su propio Python (*python-build-standalone*) y PySide6
  (rueda *manylinux* autocontenida). Podman queda como dependencia externa.
- **Rutas con espacios**: `rpmbuild` no soporta rutas con espacios, así que todo
  el trabajo intermedio se hace en `~/.cache/serviscraft/build` (configurable con
  `SERVISCRAFT_BUILD_DIR`). Los artefactos finales van a `dist/`.

## Convenciones de código

- Python 3.10+; se usan anotaciones y `from __future__ import annotations`.
- Longitud de línea 110 (configurado en `pyproject.toml`).
- `snake_case` para funciones, `PascalCase` para clases.
- Las excepciones propias heredan de `ServiscraftError`.
- La interfaz nunca llama a `podman` directamente: siempre por `ServerManager`.
- Cualquier operación destructiva pide confirmación y se prueba.
- Las copias de seguridad llevan siempre un **origen** (`core/backup.py`:
  `al-detener`, `programada`, `manual`, `automatica`, `importada`). La limpieza
  automática solo toca `ORIGENES_AUTOMATICOS` (`al-detener` + `programada`): una
  copia manual o de seguridad previa nunca se borra sola. Dos copias del mismo
  servidor se hacen **de una en una** (cerrojo por servidor en
  `BackupManager.create_backup`), porque la copia programada y una manual pueden
  coincidir.
- Los comandos de consola que nacen de un dato del usuario (nombres de jugador)
  no se componen con texto libre: hay una lista cerrada de acciones en
  `core/players.py` y el nombre se valida antes de construir el comando.
- Las etiquetas que muestran nombres de servidor (título de la cabecera, tarjeta
  lateral, resumen de la consola) usan `ElidedLabel`: recortan el texto con `…`
  y guardan el nombre completo en el *tooltip*, en lugar de ensanchar la ventana
  o salirse de su hueco. Cuando no cabe ni una palabra corta no muestran nada (es
  preferible a un resto suelto como «C»). La prueba
  `test_ninguna_etiqueta_normal_se_recorta` vigila que no aparezcan `QLabel`
  normales recortadas.
- Los grupos de botones que iban en una sola fila usan `FlowRow` (`FlowLayout`):
  con sitio se ven igual que siempre (una línea) y, cuando la ventana se estrecha,
  pasan a la línea siguiente en vez de recortarse. Cualquier barra de botones
  nueva debe envolverse con `FlowRow`. El porqué: los gestores de ventanas con
  mosaico automático (Polonium, etc.) dan a la ventana el ancho del mosaico e
  **ignoran el tamaño mínimo**, así que la interfaz debe funcionar a cualquier
  ancho (probado desde 480 px). Las pruebas `test_las_barras_se_adaptan_a_ventanas_estrechas`
  y `test_las_barras_envuelven_en_varias_filas` lo vigilan.
- Una etiqueta larga **no debe compartir fila con un grupo de botones**: al faltar
  ancho, `QBoxLayout` se lo quita todo a la etiqueta antes que encoger los botones
  (llegaba a dejarla en 0 px y vacía). Por eso el resumen de la consola tiene su
  propia línea; la prueba `test_la_etiqueta_de_estado_nunca_se_queda_sin_sitio` lo
  vigila.
- Por debajo de 640 px de ancho la lista de servidores se oculta sola y se
  recupera con el botón «Servidores» o `Ctrl+B` (`MainWindow._ANCHO_ESTRECHO`).
- Las etiquetas con texto ajustado que conviven con otros widgets en un
  `QVBoxLayout` se crean con `hint_label`/`WrappingLabel`, **no** con
  `QLabel(..., setWordWrap(True))` suelto. Motivo: Qt pide a una etiqueta
  ajustada su alto una sola vez, con el ancho de su `sizeHint` (el de una línea
  larguísima), así que en una ventana estrecha el texto necesita más líneas de
  las reservadas y se dibuja centrado: se recortaba por arriba y se solapaba con
  lo de abajo. `WrappingLabel` reserva el alto que pide su ancho real (lo mide
  con la fuente que se pinta, porque `QLabel.heightForWidth` no es de fiar con
  la fuente del estilo). Las pruebas `test_el_texto_ajustado_cabe_en_su_altura`
  y `test_las_pestanas_altas_se_desplazan_sin_comprimir_los_paneles` lo vigilan.
- Las pestañas con contenido usan los componentes de `ui/common.py` en vez de
  `QGroupBox` y texto de ayuda permanente:
  - `SectionCard` — recuadro con icono, título recortable y botón **?**;
  - `HelpButton`/`HelpDialog` — la explicación, a un clic (`help_text` admite
    HTML sencillo);
  - `Chip` — dato resumido con icono y tono (`ok`/`warn`/`bad`/`info`);
  - `icon_pixmap()` — icono del tema del escritorio (puede no existir: en ese
    caso el chip se queda solo con el texto).

  Los iconos propios se dibujan en `ui/mc_icons.py` (`lru_cache`), porque
  `QIcon.fromTheme` devuelve iconos vacíos en muchos escritorios y en offscreen.
  Ahí están, entre otros, `icono_jugador`, `icono_mochila`, `icono_consola`,
  `icono_mundo`, `icono_escudo` y `punto_estado` (el círculo de estado).
- Los diálogos que leen datos del servidor (inventario) no bloquean la ventana:
  la consulta va por `TaskRunner` y la ventana se reutiliza (`set_inventory`) en
  vez de abrir una nueva en cada refresco.
- La cabecera dibuja CPU y memoria con `ui/common.py:MinecraftBar`, una
  `QProgressBar` que se pinta a mano (fondo oscuro, degradado verde y marcas cada
  seis píxeles) para parecerse a la barra de experiencia del juego. Podman mide
  la CPU con el 100 % por núcleo: `manager.host_cpu_count()` y
  `normalize_cpu_percent()` la pasan a porcentaje del equipo antes de llegar a la
  interfaz (200 % en un equipo de 8 núcleos se muestra como 25 %), y la ventana
  vuelve a acotar a 100 por si llegara una cifra sin normalizar. La memoria se
  compara siempre con `spec.memory_mb`, no con el límite que informe Podman (que
  suele ser el del equipo entero).
- Las listas de jugadores se pueden tocar con el servidor apagado. En marcha se
  usa RCON (el cambio se aplica al momento); detenido se escriben
  `whitelist.json`, `ops.json` y `banned-players.json` con
  `core/players.py:apply_offline_action`, calculando el UUID sin cuenta premium
  igual que Java (`offline_uuid`, MD5 de `OfflinePlayer:<nombre>`). Expulsar
  sigue necesitando la consola. Así la pestaña **Jugadores** y la ventana
  **Gestionar listas…** nunca mienten sobre lo que se puede hacer.
- Las texturas de objetos y las skins (`core/textures.py`) se descargan de dos
  servidores fijos por **https** (`raw.githubusercontent.com` y `mc-heads.net`),
  con tiempo de espera corto, tamaño máximo, redirecciones limitadas a la lista
  blanca y validación de la cabecera PNG (16×16/32×32 para objetos, 64×64 o
  64×32 para skins). Se guardan en `~/.cache/serviscraft/texturas` y sin conexión
  se usan los iconos dibujados de `mc_icons.item_icon` y el jugador genérico de
  `skin_view`. `SERVISCRAFT_OFFLINE=1` desactiva toda descarga (lo usan las
  pruebas).
- Al importar un servidor no se copia a ciegas: `core/import_server.py` rechaza
  rutas absolutas y `..`, no sigue enlaces simbólicos (ni de la carpeta ni del
  `.zip`), limita ficheros y tamaño, y comprueba que no haya varios servidores
  dentro de la carpeta elegida. `ServerManager.import_server` crea primero la
  carpeta, copia, ajusta los puertos internos y RCON, y si algo falla **borra
  solo lo que acaba de crear**. El contenedor no se crea hasta el primer inicio.

### Compatibilidad de datos (nunca romper servidores antiguos)

Actualizar Serviscraft **no puede costarle a nadie su mundo**. Las reglas son:

- `meta.json` de cada servidor lleva `meta_version` (`core/store.py`,
  `META_VERSION`). Al leerlo se aplica `migrate_meta()`, que es **idempotente**: se
  puede llamar tantas veces como haga falta. En cada paso se sube la versión y se
  rellena lo que falte, pero **nunca se valida ni se descarta** lo que ya había.
- Las claves que una versión **no conoce** se guardan tal cual en
  `ServerSpec._extra` (en `KNOWN_KEYS` está la lista de las conocidas) y se
  vuelven a escribir al guardar. Así una versión más nueva no borra datos de una
  más vieja, y al revés.
- El manifiesto de mods (`.serviscraft-mods.json`) creció para recordar el
  proyecto del que salió cada fichero (`{"proyectos": {"x.jar": {...}}}`), pero el
  formato antiguo (`{"personalizados": [...]}`) sigue leyéndose: si no hay datos
  de proyecto, la lista funciona igual y solo se pierde el icono.
- Las pruebas `tests/test_migraciones.py` y `tests/test_bedrock.py` cubren el
  formato antiguo, el roto y el nuevo.

## Añadir una función nueva

1. Decide a qué capa pertenece: si toca Podman/ficheros/copias, va en `core`.
2. Añade o amplía el modelo en `core/models.py` si hace falta persistir algo.
3. Expón la operación desde `core/manager.py`.
4. Escríbele pruebas en `tests/`.
5. Añade la interfaz en el panel correspondiente (`ui/`), usando `TaskRunner`
   para cualquier operación que pueda tardar.
6. Actualiza `docs/uso.md` si afecta al usuario.
