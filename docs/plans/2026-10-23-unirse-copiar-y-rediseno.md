# Plan y traspaso: pestaña «Unirse», portapapeles, rediseño y diálogo de nombre

- **Fecha:** 2026-10-23
- **Estado:** completado y verificado
- **Petición del usuario:** el botón «Copiar» seguía sin funcionar; mejorar toda la
  interfaz y las texturas de la pestaña «Unirse»; arreglar el diálogo «Poner un
  nombre» (DuckDNS), que estaba «bugeadísimo»; verificar que todo funcione.
- **Regla de trabajo:** los cambios de esta sesión están **sin commit**.

## Dónde está el proyecto

Ruta con espacios; citarla siempre:

```bash
cd "/home/linius/Programador/Programas Personales Mios/Serviscraft"
```

- Python del proyecto: `.venv/bin/python`
- Interfaz: PySide6 6.11.2 / Qt 6.11.2
- Plataforma real del usuario: KDE Wayland (`XDG_SESSION_TYPE=wayland`).
- Las pruebas usan `QT_QPA_PLATFORM=offscreen`.

## Resultado final

### 1. El botón «Copiar» ya funciona en Wayland

El problema no era el texto que se copiaba: `ElidedLabel.full_text()` ya se leía
en el momento del clic. El problema era que, en Wayland, Qt puede dejar el texto
solo en su portapapeles interno si la ventana no tiene el foco o si el
compositor no publica la selección. Otro proceso (`wl-paste`) seguía viendo el
portapapeles anterior.

Solución implementada en `serviscraft/ui/common.py`:

- `copiar_al_portapapeles(texto) -> bool`.
- Primero escribe con `QApplication.clipboard().setText(...)`.
- En Wayland usa `wl-copy` como respaldo (habla directamente con el compositor).
- En X11 usa `xsel` o `xclip` si hace falta.
- En `QT_QPA_PLATFORM=offscreen` **nunca** llama a programas externos: así las
  pruebas no tocan el portapapeles real del usuario.
- Devuelve `True/False`; `JoinPanel` avisa si no se pudo copiar.

`JoinPanel._copy()` ahora:

1. Llama al helper.
2. Si funciona, muestra el chip verde «Copiado al portapapeles» y cambia el
   botón a «Copiado» durante 1,4 s.
3. Si falla, abre un aviso con la dirección completa y la instrucción de
   seleccionarla y pulsar `Ctrl+C`.

### 2. Rediseño de «Unirse»

- Cabecera hero verde con degradado y textura de bloques dibujada con Qt
  (`_JoinHero` en `join_panel.py`), icono propio de Java+Bedrock y botón «?».
- Dirección principal en una tarjeta destacada:
  - título «Dirección del servidor»;
  - chip «Comparte esta»;
  - dirección grande en monoespaciada;
  - botón verde grande «Copiar dirección» debajo, para que la dirección se lea
    entera incluso con la barra lateral abierta.
- `localhost` en una tarjeta secundaria más discreta.
- Bedrock, Internet y Cuentas con tarjetas de dirección y botones consistentes.
- Icono propio de copiar (`icono_copiar`) e icono Java+Bedrock
  (`icono_conectar`) en `serviscraft/ui/mc_icons.py`.
- Chip de confirmación de copia y chip de estado de cuentas premium.
- Textos de sección más cortos para que no se recorten a 700 px.
- Se mantienen todos los atributos que usan las pruebas:
  `lan_address`, `local_address`, `ddns_address`, `public_address`,
  `bedrock_address`, `copy_lan_button`, `copy_local_button`,
  `copy_ddns_button`, `copy_public_button`, `copy_bedrock_button`,
  `container_label`, `scope_note`, `state_chip`, `platform_badge`, `premium`,
  `apply_button`, etc.

### 3. Diálogo «Poner un nombre» (DuckDNS) reconstruido

El diálogo se veía «bugeado» por tres causas concretas, no por el estilo:

1. **La ventana se abría más pequeña que su propio contenido.** `QDialog` limita
   el tamaño automático a dos tercios de la pantalla (`sizeHint` era 760×417,
   pero abría a 533×417 en una pantalla de 800 px). Los botones de la fila
   inferior se salían por la derecha y quedaban cortados.
2. **La vista previa de la dirección se pintaba a 18 px de alto.** Era un
   `WrappingLabel` con relleno de hoja de estilos: Qt le daba menos altura que la
   que necesita el texto, así que la dirección aparecía cortada por la mitad.
3. **La comprobación de DNS era síncrona.** `ddns.check()` se llamaba al abrir y
   al guardar; sin internet o con DNS lento, la ventana entera se congelaba.

Cambios en `serviscraft/ui/ddns_dialog.py`:

- Se abre a **720×494** (ancho mínimo 560) llamando a `resize()` antes de
  `show()`, saltándose el límite de dos tercios de `QDialog`.
- Las tres acciones principales van en un `FlowRow`: con sitio quedan en una
  fila y, en ventanas estrechas, se envuelven en vez de recortarse.
- La dirección resultante es un `QLineEdit` de solo lectura
  (`#DdnsPreview`): se puede seleccionar y copiar, y nunca se recorta en
  vertical. Se actualiza en vivo al escribir el nombre.
- Validación **inline y en vivo**: etiquetas rojas `#FieldError` bajo el nombre
  y bajo el token, con el motivo exacto. «Guardar y actualizar» solo se activa
  con nombre y token válidos.
- «Actualizar dirección» solo se activa cuando el formulario coincide con lo
  guardado; si hay cambios sin guardar, el tooltip explica que hay que guardar
  primero.
- El token se puede mostrar/ocultar con el botón `#TokenToggle` («Ver» /
  «Ocultar»).
- Toda consulta DNS (`ddns.check`) y toda llamada a DuckDNS
  (`configure_ddns` + `ddns_update`) se ejecuta con `TaskRunner` en segundo
  plano. La ventana nunca se bloquea; mientras tanto los controles se
  deshabilitan y el cierre se ignora para no perder el resultado.
- Chips de estado: «Sin configurar», «Comprobando...», «Funcionando»,
  «Apunta a otra IP», «Guardado», «Guardado sin actualizar», «Error al
  guardar», «Error al quitar».
- Al guardar se avisa a DuckDNS **sin IP explícita**: DuckDNS usa la IP de
  salida de la petición, así se corrige sola si el operador la cambió.
- Los errores de DuckDNS se muestran aparte de los errores de guardado: si el
  nombre se guardó pero DuckDNS no respondió, el chip lo dice y se abre un aviso
  con el detalle.
- `JoinPanel._abrir_ddns()` hace `raise_()` y `activateWindow()` para que el
  diálogo aparezca delante de la ventana principal.

Estilos nuevos en `serviscraft/ui/theme.py`: `QLineEdit#DdnsPreview`,
`QLabel#FieldError` y `QPushButton#TokenToggle`.

## Archivos tocados en esta tanda

- `serviscraft/ui/common.py` — helper `copiar_al_portapapeles`.
- `serviscraft/ui/join_panel.py` — rediseño, tarjetas, hero, feedback, uso del
  helper y activación del diálogo DDNS.
- `serviscraft/ui/ddns_dialog.py` — reescritura del diálogo: tamaño, validación
  inline, vista previa, acciones asíncronas y estados.
- `serviscraft/ui/mc_icons.py` — `icono_copiar`, `icono_conectar`.
- `serviscraft/ui/theme.py` — estilos del hero, tarjetas, dirección principal,
  botones de copia, botón de guardar cuentas y estilos del diálogo DDNS.
- `tests/test_gui.py` — pruebas del helper, del fallo de copia, de los iconos y
  del diálogo DDNS (`TestDialogoNombre`).
- `docs/plans/2026-10-23-unirse-copiar-y-rediseno.md` — este documento.

También siguen sin commit los cambios anteriores de Jugadores
(`players_panel.py`, `players_manager_dialog.py`, `common.py`, `theme.py`,
`mc_icons.py`). No revertirlos sin revisar el diff.

## Verificación realizada

### Pruebas automáticas

```bash
cd "/home/linius/Programador/Programas Personales Mios/Serviscraft"

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Resultado: **783 pruebas superadas**.

Pruebas dirigidas:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_gui.py::TestPestanaUnirse \
  tests/test_gui.py::TestAdaptabilidad \
  tests/test_gui.py::TestIconosDePlataforma \
  tests/test_gui.py::TestDialogoNombre -q
```

Resultado: **19 pruebas superadas**.

`TestDialogoNombre` cubre cuatro casos:

1. los botones y la dirección caben en la ventana, también a 560 px y con la
   vista previa a la altura correcta;
2. nombre y token inválidos muestran error inline y bloquean el guardado;
3. guardar aplica el nombre y avisa a DuckDNS;
4. una comprobación de DNS lenta no congela la ventana (corre en otro hilo).

### Prueba real en Wayland (no offscreen)

Se ejecutó un `JoinPanel` real con `QT_QPA_PLATFORM=wayland`, se pulsó el botón
de copiar y se leyó el portapapeles con `wl-paste` desde la terminal:

```text
PLATAFORMA=wayland TEXTO=192.168.1.27:25565
WL_PASTE=192.168.1.27:25565
```

También se probó el helper aislado:

```text
PLATAFORMA=wayland RESULTADO=True
WL_PASTE=serviscraft-copia-real-123
```

Esto demuestra que el texto llega al portapapeles del compositor, no solo al
portapapeles interno de Qt.

### Prueba real del diálogo DDNS en Wayland

Se abrió el diálogo real con `QT_QPA_PLATFORM=wayland` (sin `offscreen`) y se
comprobó su tamaño antes de mostrarlo:

```text
PLATAFORMA=wayland TAMANO=720x494
```

Es decir: se abre con el ancho previsto y no con el límite de dos tercios de
pantalla que lo dejaba en 533 px.

### Capturas revisadas

Generadas con `/tmp/opencode/join_shot.py` (fuera del repositorio):

- `/tmp/opencode/join.png` — 1280 px, parte superior.
- `/tmp/opencode/join_bottom.png` — 1280 px, parte inferior.
- `/tmp/opencode/join_copiado.png` — 1280 px, con el aviso de copia.
- `/tmp/opencode/join_700.png` y `join_700_bottom.png`.
- `/tmp/opencode/join_480.png` y `join_480_bottom.png`.

En las capturas se comprobó que:

- la dirección principal se lee entera a 700 y 480 px;
- los botones no se salen de la ventana;
- los textos largos se envuelven o se recortan con puntos suspensivos;
- el aviso «Copiado al portapapeles» aparece y no rompe el diseño;
- el botón «Guardar el modo de cuentas» y los controles de Bedrock siguen
  visibles y utilizables.

Capturas del diálogo DDNS, generadas con `/tmp/opencode/ddns_shot.py` (fuera del
repositorio):

- `/tmp/opencode/ddns_empty.png` — 720 px, formulario vacío.
- `/tmp/opencode/ddns_filled.png` — nombre y token válidos, vista previa.
- `/tmp/opencode/ddns_error.png` — error inline al escribir «Reino Trebol».
- `/tmp/opencode/ddns_560.png` — ancho mínimo, botones envueltos.
- `/tmp/opencode/ddns_900.png` — ventana ancha.
- `/tmp/opencode/ddns_saved.png` — chip «Guardado» tras guardar.
- `/tmp/opencode/ddns_live.png` — diálogo real en Wayland (720×494).

Comprobado en ellas:

- los seis botones caben y se leen enteros a 720, 900 y 560 px;
- la dirección de la vista previa se ve completa, sin recorte vertical;
- los mensajes de error aparecen bajo el campo correspondiente y no mueven los
  botones fuera de la ventana;
- el chip de estado cambia a «Guardado» sin deformar el diseño.

## Invariantes que hay que conservar

- Los textos de la interfaz se escriben **sin acentos** en el código, como el
  resto del proyecto.
- No usar emojis: los símbolos son iconos dibujados con Qt.
- La pestaña debe seguir funcionando a 480, 560, 700, 900 y 1280 px sin
  recortes.
- No tocar la lógica de servidores, Podman, puertos ni propiedades salvo lo
  imprescindible para la copia.
- En `offscreen` no se deben ejecutar `wl-copy`, `xsel` ni `xclip`.
- `FlowRow.widgets()` incluye widgets ocultos a propósito; el layout sí los
  ignora.
- `ElidedLabel.full_text()` devuelve el texto sin recortar; el botón debe leerlo
  en el momento del clic.
- **Un `QDialog` no se autoajusta a más de dos tercios de la pantalla.** Si el
  contenido necesita más, hay que llamar a `resize()` antes de `show()`; si no,
  los botones se salen aunque `sizeHint()` diga que caben.
- **`WrappingLabel` con relleno de hoja de estilos recibe menos alto del que
  necesita el texto.** Para valores de una línea con relleno, usar `QLineEdit`
  de solo lectura o fijar una altura mínima explícita.
- `ddns.check()` y `ddns.resolve()` salen a la red y pueden bloquear: siempre a
  través de `TaskRunner`, nunca en el hilo de la interfaz.
- El diálogo DDNS no debe cerrarse mientras hay un guardado en curso
  (`reject()` y `closeEvent()` lo impiden a propósito).
- «Actualizar dirección» solo tiene sentido cuando el formulario coincide con lo
  guardado; no habilitarlo con cambios pendientes.

## Riesgos residuales y notas para la próxima IA

- **Hay una instancia de Serviscraft en ejecución del usuario** (PID aproximado
  80286). No matarla sin permiso. Para ver el arreglo hay que **cerrar y volver
  a abrir Serviscraft**: el proceso actual sigue ejecutando el código anterior.
- Si el sistema no tiene `wl-copy`, el helper recurre al portapapeles de Qt y,
  en X11, a `xsel`/`xclip`. Sin `wl-copy` en Wayland, Qt necesita foco real para
  publicar la selección.
- La llamada a `wl-copy` es síncrona y tiene un límite de 2 segundos; en
  condiciones normales termina de inmediato.
- `ruff` no está instalado en `.venv`; no se puede ejecutar aunque se intente.
- Las capturas se generan fuera del repositorio; no añadirlas al proyecto salvo
  que el usuario lo pida.
- En una pantalla muy pequeña (menos de ~620 px de ancho útil) el diálogo baja
  al mínimo de 560 px y los botones se envuelven; el contenido sigue siendo
  usable, pero conviene revisarlo si se cambia el texto de los botones.
- El diálogo comprueba el nombre guardado al abrirse en segundo plano. Si se
  cierra justo en ese momento, el `TaskRunner` puede seguir vivo hasta que
  termine la consulta; las pruebas esperan con `wait_for_done()`.

## Comandos útiles

```bash
# Suite completa
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Solo el diálogo DDNS
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_gui.py::TestDialogoNombre -q

# Capturas visuales (scripts temporales)
PYTHONPATH=. .venv/bin/python /tmp/opencode/join_shot.py
PYTHONPATH=. .venv/bin/python /tmp/opencode/ddns_shot.py

# Diálogo DDNS real en Wayland (imprime PLATAFORMA y TAMANO)
PYTHONPATH=. .venv/bin/python /tmp/opencode/ddns_live.py

# Comprobar el portapapeles real en Wayland
wl-paste --no-newline
```

Para probar el portapapeles real con una app Qt enfocada en XWayland:

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python /tmp/opencode/clip_server_xcb.py
wmctrl -a "SERVISCRAFT CLIP TEST"
xsel --clipboard --output
```
