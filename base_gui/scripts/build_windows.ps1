# Build local en Windows:  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
# Requiere Python 3.12+, Inno Setup 6 (iscc en el PATH) y: pip install -r requirements.txt pyinstaller pillow
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$ver = (python -c "from app import __version__; print(__version__)").Trim()
python scripts\make_ico.py
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }
pyinstaller --noconfirm presupuestador.spec
iscc /DAppVersion=$ver installer\windows\presupuestador.iss
Write-Host "Instalador: dist\Presupuestador_Pro_${ver}_Setup.exe"
