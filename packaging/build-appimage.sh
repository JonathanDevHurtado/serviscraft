#!/usr/bin/env bash
# Construye un AppImage autonomo de Serviscraft.
#
# Uso:
#     packaging/build-appimage.sh
#
# Resultado: dist/Serviscraft-<version>-x86_64.AppImage
#
# El AppImage empaqueta su propio interprete de Python (python-build-standalone)
# y PySide6 (rueda manylinux autocontenida, con las bibliotecas de Qt dentro),
# de modo que no depende del Python ni del PySide6 del sistema.
#
# Podman sigue siendo una dependencia EXTERNA y obligatoria del sistema: el
# AppImage no lo incluye ni lo instala, y solo lo usa en modo rootless.
#
# Requisitos en la maquina donde se ejecute: Linux x86_64 con glibc >= 2.34
# (Fedora 35+, Debian 12+, Ubuntu 22.04+) y las bibliotecas graficas habituales
# de un escritorio (OpenGL, xkbcommon, fontconfig...).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERSION="$("$PYTHON" -c "import sys; sys.path.insert(0, '$ROOT'); from serviscraft.core import paths; print(paths.APP_VERSION)")"
NAME=serviscraft

# --- Versiones fijadas del entorno empaquetado ------------------------------
PBS_VERSION="${PBS_VERSION:-3.12.15}"
PBS_TAG="${PBS_TAG:-20261013}"
PBS_ARCH="x86_64-unknown-linux-gnu"
PBS_ASSET="cpython-${PBS_VERSION}+${PBS_TAG}-${PBS_ARCH}-install_only.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_ASSET}"
PYSIDE_VERSION="${PYSIDE_VERSION:-6.12.0}"

BUILD_ROOT="${SERVISCRAFT_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/serviscraft/build}"
BUILD="$BUILD_ROOT/appimage"
CACHE="$BUILD_ROOT/cache"
APPDIR="$BUILD/Serviscraft.AppDir"
DIST="$ROOT/dist"
mkdir -p "$CACHE" "$DIST"

case "$APPDIR" in
    *" "*) echo "error: la carpeta de construccion no puede contener espacios: $APPDIR" >&2; exit 1 ;;
esac

command -v appimagetool >/dev/null 2>&1 || {
    echo "error: falta appimagetool." >&2
    echo "Descargalo en https://github.com/AppImage/appimagetool/releases y ponlo en el PATH." >&2
    exit 1
}

# ------------------------------------------------------------- Python portatil
PYTAR="$CACHE/$PBS_ASSET"
if [ ! -f "$PYTAR" ]; then
    echo "==> Descargando Python portatil ($PBS_VERSION)"
    echo "    $PBS_URL"
    if command -v curl >/dev/null 2>&1; then
        curl -fSL --retry 3 -o "$PYTAR.part" "$PBS_URL"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$PYTAR.part" "$PBS_URL"
    else
        echo "error: se necesita curl o wget para descargar Python." >&2
        exit 1
    fi
    mv "$PYTAR.part" "$PYTAR"
else
    echo "==> Usando el Python portatil en cache: $PYTAR"
fi

echo "==> Preparando el AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"
tar -xzf "$PYTAR" -C "$APPDIR/usr"

PYBIN="$APPDIR/usr/python/bin/python3"
[ -x "$PYBIN" ] || { echo "error: no se encontro $PYBIN" >&2; exit 1; }

# ------------------------------------------------------------------ PySide6
echo "==> Instalando PySide6 $PYSIDE_VERSION en el Python portatil"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_CACHE_DIR=1
"$PYBIN" -m pip --version >/dev/null 2>&1 || "$PYBIN" -m ensurepip --upgrade >/dev/null
"$PYBIN" -m pip install \
    --no-warn-script-location \
    --only-binary=:all: \
    "PySide6-Essentials==${PYSIDE_VERSION}" \
    "shiboken6==${PYSIDE_VERSION}"

# ------------------------------------------------------------------- Serviscraft
SITE="$("$PYBIN" -c 'import site; print(site.getsitepackages()[0])')"
echo "==> Copiando Serviscraft en $SITE"
cp -a "$ROOT/serviscraft" "$SITE/"
find "$SITE/serviscraft" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$SITE/serviscraft" -name '*.py[co]' -delete
"$PYBIN" -m compileall -q "$SITE/serviscraft" >/dev/null

# ------------------------------------------------------------------ integracion
install -Dpm0755 "$ROOT/scripts/serviscraft" "$APPDIR/usr/bin/serviscraft"
install -Dpm0644 "$ROOT/packaging/serviscraft.desktop" \
    "$APPDIR/usr/share/applications/serviscraft.desktop"
install -Dpm0644 "$ROOT/serviscraft/resources/icons/serviscraft.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/serviscraft.svg"
# Licencia y avisos de terceros dentro del AppImage.
install -Dpm0644 "$ROOT/LICENSE" "$APPDIR/usr/share/doc/serviscraft/LICENSE"
install -Dpm0644 "$ROOT/TERCEROS.md" "$APPDIR/usr/share/doc/serviscraft/TERCEROS.md"
install -Dpm0644 "$ROOT/CHANGELOG.md" "$APPDIR/usr/share/doc/serviscraft/CHANGELOG.md"
install -Dpm0644 "$ROOT/README.md" "$APPDIR/usr/share/doc/serviscraft/README.md"
# appimagetool exige el .desktop y el icono tambien en la raiz del AppDir.
install -pm0644 "$ROOT/packaging/serviscraft.desktop" "$APPDIR/$NAME.desktop"
install -pm0644 "$ROOT/serviscraft/resources/icons/serviscraft.svg" "$APPDIR/$NAME.svg"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Punto de entrada del AppImage.
HERE="$(dirname "$(readlink -f "$0")")"

# Nunca usar un motor Podman remoto: la API no se expone por TCP.
unset CONTAINER_HOST DOCKER_HOST CONTAINER_CONNECTION 2>/dev/null || true

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
PATH="$HERE/usr/python/bin:$PATH"
export PATH

exec "$HERE/usr/python/bin/python3" -s -m serviscraft "$@"
APPRUN
chmod 0755 "$APPDIR/AppRun"

# --------------------------------------------------------------------- empaquetar
echo "==> Generando el AppImage"
OUT="$DIST/Serviscraft-$VERSION-x86_64.AppImage"
rm -f "$OUT"
export ARCH=x86_64
# Nota: no se define SOURCE_DATE_EPOCH. appimagetool pasa sus propias marcas de
# tiempo a mksquashfs y ambas opciones son incompatibles (falla la compresion).
unset SOURCE_DATE_EPOCH
appimagetool --no-appstream "$APPDIR" "$OUT"

echo
echo "==> Comprobacion rapida (--self-test dentro del AppImage)"
"$OUT" --self-test || echo "aviso: --self-test devolvio un codigo distinto de 0"
echo
echo "OK: $OUT  ($(du -h "$OUT" | cut -f1))"
