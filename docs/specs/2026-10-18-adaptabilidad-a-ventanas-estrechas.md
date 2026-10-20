# Especificación: Serviscraft adaptable a ventanas estrechas

Fecha: 2026-10-18 · Estado: aprobada por el usuario (diseño) · Plan: `docs/plans/2026-10-18-adaptabilidad-a-ventanas-estrechas.md`

## 1. Motivo

El usuario usa el guion de KWin **Polonium** (auto-tiling): el gestor de ventanas
coloca Serviscraft en el tamaño que dicta el mosaico (1/2, 1/3 o 1/4 de pantalla)
**ignorando el tamaño mínimo que pide la aplicación**. Medido en esa situación:

- La ventana no baja de **956 px** (mínimo propio, hoy fijado en 1024×620) y aun así
  ya a 1024 px hay botones recortados.
- Cada barra es **una sola fila** (`QHBoxLayout`), de modo que si no cabe, el texto se
  corta a media palabra: `'Nuevo servidor' (131<147)`, `'Restaurar seleccionada' (82<192)`,
  `'Crear copia ahora' (82<163)`, `'Detener todos' (131<138)`…
- A ~960 px reales (Wayland) la etiqueta de estado de la consola degenera en **`'C'`**.

Evidencia: `docs/plans/…` (sección «Medición») y capturas `appimg2-wayland/*.png`.

## 2. Objetivo

Que la interfaz sea **usable a cualquier ancho** que imponga un auto-tiling, desde
~480 px (1/4 de una pantalla Full HD) en adelante, **sin recortar ningún texto** y
sin elementos degenerados. No se pierde ninguna función ni se añade ninguna nueva
de gestión; solo cambia la presentación.

## 3. Alcance

Dentro:

- Envolver en varias filas los grupos de botones que hoy son una única fila.
- Impedir etiquetas de un solo carácter al no caber.
- Hacer que la barra lateral se aparte sola cuando la ventana es estrecha.
- Bajar el mínimo de la ventana y quitar mínimos rígidos de los paneles.

Fuera (sin cambios): el motor Podman, las operaciones, la validación de entradas,
el registro de errores, la seguridad y el comportamiento de arranque (los servidores
siguen **detenidos** por defecto).

## 4. Diseño aprobado

### 4.1 `FlowLayout` y `FlowRow` (nuevo, en `serviscraft/ui/common.py`)

`FlowLayout` reparte los elementos de izquierda a derecha y, cuando no caben, **los
pasa a la fila siguiente**; su altura se calcula con `heightForWidth`. Es el ejemplo
oficial de Qt (`FlowLayout`) adaptado y documentado en español.

`FlowRow` es un `QWidget` fino que:
- contiene un `FlowLayout`,
- fija `sizePolicy` con `setHeightForWidth(True)`,
- reenvía `heightForWidth()` (y no impone ancho mínimo mayor que el del elemento más
  ancho). Así el `QVBoxLayout` de cada panel le concede el alto que necesita.

Con sitio suficiente el resultado es **idéntico al aspecto actual** (una sola fila).

### 4.2 Dónde se aplica

| Lugar | Hoy | Después |
| --- | --- | --- |
| Cabecera del servidor (Iniciar, Detener, Reiniciar, Ajustes, Eliminar) | 1 fila | `FlowRow` |
| Pie de la barra lateral (Nuevo servidor, Detener todos) | 1 fila | `FlowRow` |
| Consola (estado + casilla + Seguir/Limpiar/Guardar) | 1 fila | etiqueta de estado en su propia línea + `FlowRow` |
| Propiedades (Recargar, Guardar cambios) | 1 fila | `FlowRow` |
| Archivos (barra de vista + 5 botones) | 1 fila | `FlowRow` |
| Archivos ▸ acciones de mundos (Activar, Renombrar, Copiar mundo) | 1 fila | `FlowRow` |
| Copias (5 botones + Conservar + Limpiar antiguas) | 1 fila | `FlowRow` |
| Detalles (Copiar dirección, Guardar notas, Mantenimiento ×2) | 1 fila c/u | `FlowRow` |

No se tocan los formularios (`QFormLayout`) ni las tablas.

> Ajuste medido durante la ejecución: el resumen de estado de la consola **no puede
> compartir fila** con el grupo de botones. Al faltar ancho, `QBoxLayout` se lo quita
> todo a la etiqueta antes que encoger los botones (llegaba a quedarse con 0 px y a
> mostrarse vacía), y limitarle el ancho máximo lo empeoraba. Por eso la etiqueta va
> en su propia línea: siempre se lee entera (recortada con `…` si hace falta) y los
> botones disponen de toda la línea siguiente.

### 4.3 `ElidedLabel` sin restos

- Nueva constante `_MIN_VISIBLE_CHARS = 2`: si el texto recortado conserva **menos de
  2 caracteres reales** (sin contar `…`) se muestra `""` en lugar de una letra suelta.
- Se conserva el comportamiento ya corregido: si la etiqueta **no está visible** (pestaña
  oculta o ventana sin mostrar), no se recorta (el ancho es degenerado).
- Con sitio sigue recortando con `…` y el texto completo vive en el *tooltip*.

### 4.4 Barra lateral auto-ocultable

- `ServerSidebar.setMinimumWidth(280)` → **190**.
- Nuevo umbral `MainWindow._ANCHO_ESTRECHO = 640`:
  - al bajar de 640 px, si la barra está visible **se oculta sola**;
  - al volver a subir, solo reaparece si se ocultó **automáticamente** (si el usuario
    la cerró a mano, se respeta su elección).
- Botón **«☰ Servidores»** en la cabecera (visible solo cuando hay servidor) y acción
  *Ver ▸ Barra lateral* (`Ctrl+B`) para mostrarla u ocultarla manualmente.

### 4.5 Mínimos

- `MainWindow.setMinimumSize(480, 420)` (antes 1024×620).
- `FilesPanel.setMinimumWidth(520)` → se elimina.
- `QTabBar` con recorte a la derecha (`ElideRight`) en vez de forzar ancho.

## 5. Criterios de aceptación

1. A anchos **480, 560, 700, 900 y 1280 px**, en las **5 pestañas**, **ningún**
   `QPushButton` ni `QCheckBox` visible queda más estrecho que su `sizeHint` (es decir,
   ningún texto cortado).
2. Ninguna `ElidedLabel` visible muestra una sola letra: o muestra `…` con ≥2 caracteres,
   o está vacía.
3. A 560 px la barra lateral está oculta y el botón «☰ Servidores» la recupera; a
   1280 px vuelve a estar visible; si se cierra a mano, sigue cerrada al ensanchar.
4. Las funciones actuales siguen intactas: suite completa en verde (≥296 pruebas) y
   `--self-test` de los paquetes dice «Todo listo.».
5. Se regeneran y verifican los tres paquetes (rpm, deb, AppImage).

## 6. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| `heightForWidth` no se propaga y los botones no envuelven | `FlowRow` fija la política de tamaño; **se mide** con script antes de dar por bueno |
| Pruebas de geometría existentes que asumen ventana ≥1024 | Revisar y ajustar solo lo imprescindible, dejando constancia en el plan |
| El auto-ocultar pelea con el usuario | Se distingue ocultado automático de ocultado manual |
| Aspecto distinto en ventanas anchas | `FlowLayout` con espacio = una sola fila; se compara con captura |
