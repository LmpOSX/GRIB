#!/bin/bash
# Construye "Visor GRIB.app" y el instalador DMG (macOS).
set -e

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP_NAME="Visor GRIB"

echo "=== Generando iconos ==="
python scripts/make_icon.py

echo "=== Instalando dependencias de build ==="
pip install py2app >/dev/null 2>&1 || pip install py2app

echo "=== Limpiando builds anteriores ==="
rm -rf build dist

echo "=== Construyendo aplicación ==="
python setup.py py2app 2>&1

APP_PATH="dist/${APP_NAME}.app"
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: No se generó la aplicación"
    exit 1
fi

echo "=== Aplicación creada en: $APP_PATH ==="

# Instalador DMG
echo "=== Creando instalador DMG ==="
VERSION=$(python -c "from app import __version__; print(__version__)")
DMG_NAME="Visor_GRIB_${VERSION}"
DMG_PATH="dist/${DMG_NAME}.dmg"
DMG_TMP="dist/${DMG_NAME}_tmp.dmg"

# DMG temporal
SIZE_MB=$(du -sm "$APP_PATH" | awk '{print int($1 * 1.5 + 20)}')
hdiutil create -size "${SIZE_MB}m" -fs HFS+ -volname "$APP_NAME" "$DMG_TMP"

# Montar, copiar la app y agregar el enlace a Aplicaciones
MOUNT_DIR=$(hdiutil attach "$DMG_TMP" | grep "/Volumes" | awk -F'\t' '{print $NF}')
cp -R "$APP_PATH" "$MOUNT_DIR/"
ln -s /Applications "$MOUNT_DIR/Applications"

# Disposición de la ventana del instalador
osascript <<APPLESCRIPT
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

# Desmontar
hdiutil detach "$MOUNT_DIR"

# Convertir a DMG comprimido
hdiutil convert "$DMG_TMP" -format UDZO -o "$DMG_PATH"
rm -f "$DMG_TMP"

echo ""
echo "=== Build completado ==="
echo "  App:        $APP_PATH"
echo "  Instalador: $DMG_PATH"
echo ""
echo "Para instalar: abrir el DMG y arrastrar a Aplicaciones."
echo "Las extensiones .grib2 / .grb2 / .grib / .grb quedan asociadas al visor."
