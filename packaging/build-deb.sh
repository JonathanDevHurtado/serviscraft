#!/usr/bin/env bash
# Construye el paquete .deb de Serviscraft sin depender de dpkg-deb.
#
# Uso:
#     packaging/build-deb.sh
#
# Resultado: dist/serviscraft_<version>_all.deb
#
# Se usan `ar` y `tar` (GNU) directamente, que es exactamente lo que hace
# `dpkg-deb` por dentro: un archivo `ar` con tres miembros en orden
# (debian-binary, control.tar.gz, data.tar.gz).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERSION="$("$PYTHON" -c "import sys; sys.path.insert(0, '$ROOT'); from serviscraft.core import paths; print(paths.APP_VERSION)")"
NAME=serviscraft
ARCH=all

for tool in ar tar gzip; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "error: falta '$tool'." >&2
        exit 1
    }
done

BUILD="${SERVISCRAFT_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/serviscraft/build}/deb"
STAGE="$BUILD/${NAME}_${VERSION}_${ARCH}"
DIST="$ROOT/dist"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$DIST"

echo "==> Copiando los datos del paquete"
PYDIR="$STAGE/usr/lib/python3/dist-packages"
mkdir -p "$PYDIR"
cp -a "$ROOT/serviscraft" "$PYDIR/"
find "$PYDIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$PYDIR" -name '*.py[co]' -delete
"$PYTHON" -m compileall -q "$PYDIR/serviscraft" >/dev/null

install -Dpm0755 "$ROOT/scripts/serviscraft" "$STAGE/usr/bin/serviscraft"
install -Dpm0644 "$ROOT/packaging/serviscraft.desktop" \
    "$STAGE/usr/share/applications/serviscraft.desktop"
install -Dpm0644 "$ROOT/serviscraft/resources/icons/serviscraft.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/serviscraft.svg"

DOCDIR="$STAGE/usr/share/doc/$NAME"
install -Dpm0644 "$ROOT/README.md" "$DOCDIR/README.md"
install -Dpm0644 "$ROOT/TERCEROS.md" "$DOCDIR/TERCEROS.md"
install -Dpm0644 "$ROOT/CHANGELOG.md" "$DOCDIR/CHANGELOG.md"
cp -a "$ROOT/docs" "$DOCDIR/docs"
install -Dpm0644 "$ROOT/LICENSE" "$DOCDIR/copyright"

# Registro de cambios del paquete (Debian exige changelog.Debian.gz).
{
    printf '%s (%s) unstable; urgency=medium\n\n' "$NAME" "$VERSION"
    printf '  * Serviscraft %s: pestanas Mods, Registros y Unirse, busqueda de\n' "$VERSION"
    printf '    modpacks con filtros, ajustes por secciones y deteccion de mods que\n'
    printf '    faltan con enlace a Modrinth y copia dentro del servidor.\n\n'
    printf ' -- Jonathan Hurtado <JonathanHurtadoDev@proton.me>  %s\n' "$(date -R)"
} | gzip -9n > "$DOCDIR/changelog.Debian.gz"

echo "==> Generando DEBIAN/control"
SIZE_KB="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" \
    -e "s/@INSTALLED_SIZE@/$SIZE_KB/" \
    "$ROOT/packaging/deb/control.in" > "$STAGE/DEBIAN/control"
install -pm0755 "$ROOT/packaging/deb/postinst" "$STAGE/DEBIAN/postinst"

echo "==> Generando la lista de sumas de comprobacion (md5sums)"
(
    cd "$STAGE"
    find . -type f ! -path './DEBIAN/*' -printf '%P\0' | sort -z | xargs -0 -r md5sum
) > "$STAGE/DEBIAN/md5sums"

echo "==> Empaquetando"
printf '2.0\n' > "$BUILD/debian-binary"
(
    cd "$STAGE/DEBIAN"
    tar --owner=0 --group=0 --numeric-owner -cf - .
) | gzip -9n > "$BUILD/control.tar.gz"
(
    cd "$STAGE"
    tar --owner=0 --group=0 --numeric-owner --exclude=./DEBIAN -cf - .
) | gzip -9n > "$BUILD/data.tar.gz"

DEB="$DIST/${NAME}_${VERSION}_${ARCH}.deb"
rm -f "$DEB"
ar rc "$DEB" "$BUILD/debian-binary" "$BUILD/control.tar.gz" "$BUILD/data.tar.gz"

echo "==> Comprobaciones"
ar t "$DEB" | sed 's/^/    miembro: /'
ar p "$DEB" control.tar.gz | tar -tzf - | sed 's/^/    control: /'
ar p "$DEB" data.tar.gz | tar -tzf - | sed 's/^/    dato:    /'
echo
echo "OK: $DEB"
