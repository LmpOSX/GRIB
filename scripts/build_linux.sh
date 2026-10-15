#!/bin/bash
# Construye Visor GRIB para Linux con PyInstaller y arma los instaladores:
#   dist/Visor_GRIB_<ver>_Linux_<arch>.tar.gz   carpeta portable
#   dist/Visor_GRIB_<ver>_Linux_<arch>.deb      paquete Debian/Ubuntu
#   dist/Visor_GRIB_<ver>_Linux_<arch>.AppImage (si se puede bajar appimagetool)
set -e

cd "$(dirname "$0")/.."
APP_NAME="Visor GRIB"
EXE_NAME="VisorGRIB"
PKG="visor-grib"
VERSION=$(python -c "from app import __version__; print(__version__)")
ARCH=$(uname -m)
case "$ARCH" in
    x86_64) DEB_ARCH=amd64 ;;
    aarch64) DEB_ARCH=arm64 ;;
    *) DEB_ARCH="$ARCH" ;;
esac
BASE="Visor_GRIB_${VERSION}_Linux_${ARCH}"

echo "=== Visor GRIB $VERSION (Linux $ARCH) ==="
echo "=== Generando iconos ==="
python scripts/make_icon.py

echo "=== Limpiando builds anteriores ==="
rm -rf build dist

echo "=== Construyendo aplicación (PyInstaller) ==="
pyinstaller --noconfirm --clean packaging/visor_grib.spec
APP_DIR="dist/${EXE_NAME}"
[ -x "$APP_DIR/${EXE_NAME}" ] || { echo "ERROR: No se generó la aplicación"; exit 1; }

echo "=== Prueba de humo: abrir un GRIB WAFS dentro del paquete ==="
SMOKE_DIR=$(mktemp -d)
cp tests/data/WAFS_like_test.grib2 "$SMOKE_DIR/"
VISOR_GRIB_SMOKE=8 QT_QPA_PLATFORM=offscreen "$APP_DIR/${EXE_NAME}" "$SMOKE_DIR/WAFS_like_test.grib2"
rm -rf "$SMOKE_DIR"

echo "=== tar.gz portable ==="
tar -C dist -czf "dist/${BASE}.tar.gz" "${EXE_NAME}"

echo "=== Paquete .deb ==="
STAGE="build/deb"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/${PKG}" "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" "$STAGE/usr/share/mime/packages" \
         "$STAGE/usr/share/icons/hicolor/256x256/apps" "$STAGE/usr/share/doc/${PKG}"
cp -a "$APP_DIR/." "$STAGE/opt/${PKG}/"
ln -s "/opt/${PKG}/${EXE_NAME}" "$STAGE/usr/bin/${PKG}"
cp packaging/visor-grib.desktop "$STAGE/usr/share/applications/${PKG}.desktop"
cp packaging/visor-grib-mime.xml "$STAGE/usr/share/mime/packages/${PKG}.xml"
cp resources/app_icon_256.png "$STAGE/usr/share/icons/hicolor/256x256/apps/${PKG}.png"
cp README.md "$STAGE/usr/share/doc/${PKG}/"
SIZE_KB=$(du -sk "$STAGE/opt" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: ${PKG}
Version: ${VERSION}
Section: science
Priority: optional
Architecture: ${DEB_ARCH}
Installed-Size: ${SIZE_KB}
Depends: libc6, libgl1, libegl1, libglib2.0-0, libxkbcommon0, libxkbcommon-x11-0, libfontconfig1, libdbus-1-3, libxcb-cursor0
Maintainer: Visor GRIB <lmepequeno@gmail.com>
Homepage: https://github.com/LmpOSX/GRIB
Description: Visor de viento y temperatura en altura a partir de GRIB2
 Visualiza viento y temperatura por nivel de vuelo (FL) de GFS, WAFS,
 ECMWF, ICON y SMN en formato WAFS; límites de FIR y áreas de descarga.
CONTROL
cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
command -v update-mime-database >/dev/null 2>&1 && update-mime-database /usr/share/mime || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
exit 0
POSTINST
cp "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
dpkg-deb --build --root-owner-group "$STAGE" "dist/${BASE}.deb"

echo "=== AppImage ==="
TOOL="build/appimagetool-${ARCH}.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage" \
        && chmod +x "$TOOL" || echo "AVISO: no se pudo bajar appimagetool; se omite el AppImage"
fi
if [ -x "$TOOL" ]; then
    APPDIR="build/AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
             "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    cp -a "$APP_DIR/." "$APPDIR/usr/bin/"
    cp packaging/visor-grib.desktop "$APPDIR/${PKG}.desktop"
    cp packaging/visor-grib.desktop "$APPDIR/usr/share/applications/${PKG}.desktop"
    cp resources/app_icon_256.png "$APPDIR/${PKG}.png"
    cp resources/app_icon_256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/${PKG}.png"
    cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/VisorGRIB" "$@"
APPRUN
    chmod +x "$APPDIR/AppRun"
    ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/${BASE}.AppImage" \
        || echo "AVISO: falló appimagetool; se omite el AppImage"
fi

echo ""
echo "=== Build completado ==="
ls -la dist/Visor_GRIB_*
echo ""
echo "Instalar el .deb:  sudo apt install ./dist/${BASE}.deb   (comando: ${PKG})"
echo "AppImage:          chmod +x ${BASE}.AppImage && ./${BASE}.AppImage"
