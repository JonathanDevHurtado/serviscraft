# Instalación

## 1. Requisitos

| Componente | Mínimo | Notas |
| --- | --- | --- |
| Sistema | Linux con KDE Plasma (o escritorio Qt) | X11 o Wayland |
| Podman | 4.x | **Rootless**, sin `sudo`. Serviscraft lo comprueba al arrancar. |
| Python | 3.10 | El AppImage incluye el suyo propio. |
| PySide6 | 6.6 | En Fedora: `python3-pyside6`. |

Instala las dependencias del sistema en Fedora:

```bash
sudo dnf install podman python3-pyside6
```

Comprueba que todo está en su sitio:

```bash
serviscraft --self-test
# o, desde el código fuente:
make self-test
```

La orden devuelve `0` si todo está bien. Otros códigos:

| Código | Significado |
| --- | --- |
| `2` | PySide6 no está instalado. |
| `3` | Podman no está instalado o no responde. |
| `4` | Podman funciona, pero **no** en modo rootless. |

> Serviscraft **no** arranca si Podman no está en modo rootless. Es una decisión
> deliberada: la aplicación nunca se ejecuta con privilegios.

## 2. Instalación desde paquetes

### Fedora / RHEL (RPM)

```bash
make rpm
sudo dnf install dist/serviscraft-0.3.0-1.fc44.noarch.rpm
```

El paquete instala:

- `/usr/bin/serviscraft` — lanzador.
- `/usr/lib/python3.X/site-packages/serviscraft/` — el código.
- `/usr/share/applications/serviscraft.desktop` — entrada del menú.
- `/usr/share/icons/hicolor/scalable/apps/serviscraft.svg` — icono.
- `/usr/share/licenses/serviscraft/LICENSE` y `/usr/share/doc/serviscraft/`.

Dependencias declaradas: `python3-pyside6` y `podman`.

### Debian / Ubuntu (.deb)

```bash
make deb
sudo apt install ./dist/serviscraft_0.3.0_all.deb
```

El `.deb` se construye con `ar` + `tar` (no necesita `dpkg-deb`), pero se instala
con normalidad mediante `apt` o `dpkg`. Instala el código en
`/usr/lib/python3/dist-packages/` y declara las dependencias
`python3-pyside6.qtcore`, `.qtgui`, `.qtwidgets` y `podman`.

### AppImage (portable)

```bash
make appimage
chmod +x dist/Serviscraft-0.3.0-x86_64.AppImage
./dist/Serviscraft-0.3.0-x86_64.AppImage
```

El AppImage es autocontenido: incluye su propio intérprete de Python
(*python-build-standalone*) y PySide6 con las bibliotecas de Qt dentro.

- **Podman sigue siendo externo**: el AppImage no lo incluye ni lo instala.
- Requiere Linux x86_64 con glibc ≥ 2.34 (Fedora 35+, Debian 12+, Ubuntu 22.04+).
- Requiere las bibliotecas gráficas habituales del escritorio (OpenGL,
  xkbcommon, fontconfig…), presentes en cualquier KDE/Plasma moderno.

Para una integración opcional en el menú, instala `appimaged` o copia el
`.desktop` que el AppImage extrae.

### Instalación para tu usuario (sin root)

Ideal para desarrollo o si prefieres no tocar el sistema:

```bash
make venv             # una vez: crea .venv
make install-user     # ~/.local/bin/serviscraft + ~/.local/share/applications/…
make uninstall-user
```

Asegúrate de que `~/.local/bin` está en tu `PATH`.

El lanzador ejecuta el código de **esa misma carpeta** (con su `.venv`), así que
sirve para probar cambios al momento: si mueves o borras el proyecto, deja de
funcionar. Para una instalación fija, usa el RPM, el `.deb` o el AppImage.

## 3. Instalación desde el código fuente

```bash
git clone <repositorio> serviscraft
cd serviscraft
make venv     # crea .venv (reutiliza el PySide6 del sistema)
make run      # inicia la aplicación
```

`make venv` usa `--system-site-packages` para reutilizar el PySide6 del sistema
y solo instala las herramientas de pruebas. Si prefieres un entorno aislado:

```bash
python3 -m venv .venv
.venv/bin/pip install "PySide6>=6.6" "pytest>=7" "pytest-qt>=4.2"
.venv/bin/python -m serviscraft
```

## 4. Dónde se guardan los datos

| Qué | Ruta |
| --- | --- |
| Datos, mundos y copias | `~/.local/share/serviscraft/` |
| Definición de cada servidor | `~/.local/share/serviscraft/servers/<id>/meta.json` |
| Mundo y archivos del servidor | `~/.local/share/serviscraft/servers/<id>/data/` |
| Copias de seguridad | `~/.local/share/serviscraft/servers/<id>/backups/` |
| Registro de la aplicación | `~/.local/share/serviscraft/logs/serviscraft.log` |
| Configuración | `~/.config/serviscraft/config.json` |
| Caché (iconos de proyectos) | `~/.cache/serviscraft/` |

Se respeta la especificación XDG, así que `XDG_DATA_HOME`, `XDG_CONFIG_HOME` y
`XDG_CACHE_HOME` se tienen en cuenta. Además:

- `SERVISCRAFT_HOME` fuerza la raíz de datos (útil para pruebas).
- `SERVISCRAFT_CONFIG_HOME` fuerza la carpeta de configuración.
- `serviscraft --data-dir /ruta` equivale a definir `SERVISCRAFT_HOME`.

## 5. Desinstalación

- **RPM**: `sudo dnf remove serviscraft`.
- **DEB**: `sudo apt remove serviscraft`.
- **AppImage**: borra el archivo.
- **Usuario**: `make uninstall-user`.

Los datos **nunca** se borran al desinstalar. Si quieres eliminarlos:

```bash
rm -rf ~/.local/share/serviscraft ~/.config/serviscraft
```

> Antes de borrar a mano, detén los servidores y elimina sus contenedores con
> `podman rm -f serviscraft-<id>`. Serviscraft los detecta y te avisa al abrir.
