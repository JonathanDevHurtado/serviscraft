# Registro de cambios

Todas las versiones son para Linux y usan Podman rootless. Las fechas son las de
publicación del paquete.

## 0.8.0 — 19 de octubre de 2026

- **Importar servidores** existentes desde una carpeta o el `.zip` de Aternos:
  reconoce tipo, versión, mundo, plugins/mods, puerto y origen, copia los datos
  sin tocar el original y no crea el contenedor hasta el primer inicio.
- **Texturas de objetos y skins** en el inventario del jugador, con caché,
  validación de PNG y respaldo con iconos dibujados si no hay red.
- **Listas de jugadores unificadas**: lista blanca, bloqueados y operadores en
  una sola ventana; funciona con el servidor apagado.
- **Renombrar copias de seguridad** sin tocar el `.tar.gz`.
- **Monitor de CPU y RAM** con aspecto de las barras de experiencia de
  Minecraft; la CPU se muestra como porcentaje del equipo y nunca pasa de 100 %.
- **Detener todos** apaga de verdad todos los servidores y el estado que se ve
  es siempre el real de Podman.
- Corrige el estado «en marcha» de servidores ya apagados y las fichas de
  servidor inválidas que podían interrumpir la carga de la lista.

## 0.7.0 — 19 de octubre de 2026

- **Nombre para entrar**: DuckDNS en vez de una IP, con comprobación de que
  resuelve y actualización automática de la IP al arrancar.
- **Imagen y descripción** del servidor: icono de 64×64 y las dos líneas de la
  lista de Minecraft, con los 16 colores, vista previa y ocho bloques.
- **Cabecera adaptable**: con poco ancho los botones bajan a su propia línea.
- Endurecimiento del icono, el texto y el guardado atómico.
- **Auditoría de seguridad**: permisos, rutas, enlaces, redirecciones, secretos
  y configuración de los contenedores.

## 0.6.0 — 19 de octubre de 2026

- **Jugadores**: fichas de resumen (conectados, lista blanca, operadores,
  bloqueados), cara en la tabla y colores en los «Sí».
- **Inventario del jugador**: mochila, armadura, mano secundaria y barra rápida,
  con vida, comida y nivel, leído por RCON sin tocar el mundo.
- **Consola con personalidad**: punto de estado, leyenda de colores, filtro
  «Solo problemas» y «Copiar todo».
- Botones «?» de ayuda en Consola, Jugadores, Mods y Unirse.

## 0.5.0 — 19 de octubre de 2026

- Reparación automática de servidores antiguos con el Java equivocado, sin
  tocar el mundo.
- Migración de datos de versiones anteriores conservando todas las claves.
- Seguimiento en vivo de la consola activado por defecto y conmutable.
- Pestaña **Unirse** paso a paso, con IP pública y guía para jugar desde fuera.
- **Bedrock** con Geyser y Floodgate en servidores Paper.
- Iconos de Java/Bedrock y de cada mod o plugin.
- Textos de ayuda adaptables a ventanas estrechas.

## 0.4.0 — 19 de octubre de 2026

- Selector de modpacks con cargador, versiones, descargas, fecha y filtros.
- Catálogo de mods y plugins con los datos del proyecto y filtrado por cargador.
- Versiones de Minecraft elegidas de la lista publicada.
- Ajustes por secciones; memoria y Java cambiables en un servidor existente.
- Pestaña **Mods**: activar/desactivar sin borrar, eliminar y añadir desde
  Modrinth, un `.jar` local o una URL.
- Pestaña **Registros** con filtro, seguimiento y búsqueda de mods que faltan.
- Pestaña **Unirse** con dirección, puerto y modo de cuentas.
- Detección y descarga de los mods que el modpack no pudo bajar.
- Cajas de números y tareas de fondo corregidas.

## 0.3.0 — 18 de octubre de 2026

- Copia de seguridad automática al detener cada servidor.
- Copias programadas con retención configurable; las manuales nunca se borran.
- Origen visible de cada copia (al detener, programada, manual, automática o
  importada).
- Pestaña **Jugadores** con conectados, lista blanca, operadores y bloqueados;
  OP, expulsión, bloqueo y perdón por RCON.
- Modpacks de Modrinth con Fabric, Forge o Quilt, y aviso para NeoForge.
- Reiniciar como parada ordenada con copia más arranque.
- Dos copias en el mismo segundo ya no se pisan.

## 0.2.0 — 18 de octubre de 2026

- Corrige el asistente de creación, que no se abría.
- Cambio de versión de Minecraft con Java recomendado y aviso de compatibilidad.
- Catálogo de Modrinth con verificación SHA-512.
- Botones para abrir las carpetas de datos y de copias.
- Paper seleccionado por defecto.

## 0.1.0 — 18 de octubre de 2026

- Versión inicial: creación y gestión de servidores con Podman rootless,
  consola en tiempo real, propiedades, plugins/mods, mundos, copias de
  seguridad y estadísticas de CPU y memoria.
