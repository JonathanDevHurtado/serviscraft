# Guía de uso

Las pestañas con más contenido llevan un botón **?** en la esquina superior
derecha del recuadro: al pulsarlo se explica, sin salir de la ventana, para qué
sirve cada cosa y qué hay que hacer. Los mismos recuadros llevan un **icono** que
los identifica (el bloque de Java, la mochila del jugador, la consola, el mundo…).

## 1. Crear un servidor

Puedes **traer un servidor que ya tenías** (de este equipo, de otro o exportado
de Aternos) con **Importar servidor…**, o empezar de cero con **Nuevo servidor…**
(menú *Archivo* o `Ctrl+N`).

### Importar un servidor ya existente

El botón **Importar servidor** (barra lateral, barra de herramientas o
`Ctrl+Shift+I`) abre una ventana donde eliges la **carpeta del servidor** o el
**`.zip` que da Aternos** al descargarlo. Antes de copiar nada, Serviscraft
reconoce y te enseña:

| Dato | De dónde sale |
| --- | --- |
| Tipo y versión | `version_history.json`, `logs/latest.log` o el nombre del `.jar`. Si no se puede saber, se propone `latest` y puedes cambiarlo. |
| Mundo | `server.properties` (`level-name`) y los `level.dat` de las carpetas. |
| Plugins y mods | Los `.jar` de `plugins/` y `mods/`. |
| Puerto | `server-port` del servidor original. Se conserva si está libre. |
| Origen | Aternos, exaroton, Minehut, PloudOS, FalixNodes… si aparece su marca en la carpeta, la configuración o los registros. |
| Imagen y descripción | `server-icon.png` y el `motd`. |

Después rellenas el nombre, la memoria y el Java (los datos se proponen solos) y
pulsas **Importar servidor**. La ventana copia el mundo, los plugins o mods y la
configuración **sin tocar el original**, con barra de progreso y botón para
cancelar. No se copian los registros ni las librerías (se regeneran solas), y se
respetan las reglas de seguridad: no se siguen enlaces simbólicos y ninguna ruta
del `.zip` puede salirse de la carpeta de destino.

El contenedor **no** se crea durante la importación: se monta la primera vez que
pulsas **Iniciar**, así que puedes importar sin conexión. Al terminar se ajustan
solo los puertos internos y la contraseña de RCON (lo necesita la consola), y se
acepta el EULA que el servidor ya tenía aceptado. Si el servidor original tenía
la lista blanca activada, se conserva.

### Crear uno nuevo

Rellena el formulario:

| Campo | Qué es |
| --- | --- |
| Nombre | Nombre visible. Genera automáticamente el identificador interno. |
| Tipo | **Paper** (por defecto, admite plugins), **Vanilla**, **Fabric** o **Forge**. |
| Versión | Versión de Minecraft. Se elige **de la lista** (no se escribe a mano); `latest` deja que la imagen use la última estable. El botón **Actualizar lista…** consulta las últimas publicadas por Mojang. |
| Java | Etiqueta de Java del contenedor (`java25`, `java21`, `java17`, `java8`). Serviscraft elige la recomendada al cambiar la versión; puedes cambiarla a mano. |
| Memoria | RAM asignada al servidor (heap `-Xmx`). |
| Puerto | Puerto del juego. Serviscraft propone el primero libre. |
| Acceso desde la red | Si lo activas, el puerto se publica en la red local. |
| Jugadores de Bedrock | Solo en Paper: instala Geyser y Floodgate y publica el puerto UDP para móvil, tablet y consola (ver [Unirse](#11-unirse)). |
| Notas | Recordatorios opcionales. |

Si prefieres un **modpack** (un paquete con sus mods, configuraciones y su propio
cargador), marca la casilla *Usar un modpack de Modrinth*: el tipo y la versión
los fija el propio pack. Lo cuenta el apartado [Modpacks](#8-modpacks).

Al aceptar, Serviscraft:

1. Descarga la imagen `docker.io/itzg/minecraft-server` si no la tiene (puede
   tardar la primera vez; se muestra el progreso).
2. Crea la carpeta de datos y un `server.properties` inicial.
3. **Crea el contenedor pero no lo inicia.**

Una etiqueta de estado te indica siempre la situación: *Sin iniciar*, *En marcha*, *Detenido*, *Sin crear*.

## 2. Ciclo de vida

- **Iniciar** — arranca el contenedor. Serviscraft espera a que el servidor
  escriba `Done (…)` en el registro antes de dar el arranque por bueno.
- **Detener** — envía `stop` por RCON para que Minecraft guarde el mundo y se
  apague limpiamente. Pide confirmación. Si la casilla *Copiar cada servidor
  automáticamente al detenerlo* está activa (lo está por defecto), al terminar la
  parada se crea una **copia de seguridad automática** del servidor; al acabar
  verás en la barra de estado el nombre del archivo y la carpeta donde quedó.
- **Reiniciar** — detiene el servidor (guardando el mundo y con su copia
  automática) y lo vuelve a arrancar. Pide confirmación.
- **Eliminar** — abre un diálogo en el que puedes:
  - crear una **copia de seguridad** antes de borrar (activado por defecto);
  - decidir si se borran también los datos del disco (activado por defecto);
  - y, si vas a borrar los datos, **escribir el nombre exacto** del servidor.

  Si vas a crear esa copia y el servidor está en marcha, se crea **una sola**
  copia: Serviscraft no duplica la de «antes de eliminar» con la de la parada.

> **Los servidores nunca arrancan solos.** Al abrir la aplicación, si detecta
> contenedores de Serviscraft que quedaron funcionando de una sesión anterior,
> te pregunta si quieres detenerlos o dejarlos funcionando. Las copias automáticas
> también funcionan al cerrar la aplicación: si sales con servidores en marcha y
> eliges *Detenerlos y salir*, cada uno se apaga y se copia antes de cerrar.

## 3. Consola

La pestaña **Consola** sigue en directo la salida del contenedor
(`podman logs --follow`) y colorea las líneas por tipo. Un **punto de color** al
lado del estado dice de un vistazo si el servidor está encendido (verde) o
parado (gris), y una **leyenda** recuerda qué significa cada color:

| Color | Qué es |
| --- | --- |
| verde | el arranque terminó (*Done*) y los comandos que escribes |
| azul | las respuestas de Serviscraft |
| ámbar | avisos (*WARN*) |
| rojo | errores (*ERROR*, *FATAL*, excepciones) |
| lila | el chat de los jugadores |
| gris | el resto de mensajes normales (*INFO*) |

- El campo inferior envía comandos al servidor **por RCON**, usando la dirección
  `127.0.0.1` y la contraseña generada al crear el servidor.
- Los botones rápidos incluyen `list`, `save-all` y `stop`.
- **Solo problemas** esconde las líneas normales y deja avisos y errores (y lo
  que escribes tú). El estado dice cuántas líneas se están ocultando.
- **Copiar todo** lleva a la memoria lo que se ve (para pegarlo en un mensaje
  cuando pidas ayuda) y **Guardar registro** lo escribe en un fichero de texto.
- Las flechas **arriba/abajo** del teclado repiten comandos anteriores.
- Si el servidor está detenido, la consola muestra las últimas líneas y el envío
  de comandos queda deshabilitado.

El seguimiento en vivo solo se activa cuando la ventana está visible y la
pestaña *Consola* está en primer plano, para no gastar recursos en segundo plano.

## 4. Propiedades (`server.properties`)

La pestaña **Propiedades** ofrece un editor con las claves más habituales
(MOTD, dificultad, modo de juego, jugadores máximos, `pvp`, `online-mode`…) y un
editor de texto para el archivo completo.

Las claves que **gestiona Serviscraft** (puerto, RCON, EULA, memoria…) aparecen
bloqueadas: no se pueden quitar ni editar desde la interfaz, para no romper la
configuración del contenedor.

## 5. Archivos, plugins, mods y mundos

La pestaña **Archivos** adapta sus vistas al tipo de servidor:

- **Vanilla** no ofrece *Plugins* ni *Mods*.
- **Paper** ofrece *Plugins*.
- **Fabric**, **Forge** y los **modpacks** ofrecen *Mods*.

Puedes:

- **buscar e instalar** plugins o mods desde **Modrinth** con el botón
  **Buscar e instalar…**: escribes el nombre, eliges un resultado y Serviscraft
  descarga la versión más reciente compatible con tu versión de Minecraft y tu
  tipo de servidor (Paper, Fabric o Forge). La descarga se comprueba con su suma
  SHA-512 antes de instalarse;
- actualizar un plugin o mod volviendo a instalarlo (se sustituye el `.jar`;
  su configuración se conserva);
- subir archivos `.jar` desde tu equipo (importar);
- descargar un archivo por URL (se valida la dirección);
- crear carpetas, navegar y mostrar archivos ocultos;
- en la vista **Mundos**: crear una copia de un mundo, activar otro mundo
  (reescribe `level-name` en `server.properties`) o **eliminar** un mundo
  (nunca el que está activo, y siempre con confirmación).

Los cambios en plugins, mods y mundos se aplican **al reiniciar** el servidor.
Si un mod indica dependencias obligatorias, instálalas también desde el mismo
catálogo antes de arrancar.

Esta pestaña sirve para *ver y mover ficheros*. Para lo del día a día con el
contenido (activar y desactivar sin borrar, saber de dónde viene cada mod y
recuperar los que falten) está la pestaña **Mods**, en la sección 9.

## 6. Copias de seguridad

En la pestaña **Copias** puedes:

- **Crear** una copia con etiqueta opcional (p. ej. `antes-de-instalar-mods`).
  Si el servidor está en marcha, se avisa de que el mundo puede quedar a medias.
- **Restaurar** una copia. La restauración es transaccional: si falla, se vuelve
  al estado anterior. Está deshabilitada mientras el servidor funciona.
- **Renombrar** una copia: cambia su etiqueta (hasta 60 caracteres) sin tocar
  el archivo. Sirve para saber de un vistazo qué hay dentro; la restauración y
  la compatibilidad siguen igual.
- **Exportar / Importar** copias para llevarlas a otro equipo.
- **Limpiar antiguas**, conservando las N más recientes.
- **Abrir la carpeta** o **copiar su ruta** con un botón: la carpeta exacta de
  cada servidor aparece siempre escrita encima de la tabla.

### Dónde vive cada copia

Cada servidor guarda **sus propias copias dentro de su carpeta**:

```
~/.local/share/serviscraft/servers/<id-del-servidor>/backups/
```

Encima de la tabla, la pestaña **Copias** muestra esa ruta completa junto a los
botones **Abrir carpeta** y **Copiar ruta**. También puedes llegar desde el menú
*Servidor → Abrir carpeta de copias* o desde la pestaña **Detalles**.

Una copia es un archivo `backup-AAAAAMMDD-HHMMSS-origen.tar.gz` que contiene la
carpeta `data` del servidor (mundos, `server.properties`, plugins, mods,
configuraciones…). El contenedor no se copia: se vuelve a crear solo con
arrancar. Si haces dos copias en el mismo segundo, la segunda no pisa a la
primera: se le añade un número al final.

Cada copia guarda **de dónde viene** (columna *Origen*):

| Origen | Cuándo se crea |
| --- | --- |
| **al detener** | Automáticamente al apagar el servidor (si está activado). |
| **programada** | La copia periódica de los servidores en marcha. |
| **manual** | Cuando pulsas **Crear copia ahora** o **Copiar todos los servidores ahora**. |
| **automática** | Copia de seguridad previa a restaurar otra o a eliminar el servidor. |
| **importada** | Una copia traída de otro equipo. |

### Copia automática al detener

Activada por defecto en *Preferencias → Copias de seguridad*. Se hace **después**
de apagar el servidor, cuando Minecraft ya ha guardado el mundo. Si la copia
fallara (por ejemplo, sin espacio en disco), el servidor se apaga igual: la barra
de estado te avisa de que no se pudo copiar.

### Copia programada

En *Preferencias → Copias de seguridad* puedes pedir una copia automática cada
cierto número de minutos (por defecto **desactivada**, `0`). Mientras haya
servidores en marcha, se copian solos con esa frecuencia. No bloquea la
aplicación: la copia ocurre en segundo plano y verás el aviso en la barra de
estado.

El menú *Servidor → Copiar todos los servidores ahora* hace lo mismo cuando tú
quieres.

### Cuántas copias se conservan

En las mismas preferencias, **Conservar copias automáticas** indica cuántas
copias automáticas se guardan por servidor (por defecto `8`; `0` = conservar
todas). El número cuenta **juntas** las copias *al detener* y las *programadas*:
las más antiguas que sobran se borran al crear una nueva. Así, si programas una
copia cada hora, las copias de las paradas más antiguas irán rotando.

- Solo se limpian las copias **al detener** y **programadas**.
- Las copias **manuales**, las de **antes de restaurar/eliminar** y las
  **importadas** no se borran nunca solas: si quieres deshacerte de ellas, usa
  **Limpiar antiguas** o **Eliminar copia**.

## 7. Jugadores

La pestaña **Jugadores** reúne lo que sabes de cada jugador del servidor. Arriba,
unas **fichas de resumen** dicen de un vistazo cuántos hay conectados, cuántos
están en la lista blanca, cuántos son operadores y cuántos están bloqueados (la
ficha de bloqueados solo aparece si hay alguno).

| Columna | Qué significa |
| --- | --- |
| **Jugador** | Nombre de la cuenta, con su cara. |
| **Conectado** | Está jugando ahora mismo (solo se puede saber con el servidor en marcha). |
| **Lista blanca** | Está en la lista blanca del servidor. |
| **Operador** | Tiene permisos de administrador (OP). |
| **Bloqueado** | Está expulsado y no puede volver a entrar. |

Los «Sí» van en verde cuando es algo bueno (conectado, operador, en la lista) y en
rojo cuando es un bloqueo, para que se distinga sin leer.

Con el servidor **detenido** la pestaña sigue siendo útil: la lista blanca, los
operadores y los bloqueados se leen de los archivos del servidor
(`whitelist.json`, `ops.json` y `banned-players.json`), así que puedes consultarlos
sin arrancar nada. Quién está conectado, en cambio, solo se puede preguntar al
servidor en marcha.

Los **jugadores de Bedrock** aparecen con un punto delante del nombre
(`.Steve`): lo pone Floodgate para distinguirlos. El punto forma parte del
nombre que entiende el servidor, así que se invitan, se expulsan y se bloquean
igual que los demás. La ficha superior los cuenta y, al elegir uno, la zona de
acciones avisa de que es un jugador de Bedrock.

### Gestionar las listas

El botón **Gestionar listas…** abre una sola ventana con las **tres listas** del
servidor, cada una en su pestaña y con su contador:

- **Lista blanca**: los invitados. La casilla *Exigir lista blanca* escribe
  `white-list` en `server.properties`; con ella activada solo entra quien esté
  en la lista.
- **Bloqueados**: la lista negra. Un bloqueado no entra aunque esté en la lista
  blanca, hasta que lo perdones.
- **Operadores**: los administradores, con acceso a los comandos de gestión.

Escribe el nombre y pulsa **Añadir** (o **Bloquear**), o elige a alguien de la
lista y pulsa **Quitar de la lista**, **Perdonar** o **Quitar OP**. Doble clic
sobre un nombre también lo quita (con confirmación en los bloqueados).

Funciona **con el servidor encendido y apagado**:

- **Encendido**: la orden se envía a su consola (RCON) y el cambio se aplica al
  momento, también a quien esté jugando.
- **Apagado**: se escriben las mismas listas en disco (`whitelist.json`,
  `ops.json`, `banned-players.json`). Los cambios valen desde el próximo arranque,
  así que puedes preparar la lista blanca antes de encender.

La ventana indica en todo momento si el servidor está detenido y recuerda que los
cambios se guardan para el próximo arranque. Los UUID de los jugadores sin cuenta
premium se calculan igual que lo hace Java, para que las listas sean válidas.

### Atajos por jugador

Escribe el nombre en el campo (o selecciona una fila de la tabla, o haz doble clic)
y pulsa **Dar OP**, **Quitar OP**, **Añadir a la lista**, **Quitar de la lista**,
**Expulsar**, **Bloquear** o **Perdonar**.

- Cada botón explica lo que hace al pasar el ratón por encima.
- **Expulsar** (y el inventario) necesitan el servidor en marcha, porque la orden
  va a su consola; con el servidor detenido esos botones aparecen desactivados y
  se explica por qué. El resto funciona igual que en **Gestionar listas…**.
- **Bloquear** pide confirmación: el jugador no podrá volver hasta que uses
  **Perdonar**.
- Los nombres se validan antes de enviar nada (letras, números y guion bajo,
  hasta 32 caracteres; los de Bedrock pueden llevar además un punto delante),
  de modo que nunca se cuela un comando por accidente.
- El panel **se refresca solo** después de cada acción para que veas el efecto, y
  puedes actualizarlo cuando quieras con **Refrescar**.

### Ver el inventario

Con el servidor en marcha, elige a un jugador conectado y pulsa **Ver inventario**
(o haz doble clic en su fila). Se abre una ventana con la **mochila tal y como la
ve el jugador**: las tres filas del inventario, la armadura y la mano secundaria,
y la barra rápida (las teclas 1-9) abajo.

- Cada objeto se ve con su **textura**. La primera vez se descargan de un
  espejo público de los recursos del juego y se guardan en tu equipo (son de uno
  o dos KB); sin conexión, o mientras llegan, se dibuja un **icono propio** con
  la forma y el color del material (espada de diamante, bloque de hierba,
  manzana…).
- A la derecha se ve la **skin del jugador**, con su cara y su cuerpo. También se
  descarga una sola vez; si el servidor no tiene skins, se muestra un jugador
  genérico.
- Los **números amarillos** dicen cuántos objetos hay en ese hueco. Al pasar el
  ratón por encima se ve el nombre completo y el identificador del objeto.
- Arriba, unas fichas resumen su **vida**, su **comida**, su **nivel** y cuántos
  objetos lleva en total.
- **Actualizar** vuelve a preguntar al servidor lo que lleva en ese momento: es
  la forma de ver cómo cambia mientras juega.
- Serviscraft pregunta estos datos con `data get entity` por la consola del
  servidor: **no modifica el inventario ni el mundo**, y no hay que instalar nada.
- Si el jugador **no está conectado** (o el inventario es tan grande que la
  consola lo devuelve recortado), se avisa en lugar de enseñar datos a medias.

## 8. Modpacks

Un **modpack** es un paquete que trae de una vez los mods, sus configuraciones y
el cargador (Fabric, Forge o Quilt) que necesitan. Serviscraft los instala desde
**Modrinth** con la misma imagen de siempre:

1. En **Nuevo servidor…**, marca **Usar un modpack de Modrinth**.
2. Pulsa **Elegir modpack…**, escribe un nombre (por ejemplo `Cobblemon` o
   `Better MC`) y pulsa **Buscar**.
3. Elige el pack en la tabla. De cada resultado se muestra:

   | Columna | Qué significa |
   | --- | --- |
   | **Modpack** | Nombre del paquete. |
   | **Cargador** | Fabric, Forge, Quilt o NeoForge. |
   | **Minecraft** | Versiones de Minecraft que anuncia el pack. |
   | **Descargas** | Cuántas veces se ha descargado (señal de que funciona). |
   | **Actualizado** | Fecha de su última publicación. |
   | **Descripción** | Resumen en una línea (completo al pasar el ratón). |

   Encima de la tabla tienes **filtros**: por **cargador**, por **lado** (sirve en
   servidor o es solo de cliente) y **«Solo instalables»** (oculta lo que pide
   NeoForge). Se aplican al momento y el contador te dice cuántos quedan a la
   vista. **Ver en Modrinth** abre la página del pack en el navegador.
4. Abajo aparecen sus **versiones**. Se preselecciona la estable más reciente que
   Serviscraft pueda instalar, y verás para cada una el cargador y la versión de
   Minecraft que trae.
5. Pulsa **Usar este modpack** y crea el servidor como cualquier otro.

Detalles que conviene saber:

- **La versión de Minecraft y el tipo de servidor los fija el pack**: no se
  eligen a mano (los verás bloqueados en el formulario).
- La versión de Minecraft **no se escribe nunca a mano**: en todos los
  formularios se elige de la lista de versiones publicadas, con el botón
  **Actualizar lista…** para consultar las últimas de Mojang. Así no se puede
  escribir una versión con una errata.
- Se admiten packs de **Fabric**, **Forge** y **Quilt**. Los que solo existen
  para **NeoForge** todavía no se pueden usar: al elegirlos, el cuadro te avisa y
  desactiva el botón de aceptar. Prueba otra versión del mismo pack.
- La instalación la hace la imagen **en el primer arranque**: descarga el pack
  completo y puede tardar **bastante** (varios minutos) y ocupar unos cientos de
  MB. Mira la pestaña **Consola** para seguir el progreso.
- Al instalar un modpack, la imagen **revisa los mods** de la carpeta `mods` y
  puede quitar los que no pertenezcan al pack. Si tenías mods añadidos a mano,
  haz antes una copia de seguridad desde la pestaña **Copias**.
- Para cambiar de pack o de versión del pack lo más sencillo es crear un servidor
  nuevo, copiar tus mundos y (si quieres) restaurar tu copia de seguridad.

## 9. Mods, plugins y mods que faltan

La pestaña **Mods** es el sitio para cuidar el contenido del servidor. Muestra la
carpeta que corresponda (*Mods* en Fabric, Forge y modpacks; *Plugins* en Paper)
con estas columnas:

| Columna | Qué significa |
| --- | --- |
| **Fichero** | Nombre del fichero y su **icono**, como en Prism Launcher. |
| **Estado** | *activo* o *desactivado*. |
| **Origen** | *del modpack* (lo instala el propio pack) o *personalizado* (lo añadiste tú). |
| **Tamaño** | Cuánto ocupa. |

El icono de cada fila es:

- el **icono del proyecto** de Modrinth, si se instaló desde el catálogo
  (Serviscraft lo recuerda en el servidor y lo guarda en la caché, así que no hay
  que volver a consultar la red);
- si no se conoce el proyecto, el símbolo del tipo de contenido: una **pieza de
  puzle** para mods y un **enchufe** para plugins;
- si el fichero está **desactivado**, se ve apagado y con una raya roja.

El catálogo (**Añadir del catálogo…**) y el de modpacks muestran también el icono
real de cada proyecto en la primera columna, para reconocerlo de un vistazo.
Debajo de los botones, una **leyenda** con el símbolo real del contenido de ese
servidor recuerda qué es cada cosa y que «desactivado» no significa borrado.

### Acciones

- **Activar** o **Desactivar** (o doble clic en la fila): el botón dice lo que va
  a hacer con lo que tengas seleccionado (si no hay nada seleccionado, pone
  *Activar/Desactivar* y actúa sobre la fila elegida). Desactivar un mod **no lo
  borra**, solo le añade la terminación `.desactivado` para que el servidor no lo
  cargue. Vuelve a activarlo cuando quieras.
- **Añadir del catálogo…**: busca en **Modrinth** y descarga la versión compatible
  con tu versión de Minecraft y el cargador del servidor.
- **Añadir .jar local…**: copia un fichero que hayas descargado en tu equipo.
- **Añadir desde URL…**: descarga el `.jar` desde una dirección `http`/`https`
  (se comprueba que sea un JAR o ZIP de verdad).
- **Eliminar**: borra el fichero, con confirmación. Si venía del modpack se te
  avisa de que **volverá a aparecer** en el siguiente arranque.

Con el servidor **en marcha** estos botones se desactivan: detén el servidor, haz
los cambios y vuelve a iniciarlo. Todo lo que toca la pestaña se aplica **al
reiniciar**.

### Mods que faltan

Cuando un modpack no consigue descargar un mod (el proyecto ya no existe, la red
falló, se borró el fichero…), el servidor arranca pero los mods que lo necesitan
se quejan en el registro. La parte de abajo de la pestaña lo resuelve:

1. Pulsa **Analizar el registro**. Serviscraft lee la salida del contenedor y los
   ficheros de `logs` del servidor y saca la lista de mods que faltan (mensajes
   como *Missing or unsupported mandatory dependencies* o *Failed to download*).
2. Cada fila trae el **enlace a Modrinth** de ese mod: **Abrir enlace** (o doble
   clic) lo abre en el navegador, y **Copiar el .jar aquí…** te deja elegir el
   fichero que has descargado.
3. Al copiarlo queda **dentro del servidor** (en su carpeta de mods), la fila se
   pone en **verde** con «ya está en el servidor» y **ya puedes borrar la descarga
   original** de tu carpeta de descargas.
4. Vuelve a arrancar el servidor. Si todo está en verde, no falta nada.

También puedes llegar aquí desde la pestaña **Registros**, con el botón **Buscar
mods que faltan**.

## 10. Registros

La pestaña **Registros** enseña lo que ha escrito el servidor, tanto en marcha
como parado:

- Con el servidor **en marcha** puedes leer la **salida del contenedor**.
- Con el servidor **detenido** puedes abrir los ficheros que Minecraft guarda en
  `logs` (por ejemplo `latest.log`) y los informes de fallo de `crash-reports`.
  El desplegable **Registro** cambia de uno a otro y muestra su tamaño.

Botones útiles:

- **Filtrar líneas**: escribe `error`, `warn`, `mod` o el nombre que busques y la
  vista muestra solo las líneas que lo contienen.
- **Seguir**: vuelve a leer el registro cada dos segundos (útil para ver un
  arranque en directo).
- **Copiar todo**: copia lo que estás viendo al portapapeles.
- **Abrir carpeta de registros**: abre `logs` en el gestor de archivos.
- **Buscar mods que faltan**: salta a la pestaña **Mods** y analiza el registro.

Para no llenar la memoria se lee solo el final del fichero (los últimos 2 MiB), de
sobra para ver un arranque o un fallo.

## 11. Unirse

La pestaña **Unirse** contesta a la pregunta «¿cómo entra la gente?». Está
organizada en cuatro recuadros numerados, cada uno con su botón **?** para
explicar el paso a paso:

1. **1. Entrar desde un PC (Java)** — la dirección que se escribe en Minecraft
   de PC, Mac y Linux, con botón para copiarla.
2. **2. Jugadores de móvil, tablet y consola (Bedrock)** — el puerto y la
   dirección para Bedrock (con Geyser y Floodgate).
3. **3. Amigos de otras ciudades (internet)** — qué hace falta para jugar desde
   otra ciudad o país.
4. **4. Cuentas y seguridad** — licencia de pago o servidor sin licencia, y qué
   implica cada opción.

### Java (PC, Mac y Linux)

Los pasos van numerados en la propia ventana:

1. Abre Minecraft y entra en **Multijugador**.
2. Pulsa **Añadir servidor**.
3. En **Dirección del servidor** escribe la dirección que aparece en la fila
   **Dirección del servidor** (por ejemplo `192.168.1.40:25565`).
4. Ponle el nombre que quieras, pulsa **Hecho** y entra.

Hay dos direcciones más, cada una con su botón **Copiar**:

- **En este mismo equipo**: `localhost:<puerto>`, para probar desde el ordenador
  donde corre Serviscraft.
- **Contenedor**: el nombre del contenedor, el tipo de servidor y la versión.

Si el servidor está limitado a este equipo (no se marcó la red local al crearlo),
la dirección de red aparece como *Desactivada (solo este equipo)*; se cambia en
**Ajustes** del servidor.

### Jugadores de Bedrock (móvil, tablet y consola)

Minecraft Bedrock habla otro protocolo, así que **no pueden entrar por la
dirección de Java**. Serviscraft lo resuelve con dos plugins oficiales:

- **Geyser**: traduce Bedrock a Java. Entra en la carpeta `plugins`.
- **Floodgate**: deja entrar a quien **no tiene cuenta de Java** (solo la de
  Xbox Live, que es la que usa Bedrock).

La dirección y el puerto de Bedrock se muestran **siempre que el servidor sea
Paper**, aunque la casilla esté desmarcada. La razón es que también puedes
instalar Geyser y Floodgate a mano desde la pestaña **Plugins**: en ese caso la
nota lo dice claramente («Solo se puede si usas el plugin») y recuerda que el
puerto UDP tiene que estar abierto.

Para que Serviscraft los instale y abra el puerto por ti, marca **Permitir
jugadores de Bedrock (Geyser)** en esa misma pestaña:

- Solo está disponible en servidores **Paper** (es el único tipo que acepta
  plugins). En los demás la casilla sale desactivada, la dirección aparece como
  *No disponible* y se explica por qué.
- Se descarga el **puerto UDP** (19132 por defecto, o el siguiente libre) y se
  publica aparte del puerto de Java. El mundo, los mods y las copias **no se
  tocan**.
- Hay que hacerlo con el **servidor detenido**: se recrea el contenedor (los
  plugins se descargan en el arranque siguiente).
- En Bedrock se entra por **Jugar → Servidores → Añadir servidor**, con la IP del
  equipo y el puerto UDP que muestra la ventana. Si instalaste los plugins a
  mano, Serviscraft no puede saberlo: la dirección solo funciona con Geyser y
  Floodgate puestos.
- La primera vez que el servidor arranca, Geyser escribe su `config.yml`.
  Serviscraft lo ajusta solo (`auth-type: floodgate`) y **avisa de que hay que
  reiniciar** para que surta efecto.

### Java y Bedrock: la insignia

Al lado del nombre del servidor (y bajo él en la barra lateral) aparecen dos
bloques de Minecraft dibujados:

- **Bloque de césped**: servidor de **Java** (PC, Mac y Linux).
- **Bloque de piedra**: servidor que **también** acepta **Bedrock** (móvil,
  tablet y consola).

La ficha **Detalles** lo dice con palabras: *Java* o *Java y Bedrock*, y en
**Recursos y puertos** explica si están activados y con qué puerto UDP.

### Jugar con gente de fuera de casa

El bloque **Jugar con amigos de otros sitios (internet)** explica lo que hay que
hacer y lo que no hace Serviscraft:

1. Pulsa **Consultar mi IP pública**. Serviscraft pregunta a un servicio de
   internet cuál es tu IP de salida (la única consulta que hace fuera de
   Modrinth y de las descargas de Minecraft) y muestra `tu-ip:puerto` con botón
   para copiarla.
2. En el **router** de casa hay que abrir («Port forwarding» o «NAT») el puerto
   del servidor hacia este equipo: el **TCP** del servidor Java y, si hay
   Bedrock, el **UDP** que indique la ventana (por defecto 19132).
3. Los amigos escriben `tu-ip-pública:25565` (o la IP con el puerto UDP en
   Bedrock) y entran.

Serviscraft **no toca el router ni el cortafuegos**: solo dice qué puerto hay que
abrir y comprueba lo que puede desde el equipo. Si tu operador no deja abrir
puertos (o no tienes acceso al router), la alternativa es una **red privada
virtual** (Tailscale, ZeroTier) o un **túnel** como playit.gg: los amigos
instalan el programa, se unen a tu red y entran con la dirección que les dé. En
todos los casos, cuanto menos se abra, mejor: ver
[`seguridad.md`](seguridad.md).

### Un nombre en vez de una IP (DuckDNS)

Escribir `83.54.12.7:25565` es fácil de equivocar y además enseña tu IP a
cualquiera. En el recuadro **3. Amigos de otras ciudades** hay una fila
**Nombre para entrar** con el botón **Poner un nombre**:

1. Entra en [duckdns.org](https://www.duckdns.org) con tu cuenta de Google o
   GitHub y crea un nombre libre (por ejemplo `reinotrebol`). Es gratis.
2. Copia el **token** que te da la web (el de tu cuenta, no el del nombre).
3. Pulsa **Poner un nombre**, escribe el nombre y pega el token, y guarda.

A partir de ahí tus amigos escriben `reinotrebol.duckdns.org:25565`: un nombre
que se recuerda, no revela dónde vives y sigue valiendo aunque tu operador te
cambie la IP.

- **Mantener al día** (activado por defecto) hace que Serviscraft avise a
  DuckDNS de tu IP cada vez que arranca un servidor, para que el nombre apunte
  siempre al sitio correcto. También hay un botón **Comprobar ahora** que dice si
  el nombre ya resuelve a tu IP.
- El token se guarda en tu equipo, con permisos de solo tu usuario, y **nunca**
  aparece en el registro ni en las capturas de la consola que puedas compartir.
- Un nombre **no abre el puerto**: el router tiene que reenviar el puerto del
  juego igualmente (lo explica el recuadro 3). Y para entrar sin escribir el
  puerto haría falta un dominio propio con un registro SRV; DuckDNS no lo
  permite. Para esas redes (CGNAT, sin acceso al router) las alternativas son
  playit.gg o una red privada como Tailscale.

El nombre es **opcional**: sin él, la pestaña sigue enseñando tu IP pública y
todo funciona igual. También se puede quitar más adelante desde el mismo botón.

### Cuentas: premium o sin licencia

El interruptor **Exigir cuentas premium (online-mode)** controla si el servidor
comprueba las cuentas con Mojang:

- **Activado** (recomendado): solo entran cuentas compradas y verificadas.
- **Desactivado**: también entran clientes sin licencia.

Al desactivarlo se avisa de lo que implica: **cualquiera puede entrar usando el
nombre de otro jugador**, incluso el de un operador, así que solo tiene sentido en
un servidor privado de tu red de confianza. Serviscraft pide confirmación y deja
el aviso visible mientras esté en ese modo. El cambio se guarda en
`server.properties` y **se aplica al reiniciar** el servidor.

### La imagen y la descripción que ven tus amigos

En la lista de servidores de Minecraft cada servidor se ve con un **icono** de
64×64 y dos líneas de **descripción** (el *MOTD*). Son lo que distingue tu
servidor de los demás antes de entrar, y se cambian desde la propia aplicación:

- botón **Aspecto** en la barra de herramientas, menú *Servidor → Aspecto del
  servidor…*, el botón **Cambiar imagen y descripción…** de la pestaña
  **Detalles**, o pulsando el icono de la cabecera;
- en la pestaña **Detalles** hay una **vista previa** de la entrada tal y como la
  pinta el juego, para verla antes de entrar.

**La imagen**

- **Elegir una imagen…** acepta cualquier imagen de tu equipo: Serviscraft la
  encaja sola en 64×64 (si no es cuadrada la centra, y si ya mide 64×64 la deja
  intacta para no estropear el *pixel art*).
- **O usa uno de estos bloques**: ocho iconos ya dibujados por la aplicación
  (césped, piedra, modpack, mod, plugin, mundo, jugador y escudo), sin descargar
  nada.
- **Quitar imagen** vuelve al icono genérico del juego.

**La descripción**

- Dos líneas como máximo y 45 caracteres útiles por línea (los códigos de color
  no cuentan). El contador avisa en rojo y **Guardar** se desactiva si te pasas:
  lo que sobra no se vería, porque Minecraft lo corta.
- La paleta tiene los **16 colores** de Minecraft y los estilos **negrita,
  cursiva, subrayado, tachado, oculto y normal**. El color se escribe delante del
  texto y afecta a todo lo que venga después; si seleccionas un trozo y pulsas un
  color, solo se colorea ese trozo.
- El texto se guarda en `server.properties` con los códigos que entiende
  Minecraft (`\u00a7a` para el verde), así que se puede seguir editando desde la
  pestaña **Propiedades** y se conserva si el servidor reescribe el fichero.

**Importante:** Minecraft lee la imagen y la descripción **al arrancar**. El
cambio se ve al **reiniciar** el servidor; si está en marcha, Serviscraft avisa
de que el servidor puede reescribir su fichero de propiedades al detenerse. Con
el servidor detenido se guarda sin más. La imagen queda en
`data/server-icon.png` (ver [la sección 16](#16-dónde-están-los-archivos-del-servidor)).

## 12. Estadísticas

La cabecera muestra, para el servidor seleccionado y mientras está en ejecución,
dos barras con el aspecto de la **barra de experiencia de Minecraft** (fondo
oscuro, relleno verde y marcas de píxel), con su valor encima:

- **CPU**: porcentaje del **equipo entero**. Podman mide el 100 % por núcleo, así
  que al arrancar un servidor Java —que usa varios a la vez— la cifra bruta
  puede pasar de 100; Serviscraft la reparte entre los núcleos disponibles y
  **nunca enseña más del 100 %**. Al pasar el ratón por encima se ve el detalle:
  «2.0 de 8 núcleos del equipo».
- **Memoria**: usada respecto a la **memoria asignada** al servidor (el
  contenedor no lleva un límite aparte, y compararla con la del equipo entero
  engañaría). El detalle exacto está en el mismo sitio.
- número de **procesos** del contenedor, a la derecha.

En **Detalles** se muestra además el espacio ocupado en disco y la dirección de
conexión (local o de red local), que puedes copiar al portapapeles.

## 13. Varios servidores

Cada servidor es completamente independiente:

- su propio contenedor Podman rootless,
- su propia carpeta de datos, mundos y copias,
- su propio puerto de juego y su propio puerto RCON (siempre en `127.0.0.1`).

Puedes tener varios en marcha a la vez mientras no compartan puerto. Serviscraft
asigna automáticamente puertos libres al crear servidores nuevos.

Para apagarlos todos de golpe, usa **Detener todos** (barra lateral o menú
*Servidor*): recorre los que estén en marcha y los detiene con su copia de
seguridad habitual. La app vuelve a leer el estado real de cada contenedor, así
que un servidor que se apagó por su cuenta deja de aparecer como «En ejecución».

## 14. Ventanas estrechas y mosaico automático

Serviscraft se adapta a cualquier ancho de ventana, incluido el que imponen los
guiones de mosaico automático de KDE (como **Polonium**), que colocan la ventana
donde dicta el mosaico aunque sea más estrecha que su tamaño mínimo:

- Las barras de botones **pasan a la línea siguiente** cuando no caben, en lugar
  de cortar el texto a media palabra.
- El resumen de estado de la consola ocupa **su propia línea**, así que siempre se
  lee (recortado con `…` si el hueco es muy justo) y nunca se queda vacío.
- Los nombres largos se recortan con `…` y el nombre completo aparece al pasar el
  ratón por encima.
- Por debajo de **640 px de ancho**, la lista de servidores se oculta sola para
  dejar todo el espacio al panel. Se recupera con el botón **«Servidores»** (arriba
  a la izquierda, junto a *Nuevo servidor…*) o con **`Ctrl+B`**. Si la ocultas tú,
  se respeta tu decisión y no vuelve sola al ensanchar.
- En mosaicos muy estrechos (1/4 de pantalla) la barra superior agrupa las acciones
  que no caben en su botón de desbordamiento **«»»**; todas siguen accesibles
  también desde los menús.
- Las **pestañas** llevan su nombre completo: cuando no caben todas se navega con
  las flechas de la propia barra de pestañas, en vez de recortar los títulos. Las
  tablas anchas, como la de **Jugadores** o la de **Mods**, se pueden desplazar en
  horizontal.
- Si la ventana es tan **baja** que una pestaña no cabe (por ejemplo, en un mosaico
  de 1/4 de pantalla), la pestaña se desplaza en **vertical** con su propia barra.
  Así los botones nunca se dibujan encima del texto y no se pierde nada: se baja
  con la rueda del ratón o con la barra de la derecha.

Puedes redimensionar la ventana a cualquier tamaño con seguridad: nada se recorta
ni se sale de la ventana.

## 15. Cambiar la versión, la memoria o Java

Los **ajustes de un servidor** (cabecera o menú *Servidor → Ajustes del
servidor…*) están organizados por secciones:

| Sección | Qué se cambia |
| --- | --- |
| **Identidad** | El **nombre** que ves en la lista. |
| **Minecraft** | La **versión de Minecraft** y la **versión de Java** del contenedor. |
| **Recursos** | La **memoria (RAM)** con un deslizador y el **puerto** de conexión. |
| **Red** | El acceso desde la **red local**. |

Si el cuadro no cabe en la pantalla (o la ventana es baja), las secciones se
desplazan con su propia barra y **Guardar** queda siempre a la vista.

El servidor debe estar **detenido**. Al guardar se vuelve a crear el contenedor
con los nuevos valores; **el mundo y el contenido no se borran**.

Detalles:

- La **versión de Minecraft** se elige de la lista publicada (el botón **Actualizar
  lista…** consulta las últimas de Mojang). Serviscraft ajusta sola la **versión de
  Java** recomendada; si la cambias a mano, se respeta aunque cambies de versión de
  Minecraft.
- La **memoria** se elige deslizando o escribiendo el número exacto. El texto de
  debajo te dice cuánto *heap* tendrá Java y cuánto ocupará el contenedor en total
  (se añade un margen para la propia máquina virtual). Usar solo la memoria que
  necesites deja el equipo más ágil.
- El **puerto** debe estar libre: Serviscraft lo comprueba antes de guardar.
- Los **mundos no siempre son compatibles entre versiones**: si vas a volver a una
  versión anterior, crea antes una copia de seguridad desde la pestaña **Copias**.

### Si el servidor murió por el Java equivocado

Cada versión de Minecraft necesita un Java concreto. Por ejemplo, las versiones
**26.x y 25.x** (y `latest`) necesitan **Java 25**; 1.20.5 o superior, Java 21;
1.17–1.20.4, Java 17; y 1.16.5 o anterior, Java 8. Si un servidor se creó con una
versión antigua de Serviscraft, pudo quedarse con una etiqueta de Java que ya no
sirve y el contenedor moría al instante con
*«requires running the server with Java 25 or above»*.

Ahora Serviscraft:

1. **lo comprueba antes de arrancar** y, si la etiqueta no es la correcta,
   **recrea el contenedor** con la buena (el mundo, los mods y las copias **no se
   tocan**);
2. si aun así falla, lee el registro del contenedor y **explica el motivo** con un
   botón **Cambiar Java y arrancar…** que solo cambia esa etiqueta.

No hay que volver a crear el servidor ni recuperar el mundo a mano.

## 16. Dónde están los archivos del servidor

Cada servidor tiene su propia carpeta dentro de tu usuario (nunca hace falta
`sudo`):

| Qué | Ruta |
| --- | --- |
| Datos del servidor | `~/.local/share/serviscraft/servers/<id>/data/` |
| Mundos | `~/.local/share/serviscraft/servers/<id>/data/world*/` |
| Plugins | `~/.local/share/serviscraft/servers/<id>/data/plugins/` |
| Mods | `~/.local/share/serviscraft/servers/<id>/data/mods/` |
| Registros | `~/.local/share/serviscraft/servers/<id>/data/logs/` |
| Informes de fallo | `~/.local/share/serviscraft/servers/<id>/data/crash-reports/` |
| Copias de seguridad | `~/.local/share/serviscraft/servers/<id>/backups/` |
| Icono del servidor en la lista | `~/.local/share/serviscraft/servers/<id>/data/server-icon.png` |
| Iconos de proyectos (caché) | `~/.cache/serviscraft/iconos/` |

Para llegar a ellas sin buscar a mano:

- botón **Carpeta** en la barra de herramientas o menú
  *Servidor → Abrir carpeta del servidor*;
- menú *Servidor → Abrir carpeta de copias*;
- pestaña **Copias**, donde la ruta aparece escrita junto a **Abrir carpeta** y
  **Copiar ruta**;
- pestaña **Detalles**, donde aparecen las dos rutas completas y sus botones;
- en la pestaña **Archivos**, el botón **Abrir carpeta** abre la vista actual.

La carpeta exacta de cada servidor aparece en la información emergente del
botón **Carpeta** y en la pestaña **Detalles**.

## 17. Solución de problemas

| Síntoma | Causa probable y solución |
| --- | --- |
| «Podman no está disponible» | Instala Podman (`sudo dnf install podman`) y comprueba que funciona sin `sudo`. |
| Podman funciona solo con `sudo` | Es la configuración equivocada para Serviscraft. Revisa que tu usuario pueda ejecutar `podman info` directamente. |
| El servidor no arranca y el registro dice que el puerto está ocupado | Otro programa usa ese puerto. Cambia el puerto en *Ajustes del servidor*. |
| «Espacio insuficiente» al descargar la imagen | Libera espacio en el disco; las imágenes de Minecraft ocupan varios cientos de MB. |
| El mundo aparece con propietario extraño | Revisa que `--userns=keep-id` está activo en las preferencias (opción por defecto). |
| No puedo conectar desde otro equipo | Activa *Acceso desde la red* y revisa tu cortafuegos (ver [`seguridad.md`](seguridad.md)). |
| La ventana no arranca en Wayland | Prueba `QT_QPA_PLATFORM=xcb serviscraft` para descartar un problema del plugin de plataforma. |
| Un modpack tarda muchísimo en arrancar la primera vez | Es normal: la imagen descarga el pack completo. Síguelo en la pestaña **Consola**. |
| El cuadro de modpacks no me deja usar una versión | Esa versión solo existe para **NeoForge**, que todavía no está soportado. Elige otra versión del pack. |
| Los botones de la pestaña **Jugadores** están desactivados | Las acciones se envían por la consola del servidor: inícialo para poder usarlas. La lista blanca, los operadores y los bloqueados se ven igualmente. |
| No encuentro mis copias de seguridad | Pestaña **Copias**: la ruta completa está encima de la tabla, con **Abrir carpeta** y **Copiar ruta**. Cada servidor tiene su propia carpeta `backups/`. |
| El servidor arranca pero dice que faltan mods | Pestaña **Mods** → **Analizar el registro**: te da el enlace de Modrinth de cada mod que falta y copia el `.jar` dentro del servidor. |
| Un mod desaparece o vuelve solo | Si venía del **modpack**, la imagen lo reinstala en cada arranque. Desactívalo desde la pestaña **Mods** (no lo borres) o quítalo del pack. |
| No veo el botón para editar la memoria o Java | Abre **Ajustes** con el servidor **detenido**: con el servidor en marcha la configuración no se puede recrear. |
| Con la ventana estrecha no veo todas las pestañas | Usa las flechas de la barra de pestañas (arriba a la derecha) para desplazarte entre ellas. |
| Quiero que entren jugadores sin cuenta premium | Pestaña **Unirse**: desactiva *Exigir cuentas premium*. Lee el aviso de seguridad y reinicia el servidor. |

El registro de la aplicación está en `~/.local/share/serviscraft/logs/serviscraft.log`
y se puede abrir desde *Ver → Ver registro de Serviscraft*.
