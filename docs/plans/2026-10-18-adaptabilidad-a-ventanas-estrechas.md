# Plan: adaptabilidad a ventanas estrechas (auto-tiling / Polonium)

- **Fecha:** 2026-10-18
- **Especificación:** `docs/specs/2026-10-18-adaptabilidad-a-ventanas-estrechas.md`
- **Estado:** pendiente de confirmación del usuario para ejecutar
- **Regla:** ante cualquier imprevisto, parar, actualizar este plan y avisar antes de improvisar.

## Medición (evidencia, no suposiciones)

Medido con `QT_QPA_PLATFORM=offscreen` sobre la ventana real (`.venv/bin/python`):

| Dato | Valor |
| --- | --- |
| Mínimo que pide la ventana (hoy) | **956 px** |
| Mínimo de la barra lateral | 280 px |
| Mínimo panel Consola | 634 px |
| Mínimo panel Copias | 645 px |
| Mínimo panel Propiedades | 462 px |
| Mínimo panel Archivos | 343 px |
| Mínimo cabecera | 577 px |
| Botones con icono | todos menos «Cancelar» |

Con la ventana clavada en su mínimo (1024) ya aparecen recortes; a 960 px reales (Wayland,
Polonium) la etiqueta de estado degenera en `'C'` y «Guardar registro» se ve cortado.

## Tareas

- [x] **1. `FlowLayout` + `FlowRow` en `serviscraft/ui/common.py`**
  - `FlowLayout(QLayout)`: `addItem`, `count`, `itemAt`, `takeAt`, `setGeometry`,
    `sizeHint`, `minimumSize`, `hasHeightForWidth`, `heightForWidth`, `doLayout`
    con espaciado e interlineado.
  - `FlowRow(QWidget)`: contiene el `FlowLayout`, `setSizePolicy(Preferred, Minimum)`
    con `setHeightForWidth(True)`, `heightForWidth()` reenviado, `minimumSizeHint`
    acotado al elemento más ancho.
  - Prueba unitaria: con ancho amplio → 1 fila y alto de fila; con ancho estrecho →
    más filas y `heightForWidth` mayor.
  - Verificación: medir que un `FlowRow` con 5 botones ocupa 1 fila a 900 px y ≥3 a 300 px.

- [x] **2. Aplicar `FlowRow` a los 8 grupos de botones** del diseño §4.2
  (cabecera, pie lateral, consola, propiedades, archivos ×2, copias, detalles).
  - Mantener objeto y señales: los widgets se siguen guardando en los mismos atributos
    (`self.start_button`, `self.import_button`…) para no romper pruebas ni lógica.
  - Verificación: medir a 480/560/700 que ningún botón queda `< sizeHint`.

- [x] **3. `ElidedLabel` sin restos degenerados**
  - `_MIN_VISIBLE_CHARS = 2` y limpieza del `elided` que conserve menos caracteres.
  - Conservar la rama «no visible → texto completo» y el `tooltip` con el texto completo.
  - Pruebas: `test_la_barra_de_la_consola_no_recorta_la_etiqueta`,
    `test_las_etiquetas_recortadas_usan_el_ancho_disponible` (existentes) +
    nueva `test_ninguna_etiqueta_queda_con_un_solo_caracter` (rojo→verde).

- [x] **4. Barra lateral auto-ocultable**
  - `ServerSidebar.setMinimumWidth(190)`.
  - `MainWindow`: `_ANCHO_ESTRECHO = 640`, `resizeEvent`, estado
    `_barra_oculta_por_automatismo`, botón `self.sidebar_button` («☰ Servidores») en la
    cabecera y acción en el menú *Ver* con `Ctrl+B`.
  - Pruebas: ocultar a 560, mostrar a 1280, respetar la elección manual.

- [x] **5. Mínimos**
  - `setMinimumSize(480, 420)`; quitar `FilesPanel.setMinimumWidth(520)`;
    `self.tabs.tabBar().setElideMode(QTabBar.ElideRight)`.

- [x] **6. Prueba de aceptación (barrido)**
  - `test_las_barras_se_adaptan_a_ventanas_estrechas`: para 480/560/700/900/1280 px y
    las 5 pestañas, ningún `QPushButton`/`QCheckBox` visible con
    `width() < sizeHint().width() - 2`.
  - Forzar el rojo antes del arreglo (debe fallar) para demostrar que mide algo real.

- [x] **7. Suite completa** (`pytest -q`): esperado ≥296 pruebas + las nuevas, salida 0.

- [x] **8. Documentación**
  - `docs/desarrollo.md`: convención de `FlowRow` para barras de botones y umbral 640.
  - `docs/uso.md`: botón «☰ Servidores» / `Ctrl+B` y nota de auto-tiling.

- [x] **9. Paquetes y verificación final**
  - `make packages` (rpm + deb + AppImage) y `--self-test` de cada uno.
  - Reverificar payload de rpm/deb (`/tmp/opencode/verificar_paquetes.py`) y AppImage
    (`/tmp/opencode/verificar_appimage.py`); captura real en Wayland.

## Orden de trabajo

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Cada tarea en rojo→verde y sin avanzar sin su
verificación.

## Riesgos y planes B

- **`heightForWidth` no propaga**: si el envoltorio no crece, calcular el alto del
  `FlowRow` a mano en `resizeEvent` del panel (contar filas y fijar `setFixedHeight`).
- **Pruebas de geometría existentes**: si alguna asume 1024 px, ajustarla justificándolo
  aquí como «Ajuste durante la ejecución».
- **Aspecto en ancho grande**: comparar captura antes/después; debe ser igual (1 fila).

## Autoevaluación del plan

- Todos los cambios son de presentación: no tocan Podman, seguridad ni datos.
- Todo lo nuevo lleva prueba y medición; nada se da por bueno «a ojo».
- El plan cabe en una sola sesión (≈8 archivos) y cada paso es reversible.

## Ajustes durante la ejecución

1. **`FilesPanel.setMinimumWidth(520)` no existía**: ese mínimo era del diálogo
   `DownloadDialog` (ventana aparte, no afectada por el mosaico), así que **no se
   tocó**. El panel de archivos no imponía ningún mínimo propio.
2. **Apareció una etiqueta recortada más**: el título «Propiedades del servidor»
   era una `QLabel` normal y se recortaba a 640 px (además explicaba el mínimo
   inherente de 595 px de la ventana). Convertida a `ElidedLabel`; ahora la
   ventana no necesita más de **404 px** con la lista apartada.
3. **La prueba de aceptación se endureció**: al forzar el rojo se descubrió que,
   sin envolvimiento, los botones no se *encogen* (mantienen su ancho) sino que
   **se salen de la ventana** («Guardar registro» llegaba a 833 px en una ventana
   de 480). La prueba ahora comprueba las dos cosas: que el ancho no sea menor que
   el del texto **y** que el control no se salga por la derecha.
4. **La prueba unitaria del `FlowRow` necesitó un `addStretch` debajo**, como en
   los paneles reales: sin él la fila ocupa todo el alto y no se puede medir el
   crecimiento al envolver.
5. **La ruta de la pestaña «Archivos»** (`self.path_label`) pasó a `ElidedLabel` y
   su fila a `FlowRow`: una ruta larga es exactamente el caso que se recorta.
6. **La barra superior no usa `FlowRow`**: es un `QToolBar` y desborda con el botón
   «»» estándar de Qt (las acciones siguen en los menús). Medido a 480 px: no
   recorta nada y su mínimo es 161 px.
7. **Error de un píxel en `FlowLayout`**: al medir una ventana ancha se vio que la
   fila que encajaba **justo** de ancho se partía igualmente (`rect.right()` es
   inclusivo). Corregido usando el borde derecho exclusivo
   (`rect.x() + rect.width() - margen`); ahora, por ejemplo, los 5 botones de la
   cabecera caben en una sola fila a 1280 px.
8. **La lista de servidores se quedaba en 300 px** y su pie (303 px) envolvía en
   dos filas incluso con la ventana ancha. El ancho inicial del divisor pasa a
   `[320, 960]` y el pie vuelve a una sola fila.
9. **La etiqueta de estado de la consola llegaba a 0 px** (y a mostrarse vacía)
   porque `QBoxLayout` le quitaba el ancho antes que encoger los botones; limitar
   su ancho máximo lo empeoraba. Solución: la etiqueta tiene **su propia línea**
   (siempre legible) y los botones la línea siguiente, donde envuelven si hace
   falta. Con eso la consola vuelve a una sola fila de botones desde 1024 px y la
   etiqueta nunca queda vacía. Prueba de regresión:
   `test_la_etiqueta_de_estado_nunca_se_queda_sin_sitio`.

## Evidencia final

- Medición directa (ventana mostrada): de 480 a 1400 px, en las 5 pestañas,
  **cero recortes**; la lista se aparta por debajo de 640 px y vuelve al ensanchar.
- Suite completa: **302 pruebas en verde** (296 antes + 6 nuevas), `pytest` salida 0.
- Rojo demostrado: desactivando el envolvimiento, la prueba de aceptación falla
  con números concretos («Ajustes» hasta 562 px, «Guardar registro» hasta 833 px).
- Paquetes: rpm, deb y AppImage recompilados y verificados (payload + `--self-test`
  + capturas a 480 y 1280 px).

