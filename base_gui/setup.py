"""
py2app setup for Presupuestador Pro.

Usage:
    pip install py2app
    python setup.py py2app
"""
from setuptools import setup
from app import __version__ as VERSION

APP = ["main.py"]
APP_NAME = "Presupuestador Pro"
BUNDLE_ID = "com.presupuestadorpro.app"

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "resources/PresupuestadorPro.icns",
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "NSHumanReadableCopyright": "© 2026 Presupuestador Pro",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        # ── File type association: .ppto ──
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Presupuesto",
                "CFBundleTypeRole": "Editor",
                "CFBundleTypeIconFile": "PptoDocument.icns",
                "CFBundleTypeExtensions": ["ppto"],
                "LSItemContentTypes": ["com.presupuestadorpro.ppto"],
                "LSHandlerRank": "Owner",
            },
            {
                "CFBundleTypeName": "Archivo XML",
                "CFBundleTypeRole": "Editor",
                "CFBundleTypeExtensions": ["xml"],
                "LSHandlerRank": "Alternate",
            },
        ],
        # ── Declare the UTI for .ppto ──
        "UTExportedTypeDeclarations": [
            {
                "UTTypeIdentifier": "com.presupuestadorpro.ppto",
                "UTTypeDescription": "Presupuesto",
                "UTTypeIconFile": "PptoDocument.icns",
                "UTTypeConformsTo": ["public.xml", "public.data"],
                "UTTypeTagSpecification": {
                    "public.filename-extension": ["ppto"],
                    "public.mime-type": "application/x-presupuesto",
                },
            }
        ],
    },
    "packages": ["app"],
    "includes": [
        "PyQt6",
        "PyQt6.QtWidgets",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "openpyxl",
    ],
    "frameworks": [],
    "resources": [
        "resources/PresupuestadorPro.icns",
        "resources/PptoDocument.icns",
    ],
}

setup(
    name=APP_NAME,
    app=APP,
    version=VERSION,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
