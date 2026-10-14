"""
py2app para Visor GRIB.

Uso:
    pip install py2app
    python setup.py py2app
(o scripts/build.sh, que además genera los iconos y el DMG)
"""
from setuptools import setup
from app import __version__ as VERSION

APP = ["main.py"]
APP_NAME = "Visor GRIB"
BUNDLE_ID = "com.visorgrib.app"
GRIB_EXTENSIONS = ["grib2", "grb2", "grib", "grb"]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "resources/VisorGRIB.icns",
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "NSHumanReadableCopyright": "© 2026 Visor GRIB",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        # ── Asociación de archivos GRIB ──
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Archivo GRIB",
                "CFBundleTypeRole": "Viewer",
                "CFBundleTypeIconFile": "GribDocument.icns",
                "CFBundleTypeExtensions": GRIB_EXTENSIONS,
                "LSItemContentTypes": ["com.visorgrib.grib"],
                "LSHandlerRank": "Alternate",
            },
        ],
        "UTExportedTypeDeclarations": [
            {
                "UTTypeIdentifier": "com.visorgrib.grib",
                "UTTypeDescription": "Archivo GRIB",
                "UTTypeIconFile": "GribDocument.icns",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": GRIB_EXTENSIONS,
                    "public.mime-type": "application/x-grib",
                },
            }
        ],
    },
    "packages": ["app", "numpy", "matplotlib", "eccodes", "cartopy", "shapely",
                 "pyproj", "certifi"],
    "includes": [
        "PyQt6",
        "PyQt6.QtWidgets",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "matplotlib.backends.backend_qtagg",
    ],
    "excludes": ["tkinter", "PyQt5", "PySide6"],
    "frameworks": [],
    "resources": [
        "resources/VisorGRIB.icns",
        "resources/GribDocument.icns",
        "resources/check.svg",
        "resources/radio_dot.svg",
    ],
}

setup(
    name=APP_NAME,
    app=APP,
    version=VERSION,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
