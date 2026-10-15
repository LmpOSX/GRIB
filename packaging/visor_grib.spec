# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller de Visor GRIB, común a macOS, Linux y Windows.

    pyinstaller --noconfirm --clean packaging/visor_grib.spec

Genera `dist/VisorGRIB/` (carpeta con el ejecutable y sus bibliotecas) y, en
macOS, además `dist/Visor GRIB.app`. Los scripts `scripts/build.sh`,
`scripts/build_linux.sh` y `scripts/build_windows.ps1` lo invocan y arman
el instalador de cada sistema (DMG, .deb/AppImage/tar.gz, Setup.exe/zip).
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
sys.path.insert(0, ROOT)
from app import __version__ as VERSION  # noqa: E402

APP_NAME = "Visor GRIB"
EXE_NAME = "VisorGRIB"
BUNDLE_ID = "com.visorgrib.app"
GRIB_EXTENSIONS = ["grib2", "grb2", "grib", "grb"]
RES = os.path.join(ROOT, "resources")

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

# Recursos propios: el código los resuelve como `<raíz>/resources/...`
# relativo al paquete `app`, y en el paquete congelado esa raíz es
# `sys._MEIPASS`, por eso van al destino `resources/`.
datas = [
    (os.path.join(RES, "check.svg"), "resources"),
    (os.path.join(RES, "radio_dot.svg"), "resources"),
    (os.path.join(RES, "app_icon.png"), "resources"),
    (os.path.join(RES, "fir"), os.path.join("resources", "fir")),
]
if IS_MAC:
    # Icono de documento del Info.plist: va dentro del paquete ANTES de que
    # PyInstaller lo firme (copiarlo después rompe el sello de la firma y
    # macOS dice que la app "está dañada")
    datas.append((os.path.join(RES, "GribDocument.icns"), "."))
# cartopy: siteconfig y datos pequeños (las costas de Natural Earth se bajan
# al usarlas, igual que en modo desarrollo)
datas += collect_data_files("cartopy", excludes=["**/tests/**"])

hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "PyQt6.QtSvg",                 # tilde y punto de los controles (SVG)
    # keyring descubre sus backends por metadatos; se incluyen explícitamente
    "keyring.backends.chainer", "keyring.backends.fail", "keyring.backends.null",
    "keyring.backends.macOS", "keyring.backends.Windows",
    "keyring.backends.SecretService", "keyring.backends.kwallet",
    # fuentes de datos
    "ecmwf.opendata", "multiurl", "paramiko", "netCDF4", "cftime", "findlibs",
    "eccodes", "gribapi", "eccodeslib",
] + collect_submodules("app")

excludes = [
    "tkinter", "_tkinter", "PyQt5", "PySide2", "PySide6",
    "IPython", "jupyter", "pytest", "py2app", "setuptools._distutils",
    # Módulos de Qt que el visor no usa (evita arrastrar plugins pesados)
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
    "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtQuickWidgets",
    "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets", "PyQt6.Qt3DCore",
    "PyQt6.Qt3DRender", "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtPositioning",
    "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtCharts", "PyQt6.QtDataVisualization",
    "PyQt6.QtPdf", "PyQt6.QtPdfWidgets", "PyQt6.QtRemoteObjects", "PyQt6.QtTextToSpeech",
    "PyQt6.QtSpatialAudio", "PyQt6.QtGraphs", "PyQt6.QtGraphsWidgets",
    "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtSql", "PyQt6.QtTest",
]

if IS_MAC:
    icon = os.path.join(RES, "VisorGRIB.icns")
elif IS_WIN:
    icon = os.path.join(RES, "VisorGRIB.ico")
else:
    icon = None

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=EXE_NAME,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleVersion": VERSION,
            "CFBundleShortVersionString": VERSION,
            "NSHumanReadableCopyright": "© 2026 Visor GRIB",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "12.0",
            # Asociación de archivos GRIB (doble clic en el Finder → FileOpen)
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Archivo GRIB",
                "CFBundleTypeRole": "Viewer",
                "CFBundleTypeIconFile": "GribDocument.icns",
                "CFBundleTypeExtensions": GRIB_EXTENSIONS,
                "LSItemContentTypes": ["com.visorgrib.grib"],
                "LSHandlerRank": "Alternate",
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "com.visorgrib.grib",
                "UTTypeDescription": "Archivo GRIB",
                "UTTypeIconFile": "GribDocument.icns",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": GRIB_EXTENSIONS,
                    "public.mime-type": "application/x-grib",
                },
            }],
        },
    )
