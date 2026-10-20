# Plan: recorte elegante de textos largos y verificación de paquetes

> **Para quien ejecute esto:** sub-skill obligatoria: `subagent-driven-development` (recomendada) o `executing-plans`. Los pasos usan casillas (`- [ ]`).

**Objetivo:** que ningún nombre de servidor largo recorte la interfaz (tarjeta lateral y barra de la consola) y volver a construir y verificar los tres paquetes (rpm, deb, AppImage) con el código final.

**Arquitectura:** reutilizar `ElidedLabel`, ya existente en `serviscraft/ui/common.py`: muestra el texto completo si hay sitio y lo recorta con `…` dejando el texto íntegro en el *tooltip* cuando no lo hay. Su `sizeHint` se calcula siempre sobre el texto **completo**, de modo que la etiqueta vuelve a crecer al ensanchar la ventana. No se cambia nada más.

**Tecnologías:** Python 3.10+, PySide6 6.11/6.12, pytest + pytest-qt (plataforma `offscreen`), `rpmbuild`, `ar`+`tar`, `appimagetool`.

---

## Suposiciones (corrígeme si alguna es falsa)

1. La cabecera ya reorganizada (insignia de estado en la segunda línea, título recortable) se queda como está: ya está verificada con 292 pruebas en verde y capturas.
2. Reconstruir y verificar `rpm`, `deb` y `AppImage` entra en el alcance acordado (los pediste al principio).
3. El proyecto **no** es un repositorio git, así que no hay pasos de `git commit`; cada tarea termina con las pruebas en verde.
4. El alcance se limita a los recortes **medidos**. `properties_panel.title` y el resto de etiquetas **no** se tocan porque no se recortan.

---

## Evidencia previa (medida hoy)

Ventana al tamaño mínimo (1024×620) con un nombre de 30 caracteres. Barrido de **todas** las `QLabel` visibles de las 5 pestañas, ignorando las que tienen `wordWrap` y las `ElidedLabel`:

| Etiqueta | `objectName` | ancho | `sizeHint` | ¿recortada? |
| --- | --- | --- | --- | --- |
| `console_panel.status_label` | `Hint` | 143 | 575 | **sí** |
| `server_list` tarjeta, título | `ServerCardTitle` | 213 | 217 | **sí** |
| resto de etiquetas | — | — | — | no |

Y el comportamiento del widget de item de `QListWidget`, comprobado en aislamiento (viewport de 256 px):

| `setSizeHint` del item | ancho de la tarjeta | ¿barra horizontal? |
| --- | --- | --- |
| ancho de la tarjeta (código actual) | 309 px | **sí** (la insignia queda cortada) |
| ancho 0 | 256 px = viewport | no |

Es decir: la tarjeta lateral se sale de la barra porque su `sizeHint` fuerza el ancho del item.

---

## Mapa de ficheros

| Fichero | Responsabilidad | Cambio |
| --- | --- | --- |
| `serviscraft/ui/server_list.py` | tarjeta y barra lateral | título y subtítulo recortables; ancho del item; filtro por el texto completo |
| `serviscraft/ui/console_panel.py` | consola y su barra | etiqueta de estado recortable |
| `tests/test_gui.py` | pruebas de interfaz | 3 pruebas nuevas (clase `TestPaneles`) |
| `docs/desarrollo.md` | documentación | nota sobre `ElidedLabel` |

No se toca `serviscraft/core/`.

---

## Tarea 1: la tarjeta lateral no se sale de la barra

**Ficheros:**
- Modificar: `serviscraft/ui/server_list.py:24` (import), `:50`, `:57`, `:140`, `:188`
- Test: `tests/test_gui.py` (clase `TestPaneles`)

- [ ] **Paso 1: escribir la prueba que falla**

```python
    def test_la_tarjeta_lateral_no_se_sale_de_la_barra(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el nombre largo ensanchaba la tarjeta y la cortaba la barra."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        lista = window.sidebar.list
        tarjeta = window.sidebar._cards[spec.id]
        assert not lista.horizontalScrollBar().isVisible(), (
            "la tarjeta lateral ensancha la lista y saca una barra horizontal"
        )
        assert tarjeta.width() <= lista.viewport().width()
        assert tarjeta.badge.width() >= tarjeta.badge.sizeHint().width() - 2, (
            f"la insignia de estado se recorta: {tarjeta.badge.width()} px"
        )
```

- [ ] **Paso 2: ejecutarla y comprobar que falla**

Comando: `.venv/bin/python -m pytest "tests/test_gui.py::TestPaneles::test_la_tarjeta_lateral_no_se_sale_de_la_barra" -q`
Esperado: FAIL (la tarjeta mide ~309 px en un viewport de ~256 y la barra horizontal está visible).

- [ ] **Paso 3: implementar**

En `serviscraft/ui/server_list.py`, línea 24, añadir `ElidedLabel` al import:

```python
from .common import STATE_COLORS, ElidedLabel, StatusBadge, make_button
```

Líneas 50 y 57 (título y subtítulo de la tarjeta):

```python
        self.title = ElidedLabel(view.spec.name)
        self.title.setObjectName("ServerCardTitle")
```
```python
        self.subtitle = ElidedLabel()
        self.subtitle.setObjectName("ServerCardSubtitle")
```

Línea 140, dentro de `set_servers` (el item toma el ancho del viewport en vez del
ancho del texto):

```python
            # Ancho 0: el item se ajusta al ancho visible de la lista. Si se usa el
            # sizeHint de la tarjeta (que crece con el nombre), la lista saca una
            # barra horizontal y recorta la insignia de estado.
            item.setSizeHint(QSize(0, card.sizeHint().height() + 10))
```

Línea 188, en `_apply_filter` (el filtro debe buscar en el texto **completo**;
con un `ElidedLabel`, `text()` devuelve el texto ya recortado):

```python
            nombre = self._cards[view_id].title
            texto = nombre.full_text() if isinstance(nombre, ElidedLabel) else nombre.text()
            hidden = bool(needle) and needle not in view_id and needle not in texto.lower()
```

- [ ] **Paso 4: ejecutarla y comprobar que pasa**

Comando: `.venv/bin/python -m pytest "tests/test_gui.py::TestPaneles::test_la_tarjeta_lateral_no_se_sale_de_la_barra" -q`
Esperado: PASS.

- [ ] **Paso 5: escribir la prueba de la búsqueda (protege el paso 3)**

```python
    def test_la_busqueda_encuentra_por_el_nombre_completo(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """El recorte del titulo no debe romper la busqueda de la barra lateral."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.CREATED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        window.sidebar.search.setText("supervivencia")
        for _ in range(6):
            qapp.processEvents()
        item = window.sidebar._items[spec.id]
        assert not item.isHidden(), "no se encuentra el servidor por su nombre completo"
```

- [ ] **Paso 6: comprobar el rojo de esa prueba**

Editar temporalmente la línea 188 del paso 3 para que use solo `nombre.text()`,
ejecutar `pytest tests/test_gui.py::TestPaneles::test_la_busqueda_encuentra_por_el_nombre_completo -q`
y comprobar que **falla**; después volver a la versión con `full_text()` y
comprobar que **pasa**.

---

## Tarea 2: la etiqueta de estado de la consola

**Ficheros:**
- Modificar: `serviscraft/ui/console_panel.py:25` (import), `:83`
- Modificar: `tests/test_gui.py` (import de `ElidedLabel` en la línea 28)
- Test: `tests/test_gui.py` (clase `TestPaneles`)

- [ ] **Paso 1: añadir el import que necesita la prueba**

Línea 28 de `tests/test_gui.py`:

```python
from serviscraft.ui.common import ElidedLabel, StatusBadge, polish_table_header  # noqa: E402
```

- [ ] **Paso 2: escribir la prueba que falla**

```python
    def test_la_barra_de_la_consola_no_recorta_la_etiqueta(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Regresion: el resumen de la consola se recortaba a media palabra."""
        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()
        etiqueta = window.console.status_label
        assert isinstance(etiqueta, ElidedLabel)
        assert etiqueta.full_text().startswith("Consola de «Servidor supervivencia extremo»")
        assert etiqueta.text().endswith("…")  # recortada, no cortada a media palabra
        assert window.console.autoscroll.width() >= window.console.autoscroll.sizeHint().width() - 2
```

- [ ] **Paso 3: ejecutarla y comprobar que falla**

Comando: `.venv/bin/python -m pytest "tests/test_gui.py::TestPaneles::test_la_barra_de_la_consola_no_recorta_la_etiqueta" -q`
Esperado: FAIL con `AttributeError: 'PySide6.QtWidgets.QLabel' object has no attribute 'full_text'`.

- [ ] **Paso 4: implementar**

Línea 25 de `serviscraft/ui/console_panel.py`:

```python
from .common import ElidedLabel, hint_label, make_button
```

Línea 83 de `crear la barra superior`:

```python
        self.status_label = ElidedLabel("Sin servidor seleccionado")
        self.status_label.setObjectName("Hint")
```

- [ ] **Paso 5: ejecutarla y comprobar que pasa**

Comando: `.venv/bin/python -m pytest "tests/test_gui.py::TestPaneles::test_la_barra_de_la_consola_no_recorta_la_etiqueta" -q`
Esperado: PASS.

---

## Tarea 3: barrido de todas las etiquetas de la ventana

**Ficheros:**
- Test: `tests/test_gui.py` (clase `TestPaneles`)

- [ ] **Paso 1: escribir la prueba**

Esta prueba generaliza el fallo: recorre las 5 pestañas y exige que ninguna
`QLabel` visible, con texto y sin `wordWrap`, quede más estrecha que su
`sizeHint`. Debe listar exactamente los dos recortes de las tareas 1 y 2.

```python
    def test_ninguna_etiqueta_normal_se_recorta(
        self, window: MainWindow, store: ServerStore, qapp: QApplication
    ) -> None:
        """Barrido: toda QLabel visible cabe en su hueco o es una ElidedLabel."""
        from PySide6.QtWidgets import QLabel as _QLabel

        from serviscraft.ui.common import ElidedLabel as _ElidedLabel

        spec = make_spec(name="Servidor supervivencia extremo")
        store.prepare_dirs(spec.id)
        store.save(spec)
        window._on_views_ready([ServerView(spec=spec, state=ServerState.EXITED)])
        window.show()
        window.resize(window.minimumSize())
        for _ in range(10):
            qapp.processEvents()

        recortadas = []
        for indice in range(window.tabs.count()):
            window.tabs.setCurrentIndex(indice)
            for _ in range(6):
                qapp.processEvents()
            for etiqueta in window.findChildren(_QLabel):
                if not etiqueta.isVisible() or not etiqueta.text().strip():
                    continue
                if etiqueta.wordWrap() or isinstance(etiqueta, _ElidedLabel):
                    continue
                if etiqueta.width() < etiqueta.sizeHint().width() - 2:
                    recortadas.append(
                        f"[{window.tabs.tabText(indice)}] "
                        f"{etiqueta.objectName() or 'QLabel'}: {etiqueta.width()} px "
                        f"para un texto de {etiqueta.sizeHint().width()} px"
                    )
        assert not recortadas, "etiquetas recortadas:\n" + "\n".join(recortadas)
```

- [ ] **Paso 2: ejecutarla y comprobar que pasa** (las tareas 1 y 2 ya arreglaron
  los dos casos; si se ejecuta antes de ellas, debe listar exactamente esas dos
  etiquetas)

Comando: `.venv/bin/python -m pytest "tests/test_gui.py::TestPaneles::test_ninguna_etiqueta_normal_se_recorta" -q`
Esperado: PASS.

---

## Tarea 4: suite completa

- [ ] **Paso 1: ejecutar todo**

Comando: `.venv/bin/python -m pytest -q`
Esperado: 0 fallos (hoy hay 292 pruebas; con estas 3 deben ser 295).

---

## Tarea 5: reconstruir y verificar los tres paquetes

- [ ] **Paso 1: reconstruir**

Comando: `rm -rf dist && packaging/build-rpm.sh && packaging/build-deb.sh && packaging/build-appimage.sh`
Esperado: `dist/serviscraft-0.1.0-1.fc44.noarch.rpm`, `dist/serviscraft_0.1.0_all.deb`, `dist/Serviscraft-0.1.0-x86_64.AppImage`.

- [ ] **Paso 2: verificar el rpm**

Comandos: `rpm -qip dist/serviscraft-0.1.0-1.fc44.noarch.rpm` y
`rpm2cpio … | (cd /tmp/opencode/rpm-extract && cpio -idm --quiet)` y después
`PYTHONPATH=<extraido>/usr/lib/python3.14/site-packages SERVISCRAFT_HOME=/tmp/opencode/rpm-home sh <extraido>/usr/bin/serviscraft --self-test`
Esperado: "Todo listo." y salida 0.

- [ ] **Paso 3: verificar el deb**

Comandos: `ar t dist/serviscraft_0.1.0_all.deb` (orden `debian-binary`,
`control.tar.gz`, `data.tar.gz`), `ar p … control.tar.gz | tar -xzO ./control`
y el mismo `--self-test` con los datos extraídos de `data.tar.gz`.
Esperado: control correcto y "Todo listo.".

- [ ] **Paso 4: verificar el AppImage**

Comandos: `dist/Serviscraft-0.1.0-x86_64.AppImage --self-test` y una ventana
`offscreen` construida con el Python interno del AppDir, recorriendo las 5
pestañas.
Esperado: "Todo listo." con PySide6 6.12.0 y las 5 pestañas.

- [ ] **Paso 5: captura real en Wayland**

Lanzar el AppImage en la sesión real y capturar con `window.grab()` (la captura
`spectacle` de pantalla completa no mostró la ventana) para comprobar que la
cabecera y la tarjeta lateral ya no se recortan.

---

## Tarea 6: documentación

- [ ] **Paso 1: anotar la convención**

En `docs/desarrollo.md`, dentro de *Convenciones de código*, añadir:

```markdown
- Las etiquetas que muestran nombres de servidor (cabecera, tarjeta lateral,
  consola) usan `ElidedLabel`: recortan el texto con `…` y guardan el completo en
  el *tooltip*, en lugar de ensanchar la ventana. La prueba
  `test_ninguna_etiqueta_normal_se_recorta` vigila que no aparezcan etiquetas
  normales recortadas.
```

---

## Ajustes durante la ejecución

### Ajuste 1 (tarea 2): `ElidedLabel` con la etiqueta no visible

La suite completa descubrió una regresión en una prueba **existente**
(`test_la_consola_no_esta_activa_sin_servidor`): al convertir la etiqueta de la
consola en `ElidedLabel`, con la ventana sin mostrar (o la pestaña oculta) Qt da
a la etiqueta un ancho degenerado (6 px medidos) y `elidedText` devuelve cadena
vacía, así que `text()` dejaba de contener «Sin servidor».

**Arreglo aplicado en `serviscraft/ui/common.py`:**

- `_apply_elide()` solo recorta si la etiqueta está **visible** y su ancho es
  mayor que cero; si no, conserva el texto completo (el widget ya lo recorta al
  pintarse). Además, nunca deja el texto vacío si el completo no lo está.
- Se añade `showEvent()` que recalcula el recorte: al pasar a una pestaña visible
  el ancho no cambia, así que sin esto el texto se quedaría sin recortar.

**Verificación:** `pytest tests/test_gui.py::TestConsolaDelPanel tests/test_gui.py::TestPaneles` → 0 fallos.

---

## Riesgos y cómo se cubren

| Riesgo | Cobertura |
| --- | --- |
| El ancho 0 del item deja la tarjeta demasiado estrecha o sin pintar | Comprobado en aislamiento (viewport) y por la prueba de la tarea 1 |
| El recorte del título rompe la búsqueda de la barra lateral | Prueba del paso 5 de la tarea 1 + rojo forzado en el paso 6 |
| Aparecen etiquetas recortadas en pestañas no revisadas | Prueba de barrido de la tarea 3 |
| La reconstrucción de paquetes falla por el directorio de trabajo con espacios | Ya resuelto: los scripts construyen en `${XDG_CACHE_HOME}/serviscraft/build` |

## Autorevisión

- **Cobertura:** los dos recortes medidos, el desbordamiento de la tarjeta y la búsqueda están cubiertos; los paquetes y su verificación también.
- **Sin marcadores de posición:** todos los pasos llevan el código y el comando exactos.
- **Consistencia de nombres:** `ElidedLabel.full_text()`, `window.sidebar._cards`, `window.sidebar.list`, `window.sidebar.search`, `window.sidebar._items`, `window.console.status_label`, `window.console.autoscroll`.
