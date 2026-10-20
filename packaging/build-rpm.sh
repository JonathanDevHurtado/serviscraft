#!/usr/bin/env bash
# Construye el paquete RPM de Serviscraft. No requiere root.
#
# Uso:
#     packaging/build-rpm.sh
#
# Resultado: dist/serviscraft-<version>-<release>.noarch.rpm
# Todo el trabajo intermedio queda en packaging/build/rpm/ (ignorado por git).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

VERSION="$("$PYTHON" -c "import sys; sys.path.insert(0, '$ROOT'); from serviscraft.core import paths; print(paths.APP_VERSION)")"
NAME=serviscraft

command -v rpmbuild >/dev/null 2>&1 || {
    echo "error: falta rpmbuild. En Fedora:  sudo dnf install rpm-build" >&2
    exit 1
}

TOPDIR="${SERVISCRAFT_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/serviscraft/build}/rpm"
DIST="$ROOT/dist"
mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} "$DIST"

case "$TOPDIR" in
    *" "*) echo "error: la carpeta de construccion no puede contener espacios: $TOPDIR" >&2; exit 1 ;;
esac

echo "==> Preparando el arbol de fuentes $NAME-$VERSION"
tar -czf "$TOPDIR/SOURCES/$NAME-$VERSION.tar.gz" \
    --transform "s,^\.,$NAME-$VERSION," \
    --exclude='./.venv' \
    --exclude='./.git' \
    --exclude='./dist' \
    --exclude='./build' \
    --exclude='./packaging/build' \
    --exclude='./.pytest_cache' \
    --exclude='./.ruff_cache' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude-vcs \
    -C "$ROOT" .

echo "==> rpmbuild -bb"
rpmbuild -bb "$ROOT/packaging/rpm/$NAME.spec" \
    --define "_topdir $TOPDIR" \
    --define "_sourcedir $TOPDIR/SOURCES" \
    --define "_builddir $TOPDIR/BUILD" \
    --define "_buildrootdir $TOPDIR/BUILDROOT" \
    --define "_rpmdir $TOPDIR/RPMS" \
    --define "_specdir $TOPDIR/SPECS" \
    --define "_srcrpmdir $TOPDIR/SRPMS" \
    --define "_rpmfilename %%{NAME}-%%{VERSION}-%%{RELEASE}.%%{ARCH}.rpm"

RPM="$(ls -1 "$TOPDIR/RPMS/$NAME-$VERSION-"*.rpm 2>/dev/null | head -n1 || true)"
[ -n "$RPM" ] || { echo "error: no se genero ningun RPM" >&2; exit 1; }

cp -f "$RPM" "$DIST/"
echo
echo "==> Contenido del paquete:"
rpm -qlp "$DIST/$(basename "$RPM")" | sed 's/^/    /'
echo
echo "OK: $DIST/$(basename "$RPM")"
