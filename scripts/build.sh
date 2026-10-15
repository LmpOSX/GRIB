#!/bin/bash
# Construye "Visor GRIB.app" con PyInstaller y el instalador DMG (macOS).
#   scripts/build.sh            → dist/Visor GRIB.app  y  dist/Visor_GRIB_<ver>_macOS_<arch>.dmg
set -e

cd "$(dirname "$0")/.."
APP_NAME="Visor GRIB"
EXE_NAME="VisorGRIB"
VERSION=$(python -c "from app import __version__; print(__version__)")
ARCH=$(uname -m)

echo "=== Visor GRIB $VERSION (macOS $ARCH) ==="
echo "=== Generando iconos ==="
python scripts/make_icon.py

echo "=== Limpiando builds anteriores ==="
rm -rf build dist

echo "=== Construyendo aplicación (PyInstaller) ==="
pyinstaller --noconfirm --clean packaging/visor_grib.spec

APP_PATH="dist/${APP_NAME}.app"
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: No se generó la aplicación"
    exit 1
fi
rm -rf "dist/${EXE_NAME}"     # la carpeta suelta; en macOS se distribuye el .app
cp resources/GribDocument.icns "$APP_PATH/Contents/Resources/"

echo "=== Prueba de humo: abrir un GRIB WAFS dentro del paquete ==="
SMOKE_DIR=$(mktemp -d)
cp tests/data/WAFS_like_test.grib2 "$SMOKE_DIR/"
VISOR_GRIB_SMOKE=8 QT_QPA_PLATFORM=offscreen \
    "$APP_PATH/Contents/MacOS/${EXE_NAME}" "$SMOKE_DIR/WAFS_like_test.grib2"
rm -rf "$SMOKE_DIR"

echo "=== Creando instalador DMG ==="
DMG_NAME="Visor_GRIB_${VERSION}_macOS_${ARCH}"
DMG_PATH="dist/${DMG_NAME}.dmg"
DMG_TMP="dist/${DMG_NAME}_tmp.dmg"

SIZE_MB=$(du -sm "$APP_PATH" | awk '{print int($1 * 1.3 + 30)}')
hdiutil create -size "${SIZE_MB}m" -fs HFS+ -volname "$APP_NAME" "$DMG_TMP"
MOUNT_DIR=$(hdiutil attach "$DMG_TMP" | grep "/Volumes" | awk -F'\t' '{print $NF}')
cp -R "$APP_PATH" "$MOUNT_DIR/"
ln -s /Applications "$MOUNT_DIR/Applications"

# Disposición de la ventana del instalador (requiere Finder: se omite en CI)
if [ -z "$CI" ]; then
osascript <<APPLESCRIPT || true
tell application "Finder"
    tell disk "$APP_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {200, 120, 720, 400}
        set viewOptions to the icon view options of container window
        set icon size of viewOptions to 80
        set arrangement of viewOptions to not arranged
        set position of item "${APP_NAME}.app" of container window to {140, 140}
        set position of item "Applications" of container window to {380, 140}
        close
    end tell
end tell
APPLESCRIPT
fi

sync
hdiutil detach "$MOUNT_DIR"
hdiutil convert "$DMG_TMP" -format UDZO -o "$DMG_PATH"
rm -f "$DMG_TMP"

echo ""
echo "=== Build completado ==="
echo "  App:        $APP_PATH"
echo "  Instalador: $DMG_PATH"
echo ""
echo "Para instalar: abrir el DMG y arrastrar a Aplicaciones. La app no está"
echo "firmada con certificado de Apple: la primera vez, clic derecho ▸ Abrir"
echo "(o: xattr -cr \"/Applications/${APP_NAME}.app\")."
