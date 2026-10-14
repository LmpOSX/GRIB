# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para Windows:  pyinstaller presupuestador.spec
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
ROOT = os.path.abspath(".")

# Traducciones de Qt en español (botones Sí/No/Cancelar, diálogos de archivo)
datas = collect_data_files("PyQt6", includes=["Qt6/translations/qtbase_es.qm"])
datas += [(os.path.join(ROOT, "resources", "PresupuestadorPro.ico"), "resources"),
          (os.path.join(ROOT, "resources", "PptoDocument.ico"), "resources")]

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["openpyxl", "sqlite3"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
              "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtMultimedia"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Presupuestador Pro",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "resources", "PresupuestadorPro.ico"),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
               name="Presupuestador Pro")
